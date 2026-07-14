#!/usr/bin/env python3
"""
test_gui.py - Ispeziona la GUI AeroGreenHouse da una macchina di sviluppo
==========================================================================
Permette di avviare e ispezionare visivamente gui.py SENZA il Raspberry Pi
e senza alcun hardware collegato.

Cosa fa:
  - Sostituisce con degli STUB i moduli hardware (RPi.GPIO, adafruit_dht, board)
    in modo che import e inizializzazioni non falliscano.
  - Reindirizza le cartelle di log/salvataggio dati in una cartella locale
    (./_gui_test_data) cosi' il logging funziona anche su Mac/Windows.
  - Inietta letture sensori SIMULATE (temperatura, umidita', livello serbatoio)
    cosi' le tab Ambient e Livelli Serbatoio mostrano valori realistici.
  - Rende l'invio dei comandi IR e l'upload web delle no-op (nessun effetto reale).
  - Avvia la vera GUI (gui.AeroGreenHouseGUI).

NB: e' SOLO uno strumento di sviluppo. Sul Raspberry Pi va eseguito `python gui.py`.

Uso:
    python3 test_gui.py
    GUI_SMOKE=1 python3 test_gui.py   # smoke test: costruisce la GUI e chiude subito
"""

import os
import sys
import types
import random

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

# Cartella locale scrivibile per log e dati simulati
TEST_DATA_DIR = os.path.join(HERE, '_gui_test_data')
os.makedirs(TEST_DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 1) Stub dei moduli hardware (devono essere registrati PRIMA di importare i
#    moduli del progetto che fanno `import RPi.GPIO`, ecc.)
# ---------------------------------------------------------------------------
class _SimState:
    """Stato per generare letture simulate con un piccolo random walk."""
    temp = 24.0      # C
    humidity = 60.0  # %
    distance = 15.0  # cm (distanza sensore-acqua)


def _walk(value, lo, hi, step):
    value += random.uniform(-step, step)
    return round(max(lo, min(hi, value)), 1)


def _install_hardware_stubs():
    # ---- RPi.GPIO ----
    class _GPIO:
        BCM = 'BCM'; BOARD = 'BOARD'; IN = 'IN'; OUT = 'OUT'; HIGH = 1; LOW = 0

        def setmode(self, *a, **k): pass
        def setwarnings(self, *a, **k): pass
        def setup(self, *a, **k): pass
        def output(self, *a, **k): pass
        def input(self, *a, **k): return 0
        def cleanup(self, *a, **k): pass

    rpi = types.ModuleType('RPi')
    rpi.GPIO = _GPIO()
    sys.modules['RPi'] = rpi
    sys.modules['RPi.GPIO'] = rpi.GPIO

    # ---- adafruit_dht ----
    class _DHT22:
        def __init__(self, pin):
            self.pin = pin

        @property
        def temperature(self):
            _SimState.temp = _walk(_SimState.temp, 18.0, 32.0, 0.4)
            return _SimState.temp

        @property
        def humidity(self):
            _SimState.humidity = _walk(_SimState.humidity, 40.0, 80.0, 0.8)
            return _SimState.humidity

        def exit(self):
            pass

    adafruit_dht = types.ModuleType('adafruit_dht')
    adafruit_dht.DHT22 = _DHT22
    sys.modules['adafruit_dht'] = adafruit_dht

    # ---- board (board.D27 ecc. -> qualunque attributo) ----
    board = types.ModuleType('board')
    board.__getattr__ = lambda name: 'PIN_' + name  # PEP 562
    sys.modules['board'] = board


_install_hardware_stubs()


# ---------------------------------------------------------------------------
# 2) Patch di percorsi e comportamenti per la simulazione
# ---------------------------------------------------------------------------
import yaml
import helper_aeroGreenHouse as H
import ir_controller.ir_controller as ir_controller
from ultrasonic_sensor import ultrasonic_measurement as TM


def _patched_load_config(self, file_name):
    """Carica il config reale ma reindirizza percorsi e accorcia gli intervalli."""
    with open(file_name, 'r') as f:
        cfg = yaml.safe_load(f)

    sep = os.sep
    cfg.setdefault('log', {})['directory'] = TEST_DATA_DIR
    cfg.setdefault('dht22', {})['saving_dir'] = TEST_DATA_DIR + sep
    cfg.setdefault('tank', {})['saving_dir'] = TEST_DATA_DIR + sep

    # Intervalli brevi per vedere subito gli aggiornamenti durante l'ispezione
    cfg['dht22']['read_interval'] = 3
    cfg['tank']['read_interval'] = 3
    cfg['tank']['n_samples'] = 1
    return cfg


H.aeroHelper.load_config = _patched_load_config

# Nessun upload web reale
H.AmbientManager.upload_data_on_web = lambda self, *a, **k: None

# Nessun comando IR reale (niente chiamata a `piir`): solo log
def _sim_send_command(self, command):
    self.logger.info(f"[SIM] IR send '{command}' (no hardware)")
    return 0


ir_controller.IRController.send_command = _sim_send_command


# Misura serbatoio simulata (evita il timing GPIO reale)
def _sim_measure_distance_avg(trig_pin, echo_pin, n_samples=5, delay=0.065):
    _SimState.distance = _walk(_SimState.distance, 5.0, 28.0, 0.6)
    return _SimState.distance


TM.measure_distance_avg = _sim_measure_distance_avg


# ---------------------------------------------------------------------------
# 3) Avvio della GUI
# ---------------------------------------------------------------------------
def main():
    try:
        import tkinter as tk
    except Exception as e:
        print(f"[ERRORE] tkinter non disponibile: {e}")
        sys.exit(1)

    import gui

    # gui.py non importa aeroHelper a livello di modulo (import commentato):
    # lo iniettiamo qui, dopo aver installato gli stub hardware.
    gui.aeroHelper = H.aeroHelper

    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"[ERRORE] Impossibile aprire una finestra (display non disponibile): {e}")
        sys.exit(1)

    app = gui.AeroGreenHouseGUI(root)
    root.title("AeroGreenHouse Control Panel  —  [SIMULAZIONE / dev, nessun hardware]")

    # Smoke test: costruisci la GUI, aggiorna una volta e chiudi (per CI/verifica).
    if os.environ.get('GUI_SMOKE'):
        root.update_idletasks()
        root.update()
        root.destroy()
        print("[OK] GUI costruita correttamente (smoke test).")
        return

    print("GUI avviata in modalita' SIMULAZIONE.")
    print(f"Log e dati simulati in: {TEST_DATA_DIR}")
    print("Suggerimento: usa 'Leggi Adesso' per letture immediate, "
          "'Attiva Lettura' per gli aggiornamenti periodici.")
    root.mainloop()


if __name__ == '__main__':
    main()
