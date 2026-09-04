#
# FnP - Daily Processor
# Elaborazione giornaliera di TUTTE le grandezze misurate:
#   - Temperatura, Umidità e VPD          (file TH_*.txt, sonda DHT22)
#   - pH, EC, TDS e salinità              (file WATER_*.txt, sonde su Arduino)
#   - Livello e volume del serbatoio      (file TANK_*.txt, HC-SR04 su Arduino)
#   - Altezza delle piante                (file GROWTH.csv, HC-SR04 su Arduino)
#   - Errori di lettura del giorno        (file ERRORS_*.txt)
#
# Il plot resta quello di T/H/VPD: le altre grandezze entrano nelle medie
# giornaliere caricate sul sito, non nel grafico.
#
# Esecuzione schedulata ogni giorno alle 00:01
# Elabora il file del giorno precedente: TH<YYYY>_<MM>_<DD>.txt
# Genera statistiche (media, max, min), plot e carica su GitHub via uploader.py
#
# Reference:
#   - Struttura dati TH: Fish and Plants notes.pdf (sec. DHT22 data logging)
#   - Uploader GitHub: uploader.py (FnP AeroGreenHouse repository)
#   - Schedule pattern: main.py / helper_aeroGreenHouse.py (FnP codebase)
#   - Plot style: test.py (FnP codebase)
#

import os
import re
import sys
import json
import logging
import schedule
import threading
import subprocess
import pandas as pd
from time import sleep
from datetime import datetime, timedelta

WHEN = "00:01"
NAME_FORMAT = "TH_%Y_%m_%d.txt"
WATER_NAME_FORMAT = "WATER_%Y_%m_%d.txt"
TANK_NAME_FORMAT = "TANK_%Y_%m_%d.txt"
GROWTH_CSV_NAME = "GROWTH.csv"

# ============================================================
# CONFIGURAZIONE
# Le directory dei dati e del plot arrivano dalla sezione Daily_Data di
# config.yaml; i valori qui sotto restano solo come default.
# ============================================================

# Directory dove si trovano i file TH (es. "/home/fishnplants/Desktop/data/TH/")
DEFAULT_TH_DATA_DIR = "/home/fishnplants/Desktop/data/TH/"

# Directory dei file delle altre grandezze
DEFAULT_WATER_DATA_DIR = "/home/fishnplants/Desktop/data/WATER/"
DEFAULT_TANK_DATA_DIR = "/home/fishnplants/Desktop/data/TANK/"
DEFAULT_GROWTH_DATA_DIR = "/home/fishnplants/Desktop/data/GROWTH/"

# Directory dove salvare il plot generato
DEFAULT_PLOT_OUTPUT_DIR = "/home/fishnplants/Desktop/data/PLOT/"

# Path completo dello script uploader.py
UPLOADER_SCRIPT = "/home/fishnplants/Desktop/codes/python/AeroGreenHouse/uploader/uploader.py"

# Nome del file plot di output (deve coincidere con quello atteso da uploader.py)
PLOT_FILENAME = "plot.png"

# ============================================================


# ===== LOGGING SETUP =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_yesterday_filename(data_dir: str) -> str:
    """
    Costruisce il path completo del file TH del giorno precedente.
    Formato nome file: TH<YYYY>_<MM>_<DD>.txt

    :param data_dir: Directory in cui cercare il file
    :return: Path completo del file
    
    Reference: struttura naming file TH - Fish and Plants notes.pdf
    """
    yesterday = datetime.now() - timedelta(days=1)
    filename = yesterday.strftime(NAME_FORMAT)
    return os.path.join(data_dir, filename), yesterday


