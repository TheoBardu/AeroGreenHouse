#!/usr/bin/env python3
"""
test_gui.py - Ispeziona la GUI AeroGreenHouse da una macchina di sviluppo
==========================================================================
Permette di avviare e ispezionare visivamente gui.py SENZA il Raspberry Pi
e senza alcun hardware collegato.

Cosa fa:
  - Sostituisce con degli STUB i moduli hardware (RPi.GPIO, adafruit_dht, board,
    qwiic_as7265x, picamera2) e anche pyserial, che non serve piu' installare:
    gui.py importa arduino_link, quindi senza stub l'avvio muore con
    "No module named 'serial.tools'".
  - Simula l'Arduino con una PORTA SERIALE FINTA che parla il protocollo dello
    sketch (read_pH,A0 -> read_pH,A0:6.42): il codice vero - composizione dei
    comandi, parsing, manager - gira invariato, quindi si vede il comportamento
    reale e non un'imitazione. Una lettura su otto circa fallisce, cosi' anche
    la sezione "Errori di lettura" resta viva.
  - Reindirizza le cartelle di log/salvataggio dati in una cartella locale
    (./_gui_test_data) cosi' il logging funziona anche su Mac/Windows.
  - Inietta letture sensori SIMULATE (temperatura, umidita', pH, conducibilita'
    elettrica, livello serbatoio, spettro AS7265x, altezza pianta) cosi' le
    schermate Ambiente, H2O, Spettrometro e Crescita mostrano valori realistici.
  - Semina dati di esempio (taratura e storico MCARI2, 10 giorni di crescita,
    letture TH, livello serbatoio, pH/EC ed errori di lettura) cosi' le
    schermate H2O, Spettrometro, Crescita, Log e soprattutto Riepilogo sono
    gia' popolate al primo avvio.
  - Rende l'invio dei comandi IR e l'upload web delle no-op (nessun effetto reale).
  - Disattiva 'Salva Configurazione': e' solo un visualizzatore, non deve
    scrivere nulla.
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

# Foto della camera e plot dell'elaborazione giornaliera
IMG_DIR = os.path.join(TEST_DATA_DIR, 'IMG')
os.makedirs(IMG_DIR, exist_ok=True)

PLOT_DIR = os.path.join(TEST_DATA_DIR, 'PLOT')
os.makedirs(PLOT_DIR, exist_ok=True)

# Dati dell'acqua (pH ed EC) ed errori di lettura delle sonde
WATER_DIR = os.path.join(TEST_DATA_DIR, 'WATER')
os.makedirs(WATER_DIR, exist_ok=True)

ERRORS_DIR = os.path.join(TEST_DATA_DIR, 'ERRORS')
os.makedirs(ERRORS_DIR, exist_ok=True)

# Copia del config su cui scrive la calibrazione (mai il config.yaml reale)
SIM_CONFIG = os.path.join(TEST_DATA_DIR, 'config_sim.yaml')

# ---- Arduino simulato ----
# Porta seriale inesistente: e' l'unica che il finto pyserial accetta di
# aprire, cosi' un errore di configurazione si nota subito invece di finire
# silenziosamente su una porta vera.
SIM_PORT = '/dev/ttySIM0'

# Pin TRIG dei due HC-SR04, come nella sezione 'arduino' del config simulato.
# Servono anche alla porta finta: e' il TRIG a dirle QUALE dei due sensori
# ultrasonici le e' stato chiesto, esattamente come sull'Arduino vero.
SIM_TRIG_WATER = 2
SIM_TRIG_PLANT = 4

# Quota di letture che falliscono ('ERR' come risposta). Una su otto circa:
# abbastanza da veder vivere la sezione "Errori di lettura" della schermata
# Log, non tanta da rendere le pagine inutilizzabili.
ERR_RATE = 0.12

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

    # pH dell'acqua. Cammina attorno all'intervallo buono (5.5-6.5 nel config),
    # sconfinando ogni tanto: cosi' durante l'ispezione la pill di stato della
    # card pH cambia colore, come fa la spia dell'MCARI2.
    ph = 6.2

    # Conducibilita' elettrica [uS/cm] e salinita' [PSU]. Il TDS non e' uno
    # stato a se': l'EZO-EC lo ricava dall'EC, e la porta finta fa lo stesso.
    ec = 1250.0
    sal = 0.62

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


class _FakeSerialException(Exception):
    """Equivalente di serial.SerialException: porta assente o caduta."""


def _sim_comports():
    """
    Elenco delle porte USB "collegate", per il bottone «Rileva schede».

    Restituisce un oggetto con gli stessi attributi che
    arduino_link.list_serial_ports() legge da pyserial.
    """
    return [types.SimpleNamespace(device=SIM_PORT,
                                  description='Arduino Uno simulato',
                                  hwid='USB VID:PID=SIM:0001')]


class _FakeArduinoSerial:
    """
    Porta seriale finta che parla il protocollo dello sketch Arduino.

    Simulare a questo livello, e non sostituendo i metodi di ArduinoHub,
    lascia girare invariato tutto il codice vero: composizione del comando,
    parsing della risposta, gestione degli errori e dei manager. Quello che
    si vede nel visualizzatore e' quindi il comportamento reale, comandi e
    anteprime compresi.

    Implementa la sola superficie che ArduinoBoard usa davvero: is_open,
    reset_input_buffer(), close(), write(), readline().
    """

    def __init__(self, port, baudrate, timeout=None):
        if port != SIM_PORT:
            # Stessa eccezione di pyserial: cosi' resta ispezionabile anche
            # il percorso "scheda non raggiungibile" dei manager.
            raise _FakeSerialException(f"could not open port {port}")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self._out = []   # righe di risposta in attesa di essere lette

    def reset_input_buffer(self):
        self._out.clear()

    def close(self):
        self.is_open = False

    def write(self, data):
        """Interpreta il comando e prepara la risposta, come farebbe lo sketch."""
        cmd = data.decode('utf-8').strip()
        nome = cmd.split(',')[0]

        # Sonda che ogni tanto non risponde in modo attendibile: e' il modo
        # in cui l'Arduino vero segnala una lettura da buttare.
        if random.random() < ERR_RATE:
            self._out.append(f"{cmd}:ERR\n")
            return

        if nome == 'read_pH':
            _SimState.ph = _walk(_SimState.ph, 5.2, 6.9, 0.15, ndigits=2)
            valore = f"{_SimState.ph:.2f}"

        elif nome == 'read_EC':
            _SimState.ec = _walk(_SimState.ec, 700.0, 2200.0, 60.0)
            _SimState.sal = _walk(_SimState.sal, 0.40, 0.90, 0.03, ndigits=2)
            # L'EZO-EC restituisce EC, TDS e salinita' in un'unica risposta;
            # il TDS e' circa meta' dell'EC (fattore di conversione 0.5).
            valore = f"{_SimState.ec:.1f},{_SimState.ec / 2:.1f},{_SimState.sal:.2f}"

        elif nome == 'read_us':
            # I pin distinguono i due sensori, esattamente come sull'Arduino:
            # la coppia del serbatoio da' la distanza dal pelo dell'acqua,
            # l'altra quella dalla cima della pianta.
            trig = cmd.split(',')[1] if ',' in cmd else ''
            if trig == str(SIM_TRIG_WATER):
                _SimState.distance = _walk(_SimState.distance, 5.0, 28.0, 0.6)
                valore = f"{_SimState.distance:.2f}"
            else:
                _SimState.growth_distance = _walk(_SimState.growth_distance, 55.0, 70.0, 0.5)
                valore = f"{_SimState.growth_distance:.2f}"

        else:
            # Comando non riconosciuto: stessa risposta dello sketch
            self._out.append(f"ERR:{cmd}\n")
            return

        # Lo sketch rieccheggia il comando completo prima del valore
        self._out.append(f"{cmd}:{valore}\n")

    def readline(self):
        """Una riga di risposta; stringa vuota se non c'e' nulla (timeout)."""
        return self._out.pop(0).encode('utf-8') if self._out else b''


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

    # ---- serial (pyserial) ----
    # Va registrato QUI e non piu' avanti: gui.py importa arduino_link a
    # livello di modulo, e quel modulo fa "import serial.tools.list_ports".
    # Senza questo stub, su una macchina senza pyserial il visualizzatore
    # muore subito con "No module named 'serial.tools'".
    # I sottomoduli vanno registrati uno per uno: avere 'serial' in
    # sys.modules non basta a far passare "import serial.tools.list_ports".
    serial_mod = types.ModuleType('serial')
    serial_mod.Serial = _FakeArduinoSerial
    serial_mod.SerialException = _FakeSerialException

    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = _sim_comports

    tools = types.ModuleType('serial.tools')
    tools.list_ports = list_ports
    serial_mod.tools = tools

    sys.modules['serial'] = serial_mod
    sys.modules['serial.tools'] = tools
    sys.modules['serial.tools.list_ports'] = list_ports

    # ---- picamera2 (camera del Raspberry Pi) ----
    # capture_file scrive un JPG generato al volo: cosi' la tab Camera mostra
    # davvero un'immagine invece del riquadro "nessuna foto".
    class _Picamera2:
        sensor_resolution = (640, 480)

        def create_still_configuration(self, **k): return dict(k)
        def configure(self, *a, **k): pass
        def start(self, *a, **k): pass
        def stop(self, *a, **k): pass
        def start_preview(self, *a, **k):
            print("[SIM] Anteprima camera aperta (nessuna finestra reale)")
        def stop_preview(self, *a, **k):
            print("[SIM] Anteprima camera chiusa")
        def close(self, *a, **k): pass

        def capture_file(self, path):
            _write_sim_photo(path)

    picamera2 = types.ModuleType('picamera2')
    picamera2.Picamera2 = _Picamera2
    picamera2.Preview = types.SimpleNamespace(QTGL='QTGL', QT='QT', NULL='NULL')
    sys.modules['picamera2'] = picamera2


def _write_sim_photo(path):
    """
    Scrive un JPG finto (fondo verde con la data) al posto dello scatto reale.

    Serve solo alla simulazione: senza un file vero la tab Camera non avrebbe
    nulla da mostrare. Se Pillow manca, non scrive nulla e la tab mostrera' il
    suo messaggio di fallback.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new('RGB', (640, 480), (46, 125, 50))
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "FnP AeroGreenHouse - foto simulata", fill=(255, 255, 255))
    draw.text((20, 40), datetime.now().strftime("%d/%m/%Y %H:%M:%S"), fill=(200, 230, 201))
    img.save(path)


