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
config_lock = threading.Lock()
gpio_configs = {}   # name -> config dict
threads = []
last_mtime = 0
CONFIG_FILE = "config.yaml"

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
    GPIO.output(g["pin"], GPIO.LOW)
    gpio_configs[g["name"]] = g.copy()
    logger.info(f"GPIO {g['pin']} ({g['name']}) inizializzato")

# ==========================
# THREAD GPIO
# ==========================

def gpio_cycle(name):
    logger.info(f"Thread avviato per {name}")

    while running:
        with config_lock:
            cfg = gpio_configs[name]
            pin = cfg["pin"]
            interval = cfg["interval"]
            on_time = cfg["on_time"]

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

        time.sleep(config.get("config_reload_interval", 5))

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
# AVVIO THREAD GPIO
# ==========================

for name in gpio_configs.keys():
    t = threading.Thread(
        target=gpio_cycle,
        args=(name,),
        daemon=True
    )
    threads.append(t)
    t.start()

# ==========================
# AVVIO THREAD WATCHER
# ==========================

watcher = threading.Thread(
    target=config_watcher,
    daemon=True
)
watcher.start()

logger.info("Sistema GPIO avviato con reload dinamico")

# ==========================
# MAIN LOOP
# ==========================

while True:
    time.sleep(1)
