# AeroGreenHouse GPIO Controller with Dynamic Configuration Reload
# This module manages GPIO pin control on a Raspberry Pi with dynamic configuration reloading.
# It provides:
# - Automated GPIO pin cycling (on/off) based on configurable intervals
# - Real-time configuration file monitoring and reloading without restart
# - Thread-safe configuration updates
# - Comprehensive logging to both file and console
# - Graceful shutdown handling
# Key Features:
#     - Multiple GPIO pins controlled by separate worker threads
#     - Each pin cycles with configurable interval and on-time duration
#     - Configuration changes detected automatically from YAML file
#     - Thread-safe access to shared configuration using locks
#     - Proper cleanup and signal handling for safe shutdown
# Global Variables:
#     running (bool): Flag to control thread execution
#     config_lock (Lock): Thread synchronization for config updates
#     gpio_configs (dict): Maps GPIO names to their configuration
#     threads (list): Active worker threads
#     last_mtime (int): Last modification time of config file
# Main Threads:
#     - gpio_cycle(): Controls individual GPIO pins with on/off cycles
#     - config_watcher(): Monitors and reloads configuration file changes
# Configuration:
#     Loads settings from config.yaml including:
#     - GPIO pin numbers and names
#     - Cycle intervals and on-time durations
#     - Logging level and output directory


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

running = True # variabile che continua a far eseguire i thread
config_lock = threading.Lock() 
gpio_configs = {}   # name -> config dict
threads = [] 
last_mtime = 0
CONFIG_FILE = "config.yaml" #nome del file di configurazione .yaml

# ==========================
# CARICAMENTO CONFIG
# ==========================

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)

# ==========================
# LOGGING
# ==========================

config = load_config()

log_dir = config["log"]["directory"]
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config["log"]["level"].upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, config["log"]["filename"])),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ==========================
# SETUP GPIO
# ==========================

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for g in config["gpio_pins"]:
    GPIO.setup(g["pin"], GPIO.OUT)
    GPIO.output(g["pin"], True) #Spengo tutti i pin inizialmente
    gpio_configs[g["name"]] = g.copy()
    logger.info(f"GPIO {g['pin']} ({g['name']}) inizializzato")

# ==========================
# THREAD GPIOs
# ==========================

def gpio_cycle(name):
    logger.info(f"Thread avviato per {name}")

    while running:
        with config_lock:
            cfg = gpio_configs[name]
            pin = cfg["pin"]
            interval = cfg["interval"]
            on_time = cfg["on_time"]

        # Usa un ciclo con sleep breve per verificare rapidamente running=False
        end_time = time.time() + interval
        while time.time() < end_time and running:
            time.sleep(min(0.1, interval))

        if not running:
            break

        logger.info(f"{name} ON")
        GPIO.output(pin, False) #Accendo il pin
        time.sleep(on_time)
        GPIO.output(pin, True) # Spengo il pin
        logger.info(f"{name} OFF")

    GPIO.output(pin, True)
    logger.info(f"Thread terminato per {name}")

# ==========================
# THREAD RELOAD CONFIG
# ==========================

def config_watcher():
    global last_mtime

    while running:
        try:
            mtime = os.path.getmtime(CONFIG_FILE)

            if mtime != last_mtime:
                logger.info("Modifica configurazione rilevata")
                new_config = load_config()

                with config_lock:
                    for g in new_config["gpio_pins"]:
                        name = g["name"]
                        if name in gpio_configs:
                            gpio_configs[name]["interval"] = g["interval"]
                            gpio_configs[name]["on_time"] = g["on_time"]
                            gpio_configs[name]["pin"] = g["pin"]
                            logger.info(
                                f"Aggiornato {name}: "
                                f"pin : {g['pin']} | interval={g['interval']} | on_time={g['on_time']}"
                            )

                last_mtime = mtime

        except Exception as e:
            logger.error(f"Errore reload config: {e}")

        # Usa sleep breve per verificare rapidamente running=False
        time.sleep(5)

# ==========================
# SIGNAL HANDLER
# ==========================

def signal_handler(sig, frame):
    global running
    logger.warning("Arresto richiesto")
    running = False
    time.sleep(1)
    GPIO.cleanup()
    logger.info("GPIO cleanup completato")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ==========================
# AVVIO THREAD GPIOs
# ==========================

for name in gpio_configs.keys():
    t = threading.Thread(
        target=gpio_cycle,
        args=(name,),
        daemon=False
    )
    threads.append(t)
    t.start()

# ==========================
# AVVIO THREAD WATCHER
# ==========================

watcher = threading.Thread(
    target=config_watcher,
    daemon=False
)
watcher.start()
threads.append(watcher)

logger.info("Sistema GPIO avviato con reload dinamico")

# ==========================
# MAIN LOOP - ATTESA THREAD
# ==========================

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    # Aspetta che tutti i thread finiscano (max 5 secondi)
    logger.info("Attesa terminazione thread...")
    for t in threads:
        t.join(timeout=5)
    logger.info("Programma terminato")