_install_hardware_stubs()


# ---------------------------------------------------------------------------
# 2) Patch di percorsi e comportamenti per la simulazione
# ---------------------------------------------------------------------------
import shutil

import yaml
import helper_aeroGreenHouse as H
import ir_controller.ir_controller as ir_controller
from managers_classes import plant_growth as PG
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
    def riga(f, t):
        # Stesso formato di AmbientManager._read_loop: unita' attaccate ai valori
        temp = round(random.uniform(22.0, 25.0), 2)
        hum = round(random.uniform(55.0, 65.0), 2)
        vpd = round(0.6108 * 2.718281828 ** (17.27 * temp / (temp + 273.3)) * (1 - hum / 100), 4)
        f.write("%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
                % (t.strftime('%Y/%m/%d %H:%M:%S'), temp, hum, vpd))

    day = datetime.now()
    path = os.path.join(TEST_DATA_DIR, day.strftime('TH_%Y_%m_%d.txt'))
    if not os.path.exists(path):   # gia' seminato (o scritto da una lettura simulata)
        with open(path, 'w') as f:
            for minuti in (30, 20, 10):
                riga(f, day - timedelta(minutes=minuti))

    # Giornata completa di ieri: e' il file che elabora DailyTHManager, senza il
    # quale i bottoni "Attiva Daily" della tab Ambiente non avrebbero nulla da
    # mostrare (statistiche e plot resterebbero vuoti).
    ieri = day - timedelta(days=1)
    path_ieri = os.path.join(TEST_DATA_DIR, ieri.strftime('TH_%Y_%m_%d.txt'))
    if not os.path.exists(path_ieri):
        with open(path_ieri, 'w') as f:
            for minuti in range(0, 24 * 60, 10):
                riga(f, ieri.replace(hour=0, minute=0, second=0) + timedelta(minutes=minuti))


