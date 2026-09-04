import glob
import os
import threading
from statistics import median

from managers_classes.arduino_link import ArduinoError


# Nome dei file giornalieri scritti da ultrasonic_measurement.save_data
TANK_FILE_GLOB = "TANK_*.txt"


# =====================================================================
# Rilettura dell'ultimo dato salvato
# =====================================================================

def load_last_tank(save_dir: str) -> dict:
    '''
    Rilegge l'ultima misura del serbatoio salvata su file.

    Serve alla scheda Riepilogo: il livello e' l'unico dato che oggi si
    perderebbe ad ogni riavvio del programma.

    Formato della riga (tab-separated, header solo se il file e' nuovo):
        datetime\t\t\t dist_cm\t lvl_cm\t vol_L\t fill_%
        2026/07/17 09:41:03\t  12.4\t  19.6\t  17.64\t 65.3

    Vive qui e non in ultrasonic_measurement.py perche' quel modulo importa
    RPi.GPIO a livello di modulo, mentre leggere un file di testo non ha alcun
    bisogno della GPIO.

    Viene scelto il file piu' recente: il nome TANK_%Y_%m_%d.txt ordina
    cronologicamente anche come stringa.

    :param save_dir: directory dei dati TANK
    :return: dict con distance_cm, water_level_cm, volume_L, fill_percent,
             timestamp; oppure None se non c'e' nessuna misura leggibile.
    '''
    files = sorted(glob.glob(os.path.join(save_dir, TANK_FILE_GLOB)))
    if not files:
        return None

    try:
        with open(files[-1], "r") as f:
            righe = f.readlines()
    except OSError:
        return None

    for line in reversed(righe):
        line = line.strip()
        # Salta righe vuote e header
        if not line or line.startswith("datetime"):
            continue
        campi = line.split("\t")
        if len(campi) < 5:
            continue
        try:
            return {
                'timestamp': campi[0].strip(),
                'distance_cm': float(campi[1]),
                'water_level_cm': float(campi[2]),
                'volume_L': float(campi[3]),
                'fill_percent': float(campi[4]),
            }
        except ValueError:
            continue  # riga malformata

    return None


