import os
import threading
from datetime import datetime
from statistics import mean

from managers_classes.arduino_link import ArduinoError
from managers_classes.data_config import round_decimals, DEFAULT_DECIMALS


# =====================================================================
# Default (usati se la sezione 'plant_growth' di config.yaml e' incompleta)
# =====================================================================

READ_INTERVAL_DAYS = 1     # ogni quanti giorni misurare
N_SAMPLES = 3              # misure da mediare ad ogni campionamento
REFERENCE_HEIGHT_CM = 70.0  # distanza sensore -> camera radicale a pianta assente
HISTORY_LEN = 30            # punti tenuti in memoria per grafico e tabella
SAVE_DIR = "/home/fishnplants/Desktop/data/GROWTH/"
CSV_NAME = "GROWTH.csv"

SECONDS_PER_DAY = 86400

# File di configurazione su cui la calibrazione scrive il riferimento.
# Path relativo, come in aeroHelper e gui.py: richiede cwd = radice del progetto.
CONFIG_FILE = "config.yaml"


# =====================================================================
# Salvataggio / lettura dello storico (file unico cumulativo)
# =====================================================================

def save_growth_data(result: dict, save_dir: str) -> None:
    '''
    Aggiunge una misura al file cumulativo GROWTH.csv.

    Formato (due colonne, data nello stesso formato dei dati TH):
        datetime,h_plant_cm
        2026/07/17 09:41:03,5.2

    :param result:   dict con 'timestamp' e 'h_plant_cm'
    :param save_dir: directory di salvataggio
    '''
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, CSV_NAME)

    # Header scritto solo se il file non esiste ancora
    write_header = not os.path.exists(file_path)
    with open(file_path, "a") as f:
        if write_header:
            f.write("datetime,h_plant_cm\n")
        f.write(f"{result['timestamp']},{result['h_plant_cm']}\n")


def load_growth_data(save_dir: str, max_rows: int = None, logger=None) -> list:
    '''
    Rilegge lo storico da GROWTH.csv.

    :param save_dir: directory dei dati di crescita
    :param max_rows: se valorizzato, tiene solo le ultime N misure
    :param logger:   logger opzionale per segnalare le righe malformate
    :return:         lista di dict {'timestamp', 'h_plant_cm'} in ordine
                     cronologico crescente (lista vuota se il file non esiste)
    '''
    file_path = os.path.join(save_dir, CSV_NAME)
    if not os.path.exists(file_path):
        return []

    history = []
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            # Salta righe vuote e header
            if not line or line.startswith("datetime"):
                continue
            try:
                timestamp, height = line.split(",")
                history.append({
                    'timestamp': timestamp.strip(),
                    'h_plant_cm': float(height),
                })
            except ValueError:
                if logger is not None:
                    logger.warning(f"GROWTH: riga ignorata in {CSV_NAME}: {line!r}")

    if max_rows is not None:
        history = history[-max_rows:]
    return history


