import glob
import os
import re
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
    def upload_data_on_web(self, T, H, vpd, timestamp):
        '''
        This module upload the data on website calling the local uploader.py module
        '''
        os.system(f'python uploader/uploader.py data -t {T} -hu {H} -vpd {vpd} -ts "{timestamp}"')

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
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la lettura temporizzata. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche (logica originale, sleep interrompibile per stop immediato).'''
        import adafruit_dht
        import board
        from datetime import datetime

        interval = self.configs.get('dht22', {}).get('read_interval', 5)
        pin = self.configs.get('dht22', {}).get('pin', 27)

        self.logger.info(f"Inizio lettura AMBIENT. Intervallo: {interval}s, Pin: {pin}")
        dht = eval(f"adafruit_dht.DHT22(board.D{pin})")

        def measure_dht_22(dht):
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

        while not self._stop_event.is_set():
            try:
                # Leggi i dati
                temp, humidity = measure_dht_22(dht)
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

                # carica file online
                try:
                    self.upload_data_on_web(temp, humidity, vpd, timestamp)
                except:
                    self.logger(f"AMBIENT: not able to upload the ambient data online. Check errors if occured")

                # Attendi l'intervallo (interrompibile)
                self._stop_event.wait(interval)

            except Exception as e:
                self.logger.error(f"Errore lettura AMBIENT: {str(e)}")
                self._stop_event.wait(interval)

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
