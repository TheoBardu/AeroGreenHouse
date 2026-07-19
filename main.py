'''
Interfaccia a riga di comando per AeroGreenHouse.

Espone via shell interattiva le stesse funzioni di gui.py, cosi' da poter
pilotare la serra via SSH senza display. I job girano in thread di questo
processo (esattamente come nella GUI): per questo la CLI e' una shell
persistente e non un comando one-shot, altrimenti i job morirebbero
all'uscita del processo.

Tutta la logica di dominio vive nei manager (managers_classes/): qui c'e'
solo parsing dei comandi e stampa, come in gui.py.

Comandi (il '-' iniziale e' opzionale: '-job active' == 'job active'):

    -job list                    elenco dei job configurati
    -job active                  job attualmente attivi
    -job activate <nome>         attiva il job
    -job deactivate <nome>       disattiva il job

    -measure th [now|stop]       temperatura, umidita', VPD
    -measure water [now|stop]    livello del serbatoio

    -camera [start|stop|now]     acquisizione periodica delle foto
    -camera preview [on|off]     anteprima dal vivo (richiede un display)

    -daily [start|stop|now]      elaborazione giornaliera T/H/VPD
    -daily stats                 statistiche dell'ultima elaborazione

    -details                     riepilogo generale (scheda "Riepilogo")

    -save list                   dump della configurazione
    -save get <chiave>           es. save get tank.trig_pin
    -save set <chiave> <valore>  es. save set gpio_pins.0.interval 900
    -save write                  scrive le modifiche su config.yaml

    help                         questo elenco
    exit | quit                  cleanup delle GPIO e uscita
'''

import shlex
import sys
from datetime import datetime

import yaml

from helper_aeroGreenHouse import aeroHelper


# Formato dei timestamp scritti dai manager (vedi ambient/tank/spectro).
TS_FORMAT = "%Y/%m/%d %H:%M:%S"

# Segnaposto per i dati non ancora disponibili, come nella GUI.
ND = "--"


def format_acq_date(ts):
    '''Converte un timestamp dei manager in gg/mm/aaaa hh:mm (ND se assente).'''
    if not ts:
        return ND
    try:
        return datetime.strptime(ts, TS_FORMAT).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(ts)


def cast_value(raw):
    '''Converte la stringa di 'save set' nel tipo piu' plausibile.'''
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.lower() in ('true', 'yes', 'on'):
        return True
    if raw.lower() in ('false', 'no', 'off'):
        return False
    return raw