def parse_th_file(filepath: str) -> pd.DataFrame:
    """
    Legge e parsa il file TH nel formato FnP standard:
    <timestamp>\t <temperatura>°C\t <umidità>%\t <vpd>kPa

    :param filepath: Path del file da leggere
    :return: DataFrame con colonne timestamp, temperature, humidity, vpd
    
    Reference: formato dati DHT22 - Fish and Plants notes.pdf, TH2025_09_18.txt
    """
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 4:
                try:
                    timestamp = datetime.strptime(parts[0].strip(), '%Y/%m/%d %H:%M:%S')
                    temperature = float(re.search(r'[\d.]+', parts[1]).group())
                    humidity    = float(re.search(r'[\d.]+', parts[2]).group())
                    vpd         = float(re.search(r'[\d.]+', parts[3]).group())
                    data.append({
                        'timestamp':   timestamp,
                        'temperature': temperature,
                        'humidity':    humidity,
                        'vpd':         vpd
                    })
                except (AttributeError, ValueError) as e:
                    logger.warning(f"Riga ignorata (formato non valido): {line.strip()} | Errore: {e}")

    if not data:
        raise ValueError(f"Nessun dato valido trovato nel file: {filepath}")

    return pd.DataFrame(data)


def compute_statistics(df: pd.DataFrame) -> dict:
    """
    Calcola media, massimo e minimo per temperatura, umidità e VPD.

    :param df: DataFrame con i dati del giorno
    :return: Dizionario con le statistiche calcolate
    
    Reference: avg_data.json (FnP AeroGreenHouse repository)
    """
    stats = {
        'avg_temperature': round(df['temperature'].mean(), 2),
        'avg_humidity':    round(df['humidity'].mean(),    2),
        'avg_vpd':         round(df['vpd'].mean(),         3),
        'max_T':  round(df['temperature'].max(), 2),
        'min_T':  round(df['temperature'].min(), 2),
        'max_H':  round(df['humidity'].max(),    2),
        'min_H':  round(df['humidity'].min(),    2),
        'max_VPD': round(df['vpd'].max(), 3),
        'min_VPD': round(df['vpd'].min(), 3),
    }
    logger.info(f"Statistiche calcolate: {stats}")
    return stats



def _parse_tab_file(filepath: str, colonne: list) -> pd.DataFrame:
    """
    Parser comune ai file tab-separated scritti dai manager delle sonde.

    Salta l'header e le righe malformate, e tratta il segnaposto '--'
    (usato quando un job scrive solo una parte delle colonne) come dato
    mancante, non come zero.

    :param filepath: file da leggere
    :param colonne:  nomi delle colonne dopo il timestamp, in ordine
    :return: DataFrame con 'timestamp' + le colonne richieste (vuoto se non
             c'e' nessuna riga valida)
    """
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Salta righe vuote e header
            if not line or line.startswith('datetime'):
                continue

            parts = line.split('\t')
            if len(parts) < len(colonne) + 1:
                continue

            try:
                riga = {'timestamp': datetime.strptime(parts[0].strip(), '%Y/%m/%d %H:%M:%S')}
            except ValueError:
                logger.warning(f"Riga ignorata (timestamp non valido): {line}")
                continue

            for i, nome in enumerate(colonne, start=1):
                campo = parts[i].strip()
                if not campo or campo == '--':
                    riga[nome] = None
                    continue
                trovato = re.search(r'-?[\d.]+', campo)
                riga[nome] = float(trovato.group()) if trovato else None

            data.append(riga)

    return pd.DataFrame(data)


def parse_water_file(filepath: str) -> pd.DataFrame:
    """
    Legge il file WATER giornaliero (pH, EC, TDS, salinità).

    Formato scritto da managers_classes/water_manager.save_water_data:
        <timestamp>\t <ph>\t <ec_uScm>\t <tds_ppm>\t <sal_psu>
    Le colonne non misurate da quel job valgono '--'.
    """
    return _parse_tab_file(filepath, ['ph', 'ec_us_cm', 'tds_ppm', 'salinity_psu'])


def parse_tank_file(filepath: str) -> pd.DataFrame:
    """
    Legge il file TANK giornaliero (livello e volume del serbatoio).

    Formato scritto da sensors/ultrasonic_sensor/ultrasonic_measurement.save_data:
        <timestamp>\t <dist_cm>\t <lvl_cm>\t <vol_L>\t <fill_%>
    """
    return _parse_tab_file(filepath,
                           ['distance_cm', 'water_level_cm', 'volume_L', 'fill_percent'])


