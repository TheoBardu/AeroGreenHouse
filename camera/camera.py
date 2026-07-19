#! /usr/bin/python
#
# FnP - Anteprima camera dal vivo
#
# Wrapper da riga di comando su CameraManager: apre la finestra di anteprima
# (Preview.QTGL) e la tiene aperta fino a Ctrl-C. Non c'e' piu' un timer fisso:
# dalla GUI la stessa anteprima si apre e si chiude con un pulsante.
#
# Uso:
#     python3 camera/camera.py
#

import os
import sys
import logging
from time import sleep

import yaml

# Eseguito come script da dentro camera/: la radice del progetto va nel path
# per poter importare managers_classes.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from managers_classes.camera_manager import CameraManager

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    with open(CONFIG_FILE, "r") as f:
        configs = yaml.safe_load(f)

    camera = CameraManager(configs, logger)
    camera.start_preview()
    print("Anteprima attiva. Ctrl-C per chiudere.")

    try:
        while camera.is_previewing():
            sleep(1)
    except KeyboardInterrupt:
        camera.stop_preview()
        logger.info("Anteprima chiusa dall'utente.")
