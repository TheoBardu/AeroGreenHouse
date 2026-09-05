# AeroGreenHouse — Documentazione tecnica

> 🇮🇹 Italiano · [🇬🇧 English](DOCUMENTATION_EN.md) · Manuale utente: [IT](User_Manual.md) · [EN](User_Manual_EN.md) · CLI: [DUCUMENTATION_CLI.md](DUCUMENTATION_CLI.md)

Documento di riferimento sui principi di funzionamento del codice, organizzato
**dall'alto verso il basso**: dai punti di ingresso (ciò che l'utente avvia), attraverso
il coordinatore e i manager di categoria, fino alla fisica dei sensori e alle formule
implementate.

Il sistema gira su **Raspberry Pi** e gestisce una serra aeroponica/idroponica:
comanda le pompe via GPIO, legge temperatura/umidità, controlla il condizionatore via
infrarossi, monitora il livello del serbatoio e l'altezza delle piante con due sensori a
ultrasuoni, misura pH e conducibilità elettrica dell'acqua con due sonde Atlas Scientific,
calcola l'indice di vegetazione MCARI2 con uno spettrometro e pubblica i dati online.

**Le sonde non sono tutte sul Raspberry.** I due sensori a ultrasuoni e le due sonde
dell'acqua sono collegati a un **Arduino UNO**, interrogato dal Raspberry via seriale USB
con un protocollo testuale. È il tema del capitolo §5, il più dettagliato del documento.

---

## Indice

