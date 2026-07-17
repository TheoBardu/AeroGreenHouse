import threading


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
