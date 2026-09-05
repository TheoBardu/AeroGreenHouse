# AeroGreenHouse — Technical Documentation

> [🇮🇹 Italiano](DOCUMENTATION.md) · 🇬🇧 English · User manual: [IT](User_Manual.md) · [EN](User_Manual_EN.md) · CLI: [DUCUMENTATION_CLI.md](DUCUMENTATION_CLI.md)

Reference document on how the code works, organised **top-down**: from the entry points
(what the user starts), through the coordinator and the category managers, down to the physics
of the sensors and the formulas implemented.

The system runs on a **Raspberry Pi** and manages an aeroponic/hydroponic greenhouse: it
drives the pumps over GPIO, reads temperature/humidity, controls the air conditioner over
infrared, monitors the tank level and plant height with two ultrasonic sensors, measures the
pH and electrical conductivity of the water with two Atlas Scientific probes, computes the
MCARI2 vegetation index with a spectrometer and publishes the data online.

**Not all probes are on the Raspberry.** The two ultrasonic sensors and the two water probes
are connected to an **Arduino UNO**, queried by the Raspberry over USB serial with a text
protocol. That is the subject of chapter §5, the most detailed in this document.

> **A note on language.** Command names, configuration keys, file names and code identifiers
> are **never translated**: they are what you actually type and what actually appears on the
> wire. Only the prose is in English.

---

## Contents

