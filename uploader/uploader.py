
#
# Uploader FnP - Script per caricare dati sensori e file su GitHub
#
# Utilizzo:
#   python uploader.py data -t <temp> -hu <humidity> -vpd <vpd> -ts <timestamp>  # Crea e carica dati sensori
#   python uploader.py averages -avgt <temp> -avgh <humidity> -avgvpd <vpd> -max{T,H,VPD} <max{T,H,VPD}> -min{T,H,VPD} <min{T,H,VPD}> -ts <timestamp>  # Carica dati medi
#   python uploader.py image  # Carica immagine
#   python uploader.py plot   # Carica plot
#
# Oltre a temperatura/umidita'/VPD, entrambi i comandi accettano (come
# argomenti FACOLTATIVI) le grandezze lette dalle sonde collegate all'Arduino
# - pH, conducibilita' elettrica, livello del serbatoio, altezza delle piante -
# e l'elenco degli errori di lettura. Le chiavi non passate NON compaiono nel
# JSON: cosi' una grandezza non ancora installata o non misurata quel giorno
# non finisce sul sito come valore finto, e le chiamate esistenti che passano
# solo T/H/VPD continuano a funzionare invariate.
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


def add_optional(payload, valori):
    """
    Aggiunge al payload solo le chiavi effettivamente valorizzate.

    :param payload: dizionario da arricchire (modificato sul posto)
    :param valori:  iterabile di (chiave, valore, decimali); i valori None
                    vengono saltati, cosi' una grandezza non misurata resta
                    assente dal JSON invece di comparire come 0.
    """
    for chiave, valore, decimali in valori:
        if valore is None:
            continue
        payload[chiave] = round(valore, decimali)
    return payload


