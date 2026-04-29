"""
ir_controller.py
Modulo FnP per il controllo IR del climatizzatore
Integrazione con AeroGreenHouse via pigpio + PiIR
"""

import pigpio
import piir
import logging
from time import sleep

class IRController:
    """
    Classe per il controllo IR del climatizzatore
    da integrare in aeroHelper
    """

    def __init__(self, tx_pin: int, rx_pin: int, remote_file: str):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.remote_file = remote_file
        self.logger = logging.getLogger(__name__)

        # Connessione al deamon pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("Impossibile connettersi al demone pigpiod. Esegui: sudo systemctl start pigpiod")

        self.logger.info(f"IRController inizializzato. TX=GPIO{tx_pin}, RX=GPIO{rx_pin}")

    def send_command(self, command_name: str) -> bool:
        """
        Invia un comando IR al climatizzatore.

        :param command_name: Nome del tasto registrato nel file JSON
        :return: True se successo, False altrimenti
        """
        try:
            remote = piir.Remote(self.remote_file, self.pi, self.tx_pin)
            remote.send(command_name)
            self.logger.info(f"IR: Comando '{command_name}' inviato con successo")
            return True
        except Exception as e:
            self.logger.error(f"IR: Errore nell'invio del comando '{command_name}': {e}")
            return False

    def record_command(self, command_name: str) -> bool:
        """
        Registra un nuovo comando IR dal telecomando.

        :param command_name: Nome da assegnare al tasto
        :return: True se successo
        """
        try:
            from piir.io import receive
            from piir.decode import decode
            import json, os

            self.logger.info(f"IR: In attesa del segnale per '{command_name}'...")
            keys = {}
            data = None
            while data is None:
                raw = receive(self.rx_pin, self.pi)
                data = decode(raw)
            keys[command_name] = data

            # Carica file esistente o crea nuovo
            if os.path.exists(self.remote_file):
                with open(self.remote_file, 'r') as f:
                    existing = json.load(f)
                existing.update(keys)
                keys = existing

            from piir.prettify import prettify
            with open(self.remote_file, 'w') as f:
                json.dump(prettify(keys), f, indent=2)

            self.logger.info(f"IR: Comando '{command_name}' registrato in {self.remote_file}")
            return True
        except Exception as e:
            self.logger.error(f"IR: Errore nella registrazione: {e}")
            return False

    def cleanup(self):
        """Chiude la connessione pigpio"""
        if self.pi.connected:
            self.pi.stop()
            self.logger.info("IR: Connessione pigpio chiusa")