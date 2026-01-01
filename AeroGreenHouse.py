#
# Main code for Aerophonics greenhouse systems
#

import RPi.GPIO as GPIO
import threading
import time
import yaml
import logging
import signal
import sys
import os

# ==========================
# VARIABILI GLOBALI
# ==========================

running = True
threads = []

# ==========================
# CARICAMENTO CONFIG
# ==========================

def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config()

# ==========================
# LOGGING
# ==========================

log_dir = config["log"]["directory"]
log_file = config["log"]["filename"]
log_level = config["log"]["level"].upper()

os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, log_file)),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ==========================
# SETUP GPIO
# ==========================

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for gpio in config["gpio_pins"]:
    GPIO.setup(gpio["pin"], GPIO.OUT)
    GPIO.output(gpio["pin"], GPIO.LOW)
    logger.info(f"GPIO {gpio['pin']} ({gpio['name']}) inizializzato")

# ==========================
# THREAD GPIO
# ==========================

def gpio_cycle(name, pin, interval, on_time):
    global running
    logger.info(f"Thread avviato per {name} (GPIO {pin})")

    while running:
        time.sleep(interval)

        if not running:
            break

        logger.info(f"{name} ON")
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(on_time)
        GPIO.output(pin, GPIO.LOW)
        logger.info(f"{name} OFF")

    GPIO.output(pin, GPIO.LOW)
    logger.info(f"Thread terminato per {name}")

# ==========================
# SIGNAL HANDLER
# ==========================

def signal_handler(sig, frame):
    global running
    logger.warning("Arresto richiesto, spegnimento GPIO...")
    running = False
    time.sleep(1)
    GPIO.cleanup()
    logger.info("GPIO cleanup completato")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ==========================
# AVVIO THREAD
# ==========================

for gpio in config["gpio_pins"]:
    t = threading.Thread(
        target=gpio_cycle,
        args=(
            gpio["name"],
            gpio["pin"],
            gpio["interval"],
            gpio["on_time"]
        ),
        daemon=True
    )
    threads.append(t)
    t.start()

logger.info("Sistema GPIO avviato")

# ==========================
# MAIN LOOP
# ==========================

while True:
    time.sleep(1)
