"""
FnP AeroGreenHouse - Indice di vegetazione MCARI2 con sensore spettrale AS7265x
================================================================================
Sensore: SparkFun Triad Spectroscopy Sensor AS7265x (18 canali, 410-940 nm)
Hardware: Raspberry Pi (bus I2C)

Cosa fa questo modulo:
    Acquisisce i dati spettrali dal sensore AS7265x e calcola l'indice di
    vegetazione MCARI2 (Modified Chlorophyll Absorption in Reflectance Index 2),
    utile per stimare lo stato di salute della pianta (clorofilla, LAI) e
    individuare stress idrico/nutrizionale (in particolare carenza di azoto).

    Formula (come da Knowledge Base FnP):

        MCARI2 = 1.5 * [2.5*(NIR-RED) - 1.3*(NIR-GREEN)]
                 / sqrt( (2.0*NIR + 1)^2 - (6.0*NIR - 5*sqrt(RED)) - 0.5 )

    con GREEN ~550 nm, RED ~670 nm, NIR ~800 nm.

Mappatura bande -> canali AS7265x (getter nominali della libreria SparkFun):
    GREEN (~550 nm) -> canale 560 nm -> get_calibrated_g()
    RED   (~670 nm) -> canale 680 nm -> get_calibrated_s()
    NIR   (~800 nm) -> canale 810 nm -> get_calibrated_v()

PUNTO CRITICO - riflettanza, non irradianza grezza:
    MCARI2 e' definito su valori di RIFLETTANZA (0-1), non sull'irradianza
    assoluta (uW/cm2) restituita dal sensore, che dipende anche dall'intensita'
    della luce incidente. Per questo e' necessaria una TARATURA: si misura un
    riferimento bianco (pannello bianco) con il LED bianco integrato acceso e lo
    si salva; la riflettanza e' poi:

        R(lambda) = lettura_sul_target(lambda) / lettura_sul_riferimento(lambda)

    Riferimento e target vanno acquisiti con gli stessi gain/tempo di integrazione
    e con la stessa illuminazione (LED bianco integrato).

Dipendenze:
    pip3 install sparkfun-qwiic-as7265x
    (richiede I2C abilitato: sudo raspi-config -> Interface Options -> I2C)

Riferimenti:
    - Libreria SparkFun: https://github.com/sparkfun/qwiic_as7265x_py
    - Modulo sensore (Aliexpress): https://it.aliexpress.com/item/1005012377087652.html

Author: FnP AeroGreenHouse
Date: 2026-07-14
"""

import os
import json
import math
import glob
import time
from datetime import datetime

# Import hardware tollerante: se la libreria non e' installata (es. sviluppo su
# PC non-Raspberry), il modulo resta importabile e le funzioni di solo calcolo
# (mcari2, compute_reflectance, evaluate_MCAR2, interpreta_mcari2) restano usabili.
try:
    import qwiic_as7265x
    _HW_AVAILABLE = True
except ImportError:
    qwiic_as7265x = None
    _HW_AVAILABLE = False


# =============================================================================
# CONFIG
# =============================================================================

# Getter nominali della libreria per le tre bande della formula MCARI2.
# (Tenere la mappatura in un unico posto: read_bands li usa via getattr.)
GREEN_GETTER = "get_calibrated_g"   # 560 nm
RED_GETTER   = "get_calibrated_s"   # 680 nm
NIR_GETTER   = "get_calibrated_v"   # 810 nm

GREEN_NM = 560
RED_NM   = 680
NIR_NM   = 810

# Mappatura completa dei 18 canali AS7265x: lettera del getter -> lunghezza d'onda.
# Usata dallo script di test per stampare tutti i canali e verificare il cablaggio
# e la corrispondenza delle bande sull'hardware reale.
CHANNEL_MAP = {
    "a": 410, "b": 435, "c": 460, "d": 485, "e": 510, "f": 535,
    "g": 560, "h": 585, "r": 610, "i": 645, "s": 680, "j": 705,
    "t": 730, "u": 760, "v": 810, "w": 860, "k": 900, "l": 940,
}