class AeroCLI():
    '''Shell interattiva costruita sopra aeroHelper e i suoi manager.'''

    def __init__(self):
        self.ah = aeroHelper()
        self.config_file = 'config.yaml'
        self.commands = {
            'job': self.cmd_job,
            'measure': self.cmd_measure,
            'mesure': self.cmd_measure,   # alias tollerato
            'camera': self.cmd_camera,
            'daily': self.cmd_daily,
            'details': self.cmd_details,
            'save': self.cmd_save,
            'help': self.cmd_help,
        }

    # ------------------------------------------------------------------
    # Loop principale
    # ------------------------------------------------------------------

    def run(self):
        '''Legge ed esegue i comandi finche' l'utente non esce.'''
        print("AeroGreenHouse CLI - 'help' per l'elenco dei comandi, 'exit' per uscire.")
        while True:
            try:
                riga = input('aero> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not riga:
                continue

            try:
                argv = shlex.split(riga)
            except ValueError as e:
                print(f"Comando malformato: {e}")
                continue

            # Il '-' iniziale e' accettato ma non necessario nella shell.
            nome = argv[0].lstrip('-').lower()
            if nome in ('exit', 'quit'):
                break

            handler = self.commands.get(nome)
            if handler is None:
                print(f"Comando sconosciuto: '{argv[0]}'. Usa 'help'.")
                continue

            try:
                handler(argv[1:])
            except Exception as e:
                # La shell non deve morire per un errore di un singolo comando.
                print(f"Errore nell'esecuzione di '{nome}': {e}")

        self.shutdown()

    def shutdown(self):
        '''Rilascia le GPIO prima di uscire.'''
        self.ah.cleanup_gpios()
        print('Program Terminated')

    # ------------------------------------------------------------------
    # Stato dei processi (equivalente di gui.get_process_states)
    # ------------------------------------------------------------------

    def job_states(self):
        '''
        Stato dei soli job di attuazione, come lista di (nome, attivo).

        I sensori sono esclusi filtrando what_type, come fa la GUI.
        '''
        stati = []
        for pin_cfg in self.ah.configs.get('gpio_pins', []):
            if pin_cfg.get('what_type') == 'sensor':
                continue
            nome = pin_cfg.get('name', '')
            if nome == 'AEROPONICS':
                attivo = self.ah.jobs.aeroponics_job_active
            elif nome == 'IDROPONICS':
                attivo = self.ah.jobs.idroponics_job_active
            else:
                attivo = self.ah.jobs.general_jobs_active.get(nome, False)
            stati.append((nome, attivo))
        return stati

    def process_states(self):
        '''Stato di job e processi di sistema, come lista di (nome, attivo).'''
        stati = [(f"Job - {nome}", attivo) for nome, attivo in self.job_states()]
        stati.append(('Lettura Ambient (T/H/VPD)', self.ah.ambient.is_running()))
        stati.append(('Controllo Climatizzatore', self.ah.climate.is_running()))
        stati.append(('Lettura Serbatoio', self.ah.tank.is_running()))
        stati.append(('Lettura Spettrometro', self.ah.spectro.is_running()))
        stati.append(('Misura Crescita', self.ah.plant_growth.is_running()))
        stati.append(('Acquisizione Camera', self.ah.camera.is_acquiring()))
        stati.append(('Anteprima Camera', self.ah.camera.is_previewing()))
        stati.append(('Elaborazione Giornaliera', self.ah.daily_th.is_running()))
        return stati

    # ------------------------------------------------------------------
    # -job
    # ------------------------------------------------------------------

    def cmd_job(self, args):
        '''Gestione dei job: list / active / activate / deactivate.'''
        if not args:
            print("Uso: -job list | active | activate <nome> | deactivate <nome>")
            return

        azione = args[0].lower()

        if azione == 'list':
            self._job_list()
        elif azione == 'active':
            self._job_active()
        elif azione in ('activate', 'deactivate'):
            if len(args) < 2:
                print(f"Uso: -job {azione} <nome_job>")
                return
            nome = ' '.join(args[1:])
            if azione == 'activate':
                self._job_activate(nome)
            else:
                self._job_deactivate(nome)
        else:
            print(f"Sotto-comando job sconosciuto: '{azione}'")

    def _job_list(self):
        '''Tabella dei job definiti in config.yaml.'''
        pins = self.ah.configs.get('gpio_pins', [])
        if not pins:
            print('Nessun job configurato.')
            return

        print(f"{'NOME':<14}{'PIN':>5}{'TIPO':>10}{'INTERVAL':>10}{'ON TIME':>9}")
        for pin_cfg in pins:
            print(f"{pin_cfg.get('name', ND):<14}"
                  f"{pin_cfg.get('pin', ND):>5}"
                  f"{pin_cfg.get('what_type', ND):>10}"
                  f"{pin_cfg.get('interval', ND):>10}"
                  f"{pin_cfg.get('on_time', ND):>9}")

    def _job_active(self):
        '''Elenco dei soli job attivi, letto dallo stato reale dei manager.'''
        attivi = [nome for nome, attivo in self.job_states() if attivo]
        if not attivi:
            print('Nessun job attivo.')
            return
        print('Job attivi:')
        for nome in attivi:
            print(f"  - {nome}")

    def _find_job(self, nome):
        '''Cerca la configurazione di un job per nome (None se non esiste).'''
        for pin_cfg in self.ah.configs.get('gpio_pins', []):
            if pin_cfg.get('name') == nome:
                return pin_cfg
        return None

    def _job_activate(self, nome):
        '''Attiva un job, con lo stesso dispatch per nome della GUI.'''
        if nome == 'AEROPONICS':
            avviato = self.ah.jobs.start_aeroponics()
        elif nome == 'IDROPONICS':
            avviato = self.ah.jobs.start_idroponics()
        else:
            pin_cfg = self._find_job(nome)
            if pin_cfg is None:
                print(f"Job '{nome}' non trovato in config.yaml.")
                return
            if pin_cfg.get('what_type') == 'sensor':
                print(f"'{nome}' e' un sensore, non un job attivabile.")
                return
            avviato = self.ah.jobs.start_general(
                pin_cfg['pin'], pin_cfg['on_time'], pin_cfg['interval'], nome)

        if avviato:
            print(f"Job '{nome}' attivato.")
        else:
            print(f"Job '{nome}' era gia' attivo.")

    def _job_deactivate(self, nome):
        '''Disattiva un job, speculare a _job_activate.'''
        if nome == 'AEROPONICS':
            self.ah.jobs.deactivate_aeroponics()
        elif nome == 'IDROPONICS':
            self.ah.jobs.deactivate_idroponics()
        else:
            if self._find_job(nome) is None:
                print(f"Job '{nome}' non trovato in config.yaml.")
                return
            self.ah.jobs.deactivate_general(nome)
        print(f"Job '{nome}' disattivato.")

    # ------------------------------------------------------------------
    # -measure
    # ------------------------------------------------------------------

    def cmd_measure(self, args):
        '''Misure in tempo reale: th (T/H/VPD) e water (serbatoio).'''
        if not args:
            print('Uso: -measure th [now|stop] | -measure water [now|stop]')
            return

        grandezza = args[0].lower()
        azione = args[1].lower() if len(args) > 1 else 'start'

        if grandezza == 'th':
            self._measure_th(azione)
        elif grandezza == 'water':
            self._measure_water(azione)
        else:
            print(f"Grandezza sconosciuta: '{grandezza}'. Usa 'th' o 'water'.")

    def _print_th(self, temp, humidity, vpd, timestamp):
        '''Riga di stampa condivisa fra lettura singola e lettura continua.'''
        print(f"[{timestamp}] T = {temp:.1f} C | H = {humidity:.1f} % | VPD = {vpd:.4f} kPa")

    def _measure_th(self, azione):
        '''Lettura di temperatura, umidita' e VPD tramite AmbientManager.'''
        if azione == 'now':
            temp, humidity, vpd, timestamp = self.ah.ambient.read_now()
            self._print_th(temp, humidity, vpd, timestamp)
        elif azione == 'stop':
            if self.ah.ambient.stop_reading():
                print('Lettura T/H/VPD arrestata.')
            else:
                print('Nessuna lettura T/H/VPD in corso.')
        elif azione == 'start':
            if self.ah.ambient.start_reading(on_update=self._print_th):
                print("Lettura T/H/VPD avviata ('-measure th stop' per fermarla).")
            else:
                print('Lettura T/H/VPD gia\' in corso.')
        else:
            print(f"Azione sconosciuta: '{azione}'. Usa 'now' o 'stop'.")

    def _print_tank(self, result):
        '''Riga di stampa condivisa per le misure del serbatoio.'''
        print(f"[{result['timestamp']}] "
              f"volume = {result['volume_L']:.2f} L | "
              f"riempimento = {result['fill_percent']} % | "
              f"livello = {result['water_level_cm']} cm | "
              f"distanza = {result['distance_cm']} cm")

    def _measure_water(self, azione):
        '''Lettura del livello del serbatoio tramite TankManager.'''
        if azione == 'now':
            result = self.ah.tank.read_now()
            if result is None:
                # read_now scarta le misure fuori range (2-400 cm) e i timeout.
                print('Misura non valida: verificare il sensore ultrasonico.')
                return
            self._print_tank(result)
        elif azione == 'stop':
            if self.ah.tank.stop_reading():
                print('Lettura serbatoio arrestata.')
            else:
                print('Nessuna lettura serbatoio in corso.')
        elif azione == 'start':
            if self.ah.tank.start_reading(on_update=self._print_tank):
                print("Lettura serbatoio avviata ('-measure water stop' per fermarla).")
            else:
                print('Lettura serbatoio gia\' in corso.')
        else:
            print(f"Azione sconosciuta: '{azione}'. Usa 'now' o 'stop'.")

    # ------------------------------------------------------------------
    # -camera
    # ------------------------------------------------------------------

    def cmd_camera(self, args):
        '''Acquisizione periodica delle foto e anteprima dal vivo.'''
        azione = args[0].lower() if args else 'start'

        if azione == 'preview':
            self._camera_preview(args[1].lower() if len(args) > 1 else 'toggle')
        elif azione == 'now':
            photo = self.ah.camera.take_picture()
            print(f"Foto salvata: {photo['path']}")
        elif azione == 'stop':
            if self.ah.camera.stop_acquisition():
                print('Acquisizione foto arrestata.')
            else:
                print('Nessuna acquisizione in corso.')
        elif azione == 'start':
            if self.ah.camera.start_acquisition(on_capture=self._print_photo):
                ore = self.ah.camera.separation_hours()
                print(f"Acquisizione foto avviata: uno scatto ogni {ore} ore "
                      f"('-camera stop' per fermarla).")
            elif self.ah.camera.is_previewing():
                # La camera non e' condivisibile: l'anteprima la tiene occupata.
                print("Anteprima attiva: usa '-camera preview off' prima di avviare "
                      "l'acquisizione.")
            else:
                print('Acquisizione foto gia\' in corso.')
        else:
            print(f"Azione sconosciuta: '{azione}'. Usa 'start', 'stop', 'now' o 'preview'.")

    def _print_photo(self, photo):
        '''Riga di stampa per ogni scatto dell'acquisizione periodica.'''
        print(f"[{photo['timestamp']}] foto salvata: {photo['path']}")

    def _camera_preview(self, azione):
        '''
        Anteprima dal vivo.

        Richiede un display: via SSH senza X forwarding la finestra QTGL non
        puo' aprirsi e picamera2 solleva un errore, che il chiamante stampa.
        '''
        if azione == 'off':
            if self.ah.camera.stop_preview():
                print('Anteprima camera disattivata.')
            else:
                print('Anteprima camera non attiva.')
            return

        if azione not in ('on', 'toggle'):
            print(f"Azione sconosciuta: '{azione}'. Usa 'on' o 'off'.")
            return

        if azione == 'toggle' and self.ah.camera.is_previewing():
            self.ah.camera.stop_preview()
            print('Anteprima camera disattivata.')
            return

        if self.ah.camera.start_preview():
            print("Anteprima camera attivata ('-camera preview off' per chiuderla).")
        elif self.ah.camera.is_acquiring():
            print("Acquisizione in corso: la camera e' gia' in uso. "
                  "Usa '-camera stop' prima di attivare l'anteprima.")
        else:
            print('Anteprima camera gia\' attiva.')

    # ------------------------------------------------------------------
    # -daily
    # ------------------------------------------------------------------

    def cmd_daily(self, args):
        '''Elaborazione giornaliera di T/H/VPD (statistiche + plot).'''
        azione = args[0].lower() if args else 'start'

        if azione == 'stats':
            self._daily_stats()
        elif azione == 'now':
            # upload=True: qui l'elaborazione e' esplicita, non il giro di
            # riscaldamento che start() fa per popolare le statistiche.
            if self.ah.daily_th.run_now() is None:
                print('Nessun dato da elaborare per il giorno precedente.')
            else:
                self._daily_stats()
        elif azione == 'stop':
            if self.ah.daily_th.stop():
                print('Elaborazione giornaliera arrestata.')
            else:
                print('Nessuna elaborazione giornaliera in corso.')
        elif azione == 'start':
            if self.ah.daily_th.start():
                print("Elaborazione giornaliera avviata: job schedulato alle 00:01 "
                      "('-daily stop' per fermarla).")
            else:
                print('Elaborazione giornaliera gia\' in corso.')
        else:
            print(f"Azione sconosciuta: '{azione}'. Usa 'start', 'stop', 'now' o 'stats'.")

    def _daily_stats(self):
        '''Statistiche dell'ultima elaborazione (max/min/media di T, H e VPD).'''
        daily = self.ah.daily_th
        if not daily.last_stats:
            print(f"Nessuna elaborazione eseguita ({ND})")
            return

        s = daily.last_stats
        print(f"Giorno elaborato: {daily.last_date_label}")
        print(f"{'':<14}{'MAX':>9}{'MIN':>9}{'MEDIA':>9}")
        for etichetta, k_max, k_min, k_avg in (
                ('Temperatura', 'max_T', 'min_T', 'avg_temperature'),
                ("Umidita'", 'max_H', 'min_H', 'avg_humidity'),
                ('VPD', 'max_VPD', 'min_VPD', 'avg_vpd')):
            print(f"{etichetta:<14}{s[k_max]:>9g}{s[k_min]:>9g}{s[k_avg]:>9g}")
        print(f"Plot: {daily.last_plot_path or ND}")

    # ------------------------------------------------------------------
    # -details
    # ------------------------------------------------------------------

    def cmd_details(self, args):
        '''Riepilogo generale, equivalente testuale della scheda "Riepilogo".'''
        print('=' * 52)
        print('RIEPILOGO')
        print('=' * 52)
        self._details_ambiente()
        self._details_serbatoio()
        self._details_mcari2()
        self._details_crescita()
        self._details_camera()
        self._details_giornaliera()
        self._details_processi()
        print('=' * 52)

    def _details_ambiente(self):
        '''Ultima lettura T/H/VPD (last_result e' riletto da file all'avvio).'''
        print('\n-- Ambiente --')
        r = self.ah.ambient.last_result
        if not r:
            print(f"  Nessun dato disponibile ({ND})")
            return
        print(f"  Temperatura : {r['temperature']:.1f} C")
        print(f"  Umidita'    : {r['humidity']:.1f} %")
        print(f"  VPD         : {r['vpd']:.4f} kPa")
        print(f"  Acquisito   : {format_acq_date(r.get('timestamp'))}")

    def _details_serbatoio(self):
        '''Ultima misura del serbatoio.'''
        print('\n-- Serbatoio --')
        r = self.ah.tank.last_result
        if not r:
            print(f"  Nessun dato disponibile ({ND})")
            return
        print(f"  Volume      : {r['volume_L']:.2f} L")
        print(f"  Riempimento : {r['fill_percent']} %")
        print(f"  Misurato    : {format_acq_date(r.get('timestamp'))}")

    def _details_mcari2(self):
        '''Ultimo indice MCARI2. Attenzione: spectro.history e' piu' recente in testa.'''
        print('\n-- Indice MCARI2 --')
        history = self.ah.spectro.history
        if not history:
            print(f"  Nessun dato disponibile ({ND})")
            return
        r = history[0]
        print(f"  MCARI2      : {r['mcari2']}")
        print(f"  Stato       : {r['stato']}")
        print(f"  Valutato    : {format_acq_date(r.get('timestamp'))}")

    def _details_crescita(self):
        '''Ultima altezza misurata. Attenzione: plant_growth.history e' ascendente.'''
        print('\n-- Crescita --')
        history = self.ah.plant_growth.history
        if not history:
            print(f"  Nessun dato disponibile ({ND})")
            return
        r = history[-1]
        print(f"  Altezza     : {r['h_plant_cm']:.1f} cm")
        print(f"  Misurato    : {format_acq_date(r.get('timestamp'))}")

    def _details_camera(self):
        '''Ultima foto acquisita (last_photo e' riletto da disco all'avvio).'''
        print('\n-- Camera --')
        r = self.ah.camera.last_photo
        if not r:
            print(f"  Nessuna foto disponibile ({ND})")
            return
        print(f"  File        : {r['path']}")
        print(f"  Acquisita   : {format_acq_date(r.get('timestamp'))}")

    def _details_giornaliera(self):
        '''Sintesi dell'ultima elaborazione giornaliera ('-daily stats' per il dettaglio).'''
        print('\n-- Elaborazione Giornaliera --')
        daily = self.ah.daily_th
        if not daily.last_stats:
            print(f"  Nessun dato disponibile ({ND})")
            return
        s = daily.last_stats
        print(f"  Giorno      : {daily.last_date_label}")
        print(f"  T media     : {s['avg_temperature']:g} C "
              f"(max {s['max_T']:g} / min {s['min_T']:g})")
        print(f"  H media     : {s['avg_humidity']:g} % "
              f"(max {s['max_H']:g} / min {s['min_H']:g})")
        print(f"  VPD medio   : {s['avg_vpd']:g} kPa "
              f"(max {s['max_VPD']:g} / min {s['min_VPD']:g})")

    def _details_processi(self):
        '''Elenco dei processi attualmente attivi.'''
        print('\n-- Processi Attivi --')
        attivi = [nome for nome, acceso in self.process_states() if acceso]
        if not attivi:
            print('  Nessun processo attivo')
            return
        for nome in attivi:
            print(f"  * {nome}")

    # ------------------------------------------------------------------
    # -save
    # ------------------------------------------------------------------

    def cmd_save(self, args):
        '''Lettura e modifica dei parametri di config.yaml.'''
        if not args:
            print('Uso: -save list | get <chiave> | set <chiave> <valore> | write')
            return

        azione = args[0].lower()

        if azione == 'list':
            print(yaml.dump(self.ah.configs, default_flow_style=False,
                            sort_keys=False, allow_unicode=True), end='')
        elif azione == 'get':
            if len(args) < 2:
                print('Uso: -save get <chiave>   (es. tank.trig_pin)')
                return
            self._save_get(args[1])
        elif azione == 'set':
            if len(args) < 3:
                print('Uso: -save set <chiave> <valore>   (es. tank.trig_pin 5)')
                return
            self._save_set(args[1], ' '.join(args[2:]))
        elif azione == 'write':
            self._save_write()
        else:
            print(f"Sotto-comando save sconosciuto: '{azione}'")

    def _resolve_path(self, dotted):
        '''
        Naviga configs seguendo un dot-path e ritorna (contenitore, ultima_chiave).

        Gli indici numerici attraversano le liste, cosi' 'gpio_pins.0.interval'
        raggiunge il primo job. Solleva KeyError/IndexError se il percorso non esiste.
        '''
        parti = dotted.split('.')
        nodo = self.ah.configs
        for parte in parti[:-1]:
            nodo = nodo[int(parte)] if isinstance(nodo, list) else nodo[parte]
        ultima = parti[-1]
        return nodo, (int(ultima) if isinstance(nodo, list) else ultima)

    def _save_get(self, dotted):
        '''Stampa il valore corrente di una chiave.'''
        try:
            contenitore, chiave = self._resolve_path(dotted)
            print(f"{dotted} = {contenitore[chiave]}")
        except (KeyError, IndexError, TypeError, ValueError):
            print(f"Chiave non trovata: '{dotted}'")

    def _save_set(self, dotted, raw):
        '''
        Modifica un valore in configs.

        La modifica e' in place sul dict che i manager tengono per riferimento,
        quindi raggiunge anche i manager gia' istanziati senza riavvio.
        '''
        try:
            contenitore, chiave = self._resolve_path(dotted)
            vecchio = contenitore[chiave]
        except (KeyError, IndexError, TypeError, ValueError):
            print(f"Chiave non trovata: '{dotted}'")
            return

        nuovo = cast_value(raw)
        contenitore[chiave] = nuovo
        print(f"{dotted}: {vecchio} -> {nuovo}")
        print("(usa '-save write' per rendere la modifica permanente)")

    def _save_write(self):
        '''Scrive la configurazione corrente su config.yaml.'''
        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(self.ah.configs, f, default_flow_style=False, sort_keys=False)
            print(f"Configurazione salvata in {self.config_file}.")
        except OSError as e:
            print(f"Errore nel salvataggio: {e}")

    # ------------------------------------------------------------------
    # help
    # ------------------------------------------------------------------

    def cmd_help(self, args):
        '''Stampa l'elenco dei comandi (docstring del modulo).'''
        print(__doc__.split('Comandi', 1)[1].split('\n', 1)[1].rstrip())


if __name__ == '__main__':
    sys.exit(AeroCLI().run())