def _seed_tank_data():
    """
    Semina i file TANK di oggi e di ieri.

    Quello di oggi popola il blocco H2O del Riepilogo gia' all'avvio: il livello
    e' l'unico dato che si perderebbe ad ogni riavvio del programma. Quello di
    ieri e' cio' che l'elaborazione giornaliera media, senza il quale
    «Daily → Adesso» non produrrebbe le statistiche del serbatoio.
    """
    def scrivi(path, giorno, minuti_indietro):
        if os.path.exists(path):
            return  # gia' seminato in un avvio precedente

        # Stesso formato di ultrasonic_measurement.save_data (header + righe)
        with open(path, 'w') as f:
            f.write("datetime\t\t\t dist_cm\t lvl_cm\t vol_L\t fill_%\n")
            for minuti in minuti_indietro:
                t = giorno - timedelta(minutes=minuti)
                dist = round(random.uniform(10.0, 14.0), 1)
                livello = round(30.0 - (dist - 2.0), 1)
                f.write(f"{t.strftime('%Y/%m/%d %H:%M:%S')}\t{dist:6.1f}\t{livello:6.1f}\t"
                        f"{livello * 900.0 / 1000.0:7.2f}\t{livello / 30.0 * 100:5.1f}\n")

    day = datetime.now()
    scrivi(os.path.join(TEST_DATA_DIR, day.strftime('TANK_%Y_%m_%d.txt')),
           day, (30, 20, 10))

    # Giornata di ieri: fine giornata a ritroso, un dato ogni ora
    ieri = day.replace(hour=23, minute=50, second=0) - timedelta(days=1)
    scrivi(os.path.join(TEST_DATA_DIR, ieri.strftime('TANK_%Y_%m_%d.txt')),
           ieri, range(0, 24 * 60, 60))