def parse_growth_file(filepath: str, giorno) -> pd.DataFrame:
    """
    Legge dal file cumulativo GROWTH.csv le sole misure di un giorno.

    A differenza degli altri, lo storico della crescita e' un unico file che
    non si azzera ogni notte (le misure sono a cadenza di giorni), quindi va
    filtrato per data.

    :param giorno: datetime del giorno da estrarre
    """
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Salta righe vuote e header
            if not line or line.startswith('datetime'):
                continue
            try:
                ts_txt, altezza = line.split(',')
                timestamp = datetime.strptime(ts_txt.strip(), '%Y/%m/%d %H:%M:%S')
            except ValueError:
                logger.warning(f"Riga ignorata in {GROWTH_CSV_NAME}: {line}")
                continue

            if timestamp.date() != giorno.date():
                continue

            try:
                data.append({'timestamp': timestamp, 'h_plant_cm': float(altezza)})
            except ValueError:
                logger.warning(f"Riga ignorata in {GROWTH_CSV_NAME}: {line}")

    return pd.DataFrame(data)


def _stats_for(df: pd.DataFrame, colonna: str, prefisso: str, decimals: int = 2) -> dict:
    """
    Media, massimo e minimo di una colonna, saltando i valori mancanti.

    :return: dict con le chiavi avg_<prefisso>/max_<prefisso>/min_<prefisso>,
             oppure dict vuoto se per quel giorno non c'e' nessun dato: le
             grandezze non misurate NON devono comparire nel JSON con valori
             finti.
    """
    if df is None or df.empty or colonna not in df:
        return {}

    serie = pd.to_numeric(df[colonna], errors='coerce').dropna()
    if serie.empty:
        return {}

    return {
        f'avg_{prefisso}': round(serie.mean(), decimals),
        f'max_{prefisso}': round(serie.max(), decimals),
        f'min_{prefisso}': round(serie.min(), decimals),
    }


def compute_extra_statistics(df_water=None, df_tank=None, df_growth=None) -> dict:
    """
    Statistiche giornaliere delle grandezze lette dall'Arduino.

    Ogni blocco e' indipendente: se il serbatoio non e' stato letto ieri, le
    sue chiavi semplicemente non compaiono nel dizionario risultante.

    :return: dict con le chiavi avg_/max_/min_ delle grandezze disponibili
    """
    stats = {}
    stats.update(_stats_for(df_water, 'ph', 'ph'))
    stats.update(_stats_for(df_water, 'ec_us_cm', 'ec'))
    stats.update(_stats_for(df_water, 'tds_ppm', 'tds'))
    stats.update(_stats_for(df_water, 'salinity_psu', 'salinity'))
    stats.update(_stats_for(df_tank, 'water_level_cm', 'water_level'))
    stats.update(_stats_for(df_tank, 'volume_L', 'volume'))
    stats.update(_stats_for(df_tank, 'fill_percent', 'fill'))
    stats.update(_stats_for(df_growth, 'h_plant_cm', 'h_plant'))

    if stats:
        logger.info(f"Statistiche aggiuntive calcolate: {stats}")
    return stats


def _safe_parse(descrizione: str, funzione, *args):
    """
    Esegue un parser tollerando file mancanti o illeggibili.

    Le grandezze delle sonde su Arduino sono opzionali: se ieri il serbatoio
    non e' stato letto, il job giornaliero di T/H/VPD deve comunque arrivare
    in fondo.

    :return: DataFrame, oppure None se non c'e' nulla da leggere
    """
    filepath = args[0]
    if not os.path.exists(filepath):
        logger.info(f"{descrizione}: file non trovato ({filepath}), grandezza saltata.")
        return None
    try:
        df = funzione(*args)
    except Exception as e:
        logger.warning(f"{descrizione}: file non elaborabile ({filepath}): {e}")
        return None

    if df is None or df.empty:
        logger.info(f"{descrizione}: nessun dato valido in {filepath}.")
        return None

    logger.info(f"{descrizione}: {len(df)} righe lette da {filepath}")
    return df


