# AeroGreenHouse — Documentazione tecnica

Documento di riferimento sui principi di funzionamento del codice, organizzato
**dall'alto verso il basso**: dai punti di ingresso (ciò che l'utente avvia), attraverso
il coordinatore e i manager di categoria, fino alla fisica dei sensori e alle formule
implementate.

Il sistema gira su **Raspberry Pi** e gestisce una serra aeroponica/idroponica:
comanda le pompe via GPIO, legge temperatura/umidità, controlla il condizionatore via
infrarossi, monitora il livello del serbatoio e l'altezza delle piante con due sensori a
ultrasuoni, misura l'indice di vegetazione MCARI2 con uno spettrometro e pubblica i dati
online.

---

## Indice

1. [Architettura generale](#1-architettura-generale)
2. [Punti di ingresso](#2-punti-di-ingresso)
3. [Il coordinatore: `aeroHelper`](#3-il-coordinatore-aerohelper)
4. [Configurazione: `config.yaml`](#4-configurazione-configyaml)
5. [JobsManager — pompe e GPIO](#5-jobsmanager--pompe-e-gpio)
6. [AmbientManager — DHT22 e VPD](#6-ambientmanager--dht22-e-vpd)
7. [ClimateManager e IRController — condizionatore](#7-climatemanager-e-ircontroller--condizionatore)
8. [TankManager — livello serbatoio (HC-SR04)](#8-tankmanager--livello-serbatoio-hc-sr04)
9. [PlantGrowthManager — altezza della pianta (HC-SR04)](#9-plantgrowthmanager--altezza-della-pianta-hc-sr04)
10. [Spettrometro AS7265x — indice MCARI2](#10-spettrometro-as7265x--indice-mcari2)
11. [Camera](#11-camera)
12. [Persistenza dei dati: formati dei file](#12-persistenza-dei-dati-formati-dei-file)
13. [Elaborazione giornaliera e upload](#13-elaborazione-giornaliera-e-upload)
14. [Logging](#14-logging)
15. [Modello di concorrenza (thread)](#15-modello-di-concorrenza-thread)
16. [Riepilogo delle formule](#16-riepilogo-delle-formule)
17. [Anomalie rilevate nel codice](#17-anomalie-rilevate-nel-codice)

---

## 1. Architettura generale

Il codice è organizzato a strati. Ogni strato conosce solo quello sottostante:

```
        UTENTE
           |
   +-------+--------+
   |                |
 gui.py          main.py            <- Strato 1: punti di ingresso
   |                |
   +-------+--------+
           |
      aeroHelper                    <- Strato 2: coordinatore (config, log, GPIO)
           |
   +-------+-------+-------+--------+---------+------------+
   |       |       |       |        |         |            |
 Jobs   Ambient Climate  Tank    Spectro  PlantGrowth      <- Strato 3: manager
Manager Manager Manager Manager  Manager   Manager            di categoria
   |       |       |       |        |         |
 GPIO    DHT22  IRController HC-SR04    AS7265x   HC-SR04  <- Strato 4: driver
 pompe          + piir    ultrasonic_measurement  (2° sensore)   / hardware
   |       |       |       |        |         |
   +-------+-------+-------+--------+---------+
           |
    file .txt giornalieri  +  GROWTH.csv cumulativo
           |
   daily_th_processor.py -> uploader.py -> GitHub -> sito web
```

Il principio guida è la **separazione tra interfaccia e logica**: `gui.py` contiene
soltanto widget e callback, mentre tutta la logica di processo (thread, scheduling,
formule, I/O sui file) vive nei manager sotto `managers_classes/`. La GUI non sa *come* si
attiva una pompa: chiama `self.ah.jobs.start_aeroponics()` e riceve un booleano.

### Mappa dei file

| File | Ruolo |
|---|---|
| `main.py` | Avvio headless (solo aeroponica + idroponica) |
| `gui.py` | Pannello di controllo Tkinter (9 tab) |
| `helper_aeroGreenHouse.py` | **Cuore del sistema**: `aeroHelper`, che istanzia i 6 manager |
| `managers_classes/` | I manager di categoria, uno per file |
| `managers_classes/plant_growth.py` | Misura dell'altezza pianta + I/O di `GROWTH.csv` |
| `managers_classes/data_config.py` | Arrotondamento dei dati di misura (decimali / cifre significative) |
| `config.yaml` | Unica fonte di verità per pin, tempi e soglie |
| `ir_controller/ir_controller.py` | Invio comandi IR al condizionatore |
| `ir_controller/ac_remote.json` | Codifica dei comandi del telecomando (per `piir`) |
| `sensors/ultrasonic_sensor/ultrasonic_measurement.py` | Fisica della misura HC-SR04 |
| `sensors/spectrometer/mcari2_as7265x.py` | Acquisizione spettrale e calcolo MCARI2 |
| `camera/takePicture.py` | Scatto foto periodico |
| `daily_th_processor.py` | Statistiche e grafico giornalieri |
| `uploader/uploader.py` | Push di JSON/immagini su GitHub |

---

## 2. Punti di ingresso

Esistono **due modi** di avviare il sistema, mutuamente alternativi.

### 2.1 `main.py` — modalità headless

È il percorso minimo: istanzia `aeroHelper`, registra due job periodici con la libreria
`schedule` e cicla per sempre.

```python
ah = aeroHelper()

aeroJOB = schedule.every(ah.configs['gpio_pins'][0]['interval']).minutes.do(
    ah.runner, ah.pump_aerophonics,
    gpio=...['pin'], irrigation_time=...['on_time'])

idroJOB = schedule.every(ah.configs['gpio_pins'][1]['interval']).minutes.do(
    ah.runner, ah.pump_idrophonics, ...)

while True:
    schedule.run_pending()
    sleep(1)
```

Il ciclo `while True` interroga lo scheduler ogni secondo; alla scadenza dell'intervallo
`schedule` invoca `ah.runner`, che lancia la funzione della pompa **in un thread separato**
in modo che il ciclo principale non si blocchi durante l'irrigazione. Un `KeyboardInterrupt`
(Ctrl+C) chiama `ah.cleanup_gpios()` per rilasciare i pin.

Nota: `main.py` indicizza `gpio_pins` per **posizione** (`[0]` = aeroponica, `[1]` =
idroponica, `[2]` = sensore di umidità), quindi l'ordine delle voci in `config.yaml` è
vincolante per questo file.

### 2.2 `gui.py` — pannello di controllo

Istanzia `aeroHelper` una volta (`self.ah = aeroHelper()`) e costruisce un `Notebook`
Tkinter con 9 tab:

| Tab | Contenuto |
|---|---|
| **Configurazione** | Editing dei parametri di `config.yaml` (T_var, dht22, log, ir_control, tank, spectro, plant_growth) |
| **Processi Attivi** | Spie verde/rosso, aggiornate ogni secondo |
| **Gestione Job** | Treeview dei job; crea/modifica/elimina/attiva/disattiva |
| **Ambient** | Letture T/H/VPD, avvio/arresto della lettura periodica |
| **Climatizzatore** | Avvio/arresto del controllo automatico AC, ultimo comando IR |
| **Livelli Serbatoio** | Distanza, livello, volume, percentuale di riempimento |
| **Spettrometro** | Indice MCARI2, spia dello stato della pianta, taratura, storico |
| **Crescita** | Altezza pianta e data dell'ultima misura, grafico dell'andamento, tabella, calibrazione (§9.8) |
| **Output/Log** | Console colorata dei log in tempo reale |

La GUI usa tre meccanismi periodici basati su `root.after()` (quindi sul thread Tk, senza
bloccare l'interfaccia):

- `process_log_queue()` — ogni **100 ms**, svuota la coda dei log e li scrive nella console;
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

`get_process_states()` (gui.py:368) costruisce l'elenco delle spie interrogando
direttamente i flag dei manager:

```python
for job in self.config.get('gpio_pins', []):
    if job.get('what_type') == 'sensor':   # i sensori non sono processi
        continue
    if name == 'AEROPONICS':  active = jobs.aeroponics_job_active
    elif name == 'IDROPONICS': active = jobs.idroponics_job_active
    else:                      active = jobs.general_jobs_active.get(name, False)

states.append(("Lettura Ambient (T/H)",     self.ah.ambient.is_running()))
states.append(("Controllo Climatizzatore",  self.ah.climate.is_running()))
states.append(("Lettura Serbatoio",         self.ah.tank.is_running()))
states.append(("Lettura Spettrometro",      self.ah.spectro.is_running()))
states.append(("Misura Crescita",           self.ah.plant_growth.is_running()))
```

Le righe vengono **ricostruite solo se l'elenco delle chiavi cambia** (`_rebuild_status_rows`),
altrimenti si aggiorna soltanto il colore: evita di ridisegnare 6 widget al secondo su un
Raspberry Pi Zero.

---

## 3. Il coordinatore: `aeroHelper`

`aeroHelper.__init__()` (helper_aeroGreenHouse.py:735) esegue in sequenza:

1. **Carica la configurazione** — `load_config('config.yaml')` con `yaml.safe_load`.
2. **Configura il logging** — `logging.basicConfig` con due handler: file
   (`<log.directory>/<log.filename>`) e console.
3. **Inizializza la GPIO** — `initialize_gpio(configs)`, una sola volta per l'intero processo.
4. **Istanzia i sei manager**, passando a ciascuno `configs`, `logger` e (per i job) `gpios`:

```python
self.jobs         = JobsManager(self.configs, self.logger, self.gpios)
self.ambient      = AmbientManager(self.configs, self.logger)
self.climate      = ClimateManager(self.configs, self.logger, self.ambient)
self.tank         = TankManager(self.configs, self.logger)
self.spectro      = SpectroManager(self.configs, self.logger)
self.plant_growth = PlantGrowthManager(self.configs, self.logger)
```

`ClimateManager` riceve l'istanza di `AmbientManager`: è così che il controllo del
condizionatore legge le ultime misure di T/H senza duplicare l'accesso al sensore.

5. **Alias di retrocompatibilità** — `self.runner`, `self.pump_aerophonics`,
   `self.pump_idrophonics` puntano ai metodi di `jobs`, in modo che `main.py` (scritto prima
   della suddivisione in manager) continui a funzionare invariato.

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

---

## 4. Configurazione: `config.yaml`

Tutti i parametri operativi stanno in un unico file, letto all'avvio.

```yaml
T_var:                  # temperatura/umidità ottimali di riferimento
  Topt: 18.0
  Hopt: 65.0
dht22:
  pin: 27               # pin dati del sensore T/H
  read_interval: 300    # [s] intervallo tra le letture
  saving_dir: /home/fishnplants/Desktop/data/TH/
log:
  directory: /home/fishnplants/Desktop/
  filename: FnP_AeroGreenHouse
  level: INFO
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
plant_growth:
  trig_pin: 5           # TRIG del 2° HC-SR04 (sopra la camera radicale)
  echo_pin: 6           # ECHO -> partitore di tensione OBBLIGATORIO
  read_interval_days: 1 # [giorni] ogni quanto misurare l'altezza
  n_samples: 3          # misure da mediare
  reference_height_cm: 70.0  # distanza sensore -> camera radicale a pianta assente
  decimals: 1           # cifre da tenere dalla misura
  save: true            # abilita/disabilita il salvataggio su file
  saving_dir: /home/fishnplants/Desktop/data/GROWTH/
  history_len: 30       # punti mostrati in grafico e tabella
ir_control:
  tx_pin: 21
  file_ac_name: .../ac_remote.json
  time_max_on: 10.0     # [min] tempo massimo di accensione continua dell'AC
  control_time: 5.0     # [min] periodo del ciclo di valutazione
  T_max: 26.0           # [°C] soglia di intervento sulla temperatura
  H_max: 65.5           # [%]  soglia di intervento sull'umidità
```

**Attenzione alle unità di misura**, non uniformi e fonte di confusione:
`interval` è in **minuti**, `on_time` in **secondi**, `dht22.read_interval` in **secondi**,
`ir_control.control_time` e `time_max_on` in **minuti**, e
`plant_growth.read_interval_days` in **giorni** — terza unità di tempo del file. Il nome del
campo porta con sé l'unità (`_days`) proprio per questo; gli altri no.

Il campo `what_type` discrimina il comportamento: `pump` → pin in uscita e job avviabile;
`sensor` → pin in ingresso, escluso dall'elenco dei processi.

La sezione `tank` **non è presente** nel `config.yaml` attuale: `TankManager._params()`
ricade quindi sulle costanti definite in `ultrasonic_measurement.py` (vedi §8).
La tab Configurazione della GUI la crea al primo salvataggio.

---

## 5. `JobsManager` — pompe e GPIO

Gestisce i cicli di irrigazione. Ha tre tipi di job: **AEROPONICS**, **IDROPONICS** e
i **job generici** definiti dall'utente.

### 5.1 `runner()` — il lanciatore di thread

```python
def runner(self, job, *args, **kwargs):
    job_thread = threading.Thread(target=job, args=args, kwargs=kwargs, daemon=True)
    job_thread.start()
```

Ogni attivazione di pompa è un `daemon` thread: lo scheduler resta libero di contare il
tempo mentre la pompa è accesa, e i thread muoiono automaticamente alla chiusura del
programma.

### 5.2 Schema di attivazione/disattivazione

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

### 5.3 `pump_aerophonics()` — irrigazione a tempo fisso

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

### 5.4 `pump_idrophonics()` — irrigazione a retroazione

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

### 5.5 `on_off_general()` — job generici configurabili

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

### 5.6 `T_modifier()` — modulazione dell'irrigazione con la temperatura

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
> l'esecuzione (vedi §17).

---

## 6. `AmbientManager` — DHT22 e VPD

Legge temperatura e umidità dal sensore **DHT22**, calcola il VPD, salva su file e carica online.

### 6.1 Lettura del sensore: `measure_dht22()`

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

### 6.2 Calcolo del VPD

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
> che usa `237.3` (vedi §17).

### 6.3 Il ciclo di lettura: `_read_loop()`

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

---

## 7. `ClimateManager` e `IRController` — condizionatore

Due livelli: `ClimateManager` gestisce il **ciclo temporale**, `IRController` la **decisione**
e l'invio del segnale.

### 7.1 `ClimateManager.start()` — il ciclo di controllo

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

### 7.2 `IRController.evaluate_and_send()` — la macchina a stati

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

### 7.3 Invio del segnale IR

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

## 8. `TankManager` — livello serbatoio (HC-SR04)

`TankManager` è un **wrapper** attorno a `sensors/ultrasonic_sensor/ultrasonic_measurement.py`:
non riscrive la fisica, la riusa. Il modulo sottostante resta eseguibile in autonomia
(`python3 ultrasonic_measurement.py`) e conserva un proprio `main()` e un proprio logger.

### 8.1 Parametri con fallback

```python
def _params(self):
    t = self.configs.get('tank', {})
    return dict(
        trig=t.get('trig_pin',        self._tank.GPIO_TRIG),        # 23
        echo=t.get('echo_pin',        self._tank.GPIO_ECHO),        # 24
        height=t.get('tank_height_cm', self._tank.TANK_HEIGHT_CM),  # 30.0 cm
        offset=t.get('sensor_offset_cm', self._tank.SENSOR_OFFSET_CM), # 2.0 cm
        area=t.get('tank_area_cm2',   self._tank.TANK_AREA_CM2),    # 900.0 cm²
        low=t.get('water_low_threshold_l', self._tank.WATER_LOW_THRESHOLD_L), # 3.0 L
        interval=t.get('read_interval', self._tank.READ_INTERVAL_S),# 300 s
        n=t.get('n_samples',          self._tank.N_SAMPLES),        # 5
        save=t.get('saving_dir',      self._tank.SAVE_DIR),
    )
```

Ogni parametro viene cercato prima in `config.yaml`, poi nelle costanti del modulo. Poiché
la sezione `tank` oggi non esiste nel config, **sono in uso i valori di fallback**.

### 8.2 Principio fisico della misura

L'HC-SR04 emette un treno di 8 impulsi ultrasonici a **40 kHz** e tiene il pin ECHO alto per
tutto il tempo di volo dell'onda (andata + ritorno).

```python
GPIO.output(trig_pin, True)
time.sleep(0.00001)              # impulso TRIG da 10 µs (richiesto dal datasheet)
GPIO.output(trig_pin, False)

while GPIO.input(echo_pin) == 0:  # attende il fronte di salita
    pulse_start = time.time()
    if pulse_start > deadline: return -1.0
while GPIO.input(echo_pin) == 1:  # attende il fronte di discesa
    pulse_end = time.time()
    if pulse_end > deadline: return -1.0

pulse_duration = pulse_end - pulse_start
distance_cm = (pulse_duration * 34300.0) / 2.0
```

**Formula:**

```
distanza [cm] = (durata_echo [s] × 34300 [cm/s]) / 2
```

`34300 cm/s` è la velocità del suono in aria a ~20 °C; la divisione per 2 elimina il percorso
di ritorno. Entrambi i cicli di attesa hanno un **timeout** (40 ms ≈ 6.8 m): senza, un eco mai
ricevuto bloccherebbe il thread per sempre.

> **Nota hardware.** ECHO emette 5 V mentre i GPIO del Pi tollerano 3.3 V: è **obbligatorio**
> un partitore di tensione (R1 = 1 kΩ, R2 = 2 kΩ) documentato nell'header del modulo.

### 8.3 Filtraggio del rumore: `measure_distance_avg()`

```python
readings = []
for _ in range(n_samples):
    d = measure_distance_cm(trig_pin, echo_pin)
    if d > 0: readings.append(d)      # scarta i timeout
    time.sleep(delay)                 # delay = 0.065 s
readings.sort()
return readings[len(readings) // 2]   # MEDIANA
```

Nonostante il nome (`_avg`) la funzione restituisce la **mediana**, non la media: scelta
deliberata, perché la mediana è robusta agli outlier — un singolo eco spurio (riflesso sulla
parete della tanica, schiuma sull'acqua) sposterebbe la media, non la mediana.
Il ritardo di 65 ms tra misure rispetta la raccomandazione del datasheet (> 60 ms), che serve
a evitare che l'eco della misura precedente contamini la successiva.

### 8.4 Da distanza a volume: `distance_to_water_volume()`

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

### 8.5 Validazione e allarme

`read_now()` applica due controlli prima di accettare la misura:

```python
if dist < 0:                       # timeout
    self.logger.warning("TANK: Misura non valida ..."); return None
if dist < 2.0 or dist > 400.0:     # fuori dal range operativo dell'HC-SR04
    self.logger.warning(f"TANK: Distanza {dist:.1f}cm fuori dal range ..."); return None
```

Il ciclo `_read_loop()` salva su file e confronta con la soglia:

```python
if result['volume_L'] < p['low']:
    self.logger.warning(f"TANK LOW WATER: Volume residuo {result['volume_L']}L "
                        f"sotto la soglia di {p['low']}L! Riempire la tanica.")
```

L'inizializzazione GPIO avviene una sola volta (`_ensure_gpio` con il flag `_gpio_ready`).

---

## 9. `PlantGrowthManager` — altezza della pianta (HC-SR04)

Misura di quanto sono cresciute le piante, con un **secondo sensore HC-SR04** montato sopra
la camera radicale e puntato verso il basso. Come `TankManager` (§8) è un wrapper attorno a
`ultrasonic_measurement.py`: stessa fisica, stesso modulo, bersaglio diverso.

### 9.1 Principio della misura

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

Il **clipping a 0** ha lo stesso ruolo del clipping del serbatoio (§8.4): protegge da una
taratura imprecisa di `reference_height_cm`. Senza, un riferimento sottostimato di pochi
millimetri produrrebbe altezze negative — fisicamente impossibili.

`reference_height_cm` è quindi **il parametro da tarare**, e si tara con il sensore stesso
(§9.6) a camera radicale vuota: la distanza che il sensore legge in quel momento *è* per
definizione il riferimento. Misurarlo col metro è possibile ma meno accurato, perché il metro
e il sensore non partono necessariamente dallo stesso punto: il sensore misura dalla propria
membrana, e un errore sul riferimento si trasferisce **uguale su ogni misura successiva**.

### 9.2 Parametri con fallback

Stesso idiom di `TankManager._params()` (§8.1): prima `config.yaml`, poi le costanti del
modulo. I default stanno in `plant_growth.py` e non in `ultrasonic_measurement.py`, perché le
costanti di quel modulo (`GPIO_TRIG = 23`, `TANK_HEIGHT_CM`…) descrivono il **serbatoio**.

```python
def _params(self):
    g = self.configs.get('plant_growth', {})
    return dict(
        trig=g.get('trig_pin', GPIO_TRIG),                        # 5
        echo=g.get('echo_pin', GPIO_ECHO),                        # 6
        interval_days=g.get('read_interval_days', READ_INTERVAL_DAYS),  # 1 giorno
        n=g.get('n_samples', N_SAMPLES),                          # 3
        reference=g.get('reference_height_cm', REFERENCE_HEIGHT_CM),    # 70.0 cm
        decimals=g.get('decimals', DEFAULT_DECIMALS),             # 1
        save_enabled=g.get('save', True),
        save_dir=g.get('saving_dir', SAVE_DIR),
        history_len=g.get('history_len', HISTORY_LEN),            # 30
    )
```

### 9.3 Media o mediana? — `measure_distance_mean()`

Il modulo ultrasonico espone ora **due** filtri affiancati, che differiscono solo per la
statistica finale:

| Funzione | Statistica | Usata da | Perché |
|---|---|---|---|
| `measure_distance_avg()` | **mediana** | `TankManager` | robusta agli outlier: un eco spurio (schiuma, riflesso sulla parete della tanica) sposterebbe la media, non la mediana |
| `measure_distance_mean()` | **media** | `PlantGrowthManager` | su un bersaglio fermo come una pianta il rumore è simmetrico, e la media usa l'informazione di tutte le letture invece di scartarne N−1 |

```python
readings = []
for _ in range(n_samples):
    d = measure_distance_cm(trig_pin, echo_pin)
    if d > 0: readings.append(d)      # scarta i timeout
    time.sleep(delay)                 # delay = 0.065 s, come da datasheet
return sum(readings) / len(readings)  # MEDIA
```

Entrambe scartano i timeout (`d > 0`), rispettano il ritardo di 65 ms fra misure (> 60 ms
raccomandati dal datasheet) e restituiscono `-1.0` se nessuna lettura è valida.
Con la configurazione attuale la crescita media **3 letture**.

### 9.4 Cifre da tenere: `data_config.py`

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

### 9.5 Validazione, salvataggio e storico

`read_now()` applica gli stessi due controlli del serbatoio (§8.5) — timeout (`dist < 0`) e
range operativo dell'HC-SR04 (2–400 cm) — e in entrambi i casi restituisce `None` con un
warning, senza scrivere nulla su file.

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
riavvio. È tenuto in ordine **cronologico crescente** — è l'ordine che serve al grafico — e
la tabella lo inverte al momento di visualizzarlo. Le righe malformate vengono loggate e
saltate, non fanno fallire la lettura (stessa filosofia di `daily_th_processor.py`, §13.1).

### 9.6 Calibrazione del riferimento

`calibration_distance()` esegue la taratura: misura la distanza attuale (media di `n_samples`
letture, con la stessa validazione di `read_now()`) e la salva come `reference_height_cm`.
Va eseguita **a camera radicale vuota**. Dalla GUI è il bottone "📐 Calibrazione" della tab
Crescita, che chiede conferma prima di procedere — stesso schema della taratura dello
spettrometro (§10.3).

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
`self.configs` ad ogni chiamata (§9.2), quindi la misura successiva usa già il nuovo
riferimento: subito dopo la calibrazione `h_plant` vale 0, come atteso.

**3. La GUI deve riallineare il proprio dizionario.** Qui si incontra un difetto strutturale
del progetto (§17.6): `self.config` della GUI e `self.ah.configs` dei manager sono **due
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

### 9.7 Il ciclo periodico

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
`threading.Event` (§15), quindi il bottone "Arresta Lettura" interrompe immediatamente anche
un'attesa di un giorno intero.

Il conteggio **non è persistito**: dopo un riavvio del programma riparte da zero, con una
misura immediata. Per una cadenza giornaliera è accettabile.

### 9.8 La tab "Crescita" e il grafico

Mostra l'altezza dell'ultima misura, la sua data, un grafico dell'andamento nel tempo e la
tabella data/altezza. Tutti i valori sono in **cm**. I bottoni sono "📏 Misura Adesso",
"▶️ Attiva Lettura", "⏹️ Arresta Lettura" e "📐 Calibrazione" (§9.6).

Il grafico è disegnato con le **primitive native di `tk.Canvas`** (`create_line`,
`create_oval`), non con matplotlib. La scelta è dettata dall'hardware: su un Raspberry Pi
Zero W (512 MB di RAM, single core) `matplotlib` costerebbe ~2-4 s di import all'avvio della
GUI e decine di MB residenti. Il costo *non* sarebbe nel disegno — con una misura ogni giorno
i punti sono al massimo `history_len` e il ridisegno è rarissimo — ma nella libreria stessa.
Le primitive Tk sono già in memoria e bastano per una spezzata.

> Nota: `daily_th_processor.py` (§13.1) usa matplotlib, ma in un **processo separato**, con
> import lazy dentro la funzione e backend `Agg`: non pesa mai sulla GUI.

Il ridisegno è agganciato all'evento `<Configure>` (quindi segue il ridimensionamento della
finestra) e viene rifatto dopo ogni misura. Con meno di due punti il Canvas mostra un
placeholder testuale invece di una spezzata degenere.

### 9.9 Nota hardware

Vale quanto detto in §8.2: **ECHO emette 5 V e i GPIO del Pi tollerano 3.3 V**, quindi il
partitore di tensione (R1 = 1 kΩ, R2 = 2 kΩ) è obbligatorio anche per questo secondo sensore.
I due HC-SR04 convivono senza conflitti perché usano pin distinti (`23/24` il serbatoio,
`5/6` la crescita) e `GPIO.setmode(BCM)` è impostato una sola volta per il processo.

> ⚠️ I pin `5` e `6` in `config.yaml` sono valori **provvisori**, da allineare al cablaggio reale.

---

## 10. Spettrometro AS7265x — indice MCARI2

Modulo `sensors/spectrometer/mcari2_as7265x.py`. Misura lo stato di salute della pianta con
il sensore **SparkFun Triad AS7265x** (18 canali, 410–940 nm, bus I2C).

### 10.1 Import tollerante

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

### 10.2 Mappatura delle bande

MCARI2 richiede tre bande, mappate sui getter della libreria:

| Banda | λ nominale | Canale AS7265x | Getter |
|---|---|---|---|
| GREEN | ~550 nm | 560 nm | `get_calibrated_g()` |
| RED | ~670 nm | 680 nm | `get_calibrated_s()` |
| NIR | ~800 nm | 810 nm | `get_calibrated_v()` |

La mappatura sta in un unico posto (`GREEN_GETTER`/`RED_GETTER`/`NIR_GETTER`) e viene
risolta con `getattr`. `CHANNEL_MAP` elenca tutti i 18 canali per la diagnostica.

### 10.3 Il punto critico: riflettanza, non irradianza

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

### 10.4 La formula MCARI2

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

### 10.5 Catena di elaborazione e interpretazione

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

## 11. Camera

`camera/takePicture.py` è un processo indipendente basato su `picamera2`:

```python
schedule.every(separation_hours).hours.do(take_picture)    # ogni 2 ore
```

Ogni scatto produce **due file**: uno storico con timestamp
(`YYYY-MM-DD_HH-MM-SS.jpg`) e una copia a nome fisso `image.jpg`, che è quella che
`uploader.py` carica su GitHub — il nome fisso permette al sito di puntare sempre allo
stesso URL per l'ultima foto.

---

## 12. Persistenza dei dati: formati dei file

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

I file TANK, SPECTRO e GROWTH scrivono l'**header solo se il file non esiste**
(`write_header = not os.path.exists(file_path)`); i file TH non hanno header. L'apertura è
sempre in modalità append (`'a'`), quindi un riavvio del programma non perde i dati.

---

## 13. Elaborazione giornaliera e upload

### 13.1 `daily_th_processor.py`

Processo separato, schedulato **ogni giorno alle 00:01**, che elabora il file del giorno
precedente. La pipeline di `daily_job()`:

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

### 13.2 `uploader/uploader.py`

CLI a sottocomandi che pubblica su GitHub via **API REST**, usata come backend dati del sito.

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
rete transitori tipici di una connessione domestica (vedi §17 per un difetto nel calcolo del
delay).

---

## 14. Logging

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
`IDROPONICS:`, `AMBIENT:`, `IR_CONTROLLER:`, `TANK:`, `GROWTH:` — così i log sono filtrabili
con `grep`.

---

## 15. Modello di concorrenza (thread)

Il sistema è **multi-thread ma senza lock**. Il modello:

| Thread | Avviato da | Ciclo |
|---|---|---|
| Main / Tk | `main.py` o `gui.py` | `schedule.run_pending()` o `mainloop()` |
| AEROPONICS | `start_aeroponics()` | `while self.aeroponics_job_active` |
| IDROPONICS | `start_idroponics()` | `while self.idroponics_job_active` |
| Job generici (N) | `start_general(name)` | `while self.general_jobs_active[name]` |
| Ambient | `start_reading()` | `while not self._stop_event.is_set()` |
| Climate | `climate.start()` | `while not self._stop_event.is_set()` |
| Tank | `tank.start_reading()` | `while not self._stop_event.is_set()` |
| Spectro | `spectro.start_reading()` | `while not self._stop_event.is_set()` |
| PlantGrowth | `plant_growth.start_reading()` | `while not self._stop_event.is_set()` |
| Pulse pompa | `runner()` | one-shot, muore da solo |

Tutti sono `daemon=True`: alla chiusura del programma muoiono senza richiedere join.

**Due meccanismi di arresto**, con proprietà diverse:

1. **Flag booleano** (`JobsManager`) + `sleep(1)` — l'arresto richiede fino a 1 secondo.
   Accettabile per i job delle pompe, il cui ciclo è di minuti.
2. **`threading.Event`** (`Ambient`, `Climate`, `Tank`, `Spectro`, `PlantGrowth`) +
   `_stop_event.wait(interval)` — arresto **immediato**. Indispensabile qui, dove gli
   intervalli vanno dai 5 minuti a un giorno intero (`PlantGrowth`) e la GUI deve rispondere
   subito al bottone Stop.

**Assenza di lock.** Le variabili condivise sono `last_T`/`last_H` (scritte da Ambient, lette
da Climate) e i flag booleani. La correttezza si appoggia sull'atomicità delle assegnazioni
di riferimenti in CPython (GIL): letture e scritture di un `float` o `bool` singolo non
possono interlacciarsi. Il codice **non fa mai read-modify-write** su questi valori, che è il
caso in cui servirebbe un lock.

**Thread-safety della GUI**: Tkinter non è thread-safe; nessun thread di lavoro tocca i
widget. I dati passano per callback (`on_update`) e per la `Queue` dei log.

---

## 16. Riepilogo delle formule

| Grandezza | Formula | Dove |
|---|---|---|
| Pressione di vapore saturo | `es(T) = 0.6108 · exp(17.27·T / (T + 273.3))` [kPa] | `AmbientManager.VPD` |
| Pressione di vapore effettiva | `ea = H · es(T) / 100` | `AmbientManager.VPD` |
| **VPD** | `VPD = es(T) − ea` [kPa] | `AmbientManager.VPD` |
| Modificatore di irrigazione | `t_mod = 1/(exp(−0.2·(T−Topt)) + 1) − 0.5` | `JobsManager.T_modifier` |
| Nuova attesa irrigazione | `t_new = t_old − t_old · t_mod` | `JobsManager.T_modifier` |
| Distanza ultrasonica | `d = (durata_echo · 34300) / 2` [cm] | `measure_distance_cm` |
| **Altezza pianta** | `h_plant = riferimento − d`, con clipping a 0 [cm] | `PlantGrowthManager.read_now` |
| Livello acqua | `livello = H_tanica − (d − offset)` [cm] | `distance_to_water_volume` |
| Volume | `V = livello · area / 1000` [L] | `distance_to_water_volume` |
| Riempimento | `fill% = livello / H_tanica · 100` | `distance_to_water_volume` |
| Riflettanza | `R(λ) = target(λ) / riferimento(λ)` | `compute_reflectance` |
| **MCARI2** | `1.5·[2.5·(NIR−RED) − 1.3·(NIR−GREEN)] / √[(2·NIR+1)² − (6·NIR − 5·√RED) − 0.5]` | `mcari2` |

---

## 17. Anomalie rilevate nel codice

Difetti individuati durante la stesura di questo documento. Sono documentati qui perché
riguardano le formule e le logiche descritte sopra; **nessuno è stato corretto**.

### 17.1 `T_modifier()` — variabile usata prima di essere definita

`helper_aeroGreenHouse.py:288`

```python
t_new = t_new - t_new * t_modifier   # t_new non è ancora definita
```

Il parametro d'ingresso si chiama `t_old`, ma la riga usa `t_new` su entrambi i lati:
la funzione solleverebbe `UnboundLocalError` a ogni chiamata. Sembra dover essere
`t_new = t_old - t_old * t_modifier`. Attualmente la funzione non ha chiamanti, quindi il
difetto è latente.

### 17.2 `VPD()` — costante della formula di Tetens

`helper_aeroGreenHouse.py:358`

```python
es = lambda T: 0.6108 * exp(17.27 * T / (T + 273.3))
```

La formulazione standard di Tetens (FAO Irrigation and Drainage Paper 56) usa **237.3**,
non 273.3 — valore che sembra una confusione con la costante di conversione Kelvin (273.15).
Con `237.3`, a T = 23 °C si ha es ≈ 2.81 kPa; con `273.3` si ottiene ≈ 2.55 kPa, circa il
**9% in meno**. L'errore cresce con la temperatura. Il VPD registrato finora risulta quindi
sottostimato in modo sistematico; da valutare se correggere (e come trattare lo storico).

### 17.3 `_read_loop()` — logger invocato come funzione

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

### 17.4 `retry_with_exponential_backoff` — il backoff non è esponenziale

`uploader/uploader.py:65`

```python
BASE_DELAY = 1
delay = BASE_DELAY ** (attempt - 1)   # 1**0=1, 1**1=1, 1**2=1
```

Con `BASE_DELAY = 1` la potenza vale sempre 1: i retry avvengono a distanza fissa di 1 s,
non 1s/2s/4s come dichiara il docstring. La forma corretta sarebbe `BASE_DELAY * (2 ** (attempt - 1))`.

### 17.5 `evaluate_and_send()` — nomi dei comandi disallineati

`ir_controller/ir_controller.py:83`

```python
if self.last_command_sent in ('Tlow', 'Hlow') and ...:   # controllo del timeout
```

Ma i comandi effettivamente inviati e memorizzati sono `'T_low_21'` e `'dry'`, mai `'Tlow'`
o `'Hlow'`. La condizione non è quindi mai vera e il **controllo di `time_max_on` non
interviene**: il condizionatore non viene mai spento dal timeout di sicurezza, ma solo dal
rientro di T o H sotto soglia. La lista sembra dover essere `('T_low_21', 'dry')`.

### 17.6 La configurazione è caricata due volte, in due dizionari distinti

`gui.py:37` e `helper_aeroGreenHouse.py:32`

```python
self.config = self.load_config()   # gui.py:37   -> dizionario A
self.ah = aeroHelper()             # gui.py:48   -> dentro, dizionario B
```

Lo stesso `config.yaml` viene letto **due volte**, in due oggetti separati. `aeroHelper` passa
il **suo** (B) a tutti i manager per riferimento, quindi i sei manager sono coerenti tra loro;
ma la GUI usa A, e i due non comunicano. Conseguenze concrete:

- **Le modifiche salvate dalla tab Configurazione non raggiungono i manager** finché il
  processo non viene riavviato: la GUI scrive il file e aggiorna A, i manager continuano a
  leggere B.
- **Le modifiche ai job** (`gui.py:696/718/732` aggiungono, eliminano e modificano voci di
  `gpio_pins` in A) non arrivano mai allo scheduler, che vive su B.
- **Rischio di sovrascrittura**: `save_config()` riversa l'**intero** A. Chiunque scriva sul
  file passando da B — come fa la calibrazione della crescita (§9.6) — vedrebbe il proprio
  valore cancellato dal primo "Salva Configurazione". La calibrazione lo neutralizza
  riallineando esplicitamente A e la StringVar, ma è una toppa sul sintomo.

La cura strutturale sarebbe fare in modo che A e B siano **lo stesso oggetto** (`self.ah`
costruito per primo, poi `self.config = self.ah.configs`) e che ogni ricarica **muti il
dizionario sul posto** invece di riassegnarlo — `reload_config_tab:872` fa `self.config =
self.load_config()`, che romperebbe l'aliasing al primo click su "Ricarica". Poiché i manager
rileggono `self.configs` ad ogni uso, la mutazione sul posto darebbe l'aggiornamento a caldo
quasi gratis; resterebbero fuori i valori catturati una volta sola (pin GPIO già configurati,
intervalli già congelati negli `Scheduler`, i cinque attributi copiati da `IRController`).

### 17.7 Note minori

- `measure_distance_avg()` restituisce la mediana ma il nome e il parametro `n_samples`
  suggeriscono la media — il docstring lo chiarisce, il nome no. Da quando esiste anche
  `measure_distance_mean()`, che la media la calcola davvero (§9.3), l'ambiguità è peggiorata:
  le due funzioni stanno affiancate nello stesso modulo e i nomi non dicono che differiscono
  proprio nella statistica. `measure_distance_median()` sarebbe il nome corretto per la prima.
- `measure_dht22()` e `_read_loop()` contengono due copie della stessa logica di lettura DHT22.
- `eval(f"adafruit_dht.DHT22(board.D{gpio})")` usa `eval` dove basterebbe
  `getattr(board, f"D{gpio}")`.
- `AmbientManager.upload_data_on_web()` usa `os.system` con path relativo
  (`python uploader/uploader.py`): funziona solo se il processo è avviato dalla directory del
  progetto.
- `main.py` accede a `gpio_pins` per indice posizionale, quindi riordinare `config.yaml` ne
  rompe il funzionamento (`gui.py` cerca invece per `name`).