def _seed_water_data():
    """
    Semina i file WATER (pH ed EC) di oggi e di ieri.

    pH ed EC sono due job distinti, con intervalli propri: ogni riga porta il
    valore di UNO dei due e '--' nelle colonne dell'altro, esattamente come
    scrive water_manager.save_water_data. Serve a far partire popolate la
    pagina H2O e il Riepilogo, e a dare all'elaborazione giornaliera qualcosa
    da mediare.
    """
    def riga_ph(f, t):
        f.write(f"{t.strftime('%Y/%m/%d %H:%M:%S')}\t {random.uniform(5.8, 6.6):.2f}\t "
                f"--\t --\t --\n")

    def riga_ec(f, t):
        ec = random.uniform(1100.0, 1500.0)
        f.write(f"{t.strftime('%Y/%m/%d %H:%M:%S')}\t --\t {ec:.2f}\t "
                f"{ec / 2:.2f}\t {random.uniform(0.55, 0.70):.2f}\n")

    def scrivi(path, giorno, minuti_indietro):
        if os.path.exists(path):
            return  # gia' seminato (o scritto da una lettura simulata)

        with open(path, 'w') as f:
            f.write("datetime\t\t\t ph\t ec_uScm\t tds_ppm\t sal_psu\n")
            for i, minuti in enumerate(minuti_indietro):
                t = giorno - timedelta(minutes=minuti)
                # I due job si alternano: e' l'aspetto che ha il file quando
                # pH ed EC girano con lo stesso intervallo ma sfasati.
                (riga_ph if i % 2 == 0 else riga_ec)(f, t)

    day = datetime.now()
    scrivi(os.path.join(WATER_DIR, day.strftime('WATER_%Y_%m_%d.txt')),
           day, (30, 25, 20, 15, 10, 5))

    ieri = day.replace(hour=23, minute=50, second=0) - timedelta(days=1)
    scrivi(os.path.join(WATER_DIR, ieri.strftime('WATER_%Y_%m_%d.txt')),
           ieri, range(0, 24 * 60, 30))


