class aeroHelper():

    '''
    Class for aeroGreenHouse
    '''

    def __init__(self):
        '''
        Docstring per __init__
        
        :param self: Descrizione
        '''
        self.config_file_name = 'config.yaml'
        self.configs = self.load_config(self.config_file_name)
        print(self.configs)

    

    def load_config(self, file_name):
        import yaml
        with open(file_name, "r") as f:
            return yaml.safe_load(f)

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
    

    ###########################################
    # GPIO pins activation and deactivation
    ###########################################

    def initilize_gpio_output(self, gpio_list):
        '''
        Inizializzo tutti i GPIO pin
        '''
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for g in gpio_list:
            GPIO.setup(g, GPIO.OUT) 
            GPIO.output(g,True) #spengo tutti i pin
        
        GPIO.cleanup()
        


    def activate_deactivate_pump(self,gpio,irrigation_time):
        '''
        Function for activating and deactivating the gpio for watering
        
        :param self: Description
        :param gpio: GPIO number
        :param irrigation_time: (s), time that the pump is activated
        '''
        import RPi.GPIO as GPIO
        from time import sleep
    
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(gpio, GPIO.OUT) 

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