def save_reference_height(value_cm: float, config_file: str = None) -> None:
    '''
    Scrive l'altezza di riferimento in config.yaml, senza toccare altro.

    Il file viene riletto da disco, si aggiorna la sola chiave
    plant_growth.reference_height_cm e si riscrive. Deliberatamente NON si
    riversa il dizionario in memoria del manager: in simulazione (test_gui.py)
    quel dizionario contiene percorsi finti, che finirebbero nel config reale.

    :param value_cm:    altezza di riferimento misurata [cm]
    :param config_file: file di configurazione (default: CONFIG_FILE del modulo)
    '''
    import yaml

    if config_file is None:
        # Risolto qui e non come default dell'argomento, altrimenti il valore
        # verrebbe congelato all'import e non sarebbe piu' dirottabile.
        config_file = CONFIG_FILE

    with open(config_file, "r") as f:
        cfg = yaml.safe_load(f) or {}

    cfg.setdefault('plant_growth', {})['reference_height_cm'] = value_cm

    with open(config_file, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


# =====================================================================
# Categoria CRESCITA (altezza pianta via sensore ultrasonico HC-SR04)
# =====================================================================
class PlantGrowthManager():
    '''
    Class per la misura dell'altezza delle piante tramite un sensore
    ultrasonico HC-SR04 posto sopra la camera radicale.

    Il sensore NON e' piu' collegato ai GPIO del Raspberry: e' attaccato a un
    Arduino UNO, che lo legge su richiesta e restituisce la distanza via
    seriale USB (vedi managers_classes/arduino_link.py). Il Raspberry
    conserva la logica di controllo temporizzato e il calcolo dell'altezza.

    L'altezza della pianta e' la differenza tra la distanza di riferimento
    (sensore -> camera radicale, misurata a pianta assente) e la distanza
    letta dal sensore:

        h_plant = reference_height_cm - distanza_misurata

    Esempio: sensore a 70cm, pianta non ancora cresciuta -> misura 70cm
             -> h_plant = 0cm. Se la misura scende a 65cm -> h_plant = 5cm.

    I parametri sono letti dalla sezione 'plant_growth' di config.yaml.
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

        self.last_result = None
        self._thread = None
        self._stop_event = threading.Event()

        # Storico gia' salvato su file (serve a grafico e tabella della GUI)
        self.history = self.load_history()

    def _params(self):
        '''Legge i parametri dalla sezione 'plant_growth' di config.yaml con fallback ai default del modulo.'''
        g = self.configs.get('plant_growth', {}) or {}
        return dict(
            interval_days=g.get('read_interval_days', READ_INTERVAL_DAYS),
            n=g.get('n_samples', N_SAMPLES),
            reference=g.get('reference_height_cm', REFERENCE_HEIGHT_CM),
            decimals=g.get('decimals', DEFAULT_DECIMALS),
            save_enabled=g.get('save', True),
            save_dir=g.get('saving_dir', SAVE_DIR),
            history_len=g.get('history_len', HISTORY_LEN),
        )

    def load_history(self):
        '''Rilegge lo storico delle misure da GROWTH.csv (ordine cronologico crescente).'''
        p = self._params()
        try:
            return load_growth_data(p['save_dir'], max_rows=p['history_len'], logger=self.logger)
        except Exception as e:
            self.logger.error(f"GROWTH: errore nella lettura dello storico: {e}")
            return []

    def _measure_mean_distance(self, p):
        '''
        Media di n_samples letture chieste all'Arduino, con validazione.

        Unica definizione di "misura valida": la usano sia read_now() sia
        calibration_distance().

        A ripetere le letture e' il Raspberry: allo sketch Arduino si chiede
        una misura alla volta, cosi' la politica di campionamento resta
        configurabile da config.yaml senza ricompilare la scheda.

        :param p: parametri correnti (da _params())
        :return:  distanza in cm, oppure None se la misura non e' valida.
        '''
        letture = []
        ultimo_errore = None

        for _ in range(max(1, int(p['n']))):
            try:
                letture.append(self._arduino.read_float('US_plant'))
            except ArduinoError as e:
                ultimo_errore = e

        if not letture:
            self._errors.record(
                'US_plant',
                "Non è stato possibile leggere il sensore ultrasonico della crescita, "
                f"controlla il motivo: "
                f"{ultimo_errore.message if ultimo_errore else 'nessuna lettura valida'}"
            )
            return None

        dist = mean(letture)

        # Range fisico del sensore (2-400 cm per HC-SR04)
        if dist < 2.0 or dist > 400.0:
            self._errors.record(
                'US_plant',
                f"Non è stato possibile leggere il sensore ultrasonico della crescita, "
                f"controlla il motivo: distanza {dist:.1f}cm fuori dal range operativo "
                f"(2-400cm). Misura ignorata."
            )
            return None

        return dist

    def calibration_distance(self):
        '''
        Tara l'altezza di riferimento misurandola con il sensore stesso.

        Va eseguita a camera radicale vuota (piante non ancora cresciute): la
        distanza letta in quel momento e' per definizione il riferimento, cioe'
        lo zero da cui si contera' la crescita.

        Il valore viene scritto in config.yaml e aggiornato anche nella
        configurazione in memoria: _params() la rilegge ad ogni chiamata, quindi
        la misura successiva usa il nuovo riferimento senza riavviare il
        programma.

        :return: riferimento misurato in cm, oppure None se la misura non e' valida.
        '''
        p = self._params()

        dist = self._measure_mean_distance(p)
        if dist is None:
            self.logger.warning("GROWTH: calibrazione non eseguita, misura non valida.")
            return None

        reference = round_decimals(dist, p['decimals'])

        save_reference_height(reference)
        self.configs.setdefault('plant_growth', {})['reference_height_cm'] = reference

        self.logger.info(f"GROWTH: calibrazione eseguita, riferimento = {reference}cm "
                         f"(era {p['reference']}cm)")
        return reference

    def read_now(self):
        '''
        Esegue una misura singola dell'altezza della pianta (media di n_samples letture).

        La misura viene salvata su file se 'save' e' attivo in config.yaml: a
        differenza del serbatoio, qui la misura manuale e' un caso d'uso primario.

        :return: dict con timestamp, distance_cm, h_plant_cm
                 oppure None se la misura non e' valida.
        '''
        p = self._params()

        dist = self._measure_mean_distance(p)
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        if dist is None:
            return None

        # Altezza pianta = riferimento - distanza letta (clipping: non puo' essere negativa)
        h_plant = max(0.0, p['reference'] - dist)

        result = {
            'timestamp': timestamp,
            'distance_cm': round_decimals(dist, p['decimals']),
            'h_plant_cm': round_decimals(h_plant, p['decimals']),
        }
        self.last_result = result

        self.logger.info(
            f"GROWTH: dist={result['distance_cm']}cm | "
            f"riferimento={p['reference']}cm | "
            f"altezza pianta={result['h_plant_cm']}cm"
        )

        if p['save_enabled']:
            try:
                save_growth_data(result, p['save_dir'])
            except Exception as e:
                self.logger.error(f"GROWTH: errore nel salvataggio dati: {e}")

        # Aggiorna lo storico in memoria (grafico e tabella della GUI)
        self.history.append({'timestamp': result['timestamp'],
                             'h_plant_cm': result['h_plant_cm']})
        self.history = self.history[-p['history_len']:]

        return result

    def is_running(self):
        '''True se il thread di misura della crescita e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la misura temporizzata dell'altezza pianta in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una misura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la misura della crescita. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''
        Loop per misure periodiche della crescita (sleep interrompibile per stop immediato).

        La prima misura parte subito all'avvio, poi si attende l'intervallo
        configurato: cosi' non serve aspettare giorni per avere un dato.
        '''
        p = self._params()
        self.logger.info(f"Inizio misura GROWTH. Intervallo: {p['interval_days']} giorni, "
                         f"Campioni: {p['n']}, Riferimento: {p['reference']}cm")

        while not self._stop_event.is_set():
            try:
                result = self.read_now()  # read_now salva gia' su file
                if result is not None and on_update is not None:
                    on_update(result)

            except Exception as e:
                self.logger.error(f"Errore misura GROWTH: {str(e)}")

            # Attendi l'intervallo (interrompibile)
            self._stop_event.wait(self._params()['interval_days'] * SECONDS_PER_DAY)

        self.logger.info("Misura GROWTH interrotta")