def _seed_error_data():
    """
    Semina due errori di lettura di oggi.

    Senza, la nuova sezione "Errori di lettura" della schermata Log partirebbe
    vuota e non si capirebbe che aspetto ha. Da qui in poi si riempie da sola:
    la porta seriale finta fa fallire una lettura su otto circa.

    Formato quello di error_log.ErrorRecorder._append_to_file.
    """
    path = os.path.join(ERRORS_DIR, datetime.now().strftime('ERRORS_%Y_%m_%d.txt'))
    if os.path.exists(path):
        return

    esempi = [
        (45, 'pH', "Non è stato possibile leggere il sensore di pH, controlla il "
                   "motivo: lettura non attendibile, controlla il collegamento "
                   "della sonda alla scheda 'BoardSim'."),
        (20, 'US_water', "Non è stato possibile leggere il sensore ultrasonico del "
                         "serbatoio, controlla il motivo: distanza 412.0cm fuori dal "
                         "range operativo (2-400cm). Misura ignorata."),
    ]

    with open(path, 'w') as f:
        f.write("datetime\tsource\tmessage\n")
        for minuti, sorgente, messaggio in esempi:
            t = datetime.now() - timedelta(minutes=minuti)
            f.write(f"{t.strftime('%Y/%m/%d %H:%M:%S')}\t{sorgente}\t{messaggio}\n")


_seed_spectro_data()
_seed_growth_data()
_seed_th_data()
_seed_tank_data()
_seed_water_data()
_seed_error_data()
_redirect_calibration()


def _sim_config(file_name):
    """
    Carica il config reale ma reindirizza percorsi e accorcia gli intervalli.

    La usano DUE patch: quello su aeroHelper (la configurazione dei manager) e
    quello su gui.AeroGreenHouseGUI (la configurazione mostrata dal pannello).
    La GUI tiene infatti un self.config tutto suo, letto direttamente dal file:
    senza il secondo patch il pannello mostrerebbe la porta /dev/ttyACM0 e le
    directory di produzione, mentre i manager leggono dalla porta simulata.
    """
    with open(file_name, 'r') as f:
        cfg = yaml.safe_load(f)

    sep = os.sep
    cfg.setdefault('log', {})['directory'] = TEST_DATA_DIR
    cfg.setdefault('dht22', {})['saving_dir'] = TEST_DATA_DIR + sep
    cfg.setdefault('tank', {})['saving_dir'] = TEST_DATA_DIR + sep
    cfg.setdefault('spectro', {})['saving_dir'] = SPECTRO_DIR
    cfg.setdefault('plant_growth', {})['saving_dir'] = GROWTH_DIR
    cfg.setdefault('camera', {})['saving_dir'] = IMG_DIR
    cfg.setdefault('water', {})['saving_dir'] = WATER_DIR
    cfg.setdefault('error_log', {})['saving_dir'] = ERRORS_DIR
    cfg.setdefault('Daily_Data', {})['th_data_dir'] = TEST_DATA_DIR + sep
    cfg['Daily_Data']['plot_output_dir'] = PLOT_DIR
    cfg['Daily_Data']['water_data_dir'] = WATER_DIR
    cfg['Daily_Data']['tank_data_dir'] = TEST_DATA_DIR + sep
    cfg['Daily_Data']['growth_data_dir'] = GROWTH_DIR

    # Un'unica scheda finta con tutte e quattro le sonde. La sezione viene
    # riscritta per intero, e non solo corretta nella porta: cosi' la
    # simulazione non dipende da come e' configurato l'Arduino vero.
    # reset_delay a 0 perche' non c'e' nessuna scheda da aspettare al reset.
    cfg['arduino'] = {
        'baudrate': 9600,
        'timeout': 2,
        'reset_delay': 0,
        'boards': [{
            'name': 'BoardSim',
            'port': SIM_PORT,
            'enabled': True,
            'sensors': {
                'pH': {'pin': 'A0'},
                'EC': {'address': 100},
                'US_water': {'trig': SIM_TRIG_WATER, 'echo': 3},
                'US_plant': {'trig': SIM_TRIG_PLANT, 'echo': 5},
            },
        }],
    }

    # Intervalli brevi per vedere subito gli aggiornamenti durante l'ispezione
    cfg['dht22']['read_interval'] = 3
    cfg['tank']['read_interval'] = 3
    # Con la porta finta le letture sono istantanee: ripeterle non costa nulla
    # e cosi' una singola risposta ERR non fa perdere l'intera misura (gli
    # errori restano comunque visibili su pH ed EC, che leggono una volta sola).
    cfg['tank']['n_samples'] = 3
    cfg['spectro']['read_interval'] = 3
    cfg['water']['ph_read_interval'] = 3
    cfg['water']['ec_read_interval'] = 3
    cfg['plant_growth']['n_samples'] = 3
    # 3 secondi espressi in giorni: in produzione la misura e' ogni giorno, ma in
    # simulazione l'attesa terrebbe la tab Crescita immobile per 24 ore.
    cfg['plant_growth']['read_interval_days'] = 3 / 86400
    # 5 secondi espressi in ore: in produzione lo scatto e' ogni 2 ore, ma in
    # simulazione l'attesa terrebbe la tab Camera immobile.
    cfg['camera']['separation_hours'] = 5 / 3600
    return cfg


