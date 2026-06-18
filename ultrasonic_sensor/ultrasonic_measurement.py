"""
FnP AeroGreenHouse - Water Tank Level Monitor
==============================================
Sensore: AZDelivery HC-SR04 (B072N473HD) - compatibile con HC-SR04
Hardware: Raspberry Pi Zero W

Principio di misura:
    Il sensore HC-SR04 emette un impulso ultrasonico a 40 kHz e misura il tempo
    di ritorno dell'eco per calcolare la distanza dalla superficie dell'acqua.
    Distanza = (durata_echo * velocità_suono) / 2

Wiring (OBBLIGATORIO - voltage divider su ECHO per proteggere i 3.3V del Pi Zero):
    VCC  (HC-SR04) --> Pin 2  (5V)
    GND  (HC-SR04) --> Pin 6  (GND)
    TRIG (HC-SR04) --> Pin 16 (GPIO 23)
    ECHO (HC-SR04) --> Partitore di tensione --> Pin 18 (GPIO 24)

    Partitore di tensione ECHO (5V -> 3.3V):
        ECHO ----[ R1: 1kΩ ]----+---- GPIO 24 (Pin 18)
                                |
                              [R2: 2kΩ]
                                |
                               GND

Configurazione tanica (da inserire nella sezione TANK CONFIG):
    - Imposta TANK_HEIGHT_CM con l'altezza interna totale della tanica in cm
    - Imposta SENSOR_OFFSET_CM con la distanza del sensore dal bordo superiore
    - Imposta TANK_AREA_CM2 con la sezione trasversale della tanica in cm²
      (es. tanica rettangolare 30x40cm -> 1200 cm²)

References:
    - HC-SR04 datasheet: https://www.handsontec.com/dataspecs/HC-SR04-Ultrasonic.pdf
    - Raspberry Pi GPIO protection: https://thepihut.com/blogs/raspberry-pi-tutorials/hc-sr04-ultrasonic-range-sensor-on-the-raspberry-pi
    - Wiring & Python example: https://pimylifeup.com/raspberry-pi-distance-sensor/
    - AZDelivery HC-SR04 (B072N473HD): https://www.amazon.it/dp/B072N473HD

Author: FnP AeroGreenHouse / Hewa AI
Date: 2026-06-18
"""

import RPi.GPIO as GPIO
import time
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


# =============================================================================
# TANK CONFIG - MODIFICA QUESTI VALORI PER LA TUA TANICA
# =============================================================================

TANK_HEIGHT_CM   = 30.0   # Altezza interna totale della tanica [cm]
SENSOR_OFFSET_CM = 2.0    # Distanza sensore dal bordo superiore tanica [cm]
TANK_AREA_CM2    = 900.0  # Sezione interna della tanica [cm²] (es. 30x30)

# Livello minimo sotto il quale generare un avviso (in litri)
WATER_LOW_THRESHOLD_L = 3.0

# Intervallo di misura [secondi] - ogni quanto fare una lettura
READ_INTERVAL_S = 300  # default: ogni 5 minuti

# GPIO pins (BCM numbering)
GPIO_TRIG = 23  # Pin 16 (GPIO 23)
GPIO_ECHO = 24  # Pin 18 (GPIO 24)

# Numero di misure da mediare ad ogni campionamento (riduce il rumore)
N_SAMPLES = 5

# Directory di salvataggio dati
SAVE_DIR = "/home/fishnplants/Desktop/data/TANK/"
LOG_DIR  = "/home/fishnplants/Desktop/"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def setup_logging(log_dir: str) -> logging.Logger:
    """Setup logger con rotazione giornaliera (stesso stile di aeroHelper)."""
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("WaterTankMonitor")
    logger.setLevel(logging.INFO)

    handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "FnP_WaterTank"),
        when="midnight",
        interval=1,
        backupCount=30,
        suffix=".%Y-%m-%d"
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logger.addHandler(handler)
    logger.addHandler(console)
    return logger


