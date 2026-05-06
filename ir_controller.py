import os
import logging
from time import time


class IRController:
    """
    Class for managing infrared signals for air conditioning control.
    Use piir to send IR signals via GPIO (Transmit only).
    The ac_controller.json command file already exists and has already been registered.
    """

    def __init__(self, config, logger):
        """
        Initializes the IR controller.

        :param config: configuration dictionary (from config.yaml)
        :param logger: shared logger instance
        """
        self.config = config
        self.logger = logger

        # Parametri IR da config
        self.tx_gpio = config['ir_control']['tx_pin']
        self.file_ac_name = config['ir_control']['file_ac_name']
        self.time_max_on = float(config['ir_control'].get('time_max_on', 30.0))  # minuti

        # Parametri clima da T_var
        self.Topt = float(config['T_var']['Topt'])
        self.Hopt = float(config['T_var']['Hopt'])

        # Stato interno del controller
        self.last_command_sent = None   # 'Tlow', 'Hlow', 'off' o None
        self.command_sent_time = None   # timestamp (seconds) di quando è stato inviato Tlow o Hlow

        self.logger.info(
            f"IR_CONTROLLER: Inizializzato. TX_GPIO={self.tx_gpio}, "
            f"file={self.file_ac_name}, time_max_on={self.time_max_on} min, "
            f"Topt={self.Topt}°C, Hopt={self.Hopt}%"
        )

    # ------------------------------------------------------------------
    # Invio comandi
    # ------------------------------------------------------------------

    def send_command(self, command: str) -> int:
        """
        Send an IR command via piir.

        :param command: command name (e.g., 'Tlow', 'Hlow', 'off')
        :return: process exit code
        """
        cmd = f"piir play --gpio {self.tx_gpio} {self.file_ac_name} {command}"
        self.logger.info(f"IR_CONTROLLER: Invio comando '{command}' → GPIO {self.tx_gpio} | cmd: {cmd}")
        result = os.system(cmd)
        if result != 0:
            self.logger.warning(
                f"IR_CONTROLLER: Comando '{command}' terminato con exit code non-zero: {result}"
            )
        else:
            self.logger.info(f"IR_CONTROLLER: Comando '{command}' inviato correttamente.")
        return result

    # ------------------------------------------------------------------
    # Logica di controllo
    # ------------------------------------------------------------------

    def evaluate_and_send(self, current_temp: float, current_humidity: float):
        """
        Evaluates temperature and humidity against the targets and sends the appropriate AC command.

        Priority: Temperature > Humidity.
        If temperature control ('Tlow') is in progress, humidity control ('Hlow')
        is blocked until the air conditioner is turned off.
        If the maximum on time is exceeded, it automatically sends 'off'.

        :param current_temp: Current temperature (°C)
        :param current_humidity: Current relative humidity (%)
        """
        now = time() #take the time now

        # ---- Controllo time_max_on ----
        if self.last_command_sent in ('Tlow', 'Hlow') and self.command_sent_time is not None:
            elapsed_minutes = (now - self.command_sent_time) / 60.0
            if elapsed_minutes >= self.time_max_on:
                self.logger.info(
                    f"IR_CONTROLLER: Max time reached "
                    f"({elapsed_minutes:.1f}/{self.time_max_on} min). Send 'off'."
                )
                self.send_command('off')
                self.last_command_sent = 'off'
                self.command_sent_time = None
                return

        # ---- Controllo TEMPERATURA (priorità) ----
        if current_temp > self.Topt:
            if self.last_command_sent != 'Tlow':
                self.logger.info(
                    f"IR_CONTROLLER: T={current_temp:.1f}°C > Topt={self.Topt}°C → Send 'Tlow'."
                )
                self.send_command('Tlow')
                self.last_command_sent = 'Tlow'
                self.command_sent_time = now
            else:
                self.logger.debug(
                    f"IR_CONTROLLER: T={current_temp:.1f}°C > Topt={self.Topt}°C "
                    f"(Tlow controll already activated)."
                )
            # La temperatura ha la priorità: non si valuta l'umidità
            return

        # Temperatura OK → se era in Tlow, spegni
        if self.last_command_sent == 'Tlow':
            self.logger.info(
                f"IR_CONTROLLER: T={current_temp:.1f}°C ≤ Topt={self.Topt}°C. "
                f"Condizionamento temperatura completato → Invio 'off'."
            )
            self.send_command('off')
            self.last_command_sent = 'off'
            self.command_sent_time = None

        # ---- Controllo UMIDITÀ (solo se temperatura OK e AC non in modalità Tlow) ----
        if current_humidity > self.Hopt:
            if self.last_command_sent != 'Hlow':
                self.logger.info(
                    f"IR_CONTROLLER: H={current_humidity:.1f}% > Hopt={self.Hopt}% → Invio 'Hlow'."
                )
                self.send_command('Hlow')
                self.last_command_sent = 'Hlow'
                self.command_sent_time = now
            else:
                self.logger.debug(
                    f"IR_CONTROLLER: H={current_humidity:.1f}% > Hopt={self.Hopt}% "
                    f"(controllo Hlow già attivo)."
                )
        else:
            # Umidità OK → se era in Hlow, spegni
            if self.last_command_sent == 'Hlow':
                self.logger.info(
                    f"IR_CONTROLLER: H={current_humidity:.1f}% ≤ Hopt={self.Hopt}%. "
                    f"Condizionamento umidità completato → Invio 'off'."
                )
                self.send_command('off')
                self.last_command_sent = 'off'
                self.command_sent_time = None

    def force_off(self):
        """Forza lo spegnimento del condizionatore (usato alla disattivazione del controllo)."""
        self.logger.info("IR_CONTROLLER: Spegnimento forzato del condizionatore.")
        self.send_command('off')
        self.last_command_sent = 'off'
        self.command_sent_time = None