def _patched_load_config(self, file_name):
    """Metodo di aeroHelper: delega alla configurazione simulata condivisa."""
    return _sim_config(file_name)


H.aeroHelper.load_config = _patched_load_config

# Nessun upload web reale
H.AmbientManager.upload_data_on_web = lambda self, *a, **k: None

# Nessun comando IR reale (niente chiamata a `piir`): solo log
def _sim_send_command(self, command):
    self.logger.info(f"[SIM] IR send '{command}' (no hardware)")
    return 0


ir_controller.IRController.send_command = _sim_send_command


# NB: serbatoio e crescita non hanno bisogno di patch. I loro sensori sono
# ormai letti dall'Arduino, quindi le misure arrivano gia' simulate dalla porta
# seriale finta; di ultrasonic_measurement i manager usano solo la conversione
# distanza->volume e il salvataggio su file, che funzionano ovunque.


def _patch_gui(gui):
    """
    Adatta la GUI alla simulazione. Va chiamata dopo `import gui`.

    Due sole modifiche, entrambe per non far uscire il visualizzatore dai
    propri confini.
    """
    # 1) La GUI legge il config per conto suo (self.config), separato da quello
    #    dei manager: senza questo, il pannello di configurazione mostrerebbe
    #    la porta seriale vera e le directory di produzione.
    gui.AeroGreenHouseGUI.load_config = lambda self: _sim_config(self.config_file)

    # 2) In simulazione il salvataggio e' disattivato del tutto. Si sostituisce
    #    save_config_changes e non il solo save_config perche' quel metodo, dopo
    #    aver scritto il file, riversa le sezioni in self.ah.configs e chiama
    #    arduino.reload(): rimpiazzerebbe la porta finta con quella del config
    #    reale, e da li' in poi nessuna lettura funzionerebbe piu'.
    def _sim_save_config_changes(self):
        gui.messagebox.showinfo(
            "Simulazione",
            "Salvataggio disattivato: questo e' solo un visualizzatore di gui.py.\n"
            "Nessun file di configurazione viene modificato.")

    gui.AeroGreenHouseGUI.save_config_changes = _sim_save_config_changes


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

    _patch_gui(gui)

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
    print(f"Arduino simulato sulla porta {SIM_PORT}: 'Rileva schede' nella "
          "schermata Configurazione lo trova. Salvataggio disattivato.")
    root.mainloop()


if __name__ == '__main__':
    main()
