import os
import logging

import RPi.GPIO as GPIO

from managers_classes.jobs_manager import JobsManager
from managers_classes.ambient_manager import AmbientManager
from managers_classes.climate_manager import ClimateManager
from managers_classes.tank_manager import TankManager
from managers_classes.spectro_manager import SpectroManager
from managers_classes.plant_growth import PlantGrowthManager
from managers_classes.camera_manager import CameraManager
from managers_classes.daily_th_processor import DailyTHManager


# =====================================================================
# CORE - Coordinatore (config + logging + GPIO + manager di categoria)
# =====================================================================
class aeroHelper():

    '''
    Coordinatore per aeroGreenHouse: carica la configurazione, configura il
    logging, inizializza la GPIO una sola volta e istanzia i manager di
    categoria (jobs, ambient, climate, tank, spectro, plant_growth, camera,
    daily_th),
    condividendo configs/logger/gpios.
    '''

    def __init__(self):
        '''
        Inizializza il core e i manager di categoria.
        '''

        self.config_file_name = 'config.yaml'
        self.configs = self.load_config(self.config_file_name)
        print(self.configs)

        # Log file
        log_dir = self.configs["log"]["directory"]
        # os.makedirs(log_dir, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.configs["log"]["level"].upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(os.path.join(log_dir, self.configs["log"]["filename"])),
                logging.StreamHandler()
            ]
        )

        self.logger = logging.getLogger(__name__)
        self.logger.info('#### Started FnP AeroSystems ###')

        self.initialize_gpio(self.configs)

        # ---- Manager di categoria ----
        self.jobs = JobsManager(self.configs, self.logger, self.gpios)
        self.ambient = AmbientManager(self.configs, self.logger)
        self.climate = ClimateManager(self.configs, self.logger, self.ambient)
        self.tank = TankManager(self.configs, self.logger)
        self.spectro = SpectroManager(self.configs, self.logger)
        self.plant_growth = PlantGrowthManager(self.configs, self.logger)
        self.camera = CameraManager(self.configs, self.logger)
        self.daily_th = DailyTHManager(self.configs, self.logger)

        # ---- Backward-compat: alias usati da main.py (nessun cambio di logica) ----
        self.runner = self.jobs.runner
        self.pump_aerophonics = self.jobs.pump_aerophonics
        self.pump_idrophonics = self.jobs.pump_idrophonics

    def load_config(self, file_name):
        import yaml
        with open(file_name, "r") as f:
            return yaml.safe_load(f)

    ###########################################
    # GPIO initialization / cleanup (core)
    ###########################################

    def initialize_gpio(self, config):
        '''
        Initialization of all the GPIO pins in output to be closed (i.e deactivated)

        :param config: configure file (config.yaml) with the pin listed
        '''
        self.gpios = GPIO
        self.gpios.setmode(GPIO.BCM)
        self.gpios.setwarnings(False)
        g_list = []
        for g in config["gpio_pins"]:
            if g["what_type"] == "sensor":
                self.gpios.setup(g["pin"], self.gpios.IN)
                g_list.append(g["pin"])
                continue

            self.gpios.setup(g["pin"], self.gpios.OUT)
            self.gpios.output(g["pin"], True)  # Spengo tutti i pin inizialmente
            g_list.append(g["pin"])

        # initializing the Tx gpio pin for IR controller
        ir_tx_pin = config.get("ir_control", {}).get("tx_pin")
        if ir_tx_pin is not None:
            self.gpios.setup(ir_tx_pin, self.gpios.OUT)
            g_list.append(ir_tx_pin)
            self.logger.info(f'IR TX pin {ir_tx_pin} initialized.')

        self.logger.info('GPIOs initialized')
        # self.gpios.cleanup()

    def cleanup_gpios(self):
        self.gpios.cleanup()