1. [Architettura generale](#1-architettura-generale)
2. [Punti di ingresso](#2-punti-di-ingresso)
3. [Il coordinatore: `aeroHelper`](#3-il-coordinatore-aerohelper)
4. [Configurazione: `config.yaml`](#4-configurazione-configyaml)
5. [**Il ponte Raspberry ↔ Arduino**](#5-il-ponte-raspberry--arduino)
6. [JobsManager — pompe e GPIO](#6-jobsmanager--pompe-e-gpio)
7. [AmbientManager — DHT22 e VPD](#7-ambientmanager--dht22-e-vpd)
8. [ClimateManager e IRController — condizionatore](#8-climatemanager-e-ircontroller--condizionatore)
9. [TankManager — livello serbatoio (HC-SR04)](#9-tankmanager--livello-serbatoio-hc-sr04)
10. [WaterManager — pH e conducibilità elettrica](#10-watermanager--ph-e-conducibilità-elettrica)
11. [ErrorRecorder — registro degli errori di lettura](#11-errorrecorder--registro-degli-errori-di-lettura)
12. [PlantGrowthManager — altezza della pianta (HC-SR04)](#12-plantgrowthmanager--altezza-della-pianta-hc-sr04)
13. [Spettrometro AS7265x — indice MCARI2](#13-spettrometro-as7265x--indice-mcari2)
14. [Camera](#14-camera)
15. [Persistenza dei dati: formati dei file](#15-persistenza-dei-dati-formati-dei-file)
16. [Elaborazione giornaliera e upload](#16-elaborazione-giornaliera-e-upload)
17. [Logging](#17-logging)
18. [Modello di concorrenza (thread)](#18-modello-di-concorrenza-thread)
19. [Riepilogo delle formule](#19-riepilogo-delle-formule)
20. [Anomalie rilevate nel codice](#20-anomalie-rilevate-nel-codice)

---

## 1. Architettura generale

Il codice è organizzato a strati. Ogni strato conosce solo quello sottostante:

```
        UTENTE
           |
   +-------+--------+
   |                |
 gui.py          main.py            <- Strato 1: punti di ingresso
 (finestra)      (shell testuale)
   |                |
   +-------+--------+
           |
      aeroHelper                    <- Strato 2: coordinatore
           |                           (config, log, GPIO, servizi condivisi)
   +-------+------------------+
   |                          |
 ErrorRecorder            ArduinoHub  <- Strato 2b: servizi condivisi
 (registro errori)   (unica porta seriale)
           |                          
   +-------+-------+-------+-------+-------+--------+---------+--------+
   |       |       |       |       |       |        |         |        |
 Jobs   Ambient Climate  Tank   Water  Spectro  PlantGrowth Camera  DailyTH   <- Strato 3:
Manager Manager Manager Manager Manager Manager   Manager   Manager Manager      manager
   |       |       |       |       |       |        |
 GPIO    DHT22   IR/piir  |       |    AS7265x      |
 pompe                    |       |    (I2C sul Pi) |
                          +-------+-----------------+
                                  |
                          ARDUINO UNO (USB)         <- Strato 4: front-end sonde
                          HC-SR04 x2 · pH · EC
   |       |       |              |        |
   +-------+-------+--------------+--------+
           |
  file .txt giornalieri  +  GROWTH.csv cumulativo  +  ERRORS_*.txt
           |
   daily_th_processor.py -> uploader.py -> GitHub -> sito web
```

Il principio guida è la **separazione tra interfaccia e logica**: `gui.py` contiene
soltanto widget e callback, mentre tutta la logica di processo (thread, scheduling,
formule, I/O sui file) vive nei manager sotto `managers_classes/`. La GUI non sa *come* si
attiva una pompa: chiama `self.ah.jobs.start_aeroponics()` e riceve un booleano.

Lo stesso principio vale un livello più in basso, ed è la novità architetturale più
importante: **nessun manager sa che esiste una porta seriale**. `TankManager` chiede
`arduino.read_float('US_water')` e riceve un numero; che dietro ci sia un Arduino UNO,
un cavo USB e la stringa `read_us,2,3` è un dettaglio confinato in `arduino_link.py` (§5).

### Chi legge cosa, e da dove

| Grandezza | Sensore | Collegato a | Letto tramite |
|---|---|---|---|
| Temperatura, umidità, VPD | DHT22 | GPIO del Raspberry | `AmbientManager` |
| Pompe aeroponica / idroponica | relè | GPIO del Raspberry | `JobsManager` |
| Condizionatore | LED IR | GPIO del Raspberry | `ClimateManager` + `piir` |
| Indice MCARI2 | AS7265x | bus I2C del Raspberry | `SpectroManager` |
| Foto | Picamera2 | CSI del Raspberry | `CameraManager` |
| **Livello serbatoio** | **HC-SR04** | **Arduino UNO** | **`ArduinoHub` → `US_water`** |
| **Altezza pianta** | **HC-SR04** | **Arduino UNO** | **`ArduinoHub` → `US_plant`** |
| **pH dell'acqua** | **Atlas Surveyor V3.0** | **Arduino UNO** | **`ArduinoHub` → `pH`** |
| **Conducibilità (EC/TDS/salinità)** | **Atlas EZO-EC (I2C)** | **Arduino UNO** | **`ArduinoHub` → `EC`** |

### Mappa dei file

| File | Ruolo |
|---|---|
| `main.py` | **Shell testuale** interattiva (vedi `DUCUMENTATION_CLI.md`) |
| `gui.py` | Pannello di controllo Tkinter (11 schermate, barra laterale a icone) |
| `helper_aeroGreenHouse.py` | **Cuore del sistema**: `aeroHelper`, che istanzia i servizi condivisi e i 9 manager |
| `managers_classes/` | I manager di categoria, uno per file |
| `managers_classes/arduino_link.py` | **Ponte seriale verso le schede Arduino** (§5) |
| `managers_classes/error_log.py` | `ErrorRecorder`: registro degli errori di lettura delle sonde (§11) |
| `managers_classes/water_manager.py` | `WaterManager`: pH ed EC come due job indipendenti (§10) |
| `managers_classes/tank_manager.py` | `TankManager`: livello del serbatoio |
| `managers_classes/plant_growth.py` | Misura dell'altezza pianta + I/O di `GROWTH.csv` |
| `managers_classes/data_config.py` | Arrotondamento dei dati di misura (decimali / cifre significative) |
| `config.yaml` | Unica fonte di verità per porte, pin, tempi e soglie |
| `arduino_modules/fish_n_plant_reading_module_atlas/*.ino` | **Sketch Arduino generale** (pH, EC, ultrasuoni) |
| `arduino_modules/fish_n_plant_reading_module/*.ino` | Sketch precedente, solo ultrasuoni (storico) |
| `arduino_modules/serial_command_arduino.py` | Script di prova del collegamento seriale (§5.9) |
| `ir_controller/ir_controller.py` | Invio comandi IR al condizionatore |
| `ir_controller/ac_remote.json` | Codifica dei comandi del telecomando (per `piir`) |
| `sensors/ultrasonic_sensor/ultrasonic_measurement.py` | Matematica del volume + salvataggio su file (la misura non passa più di qui) |
| `sensors/spectrometer/mcari2_as7265x.py` | Acquisizione spettrale e calcolo MCARI2 |
| `managers_classes/camera_manager.py` | `CameraManager`: acquisizione periodica e anteprima dal vivo |
| `camera/takePicture.py` | Wrapper CLI: acquisizione periodica |
| `camera/camera.py` | Wrapper CLI: anteprima dal vivo |
| `managers_classes/daily_th_processor.py` | `DailyTHManager`: statistiche e grafico giornalieri |
| `uploader/uploader.py` | Push di JSON/immagini su GitHub |

---

## 2. Punti di ingresso

Esistono **due modi** di avviare il sistema, mutuamente alternativi.

### 2.1 `main.py` — shell testuale

`main.py` **non è più** lo scheduler headless delle prime versioni: oggi è una **shell
interattiva** che espone le stesse funzioni della GUI da terminale, così da poter pilotare
la serra via SSH senza display.

```bash
python3 main.py
FnP> -measure ph now
FnP> -measure water start
FnP> -arduino test US_water
FnP> -errors
```

Istanzia un solo `aeroHelper` e resta in attesa di comandi; i job avviati girano in thread
daemon **dello stesso processo**, quindi continuano finché la shell resta aperta — esattamente
come accade tenendo aperta la finestra della GUI.

I comandi disponibili sono `-job`, `-measure` (`th`, `water`, `ph`, `ec`, `growth`),
`-arduino`, `-errors`, `-camera`, `-daily`, `-details`, `-save`, `help`, `exit`.
Sono documentati uno per uno, con esempi, in **[`DUCUMENTATION_CLI.md`](DUCUMENTATION_CLI.md)**:
qui non vengono ripetuti.

Come `gui.py`, `main.py` contiene **solo parsing dei comandi e stampa**: nessuna logica di
processo. Thread, scheduling, formule e I/O sui file restano nei manager.

### 2.2 `gui.py` — pannello di controllo

Istanzia `aeroHelper` una volta (`self.ah = aeroHelper()`) e costruisce una finestra con
**barra laterale a icone** e **11 schermate**:

| Icona | Schermata | Contenuto |
|---|---|---|
| ▦ | **Riepilogo** | Ultimo valore di ogni sensore con la sua data, indicatori ad arco, elenco dei soli processi attivi (§2.3) |
| ⚙ | **Configurazione** | Editing dei parametri di `config.yaml`, inclusa la card **"Schede Arduino"** (§5.8) |
| ◉ | **Processi** | Spie verde/rosso, aggiornate ogni secondo |
| ⚡ | **Job** | Treeview dei job; crea/modifica/elimina/attiva/disattiva |
| 🌡 | **Ambiente** | Letture T/H/VPD, avvio/arresto della lettura periodica; sotto, l'elaborazione giornaliera (§16.1) |
| ❄ | **Clima** | Avvio/arresto del controllo automatico AC, ultimo comando IR |
| 💧 | **H2O** | Livello del serbatoio (§9), **pH ed EC** (§10) |
| ◐ | **Spettro** | Indice MCARI2, spia dello stato della pianta, taratura, storico |
| 🌱 | **Crescita** | Altezza pianta e data dell'ultima misura, grafico dell'andamento, tabella, calibrazione (§12.6) |
| 📷 | **Camera** | Acquisizione periodica, anteprima dal vivo, ultima foto con data e ora (§14) |
| ☰ | **Log** | Console colorata dei log in tempo reale + sezione **"Errori di lettura"** (§11) |

#### Niente più `Notebook`: una tupla di schermate

Le schede orizzontali sono state sostituite da una **barra laterale a icone**. La lista dei
`notebook.add()` è diventata una **tupla dichiarativa**, `SCREENS` (gui.py:359), in cui ogni
riga è `(chiave, icona, voce di menu, titolo, sottotitolo, nome del costruttore)`:

```python
SCREENS = (
    ('riepilogo', '▦', 'Riepilogo', 'Riepilogo',
     'Ultimo valore di ogni sensore e processi in esecuzione.',
     'create_riepilogo_tab'),
    ...
)
```

`create_widgets()` la percorre una volta sola, costruisce tutte le schermate impilate nella
stessa cella di una `grid` e le tiene **tutte vive**: cambiare pagina è un `tkraise()`, non
una ricostruzione. Aggiungere una schermata significa aggiungere una riga alla tupla e un
metodo `create_*_tab`, senza toccare la costruzione della finestra.

I metodi si chiamano ancora `create_*_tab` per continuità con la versione a schede: il nome
è rimasto, il contenitore no.

#### I mattoncini visivi

L'interfaccia non usa più `ttk.LabelFrame`. Tre helper costruiscono tutto:

- `_card(parent, titolo, icona, ...)` — riquadro chiaro con bordo sottile e titolo in
  maiuscoletto: è l'unità di composizione di ogni schermata;
- `_chip(parent, testo, fg, bg)` — pill di stato (Tk non arrotonda un `Label`: è un
  rettangolo con padding generoso, che a queste dimensioni legge comunque come badge);
- gli **archi** disegnati con `create_arc` su `tk.Canvas` per i valori con fondo scala
  naturale (§2.3).

La GUI usa tre meccanismi periodici basati su `root.after()` (quindi sul thread Tk, senza
bloccare l'interfaccia):

- `process_log_queue()` — ogni **100 ms**, svuota la coda dei log e li scrive nella console;
  ogni 20 giri (**2 s**) aggiorna anche la sezione "Errori di lettura", così un errore
  compare da solo senza dover cambiare schermata;
- `refresh_status_tab()` — ogni **1 s**, interroga `get_process_states()` e colora le spie;
- `_update_clock()` — ogni **1 s**, aggiorna l'orologio nell'header.

#### Il ponte log → GUI

`GUILoggingHandler` è un `logging.Handler` personalizzato che, invece di scrivere su file,
mette il record formattato in una `queue.Queue`:

```python
def emit(self, record):
    msg = self.format(record)
    self.log_queue.put((msg, record.levelname))
```

Questo è il punto chiave del disaccoppiamento thread-safe: i thread dei manager fanno
`logger.info(...)` senza toccare Tkinter (che non è thread-safe); il thread della GUI
preleva dalla coda con `get_nowait()` e aggiorna il widget. Il livello del record
(`ERROR`, `WARNING`, `DEBUG`, altro) seleziona il tag di colore del testo.

#### Lettura dello stato dei processi

`get_process_states()` costruisce l'elenco delle spie interrogando direttamente i flag dei
manager: i job GPIO da `gpio_pins` (saltando le voci `what_type: sensor`, che non sono
processi) e poi, uno per uno, i manager di categoria:

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

**pH ed EC compaiono come due voci distinte** perché sono due job separati (§10): si
avviano, si fermano e falliscono in modo indipendente.

### 2.3 La scheda Riepilogo

È la **prima** schermata: risponde alla domanda "come sta la serra?" senza visitare le altre
dieci. Una griglia 3 colonne × 4 righe:

```
┌───────────────────────────────────────────────┐
│  Ambiente:  temperatura · umidità · VPD       │  (3 archi, una sola lettura DHT22)
├───────────────────────────┬───────────────────┤
│  H2O:  pH · conducibilità │    Serbatoio      │
│  (2 archi, 2 date)        │  arco riempimento │
├───────────────────────────┼───────────────────┤
│      Indice MCARI2        │     Crescita      │
│       arco 0-1            │     altezza       │
├───────────────────────────┴───────────────────┤
│  Processi Attivi (solo quelli in esecuzione)  │
└───────────────────────────────────────────────┘
```

Ogni blocco riporta la **data della misura**: un valore senza data non dice se è di un minuto
o di tre giorni fa, e con cadenze che vanno dai 5 minuti (ambiente) a un giorno (crescita) la
differenza è sostanziale. Il blocco H2O ha **due date distinte**, una per colonna
(`data_per_colonna=True`): pH ed EC sono due job separati con intervalli propri, e mostrarne
una sola farebbe credere che l'altra sonda sia stata letta nello stesso istante.

**Da dove arrivano i valori.** Solo dai manager, mai da letture fatte dalla GUI: `last_result`
per ambiente (§7.4) e serbatoio (§9.6), `last_ph` / `last_ec` per l'acqua (§10),
`history[0]` per lo spettrometro (il più recente è in testa) e `history[-1]` per la crescita
(ordine cronologico crescente — le due liste hanno ordinamenti opposti, attenzione). Poiché
tutti rileggono l'ultimo dato dai file all'avvio, **la schermata è popolata già alla prima
apertura**, prima ancora di avviare una lettura e senza interrogare l'Arduino.

**Arco o numero.** L'arco (`create_arc` su `tk.Canvas`, come per il grafico della crescita in
§12.8: niente matplotlib) si usa dove esiste un **fondo scala di riferimento**: umidità
0-100%, riempimento 0-100%, MCARI2 0-1, e per pH ed EC la scala costruita attorno alle soglie
configurate (`ph_min`/`ph_max`, `ec_min`/`ec_max`), con le **bande colorate** che segnano
l'intervallo desiderato. L'altezza della pianta non ha un fondo scala fisico ovvio e resta un
numero. Il serbatoio colora l'arco per fascia (rosso sotto il 25%, arancione sotto il 50%),
l'MCARI2 riusa `MCARI2_COLORS`.

**Costo.** Stessa disciplina di §2.2, e per lo stesso motivo: i widget si costruiscono una
volta sola, poi il tick da 1 s tocca solo i valori. Gli archi si ridisegnano **soltanto se il
valore è cambiato** (cache `_riep_cache`, confronto in `_cambiato()`) e l'elenco dei processi
solo se cambia (`_riep_active_keys`), quindi a serra ferma un tick non disegna nulla.

---

## 3. Il coordinatore: `aeroHelper`

`aeroHelper.__init__()` esegue in sequenza:

1. **Carica la configurazione** — `load_config('config.yaml')` con `yaml.safe_load`.
2. **Configura il logging** — `logging.basicConfig` con due handler: file
   (`<log.directory>/<log.filename>`) e console.
3. **Inizializza la GPIO** — `initialize_gpio(configs)`, una sola volta per l'intero processo.
4. **Crea i due servizi condivisi** — e li crea **prima** dei manager, perché i manager che
   hanno sonde su Arduino li ricevono nel costruttore:

```python
self.errors  = ErrorRecorder(self.configs, self.logger)   # §11
self.arduino = ArduinoHub(self.configs, self.logger)      # §5
```

5. **Istanzia i nove manager**, passando a ciascuno `configs`, `logger` e ciò che gli serve:

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

Si legge la struttura del sistema dalla firma dei costruttori: chi riceve `self.gpios` parla
con i pin del Raspberry, chi riceve `self.arduino` parla con una scheda esterna, chi riceve
`self.errors` può fallire in un modo che l'utente deve vedere.
`ClimateManager` riceve invece l'istanza di `AmbientManager`: è così che il controllo del
condizionatore legge le ultime misure di T/H senza duplicare l'accesso al sensore.

6. **Collega l'upload aggregato** — `self.ambient.extra_data_provider = self.latest_extra_data`
   (§16.2).
7. **Alias di retrocompatibilità** — `self.runner`, `self.pump_aerophonics`,
   `self.pump_idrophonics` puntano ai metodi di `jobs`, per il codice scritto prima della
   suddivisione in manager.

### `latest_extra_data()` — una fotografia sola della serra

L'upload periodico parte da `AmbientManager` perché è lui ad avere la cadenza più fitta.
Perché il sito riceva **uno stato coerente** invece di un upload separato per ogni sonda,
`aeroHelper` gli passa una funzione che raccoglie gli ultimi valori noti di tutte le altre
grandezze:

```python
dati['water_level_cm'], dati['volume_L'], dati['fill_percent']  # da tank.last_result
dati['ph']                                                       # da water.last_ph
dati['ec_us_cm'], dati['tds_ppm'], dati['salinity_psu']          # da water.last_ec
dati['h_plant_cm']                                               # da plant_growth.history[-1]
dati['errors'] = self.errors.recent(10)                          # §11
```

**Ogni voce è opzionale**: una sonda mai letta — o non ancora installata — semplicemente non
compare, e l'uploader la omette dal JSON invece di pubblicare uno zero che il sito
mostrerebbe come una misura vera.

### Inizializzazione GPIO

```python
self.gpios.setmode(GPIO.BCM)      # numerazione BCM, non fisica
self.gpios.setwarnings(False)
for g in config["gpio_pins"]:
    if g["what_type"] == "sensor":
        self.gpios.setup(g["pin"], self.gpios.IN)   # sensori -> input
        continue
    self.gpios.setup(g["pin"], self.gpios.OUT)
    self.gpios.output(g["pin"], True)               # <- pin ALTO = relè SPENTO
```

**Logica active-low.** La scheda relè usata è attiva a livello basso: `output(pin, False)`
**accende** il carico, `output(pin, True)` lo **spegne**. Per questo l'inizializzazione porta
tutti i pin a `True` — cioè li spegne — evitando che le pompe partano all'avvio.
Questa convenzione, invertita rispetto all'intuizione, è la stessa in tutto il codice.

Infine viene configurato in uscita il pin TX dell'infrarosso (`ir_control.tx_pin`).

Nota: nessun pin GPIO è più riservato agli HC-SR04. I due sensori a ultrasuoni sono
sull'Arduino (§5), quindi i loro pin non compaiono in `initialize_gpio`.

### Chiusura

`cleanup_gpios()` chiude **anche** le porte seriali, non solo i pin:

```python
def cleanup_gpios(self):
    self.arduino.close_all()
    self.gpios.cleanup()
```

Lasciare una porta seriale aperta impedirebbe al processo successivo di riaprirla, ed è un
errore che si manifesta solo al secondo avvio — cioè nel momento peggiore.

---

## 4. Configurazione: `config.yaml`

Tutti i parametri operativi stanno in un unico file, letto all'avvio.

```yaml
T_var:                  # temperatura/umidità ottimali di riferimento
  Topt: 18.0
  Hopt: 65.0
dht22:
  pin: 27               # pin dati del sensore T/H (GPIO del Raspberry)
  read_interval: 300    # [s] intervallo tra le letture
  save: true
  saving_dir: /home/fishnplants/Desktop/data/TH/
  max_retries: 5        # tentativi prima di dichiarare fallita una lettura
log:
  directory: /home/fishnplants/Desktop/
  filename: FnP_AeroGreenHouse
  level: INFO
config_reload_interval: 4
gpio_pins:
- name: AEROPONICS
  pin: 19
  what_type: pump
  interval: 1200        # [min] tempo di attesa tra due irrigazioni
  on_time: 5            # [s]   durata dell'irrigazione
- name: IDROPONICS
  pin: 12
  what_type: pump
  interval: 29          # [min]
  on_time: 65           # [s] tempo MASSIMO di pompaggio
- name: MOISTURE
  pin: 26
  what_type: sensor     # -> configurato come INPUT, non è un processo
spectro:
  read_interval: 3600   # [s]
  saving_dir: /home/fishnplants/Desktop/data/SPECTRO/
  history_len: 10
plant_growth:
  read_interval_days: 1      # [giorni] ogni quanto misurare l'altezza
  n_samples: 3               # letture da mediare
  reference_height_cm: 70.0  # distanza sensore -> camera radicale a pianta assente
  decimals: 1                # cifre da tenere dalla misura
  save: true
  saving_dir: /home/fishnplants/Desktop/data/GROWTH/
  history_len: 30            # punti mostrati in grafico e tabella
camera:
  separation_hours: 2   # [ore] tempo tra uno scatto e il successivo
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
  time_max_on: 10.0     # [min] tempo massimo di accensione continua dell'AC
  control_time: 5.0     # [min] periodo del ciclo di valutazione
  T_max: 26.0           # [°C] soglia di intervento sulla temperatura
  H_max: 65.5           # [%]  soglia di intervento sull'umidità

# --- Schede Arduino collegate via USB (§5) --------------------------------
arduino:
  baudrate: 9600        # deve combaciare con Serial.begin() dello sketch
  timeout: 15           # [s] attesa massima di una risposta
  reset_delay: 2        # [s] pausa dopo l'apertura della porta (l'UNO si resetta)
  boards:
  - name: Board1        # solo descrittivo, compare nei log e nella GUI
    port: /dev/ttyACM0  # porta seriale
    enabled: true       # false = scheda ignorata, senza cancellarla dal file
    sensors:            # QUALI sonde ci sono e SU QUALI PIN
      pH:       {pin: A0}
      EC:       {address: 100}
      US_water: {trig: 2, echo: 3}
      US_plant: {trig: 4, echo: 5}

water:                  # §10
  ph_read_interval: 1800   # [s]
  ec_read_interval: 1800   # [s]
  ph_min: 5.5              # soglie di allarme (non di validità)
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
  water_low_threshold_l: 3.0   # [L] soglia di riserva
  read_interval: 900           # [s]
  n_samples: 5                 # letture di cui prendere la mediana
  saving_dir: /home/fishnplants/Desktop/data/TANK/

error_log:              # §11
  saving_dir: /home/fishnplants/Desktop/data/ERRORS/
  history_len: 200      # errori tenuti in memoria per la GUI
```

**Attenzione alle unità di misura**, non uniformi e fonte di confusione:
`interval` (job) è in **minuti**, `on_time` in **secondi**, `dht22.read_interval`,
`water.*_read_interval`, `tank.read_interval` e `spectro.read_interval` in **secondi**,
`ir_control.control_time` e `time_max_on` in **minuti**,
`plant_growth.read_interval_days` in **giorni** e `camera.separation_hours` in **ore** —
quattro unità di tempo diverse nello stesso file. I campi aggiunti più di recente
portano l'unità nel nome (`_days`, `_hours`) proprio per questo; i più vecchi no.

Il campo `what_type` discrimina il comportamento: `pump` → pin in uscita e job avviabile;
`sensor` → pin in ingresso, escluso dall'elenco dei processi.

**Soglie di allarme ≠ range di validità.** `ph_min`/`ph_max` e `ec_min`/`ec_max` dicono
quando la soluzione nutritiva va corretta: una misura fuori da questi valori è **valida e
viene salvata**, con un warning. I range di validità fisici (pH 0–14, EC 0–200000 µS/cm,
distanza 2–400 cm) sono invece costanti nel codice, e una misura fuori da quelli viene
**scartata** perché significa che la sonda è scollegata o rotta.

**I pin delle sonde su Arduino non stanno più nelle sezioni dei rispettivi manager**: né
`tank` né `plant_growth` hanno più `trig_pin`/`echo_pin`. Vivono tutti in
`arduino.boards[].sensors`, perché è lì che serve saperli — sono ciò che il Raspberry
scrive dentro il comando seriale (§5.4). La GUI lo dice esplicitamente, con una nota nelle
card di configurazione di serbatoio e crescita.

---

## 5. Il ponte Raspberry ↔ Arduino

Quattro sonde su otto non sono collegate al Raspberry: stanno su un **Arduino UNO**, unito
al Pi da un **solo cavo USB**, che porta insieme alimentazione e comunicazione seriale.
Il Raspberry chiede una misura scrivendo una riga di testo; l'Arduino la esegue e risponde
con un'altra riga. Tutto qui: nessun protocollo binario, nessuna libreria di terze parti fra
i due, niente che non si possa leggere con un terminale seriale.

Questo capitolo descrive **integralmente** quel dialogo: perché esiste, chi comanda, quali
comandi esistono, come sono fatte le risposte e cosa succede quando qualcosa va storto.

I due lati del ponte sono:

| Lato | File | Ruolo |
|---|---|---|
| Raspberry | `managers_classes/arduino_link.py` | compone i comandi, li invia, interpreta le risposte |
| Arduino | `arduino_modules/fish_n_plant_reading_module_atlas/fish_n_plant_reading_module_atlas.ino` | riceve i comandi, esegue le misure, risponde |

### 5.1 Perché un Arduino

Tre motivi, tutti hardware.

1. **Il Raspberry non ha convertitore analogico-digitale.** La sonda di pH Atlas Surveyor
   restituisce una **tensione**: senza ADC il Pi non può leggerla. L'Arduino UNO ne ha sei
   canali (A0–A5) integrati.
2. **`pulseIn` vuole tempi reali.** La misura HC-SR04 consiste nel cronometrare un impulso
   lungo poche centinaia di microsecondi. In Python su Linux, un cambio di contesto del
   sistema operativo nel mezzo del conteggio falsa la misura; su Arduino, che esegue un solo
   programma senza sistema operativo, `pulseIn()` è affidabile al microsecondo.
3. **I pin del Pi sono a 3.3 V e l'ECHO dell'HC-SR04 esce a 5 V.** Sul Pi serviva un
   partitore di tensione per ogni sensore; sull'Arduino, che lavora nativamente a 5 V, non
   serve nulla.

C'è anche un motivo di struttura: le sonde stanno **fisicamente** vicine all'acqua e alle
piante, il Raspberry no. Un solo cavo USB verso una scatola che contiene tutte le sonde è più
semplice — e più affidabile — di otto fili lunghi che tornano al Pi.

### 5.2 Un modulo solo apre la seriale

`arduino_link.py` è **l'unico file del progetto che importa `pyserial`**. I manager non lo
sanno e non devono saperlo:

```python
distanza = self._arduino.read_float('US_water')   # TankManager
valori   = self._arduino.read_named('EC')         # WaterManager
```

Il vantaggio non è estetico. Significa che sostituire l'Arduino con un'altra scheda — o
tornare a leggere un sensore direttamente dal Pi — tocca **un solo file**, e che i manager
restano testabili sostituendo l'hub con un oggetto finto.

### 5.3 Chi decide quando misurare: il Raspberry

**Nello sketch Arduino non c'è alcuna temporizzazione.** Non ci sono intervalli, non ci sono
timer, non c'è un ciclo di misura. Il `loop()` fa una cosa sola: accumula i caratteri che
arrivano dalla seriale finché non incontra un fine riga, e allora esegue il comando.

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

Il ciclo **non si blocca** in attesa di dati: se non è arrivato nulla, a questo giro non fa
niente e ricontrolla al successivo.

Tutta la politica temporale resta sul Raspberry, nei thread dei manager
(`water.ph_read_interval`, `water.ec_read_interval`, `tank.read_interval`,
`plant_growth.read_interval_days`). La conseguenza pratica è importante: **cambiare la
frequenza di una misura non richiede di ricompilare l'Arduino**, basta modificare
`config.yaml`.

Vale anche per il **numero di campioni**: `tank.n_samples: 5` significa che il Raspberry
manda cinque volte `read_us,2,3` e ne calcola la mediana, non che l'Arduino ripeta la misura
cinque volte. L'Arduino resta un esecutore elementare — una richiesta, una misura, una
risposta — e ogni scelta statistica resta configurabile dal Pi.

### 5.4 I pin viaggiano dentro il comando

È la scelta di progetto più importante dello sketch. I pin **non sono cablati nel codice
Arduino**: arrivano dentro il comando, come argomenti separati da virgola.

```
read_us,2,3      ->  misura sull'HC-SR04 collegato ai pin 2 (TRIG) e 3 (ECHO)
read_us,4,5      ->  misura sull'HC-SR04 collegato ai pin 4 e 5
```

Un **unico comando** `read_us` serve quindi *tutti* i sensori a ultrasuoni della scheda: a
distinguere il serbatoio dalla crescita è la coppia di pin, non il comando. Aggiungere un
terzo HC-SR04 non richiede una riga di codice Arduino, solo una voce in `config.yaml`.

Conseguenza operativa: **cambiare cablaggio significa modificare `config.yaml` sul
Raspberry, non riprogrammare la scheda.** Chi monta l'impianto non ha bisogno dell'IDE
Arduino.

### 5.5 Il protocollo

#### Formato della richiesta

```
<nome_comando>[,<arg1>[,<arg2>...]]\n
```

Il nome è separato dagli argomenti dalla **prima virgola**; gli argomenti fra loro ancora da
virgole. La riga termina con `\n` (lo sketch accetta anche `\r`).

#### Formato della risposta

```
<comando completo>:<valore>
```

Cioè **l'Arduino rieccheggia per intero il comando ricevuto**, poi due punti, poi il valore.

```
read_pH,A0     ->  read_pH,A0:6.87
read_EC,100    ->  read_EC,100:1250.0,625.0,0.62
read_us,2,3    ->  read_us,2,3:12.40
```

Due regole rendono il formato non ambiguo:

- **i due punti sono riservati** al separatore comando/valore;
- **gli argomenti usano la virgola**, mai i due punti.

Per questo il lato Raspberry può fare `risposta.split(':')` e pretendere **esattamente due
parti**; se ne trova un numero diverso, la risposta è malformata e viene scartata.

#### Perché l'eco

L'eco non è una ridondanza decorativa: è il **controllo di sincronismo** del canale. Sonde
diverse sono lette da thread diversi; se per qualsiasi motivo il buffer seriale si
disallineasse, il Pi rischierebbe di attribuire alla crescita la distanza del serbatoio.

```python
if comando_ricevuto.lower() != command.lower():
    self._invalidate()          # butta via la connessione
    raise ArduinoError(sensor_key, "Risposta fuori sincrono ...")
```

Confrontando l'eco con il comando inviato, un disallineamento diventa un errore esplicito
invece di un dato sbagliato — che sarebbe molto peggio, perché nessuno se ne accorgerebbe.
Alla constatazione dell'anomalia la connessione viene **invalidata**: il tentativo successivo
riapre la porta e riparte da un buffer pulito.

#### Tabella completa dei comandi

| Comando inviato | Argomenti | Risposta di esempio | Valori restituiti |
|---|---|---|---|
| `read_pH,<pin>` | pin analogico `A0`–`A5` (default `A0`) | `read_pH,A0:6.87` | pH, 2 decimali |
| `read_EC,<indirizzo>` | indirizzo I2C 1–127 (default 100) | `read_EC,100:1250.0,625.0,0.62` | EC [µS/cm], TDS [ppm], salinità [PSU] |
| `read_us,<trig>,<echo>` | due pin digitali 2–13, diversi fra loro | `read_us,2,3:12.40` | distanza [cm], 2 decimali |
| `CAL,7` | — | `MID CALIBRATED` | calibra il punto medio del pH (tampone 7) |
| `CAL,4` | — | `LOW CALIBRATED` | calibra il punto basso (tampone 4) |
| `CAL,10` | — | `HIGH CALIBRATED` | calibra il punto alto (tampone 10) |
| `CAL,CLEAR` | — | `CALIBRATION CLEARED` | azzera la calibrazione pH |
| `ECCAL,dry` | — | risposta testuale dell'EZO | punto a secco (sonda EC asciutta) |
| `ECCAL,low,<valore>` | es. `12880` | risposta testuale dell'EZO | punto basso con la soluzione indicata |
| `ECCAL,high,<valore>` | es. `80000` | risposta testuale dell'EZO | punto alto |
| `ECCAL,clear` | — | risposta testuale dell'EZO | azzera la calibrazione EC |
| `ECCMD,<comando EZO>` | es. `ECCMD,K,1.0` | risposta testuale dell'EZO | comando EZO grezzo (passthrough) |

I comandi di calibrazione **non seguono** il formato `<comando>:<valore>`: restituiscono un
messaggio testuale di conferma. Per questo `processCommand()` li intercetta prima del
dispatch generale, e per questo `arduino_link.py` non li usa — la calibrazione si fa da un
terminale seriale o con `serial_command_arduino.py` (§5.9), non dai job automatici.

#### Le tre risposte di errore

| Valore | Significato | Cause tipiche |
|---|---|---|
| `ERR` | lettura non attendibile | sonda scollegata o in aria; nessun eco entro `US_TIMEOUT_US` (40 ms ≈ 6.8 m); tensione pH fuori 150–3100 mV; EZO-EC che non risponde o che risponde con un messaggio di stato invece che con un numero |
| `ERRPIN` | pin o indirizzo non utilizzabile | pin fuori da A0–A5 / D2–D13, TRIG uguale a ECHO, indirizzo I2C fuori 1–127, argomento mancante o non numerico |
| `ERR:<comando>` | comando sconosciuto | comando scritto male o non ancora implementato |

`ERR:<comando>` ha la forma invertita rispetto agli altri due (l'errore precede i due punti)
proprio perché il comando non è stato riconosciuto: non essendoci un comando valido da
rieccheggiare, non c'è nulla da mettere davanti.

La distinzione fra `ERR` ed `ERRPIN` è deliberata, ed è ciò che permette alla GUI di dare
due messaggi diversi: `ERRPIN` è **un errore di configurazione** (l'utente ha scritto pin
sbagliati e deve correggerli in Configurazione), `ERR` è **un problema fisico** (la sonda va
controllata).

#### Validazione dei pin: `parsePin()`

```cpp
if (t.charAt(0) == 'A') { ... return A0 + idx; }   // A0..A5
if (pin < 2 || pin > 13) return -1;                // D2..D13
```

Due rifiuti espliciti meritano attenzione:

- **D0 e D1 sono rifiutati** perché sono la seriale USB verso il Raspberry: usarli come pin
  di un sensore farebbe cadere la comunicazione, cioè romperebbe il canale con cui l'errore
  andrebbe segnalato.
- **Un token non valido diventa `-1`, che diventa `ERRPIN`.** Senza questo controllo un
  refuso in `config.yaml` porterebbe a un `digitalWrite()` su un pin arbitrario — che
  potrebbe essere quello di un attuatore. Un errore di battitura non deve poter accendere
  una pompa.

### 5.6 Come sono fatte le tre misure, lato Arduino

#### `read_pH,<pin>` — la più lenta

La sonda Atlas Surveyor dichiara un tempo di risposta del 95 % in 1 s. Lo sketch lo rispetta
letteralmente: media la tensione su una **finestra di 5 secondi**, un campione al secondo.

```cpp
const unsigned long PH_READ_WINDOW_MS    = 5000;
const unsigned long PH_SAMPLE_INTERVAL_MS = 1000;
const int PH_N_SAMPLES = PH_READ_WINDOW_MS / PH_SAMPLE_INTERVAL_MS;   // 5
```

La media serve a due cose insieme: **aspettare** che lo strumento si assesti e **ridurre il
rumore**. Non equivale ai campioni ravvicinati che `read_voltage()` fa già al proprio
interno, che sono tutti nello stesso istante e quindi non danno alcuna informazione sul
transitorio.

Poi controlla che la tensione media stia nel range fisico di uscita del Surveyor
(265 mV ≈ pH 14, 3000 mV ≈ pH 0), con un margine: **fuori da 150–3100 mV risponde `ERR`**,
perché la sonda è quasi certamente scollegata o fuori scala.

Infine converte in pH con la libreria ufficiale — che usa i punti di calibrazione salvati in
**EEPROM**, non una retta fissa — e media **tre letture distanziate di 1 s**:

```cpp
float ph1 = pH_probe.read_ph(); delay(1000);
float ph2 = pH_probe.read_ph(); delay(1000);
float ph3 = pH_probe.read_ph();
float ph = (ph1 + ph2 + ph3) / 3.0;
```

**Una `read_pH` occupa quindi l'Arduino per circa 8 secondi.** È il motivo per cui il timeout
seriale lato Raspberry è di 15 s e non di 2 (§5.7).

Piccola ottimizzazione: l'oggetto `Surveyor_pH` viene ricostruito **solo se il pin richiesto
è cambiato** (`usePHPin`), perché `begin()` rilegge la EEPROM e non ha senso rifarlo ad ogni
misura.

#### `read_EC,<indirizzo>` — tre valori in una risposta

Il circuito Atlas EZO-EC è interrogato **via I2C** (SDA su A4, SCL su A5), non via UART come
nell'esempio ufficiale di Atlas. La scelta è motivata nello sketch, e sono due motivi
concreti:

1. `SoftwareSerial` **disabilita gli interrupt mentre riceve**, e questo corromperebbe il
   `pulseIn()` dei sensori a ultrasuoni;
2. l'I2C usa A4/A5 e **non sottrae pin digitali**, che devono restare tutti liberi di essere
   assegnati da `config.yaml`.

In più la sonda si indirizza per **indirizzo** e non per pin, quindi in futuro si possono
mettere più circuiti EZO sullo stesso bus.

In `setup()` lo sketch decide una volta per tutte quali grandezze l'EZO deve includere nella
risposta:

```cpp
EC_probe.send_cmd("O,EC,1");    // conducibilità
EC_probe.send_cmd("O,TDS,1");   // solidi disciolti totali
EC_probe.send_cmd("O,S,1");     // salinità
EC_probe.send_cmd("O,SG,0");    // gravità specifica: DISATTIVATA
```

Sono queste quattro righe a determinare che la risposta contenga **esattamente la terna
`EC,TDS,SAL`** attesa dal Raspberry: cambiarle senza aggiornare `SENSOR_SPECS['EC']['values']`
disallineerebbe i due lati.

La misura è il comando `R`, seguito dai 600 ms di elaborazione dichiarati da Atlas. Due
controlli prima di accettarla: `get_error() == SUCCESS`, e **il primo carattere della
risposta deve essere una cifra** — se non lo è, l'EZO ha risposto con un messaggio di stato e
non con una misura. In entrambi i casi: `ERR`.

I tre valori sono già nel formato `EC,TDS,SAL` e vengono **rimandati così come sono**, senza
riformattarli, per non perdere cifre significative.

#### `read_us,<trig>,<echo>` — la più semplice

```cpp
digitalWrite(trigPin, LOW);  delayMicroseconds(2);
digitalWrite(trigPin, HIGH); delayMicroseconds(10);   // impulso da 10 µs (datasheet)
digitalWrite(trigPin, LOW);
long duration = pulseIn(echoPin, HIGH, US_TIMEOUT_US);
if (duration == 0) return -1.0;                       // nessun eco -> ERR
return (duration * 0.0343) / 2.0;
```

**Formula:**

```
distanza [cm] = durata_echo [µs] × 0.0343 [cm/µs] / 2
```

`0.0343 cm/µs` è la velocità del suono in aria (~343 m/s a 20 °C); la divisione per 2 elimina
il percorso di ritorno. Il timeout di 40 ms corrisponde a circa 6.8 m: oltre non c'è eco
utile, e senza timeout un eco mai ricevuto bloccherebbe l'Arduino per sempre.

I `pinMode()` si fanno **qui e non in `setup()`** proprio perché i pin non sono più noti a
tempo di compilazione.

### 5.7 Il lato Raspberry: `arduino_link.py`

Tre livelli, dal più concreto al più astratto.

#### `SENSOR_SPECS` — la tabella dei sensori

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

È il **punto di estensione unico** del ponte. Per ogni sensore dichiara:

- `command` — il nome del comando Arduino, **fisso**: non è modificabile dall'utente perché
  deve combaciare con la tabella `COMMANDS[]` dello sketch;
- `args` — le triple `(chiave in config.yaml, etichetta per la GUI, default)`: sono i valori
  che l'utente compila e che finiscono dentro il comando, **in quest'ordine**;
- `values` — le coppie `(nome del valore, unità)` che la risposta contiene, **in quest'ordine**;
- `label` — il nome parlante usato nei messaggi d'errore.

Notare che `US_water` e `US_plant` sono due **chiavi** diverse che condividono lo stesso
`command`: la differenza è tutta negli argomenti. È l'esatto riflesso, lato Pi, della scelta
descritta in §5.4.

**Aggiungere una voce qui rende il sensore automaticamente disponibile sia nella GUI sia
nella CLI**: nessuna delle due ha un elenco proprio di sensori, entrambe leggono
`SENSOR_KEYS` e `SENSOR_SPECS`. La GUI costruisce da `args` i campi del pannello di
configurazione, e da `values` le etichette con le unità di misura.

> **Regola di manutenzione.** La tabella `COMMANDS[]` nello sketch e `SENSOR_SPECS` in
> `arduino_link.py` sono le due metà dello stesso contratto: un comando aggiunto da un lato
> e non dall'altro non serve a niente. Vanno modificate insieme.

`build_command()` è l'unico posto del progetto che sa **comporre** una stringa di comando:

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

Un parametro mancante diventa un `ArduinoError` **prima** che qualsiasi cosa venga scritta
sulla seriale, con un messaggio che dice all'utente dove compilarlo.

#### `ArduinoBoard` — una scheda, una porta

Gestisce la porta seriale di **una** scheda e le sonde che le sono assegnate.

**Connessione pigra.** La porta non si apre all'avvio del programma, ma alla prima lettura, e
poi resta aperta:

```python
def _ensure_open(self, sensor_key=None):
    if self._serial is not None and self._serial.is_open:
        return self._serial
    self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
    time.sleep(self.reset_delay)          # <- 2 secondi
    self._serial.reset_input_buffer()
```

I due secondi di pausa non sono prudenza generica: **aprire la porta USB resetta l'Arduino
UNO**. È un comportamento normale della scheda, dovuto al segnale DTR della USB-seriale. Lo
sketch riparte da `setup()`, e serve qualche secondo prima che sia di nuovo in ascolto: senza
la pausa, il primo comando arriverebbe mentre l'Arduino si sta ancora riavviando e andrebbe
perso. Subito dopo si svuota il buffer d'ingresso, dove intanto è finito il messaggio di
benvenuto stampato da `setup()` (`"FnP fish_n_plant_reading_module pronto."` e le righe di
stato di pH ed EC).

**Autoriparazione.** Se il cavo viene staccato, la scrittura o la lettura sollevano
`serial.SerialException`; la connessione viene invalidata (`_invalidate()`, che è solo un
`close()`) e il tentativo successivo la riapre da solo. **Non serve riavviare il programma**
per rimettere in servizio una scheda ricollegata.

**Timeout.** `DEFAULT_TIMEOUT_S = 15`, dimensionato sul comando più lento: una `read_pH`
impegna l'Arduino per circa 8 s (§5.6). Un timeout di 2 s — ragionevole per un `read_us` —
farebbe fallire *sistematicamente* ogni lettura di pH, con l'aggravante di lasciare la
risposta nel buffer e disallineare tutte le letture successive.

**Un lock per scheda.**

```python
self._lock = threading.Lock()
...
with self._lock:
    conn.write((command + '\n').encode('utf-8'))
    risposta = conn.readline().decode('utf-8', errors='replace').strip()
```

pH, EC, serbatoio e crescita sono **quattro job su quattro thread distinti** che possono
condividere la stessa scheda. Il lock serializza la **coppia** comando+risposta, non le due
operazioni separatamente: senza, due letture concorrenti si scambierebbero le risposte.
È l'unica sezione critica esplicita dell'intero sistema insieme a quella della camera (§18).

Il lock è **per scheda**, non globale: con due Arduino, due letture su schede diverse restano
parallele.

#### `ArduinoHub` — tutte le schede, indicizzate per sensore

Il resto del programma chiede `hub.read_float('US_water')`. Quale scheda risponda, su quale
porta, con quali pin, è un dettaglio che vive qui e in `config.yaml`.

`reload()` ricostruisce l'indice `{sensore: scheda}` dalla configurazione corrente, e gestisce
due casi anomali **senza fermare il programma**:

- **sensore sconosciuto** (una chiave che non sta in `SENSOR_SPECS`) → warning, voce ignorata;
- **stesso sensore su due schede** → warning, **vince la prima**. È quasi certamente un errore
  di configurazione, ma far cadere l'avvio della serra per questo sarebbe sproporzionato.

`reload()` è chiamata dalla GUI **dopo ogni salvataggio della configurazione**: cambiare
porta, pin o abilitazione di una scheda ha effetto subito, senza riavviare il programma.

Quattro modi di leggere, tutti costruiti sul precedente:

| Metodo | Restituisce | Usato da |
|---|---|---|
| `read_raw(k)` | la stringa grezza, es. `'1250.0,625.0,0.62'` | diagnostica, pulsante "Prova" della GUI |
| `read_values(k)` | lista di `float` | uso interno |
| `read_float(k)` | il primo valore come `float` | `TankManager`, `PlantGrowthManager`, pH |
| `read_named(k)` | `dict` `{nome: float}` secondo `values` | `WaterManager` per l'EC |

`read_named('EC')` restituisce `{'ec_us_cm': 1250.0, 'tds_ppm': 625.0, 'salinity_psu': 0.62}`:
i nomi vengono da `SENSOR_SPECS`, non sono ripetuti nel manager. Se i valori ricevuti sono
**meno** di quelli attesi, è un `ArduinoError` — meglio nessuna misura che tre grandezze
disallineate.

### 5.8 Il percorso completo di una lettura

```
TankManager._read_loop()                        [thread del serbatoio]
  └─ ripete n_samples volte:
     arduino.read_float('US_water')
       └─ ArduinoHub._board_or_raise('US_water')   -> Board1  (o ArduinoError)
          └─ ArduinoBoard.read_sensor('US_water')
             ├─ build_command('US_water', {'trig': 2, 'echo': 3})  ->  "read_us,2,3"
             └─ send_command("read_us,2,3")
                └─ [LOCK]
                   ├─ _ensure_open()      apre la porta se serve (+2 s di reset)
                   ├─ write("read_us,2,3\n")
                   └─ readline()          <- attende max 15 s
                                          ...   [ARDUINO: pulseIn sui pin 2 e 3]
                   risposta: "read_us,2,3:12.40"
                └─ [UNLOCK]
             ├─ split(':')  -> 2 parti?              altrimenti ArduinoError
             ├─ eco == comando inviato?              altrimenti invalida + ArduinoError
             ├─ valore == 'ERRPIN'?                  -> ArduinoError "pin non validi"
             ├─ valore == 'ERR'?                     -> ArduinoError "lettura non attendibile"
             └─ "12.40"
       └─ float("12.40") -> 12.40
  ├─ median(letture)  -> 12.40 cm
  ├─ controllo range operativo 2-400 cm
  ├─ distance_to_water_volume() -> livello, volume, riempimento    (§9.4)
  ├─ save_data() -> TANK_2026_09_05.txt
  └─ on_update() -> GUI
```

E il percorso simmetrico, quando qualcosa va storto:

```
ArduinoError(sensor, "messaggio già in italiano, già leggibile")
  └─ TankManager._measure_distance()  raccoglie l'ultimo errore
     └─ ErrorRecorder.record('US_water', "Non è stato possibile leggere ... : <messaggio>")
        ├─ deque in memoria    -> sezione "Errori di lettura" della GUI (§11)
        ├─ ERRORS_2026_09_05.txt
        ├─ logger.error(...)   -> file di log + console + console della GUI
        └─ latest_extra_data()['errors'] -> JSON -> sito web
```

Due dettagli di questo percorso non sono casuali.

**Il messaggio d'errore è scritto una volta sola, in `arduino_link.py`, già in italiano e già
rivolto all'utente finale**: «controlla che il cavo USB sia collegato», «correggili nella
schermata Configurazione», «aggiungila nella card "Schede Arduino"». Non c'è una traduzione da
codice d'errore a frase sparsa fra GUI e CLI: il messaggio nasce dove si conosce la causa e
viaggia intatto fino allo schermo.

**Un errore su un campione non fa fallire la misura.** `_measure_distance()` prova
`n_samples` volte e tiene le letture riuscite; registra un errore **solo se non ne è riuscita
nessuna**. Un singolo disturbo elettrico non deve produrre una notifica.

### 5.9 La card "Schede Arduino" e la prova del collegamento

Nella schermata **Configurazione**, la card *"Schede Arduino — porte USB e pin delle sonde"*
è generata interamente da `SENSOR_SPECS`. Contiene:

- **🔍 Rileva schede** — `list_serial_ports()` (`serial.tools.list_ports`) elenca le porte USB
  attualmente collegate con la loro descrizione, così l'utente sceglie da un elenco invece di
  ricordarsi `/dev/ttyACM0`;
- `baudrate` e `timeout` globali;
- per ogni scheda: nome, porta, casella *abilitata*, e per ogni sensore le caselle degli
  argomenti dichiarati in `args`;
- **l'anteprima del comando** che verrebbe realmente inviato (`command_preview()`), aggiornata
  mentre si scrive: è il modo più diretto per far vedere che `trig: 2` ed `echo: 3` diventano
  `read_us,2,3`;
- **Prova** (`test_arduino_sensor`) — esegue *subito* una lettura di quel solo sensore e ne
  mostra il risultato o l'errore. Serve a verificare il cablaggio senza avviare un job e
  senza aspettare il prossimo intervallo.

Da riga di comando l'equivalente è `-arduino` (elenco porte, stato delle schede, prova di un
sensore), documentato in `DUCUMENTATION_CLI.md`.

### 5.10 Provare il collegamento senza l'applicazione

`arduino_modules/serial_command_arduino.py` è uno script deliberatamente elementare — nessuna
classe, nessuna funzione — che apre la porta, manda un comando e stampa la risposta. Serve a
isolare i problemi: se funziona lui e non funziona l'applicazione, il problema non è nel
cablaggio.

Contiene anche l'unico consiglio pratico per trovare la porta giusta: eseguire `ls /dev/tty*`
**prima** di collegare l'Arduino e **dopo**; la voce comparsa nell'elenco è quella da usare.

### 5.11 Librerie richieste sull'Arduino

Da installare nell'IDE Arduino prima di compilare lo sketch:

| Libreria | Serve per |
|---|---|
| Atlas Scientific **Surveyor** (`ph_surveyor.h`, `base_surveyor.h`) | sonda di pH, con calibrazione in EEPROM |
| Atlas Scientific **Ezo_i2c_lib** (`Ezo_i2c.h`) | circuito EZO-EC su I2C |
| `Wire.h` | bus I2C (inclusa nell'IDE) |

Gli HC-SR04 non richiedono librerie: `pulseIn()` è una primitiva del core Arduino.

### 5.12 Collegamenti hardware

```
Raspberry Pi ---- cavo USB ---- Arduino UNO
                                  |
     +----------------------------+-----------------------------+
     |              |                    |                      |
  Surveyor pH    EZO-EC (I2C)      HC-SR04 serbatoio     HC-SR04 crescita
   OUT -> A0     SDA -> A4          TRIG -> D2            TRIG -> D4
   VCC -> 5V     SCL -> A5          ECHO -> D3            ECHO -> D5
   GND -> GND    VCC -> 5V          VCC  -> 5V            VCC  -> 5V
                 GND -> GND         GND  -> GND           GND  -> GND
```

I pin digitali indicati sono quelli di `config.yaml`: **sono cambiabili senza toccare lo
sketch**. Quelli analogici e I2C lo sono altrettanto (`pin: A0`, `address: 100`), con l'unico
vincolo che l'I2C sull'UNO vive fisicamente su A4/A5.

Nessun partitore di tensione: l'Arduino lavora a 5 V come gli HC-SR04. È una delle
semplificazioni ottenute spostando i sensori dal Pi alla scheda (§5.1).

---

## 6. `JobsManager` — pompe e GPIO

Gestisce i cicli di irrigazione. Ha tre tipi di job: **AEROPONICS**, **IDROPONICS** e
i **job generici** definiti dall'utente.

### 6.1 `runner()` — il lanciatore di thread

```python
def runner(self, job, *args, **kwargs):
    job_thread = threading.Thread(target=job, args=args, kwargs=kwargs, daemon=True)
    job_thread.start()
```

Ogni attivazione di pompa è un `daemon` thread: lo scheduler resta libero di contare il
tempo mentre la pompa è accesa, e i thread muoiono automaticamente alla chiusura del
programma.

### 6.2 Schema di attivazione/disattivazione

Tutti e tre i tipi di job seguono lo stesso schema a **flag + scheduler dedicato**:

```python
def start_aeroponics(self):
    if self.aeroponics_job_active:
        return False                  # già attivo: la GUI mostra un avviso
    self.aeroponics_job_active = True
    threading.Thread(target=self.activate_aeroponics, daemon=True).start()
    return True

def activate_aeroponics(self):
    self.aero_schedule = schedule.Scheduler()          # scheduler PROPRIO del job
    self.aero_schedule.every(interval).minutes.do(
        self.runner, job=self.pump_aerophonics, gpio=..., irrigation_time=...)
    while self.aeroponics_job_active:                  # <- il flag è la condizione d'uscita
        self.aero_schedule.run_pending()
        sleep(1)

def deactivate_aeroponics(self):
    self.aeroponics_job_active = False                 # il loop esce entro 1 s
```

Ogni job possiede un'**istanza `Scheduler()` separata** (non lo scheduler globale di
`schedule`): così si può fermare un job senza toccare gli altri. La disattivazione è
cooperativa — si abbassa un flag e il ciclo termina al successivo giro (≤ 1 s).

### 6.3 `pump_aerophonics()` — irrigazione a tempo fisso

Logica: accendi, conta i secondi, spegni.

```python
self.gpios.output(gpio, False)        # accende (active-low)
for i in range(irrigation_time):
    if i == irrigation_time - 1:
        self.gpios.output(gpio, True) # spegne
        break
    sleep(1)
```

Con la configurazione attuale: ogni **1200 minuti** (20 ore) la pompa resta accesa **5 secondi**.

### 6.4 `pump_idrophonics()` — irrigazione a retroazione

Qui la durata non è fissa: la pompa si ferma quando il **sensore di livello** segnala acqua
sufficiente, oppure quando scade il tempo massimo di sicurezza.

```python
for i in range(max_irrigation_time):
    if i == max_irrigation_time - 1:              # 1) timeout di sicurezza
        self.gpios.output(gpio_pump, True)        #    spegni comunque
        break
    if self.gpios.input(gpio_sensor) == 0:        # 2) livello raggiunto
        self.gpios.output(gpio_pump, True)        #    spegni
        break
    else:                                         # 3) livello basso
        self.gpios.output(gpio_pump, False)       #    tieni accesa
        sleep(1)
```

Il sensore legge **0 = acqua alta** (pompa OFF) e **1 = acqua bassa** (pompa ON). Il timeout
`max_irrigation_time` (65 s) è la protezione contro un sensore guasto: senza di esso, un
sensore bloccato su "basso" farebbe pompare all'infinito.

### 6.5 `on_off_general()` — job generici configurabili

Generalizza lo schema per qualsiasi pin. Rispetto ai due precedenti, **rilegge i parametri da
`config.yaml`** cercando la voce con il `name` corrispondente, usando gli argomenti passati
solo come fallback:

```python
job_config = next((j for j in self.configs['gpio_pins'] if j.get('name') == name), None)
if job_config is not None:
    gpio       = job_config.get('pin',      gpio)
    on_period  = job_config.get('on_time',  on_period)
    off_period = job_config.get('interval', off_period)
else:
    self.logger.warning(f'ON_OFF_GENERAL [{name}]: no matching entry in config.yaml ...')
```

Lo stato è tenuto in un dizionario `general_jobs_active[name]`, così più job generici
convivono indipendentemente. La funzione interna `_pulse()` replica la logica di
`pump_aerophonics`.

### 6.6 `T_modifier()` — modulazione dell'irrigazione con la temperatura

Funzione **non ancora integrata** nel flusso attivo (nessun chiamante). Idea: accorciare
l'attesa tra le irrigazioni quando fa caldo, tramite una **sigmoide logistica** centrata
sulla temperatura ottimale `Topt`:

```
t_modifier = amp / (exp(a·(T − Topt)) + 1) − amp/2        con a = −0.2, amp = 1
t_new      = t_old − t_old · t_modifier
```

Il modificatore vale 0 a `T = Topt` (nessuna correzione), tende a **+0.5** per `T ≫ Topt`
(attesa dimezzata → irriga più spesso) e a **−0.5** per `T ≪ Topt` (attesa aumentata del 50%).
Il parametro `a = −0.2` regola la pendenza della transizione.

> ⚠️ Nell'implementazione attuale la funzione contiene un errore che ne impedisce
> l'esecuzione (vedi §20).

---

## 7. `AmbientManager` — DHT22 e VPD

Legge temperatura e umidità dal sensore **DHT22**, calcola il VPD, salva su file e carica online.

### 7.1 Lettura del sensore: `measure_dht22()`

```python
dht = eval(f"adafruit_dht.DHT22(board.D{gpio})")
while True:
    try:
        T = dht.temperature
        H = dht.humidity
        return T, H
    except RuntimeError as error:      # errore di checksum/timing: RIPROVA
        print(error.args[0])
        sleep(2.0)
        continue
    except Exception as error:         # errore reale: propaga
        dht.exit()
        raise error
```

Il punto centrale è la **distinzione tra i due tipi di errore**. Il DHT22 usa un protocollo
one-wire con timing stretto e su un Linux non real-time fallisce spesso con `RuntimeError`
(checksum errato, impulso perso): sono errori **transitori** e la strategia è riprovare dopo
2 s, all'infinito, finché la lettura riesce. Qualsiasi altra eccezione indica un problema
hardware e viene propagata dopo aver rilasciato il sensore con `dht.exit()`.

### 7.2 Calcolo del VPD

Il **VPD** (*Vapor Pressure Deficit*, deficit di pressione di vapore) misura quanto l'aria è
"assetata": è la differenza tra il vapore che l'aria potrebbe contenere alla saturazione e
quello che effettivamente contiene. È il parametro che governa la traspirazione della pianta.

```python
def VPD(self, T, H):
    es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))   # pressione di saturazione [kPa]
    ea = lambda H: H * es(T) / 100                          # pressione parziale effettiva
    VPD = es(T) - ea(H)
    return VPD
```

- `es(T)` — **pressione di vapore saturo**, equazione di Tetens, dipende solo da T;
- `ea(H)` — **pressione di vapore effettiva**, ottenuta scalando `es` per l'umidità relativa;
- `VPD = es − ea = es·(1 − H/100)` — il deficit, in kPa.

> ⚠️ La costante `273.3` a denominatore diverge dalla formulazione standard di Tetens,
> che usa `237.3` (vedi §20).

### 7.3 Il ciclo di lettura: `_read_loop()`

Avviato da `start_reading(on_update)` in un thread daemon. Ad ogni iterazione:

1. legge T e H (con la logica di retry vista sopra);
2. calcola il VPD;
3. memorizza `self.last_T` / `self.last_H` — **è da qui che `ClimateManager` legge i dati**;
4. genera timestamp (`%Y/%m/%d %H:%M:%S`) e nome file (`%Y_%m_%d`);
5. invoca la callback `on_update(temp, humidity, vpd, timestamp)` se presente (aggiorna la GUI);
6. scrive la riga nel file giornaliero `TH_<YYYY>_<MM>_<DD>.txt`;
7. chiama `upload_data_on_web()`;
8. attende con `self._stop_event.wait(interval)`.

**L'arresto immediato** è ottenuto con `threading.Event`: `stop_reading()` fa
`self._stop_event.set()`, che sblocca istantaneamente la `wait()`. Con un `sleep(300)` la
GUI avrebbe dovuto attendere fino a 5 minuti per fermare la lettura.

Il formato di scrittura è:

```python
format_data_out = "%s\t %5.2fC\t %5.2f%%\t %5.4fkPa \n"
```

L'upload delega al modulo esterno via shell:

```python
os.system(f'python uploader/uploader.py data -t {T} -hu {H} -vpd {vpd} -ts "{timestamp}"')
```

`read_now()` esegue invece una lettura singola e sincrona (bottone "Leggi ora"), senza
salvare né caricare.

### 7.4 `last_result` e la rilettura da file — con un vincolo di sicurezza

`last_result` (`{temperature, humidity, vpd, timestamp}`) è l'ultima misura completa, e
alimenta la scheda Riepilogo (§2.3). Viene popolato da `_read_loop`, da `read_now()` e —
all'avvio — da `load_last_th()`, che rilegge l'ultima riga del file TH più recente.

`load_last_th()` è di sola libreria standard e sceglie il file con `sorted(glob(...))[-1]`: il
nome `TH_%Y_%m_%d.txt` ordina cronologicamente anche come stringa, quindi il dato c'è anche se
il pannello viene aperto a mezzanotte e il file di oggi non esiste ancora. Le unità sono
attaccate ai valori (`23.40C`), quindi il numero si estrae con la stessa regex di
`daily_th_processor` (§16.1) — ma **senza importarlo**: quel modulo tira dentro `pandas`
(secondi di import e decine di MB residenti su un Pi Zero W, per leggere una riga di testo),
`schedule`, e soprattutto esegue `logging.basicConfig` **a import-time**, riconfigurando il
logging della GUI.

> ⚠️ **`last_T`/`last_H` non vengono e non devono essere seminati da file.** Significano
> "letto dal sensore in questa sessione", e `ClimateManager.start()` si rifiuta di partire
> finché sono `None` (§8.1): è la precondizione che impedisce di comandare il condizionatore
> senza dati sul clima. Popolarli da file, magari "per simmetria" con `last_result`, farebbe
> agire l'AC su una temperatura vecchia di ore. `last_result` è solo informativo e può
> permetterselo; quelli no.

---

## 8. `ClimateManager` e `IRController` — condizionatore

Due livelli: `ClimateManager` gestisce il **ciclo temporale**, `IRController` la **decisione**
e l'invio del segnale.

### 8.1 `ClimateManager.start()` — il ciclo di controllo

```python
if self.ac_control_active:                    return 'already_active'
if self.ambient.last_T is None or self.ambient.last_H is None:
                                              return 'no_ambient'
```

**Precondizione fondamentale**: il controllo AC non parte se non c'è almeno una lettura
ambient. Senza dati sul clima non ha senso comandare il condizionatore, e la GUI usa il
valore `'no_ambient'` per dire all'utente di avviare prima la lettura T/H.

Il loop:

```python
while not self._stop_event.is_set():
    if self.ambient.last_T is not None and self.ambient.last_H is not None:
        self.ir_controller.evaluate_and_send(self.ambient.last_T, self.ambient.last_H)
        ...
    self._stop_event.wait(interval * 60)      # control_time è in MINUTI
```

`stop()` interrompe il ciclo **e forza lo spegnimento** con `ir_controller.force_off()`: il
sistema non lascia mai il condizionatore acceso quando il controllo viene disattivato.

### 8.2 `IRController.evaluate_and_send()` — la macchina a stati

Stato interno: `last_command_sent` (`'T_low_21'`, `'dry'`, `'off'` o `None`) e
`command_sent_time`. La logica, nell'ordine di valutazione:

**1. Timeout di sicurezza** — precede ogni altra valutazione:

```python
if self.last_command_sent in ('Tlow', 'Hlow') and self.command_sent_time is not None:
    elapsed_minutes = (now - self.command_sent_time) / 60.0
    if elapsed_minutes >= self.time_max_on:
        self.send_command('off'); ...; return
```

Impedisce che il condizionatore resti acceso oltre `time_max_on` (10 min) di continuo.

**2. Temperatura (priorità assoluta)**

```python
if current_temp > self.Topt:                      # Topt = ir_control.T_max = 26 °C
    if self.last_command_sent != 'T_low_21':
        self.send_command('T_low_21')             # raffredda
        self.last_command_sent = 'T_low_21'
        self.command_sent_time = now
    return                                        # <- l'umidità NON viene valutata
```

Il `return` è la chiave: **finché la temperatura è alta l'umidità viene ignorata**. Il
condizionatore ha una sola modalità attiva per volta, e raffreddare (che di per sé
deumidifica) ha la precedenza.

Il confronto `if self.last_command_sent != 'T_low_21'` evita di ritrasmettere il comando IR
a ogni ciclo se il condizionatore è già nello stato desiderato.

**3. Rientro dalla temperatura** — se T è tornata sotto soglia e lo stato era `T_low_21`,
invia `off`.

**4. Umidità** — valutata solo se la temperatura è a posto:

```python
if current_humidity > self.Hopt:                  # Hopt = ir_control.H_max = 65.5 %
    if self.last_command_sent != 'dry':
        self.send_command('dry')                  # deumidifica
else:
    if self.last_command_sent == 'dry':
        self.send_command('off')                  # umidità rientrata: spegni
```

### 8.3 Invio del segnale IR

```python
def send_command(self, command):
    cmd = f"piir play --gpio {self.tx_gpio} -f {self.file_ac_name} {command}"
    result = os.system(cmd)
```

Il modulo non modula direttamente il LED infrarosso: delega all'utility esterna **`piir`**,
che legge i codici dal file `ac_remote.json` (registrato in precedenza dal telecomando
originale) e li ritrasmette sul pin TX. Un exit code diverso da zero produce un warning
nel log ma non solleva eccezione: un comando IR perso verrà ritentato al ciclo successivo.

---

## 9. `TankManager` — livello serbatoio (HC-SR04)

Il sensore a ultrasuoni del serbatoio **non è più collegato ai GPIO del Raspberry**: sta
sull'Arduino (§5), e il manager lo legge con `arduino.read_float('US_water')`.

Il modulo `sensors/ultrasonic_sensor/ultrasonic_measurement.py` continua però a essere usato,
per due cose che non dipendono da dove sia il sensore: la **matematica del volume**
(`distance_to_water_volume`) e il **salvataggio su file** (`save_data`). Resta anche
eseguibile in autonomia (`python3 ultrasonic_measurement.py`) con i propri GPIO, per chi
volesse collegare un HC-SR04 direttamente al Pi.

### 9.1 Parametri con fallback

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

Ogni parametro viene cercato prima in `config.yaml`, poi nelle costanti del modulo.
**`trig_pin` ed `echo_pin` non ci sono più**: i pin del sensore vivono in
`arduino.boards[].sensors.US_water`, perché è lì che servono — sono ciò che finisce dentro il
comando `read_us` (§5.4).

`_params()` viene rilette ad ogni giro del ciclo, quindi un cambio di intervallo o di soglia
salvato dalla GUI ha effetto senza riavviare.

### 9.2 Principio fisico della misura

L'HC-SR04 emette un treno di 8 impulsi ultrasonici a **40 kHz** e tiene il pin ECHO alto per
tutto il tempo di volo dell'onda (andata + ritorno). Il cronometraggio avviene sull'Arduino
(§5.6):

```
distanza [cm] = durata_echo [µs] × 0.0343 [cm/µs] / 2
```

`0.0343 cm/µs` è la velocità del suono in aria a ~20 °C; la divisione per 2 elimina il
percorso di ritorno. Un eco mai ricevuto scade dopo 40 ms (≈ 6.8 m) e diventa `ERR`, che sul
Raspberry diventa un `ArduinoError`.

> **Nota hardware.** Il partitore di tensione che serviva sul Raspberry (ECHO esce a 5 V, i
> GPIO del Pi tollerano 3.3 V) **non serve più**: l'Arduino lavora nativamente a 5 V.

### 9.3 Filtraggio del rumore: la mediana di N letture

```python
letture = []
for _ in range(max(1, int(n_samples))):
    try:
        letture.append(self._arduino.read_float('US_water'))
    except ArduinoError as e:
        ultimo_errore = e            # si prosegue: un campione perso non è un guasto

if not letture:
    self._errors.record('US_water', "Non è stato possibile leggere ... : " + ...)
    return None

return median(letture)
```

La funzione restituisce la **mediana**, non la media: scelta deliberata, perché la mediana è
robusta agli outlier — un singolo eco spurio (riflesso sulla parete della tanica, schiuma
sull'acqua) sposterebbe la media, non la mediana. È la stessa statistica già usata da
`measure_distance_avg()` del modulo standalone (che, nonostante il nome, calcola anch'essa la
mediana).

**A ripetere le letture è il Raspberry**, non l'Arduino: allo sketch si chiede una misura alla
volta. Così l'Arduino resta un esecutore elementare e la politica di campionamento
(`n_samples`) resta configurabile da `config.yaml` senza ricompilare la scheda (§5.3).

Un errore su un singolo campione **non** produce una segnalazione: si tiene da parte e si
prosegue. La segnalazione arriva solo se **nessuna** delle `n_samples` letture è riuscita, e
in quel caso riporta l'ultimo errore ricevuto, che è quello con la spiegazione più utile.

Nota: il ritardo di 65 ms fra un campione e il successivo, raccomandato dal datasheet, qui è
implicito — il giro completo comando/risposta sulla seriale a 9600 baud dura più di tanto.

### 9.4 Da distanza a volume: `distance_to_water_volume()`

```
   [SENSORE]        <- sensor_offset_cm dal bordo
   [ bordo tanica ] ---
   [              ]    | colonna d'aria = distanza − offset
   [ ~~~ acqua ~~~]  ---
   [              ]    | water_level_cm
   [ fondo tanica ]  ---
```

```python
air_column_cm  = distance_cm - sensor_offset_cm
water_level_cm = tank_height_cm - air_column_cm
water_level_cm = max(0.0, min(water_level_cm, tank_height_cm))   # clipping fisico
volume_L     = (water_level_cm * tank_area_cm2) / 1000.0         # cm³ -> L
fill_percent = (water_level_cm / tank_height_cm) * 100.0
```

**Formule:**

```
livello  [cm] = altezza_tanica − (distanza_misurata − offset_sensore)
volume    [L] = livello [cm] × sezione [cm²] / 1000
riempimento [%] = livello / altezza_tanica × 100
```

Il **clipping** a `[0, tank_height_cm]` protegge da errori di taratura: senza, un offset
sbagliato produrrebbe volumi negativi o superiori alla capacità.
Il modello assume una tanica a **sezione costante** (`tank_area_cm2`); per contenitori
irregolari il volume sarebbe da ricalcolare.

### 9.5 Validazione e allarme

`read_now()` applica due controlli prima di accettare la misura:

```python
if dist is None:                   # nessuna lettura riuscita: errore già registrato
    return None
if dist < 2.0 or dist > 400.0:     # fuori dal range operativo dell'HC-SR04
    self._errors.record('US_water', f"... distanza {dist:.1f}cm fuori dal range "
                                    f"operativo (2-400cm). Misura ignorata.")
    return None
```

**I due casi sono trattati diversamente, ed è voluto.** Il primo ha già registrato il proprio
errore in `_measure_distance()`, con la causa vera (cavo, pin, sonda); registrarlo di nuovo
qui produrrebbe due voci per lo stesso guasto. Il secondo è un errore che solo questo livello
può riconoscere — l'Arduino ha risposto un numero perfettamente valido, è il *significato* a
non stare in piedi.

Il ciclo `_read_loop()` salva su file e confronta con la soglia di riserva:

```python
if result['volume_L'] < p['low']:
    self.logger.warning(f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                        f"sotto la soglia di {p['low']}L! Riempire la tanica.")
```

Il serbatoio quasi vuoto è un `warning` del logger e **non** una voce del registro errori
(§11): non è un guasto di lettura, è un'informazione agronomica. Il registro errori raccoglie
solo ciò che ha impedito di misurare.

### 9.6 Rilettura dell'ultimo livello

`load_last_tank(save_dir)` rilegge l'ultima riga del file `TANK_*.txt` più recente e popola
`last_result` in `__init__`, come già fanno spettrometro e crescita con i loro storici. Senza,
il livello del serbatoio sarebbe l'unico dato **perso ad ogni riavvio** del programma, e la
scheda Riepilogo (§2.3) mostrerebbe un blocco vuoto fino alla prima lettura.

Il lettore vive in `tank_manager.py` e **non** in `ultrasonic_measurement.py`: quel modulo fa
`import RPi.GPIO` a livello di modulo, mentre leggere un file di testo non ha alcun bisogno
della GPIO — e così la funzione resta importabile e testabile anche fuori dal Raspberry.
Salta l'header (`startswith("datetime")`) e le righe malformate, restituendo `None` se non
trova nulla di leggibile.

---

## 10. `WaterManager` — pH e conducibilità elettrica

Misura **com'è fatta** l'acqua, mentre `TankManager` (§9) misura **quanta ce n'è**. Le due
sonde sono entrambe Atlas Scientific, entrambe collegate all'Arduino (§5):

| Grandezza | Sonda | Comando | Cosa dice |
|---|---|---|---|
| pH | Surveyor V3.0 + Lab Grade pH Probe Gen 3 | `read_pH,A0` | acidità della soluzione |
| EC, TDS, salinità | EZO-EC su I2C | `read_EC,100` | quanto è concentrata la soluzione nutritiva |

### 10.1 Due job, non uno

pH ed EC sono **due job indipendenti**, con intervallo, thread e comandi di avvio/arresto
propri:

```python
water.start_ph_reading(on_update)   /  water.stop_ph_reading()   /  water.is_ph_running()
water.start_ec_reading(on_update)   /  water.stop_ec_reading()   /  water.is_ec_running()
```

Non è una duplicazione: le due sonde hanno tempi e finalità diverse, si calibrano
separatamente e si guastano separatamente. Doverle fermare insieme significherebbe, in caso
di manutenzione della sonda di pH, perdere anche il monitoraggio della concentrazione.

Restano due comodità per chi vuole trattarle insieme:

```python
def is_running(self):  return self.is_ph_running() or self.is_ec_running()
def stop_all(self):    ...   # ferma entrambi, True se almeno uno era in corso
```

`is_running()` è quella che la schermata **Processi** usa per la voce riassuntiva; le due
spie separate usano `is_ph_running()` e `is_ec_running()` (§2.2).

### 10.2 Una lettura di pH

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

**Un solo campione**, a differenza degli ultrasuoni: la media è già fatta dall'Arduino, che
per una `read_pH` impiega circa 8 s mediando su una finestra di 5 secondi più tre conversioni
(§5.6). Ripeterla dal Pi triplicherebbe il tempo senza aggiungere informazione.

Poi il valore viene arrotondato con `round_decimals()` (`water.decimals`, default 2),
memorizzato in `last_ph`, scritto su file e confrontato con le soglie:

```python
if result['ph'] < p['ph_min'] or result['ph'] > p['ph_max']:
    self.logger.warning(f"WATER pH FUORI RANGE: {result['ph']} non è compreso fra "
                        f"{p['ph_min']} e {p['ph_max']}. Correggere la soluzione nutritiva.")
```

### 10.3 Una lettura di EC: tre grandezze in un colpo solo

```python
valori = self._arduino.read_named('EC')
# {'ec_us_cm': 1250.0, 'tds_ppm': 625.0, 'salinity_psu': 0.62}
```

Il circuito EZO-EC restituisce in **un'unica risposta** conducibilità, solidi disciolti totali
e salinità, perché è così che è stato configurato in `setup()` (§5.6). Una sola lettura popola
quindi l'intero blocco EC dell'interfaccia: non ha senso — e sarebbe più lento e meno coerente
— chiedere le tre grandezze separatamente.

`read_named()` è l'unico metodo dell'hub che restituisce un dizionario, ed è usato solo qui.
I nomi delle chiavi vengono da `SENSOR_SPECS`, non sono ripetuti nel manager: aggiungere la
gravità specifica (SG) significherebbe abilitarla nello sketch e aggiungere una coppia a
`values`, senza toccare `WaterManager`.

La validazione è sul solo `ec_us_cm`, contro il **fondo scala dichiarato dell'EZO-EC**
(0–200000 µS/cm). TDS e salinità sono grandezze derivate dalla stessa misura: se la
conducibilità è plausibile lo sono anche loro.

### 10.4 Soglie di allarme e range di validità

È la distinzione già anticipata in §4, e qui è particolarmente visibile:

| | pH | EC |
|---|---|---|
| **Range di validità** (costante nel codice, fuori → misura **scartata**) | 0 – 14 | 0 – 200000 µS/cm |
| **Soglie di allarme** (in `config.yaml`, fuori → misura **salvata** + warning) | `ph_min` 5.5 – `ph_max` 6.5 | `ec_min` 800 – `ec_max` 2000 µS/cm |

Un pH di 8.2 è un problema **agronomico**: va registrato, mostrato e corretto intervenendo
sulla soluzione. Un pH di 21 è un problema **elettrico**: non è mai esistito, e salvarlo
sporcherebbe lo storico e i grafici. Confondere i due casi renderebbe inutile sia l'allarme
sia l'archivio.

### 10.5 Il formato del file: le due sonde scrivono sulla stessa tabella

```
datetime			 ph	 ec_uScm	 tds_ppm	 sal_psu
2026/09/05 09:00:12	 6.12	 --	 --	 --
2026/09/05 09:04:31	 --	 1250.0	 625.0	 0.62
```

Un unico file `WATER_%Y_%m_%d.txt` per entrambe le sonde, ma **quasi ogni riga ne riempie
solo una metà**: gli intervalli sono indipendenti, quindi pH ed EC scrivono in momenti
diversi. Le colonne non misurate valgono `--`.

Il segnaposto non è cosmetico: rileggendo, `--` diventa `None`, e chi legge distingue
**"non misurato"** da **"misurato zero"** — che per una conducibilità sono due affermazioni
molto diverse.

`load_last_water()` sfrutta esattamente questo: risale il file **all'indietro** cercando
separatamente l'ultimo pH valido e l'ultima EC valida, e si ferma appena li ha trovati
entrambi. È il motivo per cui il blocco H2O del Riepilogo ha due date distinte (§2.3).

### 10.6 Il ciclo periodico

Identico per le due sonde, e identico nella forma a quello di tutti gli altri manager:

```python
while not self._ph_stop_event.is_set():
    try:
        result = self.read_ph_now()          # read_ph_now salva già su file
        if result is not None and on_update is not None:
            on_update(result)
    except Exception as e:
        self.logger.error(f"Errore lettura pH: {str(e)}")

    self._ph_stop_event.wait(self._params()['ph_interval'])
```

Tre dettagli ricorrenti nel progetto:

- **la prima misura parte subito**, poi si attende l'intervallo: con 30 minuti di cadenza,
  l'alternativa sarebbe una schermata vuota per mezz'ora;
- l'attesa usa `threading.Event.wait()`, quindi il bottone Stop interrompe **immediatamente**
  anche un'attesa lunga (§18);
- `_params()` è riletto **ad ogni giro**, quindi cambiare l'intervallo dalla GUI ha effetto
  dal ciclo successivo senza riavviare.

L'`except Exception` è la rete di sicurezza: un errore imprevisto scrive nel log ma **non
uccide il thread**, che riproverà al giro dopo. Gli errori previsti — quelli della sonda —
sono già stati gestiti dentro `read_ph_now()` e non arrivano fin qui.

---

## 11. `ErrorRecorder` — registro degli errori di lettura

Quando una sonda non si lascia leggere, l'informazione deve arrivare **a una persona**. Il
file di log non basta: nessuno lo apre, e a fine giornata contiene migliaia di righe di
misure riuscite.

### 11.1 Perché non è un semplice handler di logging

Perché ha **due consumatori con requisiti diversi**:

1. la sezione **"Errori di lettura"** della schermata Log, che vuole gli ultimi errori con
   timestamp e una frase leggibile, subito e senza rileggere il disco;
2. l'**uploader**, che deve poter pubblicare sul sito gli errori del giorno — quindi devono
   **sopravvivere al riavvio** del programma.

Un handler di logging in memoria soddisfa il primo e non il secondo; un file di log soddisfa
il secondo ma in un formato non interrogabile. `ErrorRecorder` fa entrambe le cose, e in più
passa ogni errore anche al logger condiviso, così finisce nel file di log e a terminale come
tutto il resto.

```python
def record(self, source, message):
    errore = {'timestamp': ..., 'source': source or '-', 'message': ...}
    with self._lock:
        self._history.append(errore)     # deque(maxlen=history_len) -> GUI
        self._append_to_file(errore)     # ERRORS_%Y_%m_%d.txt      -> uploader
    self.logger.error(f"{errore['source']}: {errore['message']}")
    return errore
```

### 11.2 Dettagli che contano

**Il lock.** Le letture arrivano da thread diversi — un job per sonda — quindi sia il `deque`
sia la scrittura su file vanno protetti. È la seconda sezione critica del sistema, dopo quella
della seriale (§5.7).

**La normalizzazione.** Tabulazioni e a capo dentro il messaggio spezzerebbero il formato del
file, che è tab-separated: vengono sostituiti con spazi *prima* di scrivere.

**Il ripopolamento all'avvio.** Il costruttore rilegge gli errori già registrati **oggi**:

```python
for errore in load_errors(p['save_dir'], logger=self.logger):
    self._history.append(errore)
```

Senza, dopo un riavvio la schermata Log ripartirebbe vuota e un guasto avvenuto un'ora prima
sembrerebbe non essere mai accaduto.

**Un errore nello scrivere gli errori non è fatale.** Se `_append_to_file()` fallisce (disco
pieno, permessi), l'eccezione viene catturata e loggata: l'errore resta comunque in memoria e
nel log, e soprattutto **la lettura in corso non cade**.

### 11.3 Chi ci scrive

| Sorgente (`source`) | Registrato da | Quando |
|---|---|---|
| `pH` | `WaterManager` | `ArduinoError`, o valore fuori dalla scala 0–14 |
| `EC` | `WaterManager` | `ArduinoError`, o valore oltre il fondo scala |
| `US_water` | `TankManager` | nessuna delle `n_samples` letture riuscita, o distanza fuori 2–400 cm |
| `US_plant` | `PlantGrowthManager` | idem, per il sensore della crescita |

I nomi delle sorgenti sono **le stesse chiavi di `SENSOR_SPECS`** (§5.7): l'utente che legge
`US_plant` nella colonna "sorgente" ritrova la stessa etichetta nella card "Schede Arduino"
della Configurazione, e sa dove intervenire.

Il registro raccoglie **solo gli errori che hanno impedito una misura**. Un serbatoio in
riserva o un pH fuori range sono warning del logger, non voci del registro: sono misure
riuscite che dicono qualcosa di spiacevole, ed è una categoria diversa.

### 11.4 Il file

```
datetime	source	message
2026/09/05 09:41:03	US_water	Non è stato possibile leggere il sensore ultrasonico del serbatoio, controlla il motivo: Scheda Arduino 'Board1' non raggiungibile sulla porta /dev/ttyACM0: controlla che il cavo USB sia collegato (...)
```

Un file al giorno, `ERRORS_%Y_%m_%d.txt`, tab-separated, header solo se il file è nuovo, come
tutti gli altri formati del progetto (§15). `load_for_date(giorno)` lo rilegge per un giorno
qualsiasi — è ciò che serve all'uploader — e `load_today()` è la scorciatoia per oggi.

Il messaggio è quello nato in `arduino_link.py`, arricchito dal manager con il contesto
("quale sonda") e conservato per intero: è già una frase compiuta, in italiano, che dice cosa
è successo e cosa fare.

---

## 12. `PlantGrowthManager` — altezza della pianta (HC-SR04)

Misura di quanto sono cresciute le piante, con un **secondo sensore HC-SR04** montato sopra
la camera radicale e puntato verso il basso. Come quello del serbatoio è collegato
all'**Arduino** (§5) e non ai GPIO del Raspberry: stessa fisica, stesso comando `read_us`,
bersaglio diverso. A distinguerlo è la coppia di pin — `US_plant` invece di `US_water` (§5.4).

### 12.1 Principio della misura

Il sensore misura la distanza da sé stesso alla **sommità della pianta**. L'altezza della
pianta è quindi la differenza rispetto a una **distanza di riferimento**, misurata col metro
a pianta assente:

```
   [SENSORE]  ---
   [        ]    |
   [   🌱   ]    | distanza_misurata      reference_height_cm
   [        ]  ---                                |
   [ camera radicale ] --------------------------  ---
```

```
h_plant [cm] = reference_height_cm − distanza_misurata
```

Con il sensore a 70 cm dalla camera radicale:

| Distanza letta | h_plant | Significato |
|---|---|---|
| 70 cm | 0 cm | pianta non ancora cresciuta |
| 65 cm | 5 cm | la pianta è cresciuta di 5 cm |

```python
h_plant = max(0.0, p['reference'] - dist)
```

Il **clipping a 0** ha lo stesso ruolo del clipping del serbatoio (§9.4): protegge da una
taratura imprecisa di `reference_height_cm`. Senza, un riferimento sottostimato di pochi
millimetri produrrebbe altezze negative — fisicamente impossibili.

`reference_height_cm` è quindi **il parametro da tarare**, e si tara con il sensore stesso
(§12.6) a camera radicale vuota: la distanza che il sensore legge in quel momento *è* per
definizione il riferimento. Misurarlo col metro è possibile ma meno accurato, perché il metro
e il sensore non partono necessariamente dallo stesso punto: il sensore misura dalla propria
membrana, e un errore sul riferimento si trasferisce **uguale su ogni misura successiva**.

### 12.2 Parametri con fallback

Stesso idiom di `TankManager._params()` (§9.1): prima `config.yaml`, poi le costanti del
modulo. I default stanno in `plant_growth.py` e non in `ultrasonic_measurement.py`, perché le
costanti di quel modulo (`TANK_HEIGHT_CM`…) descrivono il **serbatoio**.

```python
def _params(self):
    g = self.configs.get('plant_growth', {}) or {}
    return dict(
        interval_days=g.get('read_interval_days', READ_INTERVAL_DAYS),  # 1 giorno
        n=g.get('n_samples', N_SAMPLES),                                # 3
        reference=g.get('reference_height_cm', REFERENCE_HEIGHT_CM),    # 70.0 cm
        decimals=g.get('decimals', DEFAULT_DECIMALS),                   # 1
        save_enabled=g.get('save', True),
        save_dir=g.get('saving_dir', SAVE_DIR),
        history_len=g.get('history_len', HISTORY_LEN),                  # 30
    )
```

Come per il serbatoio, **`trig_pin` ed `echo_pin` non compaiono più**: i pin del sensore
stanno in `arduino.boards[].sensors.US_plant` (§5.4).

### 12.3 Media o mediana? — `_measure_mean_distance()`

I due manager che leggono un HC-SR04 usano **statistiche diverse**, e la differenza è
deliberata:

| Manager | Sensore | Statistica | Perché |
|---|---|---|---|
| `TankManager` | `US_water` | **mediana** | robusta agli outlier: un eco spurio (schiuma, riflesso sulla parete della tanica) sposterebbe la media, non la mediana |
| `PlantGrowthManager` | `US_plant` | **media** | su un bersaglio fermo come una pianta il rumore è simmetrico, e la media usa l'informazione di tutte le letture invece di scartarne N−1 |

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

if dist < 2.0 or dist > 400.0:          # range operativo dell'HC-SR04
    self._errors.record('US_plant', f"... distanza {dist:.1f}cm fuori dal range ...")
    return None
return dist
```

`_measure_mean_distance()` è l'**unica definizione di "misura valida"** della crescita: la
usano sia `read_now()` sia `calibration_distance()` (§12.6). Con due implementazioni separate,
una calibrazione potrebbe accettare una lettura che una misura rifiuterebbe — e siccome la
calibrazione sposta *tutte* le misure successive, sarebbe l'errore più costoso possibile.

Con la configurazione attuale la crescita media **3 letture**.

### 12.4 Cifre da tenere: `data_config.py`

Modulo di supporto accanto a `plant_growth.py`, per decidere quante cifre conservare dal
sensore:

```python
DEFAULT_DECIMALS = 1
def round_decimals(value, decimals=None)      # arrotonda a N decimali
def round_significant(value, sig_digits)      # arrotonda a N cifre significative
```

Il manager usa `round_decimals` con `decimals` da `config.yaml`. La scelta dei **decimali**
anziché delle cifre significative è motivata dalla fisica del sensore: la risoluzione
dell'HC-SR04 è di circa **0.17 cm**, quindi su una misura in cm ciò che conta è quante cifre
dopo la virgola sono credibili — e con `decimals: 1` l'altezza è espressa al millimetro
abbondante, già oltre la risoluzione reale. `round_significant()` resta disponibile per chi
preferisca ragionare a cifre significative.

### 12.5 Validazione, salvataggio e storico

La validazione è tutta in `_measure_mean_distance()` (§12.3): nessuna lettura riuscita, oppure
distanza fuori dal range operativo dell'HC-SR04 (2–400 cm). In entrambi i casi `read_now()`
restituisce `None` senza scrivere nulla su file, e l'errore è già finito nel registro (§11).

**Differenza rispetto a `TankManager`:** qui il salvataggio avviene **dentro `read_now()`**,
non solo nel ciclo periodico. Con una misura ogni giorno la misura manuale è un caso d'uso
primario, non un'anteprima: la stessa scelta fatta da `SpectroManager`. È subordinata al
flag `save` di `config.yaml`:

```python
if p['save_enabled']:
    save_growth_data(result, p['save_dir'])
self.history.append({...})
self.history = self.history[-p['history_len']:]
```

Lo **storico** (`self.history`) è ricostruito dal file all'istanziazione con `load_history()`,
come fa `SpectroManager`: la GUI mostra così grafico e tabella già popolati subito dopo un
riavvio, e senza interrogare l'Arduino. È tenuto in ordine **cronologico crescente** — è
l'ordine che serve al grafico — e la tabella lo inverte al momento di visualizzarlo. Le righe
malformate vengono loggate e saltate, non fanno fallire la lettura (stessa filosofia di
`daily_th_processor.py`, §16.1).

### 12.6 Calibrazione del riferimento

`calibration_distance()` esegue la taratura: misura la distanza attuale (media di `n_samples`
letture, con la stessa validazione di `read_now()`) e la salva come `reference_height_cm`.
Va eseguita **a camera radicale vuota**. Dalla GUI è il bottone "📐 Calibrazione" della tab
Crescita, che chiede conferma prima di procedere — stesso schema della taratura dello
spettrometro (§13.3).

```python
dist = self._measure_mean_distance(p)          # media validata: se None, non scrive nulla
reference = round_decimals(dist, p['decimals'])
save_reference_height(reference)                                                # su file
self.configs.setdefault('plant_growth', {})['reference_height_cm'] = reference  # in memoria
```

Tre scelte meritano una spiegazione.

**1. Il file viene riletto da disco, non riversato dalla memoria.** `save_reference_height()`
apre `config.yaml`, aggiorna la sola chiave `plant_growth.reference_height_cm` e riscrive.
Riversare `self.configs` sarebbe più diretto ma sbagliato: quel dizionario può contenere
valori modificati a runtime — `test_gui.py` ci inietta percorsi di simulazione — che
finirebbero nel config di produzione. Toccando una chiave sola, invece, nient'altro viene
calpestato.

**2. Il valore è aggiornato anche in memoria, e questo evita il riavvio.** `_params()` rilegge
`self.configs` ad ogni chiamata (§12.2), quindi la misura successiva usa già il nuovo
riferimento: subito dopo la calibrazione `h_plant` vale 0, come atteso.

**3. La GUI deve riallineare il proprio dizionario.** Qui si incontra un difetto strutturale
del progetto (§20.6): `self.config` della GUI e `self.ah.configs` dei manager sono **due
dizionari distinti**, letti separatamente dallo stesso file. `save_config()` riversa l'intero
`self.config`, quindi senza contromisure la sequenza sarebbe:

> calibrazione (file: 63.2) → l'utente preme "Salva Configurazione" → la GUI riversa il suo
> dizionario, che ha ancora 70.0 → **calibrazione persa in silenzio**.

Per questo `calibration_distance()` **restituisce** il valore, e la GUI aggiorna sia il
proprio `self.config` sia la StringVar del campo "Altezza riferimento" della tab
Configurazione — è quella StringVar che `save_config_changes` rilegge al salvataggio.

Il bottone si rifiuta di calibrare se la lettura periodica è in corso: il sensore è uno solo,
e due impulsi ultrasonici sovrapposti falserebbero entrambe le misure. Una calibrazione
falsata è insidiosa perché sposta **tutte** le misure successive.

### 12.7 Il ciclo periodico

```python
p = self._params()
while not self._stop_event.is_set():
    result = self.read_now()          # read_now salva gia' su file
    if result is not None and on_update is not None:
        on_update(result)
    self._stop_event.wait(p['interval_days'] * SECONDS_PER_DAY)
```

La **prima misura parte subito** all'avvio e solo dopo si attende l'intervallo: diversamente,
con una cadenza giornaliera, l'utente non vedrebbe alcun dato per 24 ore. L'attesa usa
`threading.Event` (§18), quindi il bottone "Arresta Lettura" interrompe immediatamente anche
un'attesa di un giorno intero.

Il conteggio **non è persistito**: dopo un riavvio del programma riparte da zero, con una
misura immediata. Per una cadenza giornaliera è accettabile.

### 12.8 La tab "Crescita" e il grafico

Mostra l'altezza dell'ultima misura, la sua data, un grafico dell'andamento nel tempo e la
tabella data/altezza. Tutti i valori sono in **cm**. I bottoni sono "📏 Misura Adesso",
"▶️ Attiva Lettura", "⏹️ Arresta Lettura" e "📐 Calibrazione" (§12.6).

Il grafico è disegnato con le **primitive native di `tk.Canvas`** (`create_line`,
`create_oval`), non con matplotlib. La scelta è dettata dall'hardware: su un Raspberry Pi
Zero W (512 MB di RAM, single core) `matplotlib` costerebbe ~2-4 s di import all'avvio della
GUI e decine di MB residenti. Il costo *non* sarebbe nel disegno — con una misura ogni giorno
i punti sono al massimo `history_len` e il ridisegno è rarissimo — ma nella libreria stessa.
Le primitive Tk sono già in memoria e bastano per una spezzata.

> Nota: `daily_th_processor.py` (§16.1) usa matplotlib, ma in un **processo separato**, con
> import lazy dentro la funzione e backend `Agg`: non pesa mai sulla GUI.

Il ridisegno è agganciato all'evento `<Configure>` (quindi segue il ridimensionamento della
finestra) e viene rifatto dopo ogni misura. Con meno di due punti il Canvas mostra un
placeholder testuale invece di una spezzata degenere.

### 12.9 Nota hardware

I due HC-SR04 sono entrambi sull'Arduino (§5.12) e convivono senza conflitti perché usano
**coppie di pin distinte** — `2/3` il serbatoio, `4/5` la crescita — dichiarate in
`config.yaml` e trasmesse dentro il comando `read_us`. Le misure non si sovrappongono mai
nemmeno nel tempo: il lock della scheda (§5.7) serializza comando e risposta, quindi due
job che chiedono una distanza nello stesso istante vengono serviti uno dopo l'altro.

Il **partitore di tensione** che era obbligatorio sul Raspberry (ECHO a 5 V contro GPIO a
3.3 V) **non serve più** su nessuno dei due sensori: l'Arduino lavora nativamente a 5 V.

I pin indicati in `config.yaml` vanno comunque allineati al cablaggio reale — è l'unica cosa
che il software non può verificare da solo. Il pulsante **Prova** della card "Schede Arduino"
(§5.9) serve esattamente a questo: se i pin sono sbagliati risponde `ERRPIN`, se il sensore
non è collegato risponde `ERR`, se è tutto a posto risponde una distanza.


---

## 13. Spettrometro AS7265x — indice MCARI2

Modulo `sensors/spectrometer/mcari2_as7265x.py`. Misura lo stato di salute della pianta con
il sensore **SparkFun Triad AS7265x** (18 canali, 410–940 nm, bus I2C).

### 13.1 Import tollerante

```python
try:
    import qwiic_as7265x
    _HW_AVAILABLE = True
except ImportError:
    qwiic_as7265x = None
    _HW_AVAILABLE = False
```

Il modulo resta importabile su un PC senza la libreria: le funzioni di **solo calcolo**
(`mcari2`, `compute_reflectance`, `evaluate_MCAR2`, `interpreta_mcari2`) restano usabili e
testabili fuori dal Raspberry.

### 13.2 Mappatura delle bande

MCARI2 richiede tre bande, mappate sui getter della libreria:

| Banda | λ nominale | Canale AS7265x | Getter |
|---|---|---|---|
| GREEN | ~550 nm | 560 nm | `get_calibrated_g()` |
| RED | ~670 nm | 680 nm | `get_calibrated_s()` |
| NIR | ~800 nm | 810 nm | `get_calibrated_v()` |

La mappatura sta in un unico posto (`GREEN_GETTER`/`RED_GETTER`/`NIR_GETTER`) e viene
risolta con `getattr`. `CHANNEL_MAP` elenca tutti i 18 canali per la diagnostica.

### 13.3 Il punto critico: riflettanza, non irradianza

Il sensore restituisce **irradianza** (µW/cm²), che dipende anche dall'intensità della luce
incidente; MCARI2 è invece definito sulla **riflettanza** (0–1). Serve quindi una taratura:

```
R(λ) = lettura_sul_target(λ) / lettura_sul_riferimento_bianco(λ)
```

`calibrate(sensor)` misura un pannello bianco con il LED integrato acceso e salva i valori
in `spectro_calibration.json` insieme a **gain e cicli di integrazione**. `load_calibration()`
avvisa se i parametri correnti differiscono da quelli della taratura — riferimento e target
devono essere acquisiti nelle stesse condizioni, altrimenti il rapporto non ha senso fisico.

```python
GAIN = qwiic_as7265x.kGain16x if _HW_AVAILABLE else 2   # 16x
INTEGRATION_CYCLES = 50    # tempo di integrazione ≈ valore × 2.8 ms
SETTLE_TIME = 0.3          # assestamento del LED prima della misura [s]
```

### 13.4 La formula MCARI2

**MCARI2** (*Modified Chlorophyll Absorption in Reflectance Index 2*) stima clorofilla e LAI,
ed è sensibile allo stress idrico/nutrizionale (in particolare la carenza di azoto).

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

Il **numeratore** misura l'assorbimento della clorofilla: il termine `NIR − RED` è alto per
vegetazione sana (la clorofilla assorbe il rosso e riflette il vicino infrarosso), mentre la
sottrazione di `1.3·(NIR − GREEN)` corregge l'effetto della riflettanza nel verde.
Il **denominatore** è il fattore di normalizzazione che riduce l'influenza del suolo di sfondo.

### 13.5 Catena di elaborazione e interpretazione

```
init_sensor() -> calibrate() -> [JSON di taratura]
                                        |
read_bands() --raw--> compute_reflectance() --R--> mcari2() -> save_measurement()
```

`evaluate_MCAR2(target_bands, reference_bands=None)` è la funzione di alto livello: se il
riferimento non è fornito, carica l'ultima taratura salvata.

Soglie di `interpreta_mcari2()`:

| MCARI2 | Interpretazione |
|---|---|
| < 0.4 | Possibile stress idrico o carenza nutrizionale (es. azoto) |
| 0.4 – 0.7 | Coltura sana |
| 0.7 – 0.9 | Coltura molto sana, nessuna carenza rilevata |
| > 0.9 | Fuori dai range tipici attesi, verificare la misura |

`test_spectrometer.py` è uno script interattivo a menu per il campo: diagnostica dei 18 canali
→ taratura sul bianco → misura MCARI2.

---

## 14. Camera

La logica vive in `managers_classes/camera_manager.py` (`CameraManager`, stessa forma degli
altri manager); `camera/takePicture.py` e `camera/camera.py` sono wrapper CLI che leggono
`config.yaml` e comandano lo stesso manager che comanda la GUI.

### 14.1 Acquisizione periodica

`start_acquisition()` / `stop_acquisition()` / `is_acquiring()` — un thread daemon scatta
ogni `camera.separation_hours` ore in `camera.saving_dir`. L'attesa usa
`_stop_event.wait(interval)` e non `sleep`: con un intervallo di due ore, un `sleep` avrebbe
reso "Disattiva acquisizione" senza effetto fino allo scatto successivo.

Ogni scatto produce **due file**: uno storico con timestamp
(`YYYY-MM-DD_HH-MM-SS.jpg`) e una copia a nome fisso `image.jpg`, che è quella che
`uploader.py` carica su GitHub — il nome fisso permette al sito di puntare sempre allo
stesso URL per l'ultima foto.

### 14.2 Anteprima dal vivo

`start_preview()` / `stop_preview()` / `toggle_preview()` / `is_previewing()` — apre la
finestra `Preview.QTGL` e la tiene aperta finché non viene chiusa. Non c'è più un timer
fisso: prima `camera.py` mostrava l'anteprima per 60 secondi esatti e poi usciva.

### 14.3 Perché i due usi si escludono a vicenda

La Picamera2 è una **risorsa singola**: istanziarla due volte fa fallire l'anteprima o,
peggio, lo scatto schedulato. Il manager lo impedisce da entrambi i lati —
`start_preview()` ritorna `False` se l'acquisizione è attiva, `start_acquisition()` ritorna
`False` se l'anteprima è aperta — e un `threading.Lock` protegge l'accesso vero e proprio
all'oggetto. La GUI traduce il `False` in un pop-up che spiega quale processo va fermato
prima.

### 14.4 La tab Camera

Tre bottoni ("Attiva acquisizione", "Disattiva acquisizione", "Attiva/Disattiva camera",
quest'ultimo con il testo che segue lo stato) e, in basso, l'**ultima foto acquisita** con
data e ora. La foto viene riletta da disco all'avvio da `load_last_photo()`, che prende il
file più recente ignorando `image.jpg` e ricava la data dal **nome** e non dal mtime (che
una copia del file falserebbe): senza, con `separation_hours: 2` la scheda resterebbe vuota
per due ore dopo ogni avvio.

Il rendering passa da `_show_image()`, che usa **Pillow**: `tk.PhotoImage` legge solo PNG e
GIF, mentre le foto sono JPG. Se Pillow manca, la scheda mostra un messaggio invece di
fallire (`sudo apt install python3-pil.imagetk`). Il riferimento all'immagine va tenuto
sulla label: Tk non lo conserva e senza di esso il garbage collector la fa sparire appena
disegnata.

---

## 15. Persistenza dei dati: formati dei file

Quasi tutti i moduli scrivono file **tabulari giornalieri**, separati da tabulazioni, in un
formato coerente tra loro. L'unica eccezione è la crescita, per il motivo spiegato sotto.

### TH (ambient) — `TH_YYYY_MM_DD.txt`

```
2026/06/28 14:32:01	 23.40C	 61.20%	 1.0234kPa
```

### TANK — `TANK_YYYY_MM_DD.txt`

```
datetime			 dist_cm	 lvl_cm	 vol_L	 fill_%
2026/06/28 14:32:01	  12.4	  19.6	  17.64	 65.3
```

### WATER (pH ed EC) — `WATER_YYYY_MM_DD.txt`

```
datetime			 ph	 ec_uScm	 tds_ppm	 sal_psu
2026/09/05 09:00:12	 6.12	 --	 --	 --
2026/09/05 09:04:31	 --	 1250.0	 625.0	 0.62
```

Unico file per due sonde con intervalli indipendenti: le colonne non misurate in quella riga
valgono `--`, che rileggendo diventa `None` (§10.5).

### ERRORS — `ERRORS_YYYY_MM_DD.txt`

```
datetime	source	message
2026/09/05 09:41:03	US_water	Non è stato possibile leggere il sensore ultrasonico del serbatoio, controlla il motivo: ...
```

`source` è una chiave di `SENSOR_SPECS` (`pH`, `EC`, `US_water`, `US_plant`). Tabulazioni e
a capo dentro il messaggio sono normalizzati a spazi prima della scrittura, così una riga
resta una riga (§11.2).

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

Doppia eccezione rispetto a tutti gli altri: è l'unico file **CSV** (separato da virgole,
non da tabulazioni) ed è l'unico **cumulativo** invece che giornaliero. Il motivo è la
cadenza: con una misura ogni giorno o più, un file al giorno conterrebbe **una riga sola**, e
ricostruire lo storico per il grafico significherebbe aprire decine di file per leggere un
valore ciascuno. Un unico file in append rende `load_growth_data()` una singola lettura.

La **data usa lo stesso formato dei file TH** (`%Y/%m/%d %H:%M:%S`), così i dati di crescita
restano incrociabili con quelli di temperatura e umidità.

I file TANK, WATER, ERRORS, SPECTRO e GROWTH scrivono l'**header solo se il file non esiste**
(`write_header = not os.path.exists(file_path)`); i file TH non hanno header. L'apertura è
sempre in modalità append (`'a'`), quindi un riavvio del programma non perde i dati.

### Questi file vengono anche riletti

Non sono solo un archivio: **ogni formato ha un lettore**, ed è ciò che
permette alla scheda Riepilogo (§2.3) di mostrare l'ultimo valore noto già all'avvio, prima
che qualsiasi sensore sia stato interrogato.

| File | Lettore | Cosa restituisce |
|---|---|---|
| TH | `load_last_th()` (§7.4) | ultima misura T/H/VPD |
| TANK | `load_last_tank()` (§9.6) | ultimo livello |
| WATER | `load_last_water()` / `load_water_history()` (§10.5) | ultimo pH **e** ultima EC, cercati separatamente |
| SPECTRO | `load_measurements()` → `SpectroManager.load_history()` | ultime N misure MCARI2 |
| GROWTH | `load_growth_data()` → `PlantGrowthManager.load_history()` | ultime N altezze |
| ERRORS | `load_errors()` (§11.2) | errori di un giorno, per la GUI e per l'uploader |

Tutti sono di **sola libreria standard** e tolleranti: header, righe vuote e righe malformate
vengono saltati, e l'assenza del file non è un errore ma un `None`/lista vuota. È la stessa
filosofia del parsing giornaliero (§16.1): un dato corrotto da un'interruzione di corrente non
deve impedire di leggere tutti gli altri.

---

## 16. Elaborazione giornaliera e upload

### 16.1 `daily_th_processor.py`

`DailyTHManager` è schedulato **ogni giorno alle 00:01** ed elabora il file del giorno
precedente. Legge le directory dalla sezione `Daily_Data` di `config.yaml`
(`th_data_dir`, `plot_output_dir`); le costanti nel modulo restano solo come default.
Si comanda dalla tab Ambient ("Attiva Daily" / "Arresta Daily") oppure da riga di comando
(`python3 managers_classes/daily_th_processor.py`).

La pipeline di `daily_job()`:

```
1. get_yesterday_filename()  -> path di TH_<ieri>.txt
2. parse_th_file()           -> DataFrame pandas
3. compute_statistics()      -> medie, max, min
4. generate_plot()           -> plot.png (3 subplot)
5. call_uploader()           -> upload medie + plot su GitHub
```

**Parsing** — il file va riletto da testo, con le unità di misura attaccate ai numeri
(`23.40C`, `61.20%`), quindi si estrae il numero con una regex:

```python
timestamp   = datetime.strptime(parts[0].strip(), '%Y/%m/%d %H:%M:%S')
temperature = float(re.search(r'[\d.]+', parts[1]).group())
humidity    = float(re.search(r'[\d.]+', parts[2]).group())
vpd         = float(re.search(r'[\d.]+', parts[3]).group())
```

Le righe malformate vengono **loggate e saltate**, non fanno fallire il job: un giorno di dati
non viene perso per una riga corrotta da un'interruzione di corrente.

**Statistiche** — media/max/min per T, H e VPD (T e H arrotondati a 2 decimali, VPD a 3).

**Grafico** — 3 subplot verticali (T, H, VPD) con `matplotlib`, backend `Agg`
(non interattivo, necessario per generare immagini senza display), asse X formattato `%H:%M`
con tick ogni 2 ore, salvato a 250 dpi come `plot.png`.

**Upload** — invoca `uploader.py` via `subprocess.run` con `sys.executable` (garantisce lo
stesso interprete Python, quindi lo stesso ambiente virtuale).

**Primo giro senza upload** — `start()` esegue subito il job una volta con `upload=False`,
poi entra nello scheduler. Serve a popolare la tab Ambient: senza, statistiche e plot
resterebbero vuoti fino alla mezzanotte successiva. L'upload è saltato perché quei dati sono
già stati caricati dal giro precedente.

**Cancellazione del job** — all'uscita dal loop si chiama `schedule.cancel_job(job)`:
`schedule` tiene una coda globale, quindi senza cancellazione ogni riavvio dalla GUI
accumulerebbe un job duplicato.

### 16.1.1 La sezione "Elaborazione giornaliera" nella tab Ambient

Sotto i valori istantanei di T/H/VPD, la scheda mostra i risultati dell'ultimo job: bottoni
di avvio/arresto, una tabella **T/H/VPD × max/min/media** (le chiavi sono quelle restituite
da `compute_statistics`) e il `plot.png` generato. `refresh_daily_section()` gira ogni 2 s
ma ridisegna solo quando cambia il giorno elaborato: ricaricare il PNG da disco ogni tick
sarebbe spreco puro su un Pi Zero W — stessa logica di `_cambiato()` nel Riepilogo.

### 16.2 `uploader/uploader.py`

CLI a sottocomandi che pubblica su GitHub via **API REST**, usata come backend dati del sito.

**Cosa viene pubblicato.** L'upload periodico parte da `AmbientManager`, che ha la cadenza più
fitta, ma non pubblica solo temperatura e umidità: prima di caricare chiama
`extra_data_provider`, cioè `aeroHelper.latest_extra_data()` (§3), e aggiunge al JSON gli
ultimi valori noti di livello serbatoio, pH, EC/TDS/salinità, altezza della pianta e i
**dieci errori di lettura più recenti** (§11).

Il sito riceve così **una fotografia coerente** della serra a ogni upload, invece di un
aggiornamento separato per sonda. Le grandezze mai misurate — o le sonde non ancora installate
— semplicemente non compaiono nel JSON: l'alternativa, pubblicare zero, farebbe apparire sul
sito una misura che nessuno ha fatto.

| Comando | Effetto |
|---|---|
| `data -t -hu -vpd -ts` | Scrive `dati.json` e carica JSON + immagine |
| `averages -avgt -avgh -avgvpd -maxT ... -ts` | Scrive `avg_data.json` e carica JSON + plot |
| `image` | Carica solo `image.jpg` |
| `plot` | Carica solo `plot.png` |

Credenziali da variabili d'ambiente (`.env` via `python-dotenv`): `GITHUB_TOKEN`,
`GITHUB_USR`, `GITHUB_REPO`, `GITHUB_BRANCH`. **Nessun segreto è nel codice.**

**Protocollo di aggiornamento** — l'API GitHub Contents richiede lo SHA del file esistente per
sovrascriverlo, quindi ogni upload è una sequenza GET → PUT:

```python
response = requests.get(url_data, headers=headers)   # 1. leggi lo SHA attuale
sha = response.json()["sha"]

payload = {"message": ..., "content": encoded_content, "sha": sha, "branch": BRANCH}
put_response = requests.put(url_data, headers=headers, json=payload)   # 2. sovrascrivi
```

Il contenuto è codificato in **base64** (richiesto dall'API), sia il testo che i binari.

**Retry** — il decoratore `@retry_with_exponential_backoff` avvolge tutte le funzioni di
upload: 3 tentativi, propagando l'eccezione all'ultimo. Serve a assorbire i fallimenti di
rete transitori tipici di una connessione domestica (vedi §20 per un difetto nel calcolo del
delay).

---

## 17. Logging

Configurazione centralizzata in `aeroHelper.__init__`:

```python
logging.basicConfig(
    level=getattr(logging, self.configs["log"]["level"].upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, self.configs["log"]["filename"])),
        logging.StreamHandler()
    ])
```

Il logger è **creato una volta e passato a tutti i manager** dal costruttore: un'unica
destinazione, un unico formato. Quando gira la GUI, `setup_gui_logging_handler()` aggiunge un
terzo handler (`GUILoggingHandler`), così lo stesso messaggio finisce su file, console e
pannello grafico.

Il modulo standalone `ultrasonic_measurement.py` ha invece un proprio `setup_logging()` con
`TimedRotatingFileHandler` (rotazione a mezzanotte, 30 giorni di storico), usato solo quando
è eseguito da solo.

Convenzione dei messaggi: prefisso con la categoria in maiuscolo — `AEROPONICS:`,
`IDROPONICS:`, `AMBIENT:`, `IR_CONTROLLER:`, `TANK:`, `WATER:`, `GROWTH:`, `ARDUINO:`,
`ERRORI:` — così i log sono filtrabili con `grep`.

Gli errori delle sonde passano **anche** da `ErrorRecorder.record()` (§11), che li scrive nel
proprio file oltre che nel log: nel file di log compaiono come `ERROR` con il prefisso della
sorgente (`US_water:`, `pH:`, …).

---

## 18. Modello di concorrenza (thread)

Il sistema è **multi-thread ma senza lock**. Il modello:

| Thread | Avviato da | Ciclo |
|---|---|---|
| Main / Tk | `main.py` (shell) o `gui.py` | lettura dei comandi o `mainloop()` |
| AEROPONICS | `start_aeroponics()` | `while self.aeroponics_job_active` |
| IDROPONICS | `start_idroponics()` | `while self.idroponics_job_active` |
| Job generici (N) | `start_general(name)` | `while self.general_jobs_active[name]` |
| Ambient | `start_reading()` | `while not self._stop_event.is_set()` |
| Climate | `climate.start()` | `while not self._stop_event.is_set()` |
| Tank | `tank.start_reading()` | `while not self._stop_event.is_set()` |
| **pH** | `water.start_ph_reading()` | `while not self._ph_stop_event.is_set()` |
| **EC** | `water.start_ec_reading()` | `while not self._ec_stop_event.is_set()` |
| Spectro | `spectro.start_reading()` | `while not self._stop_event.is_set()` |
| PlantGrowth | `plant_growth.start_reading()` | `while not self._stop_event.is_set()` |
| Camera | `camera.start_acquisition()` | `while not self._stop_event.is_set()` |
| Daily TH | `daily_th.start()` | `while not self._stop_event.is_set()` |
| Pulse pompa | `runner()` | one-shot, muore da solo |

Tutti sono `daemon=True`: alla chiusura del programma muoiono senza richiedere join.

**Due meccanismi di arresto**, con proprietà diverse:

1. **Flag booleano** (`JobsManager`) + `sleep(1)` — l'arresto richiede fino a 1 secondo.
   Accettabile per i job delle pompe, il cui ciclo è di minuti.
2. **`threading.Event`** (`Ambient`, `Climate`, `Tank`, `Spectro`, `PlantGrowth`, `Camera`,
   `DailyTH`) + `_stop_event.wait(interval)` — arresto **immediato**. Indispensabile qui,
   dove gli intervalli vanno dai 5 minuti a un giorno intero (`PlantGrowth`, `DailyTH`) e la
   GUI deve rispondere subito al bottone Stop.

**Quasi assenza di lock.** Le variabili condivise sono `last_T`/`last_H` (scritte da Ambient,
lette da Climate) e i flag booleani. La correttezza si appoggia sull'atomicità delle
assegnazioni di riferimenti in CPython (GIL): letture e scritture di un `float` o `bool`
singolo non possono interlacciarsi. Il codice **non fa mai read-modify-write** su questi
valori, che è il caso in cui servirebbe un lock.

Le eccezioni sono **tre**, e sono tutte casi in cui la risorsa condivisa non è un valore ma
un dispositivo:

| Lock | Risorsa protetta | Perché |
|---|---|---|
| `ArduinoBoard._lock` (uno per scheda) | la porta seriale | fino a quattro job possono chiedere una misura alla stessa scheda; il lock serializza la **coppia** comando+risposta, altrimenti due letture si scambierebbero le risposte (§5.7) |
| `ErrorRecorder._lock` | il `deque` e il file degli errori | gli errori arrivano da thread diversi, uno per sonda (§11.2) |
| `CameraManager._lock` | l'oggetto `Picamera2` | non può essere aperto due volte (§14.3) |

Il lock della seriale è **per scheda**, non globale: con due Arduino le letture su schede
diverse restano parallele. È anche il punto in cui il sistema diventa, di fatto, sequenziale
sulle sonde di una stessa scheda — e con una `read_pH` che dura 8 secondi (§5.6), è bene
saperlo: una misura del serbatoio che capiti in quel momento aspetta.

**Thread-safety della GUI**: Tkinter non è thread-safe; nessun thread di lavoro tocca i
widget. I dati passano per callback (`on_update`) e per la `Queue` dei log.

---

## 19. Riepilogo delle formule

| Grandezza | Formula | Dove |
|---|---|---|
| Pressione di vapore saturo | `es(T) = 0.6108 · exp(17.27·T / (T + 273.3))` [kPa] | `AmbientManager.VPD` |
| Pressione di vapore effettiva | `ea = H · es(T) / 100` | `AmbientManager.VPD` |
| **VPD** | `VPD = es(T) − ea` [kPa] | `AmbientManager.VPD` |
| Modificatore di irrigazione | `t_mod = 1/(exp(−0.2·(T−Topt)) + 1) − 0.5` | `JobsManager.T_modifier` |
| Nuova attesa irrigazione | `t_new = t_old − t_old · t_mod` | `JobsManager.T_modifier` |
| Distanza ultrasonica | `d = durata_echo [µs] · 0.0343 / 2` [cm] | `measureDistanceCm()` (sketch Arduino) |
| **Altezza pianta** | `h_plant = riferimento − d`, con clipping a 0 [cm] | `PlantGrowthManager.read_now` |
| Livello acqua | `livello = H_tanica − (d − offset)` [cm] | `distance_to_water_volume` |
| Volume | `V = livello · area / 1000` [L] | `distance_to_water_volume` |
| Riempimento | `fill% = livello / H_tanica · 100` | `distance_to_water_volume` |
| Riflettanza | `R(λ) = target(λ) / riferimento(λ)` | `compute_reflectance` |
| **MCARI2** | `1.5·[2.5·(NIR−RED) − 1.3·(NIR−GREEN)] / √[(2·NIR+1)² − (6·NIR − 5·√RED) − 0.5]` | `mcari2` |

---

## 20. Anomalie rilevate nel codice

Difetti individuati durante la stesura di questo documento. Sono documentati qui perché
riguardano le formule e le logiche descritte sopra; **nessuno è stato corretto**.

### 20.1 `T_modifier()` — variabile usata prima di essere definita

`helper_aeroGreenHouse.py:288`

```python
t_new = t_new - t_new * t_modifier   # t_new non è ancora definita
```

Il parametro d'ingresso si chiama `t_old`, ma la riga usa `t_new` su entrambi i lati:
la funzione solleverebbe `UnboundLocalError` a ogni chiamata. Sembra dover essere
`t_new = t_old - t_old * t_modifier`. Attualmente la funzione non ha chiamanti, quindi il
difetto è latente.

### 20.2 `VPD()` — costante della formula di Tetens

`helper_aeroGreenHouse.py:358`

```python
es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))
```

La formulazione standard di Tetens (FAO Irrigation and Drainage Paper 56) usa **237.3**,
non 273.3 — valore che sembra una confusione con la costante di conversione Kelvin (273.15).
Con `237.3`, a T = 23 °C si ha es ≈ 2.81 kPa; con `273.3` si ottiene ≈ 2.55 kPa, circa il
**9% in meno**. L'errore cresce con la temperatura. Il VPD registrato finora risulta quindi
sottostimato in modo sistematico; da valutare se correggere (e come trattare lo storico).

### 20.3 `_read_loop()` — logger invocato come funzione

`helper_aeroGreenHouse.py:459`

```python
except:
    self.logger(f"AMBIENT: not able to upload the ambient data online. ...")
```

Manca `.error`: `self.logger(...)` solleva `TypeError` perché un `Logger` non è chiamabile.
L'eccezione viene poi catturata dal `try` esterno, quindi il ciclo sopravvive, ma il
messaggio diagnostico **non viene mai scritto** — un fallimento di upload appare nel log
come un generico "Errore lettura AMBIENT: 'Logger' object is not callable", che indica il
punto sbagliato.

### 20.4 `retry_with_exponential_backoff` — il backoff non è esponenziale

`uploader/uploader.py:65`

```python
BASE_DELAY = 1
delay = BASE_DELAY ** (attempt - 1)   # 1**0=1, 1**1=1, 1**2=1
```

Con `BASE_DELAY = 1` la potenza vale sempre 1: i retry avvengono a distanza fissa di 1 s,
non 1s/2s/4s come dichiara il docstring. La forma corretta sarebbe `BASE_DELAY * (2 ** (attempt - 1))`.

### 20.5 `evaluate_and_send()` — nomi dei comandi disallineati

`ir_controller/ir_controller.py:83`

```python
if self.last_command_sent in ('Tlow', 'Hlow') and ...:   # controllo del timeout
```

Ma i comandi effettivamente inviati e memorizzati sono `'T_low_21'` e `'dry'`, mai `'Tlow'`
o `'Hlow'`. La condizione non è quindi mai vera e il **controllo di `time_max_on` non
interviene**: il condizionatore non viene mai spento dal timeout di sicurezza, ma solo dal
rientro di T o H sotto soglia. La lista sembra dover essere `('T_low_21', 'dry')`.

### 20.6 La configurazione è caricata due volte, in due dizionari distinti

`gui.py:37` e `helper_aeroGreenHouse.py:32`

```python
self.config = self.load_config()   # gui.py:37   -> dizionario A
self.ah = aeroHelper()             # gui.py:48   -> dentro, dizionario B
```

Lo stesso `config.yaml` viene letto **due volte**, in due oggetti separati. `aeroHelper` passa
il **suo** (B) a tutti i manager per riferimento, quindi tutti i manager sono coerenti tra loro;
ma la GUI usa A, e i due non comunicano. Conseguenze concrete:

- **Le modifiche salvate dalla tab Configurazione non raggiungono i manager** finché il
  processo non viene riavviato: la GUI scrive il file e aggiorna A, i manager continuano a
  leggere B.
- **Le modifiche ai job** (`gui.py:696/718/732` aggiungono, eliminano e modificano voci di
  `gpio_pins` in A) non arrivano mai allo scheduler, che vive su B.
- **Rischio di sovrascrittura**: `save_config()` riversa l'**intero** A. Chiunque scriva sul
  file passando da B — come fa la calibrazione della crescita (§12.6) — vedrebbe il proprio
  valore cancellato dal primo "Salva Configurazione". La calibrazione lo neutralizza
  riallineando esplicitamente A e la StringVar, ma è una toppa sul sintomo.

La cura strutturale sarebbe fare in modo che A e B siano **lo stesso oggetto** (`self.ah`
costruito per primo, poi `self.config = self.ah.configs`) e che ogni ricarica **muti il
dizionario sul posto** invece di riassegnarlo — `reload_config_tab:872` fa `self.config =
self.load_config()`, che romperebbe l'aliasing al primo click su "Ricarica". Poiché i manager
rileggono `self.configs` ad ogni uso, la mutazione sul posto darebbe l'aggiornamento a caldo
quasi gratis; resterebbero fuori i valori catturati una volta sola (pin GPIO già configurati,
intervalli già congelati negli `Scheduler`, i cinque attributi copiati da `IRController`).

### 20.7 Il contratto Arduino non è verificabile a runtime

`SENSOR_SPECS` (Raspberry) e `COMMANDS[]` (Arduino) devono combaciare, ma **niente lo
controlla**: se lo sketch caricato sulla scheda è più vecchio del codice Python, un comando
nuovo riceve `ERR:<comando>` e diventa un generico "lettura non attendibile", senza dire che
la causa vera è la versione del firmware.

Lo stesso vale per l'ordine dei valori dell'EC: se qualcuno abilitasse `O,SG,1` nello sketch
senza aggiungere la coppia corrispondente in `SENSOR_SPECS['EC']['values']`, `read_named()`
continuerebbe a funzionare — assegnando però i nomi sbagliati ai valori.

Un comando `version` che risponda con l'identificativo dello sketch, confrontato all'avvio,
risolverebbe entrambi i casi.

### 20.8 Note minori

- `measure_distance_avg()` restituisce la mediana ma il nome e il parametro `n_samples`
  suggeriscono la media — il docstring lo chiarisce, il nome no. Da quando esiste anche
  `measure_distance_mean()`, che la media la calcola davvero (§12.3), l'ambiguità è peggiorata:
  le due funzioni stanno affiancate nello stesso modulo e i nomi non dicono che differiscono
  proprio nella statistica. `measure_distance_median()` sarebbe il nome corretto per la prima.
- `measure_dht22()` e `_read_loop()` contengono due copie della stessa logica di lettura DHT22.
- `eval(f"adafruit_dht.DHT22(board.D{gpio})")` usa `eval` dove basterebbe
  `getattr(board, f"D{gpio}")`.
- `AmbientManager.upload_data_on_web()` usa `os.system` con path relativo
  (`python uploader/uploader.py`): funziona solo se il processo è avviato dalla directory del
  progetto.
- `main.py` cerca i job per `name` come `gui.py`; l'indice posizionale sopravvive solo nella
  sintassi di `-save set gpio_pins.0.interval`, dove è esplicito e voluto.
- `WATER_*.txt` usa `\t\t\t` nell'header e `\t ` fra i campi, come `TANK_*.txt`: l'allineamento
  a schermo dipende dalla larghezza dei valori. È leggibile, non tabulato in senso stretto.
- `TankManager` importa `ultrasonic_measurement` **dentro** `__init__` (import ritardato) per
  non tirarsi dietro `RPi.GPIO` quando il modulo serve solo per la matematica del volume.
