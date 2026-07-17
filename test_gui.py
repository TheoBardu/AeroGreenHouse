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
  - Inietta letture sensori SIMULATE (temperatura, umidita', livello serbatoio,
    spettro AS7265x, altezza pianta) cosi' le tab Ambient, Livelli Serbatoio,
    Spettrometro e Crescita mostrano valori realistici.
  - Semina dati di esempio (taratura e storico MCARI2, 10 giorni di crescita,
    letture TH e livello serbatoio) cosi' le tab Spettrometro, Crescita e
    soprattutto Riepilogo sono gia' popolate al primo avvio.
  - Rende l'invio dei comandi IR e l'upload web delle no-op (nessun effetto reale).
  - Dirotta la calibrazione del sensore di altezza su una COPIA del config
    (_gui_test_data/config_sim.yaml): premendo 'Calibrazione' il config.yaml
    reale non viene toccato.
  - Avvia la vera GUI (gui.AeroGreenHouseGUI).

NB: e' SOLO uno strumento di sviluppo. Sul Raspberry Pi va eseguito `python gui.py`.

Uso:
    python3 test_gui.py
    GUI_SMOKE=1 python3 test_gui.py   # smoke test: costruisce la GUI e chiude subito
"""

import os
import sys
import json
import types
import random
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

# Cartella locale scrivibile per log e dati simulati
TEST_DATA_DIR = os.path.join(HERE, '_gui_test_data')
os.makedirs(TEST_DATA_DIR, exist_ok=True)

# Dati dello spettrometro (taratura + file giornalieri SPECTRO_*.txt)
SPECTRO_DIR = os.path.join(TEST_DATA_DIR, 'SPECTRO')
os.makedirs(SPECTRO_DIR, exist_ok=True)

# Dati di crescita (file cumulativo GROWTH.csv)
GROWTH_DIR = os.path.join(TEST_DATA_DIR, 'GROWTH')
os.makedirs(GROWTH_DIR, exist_ok=True)

# Copia del config su cui scrive la calibrazione (mai il config.yaml reale)
SIM_CONFIG = os.path.join(TEST_DATA_DIR, 'config_sim.yaml')

# Valore del riferimento bianco simulato su ogni banda: i getter del sensore
# finto restituiscono riflettanza * WHITE_REF, cosi' la riflettanza calcolata
# dal modulo e' esattamente quella voluta.
WHITE_REF = 1000.0


# ---------------------------------------------------------------------------
# 1) Stub dei moduli hardware (devono essere registrati PRIMA di importare i
#    moduli del progetto che fanno `import RPi.GPIO`, ecc.)
# ---------------------------------------------------------------------------
class _SimState:
    """Stato per generare letture simulate con un piccolo random walk."""
    temp = 24.0      # C
    humidity = 60.0  # %
    distance = 15.0  # cm (distanza sensore-acqua)

    # Distanza sensore-pianta [cm]: parte vicino al riferimento (70cm, pianta
    # appena piantata) e cala man mano che la pianta cresce.
    growth_distance = 64.0

    # Riflettanza delle tre bande MCARI2. Con green=0.15, red=0.05, nir=0.60
    # l'indice vale ~0.87 ("coltura sana"); facendo camminare il NIR
    # nell'intervallo sotto, l'indice attraversa tutte e quattro le fasce e la
    # spia di stato cambia colore durante l'ispezione.
    r_green = 0.15
    r_red = 0.05
    r_nir = 0.60


def _walk(value, lo, hi, step, ndigits=1):
    value += random.uniform(-step, step)
    return round(max(lo, min(hi, value)), ndigits)


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

    # ---- qwiic_as7265x (sensore spettrale) ----
    # Va registrato PRIMA che venga importato mcari2_as7265x: quel modulo fissa
    # _HW_AVAILABLE a import-time e senza questo stub init_sensor() solleverebbe
    # RuntimeError, rendendo la tab Spettrometro inutilizzabile in simulazione.
    class _QwiicAS7265x:
        # Riflettanza simulata per le lettere dei canali usati dalla formula
        # MCARI2 (g=560nm GREEN, s=680nm RED, v=810nm NIR).
        def is_connected(self): return True
        def begin(self): return True
        def set_gain(self, *a, **k): pass
        def set_integration_cycles(self, *a, **k): pass
        def disable_indicator(self, *a, **k): pass
        def enable_bulb(self, *a, **k): pass
        def disable_bulb(self, *a, **k): pass

        def take_measurements(self):
            # Nuova misura: solo il NIR cammina, come farebbe una pianta che
            # cambia stato lentamente mantenendo green/red piu' stabili.
            _SimState.r_nir = _walk(_SimState.r_nir, 0.35, 0.75, 0.06, ndigits=3)
            _SimState.r_green = _walk(_SimState.r_green, 0.12, 0.18, 0.01, ndigits=3)
            _SimState.r_red = _walk(_SimState.r_red, 0.03, 0.08, 0.01, ndigits=3)

        def __getattr__(self, name):
            # get_calibrated_<lettera> per tutti i 18 canali: le tre bande della
            # formula tornano il valore simulato, le altre un valore plausibile.
            if not name.startswith('get_calibrated_'):
                raise AttributeError(name)
            letter = name[len('get_calibrated_'):]
            refl = {'g': _SimState.r_green, 's': _SimState.r_red, 'v': _SimState.r_nir}
            return lambda: refl.get(letter, 0.20) * WHITE_REF

    qwiic = types.ModuleType('qwiic_as7265x')
    qwiic.QwiicAS7265x = _QwiicAS7265x
    qwiic.kGain16x = 2
    qwiic.kLedWhite = 0
    sys.modules['qwiic_as7265x'] = qwiic


_install_hardware_stubs()


# ---------------------------------------------------------------------------
# 2) Patch di percorsi e comportamenti per la simulazione
# ---------------------------------------------------------------------------
import shutil

import yaml
import helper_aeroGreenHouse as H
import ir_controller.ir_controller as ir_controller
from managers_classes import plant_growth as PG
from sensors.ultrasonic_sensor import ultrasonic_measurement as TM
from sensors.spectrometer import mcari2_as7265x as SP


def _seed_spectro_data():
    """
    Semina taratura e storico MCARI2 di esempio in SPECTRO_DIR.

    Senza taratura la tab Spettrometro non potrebbe misurare (l'MCARI2 si calcola
    sulla riflettanza) e senza file giornalieri lo storico partirebbe vuoto.
    """
    # Taratura: gain e cicli devono coincidere con quelli del modulo, altrimenti
    # load_calibration stampa un avviso di mismatch.
    calib = {
        "reference": {"560": WHITE_REF, "680": WHITE_REF, "810": WHITE_REF},
        "gain": SP.GAIN,
        "integration_cycles": SP.INTEGRATION_CYCLES,
        "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }
    with open(os.path.join(SPECTRO_DIR, SP.CALIB_NAME), 'w') as f:
        json.dump(calib, f, indent=2)

    # Storico: un valore per fascia (stress / limite / sana / molto sana) su
    # giorni diversi, cosi' la tabella mostra subito tutti e quattro i colori.
    mock = [(4, 0.3100), (3, 0.5200), (2, 0.7400), (1, 0.9300)]

    for days_ago, index in mock:
        day = datetime.now() - timedelta(days=days_ago)
        file_path = os.path.join(SPECTRO_DIR, day.strftime(SP.FILE_FORMAT))
        if os.path.exists(file_path):
            continue  # gia' seminato in un avvio precedente

        # Riflettanze coerenti col valore: servono solo a riempire le colonne.
        r_green, r_red, r_nir = 0.15, 0.05, 0.30 + index * 0.35
        with open(file_path, 'w') as f:
            f.write("datetime\t\t\t green_raw\t red_raw\t nir_raw\t "
                    "R_green\t R_red\t R_nir\t MCARI2\n")
            f.write(f"{day.strftime('%Y/%m/%d %H:%M:%S')}\t"
                    f"{r_green * WHITE_REF:.2f}\t{r_red * WHITE_REF:.2f}\t{r_nir * WHITE_REF:.2f}\t"
                    f"{r_green:.4f}\t{r_red:.4f}\t{r_nir:.4f}\t{index:.4f}\n")


def _seed_growth_data():
    """
    Semina uno storico di crescita in GROWTH_DIR, cosi' la tab Crescita mostra
    subito grafico e tabella popolati (altrimenti servirebbero giorni di misure).
    """
    csv_path = os.path.join(GROWTH_DIR, 'GROWTH.csv')
    if os.path.exists(csv_path):
        return  # gia' seminato in un avvio precedente

    # Curva di crescita plausibile: da 0cm a ~6cm in 10 giorni
    with open(csv_path, 'w') as f:
        f.write("datetime,h_plant_cm\n")
        for days_ago in range(10, 0, -1):
            day = datetime.now() - timedelta(days=days_ago)
            h_plant = round(max(0.0, (10 - days_ago) * 0.7 + random.uniform(-0.2, 0.2)), 1)
            f.write(f"{day.strftime('%Y/%m/%d %H:%M:%S')},{h_plant}\n")


def _redirect_calibration():
    """
    Fa scrivere la calibrazione dell'altezza su una copia del config.

    Senza questo, premere 'Calibrazione' nella GUI di sviluppo riscriverebbe il
    config.yaml REALE con un valore inventato dal sensore finto. La copia viene
    rifatta ad ogni avvio, cosi' resta fedele al config vero.
    """
    shutil.copyfile('config.yaml', SIM_CONFIG)
    PG.CONFIG_FILE = SIM_CONFIG


def _seed_th_data():
    """
    Semina un file TH di oggi, cosi' il blocco Ambiente del Riepilogo mostra
    T/H/VPD con la data gia' all'avvio (senza, sarebbe vuoto fino alla prima
    lettura del sensore).
    """
    day = datetime.now()
    path = os.path.join(TEST_DATA_DIR, day.strftime('TH_%Y_%m_%d.txt'))
    if os.path.exists(path):
        return  # gia' seminato (o scritto da una lettura simulata)

    # Stesso formato di AmbientManager._read_loop: unita' attaccate ai valori
    with open(path, 'w') as f:
        for minuti in (30, 20, 10):
            t = day - timedelta(minutes=minuti)
            temp = round(random.uniform(22.0, 25.0), 2)
            hum = round(random.uniform(55.0, 65.0), 2)
            vpd = round(0.6108 * 2.718281828 ** (17.27 * temp / (temp + 273.3)) * (1 - hum / 100), 4)
            f.write("%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
                    % (t.strftime('%Y/%m/%d %H:%M:%S'), temp, hum, vpd))


def _seed_tank_data():
    """
    Semina un file TANK di oggi, cosi' il blocco Serbatoio del Riepilogo e'
    popolato all'avvio: il livello e' l'unico dato che si perderebbe ad ogni
    riavvio del programma.
    """
    day = datetime.now()
    path = os.path.join(TEST_DATA_DIR, day.strftime('TANK_%Y_%m_%d.txt'))
    if os.path.exists(path):
        return

    # Stesso formato di ultrasonic_measurement.save_data (header + righe)
    with open(path, 'w') as f:
        f.write("datetime\t\t\t dist_cm\t lvl_cm\t vol_L\t fill_%\n")
        for minuti in (30, 20, 10):
            t = day - timedelta(minutes=minuti)
            dist = round(random.uniform(10.0, 14.0), 1)
            livello = round(30.0 - (dist - 2.0), 1)
            f.write(f"{t.strftime('%Y/%m/%d %H:%M:%S')}\t{dist:6.1f}\t{livello:6.1f}\t"
                    f"{livello * 900.0 / 1000.0:7.2f}\t{livello / 30.0 * 100:5.1f}\n")


_seed_spectro_data()
_seed_growth_data()
_seed_th_data()
_seed_tank_data()
_redirect_calibration()


def _patched_load_config(self, file_name):
    """Carica il config reale ma reindirizza percorsi e accorcia gli intervalli."""
    with open(file_name, 'r') as f:
        cfg = yaml.safe_load(f)

    sep = os.sep
    cfg.setdefault('log', {})['directory'] = TEST_DATA_DIR
    cfg.setdefault('dht22', {})['saving_dir'] = TEST_DATA_DIR + sep
    cfg.setdefault('tank', {})['saving_dir'] = TEST_DATA_DIR + sep
    cfg.setdefault('spectro', {})['saving_dir'] = SPECTRO_DIR
    cfg.setdefault('plant_growth', {})['saving_dir'] = GROWTH_DIR

    # Intervalli brevi per vedere subito gli aggiornamenti durante l'ispezione
    cfg['dht22']['read_interval'] = 3
    cfg['tank']['read_interval'] = 3
    cfg['tank']['n_samples'] = 1
    cfg['spectro']['read_interval'] = 3
    cfg['plant_growth']['n_samples'] = 1
    # 3 secondi espressi in giorni: in produzione la misura e' ogni giorno, ma in
    # simulazione l'attesa terrebbe la tab Crescita immobile per 24 ore.
    cfg['plant_growth']['read_interval_days'] = 3 / 86400
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


# Misura crescita simulata: la distanza cala lentamente (la pianta cresce)
def _sim_measure_distance_mean(trig_pin, echo_pin, n_samples=3, delay=0.065):
    _SimState.growth_distance = _walk(_SimState.growth_distance, 55.0, 70.0, 0.5)
    return _SimState.growth_distance


TM.measure_distance_mean = _sim_measure_distance_mean


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
          "'Attiva Lettura' per gli aggiornamenti periodici (~3s).")
    print("Tab Crescita: grafico e tabella partono gia' popolati con 10 giorni "
          "di storico; 'Attiva Lettura' aggiunge un punto ogni ~3s.")
    root.mainloop()


if __name__ == '__main__':
    main()