# =====================================================================
# Categoria SERBATOIO (livello acqua via HC-SR04 collegato all'Arduino UNO)
# =====================================================================
class TankManager():
    '''
    Class per la lettura del livello dell'acqua nel serbatoio tramite il
    sensore ultrasonico HC-SR04.

    Il sensore NON e' piu' collegato ai GPIO del Raspberry: e' attaccato a un
    Arduino UNO, che lo legge su richiesta e restituisce la distanza via
    seriale USB (vedi managers_classes/arduino_link.py). Il Raspberry
    conserva la logica di controllo temporizzato e la conversione
    distanza -> volume, che resta quella di
    sensors/ultrasonic_sensor/ultrasonic_measurement.py (nessuna riscrittura
    della fisica).

    I parametri di taratura sono letti dalla sezione 'tank' di config.yaml.
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

        self._thread = None
        self._stop_event = threading.Event()

        # Riuso del modulo standalone per la sola matematica del volume e per
        # il salvataggio su file (resta eseguibile da solo con i suoi GPIO).
        from sensors.ultrasonic_sensor import ultrasonic_measurement as tank_mod
        self._tank = tank_mod

        # Ultima misura salvata (serve alla scheda Riepilogo gia' all'avvio).
        # Va dopo self._tank: _params() usa le costanti del modulo come default.
        self.last_result = self.load_last_reading()

    def _params(self):
        '''Legge i parametri dalla sezione 'tank' di config.yaml con fallback alle costanti del modulo.'''
        t = self.configs.get('tank', {}) or {}
        return dict(
            height=t.get('tank_height_cm', self._tank.TANK_HEIGHT_CM),
            offset=t.get('sensor_offset_cm', self._tank.SENSOR_OFFSET_CM),
            area=t.get('tank_area_cm2', self._tank.TANK_AREA_CM2),
            low=t.get('water_low_threshold_l', self._tank.WATER_LOW_THRESHOLD_L),
            interval=t.get('read_interval', self._tank.READ_INTERVAL_S),
            n=t.get('n_samples', self._tank.N_SAMPLES),
            save=t.get('saving_dir', self._tank.SAVE_DIR),
        )

    def load_last_reading(self):
        '''Rilegge da file l'ultima misura del serbatoio salvata (None se non c'e').'''
        try:
            return load_last_tank(self._params()['save'])
        except Exception as e:
            self.logger.error(f"TANK: errore nella rilettura dell'ultimo dato: {e}")
            return None

    def _measure_distance(self, n_samples):
        '''
        Chiede n_samples letture all'Arduino e ne restituisce la MEDIANA.

        La mediana (e non la media) e' la stessa scelta gia' fatta da
        ultrasonic_measurement.measure_distance_avg(): un singolo eco
        spurio non deve spostare la misura.

        A differenza di prima, a ripetere le letture e' il Raspberry: allo
        sketch Arduino si chiede una misura alla volta, cosi' resta un
        esecutore semplice e la politica di campionamento resta configurabile
        da config.yaml.

        :return: distanza in cm, oppure None se nessuna lettura e' riuscita.
        '''
        letture = []
        ultimo_errore = None

        for _ in range(max(1, int(n_samples))):
            try:
                letture.append(self._arduino.read_float('US_water'))
            except ArduinoError as e:
                ultimo_errore = e

        if not letture:
            self._errors.record(
                'US_water',
                "Non è stato possibile leggere il sensore ultrasonico del serbatoio, "
                f"controlla il motivo: {ultimo_errore.message if ultimo_errore else 'nessuna lettura valida'}"
            )
            return None

        return median(letture)

    def read_now(self):
        '''
        Esegue una misura singola del livello serbatoio.

        :return: dict con distance_cm, water_level_cm, volume_L, fill_percent, timestamp
                 oppure None se la misura non e' valida.
        '''
        from datetime import datetime

        p = self._params()

        dist = self._measure_distance(p['n'])
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        if dist is None:
            return None

        # Range fisico del sensore (2-400 cm per HC-SR04)
        if dist < 2.0 or dist > 400.0:
            self._errors.record(
                'US_water',
                f"Non è stato possibile leggere il sensore ultrasonico del serbatoio, "
                f"controlla il motivo: distanza {dist:.1f}cm fuori dal range operativo "
                f"(2-400cm). Misura ignorata."
            )
            return None

        result = self._tank.distance_to_water_volume(dist, p['height'], p['offset'], p['area'])
        result['timestamp'] = timestamp
        self.last_result = result

        self.logger.info(
            f"TANK: dist={result['distance_cm']}cm | "
            f"livello={result['water_level_cm']}cm | "
            f"volume={result['volume_L']}L | "
            f"fill={result['fill_percent']}%"
        )
        return result

    def is_running(self):
        '''True se il thread di lettura serbatoio e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata del livello serbatoio in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la lettura serbatoio. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche del serbatoio (sleep interrompibile per stop immediato).'''
        p = self._params()
        self.logger.info(f"Inizio lettura TANK. Intervallo: {p['interval']}s, Campioni: {p['n']}")

        while not self._stop_event.is_set():
            try:
                result = self.read_now()
                if result is not None:
                    # Salvataggio su file (riusa save_data del modulo)
                    try:
                        self._tank.save_data(result, p['save'])
                    except Exception as e:
                        self.logger.error(f"TANK: errore nel salvataggio dati: {e}")

                    # Allarme livello basso
                    if result['volume_L'] < p['low']:
                        self.logger.warning(
                            f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                            f"sotto la soglia di {p['low']}L! Riempire la tanica."
                        )

                    if on_update is not None:
                        on_update(result)

            except Exception as e:
                self.logger.error(f"Errore lettura TANK: {str(e)}")

            # Attendi l'intervallo (interrompibile)
            self._stop_event.wait(self._params()['interval'])

        self.logger.info("Lettura TANK interrotta")
