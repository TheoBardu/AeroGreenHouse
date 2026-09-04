import glob
import json
import os
import re
import subprocess
import sys
import threading
from time import sleep


# Nome dei file giornalieri scritti da _read_loop
TH_FILE_GLOB = "TH_*.txt"


# =====================================================================
# Rilettura dell'ultimo dato salvato
# =====================================================================

def load_last_th(save_dir: str) -> dict:
    '''
    Rilegge l'ultima misura ambientale salvata su file.

    Serve alla scheda Riepilogo: senza, all'avvio del pannello temperatura,
    umidita' e VPD resterebbero vuoti fino alla prima lettura del sensore.

    Formato della riga (unita' attaccate ai valori, nessun header):
        2026/07/17 09:41:03\t  23.40C\t  61.20%\t 1.0234kPa

    Viene scelto il file piu' recente: il nome TH_%Y_%m_%d.txt ordina
    cronologicamente anche come stringa, quindi basta l'ultimo in ordine
    alfabetico. Cosi' il dato c'e' anche se il file di oggi non esiste ancora.

    :param save_dir: directory dei dati TH
    :return: dict con temperature, humidity, vpd, timestamp
             oppure None se non c'e' nessuna misura leggibile.
    '''
    files = sorted(glob.glob(os.path.join(save_dir, TH_FILE_GLOB)))
    if not files:
        return None

    try:
        with open(files[-1], "r") as f:
            righe = f.readlines()
    except OSError:
        return None

    # Dall'ultima riga a ritroso: la prima interpretabile e' l'ultima misura
    for line in reversed(righe):
        campi = line.strip().split("\t")
        if len(campi) < 4:
            continue
        try:
            valori = [re.search(r'[\d.]+', c).group() for c in campi[1:4]]
        except AttributeError:
            continue  # riga senza numeri (malformata)
        try:
            return {
                'timestamp': campi[0].strip(),
                'temperature': float(valori[0]),
                'humidity': float(valori[1]),
                'vpd': float(valori[2]),
            }
        except ValueError:
            continue

    return None


