import os
import logging

import RPi.GPIO as GPIO

from managers_classes.arduino_link import ArduinoHub
from managers_classes.error_log import ErrorRecorder
from managers_classes.jobs_manager import JobsManager
from managers_classes.ambient_manager import AmbientManager
from managers_classes.climate_manager import ClimateManager
from managers_classes.tank_manager import TankManager
from managers_classes.water_manager import WaterManager
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
    logging, inizializza la GPIO una sola volta, apre il ponte verso le schede
    Arduino e istanzia i manager di categoria (jobs, ambient, climate, tank,
    water, spectro, plant_growth, camera, daily_th), condividendo
    configs/logger/gpios/arduino/errors.
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

        # ---- Servizi condivisi ----
        # Vanno creati PRIMA dei manager: le sonde su Arduino li ricevono
        # nel costruttore.
        self.errors = ErrorRecorder(self.configs, self.logger)
        self.arduino = ArduinoHub(self.configs, self.logger)

        # ---- Manager di categoria ----
        self.jobs = JobsManager(self.configs, self.logger, self.gpios)
        self.ambient = AmbientManager(self.configs, self.logger)
        self.climate = ClimateManager(self.configs, self.logger, self.ambient)
        self.tank = TankManager(self.configs, self.logger, self.arduino, self.errors)
        self.water = WaterManager(self.configs, self.logger, self.arduino, self.errors)
        self.spectro = SpectroManager(self.configs, self.logger)
        self.plant_growth = PlantGrowthManager(self.configs, self.logger,
                                               self.arduino, self.errors)
        self.camera = CameraManager(self.configs, self.logger)
        self.daily_th = DailyTHManager(self.configs, self.logger, self.errors)

        # L'upload periodico parte da AmbientManager (e' lui ad avere la
        # cadenza piu' fitta): gli si dice dove trovare gli ultimi valori
        # delle altre grandezze, cosi' il sito riceve una fotografia unica
        # della serra invece di un upload separato per ogni sonda.
        self.ambient.extra_data_provider = self.latest_extra_data

        # ---- Backward-compat: alias usati da main.py (nessun cambio di logica) ----
        self.runner = self.jobs.runner
        self.pump_aerophonics = self.jobs.pump_aerophonics
        self.pump_idrophonics = self.jobs.pump_idrophonics

    def latest_extra_data(self):
        '''
        Ultimi valori noti delle grandezze diverse da T/H/VPD, per l'upload.

        Ogni voce e' opzionale: una sonda mai letta (o non ancora installata)
        semplicemente non compare, e l'uploader la omette dal JSON invece di
        pubblicare uno zero.

        :return: dict con le chiavi attese da uploader.py piu' 'errors'
        '''
        dati = {}

        tank = self.tank.last_result
        if tank:
            dati['water_level_cm'] = tank.get('water_level_cm')
            dati['volume_L'] = tank.get('volume_L')
            dati['fill_percent'] = tank.get('fill_percent')

        if self.water.last_ph:
            dati['ph'] = self.water.last_ph.get('ph')

        if self.water.last_ec:
            dati['ec_us_cm'] = self.water.last_ec.get('ec_us_cm')
            dati['tds_ppm'] = self.water.last_ec.get('tds_ppm')
            dati['salinity_psu'] = self.water.last_ec.get('salinity_psu')

        if self.plant_growth.history:
            dati['h_plant_cm'] = self.plant_growth.history[-1].get('h_plant_cm')

        # Solo gli errori piu' recenti: il JSON del sito e' una fotografia
        # dello stato attuale, non un archivio.
        dati['errors'] = self.errors.recent(10)

        return dati

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
        '''Rilascia le GPIO e chiude le porte seriali verso le schede Arduino.'''
        self.arduino.close_all()
        self.gpios.cleanup()