def generate_plot(df: pd.DataFrame, output_dir: str, date_label: str):
    """
    Genera il plot con 3 subplot (temperatura, umidità, VPD) e lo salva come plot.png.

    :param df: DataFrame con i dati del giorno
    :param output_dir: Directory dove salvare il plot
    :param date_label: Stringa data per il titolo del plot (es. "2025-09-18")
    
    Reference: test.py (FnP codebase), Fish and Plants notes.pdf
    """
    import matplotlib
    matplotlib.use('Agg')  # Backend non-interattivo per salvataggio file
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, PLOT_FILENAME)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    fig.suptitle(f'FnP – Dati T/H/VPD del {date_label}', fontsize=14, fontweight='bold')

    # --- Temperatura ---
    axes[0].plot(df['timestamp'], df['temperature'], color='steelblue', linewidth=1.5, label='Temperatura')
    axes[0].set_ylabel('Temperatura (°C)', fontsize=11)
    axes[0].set_title('Temperatura vs Tempo', fontsize=12, fontweight='bold')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc='upper right', fontsize=9)

    # --- Umidità ---
    axes[1].plot(df['timestamp'], df['humidity'], color='seagreen', linewidth=1.5, label='Umidità')
    axes[1].set_ylabel('Umidità (%)', fontsize=11)
    axes[1].set_title('Umidità vs Tempo', fontsize=12, fontweight='bold')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc='upper right', fontsize=9)

    # --- VPD ---
    axes[2].plot(df['timestamp'], df['vpd'], color='tomato', linewidth=1.5, label='VPD')
    axes[2].set_ylabel('VPD (kPa)', fontsize=11)
    axes[2].set_xlabel('Ora', fontsize=11)
    axes[2].set_title('VPD vs Tempo', fontsize=12, fontweight='bold')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc='upper right', fontsize=9)

    # Formattazione asse X comune
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig(output_path, dpi=250, bbox_inches='tight')
    plt.close(fig)

    logger.info(f"Plot salvato in: {output_path}")
    return output_path


# Grandezze opzionali: (prefisso nelle stats, flag da passare all'uploader).
# Le chiavi assenti dalle stats (grandezza non misurata quel giorno) non
# generano alcun argomento, cosi' l'uploader le omette dal JSON.
EXTRA_UPLOAD_FLAGS = (
    ('ph', '-avgph', '-maxph', '-minph'),
    ('ec', '-avgec', '-maxec', '-minec'),
    ('tds', '-avgtds', '-maxtds', '-mintds'),
    ('salinity', '-avgsal', '-maxsal', '-minsal'),
    ('water_level', '-avglvl', '-maxlvl', '-minlvl'),
    ('volume', '-avgvol', '-maxvol', '-minvol'),
    ('fill', '-avgfill', '-maxfill', '-minfill'),
    ('h_plant', '-avghp', '-maxhp', '-minhp'),
)


def _extra_upload_args(stats: dict) -> list:
    """
    Traduce le statistiche opzionali negli argomenti da riga di comando.

    :param stats: dizionario completo delle statistiche del giorno
    :return: lista piatta di argomenti, vuota se non c'e' nessuna grandezza
             aggiuntiva disponibile
    """
    args = []
    for prefisso, flag_avg, flag_max, flag_min in EXTRA_UPLOAD_FLAGS:
        for flag, chiave in ((flag_avg, f'avg_{prefisso}'),
                             (flag_max, f'max_{prefisso}'),
                             (flag_min, f'min_{prefisso}')):
            if chiave in stats:
                args += [flag, str(stats[chiave])]
    return args


