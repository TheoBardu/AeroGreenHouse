import threading
import schedule
from time import sleep
import os
import logging
from logging.handlers import TimedRotatingFileHandler

import RPi.GPIO as GPIO


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


# =====================================================================
# Categoria AMBIENTE (lettura DHT22, VPD, salvataggio e upload dati)
# =====================================================================
class AmbientManager():
    '''
    Class per la lettura dei dati ambientali (temperatura, umidita', VPD)
    tramite sensore DHT22, il salvataggio su file e l'upload online.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        # Last DHT22 reading
        self.last_T = None
        self.last_H = None

        # TH jobs control
        self.th_job_active = False   # controlla se viene eseguita la lettura dei dati TH
        self.th_job_saving = False   # controlla se viene eseguito il job TH (salvataggio dati TH e VPD)

        # Gestione thread di lettura periodica
        self._thread = None
        self._stop_event = threading.Event()

    ###########################################
    # DHT22 sensor measurements
    ###########################################
    def measure_dht22(self, gpio):
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
                # print('T = %4.2f C ;  H = %4.2f'%(T, H),'%', 'VPD = %5.4f kPa'%(self.VPD(T,H))) #For debug
                return T, H
                break
            except RuntimeError as error:
                print(error.args[0])
                sleep(2.0)
                continue
            except Exception as error:
                dht.exit()
                raise error

    def VPD(self, T, H):
        '''
        Function that calculate the VPD
        '''
        from math import exp
        es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))
        ea = lambda H: H * es(T) / 100

        VPD = es(T) - ea(H)
        return VPD

    ###########################################
    # Uploading data on website
    ###########################################
    def upload_data_on_web(self, T, H, vpd, timestamp):
        '''
        This module upload the data on website calling the local uploader.py module
        '''
        os.system(f'python uploader/uploader.py data -t {T} -hu {H} -vpd {vpd} -ts "{timestamp}"')

    ###########################################
    # Lettura periodica (spostata da gui.py)
    ###########################################
    def is_running(self):
        '''True se il thread di lettura ambient e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata dei dati ambient in un thread.

        :param on_update: callback opzionale on_update(temp, humidity, vpd, timestamp)
                          usata dalla GUI per aggiornare le label.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la lettura temporizzata. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche (logica originale, sleep interrompibile per stop immediato).'''
        import adafruit_dht
        import board
        from datetime import datetime

        interval = self.configs.get('dht22', {}).get('read_interval', 5)
        pin = self.configs.get('dht22', {}).get('pin', 27)

        self.logger.info(f"Inizio lettura AMBIENT. Intervallo: {interval}s, Pin: {pin}")
        dht = eval(f"adafruit_dht.DHT22(board.D{pin})")

        def measure_dht_22(dht):
            while True:
                try:
                    T = dht.temperature
                    H = dht.humidity
                    # print('T = %4.2f C ;  H = %4.2f'%(T, H),'%', 'VPD = %5.4f kPa'%(self.VPD(T,H))) #For debug
                    return T, H
                    break
                except RuntimeError as error:
                    print(error.args[0])
                    sleep(2.0)
                    continue
                except Exception as error:
                    dht.exit()
                    raise error

        while not self._stop_event.is_set():
            try:
                # Leggi i dati
                temp, humidity = measure_dht_22(dht)
                vpd = self.VPD(temp, humidity)

                self.last_T = temp
                self.last_H = humidity

                # Ottieni timestamp
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                file_name = datetime.now().strftime("%Y_%m_%d")

                # Aggiorna GUI tramite callback
                if on_update is not None:
                    on_update(temp, humidity, vpd, timestamp)

                self.logger.info(f"AMBIENT: T={temp:.2f}C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")

                # salva file
                format_data_out = "%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
                fid = open(self.configs.get('dht22', {}).get('saving_dir', '/home/fishnplants/Desktop/data/TH/') + 'TH_' + file_name + '.txt', 'a')
                fid.write(format_data_out % (timestamp, temp, humidity, vpd))
                fid.close()

                # carica file online
                try:
                    self.upload_data_on_web(temp, humidity, vpd, timestamp)
                except:
                    self.logger(f"AMBIENT: not able to upload the ambient data online. Check errors if occured")

                # Attendi l'intervallo (interrompibile)
                self._stop_event.wait(interval)

            except Exception as e:
                self.logger.error(f"Errore lettura AMBIENT: {str(e)}")
                self._stop_event.wait(interval)

        self.logger.info("Lettura AMBIENT interrotta")

    def read_now(self):
        '''
        Legge immediatamente i dati ambient.

        :return: tupla (temp, humidity, vpd, timestamp)
        '''
        from datetime import datetime

        pin = self.configs.get('dht22', {}).get('pin', 27)

        # Leggi i dati
        temp, humidity = self.measure_dht22(pin)
        vpd = self.VPD(temp, humidity)

        # Ottieni timestamp
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        self.logger.info(f"AMBIENT (lettura immediata): T={temp:.2f}C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")
        return temp, humidity, vpd, timestamp


# =====================================================================
# Categoria CONTROLLO REMOTO CONDIZIONATORE (IR)
# =====================================================================
class ClimateManager():
    '''
    Class per il controllo automatico del condizionatore tramite IR.
    Incapsula l'IRController e il loop di controllo (spostato da gui.py).
    '''

    def __init__(self, configs, logger, ambient):
        '''
        :param configs:  dizionario di configurazione (config.yaml)
        :param logger:   logger condiviso
        :param ambient:  istanza di AmbientManager (per leggere last_T / last_H)
        '''
        self.configs = configs
        self.logger = logger
        self.ambient = ambient

        self.ac_control_active = False
        self._thread = None
        self._stop_event = threading.Event()

        # Inizializza il controller IR con il logger condiviso
        from ir_controller.ir_controller import IRController
        self.ir_controller = IRController(self.configs, self.logger)

    def is_running(self):
        '''True se il controllo AC e' attivo.'''
        return self.ac_control_active

    def start(self, on_command_sent=None):
        '''
        Avvia il loop di controllo automatico del condizionatore.

        :param on_command_sent: callback opzionale on_command_sent(cmd) per aggiornare la GUI.
        :return: 'already_active' se gia' attivo, 'no_ambient' se manca la lettura ambient,
                 'started' se avviato correttamente.
        '''
        if self.ac_control_active:
            return 'already_active'

        if self.ambient.last_T is None or self.ambient.last_H is None:
            return 'no_ambient'

        self.ac_control_active = True
        self._stop_event.clear()

        self.logger.info("AC_CONTROL: Controllo automatico condizionatore ## ATTIVATO ##")

        def ac_control_loop():
            interval = self.configs.get('ir_control', {}).get('control_time', 15)
            while not self._stop_event.is_set():
                if self.ambient.last_T is not None and self.ambient.last_H is not None:
                    try:
                        self.ir_controller.evaluate_and_send(self.ambient.last_T, self.ambient.last_H)
                        # Notifica la GUI dell'ultimo comando inviato
                        last_cmd = self.ir_controller.last_command_sent or '--'
                        if on_command_sent is not None:
                            on_command_sent(last_cmd)
                    except Exception as e:
                        self.logger.error(f"AC_CONTROL: Errore nel loop di controllo: {e}")
                # control_time e' espresso in minuti (logica di main)
                self._stop_event.wait(interval * 60)

            self.logger.info("AC_CONTROL: Controllo automatico condizionatore ## DISATTIVATO ##")

        self._thread = threading.Thread(target=ac_control_loop, daemon=True)
        self._thread.start()
        return 'started'

    def stop(self):
        '''Arresta immediatamente il controllo AC e forza lo spegnimento. False se non attivo.'''
        if not self.ac_control_active:
            return False

        self._stop_event.set()
        self.ac_control_active = False

        # Forza spegnimento AC
        if self.ir_controller is not None:
            self.ir_controller.force_off()

        return True