# Impostazioni di acquisizione: DEVONO restare identiche tra riferimento e target.
# Se la libreria non e' disponibile usiamo dei valori interi equivalenti come
# fallback (0=1x, 1=3.7x, 2=16x, 3=64x) per non rompere l'import.
GAIN = qwiic_as7265x.kGain16x if _HW_AVAILABLE else 2  # 16x
INTEGRATION_CYCLES = 50    # tempo di integrazione ~ valore * 2.8 ms
SETTLE_TIME = 0.3          # attesa di assestamento del LED prima della misura [s]

# Intervallo tra due letture nel monitoraggio periodico [s]. Un'ora e'
# sufficiente: l'MCARI2 varia su scala di giorni e ogni misura accende il LED.
READ_INTERVAL_S = 3600

# Persistenza
SAVE_DIR = "/home/fishnplants/Desktop/data/SPECTRO/"
CALIB_FILE = os.path.join(SAVE_DIR, "spectro_calibration.json")
CALIB_NAME = "spectro_calibration.json"
FILE_FORMAT = "SPECTRO_%Y_%m_%d.txt"


def _calib_path(save_dir=SAVE_DIR):
    """Percorso del file di taratura nella directory indicata."""
    return os.path.join(save_dir, CALIB_NAME)


# =============================================================================
# ACQUISIZIONE (richiede hardware)
# =============================================================================

def init_sensor():
    """
    Inizializza il sensore AS7265x e imposta gain/tempo di integrazione.

    Returns:
        Istanza QwiicAS7265x pronta all'uso.

    Raises:
        RuntimeError: se la libreria non e' installata, il sensore non e'
            rilevato sul bus I2C o l'inizializzazione fallisce.
    """
    if not _HW_AVAILABLE:
        raise RuntimeError(
            "Libreria qwiic_as7265x non trovata. Installarla con:\n"
            "  pip3 install sparkfun-qwiic-as7265x\n"
            "(richiede I2C abilitato: sudo raspi-config -> Interface Options -> I2C)"
        )

    sensor = qwiic_as7265x.QwiicAS7265x()

    if not sensor.is_connected():
        raise RuntimeError("AS7265x non rilevato sul bus I2C. Controllare i collegamenti.")

    if not sensor.begin():
        raise RuntimeError("Inizializzazione AS7265x fallita.")

    sensor.set_gain(GAIN)
    sensor.set_integration_cycles(INTEGRATION_CYCLES)
    sensor.disable_indicator()  # spegne il LED di stato per non disturbare la misura

    return sensor


def _measure(sensor, use_bulb):
    """Esegue una misura, opzionalmente con il LED bianco integrato acceso."""
    if use_bulb:
        sensor.enable_bulb(qwiic_as7265x.kLedWhite)
        time.sleep(SETTLE_TIME)  # assestamento del LED

    sensor.take_measurements()

    if use_bulb:
        sensor.disable_bulb(qwiic_as7265x.kLedWhite)


def read_bands(sensor, use_bulb=True):
    """
    Esegue una misura e restituisce i valori calibrati delle tre bande MCARI2.

    Args:
        sensor: istanza QwiicAS7265x inizializzata da init_sensor().
        use_bulb: se True accende il LED bianco integrato durante la misura
            (necessario sia per il riferimento sia per il target).

    Returns:
        dict {560: green, 680: red, 810: nir} con i valori calibrati (uW/cm2).
    """
    _measure(sensor, use_bulb)
    return {
        GREEN_NM: getattr(sensor, GREEN_GETTER)(),
        RED_NM:   getattr(sensor, RED_GETTER)(),
        NIR_NM:   getattr(sensor, NIR_GETTER)(),
    }