def call_uploader(stats: dict, timestamp_str: str, errors: list = None):
    """
    Invoca uploader.py per caricare le statistiche medie e il plot su GitHub.

    :param stats: Dizionario con le statistiche del giorno (T/H/VPD piu' le
                  grandezze opzionali di acqua, serbatoio e crescita)
    :param timestamp_str: Timestamp da passare all'uploader
    :param errors: elenco degli errori di lettura del giorno, gia' nel
                   formato {'timestamp', 'source', 'message'}

    Reference: uploader.py – comandi 'averages' e 'plot' (FnP AeroGreenHouse repository)
    """
    python_exec = sys.executable  # usa lo stesso interprete Python attivo

    # --- Carica le medie ---
    avg_cmd = [
        python_exec, UPLOADER_SCRIPT, 'averages',
        '-avgt',   str(stats['avg_temperature']),
        '-avgh',   str(stats['avg_humidity']),
        '-avgvpd', str(stats['avg_vpd']),
        '-maxT', str(stats['max_T']),
        '-maxH', str(stats['max_H']),
        '-maxVPD', str(stats['max_VPD']),
        '-minT', str(stats['min_T']),
        '-minH', str(stats['min_H']),
        '-minVPD', str(stats['min_VPD']),
        '-ts',     timestamp_str
    ]
    avg_cmd += _extra_upload_args(stats)

    if errors:
        # Gli errori viaggiano come stringa JSON: sono una lista di record,
        # non un valore scalare, e i flag di argparse non li reggerebbero.
        avg_cmd += ['-err', json.dumps(errors, ensure_ascii=False)]

    logger.info(f"Eseguo uploader averages: {' '.join(avg_cmd)}")
    result_avg = subprocess.run(avg_cmd, capture_output=True, text=True)
    if result_avg.returncode == 0:
        logger.info(f"Upload medie OK: {result_avg.stdout.strip()}")
    else:
        logger.error(f"Errore upload medie: {result_avg.stderr.strip()}")

    # --- Carica il plot ---
    plot_cmd = [python_exec, UPLOADER_SCRIPT, 'plot']
    logger.info(f"Eseguo uploader plot: {' '.join(plot_cmd)}")
    result_plot = subprocess.run(plot_cmd, capture_output=True, text=True)
    if result_plot.returncode == 0:
        logger.info(f"Upload plot OK: {result_plot.stdout.strip()}")
    else:
        logger.error(f"Errore upload plot: {result_plot.stderr.strip()}")


