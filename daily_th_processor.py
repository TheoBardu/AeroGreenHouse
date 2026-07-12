#
# FnP - Daily TH Processor
# Elaborazione giornaliera dati Temperatura, Umidità e VPD
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
import logging
import schedule
import subprocess
import matplotlib
matplotlib.use('Agg')  # Backend non-interattivo per salvataggio file
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from time import sleep
from datetime import datetime, timedelta

WHEN = "00:01"
NAME_FORMAT = "TH_%Y_%m_%d.txt"

# ============================================================
# CONFIGURAZIONE - modifica queste variabili secondo necessità
# ============================================================

# Directory dove si trovano i file TH (es. "/home/fishnplants/Desktop/data/TH/")
TH_DATA_DIR = "/home/fishnplants/Desktop/data/TH/"

# Directory dove salvare il plot generato
PLOT_OUTPUT_DIR = "/home/fishnplants/Desktop/data/PLOT/"

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


def generate_plot(df: pd.DataFrame, output_dir: str, date_label: str):
    """
    Genera il plot con 3 subplot (temperatura, umidità, VPD) e lo salva come plot.png.

    :param df: DataFrame con i dati del giorno
    :param output_dir: Directory dove salvare il plot
    :param date_label: Stringa data per il titolo del plot (es. "2025-09-18")
    
    Reference: test.py (FnP codebase), Fish and Plants notes.pdf
    """
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


def call_uploader(stats: dict, timestamp_str: str):
    """
    Invoca uploader.py per caricare le statistiche medie e il plot su GitHub.

    :param stats: Dizionario con le statistiche del giorno
    :param timestamp_str: Timestamp da passare all'uploader

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


def daily_job():
    """
    Job principale eseguito alle 00:01 ogni giorno.
    Pipeline:
      1. Individua il file TH del giorno precedente
      2. Parsa i dati
      3. Calcola le statistiche
      4. Genera il plot
      5. Carica medie e plot su GitHub via uploader.py
    
    Reference: schedule pattern - main.py / helper_aeroGreenHouse.py (FnP codebase)
    """
    logger.info("===== FnP Daily TH Processor - START =====")

    try:
        # 1. Path file giorno precedente
        filepath, yesterday = get_yesterday_filename(TH_DATA_DIR)
        date_label = yesterday.strftime("%Y-%m-%d")
        timestamp_str = yesterday.strftime("%Y-%m-%d")

        logger.info(f"Elaborazione file: {filepath}")

        if not os.path.exists(filepath):
            logger.error(f"File non trovato: {filepath}. Job saltato.")
            return

        # 2. Parsing dati
        df = parse_th_file(filepath)
        logger.info(f"Righe lette: {len(df)}")

        # 3. Calcolo statistiche
        stats = compute_statistics(df)

        # 4. Generazione plot
        generate_plot(df, PLOT_OUTPUT_DIR, date_label)

        # 5. Upload su GitHub
        call_uploader(stats, timestamp_str)

        logger.info("===== FnP Daily TH Processor - DONE =====")

    except FileNotFoundError as e:
        logger.error(f"File non trovato: {e}")
    except ValueError as e:
        logger.error(f"Errore nei dati: {e}")
    except Exception as e:
        logger.exception(f"Errore inatteso nel job giornaliero: {e}")


# ============================================================
# ENTRY POINT - Scheduler
# ============================================================

if __name__ == "__main__":
    logger.info(f"FnP Daily TH Processor avviato - job schedulato alle {WHEN}")

    # Schedula il job ogni giorno alle 00:01
    # Reference: schedule library - main.py (FnP AeroGreenHouse repository)
    schedule.every().day.at(WHEN).do(daily_job)

    # Opzione: esecuzione immediata per test (decommenta la riga seguente)
    # daily_job()

    try:
        while True:
            schedule.run_pending()
            sleep(30)  # polling ogni 30 secondi per non saturare la CPU
    except KeyboardInterrupt:
        logger.info("FnP Daily TH Processor terminato dall'utente.")
