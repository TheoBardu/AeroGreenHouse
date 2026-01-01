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
    
    def new_interval(self, T):
        '''
        Modifica la voce "interval" di AEROPONICS nel file di configurazione

        :param T: Temperatura rilevata
        :return: nuovo valore di interval (int)
        '''
        import yaml

        # Cerca la voce AEROPONICS tra i gpio_pins
        for pin in self.configs.get('gpio_pins', []):
            if pin.get('name') == 'AEROPONICS':
                sep_old = pin.get('interval')
                if sep_old is None:
                    raise KeyError("La voce 'AEROPONICS' non ha 'interval'")

                # Calcola il nuovo interval e assicurati sia almeno 1
                new_interval = sep_old - self.T_modifier(T) * sep_old

                # Aggiorna la configurazione in memoria
                pin['interval'] = new_interval

                # Salva la configurazione sul file
                with open(self.config_file_name, 'w') as f:
                    yaml.safe_dump(self.configs, f, sort_keys=False)

                return new_interval

        # Se non trovata
        raise ValueError("Nessun gpio pin chiamato 'AEROPONICS' trovato nella configurazione")


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

        







