import threading
import schedule
from time import sleep


# =====================================================================
# Categoria JOB (AEROPONICS / IDROPONICS / job generici - GPIO pumps)
# =====================================================================
class JobsManager():
    '''
    Class for aeroGreenHouse JOBs control (AEROPONICS, IDROPONICS, job generici).
    Tutta la logica dei job e dei thread relativi vive qui.
    '''

    def __init__(self, configs, logger, gpios):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        :param gpios:   modulo GPIO gia' inizializzato dal core (aeroHelper)
        '''
        self.configs = configs
        self.logger = logger
        self.gpios = gpios

        # GPIO jobs control
        self.aeroponics_job_active = False  # controlla se viene eseguito il job aeroponics
        self.idroponics_job_active = False  # controlla se viene eseguito il job idroponics
        self.general_jobs_active = {}       # stato dei job generici {name: bool}

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
    # Avvio dei thread dei job (spostato da gui.py)
    ###########################################

    def start_aeroponics(self):
        '''Avvia il job AEROPONICS in un thread dedicato. Ritorna False se gia' attivo.'''
        if self.aeroponics_job_active:
            return False
        self.aeroponics_job_active = True
        threading.Thread(target=self.activate_aeroponics, daemon=True).start()
        return True

    def start_idroponics(self):
        '''Avvia il job IDROPONICS in un thread dedicato. Ritorna False se gia' attivo.'''
        if self.idroponics_job_active:
            return False
        self.idroponics_job_active = True
        threading.Thread(target=self.activate_idroponics, daemon=True).start()
        return True

    def start_general(self, gpio, on_time, interval, name):
        '''Avvia un job generico in un thread dedicato. Ritorna False se gia' attivo.'''
        if self.general_jobs_active.get(name, False):
            return False
        self.general_jobs_active[name] = True
        threading.Thread(
            target=self.on_off_general,
            kwargs=dict(gpio=gpio, on_period=on_time, off_period=interval, name=name),
            daemon=True
        ).start()
        return True

    ###########################################
    # Activation of GPIOs
    ###########################################

    def activate_aeroponics(self):
        '''
        Function that activate the AEROPONICS controller system

        :param
        '''

        self.logger.info('AEROPONICS system control ## ACTIVATED ##')

        self.aero_schedule = schedule.Scheduler()  # scheduler aeroponics
        self.aero_schedule.every(self.configs['gpio_pins'][0]['interval']).minutes.do(self.runner, job=self.pump_aerophonics, gpio=self.configs['gpio_pins'][0]['pin'], irrigation_time=self.configs['gpio_pins'][0]['on_time'])

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

        self.idro_schedule = schedule.Scheduler()  # scheduler idroponics

        self.idro_schedule.every(self.configs['gpio_pins'][1]['interval']).minutes.do(self.runner, job=self.pump_idrophonics, gpio_pump=self.configs['gpio_pins'][1]['pin'], gpio_sensor=self.configs['gpio_pins'][2]['pin'], max_irrigation_time=self.configs['gpio_pins'][1]['on_time'])
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
        :param off_period: (min) interval between activations - i.e. OFF period
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
                f'ON_OFF_GENERAL [{name}]: no matching entry in config.yaml - '
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

        # --- 5. Blocking loop - exits when deactivate_general(name) is called ---
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

    def pump_aerophonics(self, gpio, irrigation_time):
        '''
        Function for activating and deactivating the gpio for aerophonics watering system

        :param gpio: GPIO number
        :param irrigation_time: (s), time that the pump is activated
        '''

        # gpio = self.configs['gpio_pins'][0]['pin']
        # irrigation_time=self.configs['gpio_pins'][0]['on_time']

        self.gpios.output(gpio, False)  # turning on pump

        self.logger.info('AEROPONICS: Turning on the pump')

        for i in range(irrigation_time):
            if i == irrigation_time - 1:

                self.gpios.output(gpio, True)  # turning off the pump

                self.logger.info('AEROPONICS: Turning off the pump')
                break
            sleep(1)

    def pump_idrophonics(self, gpio_pump, gpio_sensor, max_irrigation_time):
        '''
        Function for activating and deactivating the gpio for idroponics watering system

        :param gpio: GPIO number
        :param max_irrigation_time: (s), maximum time that the pump is activated
        '''

        # uncomment this and remove the input variable in the function if does not work
        # gpio_pump = self.configs['gpio_pins'][1]['pin']
        # gpio_sensor = self.configs['gpio_pins'][2]['pin']
        # max_irrigation_time = self.configs['gpio_pins'][1]['on_time']

        for i in range(max_irrigation_time):

            # tempo massimo raggiunto
            if i == max_irrigation_time - 1:
                self.logger.info("IDROPONICS: Maximum time reached. Turning OFF the pump")
                self.gpios.output(gpio_pump, True)
                break

            # not activation of the pump
            if self.gpios.input(gpio_sensor) == 0:
                self.logger.info('IDROPONICS: Water level high. pump OFF.')
                self.gpios.output(gpio_pump, True)
                break

            # activation of the pump
            else:
                self.gpios.output(gpio_pump, False)  # turning on pump
                self.logger.info('IDROPONICS: Water level low, pump ON')
                sleep(1)

    ###########################################
    # Irrigation time modifier for Aerophonics
    ###########################################

    def T_modifier(self, T: float, t_old: float):
        '''
        Funzione per modificare il tempo di irrigazione in base alla temperatura settata

        INPUT:
            T =  Temperatura rilevata in C
            t_old = vecchio tempo di attesa tra le irrigazioni (in minuti)

        OUTPUT:
            t_new: nuovo tempo di sospensione tra le irrigazioni (in minuti)
        '''

        from math import exp
        Topt = self.configs['T_var']['Topt']
        a = -0.2
        amp = 1
        t_modifier = amp / (exp(a * (T - Topt)) + 1) - amp / 2  # time modifier
        t_new = t_new - t_new * t_modifier  # new time separation
        return t_new
