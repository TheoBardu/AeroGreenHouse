
#
# Uploader FnP - Script per caricare dati sensori e file su GitHub
#
# Utilizzo:
#   python uploader.py data -t <temp> -hu <humidity> -vpd <vpd> -ts <timestamp>  # Crea e carica dati sensori
#   python uploader.py averages -avgt <temp> -avgh <humidity> -avgvpd <vpd> -max{T,H,VPD} <max{T,H,VPD}> -min{T,H,VPD} <min{T,H,VPD}> -ts <timestamp>  # Carica dati medi
#   python uploader.py image  # Carica immagine
#   python uploader.py plot   # Carica plot
#
# I dati verranno salvati come JSON e caricati sul repository GitHub FnP
# per essere visualizzati sul sito web del progetto.
#


import base64
import requests
import json
import argparse
from datetime import datetime
import sys
import os
import time
from dotenv import load_dotenv


os.chdir(os.getcwd())
load_dotenv()  # Carica variabili d'ambiente da .env

# ===== BASIC CONFIG =====
NAME_DATA = "dati.json"
NAME_DATA_AVG = "avg_data.json"
NAME_IMG = "image.jpg"
NAME_PLOT = "plot.png"
TIMEOUT = 50 #timeout seconds

img_location = "/home/fishnplants/Desktop/data/IMG/"
plot_location = "/home/fishnplants/Desktop/data/PLOT/"


# ===== GITHUB CONFIG =====
TOKEN = os.getenv("GITHUB_TOKEN")
USR = os.getenv("GITHUB_USR")
REPO = os.getenv("GITHUB_REPO")
BRANCH = os.getenv("GITHUB_BRANCH")


# ===== RETRY CONFIG =====
MAX_RETRIES = 3  # 3 tentativi totali = 2 retry
BASE_DELAY = 1   # delay iniziale in secondi

def retry_with_exponential_backoff(func):
    """
    Decoratore che aggiunge retry con backoff esponenziale.
    Max 3 tentativi totali con delay esponenziale (1s, 2s, 4s).
    """
    def wrapper(*args, **kwargs):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"❌ Errore dopo {attempt} tentativi: {str(e)}")
                    raise
                delay = BASE_DELAY ** (attempt - 1)  # 1s, 2s, 4s
                print(f"⚠️  Tentativo {attempt} fallito. Retry in {delay}s... ({str(e)})")
                time.sleep(delay)
    return wrapper

@retry_with_exponential_backoff
def upload_json():
    """
    Upload the JSON data to GitHub
    """

    # ===== LEGGI FILE LOCALE =====
    with open(NAME_DATA, "r") as f:
        content = f.read()

    encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    print(content)

    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # ===== PRENDI SHA ATTUALE =====
    url_data = f"https://api.github.com/repos/{USR}/{REPO}/contents/{NAME_DATA}"

    response = requests.get(url_data, headers=headers)
    response.raise_for_status()

    sha = response.json()["sha"]

    # ===== CARICA NUOVO FILE =====
    payload = {
        "message": "Aggiornamento dati sensori FnP",
        "content": encoded_content,
        "sha": sha,
        "branch": BRANCH
    }

    put_response = requests.put(url_data, headers=headers, json=payload)
    put_response.raise_for_status()

    print("✅ File JSON aggiornato correttamente su GitHub")

@retry_with_exponential_backoff
def upload_image():
    """
    Upload the image captured to GitHub
    """

    # ===== LEGGI FILE LOCALE =====
    with open(img_location + NAME_IMG, "rb") as f:
        encoded_content = base64.b64encode(f.read()).decode("utf-8")


    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # ===== PRENDI SHA ATTUALE =====
    url_data = f"https://api.github.com/repos/{USR}/{REPO}/contents/{NAME_IMG}"

    response = requests.get(url_data, headers=headers)
    response.raise_for_status()

    sha = response.json()["sha"]

    # ===== CARICA NUOVO FILE =====
    payload = {
        "message": "Aggiornamento immagine FnP",
        "content": encoded_content,
        "sha": sha,
        "branch": BRANCH
    }

    put_response = requests.put(url_data, headers=headers, json=payload, timeout=TIMEOUT)
    put_response.raise_for_status()

    print("✅ Image file aggiornato correttamente su GitHub")


@retry_with_exponential_backoff
def upload_plot():
    """
    Upload the plot captured to GitHub
    """
    # ===== LEGGI FILE LOCALE =====
    with open(plot_location + NAME_PLOT, "rb") as f:
        encoded_content = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # ===== PRENDI SHA ATTUALE =====
    url_data = f"https://api.github.com/repos/{USR}/{REPO}/contents/{NAME_PLOT}"

    response = requests.get(url_data, headers=headers)
    response.raise_for_status()

    sha = response.json()["sha"]

    # ===== CARICA NUOVO FILE =====
    payload = {
        "message": "Aggiornamento plot FnP",
        "content": encoded_content,
        "sha": sha,
        "branch": BRANCH
    }

    put_response = requests.put(url_data, headers=headers, json=payload, timeout=TIMEOUT)
    put_response.raise_for_status()

    print("✅ Plot file aggiornato correttamente su GitHub")