# =====================================================================
# Categoria SERBATOIO (livello acqua via sensore ultrasonico HC-SR04)
# =====================================================================
class TankManager():
    '''
    Class per la lettura del livello dell'acqua nel serbatoio tramite il
    sensore ultrasonico HC-SR04. Riusa la logica di misura definita in
    ultrasonic_sensor/ultrasonic_measurement.py (nessuna riscrittura della fisica).
    I parametri di taratura sono letti dalla sezione 'tank' di config.yaml.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        self.last_result = None
        self._thread = None
        self._stop_event = threading.Event()
        self._gpio_ready = False

        # Riuso del modulo standalone (resta eseguibile da solo)
        from sensors.ultrasonic_sensor import ultrasonic_measurement as tank_mod
        self._tank = tank_mod

    def _params(self):
        '''Legge i parametri dalla sezione 'tank' di config.yaml con fallback alle costanti del modulo.'''
        t = self.configs.get('tank', {})
        return dict(
            trig=t.get('trig_pin', self._tank.GPIO_TRIG),
            echo=t.get('echo_pin', self._tank.GPIO_ECHO),
            height=t.get('tank_height_cm', self._tank.TANK_HEIGHT_CM),
            offset=t.get('sensor_offset_cm', self._tank.SENSOR_OFFSET_CM),
            area=t.get('tank_area_cm2', self._tank.TANK_AREA_CM2),
            low=t.get('water_low_threshold_l', self._tank.WATER_LOW_THRESHOLD_L),
            interval=t.get('read_interval', self._tank.READ_INTERVAL_S),
            n=t.get('n_samples', self._tank.N_SAMPLES),
            save=t.get('saving_dir', self._tank.SAVE_DIR),
        )

    def _ensure_gpio(self, trig, echo):
        '''Inizializza i pin del sensore una sola volta.'''
        if not self._gpio_ready:
            self._tank.initialize_gpio(trig, echo)
            self._gpio_ready = True
            self.logger.info(f"TANK: GPIO inizializzati TRIG=GPIO{trig}, ECHO=GPIO{echo}")

    def read_now(self):
        '''
        Esegue una misura singola del livello serbatoio.

        :return: dict con distance_cm, water_level_cm, volume_L, fill_percent, timestamp
                 oppure None se la misura non e' valida.
        '''
        from datetime import datetime

        p = self._params()
        self._ensure_gpio(p['trig'], p['echo'])

        dist = self._tank.measure_distance_avg(p['trig'], p['echo'], n_samples=p['n'])
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        if dist < 0:
            self.logger.warning("TANK: Misura non valida (timeout o fuori range). "
                                "Verificare il posizionamento del sensore.")
            return None

        # Range fisico del sensore (2-400 cm per HC-SR04)
        if dist < 2.0 or dist > 400.0:
            self.logger.warning(f"TANK: Distanza {dist:.1f}cm fuori dal range "
                                "operativo del sensore (2-400cm). Misura ignorata.")
            return None

        result = self._tank.distance_to_water_volume(dist, p['height'], p['offset'], p['area'])
        result['timestamp'] = timestamp
        self.last_result = result

        self.logger.info(
            f"TANK: dist={result['distance_cm']}cm | "
            f"livello={result['water_level_cm']}cm | "
            f"volume={result['volume_L']}L | "
            f"fill={result['fill_percent']}%"
        )
        return result

    def is_running(self):
        '''True se il thread di lettura serbatoio e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata del livello serbatoio in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la lettura serbatoio. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche del serbatoio (sleep interrompibile per stop immediato).'''
        p = self._params()
        self.logger.info(f"Inizio lettura TANK. Intervallo: {p['interval']}s, Campioni: {p['n']}")

        while not self._stop_event.is_set():
            try:
                result = self.read_now()
                if result is not None:
                    # Salvataggio su file (riusa save_data del modulo)
                    try:
                        self._tank.save_data(result, p['save'])
                    except Exception as e:
                        self.logger.error(f"TANK: errore nel salvataggio dati: {e}")

                    # Allarme livello basso
                    if result['volume_L'] < p['low']:
                        self.logger.warning(
                            f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                            f"sotto la soglia di {p['low']}L! Riempire la tanica."
                        )

                    if on_update is not None:
                        on_update(result)

            except Exception as e:
                self.logger.error(f"Errore lettura TANK: {str(e)}")

            # Attendi l'intervallo (interrompibile)
            self._stop_event.wait(p['interval'])

        self.logger.info("Lettura TANK interrotta")


# =====================================================================
# Categoria SPECTRO (indice di vegetazione MCARI2 - AS7265x)
# =====================================================================
class SpectroManager():
    '''
    Class per la misura dell'indice di vegetazione MCARI2 tramite il sensore
    spettrale AS7265x. Riusa il calcolo definito in
    spectrometer/mcari2_as7265x.py (nessuna riscrittura della formula).
    I parametri sono letti dalla sezione 'spectro' di config.yaml.

    A differenza degli altri sensori, la misura richiede una taratura sul
    riferimento bianco (has_calibration/calibrate) prima di poter essere eseguita.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        self.last_result = None
        self._thread = None
        self._stop_event = threading.Event()
        self._sensor = None

        # Riuso del modulo standalone (resta eseguibile da solo)
        from sensors.spectrometer import mcari2_as7265x as spectro_mod
        self._spectro = spectro_mod

        # Storico gia' disponibile all'avvio: le misure vivono sui file giornalieri.
        self.history = self.load_history()

    def _params(self):
        '''Legge i parametri dalla sezione 'spectro' di config.yaml con fallback alle costanti del modulo.'''
        s = self.configs.get('spectro', {})
        return dict(
            interval=s.get('read_interval', self._spectro.READ_INTERVAL_S),
            save=s.get('saving_dir', self._spectro.SAVE_DIR),
            history_len=s.get('history_len', 10),
        )

    def _ensure_sensor(self):
        '''Inizializza il sensore spettrale una sola volta.'''
        if self._sensor is None:
            self._sensor = self._spectro.init_sensor()
            self.logger.info("SPECTRO: sensore AS7265x inizializzato")
        return self._sensor

    def load_history(self):
        '''
        Rilegge lo storico delle misure dai file giornalieri SPECTRO_*.txt.

        :return: lista di dict {timestamp, mcari2, stato, testo}, dalla piu' recente.
        '''
        p = self._params()
        try:
            rows = self._spectro.load_measurements(save_dir=p['save'], max_rows=p['history_len'])
        except Exception as e:
            self.logger.error(f"SPECTRO: errore nella lettura dello storico: {e}")
            return []

        history = []
        for row in rows:
            index = row['mcari2']
            history.append({
                'timestamp': row['timestamp'].strftime("%Y/%m/%d %H:%M:%S"),
                'mcari2': index,
                'stato': self._spectro.classifica_mcari2(index),
                'testo': self._spectro.interpreta_mcari2(index),
            })
        return history

    def has_calibration(self):
        '''True se esiste una taratura salvata (riferimento bianco).'''
        p = self._params()
        try:
            self._spectro.load_calibration(save_dir=p['save'])
            return True
        except FileNotFoundError:
            return False

    def calibrate(self):
        '''
        Esegue la taratura sul riferimento bianco: il sensore va puntato su un
        pannello bianco prima di chiamare questo metodo.

        :return: dict {560, 680, 810} con i valori di riferimento misurati.
        '''
        p = self._params()
        sensor = self._ensure_sensor()
        reference = self._spectro.calibrate(sensor, save_dir=p['save'])
        self.logger.info(f"SPECTRO: taratura eseguita, riferimento bianco = {reference}")
        return reference

    def read_now(self):
        '''
        Esegue una misura singola dell'indice MCARI2, la salva e la aggiunge allo
        storico.

        Nota: a differenza di TankManager il salvataggio avviene qui e non nel
        loop, perche' sullo spettrometro la misura manuale e' il caso d'uso
        principale e deve comunque finire nello storico.

        :return: dict con bands, reflectance, mcari2, stato, testo, timestamp.
        :raises FileNotFoundError: se non esiste una taratura salvata.
        '''
        from datetime import datetime

        p = self._params()
        sensor = self._ensure_sensor()

        reference = self._spectro.load_calibration(save_dir=p['save'])
        bands, reflectance, index = self._spectro.measure_mcari2(sensor, reference_bands=reference)
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        result = {
            'bands': bands,
            'reflectance': reflectance,
            'mcari2': index,
            'stato': self._spectro.classifica_mcari2(index),
            'testo': self._spectro.interpreta_mcari2(index),
            'timestamp': timestamp,
        }
        self.last_result = result

        # Salvataggio su file (riusa save_measurement del modulo)
        try:
            self._spectro.save_measurement(bands, reflectance, index, save_dir=p['save'])
        except Exception as e:
            self.logger.error(f"SPECTRO: errore nel salvataggio dati: {e}")

        # Storico in memoria allineato al file (piu' recente in testa)
        self.history.insert(0, {k: result[k] for k in ('timestamp', 'mcari2', 'stato', 'testo')})
        del self.history[p['history_len']:]

        self.logger.info(f"SPECTRO: MCARI2={index:.4f} | stato={result['stato']} | {result['testo']}")

        if result['stato'] == self._spectro.STATO_STRESS:
            self.logger.warning(
                f"SPECTRO PLANT STRESS: MCARI2={index:.4f} sotto la soglia di 0.4. {result['testo']}"
            )

        return result

    def is_running(self):
        '''True se il thread di lettura spettrometro e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    def start_reading(self, on_update=None):
        '''
        Avvia la lettura temporizzata dell'indice MCARI2 in un thread.

        :param on_update: callback opzionale on_update(result_dict) per aggiornare la GUI.
        :return: False se una lettura e' gia' in corso, True altrimenti.
        '''
        if self.is_running():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, args=(on_update,), daemon=True)
        self._thread.start()
        return True

    def stop_reading(self):
        '''Arresta immediatamente la lettura spettrometro. False se non era in corso.'''
        if not self.is_running():
            return False
        self._stop_event.set()
        return True

    def _read_loop(self, on_update):
        '''Loop per letture periodiche dell'MCARI2 (sleep interrompibile per stop immediato).'''
        p = self._params()
        self.logger.info(f"Inizio lettura SPECTRO. Intervallo: {p['interval']}s")

        while not self._stop_event.is_set():
            try:
                # read_now() salva e aggiorna lo storico
                result = self.read_now()
                if result is not None and on_update is not None:
                    on_update(result)

            except Exception as e:
                self.logger.error(f"Errore lettura SPECTRO: {str(e)}")

            # Attendi l'intervallo (interrompibile)
            self._stop_event.wait(p['interval'])

        self.logger.info("Lettura SPECTRO interrotta")


# =====================================================================
# CORE - Coordinatore (config + logging + GPIO + manager di categoria)
# =====================================================================
class aeroHelper():

    '''
    Coordinatore per aeroGreenHouse: carica la configurazione, configura il
    logging, inizializza la GPIO una sola volta e istanzia i manager di
    categoria (jobs, ambient, climate, tank, spectro), condividendo
    configs/logger/gpios.
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
