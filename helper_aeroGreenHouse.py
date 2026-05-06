import threading
import schedule
from time import sleep
import os
import logging
from logging.handlers import TimedRotatingFileHandler

import RPi.GPIO as GPIO



class aeroHelper():

    '''
    Class for aeroGreenHouse JOBs controll
    '''
    
    def __init__(self):
        '''
        Docstring per __init__
        
        :param self: Descrizione
        '''

        self.config_file_name = 'config.yaml'
        self.configs = self.load_config(self.config_file_name)
        print(self.configs)

        #Log file
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
        
        # IR module pins activation
        self.ir_controller = None
        if self.configs.get('ir_control', {}).get('enabled', False):
            from ir_controller import IRController
            ir_cfg = self.configs['ir_control']
            try:
                self.ir_controller = IRController(
                    tx_pin=ir_cfg['tx_pin'],
                    rx_pin=ir_cfg['rx_pin'],
                    remote_file=ir_cfg['remote_file']
                )
                self.logger.info("IR Controller caricato con successo")
            except Exception as e:
                self.logger.warning(f"IR Controller non disponibile: {e}")

        
        #GPIO jobs controll
        self.aeroponics_job_active = False # controlla se viene eseguito il job aeroponics
        self.idroponics_job_active = False # controlla se viene eseguito il job idroponics

        # Last DHT22 reading
        self.last_T = None   
        self.last_H = None   
        
        # TH jobs controll
        self.th_job_active = False #controlla se viene eseguita la lettura dei dati TH
        self.th_job_saving = False #controlla se viene eseguito il job TH (salvataggio dati TH e VPD)

    

    def load_config(self, file_name):
        import yaml
        with open(file_name, "r") as f:
            return yaml.safe_load(f)
    

    def runner(self, job, *args, **kwargs):
        '''
        Function that runs in multi-thread the AeroSystems jobs
        
        :param job: Name of the function to run
        :param args: Arguments of the function <job>
        :param kwargs: Keyworkds arguments of the function <job>
        '''
        job_thread = threading.Thread(target=job, args=args, kwargs=kwargs, daemon=True)
        job_thread.start()


    ###########################################
    # Activation of GPIOs
    ###########################################

    def activate_aeroponics(self):
        '''
        Function that activate the AEROPONICS controller system
        
        :param 
        '''
        
        self.logger.info('AEROPONICS system control ## ACTIVATED ##')
        
        self.aero_schedule = schedule.Scheduler() #scheduler aeroponics
        self.aero_schedule.every(self.configs['gpio_pins'][0]['interval']).minutes.do(self.runner, job= self.pump_aerophonics, gpio=self.configs['gpio_pins'][0]['pin'] , irrigation_time=self.configs['gpio_pins'][0]['on_time'])

        while self.aeroponics_job_active:
            self.aero_schedule.run_pending()
            sleep(1)
        else:
            self.logger.info('AEROPONICS system control ## DEACTIVATED ##')


    def activate_idroponics(self):
        '''
        Function that activate the IDROPONICS controller system
        
        :param 
        '''
        
       

        self.logger.info('IDROPONICS system control ## ACTIVATED ##')
        
        self.idro_schedule = schedule.Scheduler() #scheduler idroponics
        
        self.idro_schedule.every(self.configs['gpio_pins'][1]['interval']).minutes.do(self.runner, job = self.pump_idrophonics, gpio_pump = self.configs['gpio_pins'][1]['pin'], gpio_sensor = self.configs['gpio_pins'][2]['pin'], max_irrigation_time = self.configs['gpio_pins'][1]['on_time'] )
        # self.idro_schedule.every(self.configs['gpio_pins'][1]['interval']).minutes.do(self.runner, self.pump_idrophonics)

        while self.idroponics_job_active:
            self.idro_schedule.run_pending()
            sleep(1)
        else:
            self.logger.info('IDROPONICS system control ## DEACTIVATED ##')

    def on_off_general(self, gpio, on_period, off_period, name):
        '''
        General function for activating and deactivating a GPIO pin
        with configurable on/off periods. Integrates runner() and 
        activate_aeroponics() scheduling logic in a single function.

        Parameters are read from config.yaml for the entry matching <name>.
        The passed arguments (gpio, on_period, off_period) are used as fallback
        if the config entry is not found.

        :param gpio:       GPIO pin number (BCM numbering)
        :param on_period:  (s)   time the GPIO stays ON (replaces irrigation_time)
        :param off_period: (min) interval between activations – i.e. OFF period
        :param name:       name of the process; must match a 'name' field under
                        gpio_pins in config.yaml
        '''

        # --- 1. Read parameters from config.yaml for the matching name ----------
        job_config = next(
            (j for j in self.configs['gpio_pins'] if j.get('name') == name),
            None
        )

        if job_config is not None:
            gpio       = job_config.get('pin',      gpio)
            on_period  = job_config.get('on_time',  on_period)
            off_period = job_config.get('interval', off_period)  # 'interval' = off_period in config
        else:
            self.logger.warning(
                f'ON_OFF_GENERAL [{name}]: no matching entry in config.yaml – '
                f'using passed arguments (gpio={gpio}, on_period={on_period}s, '
                f'off_period={off_period}min)'
            )

        # --- 2. Initialise per-job active flag (shared dict on the instance) ----
        if not hasattr(self, 'general_jobs_active'):
            self.general_jobs_active = {}

        self.general_jobs_active[name] = True
        self.logger.info(f'{name} system control ## ACTIVATED ## '
                        f'(gpio={gpio}, on={on_period}s, off={off_period}min)')

        # --- 3. Inner pulse function (mirrors pump_aerophonics logic) -----------
        def _pulse():
            self.gpios.output(gpio, False)          # relay ON  (active-low board)
            self.logger.info(f'{name}: GPIO {gpio} ON')

            for i in range(on_period):
                if i == on_period - 1:
                    self.gpios.output(gpio, True)   # relay OFF
                    self.logger.info(f'{name}: GPIO {gpio} OFF')
                    break
                sleep(1)

        # --- 4. Dedicated scheduler (mirrors activate_aeroponics pattern) -------
        job_schedule = schedule.Scheduler()
        job_schedule.every(off_period).minutes.do(
            self.runner, job=_pulse          # runner() launches _pulse in a thread
        )

        # --- 5. Blocking loop – exits when deactivate_general(name) is called ---
        while self.general_jobs_active.get(name, False):
            job_schedule.run_pending()
            sleep(1)

        self.logger.info(f'{name} system control ## DEACTIVATED ##')


    ###########################################
    # Deactivation of GPIOs
    ###########################################

    def deactivate_aeroponics(self):
        self.aeroponics_job_active = False
    
    def deactivate_idroponics(self):
        self.idroponics_job_active = False

    def deactivate_general(self, name):
        '''
        Stops the on_off_general loop for the job identified by <name>.

        :param name: name of the process to deactivate
        '''
        if hasattr(self, 'general_jobs_active'):
            self.general_jobs_active[name] = False

    


    ###########################################
    # GPIO pins for watering (PUMPs)
    ###########################################

    def initialize_gpio(self,config):
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
            self.gpios.output(g["pin"], True) #Spengo tutti i pin inizialmente
            g_list.append(g["pin"])
        
        #initializing the Tx gpio pin for IR controller
        ir_tx_pin = config.get("ir_control", {}).get("tx_pin")
        if ir_tx_pin is not None:
            self.gpios.setup(ir_tx_pin, self.gpios.OUT)
            g_list.append(ir_tx_pin)
            self.logger.info(f'IR TX pin {ir_tx_pin} initialized.')
        
        self.logger.info('GPIOs initialized')
        #self.gpios.cleanup()


    def cleanup_gpios(self):
        self.gpios.cleanup()


    def pump_aerophonics(self,gpio,irrigation_time):
        '''
        Function for activating and deactivating the gpio for aerophonics watering system
        
        :param gpio: GPIO number
        :param irrigation_time: (s), time that the pump is activated
        '''
        
        # gpio = self.configs['gpio_pins'][0]['pin']
        # irrigation_time=self.configs['gpio_pins'][0]['on_time']

        self.gpios.output(gpio, False) #turning on pump
        
        self.logger.info('AEROPONICS: Turning on the pump')
        
        for i in range(irrigation_time):
            if i==irrigation_time-1:
        
                self.gpios.output(gpio,True) #turning off the pump
        
                self.logger.info('AEROPONICS: Turning off the pump')
                break
            sleep(1)
        


    def pump_idrophonics(self, gpio_pump , gpio_sensor, max_irrigation_time):
        '''
        Function for activating and deactivating the gpio for idroponics watering system
        
        :param gpio: GPIO number
        :param max_irrigation_time: (s), maximum time that the pump is activated
        '''
        
        #uncomment this and remove the input variable in the function if does not work 
        # gpio_pump = self.configs['gpio_pins'][1]['pin']
        # gpio_sensor = self.configs['gpio_pins'][2]['pin']
        # max_irrigation_time = self.configs['gpio_pins'][1]['on_time']

        for i in range(max_irrigation_time):
            
            #tempo massimo raggiunto
            if i == max_irrigation_time -1:
                self.logger.info("IDROPONICS: Maximum time reached. Turning OFF the pump")
                self.gpios.output(gpio_pump, True)
                break

            # not activation of the pump
            if self.gpios.input(gpio_sensor) == 0: 
                self.logger.info('IDROPONICS: Water level high. pump OFF.')
                self.gpios.output(gpio_pump, True)
                break

            #activation of the pump
            else: 
                self.gpios.output(gpio_pump, False) #turning on pump
                self.logger.info('IDROPONICS: Water level low, pump ON')
                sleep(1)

    

         



    ###########################################
    # DHT22 sensor measurements
    ###########################################        
    def measure_dht22(self,gpio):
        '''
        Module that use the DHT22 sensor for reading the temperature and humidity  
        
        :param self: Description
        :param gpio: GPIO number (27,17, ecc)
        '''
        import adafruit_dht
        import board
        from time import sleep
        from datetime import datetime

        dht = eval(f"adafruit_dht.DHT22(board.D{gpio})")

        while True:
            try:
                T = dht.temperature
                H = dht.humidity
                #print('T = %4.2f °C ;  H = %4.2f'%(T, H),'%', 'VPD = %5.4f kPa'%(self.VPD(T,H))) #For debug
                return T,H
                break
            except RuntimeError as error:
                print(error.args[0])
                sleep(2.0)
                continue
            except Exception as error:
                dht.exit()
                raise error
        
    
    def VPD(self,T,H):
        '''
        Function that calculate the VPD
        '''
        from math import exp
        es = lambda T : 0.6108 * exp(17.27*T/ (T + 273.3 ) )
        ea = lambda H : H * es(T) / 100

        VPD = es(T) - ea(H)
        return VPD



    
    ###########################################
    # Irrigation time modifier for Aerophonics
    ###########################################

    def T_modifier(self, T: float, t_old: float):
        '''
        Funzione per modificare il tempo di irrigazione in base alla temperatura settata
        
        INPUT:
            T =  Temperatura rilevata in °C
            t_old = vecchio tempo di attesa tra le irrigazioni (in minuti)

        OUTPUT:
            t_new: nuovo tempo di sospensione tra le irrigazioni (in minuti)
        '''

        from math import exp
        Topt = self.configs['T_var']['Topt']
        a = -0.2
        amp = 1
        t_modifier = amp/(exp(a* (T - Topt)) + 1 ) - amp/2 #time modifier
        t_new = t_new - t_new * t_modifier #new time separation
        return t_new



    ###########################################
    # Uploading data on website
    ###########################################
    def upload_data_on_web(self,T,H,vpd,timestamp):
        '''
        This module upload the data on website calling the local uploader.py module
        '''
        os.system(f'python uploader/uploader.py data -t {T} -hu {H} -vpd {vpd} -ts "{timestamp}"')