def write_json(temperature, humidity, vpd, timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S"), filename=NAME_DATA):
    payload = {
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "vpd": round(vpd, 3),
        "timestamp": timestamp
    }

    with open(filename, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✅ {NAME_DATA} aggiornato correttamente")


def write_json_avg(avg_T, avg_H, avg_vpd, maxT, minT, maxH, minH, maxVPD, minVPD, timestamp = datetime.now().strftime("%Y-%m-%d %H:%M"), filename=NAME_DATA_AVG):
    payload = {
        "avg_temperature": round(avg_T, 2),
        "avg_humidity": round(avg_H, 2),
        "avg_vpd": round(avg_vpd, 3),
        "max_T" : round(maxT,2),
        "min_T" : round(minT,2),
        "max_H" : round(maxH,2),
        "min_H" : round(minH,2),
        "max_VPD" : round(maxVPD,3),
        "min_VPD" : round(minVPD,3),
        "timestamp": timestamp
    }

    with open(filename, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✅ {filename} aggiornato correttamente")


def create_json(temperature, humidity, vpd, timestamp):
    """
    Create JSON data with temperature, humidity, vpd and timestamp
    """
    write_json(
        temperature=temperature,
        humidity=humidity,
        vpd=vpd,
        timestamp=timestamp
    )

@retry_with_exponential_backoff
def upload_averages():
    """
    Upload the averaged JSON data to GitHub
    """

    # ===== LEGGI FILE LOCALE =====
    with open(NAME_DATA_AVG, "r") as f:
        content = f.read()

    encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    print(content)

    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # ===== PRENDI SHA ATTUALE =====
    url_data = f"https://api.github.com/repos/{USR}/{REPO}/contents/{NAME_DATA_AVG}"

    response = requests.get(url_data, headers=headers)
    response.raise_for_status()

    sha = response.json()["sha"]

    # ===== CARICA NUOVO FILE =====
    payload = {
        "message": "Aggiornamento dati medi sensori FnP",
        "content": encoded_content,
        "sha": sha,
        "branch": BRANCH
    }

    put_response = requests.put(url_data, headers=headers, json=payload, timeout=TIMEOUT)
    put_response.raise_for_status()

    print("✅ File JSON medi aggiornato correttamente su GitHub")

if __name__ == "__main__":

    main_parser = argparse.ArgumentParser(
        description="Uploader FnP - Gestione dati sensori e file"
    )
    subparsers = main_parser.add_subparsers(dest='command', help='Comando da eseguire')
    
    # Subparser per data
    data_parser = subparsers.add_parser('data', help='Crea JSON dati sensori')
    data_parser.add_argument(
        '-t', '--temperature',
        type=float,
        required=True,
        help="Temperatura in °C"
    )
    data_parser.add_argument(
        '-hu', '--humidity',
        type=float,
        required=True,
        help="Umidità relativa in percentuale"
    )
    data_parser.add_argument(
        '-vpd',
        type=float,
        required=True,
        help="Vapor Pressure Deficit in kPa"
    )
    data_parser.add_argument(
        '-ts', '--timestamp',
        type=str,
        required=True,
        help="Timestamp string in ISO8601 format"
    )
    
    # Subparser per image
    image_parser = subparsers.add_parser('image', help='Carica immagine su GitHub')
    
    # Subparser per averages
    avg_parser = subparsers.add_parser('averages', help='Carica dati medi')
    avg_parser.add_argument(
        '-avgt', '--avg-temperature',
        type=float,
        required=True,
        help="Temperatura media in °C"
    )
    avg_parser.add_argument(
        '-avgh', '--avg-humidity',
        type=float,
        required=True,
        help="Umidità relativa media in percentuale"
    )
    avg_parser.add_argument(
        '-avgvpd', '--avg-vpd',
        type=float,
        required=True,
        help="Average Vapor Pressure Deficit in kPa"
    )
    avg_parser.add_argument(
        '-ts', '--timestamp',
        type=str,
        required=True,
        help="Timestamp string in ISO8601 format"
    )
    avg_parser.add_argument(
        '-maxT', '--max-temperature',
        type=float,
        required=True,
        help="Temperatura massima in °C"
    )
    avg_parser.add_argument(
        '-minT', '--min-temperature',
        type=float,
        required=True,
        help="Temperatura minima in °C"
    )
    avg_parser.add_argument(
        '-maxH', '--max-humidity',
        type=float,
        required=True,
        help="Umidità massima in percentuale"
    )
    avg_parser.add_argument(
        '-minH', '--min-humidity',
        type=float,
        required=True,
        help="Umidità minima in percentuale"
    )
    avg_parser.add_argument(
        '-maxVPD', '--max-vpd',
        type=float,
        required=True,
        help="Vapor Pressure Deficit massimo in kPa"
    )
    avg_parser.add_argument(
        '-minVPD', '--min-vpd',
        type=float,
        required=True,
        help="Vapor Pressure Deficit minimo in kPa"
    )
    
    # Subparser per plot
    plot_parser = subparsers.add_parser('plot', help='Carica plot su GitHub')
    
    args = main_parser.parse_args()
    
    if args.command == 'data':
        create_json(
            temperature=args.temperature,
            humidity=args.humidity,
            vpd=args.vpd,
            timestamp=args.timestamp
        )
        upload_json()
        upload_image()
    elif args.command == 'image':
        upload_image()
    elif args.command == 'averages':
        write_json_avg(
            avg_T=args.avg_temperature,
            avg_H=args.avg_humidity,
            avg_vpd=args.avg_vpd,
            maxT=args.max_temperature,
            minT=args.min_temperature,
            maxH=args.max_humidity,
            minH=args.min_humidity,
            maxVPD=args.max_vpd,
            minVPD=args.min_vpd,
            timestamp=args.timestamp
        )
        upload_averages()
        upload_plot()
    elif args.command == 'plot':
        upload_plot()