# =====================================================================
# Categoria AMBIENTE (lettura DHT22, VPD, salvataggio e upload dati)
# =====================================================================
class AmbientManager():
    '''
    Class per la lettura dei dati ambientali (temperatura, umidita', VPD)
    tramite sensore DHT22, il salvataggio su file e l'upload online.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        # Last DHT22 reading.
        # ATTENZIONE: last_T/last_H significano "letto dal sensore in questa
        # sessione" e NON vanno mai popolati da file. ClimateManager.start() si
        # rifiuta di partire finche' sono None: e' cio' che impedisce di
        # comandare il condizionatore senza dati sul clima. Seminarli da file
        # farebbe agire l'AC su una temperatura magari vecchia di ore.
        self.last_T = None
        self.last_H = None

        # Ultima misura completa (T, H, VPD, data) per la scheda Riepilogo.
        # Questa invece si puo' rileggere da file: e' solo informativa.
        self.last_result = self.load_last_reading()

        # TH jobs control
        self.th_job_active = False   # controlla se viene eseguita la lettura dei dati TH
        self.th_job_saving = False   # controlla se viene eseguito il job TH (salvataggio dati TH e VPD)

        # Gestione thread di lettura periodica
        self._thread = None
        self._stop_event = threading.Event()

        # Funzione, impostata da aeroHelper dopo aver creato tutti i manager,
        # che restituisce gli ultimi valori noti delle altre grandezze (acqua,
        # serbatoio, crescita) e gli errori recenti, da allegare all'upload.
        # Resta None se il manager e' usato da solo: in quel caso si carica
        # solo T/H/VPD, esattamente come prima.
        self.extra_data_provider = None

    def load_last_reading(self):
        '''Rilegge da file l'ultima misura ambientale salvata (None se non c'e').'''
        save_dir = self.configs.get('dht22', {}).get('saving_dir',
                                                     '/home/fishnplants/Desktop/data/TH/')
        try:
            return load_last_th(save_dir)
        except Exception as e:
            self.logger.error(f"AMBIENT: errore nella rilettura dell'ultimo dato: {e}")
            return None

    ###########################################
    # DHT22 sensor measurements
    ###########################################
    def measure_dht22(self, gpio):
        '''
        Module that use the DHT22 sensor for reading the temperature and humidity

        :param self: Description
        :param gpio: GPIO number (27,17, ecc)
        '''
        import adafruit_dht
        import board
        from time import sleep
        from datetime import datetime

        dht = eval(f"adafruit_dht.DHT22(board.D{gpio})")

        while True:
            try:
                T = dht.temperature
                H = dht.humidity
                # print('T = %4.2f C ;  H = %4.2f'%(T, H),'%', 'VPD = %5.4f kPa'%(self.VPD(T,H))) #For debug
                return T, H
                break
            except RuntimeError as error:
                print(error.args[0])
                sleep(2.0)
                continue
            except Exception as error:
                dht.exit()
                raise error

    def VPD(self, T, H):
        '''
        Function that calculate the VPD
        '''
        from math import exp
        es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))
        ea = lambda H: H * es(T) / 100

        VPD = es(T) - ea(H)
        return VPD

    ###########################################
    # Uploading data on website
    ###########################################
    # Grandezze allegabili all'upload: (chiave restituita dal provider, flag).
    UPLOAD_EXTRA_FLAGS = (
        ('ph', '-ph'),
        ('ec_us_cm', '-ec'),
        ('tds_ppm', '-tds'),
        ('salinity_psu', '-sal'),
        ('water_level_cm', '-lvl'),
        ('volume_L', '-vol'),
        ('fill_percent', '-fill'),
        ('h_plant_cm', '-hp'),
    )

    def upload_data_on_web(self, T, H, vpd, timestamp):
        '''
        Carica sul sito l'ultima lettura, chiamando il modulo uploader.py.

        Oltre a T/H/VPD allega, se disponibili, gli ultimi valori noti delle
        altre grandezze (pH, EC, serbatoio, altezza piante) e gli errori di
        lettura recenti: il sito mostra una fotografia unica dello stato della
        serra, e non ha senso fare un upload separato per ogni sonda.

        Si usa subprocess con una lista di argomenti e non os.system: gli
        errori sono una stringa JSON con virgolette e accenti, che passando
        dalla shell verrebbe interpretata e spezzata.
        '''
        cmd = [sys.executable, 'uploader/uploader.py', 'data',
               '-t', str(T), '-hu', str(H), '-vpd', str(vpd), '-ts', str(timestamp)]

        extra = {}
        if self.extra_data_provider is not None:
            try:
                extra = self.extra_data_provider() or {}
            except Exception as e:
                self.logger.warning(f"AMBIENT: dati aggiuntivi non disponibili per "
                                    f"l'upload: {e}")

        for chiave, flag in self.UPLOAD_EXTRA_FLAGS:
            valore = extra.get(chiave)
            if valore is not None:
                cmd += [flag, str(valore)]

        errori = extra.get('errors')
        if errori:
            cmd += ['-err', json.dumps(errori, ensure_ascii=False)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"AMBIENT: upload dati fallito: {result.stderr.strip()}")

    ###########################################
    # Lettura periodica (spostata da gui.py)
    ###########################################
    def is_running(self):
        '''True se il thread di lettura ambient e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata dei dati ambient in un thread.

        :param on_update: callback opzionale on_update(temp, humidity, vpd, timestamp)
                          usata dalla GUI per aggiornare le label.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        # Thread residuo di una lettura precedente gia' terminata
        self._thread = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self, timeout=5):
        '''
        Arresta immediatamente la lettura temporizzata. False se non era in corso.

        Oltre a segnalare lo stop, attende la fine del thread e azzera subito
        self._thread: senza questo is_running() resterebbe True finche' il
        thread agonizza e "Attiva Lettura" rifiuterebbe di ripartire.
        '''
        if not self.is_running():
            return False
        self._stop_event.set()
        t = self._thread
        self._thread = None
        if t is not threading.current_thread():
            t.join(timeout=timeout)
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche (logica originale, sleep interrompibile per stop immediato).'''
        import adafruit_dht
        import board
        from datetime import datetime

        interval = self.configs.get('dht22', {}).get('read_interval', 5)
        pin = self.configs.get('dht22', {}).get('pin', 27)
        # Tentativi massimi di lettura per ciclo prima di arrendersi e
        # ritentare al ciclo successivo (evita il retry infinito silenzioso).
        max_retries = self.configs.get('dht22', {}).get('max_retries', 5)

        self.logger.info(f"Inizio lettura AMBIENT. Intervallo: {interval}s, Pin: {pin}")

        def make_dht():
            '''Crea l'oggetto sensore. getattr al posto di eval (piu' sicuro).'''
            return adafruit_dht.DHT22(getattr(board, f"D{pin}"))

        def init_dht():
            '''
            Inizializza il sensore ritentando: se il pin e' ancora occupato da
            una sessione precedente l'init fallisce, ma NON deve uccidere il
            thread. Ritenta con attesa interrompibile finche' non riesce o
            finche' non viene chiesto lo stop (in tal caso ritorna None).
            '''
            while not self._stop_event.is_set():
                try:
                    return make_dht()
                except Exception as error:
                    self.logger.warning(f"AMBIENT: init sensore fallito ({error}), ritento...")
                    self._stop_event.wait(2.0)
            return None

        # dht e' gestito nel loop (puo' essere ricreato su fallimento
        # persistente): usiamo una lista per poterlo riassegnare dalla closure.
        dht_box = [None]

        def measure_dht_22():
            '''
            Ritenta la lettura del DHT22 fino a max_retries volte. I RuntimeError
            sono frequentissimi sul Pi: l'attesa fra un tentativo e l'altro usa
            _stop_event.wait() cosi' l'arresto e' immediato anche qui.

            Ritorna:
              (T, H)        lettura riuscita
              (None, None)  stop richiesto OPPURE fallimento dopo max_retries.
                            Il chiamante distingue i due casi con _stop_event.
            Su fallimento persistente ricrea il sensore (dht.exit + re-init)
            per liberare un pin eventualmente latchato.
            '''
            attempts = 0
            while not self._stop_event.is_set():
                try:
                    T = dht_box[0].temperature
                    H = dht_box[0].humidity
                    # print('T = %4.2f C ;  H = %4.2f'%(T, H),'%', 'VPD = %5.4f kPa'%(self.VPD(T,H))) #For debug
                    return T, H
                except RuntimeError as error:
                    attempts += 1
                    self.logger.warning(f"AMBIENT: lettura fallita ({error.args[0]}), tentativo {attempts}/{max_retries}")
                    if attempts >= max_retries:
                        self.logger.warning(f"AMBIENT: sensore non risponde dopo {max_retries} tentativi, ritento al prossimo ciclo")
                        # Ricrea il sensore per liberare un pin latchato
                        try:
                            dht_box[0].exit()
                        except Exception:
                            pass
                        new_dht = init_dht()
                        if new_dht is None:
                            return None, None  # stop richiesto durante il re-init
                        dht_box[0] = new_dht
                        return None, None  # fallimento ciclo: si ritenta al prossimo giro
                    self._stop_event.wait(2.0)
                    continue
            return None, None

        try:
            dht_box[0] = init_dht()
            if dht_box[0] is None:
                # Stop richiesto prima ancora di inizializzare il sensore
                self.logger.info("Lettura AMBIENT interrotta")
                return
            while not self._stop_event.is_set():
                try:
                    # Leggi i dati
                    temp, humidity = measure_dht_22()
                    if self._stop_event.is_set():
                        break  # stop reale richiesto
                    if temp is None:
                        # Fallimento del ciclo: NON uscire, ritenta al prossimo giro
                        self._stop_event.wait(interval)
                        continue
                    vpd = self.VPD(temp, humidity)

                    self.last_T = temp
                    self.last_H = humidity

                    # Ottieni timestamp
                    timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                    file_name = datetime.now().strftime("%Y_%m_%d")

                    self.last_result = {'timestamp': timestamp, 'temperature': temp,
                                        'humidity': humidity, 'vpd': vpd}

                    # Aggiorna GUI tramite callback
                    if on_update is not None:
                        on_update(temp, humidity, vpd, timestamp)

                    self.logger.info(f"AMBIENT: T={temp:.2f}C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")

                    # salva file
                    format_data_out = "%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
                    fid = open(self.configs.get('dht22', {}).get('saving_dir', '/home/fishnplants/Desktop/data/TH/') + 'TH_' + file_name + '.txt', 'a')
                    fid.write(format_data_out % (timestamp, temp, humidity, vpd))
                    fid.close()

                    # carica file online (os.system e' bloccante: se e' gia'
                    # stato chiesto lo stop lo saltiamo per uscire subito)
                    if self._stop_event.is_set():
                        break
                    try:
                        self.upload_data_on_web(temp, humidity, vpd, timestamp)
                    except:
                        self.logger.error(f"AMBIENT: not able to upload the ambient data online. Check errors if occured")

                    # Attendi l'intervallo (interrompibile)
                    self._stop_event.wait(interval)

                except Exception as e:
                    self.logger.error(f"Errore lettura AMBIENT: {str(e)}")
                    self._stop_event.wait(interval)
        finally:
            # Libera il pin, altrimenti il riavvio della lettura fallisce
            try:
                if dht_box[0] is not None:
                    dht_box[0].exit()
            except Exception:
                pass

        self.logger.info("Lettura AMBIENT interrotta")

    def read_now(self):
        '''
        Legge immediatamente i dati ambient.

        :return: tupla (temp, humidity, vpd, timestamp)
        '''
        from datetime import datetime

        pin = self.configs.get('dht22', {}).get('pin', 27)

        # Leggi i dati
        temp, humidity = self.measure_dht22(pin)
        vpd = self.VPD(temp, humidity)

        # Ottieni timestamp
        now = datetime.now()
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")

        # last_result usa il formato standard del progetto (%Y/%m/%d), non
        # quello restituito qui: cosi' la scheda Riepilogo non alterna due
        # formati di data. La tupla restituita resta invariata.
        self.last_result = {'timestamp': now.strftime("%Y/%m/%d %H:%M:%S"),
                            'temperature': temp, 'humidity': humidity, 'vpd': vpd}

        self.logger.info(f"AMBIENT (lettura immediata): T={temp:.2f}C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")
        return temp, humidity, vpd, timestamp
