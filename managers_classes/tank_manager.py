import threading


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