def daily_job(th_data_dir=DEFAULT_TH_DATA_DIR, plot_output_dir=DEFAULT_PLOT_OUTPUT_DIR,
              upload=True, log=logger, water_data_dir=DEFAULT_WATER_DATA_DIR,
              tank_data_dir=DEFAULT_TANK_DATA_DIR,
              growth_data_dir=DEFAULT_GROWTH_DATA_DIR, errors_recorder=None):
    """
    Job principale eseguito alle 00:01 ogni giorno.
    Pipeline:
      1. Individua i file del giorno precedente
      2. Parsa i dati T/H/VPD (obbligatori) e quelli delle sonde su Arduino
         (acqua, serbatoio, crescita: opzionali)
      3. Calcola le statistiche
      4. Genera il plot T/H/VPD
      5. Raccoglie gli errori di lettura del giorno
      6. Carica medie, errori e plot su GitHub via uploader.py

    :param th_data_dir: directory dei file TH giornalieri
    :param plot_output_dir: directory in cui salvare il plot
    :param upload: se False salta l'upload (usato per ripopolare la GUI
                   all'avvio senza ricaricare su GitHub dati gia' caricati)
    :param log: logger da usare (quello condiviso quando gira dentro la GUI)
    :param water_data_dir: directory dei file WATER (pH, EC)
    :param tank_data_dir: directory dei file TANK (livello serbatoio)
    :param growth_data_dir: directory del file GROWTH.csv (altezza piante)
    :param errors_recorder: ErrorRecorder da cui rileggere gli errori di ieri
    :return: dict con stats, plot_path, date_label ed errors, oppure None se il
             file T/H del giorno precedente non esiste o non contiene dati validi.

    Reference: schedule pattern - main.py / helper_aeroGreenHouse.py (FnP codebase)
    """
    log.info("===== FnP Daily Processor - START =====")

    try:
        # 1. Path file giorno precedente
        filepath, yesterday = get_yesterday_filename(th_data_dir)
        date_label = yesterday.strftime("%Y-%m-%d")
        timestamp_str = yesterday.strftime("%Y-%m-%d")

        log.info(f"Elaborazione file: {filepath}")

        # T/H/VPD e' l'unica grandezza obbligatoria: senza di essa non ha
        # senso produrre le medie giornaliere.
        if not os.path.exists(filepath):
            log.error(f"File non trovato: {filepath}. Job saltato.")
            return None

        # 2. Parsing dati
        df = parse_th_file(filepath)
        log.info(f"Righe lette: {len(df)}")

        # 2b. Grandezze lette dall'Arduino: opzionali, ognuna indipendente
        df_water = _safe_parse(
            'ACQUA (pH/EC)', parse_water_file,
            os.path.join(water_data_dir, yesterday.strftime(WATER_NAME_FORMAT)))
        df_tank = _safe_parse(
            'SERBATOIO', parse_tank_file,
            os.path.join(tank_data_dir, yesterday.strftime(TANK_NAME_FORMAT)))
        df_growth = _safe_parse(
            'CRESCITA', parse_growth_file,
            os.path.join(growth_data_dir, GROWTH_CSV_NAME), yesterday)

        # 3. Calcolo statistiche
        stats = compute_statistics(df)
        stats.update(compute_extra_statistics(df_water, df_tank, df_growth))

        # 4. Generazione plot
        plot_path = generate_plot(df, plot_output_dir, date_label)

        # 5. Errori di lettura registrati ieri
        errors = []
        if errors_recorder is not None:
            try:
                errors = errors_recorder.load_for_date(yesterday.date())
            except Exception as e:
                log.warning(f"Errori del giorno non rileggibili: {e}")

        # 6. Upload su GitHub
        if upload:
            call_uploader(stats, timestamp_str, errors=errors)

        log.info("===== FnP Daily Processor - DONE =====")
        return {'stats': stats, 'plot_path': plot_path,
                'date_label': date_label, 'errors': errors}

    except FileNotFoundError as e:
        log.error(f"File non trovato: {e}")
    except ValueError as e:
        log.error(f"Errore nei dati: {e}")
    except Exception as e:
        log.exception(f"Errore inatteso nel job giornaliero: {e}")

    return None