def read_all_channels(sensor, use_bulb=True):
    """
    Esegue una misura e restituisce tutti i 18 canali {lunghezza_donda: valore}.

    Utile per diagnostica: verificare il cablaggio I2C e confermare la
    corrispondenza delle bande (560/680/810 nm) sull'hardware reale.

    Args:
        sensor: istanza QwiicAS7265x inizializzata.
        use_bulb: se True accende il LED bianco integrato durante la misura.

    Returns:
        dict {nm: valore_calibrato} ordinato per lunghezza d'onda.
    """
    _measure(sensor, use_bulb)
    values = {}
    for letter, nm in CHANNEL_MAP.items():
        values[nm] = getattr(sensor, f"get_calibrated_{letter}")()
    return dict(sorted(values.items()))


# =============================================================================
# TARATURA (riferimento bianco)
# =============================================================================

def calibrate(sensor, save_dir=SAVE_DIR):
    """
    Esegue la taratura misurando il riferimento bianco e la salva su file.

    Va eseguita puntando il sensore su un pannello bianco (white reference), con
    le stesse condizioni (gain/tempo di integrazione/LED) usate poi per la misura
    sulla pianta. I valori salvati costituiscono il "fondo" rispetto al quale
    calcolare la riflettanza.

    Args:
        sensor: istanza QwiicAS7265x inizializzata.
        save_dir: directory in cui salvare la taratura.

    Returns:
        dict {560, 680, 810} con i valori di riferimento appena misurati.
    """
    reference = read_bands(sensor, use_bulb=True)

    payload = {
        "reference": {str(nm): reference[nm] for nm in (GREEN_NM, RED_NM, NIR_NM)},
        "gain": GAIN,
        "integration_cycles": INTEGRATION_CYCLES,
        "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }

    os.makedirs(save_dir, exist_ok=True)
    with open(_calib_path(save_dir), "w") as f:
        json.dump(payload, f, indent=2)

    return reference


def load_calibration(save_dir=SAVE_DIR):
    """
    Carica i valori di riferimento salvati dall'ultima taratura.

    Args:
        save_dir: directory in cui cercare la taratura.

    Returns:
        dict {560, 680, 810} con i valori di riferimento bianco.

    Raises:
        FileNotFoundError: se non esiste una taratura salvata.
    """
    calib_file = _calib_path(save_dir)

    if not os.path.exists(calib_file):
        raise FileNotFoundError(
            f"Nessuna taratura trovata in {calib_file}. Eseguire prima la taratura "
            "(funzione calibrate) puntando il sensore sul riferimento bianco."
        )

    with open(calib_file, "r") as f:
        payload = json.load(f)

    # Avvisa se le impostazioni correnti non coincidono con quelle della taratura:
    # la riflettanza sarebbe falsata se gain/integrazione fossero cambiati.
    saved_gain = payload.get("gain")
    saved_cycles = payload.get("integration_cycles")
    if saved_gain is not None and saved_gain != GAIN:
        print(f"ATTENZIONE: gain di taratura ({saved_gain}) diverso da quello "
              f"corrente ({GAIN}). Rifare la taratura.")
    if saved_cycles is not None and saved_cycles != INTEGRATION_CYCLES:
        print(f"ATTENZIONE: tempo di integrazione di taratura ({saved_cycles}) diverso "
              f"da quello corrente ({INTEGRATION_CYCLES}). Rifare la taratura.")

    ref = payload["reference"]
    return {GREEN_NM: ref["560"], RED_NM: ref["680"], NIR_NM: ref["810"]}


# =============================================================================
# CALCOLO (nessun hardware richiesto)
# =============================================================================

def compute_reflectance(target_raw, reference_raw):
    """
    Calcola la riflettanza canale per canale come rapporto tra la lettura sul
    target e la lettura sul riferimento bianco.

    Args:
        target_raw: dict {560, 680, 810} misurato sulla pianta.
        reference_raw: dict {560, 680, 810} del riferimento bianco (taratura).

    Returns:
        dict {560, 680, 810} di riflettanza (tipicamente 0-1).

    Raises:
        ZeroDivisionError: se un valore di riferimento e' nullo.
    """
    reflectance = {}
    for band, value in target_raw.items():
        ref_value = reference_raw[band]
        if ref_value == 0:
            raise ZeroDivisionError(f"Lettura di riferimento nulla per il canale {band} nm")
        reflectance[band] = value / ref_value
    return reflectance


def mcari2(reflectance):
    """
    Calcola l'indice MCARI2 a partire dalla riflettanza delle tre bande.

    Args:
        reflectance: dict {560: GREEN, 680: RED, 810: NIR} di riflettanza.

    Returns:
        Valore MCARI2 (float).
    """
    green = reflectance[GREEN_NM]
    red = reflectance[RED_NM]
    nir = reflectance[NIR_NM]

    numeratore = 1.5 * (2.5 * (nir - red) - 1.3 * (nir - green))
    denominatore = math.sqrt(
        (2.0 * nir + 1) ** 2 - (6.0 * nir - 5 * math.sqrt(red)) - 0.5
    )

    return numeratore / denominatore


def evaluate_MCAR2(target_bands, reference_bands=None):
    """
    Calcola l'indice MCARI2 a partire dai dati acquisiti dal sensore.

    Partendo dai valori grezzi delle tre bande misurati sulla pianta, normalizza
    rispetto al riferimento bianco (per ottenere la riflettanza) e calcola MCARI2.
    Se reference_bands non e' fornito, viene caricata la taratura salvata.

    Args:
        target_bands: dict {560, 680, 810} misurato sulla pianta.
        reference_bands: dict {560, 680, 810} del riferimento bianco; se None,
            viene caricato dall'ultima taratura salvata (load_calibration()).

    Returns:
        Valore MCARI2 (float).

    Raises:
        FileNotFoundError: se reference_bands e' None e non esiste una taratura.
    """
    if reference_bands is None:
        reference_bands = load_calibration()

    reflectance = compute_reflectance(target_bands, reference_bands)
    return mcari2(reflectance)


def measure_mcari2(sensor, reference_bands=None):
    """
    Acquisisce le bande dal sensore e ne calcola l'MCARI2 (convenience).

    Args:
        sensor: istanza QwiicAS7265x inizializzata.
        reference_bands: riferimento bianco; se None usa la taratura salvata.

    Returns:
        tuple (bands, reflectance, index):
            bands: dict {560, 680, 810} grezzo misurato,
            reflectance: dict {560, 680, 810} di riflettanza,
            index: valore MCARI2.
    """
    if reference_bands is None:
        reference_bands = load_calibration()

    bands = read_bands(sensor, use_bulb=True)
    reflectance = compute_reflectance(bands, reference_bands)
    index = mcari2(reflectance)
    return bands, reflectance, index


# Chiavi di stato della coltura. Sono l'interfaccia verso chi consuma il dato
# (es. la GUI, che ci mappa sopra un colore): le soglie numeriche restano qui.
STATO_STRESS = "stress"
STATO_LIMITE = "limite"
STATO_SANA = "sana"
STATO_MOLTO_SANA = "molto_sana"

TESTI_MCARI2 = {
    STATO_STRESS: "Possibile stress idrico o carenza nutrizionale (es. azoto)",
    STATO_LIMITE: "Coltura al limite, tenere sotto osservazione",
    STATO_SANA: "Coltura sana",
    STATO_MOLTO_SANA: "Coltura molto sana, nessuna carenza rilevata",
}


def classifica_mcari2(valore):
    """
    Classifica l'MCARI2 secondo le soglie della Knowledge Base FnP.

    Args:
        valore: indice MCARI2.

    Returns:
        Una delle chiavi STATO_* (stress / limite / sana / molto_sana).
    """
    if valore < 0.4:
        return STATO_STRESS
    elif valore < 0.6:
        return STATO_LIMITE
    elif valore <= 0.9:
        return STATO_SANA
    else:
        return STATO_MOLTO_SANA


def interpreta_mcari2(valore):
    """Interpretazione qualitativa dell'MCARI2 secondo le soglie della Knowledge Base."""
    return TESTI_MCARI2[classifica_mcari2(valore)]


# =============================================================================
# SALVATAGGIO DATI
# =============================================================================

def save_measurement(bands, reflectance, index, save_dir=SAVE_DIR):
    """
    Salva una misura MCARI2 in un file tabulare giornaliero (.txt), coerente con
    il formato usato dagli altri moduli FnP (TH data, TANK data).

    Formato colonne:
        datetime  green_raw red_raw nir_raw  R_green R_red R_nir  MCARI2

    Args:
        bands: dict {560, 680, 810} grezzo misurato.
        reflectance: dict {560, 680, 810} di riflettanza.
        index: valore MCARI2.
        save_dir: directory di salvataggio.
    """
    os.makedirs(save_dir, exist_ok=True)
    now = datetime.now()
    file_path = os.path.join(save_dir, now.strftime(FILE_FORMAT))
    timestamp = now.strftime("%Y/%m/%d %H:%M:%S")

    line = (f"{timestamp}\t"
            f"{bands[GREEN_NM]:.2f}\t{bands[RED_NM]:.2f}\t{bands[NIR_NM]:.2f}\t"
            f"{reflectance[GREEN_NM]:.4f}\t{reflectance[RED_NM]:.4f}\t{reflectance[NIR_NM]:.4f}\t"
            f"{index:.4f}\n")

    write_header = not os.path.exists(file_path)
    with open(file_path, "a") as f:
        if write_header:
            f.write("datetime\t\t\t green_raw\t red_raw\t nir_raw\t "
                    "R_green\t R_red\t R_nir\t MCARI2\n")
        f.write(line)


def _parse_measurement_line(line):
    """
    Interpreta una riga di un file SPECTRO_*.txt.

    Returns:
        dict {timestamp, mcari2} oppure None se la riga non e' una misura
        (header, riga vuota o malformata).
    """
    parts = line.strip().split("\t")
    if len(parts) < 8:
        return None

    try:
        timestamp = datetime.strptime(parts[0].strip(), "%Y/%m/%d %H:%M:%S")
        index = float(parts[7].strip())
    except ValueError:
        # Header o riga corrotta: si salta senza far fallire la lettura.
        return None

    return {"timestamp": timestamp, "mcari2": index}


def load_measurements(save_dir=SAVE_DIR, max_rows=10):
    """
    Rilegge le ultime misure salvate dai file giornalieri SPECTRO_*.txt.

    Simmetrica a save_measurement: serve a ricostruire lo storico dell'indice
    (es. all'avvio della GUI) senza tenere nulla in memoria tra un avvio e l'altro.
    Le righe non interpretabili (header compreso) vengono ignorate.

    Args:
        save_dir: directory dei file giornalieri.
        max_rows: numero massimo di misure da restituire.

    Returns:
        Lista di dict {timestamp: datetime, mcari2: float}, dalla piu' recente
        alla piu' vecchia. Lista vuota se non esistono dati.
    """
    if not os.path.isdir(save_dir):
        return []

    # I nomi contengono la data zero-padded: l'ordine alfabetico inverso e'
    # anche l'ordine cronologico inverso.
    files = sorted(glob.glob(os.path.join(save_dir, "SPECTRO_*.txt")), reverse=True)

    measurements = []
    for file_path in files:
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
        except OSError:
            continue

        # Dentro al file le misure sono in ordine cronologico: si parte dal fondo.
        for line in reversed(lines):
            row = _parse_measurement_line(line)
            if row is not None:
                measurements.append(row)
                if len(measurements) >= max_rows:
                    return measurements

    return measurements
