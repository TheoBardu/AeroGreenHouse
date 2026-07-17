import threading


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
