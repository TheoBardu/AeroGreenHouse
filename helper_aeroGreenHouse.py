import threading
class aeroHelper():

    '''
    Class for aeroGreenHouse
    '''
    
    def __init__(self):
        '''
        Docstring per __init__
        
        :param self: Descrizione
        '''
        import os
        import logging


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

    

    def load_config(self, file_name):
        import yaml
        with open(file_name, "r") as f:
            return yaml.safe_load(f)
    

    def runner(job,*args, **kwargs):
        '''
        Function that runs in multi-thread the AeroSystems jobs
        
        :param job: Name of the function to run
        :param args: Arguments of the function <job>
        :param kwargs: Keyworkds arguments of the function <job>
        '''
        job_thread = threading.Thread(target=job, args=args, kwargs=kwargs)
        job_thread.start()

    ###########################################
    # GPIO pins for watering (PUMPs)
    ###########################################

    def initialize_gpio(self,config):
        '''
        Initialization of all the GPIO pins in output to be closed (i.e deactivated)
        
        :param config: configure file (config.yaml) with the pin listed
        '''
        import RPi.GPIO as GPIO
        self.gpios = GPIO
        self.gpios.setmode(GPIO.BCM)
        self.gpios.setwarnings(False)
        g_list = []
        for g in config["gpio_pins"]:
            if g["what_type"] == "sensor":
                self.gpios.setup(g["pin"], self.gpios.IN)
                g_list.append(g["pin"])
                        
            self.gpios.setup(g["pin"], self.gpios.OUT)
            self.gpios.output(g["pin"], True) #Spengo tutti i pin inizialmente
            g_list.append(g["pin"])
            
        
        self.logger.info('Initialized GPIOs')
        #self.gpios.cleanup()

    def cleanup_gpios(self):
        self.gpios.cleanup()


    def pump_aerophonics(self,gpio,irrigation_time):
        '''
        Function for activating and deactivating the gpio for aerophonics watering system
        
        :param gpio: GPIO number
        :param irrigation_time: (s), time that the pump is activated
        '''
        
        from time import sleep
        
        # import RPi.GPIO as GPIO
        # GPIO.setmode(GPIO.BCM)
        # GPIO.setwarnings(False)
        # GPIO.setup(gpio, GPIO.OUT)
        self.gpios.output(gpio, False) #turning on pump
        
        self.logger.info('AEROPONICS: Turning on the pump')
        
        for i in range(irrigation_time):
            if i==irrigation_time-1:
        
                self.gpios.output(gpio,True) #turning off the pump
        
                self.logger.info('AEROPONICS: Turning off the pump')
                break
            sleep(1)
        
        #GPIO.cleanup()


    def pump_idrophonics(self,gpio_pump, gpio_sensor, max_irrigation_time):
        '''
        Function for activating and deactivating the gpio for idroponics watering system
        
        :param gpio: GPIO number
        :param max_irrigation_time: (s), maximum time that the pump is activated
        '''
        from time import sleep
        
        # import RPi.GPIO as GPIO
        # GPIO.setmode(GPIO.BCM)
        # GPIO.setwarnings(False)
        # GPIO.setup(gpio_pump, GPIO.OUT)
        # GPIO.setup(gpio_sensor, GPIO.IN)

        
        if self.gpios.input(gpio_sensor) == 0:
            self.logger.info('IDROPONICS: Water level high')
            #GPIO.cleanup()
        else:
            self.gpios.output(gpio_pump, False) #turning on pump
            self.logger.info('IDROPONICS: Water level low, turning ON the pump')

            for i in range(max_irrigation_time):
                if self.gpios.input(gpio_sensor) == 0:
                    self.gpios.output(gpio_pump, True) #turning off pump
                    self.logger.info('IDROPONICS: Water level high. Stopping the pump')
                    #GPIO.cleanup()
                    break
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


    def save_TH_measure(self,T,H,vpd,loc='/home/fishnplants/Desktop/data/TH/', name_data_out = 'TH%s.txt', format_data_out= "%s\t %5.2f°C\t %5.2f%%\t %5.4fkPa \n"):
        '''
        Function for saving the TH measure
        '''
        fid = open(loc+name_data_out)
        return 
        

    ###########################################
    # Irrigation time modifier for Aerophonics
    ###########################################

    def T_modifier(self,T):
        '''
        Funzione per modificare il tempo di irrigazione in base alla temperatura settata
        
        
        :param T: Temperatura rilevata
        '''

        from math import exp
        Topt = self.configs['T_var']['Topt']
        a = -0.2
        amp = 1
        f = amp/(exp(a* (T - Topt)) + 1 ) - amp/2
        return f