def initialize_gpio(trig_pin: int, echo_pin: int) -> None:
    """Inizializza i pin GPIO per il sensore HC-SR04."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(trig_pin, GPIO.OUT)
    GPIO.setup(echo_pin, GPIO.IN)
    GPIO.output(trig_pin, False)
    time.sleep(0.5)  # Lascia stabilizzare il sensore


def measure_distance_cm(trig_pin: int, echo_pin: int, timeout: float = 0.04) -> float:
    """
    Esegue una singola misura di distanza con l'HC-SR04.

    Il sensore richiede un impulso TRIG di almeno 10 µs, poi invia 8 burst
    ultrasonici a 40 kHz e porta ECHO HIGH per la durata del viaggio dell'onda.

    Distanza [cm] = (durata_echo [s] * 34300 [cm/s]) / 2

    Args:
        trig_pin: pin GPIO del trigger
        echo_pin: pin GPIO dell'echo
        timeout: timeout massimo [s] per l'attesa dell'echo (default 40ms ~ 6.8m)

    Returns:
        Distanza misurata in cm, oppure -1 in caso di timeout/errore.

    Reference:
        https://www.handsontec.com/dataspecs/HC-SR04-Ultrasonic.pdf (timing diagram)
    """
    # Invia impulso TRIG da 10 µs
    GPIO.output(trig_pin, True)
    time.sleep(0.00001)  # 10 µs
    GPIO.output(trig_pin, False)

    # Attendi inizio dell'echo (ECHO HIGH)
    pulse_start = time.time()
    deadline = pulse_start + timeout
    while GPIO.input(echo_pin) == 0:
        pulse_start = time.time()
        if pulse_start > deadline:
            return -1.0  # timeout: nessun echo ricevuto

    # Attendi fine dell'echo (ECHO LOW)
    pulse_end = time.time()
    deadline = pulse_end + timeout
    while GPIO.input(echo_pin) == 1:
        pulse_end = time.time()
        if pulse_end > deadline:
            return -1.0  # timeout: echo troppo lungo (fuori range)

    pulse_duration = pulse_end - pulse_start
    distance_cm = (pulse_duration * 34300.0) / 2.0
    return distance_cm


def measure_distance_avg(trig_pin: int, echo_pin: int,
                          n_samples: int = 5, delay: float = 0.065) -> float:
    """
    Esegue N misure e restituisce la mediana (robusta agli outlier).

    Il datasheet HC-SR04 raccomanda almeno 60 ms tra una misura e l'altra
    per evitare interferenze tra impulsi successivi.

    Args:
        trig_pin: pin GPIO del trigger
        echo_pin: pin GPIO dell'echo
        n_samples: numero di misure da mediare
        delay: attesa tra misure [s] (>= 0.060 raccomandato)

    Returns:
        Distanza mediana in cm, oppure -1 se tutte le misure falliscono.

    Reference:
        https://www.handsontec.com/dataspecs/HC-SR04-Ultrasonic.pdf
        "Suggest to use over 60ms measurement cycle"
    """
    readings = []
    for _ in range(n_samples):
        d = measure_distance_cm(trig_pin, echo_pin)
        if d > 0:
            readings.append(d)
        time.sleep(delay)

    if not readings:
        return -1.0

    readings.sort()
    mid = len(readings) // 2
    return readings[mid]  # mediana


def distance_to_water_volume(
        distance_cm: float,
        tank_height_cm: float,
        sensor_offset_cm: float,
        tank_area_cm2: float) -> dict:
    """
    Converte la distanza misurata in livello e volume d'acqua nella tanica.

    Schema fisico:
        [SENSORE]  <- sensor_offset_cm dal bordo
        [  bordo tanica  ]
        [                ] <- spazio vuoto = distance_cm - sensor_offset_cm
        [  ~~~ acqua ~~~  ]
        [                ]
        [    fondo tanica ]

    Il livello d'acqua è:
        water_level_cm = tank_height_cm - (distance_cm - sensor_offset_cm)

    Args:
        distance_cm: distanza misurata dal sensore [cm]
        tank_height_cm: altezza interna totale della tanica [cm]
        sensor_offset_cm: distanza dal sensore al bordo superiore [cm]
        tank_area_cm2: sezione interna della tanica [cm²]

    Returns:
        dict con: distance_cm, water_level_cm, volume_L, fill_percent
    """
    # Distanza dalla superficie dell'acqua al bordo superiore della tanica
    air_column_cm = distance_cm - sensor_offset_cm

    # Livello d'acqua rispetto al fondo
    water_level_cm = tank_height_cm - air_column_cm

    # Clipping: livello fisicamente valido [0, tank_height_cm]
    water_level_cm = max(0.0, min(water_level_cm, tank_height_cm))

    volume_L = (water_level_cm * tank_area_cm2) / 1000.0  # cm³ -> L
    fill_percent = (water_level_cm / tank_height_cm) * 100.0

    return {
        "distance_cm": round(distance_cm, 1),
        "water_level_cm": round(water_level_cm, 1),
        "volume_L": round(volume_L, 2),
        "fill_percent": round(fill_percent, 1),
    }


def save_data(data: dict, save_dir: str) -> None:
    """
    Salva i dati in un file tabulare giornaliero (.txt), compatibile con
    il formato usato negli altri moduli FnP (TH data, fnp_analysis.m).

    Formato colonne:
        datetime  distance_cm  water_level_cm  volume_L  fill_percent

    Args:
        data: dizionario con i valori misurati (da distance_to_water_volume + timestamp)
        save_dir: directory di salvataggio
    """
    os.makedirs(save_dir, exist_ok=True)
    now = datetime.now()
    file_name = now.strftime("TANK_%Y_%m_%d.txt")
    file_path = os.path.join(save_dir, file_name)

    timestamp = data["timestamp"]
    line = (f"{timestamp}\t"
            f"{data['distance_cm']:6.1f}\t"
            f"{data['water_level_cm']:6.1f}\t"
            f"{data['volume_L']:7.2f}\t"
            f"{data['fill_percent']:5.1f}\n")

    # Scrive header solo se il file è nuovo
    write_header = not os.path.exists(file_path)
    with open(file_path, "a") as f:
        if write_header:
            f.write("datetime\t\t\t dist_cm\t lvl_cm\t vol_L\t fill_%\n")
        f.write(line)


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger = setup_logging(LOG_DIR)
    logger.info("#### FnP Water Tank Monitor - STARTED ####")
    logger.info(f"Configurazione tanica: H={TANK_HEIGHT_CM}cm, "
                f"Area={TANK_AREA_CM2}cm², "
                f"Offset sensore={SENSOR_OFFSET_CM}cm")
    logger.info(f"Intervallo misura: {READ_INTERVAL_S}s, "
                f"Campioni per misura: {N_SAMPLES}")

    initialize_gpio(GPIO_TRIG, GPIO_ECHO)
    logger.info(f"GPIO inizializzati: TRIG=GPIO{GPIO_TRIG}, ECHO=GPIO{GPIO_ECHO}")

    try:
        while True:
            # --- Misura ---
            dist = measure_distance_avg(GPIO_TRIG, GPIO_ECHO, n_samples=N_SAMPLES)

            timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

            if dist < 0:
                logger.warning("TANK: Misura non valida (timeout o fuori range). "
                               "Verificare il posizionamento del sensore.")
                time.sleep(READ_INTERVAL_S)
                continue

            # Controlla range fisico del sensore (2-400 cm per HC-SR04)
            if dist < 2.0 or dist > 400.0:
                logger.warning(f"TANK: Distanza {dist:.1f}cm fuori dal range "
                               "operativo del sensore (2-400cm). Misura ignorata.")
                time.sleep(READ_INTERVAL_S)
                continue

            # --- Conversione distanza -> livello/volume ---
            result = distance_to_water_volume(
                dist, TANK_HEIGHT_CM, SENSOR_OFFSET_CM, TANK_AREA_CM2
            )
            result["timestamp"] = timestamp

            # --- Log ---
            logger.info(
                f"TANK: dist={result['distance_cm']}cm | "
                f"livello={result['water_level_cm']}cm | "
                f"volume={result['volume_L']}L | "
                f"fill={result['fill_percent']}%"
            )

            # --- Allarme livello basso ---
            if result["volume_L"] < WATER_LOW_THRESHOLD_L:
                logger.warning(
                    f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                    f"sotto la soglia di {WATER_LOW_THRESHOLD_L}L! "
                    "Riempire la tanica."
                )

            # --- Salvataggio su file ---
            save_data(result, SAVE_DIR)

            # --- Attesa prossima misura ---
            time.sleep(READ_INTERVAL_S)

    except KeyboardInterrupt:
        logger.info("#### FnP Water Tank Monitor - STOPPED (KeyboardInterrupt) ####")
    finally:
        GPIO.cleanup()
        logger.info("GPIO cleaned up.")


if __name__ == "__main__":
    main()