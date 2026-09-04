'''
Qualita' dell'acqua: pH e conducibilita' elettrica (EC).

Entrambe le sonde sono collegate a un Arduino UNO e lette via seriale USB
(vedi managers_classes/arduino_link.py). Il Raspberry mantiene la sola
logica di controllo temporizzato: pH ed EC sono due JOB INDIPENDENTI, con
intervallo, thread e comandi di avvio/arresto propri, perche' le due sonde
hanno tempi e finalita' diversi e si deve poterne fermare una sola.
'''

import glob
import os
import threading
from datetime import datetime

from managers_classes.arduino_link import ArduinoError
from managers_classes.data_config import round_decimals


# =====================================================================
# Default (usati se la sezione 'water' di config.yaml e' incompleta)
# =====================================================================

PH_READ_INTERVAL_S = 1800    # ogni quanti secondi leggere il pH
EC_READ_INTERVAL_S = 1800    # ogni quanti secondi leggere l'EC
PH_MIN = 5.5                 # soglia di allarme, sotto la quale avvisare
PH_MAX = 6.5
EC_MIN = 800.0               # uS/cm
EC_MAX = 2000.0
DECIMALS = 2
SAVE_DIR = "/home/fishnplants/Desktop/data/WATER/"
HISTORY_LEN = 30

# Range fisici oltre i quali la lettura e' certamente sbagliata (sonda
# scollegata, in aria, o circuito da ricalibrare).
PH_VALID_MIN = 0.0
PH_VALID_MAX = 14.0
EC_VALID_MIN = 0.0
EC_VALID_MAX = 200000.0      # fondo scala dichiarato dell'EZO-EC

# Nome dei file giornalieri, come per TANK_*.txt e TH_*.txt
WATER_FILE_GLOB = "WATER_*.txt"
NAME_FORMAT = "WATER_%Y_%m_%d.txt"

HEADER = "datetime\t\t\t ph\t ec_uScm\t tds_ppm\t sal_psu\n"

# Segnaposto per le colonne che il job che sta scrivendo non ha misurato:
# pH ed EC hanno intervalli diversi, quindi quasi ogni riga ne riempie solo
# una meta'.
ND = "--"


# =====================================================================
# Salvataggio / rilettura delle misure
# =====================================================================

def save_water_data(result, save_dir):
    '''
    Appende una misura al file giornaliero WATER_%Y_%m_%d.txt.

    Le colonne non presenti in 'result' vengono scritte come '--', cosi'
    il formato del file resta unico anche se le due sonde scrivono in
    momenti diversi.

    :param result:   dict con 'timestamp' e almeno una fra 'ph' e 'ec_us_cm'
    :param save_dir: directory di salvataggio
    '''
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, datetime.now().strftime(NAME_FORMAT))

    def campo(chiave):
        valore = result.get(chiave)
        return ND if valore is None else f"{valore}"

    # Header scritto solo se il file non esiste ancora
    write_header = not os.path.exists(file_path)
    with open(file_path, "a") as f:
        if write_header:
            f.write(HEADER)
        f.write(f"{result['timestamp']}\t {campo('ph')}\t {campo('ec_us_cm')}\t "
                f"{campo('tds_ppm')}\t {campo('salinity_psu')}\n")


def _parse_water_line(line):
    '''
    Converte una riga del file in dict, o None se la riga non e' valida.

    I campi a '--' diventano None: chi legge distingue "non misurato" da
    "misurato zero".
    '''
    line = line.strip()
    # Salta righe vuote e header
    if not line or line.startswith("datetime"):
        return None

    campi = line.split("\t")
    if len(campi) < 5:
        return None

    def valore(campo):
        campo = campo.strip()
        if not campo or campo == ND:
            return None
        try:
            return float(campo)
        except ValueError:
            return None

    return {
        'timestamp': campi[0].strip(),
        'ph': valore(campi[1]),
        'ec_us_cm': valore(campi[2]),
        'tds_ppm': valore(campi[3]),
        'salinity_psu': valore(campi[4]),
    }