def write_json(temperature, humidity, vpd, timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
               filename=NAME_DATA, ph=None, ec_us_cm=None, tds_ppm=None,
               salinity_psu=None, water_level_cm=None, volume_L=None,
               fill_percent=None, h_plant_cm=None, errors=None):
    """
    Scrive il JSON con l'ultima lettura di ogni grandezza.

    :param temperature/humidity/vpd: dati ambientali (obbligatori)
    :param ph, ec_us_cm, tds_ppm, salinity_psu: qualita' dell'acqua (opzionali)
    :param water_level_cm, volume_L, fill_percent: serbatoio (opzionali)
    :param h_plant_cm: altezza delle piante (opzionale)
    :param errors: lista di dict {'timestamp', 'source', 'message'} con gli
                   errori di lettura da mostrare sul sito (opzionale)
    """
    payload = {
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "vpd": round(vpd, 3),
    }

    add_optional(payload, (
        ("ph", ph, 2),
        ("ec_us_cm", ec_us_cm, 2),
        ("tds_ppm", tds_ppm, 2),
        ("salinity_psu", salinity_psu, 2),
        ("water_level_cm", water_level_cm, 2),
        ("volume_L", volume_L, 2),
        ("fill_percent", fill_percent, 1),
        ("h_plant_cm", h_plant_cm, 1),
    ))

    if errors:
        payload["errors"] = errors

    # Il timestamp resta l'ultima chiave, come nei file di esempio.
    payload["timestamp"] = timestamp

    with open(filename, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ {NAME_DATA} aggiornato correttamente")


# Grandezze giornaliere opzionali: (prefisso delle chiavi, decimali).
# Per ognuna si scrivono avg_/max_/min_ solo se sono state calcolate.
AVG_OPTIONAL_FIELDS = (
    ("ph", 2),
    ("ec", 2),
    ("tds", 2),
    ("salinity", 2),
    ("water_level", 2),
    ("volume", 2),
    ("fill", 1),
    ("h_plant", 1),
)


def write_json_avg(avg_T, avg_H, avg_vpd, maxT, minT, maxH, minH, maxVPD, minVPD,
                   timestamp = datetime.now().strftime("%Y-%m-%d %H:%M"),
                   filename=NAME_DATA_AVG, extra=None, errors=None):
    """
    Scrive il JSON con le medie giornaliere.

    :param extra:  dict con le statistiche opzionali gia' calcolate, nella
                   forma {'avg_ph': .., 'max_ph': .., 'min_ec': .., ...}.
                   Le grandezze non misurate quel giorno vengono omesse.
    :param errors: lista di dict {'timestamp', 'source', 'message'} con gli
                   errori di lettura registrati nel giorno
    """
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
    }

    extra = extra or {}
    for prefisso, decimali in AVG_OPTIONAL_FIELDS:
        add_optional(payload, (
            (f"avg_{prefisso}", extra.get(f"avg_{prefisso}"), decimali),
            (f"max_{prefisso}", extra.get(f"max_{prefisso}"), decimali),
            (f"min_{prefisso}", extra.get(f"min_{prefisso}"), decimali),
        ))

    if errors:
        payload["errors"] = errors

    payload["timestamp"] = timestamp

    with open(filename, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ {filename} aggiornato correttamente")


def create_json(temperature, humidity, vpd, timestamp, **extra):
    """
    Create JSON data with temperature, humidity, vpd and timestamp.

    Gli argomenti aggiuntivi (ph, ec_us_cm, water_level_cm, h_plant_cm, ...)
    vengono inoltrati tali e quali a write_json, che scarta quelli a None.
    """
    write_json(
        temperature=temperature,
        humidity=humidity,
        vpd=vpd,
        timestamp=timestamp,
        **extra
    )


def parse_errors(raw):
    """
    Interpreta l'argomento -err, che arriva come stringa JSON.

    Gli errori sono una LISTA di record e non un valore scalare, quindi non
    possono passare da un flag numerico come le altre grandezze.

    :param raw: stringa JSON, oppure None
    :return: lista di dict (vuota se l'argomento manca o non e' valido)
    """
    if not raw:
        return []
    try:
        errori = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️  Argomento -err ignorato, JSON non valido: {e}")
        return []

    if not isinstance(errori, list):
        print("⚠️  Argomento -err ignorato: atteso un elenco di errori.")
        return []
    return errori

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

# Flag opzionali del comando 'data': (flag, nome destinazione, aiuto).
DATA_OPTIONAL_ARGS = (
    ('-ph', 'ph', "pH dell'acqua"),
    ('-ec', 'ec_us_cm', "Conducibilità elettrica in µS/cm"),
    ('-tds', 'tds_ppm', "Solidi disciolti totali in ppm"),
    ('-sal', 'salinity_psu', "Salinità in PSU"),
    ('-lvl', 'water_level_cm', "Livello del serbatoio in cm"),
    ('-vol', 'volume_L', "Volume nel serbatoio in litri"),
    ('-fill', 'fill_percent', "Riempimento del serbatoio in percentuale"),
    ('-hp', 'h_plant_cm', "Altezza delle piante in cm"),
)

# Flag opzionali del comando 'averages': per ogni grandezza media/max/min.
AVG_OPTIONAL_ARGS = (
    ('ph', 'ph', "pH dell'acqua"),
    ('ec', 'ec', "conducibilità elettrica (µS/cm)"),
    ('tds', 'tds', "solidi disciolti totali (ppm)"),
    ('sal', 'salinity', "salinità (PSU)"),
    ('lvl', 'water_level', "livello del serbatoio (cm)"),
    ('vol', 'volume', "volume nel serbatoio (L)"),
    ('fill', 'fill', "riempimento del serbatoio (%)"),
    ('hp', 'h_plant', "altezza delle piante (cm)"),
)


def add_optional_arguments(parser, comando):
    """
    Aggiunge a un subparser i flag delle grandezze opzionali.

    Sono tutti facoltativi e con default None: le chiamate che passano solo
    T/H/VPD continuano quindi a funzionare esattamente come prima.

    :param parser:  subparser da arricchire
    :param comando: 'data' oppure 'averages'
    """
    if comando == 'data':
        for flag, dest, aiuto in DATA_OPTIONAL_ARGS:
            parser.add_argument(flag, dest=dest, type=float, required=False,
                                default=None, help=aiuto)
    else:
        for sigla, prefisso, aiuto in AVG_OPTIONAL_ARGS:
            parser.add_argument(f'-avg{sigla}', dest=f'avg_{prefisso}', type=float,
                                required=False, default=None, help=f"Media giornaliera: {aiuto}")
            parser.add_argument(f'-max{sigla}', dest=f'max_{prefisso}', type=float,
                                required=False, default=None, help=f"Massimo giornaliero: {aiuto}")
            parser.add_argument(f'-min{sigla}', dest=f'min_{prefisso}', type=float,
                                required=False, default=None, help=f"Minimo giornaliero: {aiuto}")

    parser.add_argument('-err', '--errors', type=str, required=False, default=None,
                        help="Errori di lettura, come stringa JSON: elenco di "
                             "{'timestamp','source','message'}")


def collect_extra(args):
    """Raccoglie da args le statistiche opzionali effettivamente passate."""
    extra = {}
    for _sigla, prefisso, _aiuto in AVG_OPTIONAL_ARGS:
        for chiave in (f'avg_{prefisso}', f'max_{prefisso}', f'min_{prefisso}'):
            valore = getattr(args, chiave, None)
            if valore is not None:
                extra[chiave] = valore
    return extra


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
    
    add_optional_arguments(data_parser, 'data')

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
    
    add_optional_arguments(avg_parser, 'averages')

    # Subparser per plot
    plot_parser = subparsers.add_parser('plot', help='Carica plot su GitHub')
    
    args = main_parser.parse_args()
    
    if args.command == 'data':
        create_json(
            temperature=args.temperature,
            humidity=args.humidity,
            vpd=args.vpd,
            timestamp=args.timestamp,
            errors=parse_errors(args.errors),
            **{dest: getattr(args, dest) for _flag, dest, _aiuto in DATA_OPTIONAL_ARGS}
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
            timestamp=args.timestamp,
            extra=collect_extra(args),
            errors=parse_errors(args.errors)
        )
        upload_averages()
        upload_plot()
    elif args.command == 'plot':
        upload_plot()