# =====================================================================
# Categoria DAILY (elaborazione giornaliera schedulata)
# =====================================================================
class DailyTHManager():
    '''
    Manager dell'elaborazione giornaliera T/H/VPD.

    Stessa forma degli altri manager (is_running / start / stop su un thread
    daemon), cosi' la GUI puo' comandarlo e mostrarne la spia di stato accanto
    agli altri processi. Conserva l'esito dell'ultimo job (statistiche e path
    del plot) perche' la scheda Ambiente possa mostrarlo.
    '''

    def __init__(self, configs, logger_, errors=None):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger_: logger condiviso
        :param errors:  ErrorRecorder condiviso, da cui rileggere gli errori
                        del giorno elaborato (opzionale: senza, il job gira
                        lo stesso e carica solo le medie)
        '''
        self.configs = configs
        self.logger = logger_
        self._errors = errors

        # Esito dell'ultimo job: popolato da _run_job e ricaricato all'avvio
        self.last_stats = None
        self.last_plot_path = None
        self.last_date_label = None
        self.last_errors = []

        self._thread = None
        self._stop_event = threading.Event()

    ###########################################
    # Configurazione
    ###########################################
    def th_data_dir(self):
        '''Directory dei file TH giornalieri (sezione Daily_Data del config).'''
        return self.configs.get('Daily_Data', {}).get('th_data_dir', DEFAULT_TH_DATA_DIR)

    def water_data_dir(self):
        '''Directory dei file WATER giornalieri (pH ed EC).'''
        return self.configs.get('Daily_Data', {}).get('water_data_dir',
                                                      DEFAULT_WATER_DATA_DIR)

    def tank_data_dir(self):
        '''Directory dei file TANK giornalieri (livello serbatoio).'''
        return self.configs.get('Daily_Data', {}).get('tank_data_dir',
                                                      DEFAULT_TANK_DATA_DIR)

    def growth_data_dir(self):
        '''Directory del file cumulativo GROWTH.csv (altezza piante).'''
        return self.configs.get('Daily_Data', {}).get('growth_data_dir',
                                                      DEFAULT_GROWTH_DATA_DIR)

    def plot_output_dir(self):
        '''Directory in cui salvare il plot (sezione Daily_Data del config).'''
        return self.configs.get('Daily_Data', {}).get('plot_output_dir',
                                                      DEFAULT_PLOT_OUTPUT_DIR)

    ###########################################
    # Esecuzione
    ###########################################
    def is_running(self):
        '''True se il thread dello scheduler giornaliero e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start(self, on_done=None):
        '''
        Avvia lo scheduler giornaliero in un thread.

        Il job viene anche eseguito subito (senza upload) per popolare le
        statistiche: altrimenti la scheda Ambiente resterebbe vuota fino alla
        mezzanotte successiva.

        :param on_done: callback opzionale on_done(result) chiamata a fine job
        :return: False se e' gia' in esecuzione, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._schedule_loop,
                                        args=(on_done,), daemon=True)
        self._thread.start()
        return True

    def stop(self):
        '''Arresta lo scheduler giornaliero. False se non era in esecuzione.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def run_now(self, upload=True, on_done=None):
        '''
        Esegue subito il job sul file del giorno precedente.

        :return: il dict di daily_job (None se non c'era nulla da elaborare)
        '''
        result = daily_job(self.th_data_dir(), self.plot_output_dir(),
                           upload=upload, log=self.logger,
                           water_data_dir=self.water_data_dir(),
                           tank_data_dir=self.tank_data_dir(),
                           growth_data_dir=self.growth_data_dir(),
                           errors_recorder=self._errors)
        if result is not None:
            self.last_stats = result['stats']
            self.last_plot_path = result['plot_path']
            self.last_date_label = result['date_label']
            self.last_errors = result.get('errors', [])
            if on_done is not None:
                on_done(result)
        return result

    def _schedule_loop(self, on_done):
        '''
        Loop dello scheduler.

        L'attesa usa _stop_event.wait invece di sleep: "Arresta Daily" deve
        avere effetto subito, non entro 30 secondi.
        '''
        self.logger.info(f"FnP Daily Processor avviato - job schedulato alle {WHEN}")

        # Primo giro senza upload: serve solo a popolare la GUI con i dati di ieri
        self.run_now(upload=False, on_done=on_done)

        job = schedule.every().day.at(WHEN).do(self.run_now, True, on_done)
        try:
            while not self._stop_event.is_set():
                schedule.run_pending()
                self._stop_event.wait(30)  # polling ogni 30 s per non saturare la CPU
        finally:
            # Senza questo, riavviare il processo accumulerebbe job duplicati
            # nello scheduler globale della libreria schedule.
            schedule.cancel_job(job)

        self.logger.info("FnP Daily Processor interrotto")


# ============================================================
# ENTRY POINT - Scheduler
# ============================================================

if __name__ == "__main__":
    import yaml

    config_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
    with open(config_file, "r") as f:
        configs = yaml.safe_load(f)

    manager = DailyTHManager(configs, logger)
    manager.start()

    try:
        while manager.is_running():
            sleep(1)
    except KeyboardInterrupt:
        manager.stop()
        logger.info("FnP Daily TH Processor terminato dall'utente.")