def load_water_history(save_dir, max_rows=None):
    '''
    Rilegge le misure dell'ultimo file giornaliero disponibile.

    Viene scelto il file piu' recente: il nome WATER_%Y_%m_%d.txt ordina
    cronologicamente anche come stringa.

    :param save_dir: directory dei dati WATER
    :param max_rows: se valorizzato, tiene solo le ultime N righe
    :return: lista di dict in ordine cronologico crescente
    '''
    files = sorted(glob.glob(os.path.join(save_dir, WATER_FILE_GLOB)))
    if not files:
        return []

    try:
        with open(files[-1], "r") as f:
            righe = f.readlines()
    except OSError:
        return []

    storico = [r for r in (_parse_water_line(line) for line in righe) if r is not None]
    if max_rows is not None:
        storico = storico[-max_rows:]
    return storico


def load_last_water(save_dir):
    '''
    Rilegge l'ultima misura salvata di pH e di EC.

    Le due sonde scrivono su righe diverse, quindi si risale il file
    all'indietro cercando separatamente l'ultimo pH e l'ultimo EC validi.

    :return: tupla (last_ph, last_ec), ciascuno dict o None.
    '''
    storico = load_water_history(save_dir)

    last_ph = None
    last_ec = None
    for riga in reversed(storico):
        if last_ph is None and riga['ph'] is not None:
            last_ph = {'timestamp': riga['timestamp'], 'ph': riga['ph']}
        if last_ec is None and riga['ec_us_cm'] is not None:
            last_ec = {
                'timestamp': riga['timestamp'],
                'ec_us_cm': riga['ec_us_cm'],
                'tds_ppm': riga['tds_ppm'],
                'salinity_psu': riga['salinity_psu'],
            }
        if last_ph is not None and last_ec is not None:
            break

    return last_ph, last_ec