1. [General architecture](#1-general-architecture)
2. [Entry points](#2-entry-points)
3. [The coordinator: `aeroHelper`](#3-the-coordinator-aerohelper)
4. [Configuration: `config.yaml`](#4-configuration-configyaml)
5. [**The Raspberry ↔ Arduino bridge**](#5-the-raspberry--arduino-bridge)
6. [JobsManager — pumps and GPIO](#6-jobsmanager--pumps-and-gpio)
7. [AmbientManager — DHT22 and VPD](#7-ambientmanager--dht22-and-vpd)
8. [ClimateManager and IRController — air conditioner](#8-climatemanager-and-ircontroller--air-conditioner)
9. [TankManager — tank level (HC-SR04)](#9-tankmanager--tank-level-hc-sr04)
10. [WaterManager — pH and electrical conductivity](#10-watermanager--ph-and-electrical-conductivity)
11. [ErrorRecorder — reading-error register](#11-errorrecorder--reading-error-register)
12. [PlantGrowthManager — plant height (HC-SR04)](#12-plantgrowthmanager--plant-height-hc-sr04)
13. [AS7265x spectrometer — MCARI2 index](#13-as7265x-spectrometer--mcari2-index)
14. [Camera](#14-camera)
15. [Data persistence: file formats](#15-data-persistence-file-formats)
16. [Daily processing and upload](#16-daily-processing-and-upload)
17. [Logging](#17-logging)
18. [Concurrency model (threads)](#18-concurrency-model-threads)
19. [Formula summary](#19-formula-summary)
20. [Anomalies found in the code](#20-anomalies-found-in-the-code)

---

## 1. General architecture

The code is organised in layers. Each layer only knows the one below it:

```
         USER
           |
   +-------+--------+
   |                |
 gui.py          main.py            <- Layer 1: entry points
 (window)        (text shell)
   |                |
   +-------+--------+
           |
      aeroHelper                    <- Layer 2: coordinator
           |                           (config, log, GPIO, shared services)
   +-------+------------------+
   |                          |
 ErrorRecorder            ArduinoHub  <- Layer 2b: shared services
 (error register)   (the only serial port)
           |
   +-------+-------+-------+-------+-------+--------+---------+--------+
   |       |       |       |       |       |        |         |        |
 Jobs   Ambient Climate  Tank   Water  Spectro  PlantGrowth Camera  DailyTH   <- Layer 3:
Manager Manager Manager Manager Manager Manager   Manager   Manager Manager      managers
   |       |       |       |       |       |        |
 GPIO    DHT22   IR/piir  |       |    AS7265x      |
 pumps                    |       |    (I2C on Pi)  |
                          +-------+-----------------+
                                  |
                          ARDUINO UNO (USB)         <- Layer 4: probe front-end
                          HC-SR04 x2 · pH · EC
   |       |       |              |        |
   +-------+-------+--------------+--------+
           |
  daily .txt files  +  cumulative GROWTH.csv  +  ERRORS_*.txt
           |
   daily_th_processor.py -> uploader.py -> GitHub -> website
```

The guiding principle is **separation between interface and logic**: `gui.py` contains widgets
and callbacks only, while all process logic (threads, scheduling, formulas, file I/O) lives in
the managers under `managers_classes/`. The GUI does not know *how* a pump is started: it
calls `self.ah.jobs.start_aeroponics()` and gets a boolean back.

The same principle applies one level down, and it is the most important architectural change:
**no manager knows that a serial port exists**. `TankManager` asks for
`arduino.read_float('US_water')` and receives a number; that behind it there is an Arduino
UNO, a USB cable and the string `read_us,2,3` is a detail confined to `arduino_link.py` (§5).

### What reads what, and from where

| Quantity | Sensor | Connected to | Read through |
|---|---|---|---|
| Temperature, humidity, VPD | DHT22 | Raspberry GPIO | `AmbientManager` |
| Aeroponic / hydroponic pumps | relays | Raspberry GPIO | `JobsManager` |
| Air conditioner | IR LED | Raspberry GPIO | `ClimateManager` + `piir` |
| MCARI2 index | AS7265x | Raspberry I2C bus | `SpectroManager` |
| Photos | Picamera2 | Raspberry CSI | `CameraManager` |
| **Tank level** | **HC-SR04** | **Arduino UNO** | **`ArduinoHub` → `US_water`** |
| **Plant height** | **HC-SR04** | **Arduino UNO** | **`ArduinoHub` → `US_plant`** |
| **Water pH** | **Atlas Surveyor V3.0** | **Arduino UNO** | **`ArduinoHub` → `pH`** |
| **Conductivity (EC/TDS/salinity)** | **Atlas EZO-EC (I2C)** | **Arduino UNO** | **`ArduinoHub` → `EC`** |

### File map

| File | Role |
|---|---|
| `main.py` | Interactive **text shell** (see `DUCUMENTATION_CLI.md`) |
| `gui.py` | Tkinter control panel (11 screens, icon side bar) |
| `helper_aeroGreenHouse.py` | **Heart of the system**: `aeroHelper`, which instantiates the shared services and the 9 managers |
| `managers_classes/` | The category managers, one per file |
| `managers_classes/arduino_link.py` | **Serial bridge to the Arduino boards** (§5) |
| `managers_classes/error_log.py` | `ErrorRecorder`: register of probe reading errors (§11) |
| `managers_classes/water_manager.py` | `WaterManager`: pH and EC as two independent jobs (§10) |
| `managers_classes/tank_manager.py` | `TankManager`: tank level |
| `managers_classes/plant_growth.py` | Plant height measurement + `GROWTH.csv` I/O |
| `managers_classes/data_config.py` | Rounding of measurement data (decimals / significant digits) |
| `config.yaml` | Single source of truth for ports, pins, timings and thresholds |
| `arduino_modules/fish_n_plant_reading_module_atlas/*.ino` | **General-purpose Arduino sketch** (pH, EC, ultrasound) |
| `arduino_modules/fish_n_plant_reading_module/*.ino` | Earlier sketch, ultrasound only (historical) |
| `arduino_modules/serial_command_arduino.py` | Serial-link test script (§5.10) |
| `ir_controller/ir_controller.py` | Sends IR commands to the air conditioner |
| `ir_controller/ac_remote.json` | Remote-control command encoding (for `piir`) |
| `sensors/ultrasonic_sensor/ultrasonic_measurement.py` | Volume maths + file saving (the measurement no longer goes through here) |
| `sensors/spectrometer/mcari2_as7265x.py` | Spectral acquisition and MCARI2 computation |
| `managers_classes/camera_manager.py` | `CameraManager`: periodic acquisition and live preview |
| `camera/takePicture.py` | CLI wrapper: periodic acquisition |
| `camera/camera.py` | CLI wrapper: live preview |
| `managers_classes/daily_th_processor.py` | `DailyTHManager`: daily statistics and chart |
| `uploader/uploader.py` | Pushes JSON/images to GitHub |

---

## 2. Entry points

There are **two ways** of starting the system, mutually alternative.

### 2.1 `main.py` — text shell

`main.py` is **no longer** the headless scheduler of the early versions: today it is an
**interactive shell** exposing the same functions as the GUI from a terminal, so the
greenhouse can be driven over SSH without a display.

```bash
python3 main.py
FnP> -measure ph now
FnP> -measure water start
FnP> -arduino test US_water
FnP> -errors
```

It instantiates a single `aeroHelper` and waits for commands; the jobs it starts run in daemon
threads **of the same process**, so they keep running as long as the shell stays open —
exactly as they do while the GUI window is open.

The available commands are `-job`, `-measure` (`th`, `water`, `ph`, `ec`, `growth`),
`-arduino`, `-errors`, `-camera`, `-daily`, `-details`, `-save`, `help`, `exit`.
They are documented one by one, with examples, in
**[`DUCUMENTATION_CLI.md`](DUCUMENTATION_CLI.md)**: they are not repeated here.

Like `gui.py`, `main.py` contains **only command parsing and printing**: no process logic.
Threads, scheduling, formulas and file I/O all stay in the managers.

### 2.2 `gui.py` — control panel

It instantiates `aeroHelper` once (`self.ah = aeroHelper()`) and builds a window with an
**icon side bar** and **11 screens**:

| Icon | Screen | Content |
|---|---|---|
| ▦ | **Summary** | Latest value of each sensor with its date, arc indicators, list of running processes only (§2.3) |
| ⚙ | **Configuration** | Editing of `config.yaml` parameters, including the **"Arduino boards"** card (§5.9) |
| ◉ | **Processes** | Green/red indicators, refreshed every second |
| ⚡ | **Jobs** | Treeview of jobs; create/edit/delete/activate/deactivate |
| 🌡 | **Environment** | T/H/VPD readings, start/stop of periodic reading; below, the daily processing (§16.1) |
| ❄ | **Climate** | Start/stop of automatic AC control, last IR command |
| 💧 | **H2O** | Tank level (§9), **pH and EC** (§10) |
| ◐ | **Spectrum** | MCARI2 index, plant-state indicator, calibration, history |
| 🌱 | **Growth** | Plant height and date of last measurement, trend chart, table, calibration (§12.6) |
| 📷 | **Camera** | Periodic acquisition, live preview, last photo with date and time (§14) |
| ☰ | **Log** | Colour-coded live log console + **"Reading errors"** section (§11) |

#### No more `Notebook`: a tuple of screens

Horizontal tabs have been replaced by an **icon side bar**. The list of `notebook.add()` calls
has become a **declarative tuple**, `SCREENS` (gui.py:359), where each row is
`(key, icon, menu entry, title, subtitle, constructor name)`:

```python
SCREENS = (
    ('riepilogo', '▦', 'Riepilogo', 'Riepilogo',
     'Ultimo valore di ogni sensore e processi in esecuzione.',
     'create_riepilogo_tab'),
    ...
)
```

`create_widgets()` walks it once, builds every screen stacked in the same cell of a `grid` and
keeps them **all alive**: switching pages is a `tkraise()`, not a rebuild. Adding a screen
means adding a row to the tuple and a `create_*_tab` method, without touching window
construction.

The methods are still called `create_*_tab` for continuity with the tabbed version: the name
survived, the container did not.

#### The visual building blocks

The interface no longer uses `ttk.LabelFrame`. Three helpers build everything:

- `_card(parent, titolo, icona, ...)` — light panel with a thin border and a small-caps title:
  it is the composition unit of every screen;
- `_chip(parent, testo, fg, bg)` — status pill (Tk does not round a `Label`: it is a rectangle
  with generous padding, which at this size still reads as a badge);
- the **arcs** drawn with `create_arc` on a `tk.Canvas` for values with a natural full scale
  (§2.3).

The GUI uses three periodic mechanisms based on `root.after()` (hence on the Tk thread,
without blocking the interface):

- `process_log_queue()` — every **100 ms**, drains the log queue and writes to the console;
  every 20 rounds (**2 s**) it also refreshes the "Reading errors" section, so an error
  appears on its own without changing screen;
- `refresh_status_tab()` — every **1 s**, queries `get_process_states()` and colours the
  indicators;
- `_update_clock()` — every **1 s**, updates the clock in the header.

#### The log → GUI bridge

`GUILoggingHandler` is a custom `logging.Handler` which, instead of writing to a file, puts
the formatted record into a `queue.Queue`:

```python
def emit(self, record):
    msg = self.format(record)
    self.log_queue.put((msg, record.levelname))
```

This is the key point of thread-safe decoupling: the manager threads call `logger.info(...)`
without touching Tkinter (which is not thread-safe); the GUI thread pulls from the queue with
`get_nowait()` and updates the widget. The record level (`ERROR`, `WARNING`, `DEBUG`, other)
selects the text colour tag.

#### Reading process state

`get_process_states()` builds the list of indicators by querying the managers' flags directly:
the GPIO jobs from `gpio_pins` (skipping `what_type: sensor` entries, which are not processes)
and then, one by one, the category managers:

```python
states.append(("Lettura Ambient (T/H)",     self.ah.ambient.is_running()))
states.append(("Controllo Climatizzatore",  self.ah.climate.is_running()))
states.append(("Lettura Serbatoio",         self.ah.tank.is_running()))
states.append(("Lettura pH",                self.ah.water.is_ph_running()))
states.append(("Lettura EC",                self.ah.water.is_ec_running()))
states.append(("Lettura Spettrometro",      self.ah.spectro.is_running()))
states.append(("Misura Crescita",           self.ah.plant_growth.is_running()))
states.append(("Acquisizione Camera",       self.ah.camera.is_acquiring()))
```

**pH and EC appear as two distinct entries** because they are two separate jobs (§10): they
start, stop and fail independently.

### 2.3 The Summary screen

It is the **first** screen: it answers "how is the greenhouse doing?" without visiting the
other ten. A grid of 3 columns × 4 rows:

```
┌───────────────────────────────────────────────┐
│  Environment: temperature · humidity · VPD    │  (3 arcs, a single DHT22 reading)
├───────────────────────────┬───────────────────┤
│  H2O:  pH · conductivity  │       Tank        │
│  (2 arcs, 2 dates)        │     fill arc      │
├───────────────────────────┼───────────────────┤
│      MCARI2 index         │      Growth       │
│       arc 0-1             │      height       │
├───────────────────────────┴───────────────────┤
│  Active Processes (running ones only)         │
└───────────────────────────────────────────────┘
```

Every panel shows the **date of the measurement**: a value without a date does not tell you
whether it is a minute or three days old, and with intervals ranging from 5 minutes
(environment) to a day (growth) the difference matters. The H2O panel has **two distinct
dates**, one per column (`data_per_colonna=True`): pH and EC are two separate jobs with their
own intervals, and showing a single date would suggest the other probe had been read at the
same instant.

**Where the values come from.** Only from the managers, never from readings taken by the GUI:
`last_result` for environment (§7.4) and tank (§9.6), `last_ph` / `last_ec` for water (§10),
`history[0]` for the spectrometer (most recent first) and `history[-1]` for growth
(chronologically ascending — the two lists have opposite orderings, beware). Since all of them
re-read the last datum from file at startup, **the screen is populated at first opening**,
before any reading is started and without querying the Arduino.

**Arc or number.** The arc (`create_arc` on `tk.Canvas`, as for the growth chart in §12.8: no
matplotlib) is used where a **reference full scale** exists: humidity 0-100 %, fill 0-100 %,
MCARI2 0-1, and for pH and EC the scale built around the configured thresholds
(`ph_min`/`ph_max`, `ec_min`/`ec_max`), with **coloured bands** marking the desired interval.
Plant height has no obvious physical full scale and stays a number. The tank colours the arc
by band (red below 25 %, orange below 50 %), MCARI2 reuses `MCARI2_COLORS`.

**Cost.** Same discipline as §2.2, and for the same reason: widgets are built once, then the
1 s tick touches values only. Arcs are redrawn **only if the value changed** (`_riep_cache`
cache, compared in `_cambiato()`) and the process list only if it changes
(`_riep_active_keys`), so with a idle greenhouse a tick draws nothing.

---

## 3. The coordinator: `aeroHelper`

`aeroHelper.__init__()` performs, in order:

1. **Loads the configuration** — `load_config('config.yaml')` with `yaml.safe_load`.
2. **Sets up logging** — `logging.basicConfig` with two handlers: file
   (`<log.directory>/<log.filename>`) and console.
3. **Initialises the GPIO** — `initialize_gpio(configs)`, once for the whole process.
4. **Creates the two shared services** — and creates them **before** the managers, because the
   managers with probes on the Arduino receive them in their constructor:

```python
self.errors  = ErrorRecorder(self.configs, self.logger)   # §11
self.arduino = ArduinoHub(self.configs, self.logger)      # §5
```

5. **Instantiates the nine managers**, passing each `configs`, `logger` and whatever it needs:

```python
self.jobs         = JobsManager(self.configs, self.logger, self.gpios)
self.ambient      = AmbientManager(self.configs, self.logger)
self.climate      = ClimateManager(self.configs, self.logger, self.ambient)
self.tank         = TankManager(self.configs, self.logger, self.arduino, self.errors)
self.water        = WaterManager(self.configs, self.logger, self.arduino, self.errors)
self.spectro      = SpectroManager(self.configs, self.logger)
self.plant_growth = PlantGrowthManager(self.configs, self.logger, self.arduino, self.errors)
self.camera       = CameraManager(self.configs, self.logger)
self.daily_th     = DailyTHManager(self.configs, self.logger, self.errors)
```

The structure of the system can be read off the constructor signatures: whoever receives
`self.gpios` talks to the Raspberry's pins, whoever receives `self.arduino` talks to an
external board, whoever receives `self.errors` can fail in a way the user must see.
`ClimateManager` instead receives the `AmbientManager` instance: that is how air-conditioner
control reads the latest T/H measurements without duplicating access to the sensor.

6. **Wires up the aggregate upload** — `self.ambient.extra_data_provider = self.latest_extra_data`
   (§16.2).
7. **Backward-compatibility aliases** — `self.runner`, `self.pump_aerophonics`,
   `self.pump_idrophonics` point to the `jobs` methods, for code written before the split into
   managers.

### `latest_extra_data()` — a single snapshot of the greenhouse

The periodic upload starts from `AmbientManager` because it has the tightest cadence. So that
the website receives **a coherent state** rather than a separate upload per probe, `aeroHelper`
gives it a function collecting the latest known values of every other quantity:

```python
dati['water_level_cm'], dati['volume_L'], dati['fill_percent']  # from tank.last_result
dati['ph']                                                       # from water.last_ph
dati['ec_us_cm'], dati['tds_ppm'], dati['salinity_psu']          # from water.last_ec
dati['h_plant_cm']                                               # from plant_growth.history[-1]
dati['errors'] = self.errors.recent(10)                          # §11
```

**Every entry is optional**: a probe never read — or not yet installed — simply does not
appear, and the uploader omits it from the JSON instead of publishing a zero that the site
would display as a real measurement.

### GPIO initialisation

```python
self.gpios.setmode(GPIO.BCM)      # BCM numbering, not physical
self.gpios.setwarnings(False)
for g in config["gpio_pins"]:
    if g["what_type"] == "sensor":
        self.gpios.setup(g["pin"], self.gpios.IN)   # sensors -> input
        continue
    self.gpios.setup(g["pin"], self.gpios.OUT)
    self.gpios.output(g["pin"], True)               # <- pin HIGH = relay OFF
```

**Active-low logic.** The relay board used is active low: `output(pin, False)` **switches on**
the load, `output(pin, True)` **switches it off**. That is why initialisation drives all pins
to `True` — i.e. switches them off — preventing the pumps from starting at boot.
This convention, the inverse of intuition, is the same throughout the code.

Finally the infrared TX pin (`ir_control.tx_pin`) is configured as an output.

Note: no GPIO pin is reserved for the HC-SR04 sensors any more. Both ultrasonic sensors are on
the Arduino (§5), so their pins do not appear in `initialize_gpio`.

### Shutdown

`cleanup_gpios()` closes **the serial ports too**, not just the pins:

```python
def cleanup_gpios(self):
    self.arduino.close_all()
    self.gpios.cleanup()
```

Leaving a serial port open would prevent the next process from reopening it, and it is a bug
that only shows up on the second start — that is, at the worst possible moment.

---

## 4. Configuration: `config.yaml`

All operational parameters live in a single file, read at startup.

```yaml
T_var:                  # optimal reference temperature/humidity
  Topt: 18.0
  Hopt: 65.0
dht22:
  pin: 27               # data pin of the T/H sensor (Raspberry GPIO)
  read_interval: 300    # [s] interval between readings
  save: true
  saving_dir: /home/fishnplants/Desktop/data/TH/
  max_retries: 5        # attempts before declaring a reading failed
log:
  directory: /home/fishnplants/Desktop/
  filename: FnP_AeroGreenHouse
  level: INFO
config_reload_interval: 4
gpio_pins:
- name: AEROPONICS
  pin: 19
  what_type: pump
  interval: 1200        # [min] wait between two irrigations
  on_time: 5            # [s]   irrigation duration
- name: IDROPONICS
  pin: 12
  what_type: pump
  interval: 29          # [min]
  on_time: 65           # [s] MAXIMUM pumping time
- name: MOISTURE
  pin: 26
  what_type: sensor     # -> configured as INPUT, not a process
spectro:
  read_interval: 3600   # [s]
  saving_dir: /home/fishnplants/Desktop/data/SPECTRO/
  history_len: 10
plant_growth:
  read_interval_days: 1      # [days] how often to measure the height
  n_samples: 3               # readings to average
  reference_height_cm: 70.0  # sensor -> root chamber distance with no plant
  decimals: 1                # digits to keep from the measurement
  save: true
  saving_dir: /home/fishnplants/Desktop/data/GROWTH/
  history_len: 30            # points shown in chart and table
camera:
  separation_hours: 2   # [hours] time between shots
  saving_dir: /home/fishnplants/Desktop/data/IMG/
Daily_Data:
  th_data_dir:     /home/fishnplants/Desktop/data/TH/
  water_data_dir:  /home/fishnplants/Desktop/data/WATER/
  tank_data_dir:   /home/fishnplants/Desktop/data/TANK/
  growth_data_dir: /home/fishnplants/Desktop/data/GROWTH/
  plot_output_dir: /home/fishnplants/Desktop/data/PLOT/
ir_control:
  rx_pin: 20
  tx_pin: 21
  file_ac_name: .../ac_remote.json
  default_temp: 22
  enabled: true
  time_max_on: 10.0     # [min] maximum continuous AC on-time
  control_time: 5.0     # [min] evaluation cycle period
  T_max: 26.0           # [°C] temperature intervention threshold
  H_max: 65.5           # [%]  humidity intervention threshold

# --- Arduino boards connected over USB (§5) -------------------------------
arduino:
  baudrate: 9600        # must match the sketch's Serial.begin()
  timeout: 15           # [s] maximum wait for a response
  reset_delay: 2        # [s] pause after opening the port (the UNO resets)
  boards:
  - name: Board1        # descriptive only, appears in logs and in the GUI
    port: /dev/ttyACM0  # serial port
    enabled: true       # false = board ignored, without deleting it from the file
    sensors:            # WHICH probes are present and ON WHICH PINS
      pH:       {pin: A0}
      EC:       {address: 100}
      US_water: {trig: 2, echo: 3}
      US_plant: {trig: 4, echo: 5}

water:                  # §10
  ph_read_interval: 1800   # [s]
  ec_read_interval: 1800   # [s]
  ph_min: 5.5              # alarm thresholds (not validity limits)
  ph_max: 6.5
  ec_min: 800              # [µS/cm]
  ec_max: 2000
  decimals: 2
  save: true
  saving_dir: /home/fishnplants/Desktop/data/WATER/
  history_len: 30

tank:                   # §9
  tank_height_cm: 30.0
  sensor_offset_cm: 2.0
  tank_area_cm2: 900.0
  water_low_threshold_l: 3.0   # [L] reserve threshold
  read_interval: 900           # [s]
  n_samples: 5                 # readings to take the median of
  saving_dir: /home/fishnplants/Desktop/data/TANK/

error_log:              # §11
  saving_dir: /home/fishnplants/Desktop/data/ERRORS/
  history_len: 200      # errors kept in memory for the GUI
```

**Beware of the units**, which are not uniform and are a source of confusion:
`interval` (jobs) is in **minutes**, `on_time` in **seconds**, `dht22.read_interval`,
`water.*_read_interval`, `tank.read_interval` and `spectro.read_interval` in **seconds**,
`ir_control.control_time` and `time_max_on` in **minutes**,
`plant_growth.read_interval_days` in **days** and `camera.separation_hours` in **hours** —
four different time units in the same file. The more recently added fields carry the unit in
their name (`_days`, `_hours`) precisely for this reason; the older ones do not.

The `what_type` field discriminates behaviour: `pump` → output pin and startable job;
`sensor` → input pin, excluded from the process list.

**Alarm thresholds ≠ validity ranges.** `ph_min`/`ph_max` and `ec_min`/`ec_max` say when the
nutrient solution needs correcting: a measurement outside them is **valid and gets saved**,
with a warning. The physical validity ranges (pH 0–14, EC 0–200000 µS/cm, distance 2–400 cm)
are constants in the code, and a measurement outside those is **discarded**, because it means
the probe is disconnected or broken.

**The pins of the Arduino probes no longer live in their managers' sections**: neither `tank`
nor `plant_growth` has `trig_pin`/`echo_pin` any more. They all live in
`arduino.boards[].sensors`, because that is where they are needed — they are what the
Raspberry writes inside the serial command (§5.4). The GUI says so explicitly, with a note in
the tank and growth configuration cards.

---

## 5. The Raspberry ↔ Arduino bridge

Four probes out of eight are not connected to the Raspberry: they sit on an **Arduino UNO**,
joined to the Pi by **a single USB cable**, which carries both power and serial communication.
The Raspberry asks for a measurement by writing a line of text; the Arduino performs it and
answers with another line. That is all: no binary protocol, no third-party library between the
two, nothing you could not read with a serial terminal.

This chapter describes that dialogue **in full**: why it exists, who is in charge, which
commands exist, what the responses look like and what happens when something goes wrong.

The two sides of the bridge are:

| Side | File | Role |
|---|---|---|
| Raspberry | `managers_classes/arduino_link.py` | composes commands, sends them, interprets responses |
| Arduino | `arduino_modules/fish_n_plant_reading_module_atlas/fish_n_plant_reading_module_atlas.ino` | receives commands, performs measurements, answers |

### 5.1 Why an Arduino

Three reasons, all of them hardware.

1. **The Raspberry has no analogue-to-digital converter.** The Atlas Surveyor pH probe returns
   a **voltage**: without an ADC the Pi cannot read it. The Arduino UNO has six built-in
   channels (A0–A5).
2. **`pulseIn` needs real time.** An HC-SR04 measurement consists of timing a pulse a few
   hundred microseconds long. In Python on Linux, an operating-system context switch in the
   middle of the count falsifies the measurement; on an Arduino, which runs a single program
   with no operating system, `pulseIn()` is reliable to the microsecond.
3. **The Pi's pins are 3.3 V and the HC-SR04 ECHO output is 5 V.** On the Pi a voltage divider
   was needed for each sensor; on the Arduino, which natively works at 5 V, nothing is needed.

There is also a structural reason: the probes are **physically** near the water and the
plants, the Raspberry is not. A single USB cable to a box containing all the probes is simpler
— and more reliable — than eight long wires running back to the Pi.

### 5.2 Only one module opens the serial port

`arduino_link.py` is **the only file in the project that imports `pyserial`**. The managers do
not know about it and do not need to:

```python
distanza = self._arduino.read_float('US_water')   # TankManager
valori   = self._arduino.read_named('EC')         # WaterManager
```

The benefit is not cosmetic. It means that replacing the Arduino with another board — or going
back to reading a sensor directly from the Pi — touches **one file only**, and that the
managers remain testable by substituting the hub with a fake object.

### 5.3 Who decides when to measure: the Raspberry

**There is no timing whatsoever in the Arduino sketch.** No intervals, no timers, no
measurement cycle. `loop()` does exactly one thing: it accumulates the characters arriving on
the serial line until it meets an end-of-line, and then executes the command.

```cpp
void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      inputCommand.trim();
      if (inputCommand.length() > 0) processCommand(inputCommand);
      inputCommand = "";
    } else {
      inputCommand += c;
    }
  }
}
```

The loop **does not block** waiting for data: if nothing has arrived, it does nothing this time
round and checks again on the next.

All the timing policy stays on the Raspberry, in the manager threads
(`water.ph_read_interval`, `water.ec_read_interval`, `tank.read_interval`,
`plant_growth.read_interval_days`). The practical consequence matters: **changing how often a
measurement is taken does not require recompiling the Arduino**, only editing `config.yaml`.

The same applies to the **number of samples**: `tank.n_samples: 5` means the Raspberry sends
`read_us,2,3` five times and computes the median, not that the Arduino repeats the measurement
five times. The Arduino remains an elementary executor — one request, one measurement, one
response — and every statistical choice stays configurable from the Pi.

### 5.4 The pins travel inside the command

This is the most important design decision in the sketch. The pins are **not hard-wired in the
Arduino code**: they arrive inside the command, as comma-separated arguments.

```
read_us,2,3      ->  measures on the HC-SR04 wired to pins 2 (TRIG) and 3 (ECHO)
read_us,4,5      ->  measures on the HC-SR04 wired to pins 4 and 5
```

A **single command** `read_us` therefore serves *all* the ultrasonic sensors on the board:
what distinguishes the tank from the growth sensor is the pin pair, not the command. Adding a
third HC-SR04 requires no line of Arduino code, only an entry in `config.yaml`.

Operational consequence: **changing the wiring means editing `config.yaml` on the Raspberry,
not reprogramming the board.** Whoever assembles the rig does not need the Arduino IDE.

### 5.5 The protocol

#### Request format

```
<command_name>[,<arg1>[,<arg2>...]]\n
```

The name is separated from the arguments by the **first comma**; arguments from each other by
further commas. The line ends with `\n` (the sketch also accepts `\r`).

#### Response format

```
<full command>:<value>
```

That is, **the Arduino echoes back the whole command it received**, then a colon, then the
value.

```
read_pH,A0     ->  read_pH,A0:6.87
read_EC,100    ->  read_EC,100:1250.0,625.0,0.62
read_us,2,3    ->  read_us,2,3:12.40
```

Two rules make the format unambiguous:

- **the colon is reserved** for the command/value separator;
- **arguments use commas**, never colons.

That is why the Raspberry side can do `risposta.split(':')` and demand **exactly two parts**;
if it finds a different number, the response is malformed and gets discarded.

#### Why the echo

The echo is not decorative redundancy: it is the channel's **synchronisation check**.
Different probes are read by different threads; if for any reason the serial buffer got out of
step, the Pi would risk attributing the tank's distance to the growth sensor.

```python
if comando_ricevuto.lower() != command.lower():
    self._invalidate()          # throw the connection away
    raise ArduinoError(sensor_key, "Risposta fuori sincrono ...")
```

By comparing the echo with the command sent, a desynchronisation becomes an explicit error
instead of a wrong datum — which would be far worse, because nobody would notice. On detecting
the anomaly the connection is **invalidated**: the next attempt reopens the port and starts
again from a clean buffer.

#### Complete command table

| Command sent | Arguments | Example response | Values returned |
|---|---|---|---|
| `read_pH,<pin>` | analogue pin `A0`–`A5` (default `A0`) | `read_pH,A0:6.87` | pH, 2 decimals |
| `read_EC,<address>` | I2C address 1–127 (default 100) | `read_EC,100:1250.0,625.0,0.62` | EC [µS/cm], TDS [ppm], salinity [PSU] |
| `read_us,<trig>,<echo>` | two digital pins 2–13, different from each other | `read_us,2,3:12.40` | distance [cm], 2 decimals |
| `CAL,7` | — | `MID CALIBRATED` | calibrates the pH mid point (buffer 7) |
| `CAL,4` | — | `LOW CALIBRATED` | calibrates the low point (buffer 4) |
| `CAL,10` | — | `HIGH CALIBRATED` | calibrates the high point (buffer 10) |
| `CAL,CLEAR` | — | `CALIBRATION CLEARED` | clears the pH calibration |
| `ECCAL,dry` | — | EZO text response | dry point (probe dry) |
| `ECCAL,low,<value>` | e.g. `12880` | EZO text response | low point with the stated solution |
| `ECCAL,high,<value>` | e.g. `80000` | EZO text response | high point |
| `ECCAL,clear` | — | EZO text response | clears the EC calibration |
| `ECCMD,<EZO command>` | e.g. `ECCMD,K,1.0` | EZO text response | raw EZO command (passthrough) |

Calibration commands **do not follow** the `<command>:<value>` format: they return a textual
confirmation message. That is why `processCommand()` intercepts them before the general
dispatch, and why `arduino_link.py` does not use them — calibration is done from a serial
terminal or with `serial_command_arduino.py` (§5.10), not from the automatic jobs.

#### The three error responses

| Value | Meaning | Typical causes |
|---|---|---|
| `ERR` | unreliable reading | probe disconnected or in air; no echo within `US_TIMEOUT_US` (40 ms ≈ 6.8 m); pH voltage outside 150–3100 mV; EZO-EC not answering or answering with a status message instead of a number |
| `ERRPIN` | unusable pin or address | pin outside A0–A5 / D2–D13, TRIG equal to ECHO, I2C address outside 1–127, missing or non-numeric argument |
| `ERR:<command>` | unknown command | mistyped or not yet implemented command |

`ERR:<command>` has the inverse shape of the other two (the error precedes the colon) exactly
because the command was not recognised: with no valid command to echo, there is nothing to put
in front.

The distinction between `ERR` and `ERRPIN` is deliberate, and it is what lets the GUI give two
different messages: `ERRPIN` is **a configuration error** (the user entered the wrong pins and
must fix them in Configuration), `ERR` is **a physical problem** (the probe needs checking).

#### Pin validation: `parsePin()`

```cpp
if (t.charAt(0) == 'A') { ... return A0 + idx; }   // A0..A5
if (pin < 2 || pin > 13) return -1;                // D2..D13
```

Two explicit refusals deserve attention:

- **D0 and D1 are refused** because they are the USB serial line to the Raspberry: using them
  as a sensor pin would drop the communication, i.e. break the very channel through which the
  error would have to be reported.
- **An invalid token becomes `-1`, which becomes `ERRPIN`.** Without this check a typo in
  `config.yaml` would lead to a `digitalWrite()` on an arbitrary pin — which could be an
  actuator's. A typing mistake must not be able to start a pump.

### 5.6 How the three measurements are performed, Arduino-side

#### `read_pH,<pin>` — the slowest

The Atlas Surveyor probe declares a response time of 95 % in 1 s. The sketch honours that
literally: it averages the voltage over a **5-second window**, one sample per second.

```cpp
const unsigned long PH_READ_WINDOW_MS    = 5000;
const unsigned long PH_SAMPLE_INTERVAL_MS = 1000;
const int PH_N_SAMPLES = PH_READ_WINDOW_MS / PH_SAMPLE_INTERVAL_MS;   // 5
```

The average serves two purposes at once: **waiting** for the instrument to settle and
**reducing noise**. It is not equivalent to the closely-spaced samples `read_voltage()` already
takes internally, which are all at the same instant and therefore say nothing about the
transient.

It then checks that the average voltage lies within the Surveyor's physical output range
(265 mV ≈ pH 14, 3000 mV ≈ pH 0), with a margin: **outside 150–3100 mV it answers `ERR`**,
because the probe is almost certainly disconnected or out of scale.

Finally it converts to pH using the official library — which uses the calibration points
stored in **EEPROM**, not a fixed straight line — and averages **three readings 1 s apart**:

```cpp
float ph1 = pH_probe.read_ph(); delay(1000);
float ph2 = pH_probe.read_ph(); delay(1000);
float ph3 = pH_probe.read_ph();
float ph = (ph1 + ph2 + ph3) / 3.0;
```

**A `read_pH` therefore occupies the Arduino for about 8 seconds.** This is why the serial
timeout on the Raspberry side is 15 s and not 2 (§5.7).

A small optimisation: the `Surveyor_pH` object is rebuilt **only if the requested pin has
changed** (`usePHPin`), because `begin()` re-reads the EEPROM and there is no point doing that
on every measurement.

#### `read_EC,<address>` — three values in one response

The Atlas EZO-EC circuit is queried **over I2C** (SDA on A4, SCL on A5), not over UART as in
Atlas's official example. The sketch documents the choice, and there are two concrete reasons:

1. `SoftwareSerial` **disables interrupts while receiving**, which would corrupt the
   ultrasonic sensors' `pulseIn()`;
2. I2C uses A4/A5 and **does not consume digital pins**, which must all stay free to be
   assigned from `config.yaml`.

In addition the probe is addressed by **address** and not by pin, so several EZO circuits could
be placed on the same bus in future.

In `setup()` the sketch decides once and for all which quantities the EZO must include in its
response:

```cpp
EC_probe.send_cmd("O,EC,1");    // conductivity
EC_probe.send_cmd("O,TDS,1");   // total dissolved solids
EC_probe.send_cmd("O,S,1");     // salinity
EC_probe.send_cmd("O,SG,0");    // specific gravity: DISABLED
```

It is these four lines that make the response contain **exactly the `EC,TDS,SAL` triple** the
Raspberry expects: changing them without updating `SENSOR_SPECS['EC']['values']` would
desynchronise the two sides.

The measurement is the `R` command, followed by the 600 ms of processing declared by Atlas.
Two checks before accepting it: `get_error() == SUCCESS`, and **the first character of the
response must be a digit** — if it is not, the EZO answered with a status message rather than a
measurement. In either case: `ERR`.

The three values are already in `EC,TDS,SAL` format and are **passed on exactly as they are**,
without reformatting, so as not to lose significant digits.

#### `read_us,<trig>,<echo>` — the simplest

```cpp
digitalWrite(trigPin, LOW);  delayMicroseconds(2);
digitalWrite(trigPin, HIGH); delayMicroseconds(10);   // 10 µs pulse (datasheet)
digitalWrite(trigPin, LOW);
long duration = pulseIn(echoPin, HIGH, US_TIMEOUT_US);
if (duration == 0) return -1.0;                       // no echo -> ERR
return (duration * 0.0343) / 2.0;
```

**Formula:**

```
distance [cm] = echo_duration [µs] × 0.0343 [cm/µs] / 2
```

`0.0343 cm/µs` is the speed of sound in air (~343 m/s at 20 °C); dividing by 2 removes the
return path. The 40 ms timeout corresponds to about 6.8 m: beyond that there is no useful
echo, and without a timeout an echo that never arrives would block the Arduino for ever.

The `pinMode()` calls are made **here and not in `setup()`** precisely because the pins are no
longer known at compile time.

### 5.7 The Raspberry side: `arduino_link.py`

Three levels, from the most concrete to the most abstract.

#### `SENSOR_SPECS` — the sensor table

```python
SENSOR_SPECS = {
    'pH': {
        'command': 'read_pH',
        'label': 'sonda di pH',
        'args':   [('pin', 'Pin analogico', 'A0')],
        'values': [('ph', '')],
    },
    'EC': {
        'command': 'read_EC',
        'label': 'sonda di conducibilità (EC)',
        'args':   [('address', 'Indirizzo I2C', 100)],
        'values': [('ec_us_cm', 'µS/cm'), ('tds_ppm', 'ppm'), ('salinity_psu', 'PSU')],
    },
    'US_water': {'command': 'read_us', 'label': 'sensore ultrasonico del serbatoio',
                 'args': [('trig', 'Pin TRIG', 2), ('echo', 'Pin ECHO', 3)],
                 'values': [('distance_cm', 'cm')]},
    'US_plant': {'command': 'read_us', 'label': 'sensore ultrasonico della crescita',
                 'args': [('trig', 'Pin TRIG', 4), ('echo', 'Pin ECHO', 5)],
                 'values': [('distance_cm', 'cm')]},
}
```

This is the bridge's **single extension point**. For each sensor it declares:

- `command` — the Arduino command name, **fixed**: not user-editable, because it must match
  the sketch's `COMMANDS[]` table;
- `args` — the triples `(key in config.yaml, GUI label, default)`: these are the values the
  user fills in and which end up inside the command, **in this order**;
- `values` — the pairs `(value name, unit)` the response contains, **in this order**;
- `label` — the human-readable name used in error messages.

Note that `US_water` and `US_plant` are two different **keys** sharing the same `command`: the
difference is entirely in the arguments. It is the exact reflection, Pi-side, of the choice
described in §5.4.

**Adding an entry here makes the sensor automatically available both in the GUI and in the
CLI**: neither has its own list of sensors, both read `SENSOR_KEYS` and `SENSOR_SPECS`. The GUI
builds the configuration-panel fields from `args`, and the labels with units from `values`.

> **Maintenance rule.** The `COMMANDS[]` table in the sketch and `SENSOR_SPECS` in
> `arduino_link.py` are the two halves of the same contract: a command added on one side and
> not the other is useless. They must be edited together.

`build_command()` is the only place in the project that knows how to **compose** a command
string:

```python
def build_command(sensor_key, sensor_cfg):
    spec = SENSOR_SPECS[sensor_key]
    parti = [spec['command']]
    for chiave, _etichetta, default in spec['args']:
        valore = (sensor_cfg or {}).get(chiave, default)
        if valore is None or str(valore).strip() == '':
            raise ArduinoError(sensor_key, f"Manca il parametro '{chiave}' ...")
        parti.append(str(valore).strip())
    return ','.join(parti)
```

A missing parameter becomes an `ArduinoError` **before** anything is written to the serial
port, with a message telling the user where to fill it in.

#### `ArduinoBoard` — one board, one port

It manages the serial port of **one** board and the probes assigned to it.

**Lazy connection.** The port is not opened when the program starts, but on the first reading,
and then it stays open:

```python
def _ensure_open(self, sensor_key=None):
    if self._serial is not None and self._serial.is_open:
        return self._serial
    self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
    time.sleep(self.reset_delay)          # <- 2 seconds
    self._serial.reset_input_buffer()
```

The two-second pause is not generic caution: **opening the USB port resets the Arduino UNO**.
This is normal board behaviour, caused by the DTR signal of the USB-serial converter. The
sketch restarts from `setup()`, and it takes a few seconds before it is listening again:
without the pause, the first command would arrive while the Arduino is still rebooting and
would be lost. Immediately afterwards the input buffer is flushed, since by then it contains
the welcome message printed by `setup()` (`"FnP fish_n_plant_reading_module pronto."` and the
pH/EC status lines).

**Self-healing.** If the cable is unplugged, writing or reading raises
`serial.SerialException`; the connection is invalidated (`_invalidate()`, which is just a
`close()`) and the next attempt reopens it by itself. **There is no need to restart the
program** to bring a reconnected board back into service.

**Timeout.** `DEFAULT_TIMEOUT_S = 15`, sized on the slowest command: a `read_pH` occupies the
Arduino for about 8 s (§5.6). A 2 s timeout — reasonable for a `read_us` — would make every pH
reading fail *systematically*, with the aggravating factor of leaving the response in the
buffer and desynchronising all subsequent readings.

**One lock per board.**

```python
self._lock = threading.Lock()
...
with self._lock:
    conn.write((command + '\n').encode('utf-8'))
    risposta = conn.readline().decode('utf-8', errors='replace').strip()
```

pH, EC, tank and growth are **four jobs on four distinct threads** which may share the same
board. The lock serialises the **pair** command+response, not the two operations separately:
without it, two concurrent readings would swap each other's answers. It is the only explicit
critical section in the whole system besides the camera's (§18).

The lock is **per board**, not global: with two Arduinos, readings on different boards stay
parallel.

#### `ArduinoHub` — all the boards, indexed by sensor

The rest of the program asks for `hub.read_float('US_water')`. Which board answers, on which
port, with which pins, is a detail that lives here and in `config.yaml`.

`reload()` rebuilds the `{sensor: board}` index from the current configuration, and handles two
anomalous cases **without stopping the program**:

- **unknown sensor** (a key not in `SENSOR_SPECS`) → warning, entry ignored;
- **same sensor on two boards** → warning, **the first one wins**. It is almost certainly a
  configuration mistake, but bringing down the greenhouse's startup over it would be
  disproportionate.

`reload()` is called by the GUI **after every configuration save**: changing a port, a pin or a
board's enabled flag takes effect immediately, without restarting the program.

Four ways of reading, each built on the previous one:

| Method | Returns | Used by |
|---|---|---|
| `read_raw(k)` | the raw string, e.g. `'1250.0,625.0,0.62'` | diagnostics, the GUI's "Test" button |
| `read_values(k)` | list of `float` | internal use |
| `read_float(k)` | the first value as a `float` | `TankManager`, `PlantGrowthManager`, pH |
| `read_named(k)` | `dict` `{name: float}` according to `values` | `WaterManager` for EC |

`read_named('EC')` returns `{'ec_us_cm': 1250.0, 'tds_ppm': 625.0, 'salinity_psu': 0.62}`: the
names come from `SENSOR_SPECS`, they are not repeated in the manager. If **fewer** values are
received than expected, it is an `ArduinoError` — better no measurement than three
misaligned quantities.

### 5.8 The complete path of a reading

```
TankManager._read_loop()                        [tank thread]
  └─ repeats n_samples times:
     arduino.read_float('US_water')
       └─ ArduinoHub._board_or_raise('US_water')   -> Board1  (or ArduinoError)
          └─ ArduinoBoard.read_sensor('US_water')
             ├─ build_command('US_water', {'trig': 2, 'echo': 3})  ->  "read_us,2,3"
             └─ send_command("read_us,2,3")
                └─ [LOCK]
                   ├─ _ensure_open()      opens the port if needed (+2 s reset)
                   ├─ write("read_us,2,3\n")
                   └─ readline()          <- waits at most 15 s
                                          ...   [ARDUINO: pulseIn on pins 2 and 3]
                   response: "read_us,2,3:12.40"
                └─ [UNLOCK]
             ├─ split(':')  -> 2 parts?               otherwise ArduinoError
             ├─ echo == command sent?                 otherwise invalidate + ArduinoError
             ├─ value == 'ERRPIN'?                    -> ArduinoError "invalid pins"
             ├─ value == 'ERR'?                       -> ArduinoError "unreliable reading"
             └─ "12.40"
       └─ float("12.40") -> 12.40
  ├─ median(readings)  -> 12.40 cm
  ├─ operating-range check 2-400 cm
  ├─ distance_to_water_volume() -> level, volume, fill                (§9.4)
  ├─ save_data() -> TANK_2026_09_05.txt
  └─ on_update() -> GUI
```

And the symmetric path, when something goes wrong:

```
ArduinoError(sensor, "message already in Italian, already readable")
  └─ TankManager._measure_distance()  keeps the last error
     └─ ErrorRecorder.record('US_water', "Non è stato possibile leggere ... : <message>")
        ├─ in-memory deque -> "Reading errors" section of the GUI (§11)
        ├─ ERRORS_2026_09_05.txt
        ├─ logger.error(...)   -> log file + console + GUI console
        └─ latest_extra_data()['errors'] -> JSON -> website
```

Two details of this path are not accidental.

**The error message is written once, in `arduino_link.py`, already in Italian and already
addressed to the end user**: «check that the USB cable is connected», «correct them in the
Configuration screen», «add it in the "Schede Arduino" card». There is no translation from
error code to sentence scattered between GUI and CLI: the message is born where the cause is
known and travels intact to the screen.

**One failed sample does not fail the measurement.** `_measure_distance()` tries `n_samples`
times and keeps the successful readings; it records an error **only if none succeeded**. A
single electrical disturbance must not produce a notification.

### 5.9 The "Schede Arduino" card and testing the connection

In the **Configuration** screen, the card *"Schede Arduino — porte USB e pin delle sonde"* is
generated entirely from `SENSOR_SPECS`. It contains:

- **🔍 Rileva schede** — `list_serial_ports()` (`serial.tools.list_ports`) lists the currently
  connected USB ports with their description, so the user picks from a list instead of
  remembering `/dev/ttyACM0`;
- the global `baudrate` and `timeout`;
- for each board: name, port, *enabled* checkbox, and for each sensor the fields for the
  arguments declared in `args`;
- **a preview of the command** that would actually be sent (`command_preview()`), updated as
  you type: it is the most direct way of showing that `trig: 2` and `echo: 3` become
  `read_us,2,3`;
- **Prova** (`test_arduino_sensor`) — performs a reading of that single sensor *right now* and
  shows the result or the error. It exists to verify the wiring without starting a job and
  without waiting for the next interval.

From the command line the equivalent is `-arduino` (list ports, board status, test a sensor),
documented in `DUCUMENTATION_CLI.md`.

### 5.10 Testing the link without the application

`arduino_modules/serial_command_arduino.py` is a deliberately elementary script — no classes,
no functions — which opens the port, sends a command and prints the response. It exists to
isolate problems: if it works and the application does not, the problem is not the wiring.

It also carries the one practical tip for finding the right port: run `ls /dev/tty*`
**before** plugging in the Arduino and **after**; the entry that appeared is the one to use.

### 5.11 Libraries required on the Arduino

To be installed in the Arduino IDE before compiling the sketch:

| Library | Needed for |
|---|---|
| Atlas Scientific **Surveyor** (`ph_surveyor.h`, `base_surveyor.h`) | pH probe, with calibration in EEPROM |
| Atlas Scientific **Ezo_i2c_lib** (`Ezo_i2c.h`) | EZO-EC circuit over I2C |
| `Wire.h` | I2C bus (bundled with the IDE) |

The HC-SR04 sensors require no library: `pulseIn()` is an Arduino core primitive.

### 5.12 Hardware connections

```
Raspberry Pi ---- USB cable ---- Arduino UNO
                                   |
     +-----------------------------+-----------------------------+
     |              |                    |                       |
  Surveyor pH    EZO-EC (I2C)      HC-SR04 tank           HC-SR04 growth
   OUT -> A0     SDA -> A4          TRIG -> D2              TRIG -> D4
   VCC -> 5V     SCL -> A5          ECHO -> D3              ECHO -> D5
   GND -> GND    VCC -> 5V          VCC  -> 5V              VCC  -> 5V
                 GND -> GND         GND  -> GND             GND  -> GND
```

The digital pins shown are those in `config.yaml`: **they can be changed without touching the
sketch**. The analogue and I2C ones can too (`pin: A0`, `address: 100`), with the single
constraint that I2C on the UNO physically lives on A4/A5.

No voltage divider: the Arduino works at 5 V just like the HC-SR04s. It is one of the
simplifications gained by moving the sensors from the Pi to the board (§5.1).

---

## 6. `JobsManager` — pumps and GPIO

Manages the irrigation cycles. It has three kinds of job: **AEROPONICS**, **IDROPONICS** and
the **generic jobs** defined by the user.

### 6.1 `runner()` — the thread launcher

```python
def runner(self, job, *args, **kwargs):
    job_thread = threading.Thread(target=job, args=args, kwargs=kwargs, daemon=True)
    job_thread.start()
```

Every pump activation is a `daemon` thread: the scheduler stays free to count time while the
pump is on, and the threads die automatically when the program closes.

### 6.2 Activation/deactivation pattern

All three kinds of job follow the same **flag + dedicated scheduler** pattern:

```python
def start_aeroponics(self):
    if self.aeroponics_job_active:
        return False                  # already active: the GUI shows a warning
    self.aeroponics_job_active = True
    threading.Thread(target=self.activate_aeroponics, daemon=True).start()
    return True

def activate_aeroponics(self):
    self.aero_schedule = schedule.Scheduler()          # the job's OWN scheduler
    self.aero_schedule.every(interval).minutes.do(
        self.runner, job=self.pump_aerophonics, gpio=..., irrigation_time=...)
    while self.aeroponics_job_active:                  # <- the flag is the exit condition
        self.aero_schedule.run_pending()
        sleep(1)

def deactivate_aeroponics(self):
    self.aeroponics_job_active = False                 # the loop exits within 1 s
```

Each job owns a **separate `Scheduler()` instance** (not `schedule`'s global scheduler): that
way one job can be stopped without touching the others. Deactivation is cooperative — a flag
is lowered and the loop ends on the next round (≤ 1 s).

### 6.3 `pump_aerophonics()` — fixed-time irrigation

Logic: switch on, count the seconds, switch off.

```python
self.gpios.output(gpio, False)        # on (active-low)
for i in range(irrigation_time):
    if i == irrigation_time - 1:
        self.gpios.output(gpio, True) # off
        break
    sleep(1)
```

With the current configuration: every **1200 minutes** (20 hours) the pump stays on for
**5 seconds**.

### 6.4 `pump_idrophonics()` — feedback irrigation

Here the duration is not fixed: the pump stops when the **level sensor** reports enough water,
or when the maximum safety time expires.

```python
for i in range(max_irrigation_time):
    if i == max_irrigation_time - 1:              # 1) safety timeout
        self.gpios.output(gpio_pump, True)        #    switch off anyway
        break
    if self.gpios.input(gpio_sensor) == 0:        # 2) level reached
        self.gpios.output(gpio_pump, True)        #    switch off
        break
    else:                                         # 3) level low
        self.gpios.output(gpio_pump, False)       #    keep it on
        sleep(1)
```

The sensor reads **0 = water high** (pump OFF) and **1 = water low** (pump ON). The
`max_irrigation_time` timeout (65 s) protects against a faulty sensor: without it, a sensor
stuck on "low" would pump for ever.

### 6.5 `on_off_general()` — configurable generic jobs

Generalises the pattern to any pin. Unlike the previous two, it **re-reads the parameters from
`config.yaml`**, looking for the entry with the matching `name`, and uses the arguments passed
in only as a fallback:

```python
job_config = next((j for j in self.configs['gpio_pins'] if j.get('name') == name), None)
if job_config is not None:
    gpio       = job_config.get('pin',      gpio)
    on_period  = job_config.get('on_time',  on_period)
    off_period = job_config.get('interval', off_period)
else:
    self.logger.warning(f'ON_OFF_GENERAL [{name}]: no matching entry in config.yaml ...')
```

State is held in a `general_jobs_active[name]` dictionary, so several generic jobs coexist
independently. The inner `_pulse()` function replicates the logic of `pump_aerophonics`.

### 6.6 `T_modifier()` — modulating irrigation with temperature

A function **not yet wired into the active flow** (no callers). The idea: shorten the wait
between irrigations when it is hot, through a **logistic sigmoid** centred on the optimal
temperature `Topt`:

```
t_modifier = amp / (exp(a·(T − Topt)) + 1) − amp/2        with a = −0.2, amp = 1
t_new      = t_old − t_old · t_modifier
```

The modifier is 0 at `T = Topt` (no correction), tends to **+0.5** for `T ≫ Topt` (wait halved
→ irrigate more often) and to **−0.5** for `T ≪ Topt` (wait increased by 50 %). The parameter
`a = −0.2` sets the steepness of the transition.

> ⚠️ In the current implementation the function contains a bug preventing it from running
> (see §20).

---

## 7. `AmbientManager` — DHT22 and VPD

Reads temperature and humidity from the **DHT22** sensor, computes VPD, saves to file and
uploads online.

### 7.1 Reading the sensor: `measure_dht22()`

```python
dht = eval(f"adafruit_dht.DHT22(board.D{gpio})")
while True:
    try:
        T = dht.temperature
        H = dht.humidity
        return T, H
    except RuntimeError as error:      # checksum/timing error: RETRY
        print(error.args[0])
        sleep(2.0)
        continue
    except Exception as error:         # real error: propagate
        dht.exit()
        raise error
```

The central point is the **distinction between the two kinds of error**. The DHT22 uses a
one-wire protocol with tight timing and on a non-real-time Linux it often fails with a
`RuntimeError` (bad checksum, missed pulse): these are **transient** errors and the strategy is
to retry after 2 s, indefinitely, until the reading succeeds. Any other exception indicates a
hardware problem and is propagated after releasing the sensor with `dht.exit()`.

### 7.2 Computing VPD

**VPD** (*Vapor Pressure Deficit*) measures how "thirsty" the air is: it is the difference
between the vapour the air could hold at saturation and the vapour it actually holds. It is the
parameter that governs plant transpiration.

```python
def VPD(self, T, H):
    es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))   # saturation pressure [kPa]
    ea = lambda H: H * es(T) / 100                          # actual partial pressure
    VPD = es(T) - ea(H)
    return VPD
```

- `es(T)` — **saturated vapour pressure**, Tetens equation, depends on T only;
- `ea(H)` — **actual vapour pressure**, obtained by scaling `es` by relative humidity;
- `VPD = es − ea = es·(1 − H/100)` — the deficit, in kPa.

> ⚠️ The constant `273.3` in the denominator differs from the standard Tetens formulation,
> which uses `237.3` (see §20).

### 7.3 The reading loop: `_read_loop()`

Started by `start_reading(on_update)` in a daemon thread. On each iteration it:

1. reads T and H (with the retry logic above);
2. computes VPD;
3. stores `self.last_T` / `self.last_H` — **this is where `ClimateManager` reads the data
   from**;
4. generates a timestamp (`%Y/%m/%d %H:%M:%S`) and a file name (`%Y_%m_%d`);
5. invokes the `on_update(temp, humidity, vpd, timestamp)` callback if present (updates the
   GUI);
6. writes the line into the daily file `TH_<YYYY>_<MM>_<DD>.txt`;
7. calls `upload_data_on_web()`;
8. waits with `self._stop_event.wait(interval)`.

**Immediate stopping** is achieved with `threading.Event`: `stop_reading()` calls
`self._stop_event.set()`, which unblocks the `wait()` instantly. With a `sleep(300)` the GUI
would have had to wait up to 5 minutes to stop the reading.

The write format is:

```python
format_data_out = "%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
```

The upload is delegated to the external module through the shell:

```python
os.system(f'python uploader/uploader.py data -t {T} -hu {H} -vpd {vpd} -ts "{timestamp}"')
```

`read_now()` instead performs a single, synchronous reading (the "Read now" button), without
saving or uploading.

### 7.4 `last_result` and re-reading from file — with a safety constraint

`last_result` (`{temperature, humidity, vpd, timestamp}`) is the last complete measurement, and
it feeds the Summary screen (§2.3). It is populated by `_read_loop`, by `read_now()` and — at
startup — by `load_last_th()`, which re-reads the last line of the most recent TH file.

`load_last_th()` uses the standard library only and picks the file with
`sorted(glob(...))[-1]`: the name `TH_%Y_%m_%d.txt` sorts chronologically as a string too, so
the datum is there even if the panel is opened at midnight and today's file does not exist yet.
Units are attached to the values (`23.40C`), so the number is extracted with the same regex as
`daily_th_processor` (§16.1) — but **without importing it**: that module pulls in `pandas`
(seconds of import and tens of MB resident on a Pi Zero W, just to read one line of text),
`schedule`, and above all runs `logging.basicConfig` **at import time**, reconfiguring the
GUI's logging.

> ⚠️ **`last_T`/`last_H` are not — and must not be — seeded from file.** They mean "read from
> the sensor in this session", and `ClimateManager.start()` refuses to start while they are
> `None` (§8.1): that is the precondition preventing the air conditioner from being driven
> without climate data. Populating them from file, perhaps "for symmetry" with `last_result`,
> would make the AC act on a temperature hours old. `last_result` is purely informative and
> can afford that; those cannot.

---

## 8. `ClimateManager` and `IRController` — air conditioner

Two levels: `ClimateManager` handles the **time cycle**, `IRController` the **decision** and
the transmission of the signal.

### 8.1 `ClimateManager.start()` — the control loop

```python
if self.ac_control_active:                    return 'already_active'
if self.ambient.last_T is None or self.ambient.last_H is None:
                                              return 'no_ambient'
```

**Fundamental precondition**: AC control does not start unless there is at least one ambient
reading. Without climate data there is no sense in driving the air conditioner, and the GUI
uses the `'no_ambient'` value to tell the user to start the T/H reading first.

The loop:

```python
while not self._stop_event.is_set():
    if self.ambient.last_T is not None and self.ambient.last_H is not None:
        self.ir_controller.evaluate_and_send(self.ambient.last_T, self.ambient.last_H)
        ...
    self._stop_event.wait(interval * 60)      # control_time is in MINUTES
```

`stop()` breaks the cycle **and forces a switch-off** with `ir_controller.force_off()`: the
system never leaves the air conditioner running when control is deactivated.

### 8.2 `IRController.evaluate_and_send()` — the state machine

Internal state: `last_command_sent` (`'T_low_21'`, `'dry'`, `'off'` or `None`) and
`command_sent_time`. The logic, in evaluation order:

**1. Safety timeout** — evaluated before anything else:

```python
if self.last_command_sent in ('Tlow', 'Hlow') and self.command_sent_time is not None:
    elapsed_minutes = (now - self.command_sent_time) / 60.0
    if elapsed_minutes >= self.time_max_on:
        self.send_command('off'); ...; return
```

It prevents the air conditioner from staying on for more than `time_max_on` (10 min)
continuously.

**2. Temperature (absolute priority)**

```python
if current_temp > self.Topt:                      # Topt = ir_control.T_max = 26 °C
    if self.last_command_sent != 'T_low_21':
        self.send_command('T_low_21')             # cool down
        self.last_command_sent = 'T_low_21'
        self.command_sent_time = now
    return                                        # <- humidity is NOT evaluated
```

The `return` is the key: **as long as the temperature is high, humidity is ignored**. The air
conditioner has one active mode at a time, and cooling (which dehumidifies by itself) takes
precedence.

The `if self.last_command_sent != 'T_low_21'` check avoids retransmitting the IR command on
every cycle if the air conditioner is already in the desired state.

**3. Returning from the temperature branch** — if T has come back below the threshold and the
state was `T_low_21`, it sends `off`.

**4. Humidity** — evaluated only if the temperature is fine:

```python
if current_humidity > self.Hopt:                  # Hopt = ir_control.H_max = 65.5 %
    if self.last_command_sent != 'dry':
        self.send_command('dry')                  # dehumidify
else:
    if self.last_command_sent == 'dry':
        self.send_command('off')                  # humidity back to normal: switch off
```

### 8.3 Transmitting the IR signal

```python
def send_command(self, command):
    cmd = f"piir play --gpio {self.tx_gpio} -f {self.file_ac_name} {command}"
    result = os.system(cmd)
```

The module does not modulate the infrared LED directly: it delegates to the external utility
**`piir`**, which reads the codes from the `ac_remote.json` file (previously recorded from the
original remote control) and retransmits them on the TX pin. A non-zero exit code produces a
warning in the log but raises no exception: a lost IR command will be retried on the next
cycle.

---

## 9. `TankManager` — tank level (HC-SR04)

The tank's ultrasonic sensor is **no longer connected to the Raspberry's GPIO**: it sits on the
Arduino (§5), and the manager reads it with `arduino.read_float('US_water')`.

The module `sensors/ultrasonic_sensor/ultrasonic_measurement.py` is still used, though, for two
things that do not depend on where the sensor is: the **volume maths**
(`distance_to_water_volume`) and **saving to file** (`save_data`). It also remains runnable on
its own (`python3 ultrasonic_measurement.py`) with its own GPIO, for anyone wanting to wire an
HC-SR04 straight to the Pi.

### 9.1 Parameters with fallbacks

```python
def _params(self):
    t = self.configs.get('tank', {}) or {}
    return dict(
        height=t.get('tank_height_cm',       self._tank.TANK_HEIGHT_CM),   # 30.0 cm
        offset=t.get('sensor_offset_cm',     self._tank.SENSOR_OFFSET_CM), #  2.0 cm
        area=t.get('tank_area_cm2',          self._tank.TANK_AREA_CM2),    # 900.0 cm²
        low=t.get('water_low_threshold_l',   self._tank.WATER_LOW_THRESHOLD_L), # 3.0 L
        interval=t.get('read_interval',      self._tank.READ_INTERVAL_S),
        n=t.get('n_samples',                 self._tank.N_SAMPLES),
        save=t.get('saving_dir',             self._tank.SAVE_DIR),
    )
```

Each parameter is looked up first in `config.yaml`, then in the module's constants.
**`trig_pin` and `echo_pin` are gone**: the sensor's pins live in
`arduino.boards[].sensors.US_water`, because that is where they are needed — they are what ends
up inside the `read_us` command (§5.4).

`_params()` is re-read on every round of the loop, so an interval or threshold changed and
saved from the GUI takes effect without restarting.

### 9.2 Physical principle of the measurement

The HC-SR04 emits a burst of 8 ultrasonic pulses at **40 kHz** and holds the ECHO pin high for
the whole time of flight of the wave (out and back). The timing is done on the Arduino (§5.6):

```
distance [cm] = echo_duration [µs] × 0.0343 [cm/µs] / 2
```

`0.0343 cm/µs` is the speed of sound in air at ~20 °C; dividing by 2 removes the return path.
An echo that never arrives times out after 40 ms (≈ 6.8 m) and becomes `ERR`, which on the
Raspberry becomes an `ArduinoError`.

> **Hardware note.** The voltage divider that was needed on the Raspberry (ECHO outputs 5 V,
> the Pi's GPIO tolerate 3.3 V) **is no longer required**: the Arduino works natively at 5 V.

### 9.3 Noise filtering: the median of N readings

```python
letture = []
for _ in range(max(1, int(n_samples))):
    try:
        letture.append(self._arduino.read_float('US_water'))
    except ArduinoError as e:
        ultimo_errore = e            # carry on: one lost sample is not a fault

if not letture:
    self._errors.record('US_water', "Non è stato possibile leggere ... : " + ...)
    return None

return median(letture)
```

The function returns the **median**, not the mean: a deliberate choice, because the median is
robust to outliers — a single spurious echo (a reflection off the tank wall, foam on the water)
would move the mean, not the median. It is the same statistic already used by
`measure_distance_avg()` in the standalone module (which, despite its name, also computes the
median).

**It is the Raspberry that repeats the readings**, not the Arduino: the sketch is asked for one
measurement at a time. This keeps the Arduino an elementary executor and the sampling policy
(`n_samples`) configurable from `config.yaml` without recompiling the board (§5.3).

An error on a single sample produces **no** report: it is kept aside and the loop carries on.
A report is issued only if **none** of the `n_samples` readings succeeded, and in that case it
carries the last error received, which is the one with the most useful explanation.

Note: the 65 ms delay between one sample and the next, recommended by the datasheet, is
implicit here — a full command/response round trip on a 9600-baud serial line takes longer than
that.

### 9.4 From distance to volume: `distance_to_water_volume()`

```
   [SENSOR]         <- sensor_offset_cm from the rim
   [ tank rim    ] ---
   [             ]    | air column = distance − offset
   [ ~~~ water ~~]  ---
   [             ]    | water_level_cm
   [ tank bottom ]  ---
```

```python
air_column_cm  = distance_cm - sensor_offset_cm
water_level_cm = tank_height_cm - air_column_cm
water_level_cm = max(0.0, min(water_level_cm, tank_height_cm))   # physical clipping
volume_L     = (water_level_cm * tank_area_cm2) / 1000.0         # cm³ -> L
fill_percent = (water_level_cm / tank_height_cm) * 100.0
```

**Formulas:**

```
level      [cm] = tank_height − (measured_distance − sensor_offset)
volume      [L] = level [cm] × cross-section [cm²] / 1000
fill        [%] = level / tank_height × 100
```

**Clipping** to `[0, tank_height_cm]` protects against calibration errors: without it, a wrong
offset would produce negative volumes or volumes above capacity.
The model assumes a tank with a **constant cross-section** (`tank_area_cm2`); for irregular
containers the volume would have to be recomputed.

### 9.5 Validation and alarm

`read_now()` applies two checks before accepting the measurement:

```python
if dist is None:                   # no successful reading: error already recorded
    return None
if dist < 2.0 or dist > 400.0:     # outside the HC-SR04 operating range
    self._errors.record('US_water', f"... distanza {dist:.1f}cm fuori dal range "
                                    f"operativo (2-400cm). Misura ignorata.")
    return None
```

**The two cases are treated differently, and that is deliberate.** The first has already
recorded its own error in `_measure_distance()`, with the real cause (cable, pins, probe);
recording it again here would produce two entries for one fault. The second is an error only
this level can recognise — the Arduino answered a perfectly valid number, it is the *meaning*
that does not hold up.

The `_read_loop()` cycle saves to file and compares against the reserve threshold:

```python
if result['volume_L'] < p['low']:
    self.logger.warning(f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                        f"sotto la soglia di {p['low']}L! Riempire la tanica.")
```

A nearly empty tank is a logger `warning` and **not** an entry in the error register (§11): it
is not a reading fault, it is agronomic information. The error register collects only what
prevented a measurement.

### 9.6 Re-reading the last level

`load_last_tank(save_dir)` re-reads the last line of the most recent `TANK_*.txt` file and
populates `last_result` in `__init__`, as the spectrometer and growth managers already do with
their histories. Without it, the tank level would be the only datum **lost at every restart**
of the program, and the Summary screen (§2.3) would show an empty panel until the first
reading.

The reader lives in `tank_manager.py` and **not** in `ultrasonic_measurement.py`: that module
does `import RPi.GPIO` at module level, whereas reading a text file has no need whatsoever for
GPIO — and so the function stays importable and testable off the Raspberry too. It skips the
header (`startswith("datetime")`) and malformed lines, returning `None` if it finds nothing
readable.

---

## 10. `WaterManager` — pH and electrical conductivity

It measures **what** the water is like, while `TankManager` (§9) measures **how much** of it
there is. Both probes are Atlas Scientific, both connected to the Arduino (§5):

| Quantity | Probe | Command | What it tells you |
|---|---|---|---|
| pH | Surveyor V3.0 + Lab Grade pH Probe Gen 3 | `read_pH,A0` | acidity of the solution |
| EC, TDS, salinity | EZO-EC over I2C | `read_EC,100` | how concentrated the nutrient solution is |

### 10.1 Two jobs, not one

pH and EC are **two independent jobs**, each with its own interval, thread and start/stop
commands:

```python
water.start_ph_reading(on_update)   /  water.stop_ph_reading()   /  water.is_ph_running()
water.start_ec_reading(on_update)   /  water.stop_ec_reading()   /  water.is_ec_running()
```

This is not duplication: the two probes have different timings and purposes, are calibrated
separately and fail separately. Having to stop them together would mean, when servicing the pH
probe, losing concentration monitoring as well.

Two conveniences remain for treating them together:

```python
def is_running(self):  return self.is_ph_running() or self.is_ec_running()
def stop_all(self):    ...   # stops both, True if at least one was running
```

`is_running()` is the one the **Processes** screen uses for the summary entry; the two separate
indicators use `is_ph_running()` and `is_ec_running()` (§2.2).

### 10.2 A pH reading

```python
try:
    ph = self._arduino.read_float('pH')
except ArduinoError as e:
    self._errors.record('pH', f"Non è stato possibile leggere il sensore di pH, "
                              f"controlla il motivo: {e.message}")
    return None

if ph < 0.0 or ph > 14.0:
    self._errors.record('pH', f"... valore {ph} fuori dalla scala 0-14. Misura ignorata.")
    return None
```

**A single sample**, unlike the ultrasonic sensors: the averaging is already done by the
Arduino, which for a `read_pH` takes about 8 s averaging over a 5-second window plus three
conversions (§5.6). Repeating it from the Pi would triple the time without adding information.

The value is then rounded with `round_decimals()` (`water.decimals`, default 2), stored in
`last_ph`, written to file and compared against the thresholds:

```python
if result['ph'] < p['ph_min'] or result['ph'] > p['ph_max']:
    self.logger.warning(f"WATER pH FUORI RANGE: {result['ph']} non è compreso fra "
                        f"{p['ph_min']} e {p['ph_max']}. Correggere la soluzione nutritiva.")
```

### 10.3 An EC reading: three quantities in one go

```python
valori = self._arduino.read_named('EC')
# {'ec_us_cm': 1250.0, 'tds_ppm': 625.0, 'salinity_psu': 0.62}
```

The EZO-EC circuit returns conductivity, total dissolved solids and salinity in **a single
response**, because that is how it was configured in `setup()` (§5.6). One reading therefore
populates the whole EC panel of the interface: there would be no sense — and it would be slower
and less coherent — in asking for the three quantities separately.

`read_named()` is the only hub method returning a dictionary, and it is used only here. The key
names come from `SENSOR_SPECS`, they are not repeated in the manager: adding specific gravity
(SG) would mean enabling it in the sketch and adding a pair to `values`, without touching
`WaterManager`.

Validation is applied to `ec_us_cm` alone, against the **declared full scale of the EZO-EC**
(0–200000 µS/cm). TDS and salinity are quantities derived from the same measurement: if
conductivity is plausible, so are they.

### 10.4 Alarm thresholds and validity ranges

This is the distinction already anticipated in §4, and here it is particularly visible:

| | pH | EC |
|---|---|---|
| **Validity range** (constant in the code, outside → measurement **discarded**) | 0 – 14 | 0 – 200000 µS/cm |
| **Alarm thresholds** (in `config.yaml`, outside → measurement **saved** + warning) | `ph_min` 5.5 – `ph_max` 6.5 | `ec_min` 800 – `ec_max` 2000 µS/cm |

A pH of 8.2 is an **agronomic** problem: it must be recorded, displayed and corrected by acting
on the solution. A pH of 21 is an **electrical** problem: it never existed, and saving it would
pollute the history and the charts. Confusing the two cases would make both the alarm and the
archive useless.

### 10.5 The file format: both probes write to the same table

```
datetime			 ph	 ec_uScm	 tds_ppm	 sal_psu
2026/09/05 09:00:12	 6.12	 --	 --	 --
2026/09/05 09:04:31	 --	 1250.0	 625.0	 0.62
```

A single `WATER_%Y_%m_%d.txt` file for both probes, but **almost every line fills only half of
it**: the intervals are independent, so pH and EC write at different moments. Columns not
measured hold `--`.

The placeholder is not cosmetic: on re-reading, `--` becomes `None`, and the reader can
distinguish **"not measured"** from **"measured zero"** — which, for a conductivity, are two
very different statements.

`load_last_water()` exploits exactly this: it walks the file **backwards** looking separately
for the last valid pH and the last valid EC, and stops as soon as it has found both. It is the
reason the Summary's H2O panel has two distinct dates (§2.3).

### 10.6 The periodic cycle

Identical for the two probes, and identical in shape to that of every other manager:

```python
while not self._ph_stop_event.is_set():
    try:
        result = self.read_ph_now()          # read_ph_now already saves to file
        if result is not None and on_update is not None:
            on_update(result)
    except Exception as e:
        self.logger.error(f"Errore lettura pH: {str(e)}")

    self._ph_stop_event.wait(self._params()['ph_interval'])
```

Three details recur throughout the project:

- **the first measurement starts immediately**, then the interval is awaited: with a 30-minute
  cadence, the alternative would be an empty screen for half an hour;
- the wait uses `threading.Event.wait()`, so the Stop button interrupts **immediately** even a
  long wait (§18);
- `_params()` is re-read **on every round**, so changing the interval from the GUI takes effect
  from the next cycle without restarting.

The `except Exception` is the safety net: an unforeseen error is logged but **does not kill the
thread**, which will try again next time round. Foreseen errors — the probe's — have already
been handled inside `read_ph_now()` and never reach this far.

---

## 11. `ErrorRecorder` — reading-error register

When a probe refuses to be read, the information has to reach **a person**. The log file is not
enough: nobody opens it, and by the end of the day it contains thousands of lines of successful
measurements.

### 11.1 Why it is not just a logging handler

Because it has **two consumers with different requirements**:

1. the **"Reading errors"** section of the Log screen, which wants the latest errors with a
   timestamp and a readable sentence, immediately and without re-reading the disk;
2. the **uploader**, which must be able to publish the day's errors to the website — so they
   must **survive a restart** of the program.

An in-memory logging handler satisfies the first and not the second; a log file satisfies the
second but in a format that cannot be queried. `ErrorRecorder` does both, and on top of that
passes every error to the shared logger as well, so it ends up in the log file and on the
terminal like everything else.

```python
def record(self, source, message):
    errore = {'timestamp': ..., 'source': source or '-', 'message': ...}
    with self._lock:
        self._history.append(errore)     # deque(maxlen=history_len) -> GUI
        self._append_to_file(errore)     # ERRORS_%Y_%m_%d.txt      -> uploader
    self.logger.error(f"{errore['source']}: {errore['message']}")
    return errore
```

### 11.2 Details that matter

**The lock.** Readings come from different threads — one job per probe — so both the `deque`
and the file write must be protected. It is the second critical section in the system, after
the serial one (§5.7).

**Normalisation.** Tabs and newlines inside the message would break the file format, which is
tab-separated: they are replaced with spaces *before* writing.

**Repopulation at startup.** The constructor re-reads the errors already recorded **today**:

```python
for errore in load_errors(p['save_dir'], logger=self.logger):
    self._history.append(errore)
```

Without it, after a restart the Log screen would start empty and a fault that happened an hour
earlier would look as if it had never occurred.

**An error while writing errors is not fatal.** If `_append_to_file()` fails (disk full,
permissions), the exception is caught and logged: the error still stays in memory and in the
log, and above all **the reading in progress does not fail**.

### 11.3 Who writes to it

| Source (`source`) | Recorded by | When |
|---|---|---|
| `pH` | `WaterManager` | `ArduinoError`, or a value outside the 0–14 scale |
| `EC` | `WaterManager` | `ArduinoError`, or a value beyond full scale |
| `US_water` | `TankManager` | none of the `n_samples` readings succeeded, or distance outside 2–400 cm |
| `US_plant` | `PlantGrowthManager` | likewise, for the growth sensor |

The source names are **the same keys as in `SENSOR_SPECS`** (§5.7): a user reading `US_plant`
in the "source" column finds the same label in the "Schede Arduino" card of the Configuration
screen, and knows where to act.

The register collects **only errors that prevented a measurement**. A tank in reserve or a pH
out of range are logger warnings, not register entries: they are successful measurements
saying something unwelcome, which is a different category.

### 11.4 The file

```
datetime	source	message
2026/09/05 09:41:03	US_water	Non è stato possibile leggere il sensore ultrasonico del serbatoio, controlla il motivo: Scheda Arduino 'Board1' non raggiungibile sulla porta /dev/ttyACM0: controlla che il cavo USB sia collegato (...)
```

One file per day, `ERRORS_%Y_%m_%d.txt`, tab-separated, header written only if the file is new,
like every other format in the project (§15). `load_for_date(giorno)` re-reads it for any day —
which is what the uploader needs — and `load_today()` is the shortcut for today.

The message is the one born in `arduino_link.py`, enriched by the manager with the context
("which probe") and kept whole: it is already a complete sentence, in Italian, saying what
happened and what to do.

---

## 12. `PlantGrowthManager` — plant height (HC-SR04)

Measures how much the plants have grown, with a **second HC-SR04 sensor** mounted above the
root chamber and pointing down. Like the tank's, it is connected to the **Arduino** (§5) and
not to the Raspberry's GPIO: same physics, same `read_us` command, different target. What
distinguishes it is the pin pair — `US_plant` instead of `US_water` (§5.4).

### 12.1 Principle of the measurement

The sensor measures the distance from itself to the **top of the plant**. Plant height is
therefore the difference from a **reference distance**, measured with a ruler with no plant
present:

```
   [SENSOR]   ---
   [        ]    |
   [   🌱   ]    | measured_distance      reference_height_cm
   [        ]  ---                                |
   [ root chamber ] -----------------------------  ---
```

```
h_plant [cm] = reference_height_cm − measured_distance
```

With the sensor 70 cm above the root chamber:

| Distance read | h_plant | Meaning |
|---|---|---|
| 70 cm | 0 cm | plant has not grown yet |
| 65 cm | 5 cm | the plant has grown by 5 cm |

```python
h_plant = max(0.0, p['reference'] - dist)
```

**Clipping at 0** plays the same role as the tank's clipping (§9.4): it protects against an
imprecise calibration of `reference_height_cm`. Without it, a reference underestimated by a few
millimetres would produce negative heights — physically impossible.

`reference_height_cm` is therefore **the parameter to calibrate**, and it is calibrated with
the sensor itself (§12.6) with the root chamber empty: the distance the sensor reads at that
moment *is*, by definition, the reference. Measuring it with a ruler is possible but less
accurate, because ruler and sensor do not necessarily start from the same point: the sensor
measures from its own membrane, and an error in the reference transfers **identically to every
subsequent measurement**.

### 12.2 Parameters with fallbacks

Same idiom as `TankManager._params()` (§9.1): `config.yaml` first, then the module's constants.
The defaults live in `plant_growth.py` and not in `ultrasonic_measurement.py`, because that
module's constants (`TANK_HEIGHT_CM`…) describe the **tank**.

```python
def _params(self):
    g = self.configs.get('plant_growth', {}) or {}
    return dict(
        interval_days=g.get('read_interval_days', READ_INTERVAL_DAYS),  # 1 day
        n=g.get('n_samples', N_SAMPLES),                                # 3
        reference=g.get('reference_height_cm', REFERENCE_HEIGHT_CM),    # 70.0 cm
        decimals=g.get('decimals', DEFAULT_DECIMALS),                   # 1
        save_enabled=g.get('save', True),
        save_dir=g.get('saving_dir', SAVE_DIR),
        history_len=g.get('history_len', HISTORY_LEN),                  # 30
    )
```

As for the tank, **`trig_pin` and `echo_pin` no longer appear**: the sensor's pins live in
`arduino.boards[].sensors.US_plant` (§5.4).

### 12.3 Mean or median? — `_measure_mean_distance()`

The two managers reading an HC-SR04 use **different statistics**, and the difference is
deliberate:

| Manager | Sensor | Statistic | Why |
|---|---|---|---|
| `TankManager` | `US_water` | **median** | robust to outliers: a spurious echo (foam, a reflection off the tank wall) would move the mean, not the median |
| `PlantGrowthManager` | `US_plant` | **mean** | on a still target such as a plant the noise is symmetric, and the mean uses the information of every reading instead of discarding N−1 of them |

```python
letture = []
for _ in range(max(1, int(p['n']))):
    try:
        letture.append(self._arduino.read_float('US_plant'))
    except ArduinoError as e:
        ultimo_errore = e

if not letture:
    self._errors.record('US_plant', "Non è stato possibile leggere ... : " + ...)
    return None

dist = mean(letture)

if dist < 2.0 or dist > 400.0:          # HC-SR04 operating range
    self._errors.record('US_plant', f"... distanza {dist:.1f}cm fuori dal range ...")
    return None
return dist
```

`_measure_mean_distance()` is the **single definition of "valid measurement"** for growth: both
`read_now()` and `calibration_distance()` (§12.6) use it. With two separate implementations, a
calibration could accept a reading a measurement would reject — and since calibration shifts
*all* subsequent measurements, that would be the most expensive possible mistake.

With the current configuration growth averages **3 readings**.

### 12.4 Digits to keep: `data_config.py`

A support module beside `plant_growth.py`, deciding how many digits to keep from the sensor:

```python
DEFAULT_DECIMALS = 1
def round_decimals(value, decimals=None)      # rounds to N decimals
def round_significant(value, sig_digits)      # rounds to N significant digits
```

The manager uses `round_decimals` with `decimals` from `config.yaml`. Choosing **decimals**
rather than significant digits is motivated by the sensor's physics: the HC-SR04's resolution
is about **0.17 cm**, so on a measurement in cm what matters is how many digits after the point
are credible — and with `decimals: 1` the height is expressed to a generous millimetre, already
beyond the real resolution. `round_significant()` remains available for anyone preferring to
think in significant digits.

### 12.5 Validation, saving and history

Validation lives entirely in `_measure_mean_distance()` (§12.3): no successful reading, or a
distance outside the HC-SR04's operating range (2–400 cm). In both cases `read_now()` returns
`None` without writing anything to file, and the error has already gone into the register
(§11).

**Difference from `TankManager`:** here saving happens **inside `read_now()`**, not only in the
periodic cycle. With one measurement a day, a manual measurement is a primary use case, not a
preview: the same choice made by `SpectroManager`. It is subject to the `save` flag in
`config.yaml`:

```python
if p['save_enabled']:
    save_growth_data(result, p['save_dir'])
self.history.append({...})
self.history = self.history[-p['history_len']:]
```

The **history** (`self.history`) is rebuilt from file at instantiation with `load_history()`,
as `SpectroManager` does: the GUI therefore shows a populated chart and table right after a
restart, without querying the Arduino. It is kept in **ascending chronological order** — the
order the chart needs — and the table reverses it at display time. Malformed lines are logged
and skipped, they do not fail the read (same philosophy as `daily_th_processor.py`, §16.1).

### 12.6 Calibrating the reference

`calibration_distance()` performs the calibration: it measures the current distance (the mean
of `n_samples` readings, with the same validation as `read_now()`) and stores it as
`reference_height_cm`. It must be run **with the root chamber empty**. In the GUI it is the
"📐 Calibrazione" button of the Growth screen, which asks for confirmation before proceeding —
the same pattern as the spectrometer calibration (§13.3).

```python
dist = self._measure_mean_distance(p)          # validated mean: if None, nothing is written
reference = round_decimals(dist, p['decimals'])
save_reference_height(reference)                                                # to file
self.configs.setdefault('plant_growth', {})['reference_height_cm'] = reference  # in memory
```

Three choices deserve an explanation.

**1. The file is re-read from disk, not dumped from memory.** `save_reference_height()` opens
`config.yaml`, updates the single `plant_growth.reference_height_cm` key and writes it back.
Dumping `self.configs` would be more direct but wrong: that dictionary may contain values
modified at runtime — `test_gui.py` injects simulation paths into it — which would end up in
the production config. By touching one key only, nothing else is trampled.

**2. The value is updated in memory too, and this avoids a restart.** `_params()` re-reads
`self.configs` on every call (§12.2), so the next measurement already uses the new reference:
right after calibration `h_plant` is 0, as expected.

**3. The GUI must realign its own dictionary.** Here we meet a structural flaw of the project
(§20.6): the GUI's `self.config` and the managers' `self.ah.configs` are **two distinct
dictionaries**, read separately from the same file. `save_config()` dumps the whole
`self.config`, so without countermeasures the sequence would be:

> calibration (file: 63.2) → the user presses "Salva Configurazione" → the GUI dumps its
> dictionary, which still holds 70.0 → **calibration silently lost**.

That is why `calibration_distance()` **returns** the value, and the GUI updates both its own
`self.config` and the StringVar of the "Altezza riferimento" field in the Configuration screen —
it is that StringVar `save_config_changes` re-reads when saving.

The button refuses to calibrate while the periodic reading is running: there is only one
sensor, and two overlapping ultrasonic pulses would falsify both measurements. A falsified
calibration is insidious because it shifts **every** subsequent measurement.

### 12.7 The periodic cycle

```python
p = self._params()
while not self._stop_event.is_set():
    result = self.read_now()          # read_now already saves to file
    if result is not None and on_update is not None:
        on_update(result)
    self._stop_event.wait(p['interval_days'] * SECONDS_PER_DAY)
```

The **first measurement starts immediately** and only then is the interval awaited: otherwise,
with a daily cadence, the user would see no data for 24 hours. The wait uses `threading.Event`
(§18), so the "Arresta Lettura" button interrupts even a full-day wait immediately.

The count **is not persisted**: after a restart it starts over, with an immediate measurement.
For a daily cadence that is acceptable.

### 12.8 The "Crescita" screen and the chart

It shows the height of the last measurement, its date, a chart of the trend over time and the
date/height table. All values are in **cm**. The buttons are "📏 Misura Adesso",
"▶️ Attiva Lettura", "⏹️ Arresta Lettura" and "📐 Calibrazione" (§12.6).

The chart is drawn with the **native primitives of `tk.Canvas`** (`create_line`,
`create_oval`), not with matplotlib. The choice is dictated by the hardware: on a Raspberry Pi
Zero W (512 MB RAM, single core) `matplotlib` would cost ~2-4 s of import time at GUI startup
and tens of MB resident. The cost would *not* be in the drawing — with one measurement a day
there are at most `history_len` points and redraws are very rare — but in the library itself.
The Tk primitives are already in memory and are enough for a polyline.

> Note: `daily_th_processor.py` (§16.1) does use matplotlib, but in a **separate process**,
> with a lazy import inside the function and the `Agg` backend: it never weighs on the GUI.

Redrawing is hooked to the `<Configure>` event (so it follows window resizing) and is repeated
after every measurement. With fewer than two points the Canvas shows a textual placeholder
instead of a degenerate polyline.

### 12.9 Hardware note

Both HC-SR04s are on the Arduino (§5.12) and coexist without conflicts because they use
**distinct pin pairs** — `2/3` for the tank, `4/5` for growth — declared in `config.yaml` and
transmitted inside the `read_us` command. The measurements never overlap in time either: the
board lock (§5.7) serialises command and response, so two jobs asking for a distance at the
same instant are served one after the other.

The **voltage divider** that was mandatory on the Raspberry (ECHO at 5 V against 3.3 V GPIO) is
**no longer needed** on either sensor: the Arduino works natively at 5 V.

The pins listed in `config.yaml` must still match the real wiring — it is the one thing the
software cannot verify by itself. The **Prova** button of the "Schede Arduino" card (§5.9)
exists exactly for this: if the pins are wrong it answers `ERRPIN`, if the sensor is not
connected it answers `ERR`, if everything is fine it answers a distance.

---

## 13. AS7265x spectrometer — MCARI2 index

Module `sensors/spectrometer/mcari2_as7265x.py`. It measures plant health with the **SparkFun
Triad AS7265x** sensor (18 channels, 410–940 nm, I2C bus).

### 13.1 Tolerant import

```python
try:
    import qwiic_as7265x
    _HW_AVAILABLE = True
except ImportError:
    qwiic_as7265x = None
    _HW_AVAILABLE = False
```

The module stays importable on a PC without the library: the **computation-only** functions
(`mcari2`, `compute_reflectance`, `evaluate_MCAR2`, `interpreta_mcari2`) remain usable and
testable off the Raspberry.

### 13.2 Band mapping

MCARI2 requires three bands, mapped onto the library's getters:

| Band | Nominal λ | AS7265x channel | Getter |
|---|---|---|---|
| GREEN | ~550 nm | 560 nm | `get_calibrated_g()` |
| RED | ~670 nm | 680 nm | `get_calibrated_s()` |
| NIR | ~800 nm | 810 nm | `get_calibrated_v()` |

The mapping lives in one place (`GREEN_GETTER`/`RED_GETTER`/`NIR_GETTER`) and is resolved with
`getattr`. `CHANNEL_MAP` lists all 18 channels for diagnostics.

### 13.3 The critical point: reflectance, not irradiance

The sensor returns **irradiance** (µW/cm²), which also depends on the intensity of the incident
light; MCARI2 is instead defined on **reflectance** (0–1). A calibration is therefore needed:

```
R(λ) = reading_on_target(λ) / reading_on_white_reference(λ)
```

`calibrate(sensor)` measures a white panel with the built-in LED on and stores the values in
`spectro_calibration.json` together with **gain and integration cycles**. `load_calibration()`
warns if the current parameters differ from those of the calibration — reference and target
must be acquired under the same conditions, otherwise the ratio has no physical meaning.

```python
GAIN = qwiic_as7265x.kGain16x if _HW_AVAILABLE else 2   # 16x
INTEGRATION_CYCLES = 50    # integration time ≈ value × 2.8 ms
SETTLE_TIME = 0.3          # LED settling before the measurement [s]
```

### 13.4 The MCARI2 formula

**MCARI2** (*Modified Chlorophyll Absorption in Reflectance Index 2*) estimates chlorophyll and
LAI, and is sensitive to water/nutrient stress (nitrogen deficiency in particular).

```
                1.5 · [2.5·(NIR − RED) − 1.3·(NIR − GREEN)]
MCARI2 = ───────────────────────────────────────────────────────────
           √[ (2·NIR + 1)² − (6·NIR − 5·√RED) − 0.5 ]
```

```python
numeratore = 1.5 * (2.5 * (nir - red) - 1.3 * (nir - green))
denominatore = math.sqrt((2.0 * nir + 1) ** 2 - (6.0 * nir - 5 * math.sqrt(red)) - 0.5)
return numeratore / denominatore
```

The **numerator** measures chlorophyll absorption: the `NIR − RED` term is high for healthy
vegetation (chlorophyll absorbs red and reflects near infrared), while subtracting
`1.3·(NIR − GREEN)` corrects for the effect of green reflectance.
The **denominator** is the normalisation factor reducing the influence of background soil.

### 13.5 Processing chain and interpretation

```
init_sensor() -> calibrate() -> [calibration JSON]
                                        |
read_bands() --raw--> compute_reflectance() --R--> mcari2() -> save_measurement()
```

`evaluate_MCAR2(target_bands, reference_bands=None)` is the high-level function: if the
reference is not supplied, it loads the last saved calibration.

Thresholds of `interpreta_mcari2()`:

| MCARI2 | Interpretation |
|---|---|
| < 0.4 | Possible water stress or nutrient deficiency (e.g. nitrogen) |
| 0.4 – 0.7 | Healthy crop |
| 0.7 – 0.9 | Very healthy crop, no deficiency detected |
| > 0.9 | Outside the expected typical range, check the measurement |

`test_spectrometer.py` is an interactive menu-driven script for field use: diagnostics of the
18 channels → white calibration → MCARI2 measurement.

---

## 14. Camera

The logic lives in `managers_classes/camera_manager.py` (`CameraManager`, same shape as the
other managers); `camera/takePicture.py` and `camera/camera.py` are CLI wrappers that read
`config.yaml` and drive the same manager the GUI drives.

### 14.1 Periodic acquisition

`start_acquisition()` / `stop_acquisition()` / `is_acquiring()` — a daemon thread takes a shot
every `camera.separation_hours` hours into `camera.saving_dir`. The wait uses
`_stop_event.wait(interval)` and not `sleep`: with a two-hour interval, a `sleep` would have
made "Disattiva acquisizione" ineffective until the next shot.

Every shot produces **two files**: a historical one with a timestamp
(`YYYY-MM-DD_HH-MM-SS.jpg`) and a fixed-name copy `image.jpg`, which is the one `uploader.py`
pushes to GitHub — the fixed name lets the website always point at the same URL for the latest
photo.

### 14.2 Live preview

`start_preview()` / `stop_preview()` / `toggle_preview()` / `is_previewing()` — opens the
`Preview.QTGL` window and keeps it open until it is closed. There is no longer a fixed timer:
`camera.py` used to show the preview for exactly 60 seconds and then exit.

### 14.3 Why the two uses are mutually exclusive

Picamera2 is a **single resource**: instantiating it twice makes the preview fail or, worse,
the scheduled shot. The manager prevents it from both sides — `start_preview()` returns `False`
if acquisition is active, `start_acquisition()` returns `False` if the preview is open — and a
`threading.Lock` protects the actual access to the object. The GUI turns the `False` into a
pop-up explaining which process must be stopped first.

### 14.4 The Camera screen

Three buttons ("Attiva acquisizione", "Disattiva acquisizione", "Attiva/Disattiva camera", the
last one with text following the state) and, at the bottom, the **last photo acquired** with
date and time. The photo is re-read from disk at startup by `load_last_photo()`, which takes
the most recent file ignoring `image.jpg` and derives the date from the **name** and not from
the mtime (which copying the file would falsify): without it, with `separation_hours: 2` the
screen would stay empty for two hours after every start.

Rendering goes through `_show_image()`, which uses **Pillow**: `tk.PhotoImage` only reads PNG
and GIF, while the photos are JPG. If Pillow is missing, the screen shows a message instead of
failing (`sudo apt install python3-pil.imagetk`). The reference to the image must be kept on
the label: Tk does not retain it, and without it the garbage collector makes the image vanish
as soon as it is drawn.

---

## 15. Data persistence: file formats

Almost every module writes **daily tabular files**, tab-separated, in a format consistent with
one another. The only exception is growth, for the reason explained below.

### TH (ambient) — `TH_YYYY_MM_DD.txt`

```
2026/06/28 14:32:01	 23.40C	 61.20%	 1.0234kPa
```

### TANK — `TANK_YYYY_MM_DD.txt`

```
datetime			 dist_cm	 lvl_cm	 vol_L	 fill_%
2026/06/28 14:32:01	  12.4	  19.6	  17.64	 65.3
```

### WATER (pH and EC) — `WATER_YYYY_MM_DD.txt`

```
datetime			 ph	 ec_uScm	 tds_ppm	 sal_psu
2026/09/05 09:00:12	 6.12	 --	 --	 --
2026/09/05 09:04:31	 --	 1250.0	 625.0	 0.62
```

A single file for two probes with independent intervals: columns not measured on that line hold
`--`, which on re-reading becomes `None` (§10.5).

### ERRORS — `ERRORS_YYYY_MM_DD.txt`

```
datetime	source	message
2026/09/05 09:41:03	US_water	Non è stato possibile leggere il sensore ultrasonico del serbatoio, controlla il motivo: ...
```

`source` is a `SENSOR_SPECS` key (`pH`, `EC`, `US_water`, `US_plant`). Tabs and newlines inside
the message are normalised to spaces before writing, so one line stays one line (§11.2).

### SPECTRO — `SPECTRO_YYYY_MM_DD.txt`

```
datetime			 green_raw	 red_raw	 nir_raw	 R_green	 R_red	 R_nir	 MCARI2
```

### GROWTH — `GROWTH.csv`

```
datetime,h_plant_cm
2026/07/10 09:00:00,0.0
2026/07/11 09:00:00,2.3
2026/07/12 09:00:00,5.1
```

A double exception compared with all the others: it is the only **CSV** file (comma-separated,
not tab-separated) and the only **cumulative** one instead of daily. The reason is the cadence:
with one measurement a day or less, a daily file would contain **a single line**, and rebuilding
the history for the chart would mean opening dozens of files to read one value each. A single
append-mode file makes `load_growth_data()` a single read.

The **date uses the same format as the TH files** (`%Y/%m/%d %H:%M:%S`), so growth data stays
cross-referenceable with temperature and humidity.

The TANK, WATER, ERRORS, SPECTRO and GROWTH files write the **header only if the file does not
exist** (`write_header = not os.path.exists(file_path)`); TH files have no header. Files are
always opened in append mode (`'a'`), so restarting the program loses no data.

### These files are also read back

They are not just an archive: **every format has a reader**, and that is what allows the Summary
screen (§2.3) to show the last known value at startup, before any sensor has been queried.

| File | Reader | What it returns |
|---|---|---|
| TH | `load_last_th()` (§7.4) | last T/H/VPD measurement |
| TANK | `load_last_tank()` (§9.6) | last level |
| WATER | `load_last_water()` / `load_water_history()` (§10.5) | last pH **and** last EC, searched separately |
| SPECTRO | `load_measurements()` → `SpectroManager.load_history()` | last N MCARI2 measurements |
| GROWTH | `load_growth_data()` → `PlantGrowthManager.load_history()` | last N heights |
| ERRORS | `load_errors()` (§11.2) | one day's errors, for the GUI and the uploader |

All of them use **the standard library only** and are tolerant: headers, blank lines and
malformed lines are skipped, and a missing file is not an error but a `None`/empty list. It is
the same philosophy as the daily parsing (§16.1): a datum corrupted by a power cut must not
prevent all the others from being read.

---

## 16. Daily processing and upload

### 16.1 `daily_th_processor.py`

`DailyTHManager` is scheduled **every day at 00:01** and processes the previous day's file. It
reads the directories from the `Daily_Data` section of `config.yaml` (`th_data_dir`,
`plot_output_dir`); the module's constants remain only as defaults. It is driven from the
Environment screen ("Attiva Daily" / "Arresta Daily") or from the command line
(`python3 managers_classes/daily_th_processor.py`).

The `daily_job()` pipeline:

```
1. get_yesterday_filename()  -> path of TH_<yesterday>.txt
2. parse_th_file()           -> pandas DataFrame
3. compute_statistics()      -> means, max, min
4. generate_plot()           -> plot.png (3 subplots)
5. call_uploader()           -> upload means + plot to GitHub
```

**Parsing** — the file has to be re-read as text, with units attached to the numbers
(`23.40C`, `61.20%`), so the number is extracted with a regex:

```python
timestamp   = datetime.strptime(parts[0].strip(), '%Y/%m/%d %H:%M:%S')
temperature = float(re.search(r'[\d.]+', parts[1]).group())
humidity    = float(re.search(r'[\d.]+', parts[2]).group())
vpd         = float(re.search(r'[\d.]+', parts[3]).group())
```

Malformed lines are **logged and skipped**, they do not fail the job: a day's data is not lost
because of one line corrupted by a power cut.

**Statistics** — mean/max/min for T, H and VPD (T and H rounded to 2 decimals, VPD to 3).

**Chart** — 3 vertical subplots (T, H, VPD) with `matplotlib`, `Agg` backend (non-interactive,
required to generate images without a display), X axis formatted `%H:%M` with ticks every 2
hours, saved at 250 dpi as `plot.png`.

**Upload** — invokes `uploader.py` via `subprocess.run` with `sys.executable` (guaranteeing the
same Python interpreter, hence the same virtual environment).

**First round without upload** — `start()` runs the job once immediately with `upload=False`,
then enters the scheduler. This is to populate the Environment screen: without it, statistics
and plot would stay empty until the following midnight. The upload is skipped because that data
was already uploaded by the previous round.

**Cancelling the job** — on exiting the loop, `schedule.cancel_job(job)` is called: `schedule`
keeps a global queue, so without cancellation every restart from the GUI would accumulate a
duplicate job.

### 16.1.1 The "Elaborazione giornaliera" section of the Environment screen

Below the instantaneous T/H/VPD values, the screen shows the results of the last job:
start/stop buttons, a **T/H/VPD × max/min/mean** table (the keys are those returned by
`compute_statistics`) and the generated `plot.png`. `refresh_daily_section()` runs every 2 s
but redraws only when the processed day changes: reloading the PNG from disk on every tick
would be pure waste on a Pi Zero W — the same logic as `_cambiato()` in the Summary.

### 16.2 `uploader/uploader.py`

A sub-command CLI that publishes to GitHub through the **REST API**, used as the website's data
back end.

**What gets published.** The periodic upload starts from `AmbientManager`, which has the
tightest cadence, but it does not publish temperature and humidity only: before uploading it
calls `extra_data_provider`, i.e. `aeroHelper.latest_extra_data()` (§3), and adds to the JSON
the latest known values of tank level, pH, EC/TDS/salinity, plant height and the **ten most
recent reading errors** (§11).

The website therefore receives **a coherent snapshot** of the greenhouse at every upload,
instead of a separate update per probe. Quantities never measured — or probes not yet installed
— simply do not appear in the JSON: the alternative, publishing zero, would make the site show
a measurement nobody took.

| Command | Effect |
|---|---|
| `data -t -hu -vpd -ts` | Writes `dati.json` and uploads JSON + image |
| `averages -avgt -avgh -avgvpd -maxT ... -ts` | Writes `avg_data.json` and uploads JSON + plot |
| `image` | Uploads `image.jpg` only |
| `plot` | Uploads `plot.png` only |

Credentials come from environment variables (`.env` via `python-dotenv`): `GITHUB_TOKEN`,
`GITHUB_USR`, `GITHUB_REPO`, `GITHUB_BRANCH`. **No secret is in the code.**

**Update protocol** — the GitHub Contents API requires the SHA of the existing file in order to
overwrite it, so every upload is a GET → PUT sequence:

```python
response = requests.get(url_data, headers=headers)   # 1. read the current SHA
sha = response.json()["sha"]

payload = {"message": ..., "content": encoded_content, "sha": sha, "branch": BRANCH}
put_response = requests.put(url_data, headers=headers, json=payload)   # 2. overwrite
```

The content is encoded in **base64** (required by the API), both text and binaries.

**Retry** — the `@retry_with_exponential_backoff` decorator wraps every upload function: 3
attempts, propagating the exception on the last one. It absorbs the transient network failures
typical of a domestic connection (see §20 for a flaw in the delay computation).

---

## 17. Logging

Centralised configuration in `aeroHelper.__init__`:

```python
logging.basicConfig(
    level=getattr(logging, self.configs["log"]["level"].upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, self.configs["log"]["filename"])),
        logging.StreamHandler()
    ])
```

The logger is **created once and passed to every manager** by the constructor: one
destination, one format. When the GUI is running, `setup_gui_logging_handler()` adds a third
handler (`GUILoggingHandler`), so the same message ends up in the file, on the console and in
the graphical panel.

The standalone module `ultrasonic_measurement.py` instead has its own `setup_logging()` with a
`TimedRotatingFileHandler` (rotation at midnight, 30 days of history), used only when it is run
on its own.

Message convention: prefix with the category in capitals — `AEROPONICS:`, `IDROPONICS:`,
`AMBIENT:`, `IR_CONTROLLER:`, `TANK:`, `WATER:`, `GROWTH:`, `ARDUINO:`, `ERRORI:` — so the logs
can be filtered with `grep`.

Probe errors **also** go through `ErrorRecorder.record()` (§11), which writes them into its own
file as well as into the log: in the log file they appear as `ERROR` with the source prefix
(`US_water:`, `pH:`, …).

---

## 18. Concurrency model (threads)

The system is **multi-threaded but almost lock-free**. The model:

| Thread | Started by | Loop |
|---|---|---|
| Main / Tk | `main.py` (shell) or `gui.py` | command reading or `mainloop()` |
| AEROPONICS | `start_aeroponics()` | `while self.aeroponics_job_active` |
| IDROPONICS | `start_idroponics()` | `while self.idroponics_job_active` |
| Generic jobs (N) | `start_general(name)` | `while self.general_jobs_active[name]` |
| Ambient | `start_reading()` | `while not self._stop_event.is_set()` |
| Climate | `climate.start()` | `while not self._stop_event.is_set()` |
| Tank | `tank.start_reading()` | `while not self._stop_event.is_set()` |
| **pH** | `water.start_ph_reading()` | `while not self._ph_stop_event.is_set()` |
| **EC** | `water.start_ec_reading()` | `while not self._ec_stop_event.is_set()` |
| Spectro | `spectro.start_reading()` | `while not self._stop_event.is_set()` |
| PlantGrowth | `plant_growth.start_reading()` | `while not self._stop_event.is_set()` |
| Camera | `camera.start_acquisition()` | `while not self._stop_event.is_set()` |
| Daily TH | `daily_th.start()` | `while not self._stop_event.is_set()` |
| Pump pulse | `runner()` | one-shot, dies by itself |

All of them are `daemon=True`: when the program closes they die without requiring a join.

**Two stopping mechanisms**, with different properties:

1. **Boolean flag** (`JobsManager`) + `sleep(1)` — stopping takes up to 1 second. Acceptable
   for pump jobs, whose cycle is minutes long.
2. **`threading.Event`** (`Ambient`, `Climate`, `Tank`, `Water`, `Spectro`, `PlantGrowth`,
   `Camera`, `DailyTH`) + `_stop_event.wait(interval)` — **immediate** stop. Indispensable
   here, where intervals range from 5 minutes to a whole day (`PlantGrowth`, `DailyTH`) and the
   GUI must respond to the Stop button at once.

**Almost no locks.** The shared variables are `last_T`/`last_H` (written by Ambient, read by
Climate) and the boolean flags. Correctness relies on the atomicity of reference assignments in
CPython (the GIL): reads and writes of a single `float` or `bool` cannot interleave. The code
**never does read-modify-write** on these values, which is the case where a lock would be
needed.

There are **three** exceptions, and they are all cases where the shared resource is not a value
but a device:

| Lock | Protected resource | Why |
|---|---|---|
| `ArduinoBoard._lock` (one per board) | the serial port | up to four jobs may ask the same board for a measurement; the lock serialises the **pair** command+response, otherwise two readings would swap answers (§5.7) |
| `ErrorRecorder._lock` | the `deque` and the error file | errors arrive from different threads, one per probe (§11.2) |
| `CameraManager._lock` | the `Picamera2` object | it cannot be opened twice (§14.3) |

The serial lock is **per board**, not global: with two Arduinos, readings on different boards
stay parallel. It is also the point at which the system becomes, in effect, sequential over the
probes of one board — and with a `read_pH` taking 8 seconds (§5.6), that is worth knowing: a
tank measurement falling in that window waits.

**GUI thread-safety**: Tkinter is not thread-safe; no worker thread touches the widgets. Data
travels through callbacks (`on_update`) and through the log `Queue`.

---

## 19. Formula summary

| Quantity | Formula | Where |
|---|---|---|
| Saturated vapour pressure | `es(T) = 0.6108 · exp(17.27·T / (T + 273.3))` [kPa] | `AmbientManager.VPD` |
| Actual vapour pressure | `ea = H · es(T) / 100` | `AmbientManager.VPD` |
| **VPD** | `VPD = es(T) − ea` [kPa] | `AmbientManager.VPD` |
| Irrigation modifier | `t_mod = 1/(exp(−0.2·(T−Topt)) + 1) − 0.5` | `JobsManager.T_modifier` |
| New irrigation wait | `t_new = t_old − t_old · t_mod` | `JobsManager.T_modifier` |
| Ultrasonic distance | `d = echo_duration [µs] · 0.0343 / 2` [cm] | `measureDistanceCm()` (Arduino sketch) |
| **Plant height** | `h_plant = reference − d`, clipped at 0 [cm] | `PlantGrowthManager.read_now` |
| Water level | `level = tank_height − (d − offset)` [cm] | `distance_to_water_volume` |
| Volume | `V = level · area / 1000` [L] | `distance_to_water_volume` |
| Fill | `fill% = level / tank_height · 100` | `distance_to_water_volume` |
| Reflectance | `R(λ) = target(λ) / reference(λ)` | `compute_reflectance` |
| **MCARI2** | `1.5·[2.5·(NIR−RED) − 1.3·(NIR−GREEN)] / √[(2·NIR+1)² − (6·NIR − 5·√RED) − 0.5]` | `mcari2` |

---

## 20. Anomalies found in the code

Defects spotted while writing this document. They are documented here because they concern the
formulas and logic described above; **none of them has been fixed**.

### 20.1 `T_modifier()` — variable used before being defined

`helper_aeroGreenHouse.py:288`

```python
t_new = t_new - t_new * t_modifier   # t_new is not defined yet
```

The input parameter is called `t_old`, but the line uses `t_new` on both sides: the function
would raise `UnboundLocalError` on every call. It looks as if it should be
`t_new = t_old - t_old * t_modifier`. The function currently has no callers, so the defect is
latent.

### 20.2 `VPD()` — Tetens formula constant

`helper_aeroGreenHouse.py:358`

```python
es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))
```

The standard Tetens formulation (FAO Irrigation and Drainage Paper 56) uses **237.3**, not
273.3 — a value that looks like a confusion with the Kelvin conversion constant (273.15). With
`237.3`, at T = 23 °C es ≈ 2.81 kPa; with `273.3` you get ≈ 2.55 kPa, about **9 % lower**. The
error grows with temperature. The VPD recorded so far is therefore systematically
underestimated; whether to fix it (and how to treat the history) needs deciding.

### 20.3 `_read_loop()` — logger called as a function

`helper_aeroGreenHouse.py:459`

```python
except:
    self.logger(f"AMBIENT: not able to upload the ambient data online. ...")
```

`.error` is missing: `self.logger(...)` raises `TypeError` because a `Logger` is not callable.
The exception is then caught by the outer `try`, so the loop survives, but the diagnostic
message is **never written** — an upload failure appears in the log as a generic "Errore
lettura AMBIENT: 'Logger' object is not callable", which points at the wrong place.

### 20.4 `retry_with_exponential_backoff` — the backoff is not exponential

`uploader/uploader.py:65`

```python
BASE_DELAY = 1
delay = BASE_DELAY ** (attempt - 1)   # 1**0=1, 1**1=1, 1**2=1
```

With `BASE_DELAY = 1` the power is always 1: the retries happen at a fixed 1 s spacing, not
1s/2s/4s as the docstring claims. The correct form would be `BASE_DELAY * (2 ** (attempt - 1))`.

### 20.5 `evaluate_and_send()` — misaligned command names

`ir_controller/ir_controller.py:83`

```python
if self.last_command_sent in ('Tlow', 'Hlow') and ...:   # timeout check
```

But the commands actually sent and stored are `'T_low_21'` and `'dry'`, never `'Tlow'` or
`'Hlow'`. The condition is therefore never true and the **`time_max_on` check never fires**:
the air conditioner is never switched off by the safety timeout, only by T or H coming back
below threshold. The list looks as if it should be `('T_low_21', 'dry')`.

### 20.6 The configuration is loaded twice, into two distinct dictionaries

`gui.py:37` and `helper_aeroGreenHouse.py:32`

```python
self.config = self.load_config()   # gui.py:37   -> dictionary A
self.ah = aeroHelper()             # gui.py:48   -> inside it, dictionary B
```

The same `config.yaml` is read **twice**, into two separate objects. `aeroHelper` passes
**its** one (B) to every manager by reference, so all the managers are consistent with each
other; but the GUI uses A, and the two do not talk. Concrete consequences:

- **Changes saved from the Configuration screen do not reach the managers** until the process
  is restarted: the GUI writes the file and updates A, the managers keep reading B.
- **Job changes** (`gui.py:696/718/732` add, delete and edit `gpio_pins` entries in A) never
  reach the scheduler, which lives on B.
- **Overwriting risk**: `save_config()` dumps **the whole** of A. Anyone writing to the file
  through B — as growth calibration does (§12.6) — would see their value wiped out by the first
  "Salva Configurazione". Calibration neutralises this by explicitly realigning A and the
  StringVar, but that is a patch on the symptom.

The structural cure would be to make A and B **the same object** (`self.ah` built first, then
`self.config = self.ah.configs`) and to have every reload **mutate the dictionary in place**
instead of reassigning it — `reload_config_tab:872` does `self.config = self.load_config()`,
which would break the aliasing on the first click of "Ricarica". Since the managers re-read
`self.configs` on every use, in-place mutation would give hot reloading almost for free; what
would remain outside are the values captured once (GPIO pins already configured, intervals
already frozen in the `Scheduler`s, the five attributes copied by `IRController`).

### 20.7 The Arduino contract cannot be verified at runtime

`SENSOR_SPECS` (Raspberry) and `COMMANDS[]` (Arduino) must match, but **nothing checks it**: if
the sketch loaded on the board is older than the Python code, a new command gets
`ERR:<command>` back and turns into a generic "unreliable reading", without saying that the
real cause is the firmware version.

The same applies to the ordering of the EC values: if someone enabled `O,SG,1` in the sketch
without adding the corresponding pair to `SENSOR_SPECS['EC']['values']`, `read_named()` would
keep working — while assigning the wrong names to the values.

A `version` command answering with the sketch's identifier, checked at startup, would solve
both cases.

### 20.8 Minor notes

- `measure_distance_avg()` returns the median but its name and the `n_samples` parameter
  suggest the mean — the docstring clarifies it, the name does not. Since `measure_distance_mean()`
  also exists, which really does compute the mean (§12.3), the ambiguity has got worse: the two
  functions sit side by side in the same module and their names do not say that they differ
  precisely in the statistic. `measure_distance_median()` would be the correct name for the
  first one.
- `measure_dht22()` and `_read_loop()` contain two copies of the same DHT22 reading logic.
- `eval(f"adafruit_dht.DHT22(board.D{gpio})")` uses `eval` where `getattr(board, f"D{gpio}")`
  would do.
- `AmbientManager.upload_data_on_web()` uses `os.system` with a relative path
  (`python uploader/uploader.py`): it only works if the process was started from the project
  directory.
- `main.py` looks jobs up by `name` like `gui.py`; positional indexing survives only in the
  syntax of `-save set gpio_pins.0.interval`, where it is explicit and intended.
- `WATER_*.txt` uses `\t\t\t` in the header and `\t ` between fields, like `TANK_*.txt`:
  on-screen alignment depends on the width of the values. It is readable, not strictly tabulated.
- `TankManager` imports `ultrasonic_measurement` **inside** `__init__` (deferred import) so as
  not to drag in `RPi.GPIO` when the module is only needed for the volume maths.