# =====================================================================
# Categoria ACQUA (pH ed EC via Arduino UNO)
# =====================================================================
class WaterManager():
    '''
    Class per la lettura del pH e della conducibilita' elettrica dell'acqua.

    Le due sonde Atlas Scientific (Surveyor pH e EZO-EC) sono collegate a un
    Arduino UNO, che le legge su richiesta; qui si decide soltanto QUANDO
    chiedere la lettura, si validano i valori, si salvano su file e si
    confrontano con le soglie di allarme.

    pH ed EC sono due job separati: start_ph_reading() e start_ec_reading()
    si avviano e si fermano in modo indipendente.

    I parametri sono letti dalla sezione 'water' di config.yaml.
    '''

    def __init__(self, configs, logger, arduino, errors):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        :param arduino: ArduinoHub condiviso (managers_classes/arduino_link.py)
        :param errors:  ErrorRecorder condiviso (managers_classes/error_log.py)
        '''
        self.configs = configs
        self.logger = logger
        self._arduino = arduino
        self._errors = errors

        self._ph_thread = None
        self._ph_stop_event = threading.Event()
        self._ec_thread = None
        self._ec_stop_event = threading.Event()

        # Ultime misure salvate (servono alla scheda Riepilogo gia' all'avvio)
        self.last_ph, self.last_ec = self.load_last_readings()
        self.history = self.load_history()

    def _params(self):
        '''Legge i parametri dalla sezione 'water' di config.yaml con fallback ai default del modulo.'''
        w = self.configs.get('water', {}) or {}
        return dict(
            ph_interval=w.get('ph_read_interval', PH_READ_INTERVAL_S),
            ec_interval=w.get('ec_read_interval', EC_READ_INTERVAL_S),
            ph_min=w.get('ph_min', PH_MIN),
            ph_max=w.get('ph_max', PH_MAX),
            ec_min=w.get('ec_min', EC_MIN),
            ec_max=w.get('ec_max', EC_MAX),
            decimals=w.get('decimals', DECIMALS),
            save_enabled=w.get('save', True),
            save_dir=w.get('saving_dir', SAVE_DIR),
            history_len=w.get('history_len', HISTORY_LEN),
        )

    def load_last_readings(self):
        '''Rilegge da file l'ultimo pH e l'ultima EC salvati ((None, None) se non ci sono).'''
        try:
            return load_last_water(self._params()['save_dir'])
        except Exception as e:
            self.logger.error(f"WATER: errore nella rilettura degli ultimi dati: {e}")
            return None, None

    def load_history(self):
        '''Rilegge lo storico delle misure (per grafici e tabelle della GUI).'''
        p = self._params()
        try:
            return load_water_history(p['save_dir'], max_rows=p['history_len'])
        except Exception as e:
            self.logger.error(f"WATER: errore nella lettura dello storico: {e}")
            return []

    def _store(self, result, p):
        '''Salva su file e aggiorna lo storico in memoria (comune a pH ed EC).'''
        if p['save_enabled']:
            try:
                save_water_data(result, p['save_dir'])
            except Exception as e:
                self.logger.error(f"WATER: errore nel salvataggio dati: {e}")

        self.history.append(result)
        self.history = self.history[-p['history_len']:]

    # ------------------------------------------------------------------
    # pH
    # ------------------------------------------------------------------

    def read_ph_now(self):
        '''
        Esegue una misura singola del pH chiedendola all'Arduino.

        :return: dict con timestamp e ph, oppure None se la misura non e' valida.
        '''
        p = self._params()

        try:
            ph = self._arduino.read_float('pH')
        except ArduinoError as e:
            self._errors.record('pH', f"Non è stato possibile leggere il sensore di pH, "
                                      f"controlla il motivo: {e.message}")
            return None

        if ph < PH_VALID_MIN or ph > PH_VALID_MAX:
            self._errors.record('pH', f"Non è stato possibile leggere il sensore di pH, "
                                      f"controlla il motivo: valore {ph} fuori dalla scala "
                                      f"0-14. Misura ignorata.")
            return None

        result = {
            'timestamp': datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            'ph': round_decimals(ph, p['decimals']),
        }
        self.last_ph = result

        self.logger.info(f"WATER: pH={result['ph']}")

        if result['ph'] < p['ph_min'] or result['ph'] > p['ph_max']:
            self.logger.warning(
                f"WATER pH FUORI RANGE: {result['ph']} non è compreso fra "
                f"{p['ph_min']} e {p['ph_max']}. Correggere la soluzione nutritiva."
            )

        self._store(result, p)
        return result

    def is_ph_running(self):
        '''True se il thread di lettura del pH e' attivo.'''
        return self._ph_thread is not None and self._ph_thread.is_alive()

    def start_ph_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata del pH in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_ph_running():
            return False
        self._ph_stop_event.clear()
        self._ph_thread = threading.Thread(target=self._ph_read_loop,
                                           args=(on_update,), daemon=True)
        self._ph_thread.start()
        return True

    def stop_ph_reading(self):
        '''Arresta immediatamente la lettura del pH. False se non era in corso.'''
        if not self.is_ph_running():
            return False
        self._ph_stop_event.set()
        return True

    def _ph_read_loop(self, on_update):
        '''Loop per letture periodiche del pH (sleep interrompibile per stop immediato).'''
        p = self._params()
        self.logger.info(f"Inizio lettura pH. Intervallo: {p['ph_interval']}s")

        while not self._ph_stop_event.is_set():
            try:
                result = self.read_ph_now()  # read_ph_now salva gia' su file
                if result is not None and on_update is not None:
                    on_update(result)
            except Exception as e:
                self.logger.error(f"Errore lettura pH: {str(e)}")

            # Attendi l'intervallo (interrompibile). Rileggo i parametri ad
            # ogni giro cosi' un cambio di intervallo ha effetto subito.
            self._ph_stop_event.wait(self._params()['ph_interval'])

        self.logger.info("Lettura pH interrotta")

    # ------------------------------------------------------------------
    # EC (conducibilita' elettrica)
    # ------------------------------------------------------------------

    def read_ec_now(self):
        '''
        Esegue una misura singola della conducibilita' chiedendola all'Arduino.

        Il circuito EZO-EC restituisce in un'unica risposta conducibilita',
        solidi disciolti totali e salinita': una sola lettura popola tutti e
        tre i valori.

        :return: dict con timestamp, ec_us_cm, tds_ppm, salinity_psu,
                 oppure None se la misura non e' valida.
        '''
        p = self._params()

        try:
            valori = self._arduino.read_named('EC')
        except ArduinoError as e:
            self._errors.record('EC', f"Non è stato possibile leggere il sensore di "
                                      f"conducibilità (EC), controlla il motivo: {e.message}")
            return None

        ec = valori['ec_us_cm']
        if ec < EC_VALID_MIN or ec > EC_VALID_MAX:
            self._errors.record('EC', f"Non è stato possibile leggere il sensore di "
                                      f"conducibilità (EC), controlla il motivo: valore {ec} "
                                      f"fuori dal fondo scala della sonda. Misura ignorata.")
            return None

        result = {
            'timestamp': datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            'ec_us_cm': round_decimals(ec, p['decimals']),
            'tds_ppm': round_decimals(valori['tds_ppm'], p['decimals']),
            'salinity_psu': round_decimals(valori['salinity_psu'], p['decimals']),
        }
        self.last_ec = result

        self.logger.info(
            f"WATER: EC={result['ec_us_cm']}uS/cm | "
            f"TDS={result['tds_ppm']}ppm | "
            f"salinità={result['salinity_psu']}PSU"
        )

        if result['ec_us_cm'] < p['ec_min'] or result['ec_us_cm'] > p['ec_max']:
            self.logger.warning(
                f"WATER EC FUORI RANGE: {result['ec_us_cm']}uS/cm non è compreso fra "
                f"{p['ec_min']} e {p['ec_max']}. Correggere la soluzione nutritiva."
            )

        self._store(result, p)
        return result

    def is_ec_running(self):
        '''True se il thread di lettura dell'EC e' attivo.'''
        return self._ec_thread is not None and self._ec_thread.is_alive()

    def start_ec_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata dell'EC in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_ec_running():
            return False
        self._ec_stop_event.clear()
        self._ec_thread = threading.Thread(target=self._ec_read_loop,
                                           args=(on_update,), daemon=True)
        self._ec_thread.start()
        return True

    def stop_ec_reading(self):
        '''Arresta immediatamente la lettura dell'EC. False se non era in corso.'''
        if not self.is_ec_running():
            return False
        self._ec_stop_event.set()
        return True

    def _ec_read_loop(self, on_update):
        '''Loop per letture periodiche dell'EC (sleep interrompibile per stop immediato).'''
        p = self._params()
        self.logger.info(f"Inizio lettura EC. Intervallo: {p['ec_interval']}s")

        while not self._ec_stop_event.is_set():
            try:
                result = self.read_ec_now()  # read_ec_now salva gia' su file
                if result is not None and on_update is not None:
                    on_update(result)
            except Exception as e:
                self.logger.error(f"Errore lettura EC: {str(e)}")

            self._ec_stop_event.wait(self._params()['ec_interval'])

        self.logger.info("Lettura EC interrotta")

    # ------------------------------------------------------------------
    # Comodita' per chi vuole trattarli insieme
    # ------------------------------------------------------------------

    def is_running(self):
        '''True se almeno uno dei due job (pH o EC) e' attivo.'''
        return self.is_ph_running() or self.is_ec_running()

    def stop_all(self):
        '''Arresta entrambi i job. True se almeno uno era in corso.'''
        fermato_ph = self.stop_ph_reading()
        fermato_ec = self.stop_ec_reading()
        return fermato_ph or fermato_ec
