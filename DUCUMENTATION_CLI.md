# AeroGreenHouse — Documentazione della CLI (`main.py`)

Documento di riferimento sull'interfaccia a riga di comando. Descrive **come funziona**
`main.py`, **tutti i comandi** implementati e le scelte possibili per ciascuno, con un
esempio per ogni comando.

Per la documentazione del sistema nel suo complesso (manager, sensori, formule) si veda
[`DOCUMENTATION.md`](DOCUMENTATION.md).

---

## Indice

1. [Cosa fa e perché è una shell](#1-cosa-fa-e-perché-è-una-shell)
2. [Avvio e ciclo di vita](#2-avvio-e-ciclo-di-vita)
3. [Come vengono interpretati i comandi](#3-come-vengono-interpretati-i-comandi)
4. [Struttura interna](#4-struttura-interna)
5. [`-job` — gestione dei job](#5--job--gestione-dei-job)
6. [`-measure` — misure in tempo reale](#6--measure--misure-in-tempo-reale)
7. [`-camera` — foto e anteprima](#7--camera--foto-e-anteprima)
8. [`-daily` — elaborazione giornaliera](#8--daily--elaborazione-giornaliera)
9. [`-details` — riepilogo generale](#9--details--riepilogo-generale)
10. [`-save` — lettura e modifica della configurazione](#10--save--lettura-e-modifica-della-configurazione)
11. [`help`, `exit`, `quit`](#11-help-exit-quit)
12. [Tabella riassuntiva di tutti i comandi](#12-tabella-riassuntiva-di-tutti-i-comandi)
13. [Sessione di esempio completa](#13-sessione-di-esempio-completa)
14. [Differenze rispetto alla GUI](#14-differenze-rispetto-alla-gui)
15. [Errori tipici e cosa significano](#15-errori-tipici-e-cosa-significano)

---

## 1. Cosa fa e perché è una shell

`main.py` espone le stesse funzioni di `gui.py` da terminale, così da poter pilotare la
serra **via SSH senza display**.

È una **shell interattiva** (un prompt che resta aperto) e non una serie di comandi
one-shot tipo `python main.py -job activate AEROPONICS`. La ragione è nel modello di
concorrenza del sistema: i job girano in **thread daemon del processo** che li ha avviati
(§15 di `DOCUMENTATION.md`). Un comando one-shot terminerebbe subito dopo l'attivazione e
il thread morirebbe con lui; inoltre `-job active` non avrebbe mai nulla da mostrare,
perché non esiste stato condiviso fra processi diversi.

Con la shell il processo resta vivo, i job continuano a girare e lo stato è consultabile —
esattamente come accade tenendo aperta la finestra della GUI.

> **Conseguenza pratica:** chiudendo la shell si fermano tutti i job. Per un servizio che
> sopravvive alla disconnessione SSH, avviarla dentro `screen`/`tmux` o come servizio
> systemd.

Come `gui.py`, `main.py` contiene **solo parsing dei comandi e stampa**: nessuna logica di
processo. Thread, scheduling, formule e I/O sui file restano nei manager sotto
`managers_classes/`.

---

## 2. Avvio e ciclo di vita

```bash
cd /home/fishnplants/Desktop/codes/python/AeroGreenHouse
python3 main.py
```

All'avvio viene istanziato `aeroHelper()`, che carica `config.yaml`, configura il logging,
inizializza le GPIO e costruisce gli otto manager. Compare quindi il prompt:

```
AeroGreenHouse CLI - 'help' per l'elenco dei comandi, 'exit' per uscire.
aero>
```

Richiede **RPi.GPIO e i driver dei sensori**: gira solo sul Raspberry, non su un PC di
sviluppo.

L'uscita avviene con `exit`, `quit`, Ctrl+C o Ctrl+D. In tutti i casi viene chiamato
`ah.cleanup_gpios()` per rilasciare i pin, e viene stampato `Program Terminated`.

**Nessun job parte da solo.** Il vecchio `main.py` avviava aeroponica e idroponica
all'esecuzione; la shell no, tutto va attivato esplicitamente con `-job activate`.

---

## 3. Come vengono interpretati i comandi

Ogni riga passa attraverso tre passaggi:

1. **`shlex.split()`** — divide la riga rispettando le virgolette, così un valore con spazi
   si passa fra apici: `save set log.filename "FnP Serra"`.
2. **Normalizzazione del comando** — dal primo token viene tolto il `-` iniziale e il tutto
   è reso minuscolo. Perciò `-job active`, `job active` e `JOB ACTIVE` sono equivalenti: il
   `-` è accettato per coerenza con la notazione richiesta, ma dentro la shell è opzionale.
3. **Dispatch** — il nome viene cercato in un dizionario `{nome: metodo}`.

I nomi dei job e i valori di configurazione restano **case-sensitive**: solo il comando
viene reso minuscolo, non i suoi argomenti. `-job activate aeroponics` non funziona,
serve `AEROPONICS`.

`measure` accetta l'alias **`mesure`**, per tollerare la grafia senza la "a".

Un errore dentro un comando viene intercettato e stampato: **la shell non muore mai** per
un singolo comando fallito.

---

## 4. Struttura interna

Tutto vive nella classe `AeroCLI`, che tiene una sola istanza `self.ah = aeroHelper()`.

| Metodo | Ruolo |
|---|---|
| `run()` | Loop di lettura ed esecuzione dei comandi |
| `shutdown()` | `cleanup_gpios()` all'uscita |
| `job_states()` | Stato dei soli job, come lista di `(nome, attivo)` |
| `process_states()` | Job **+** gli otto processi di sistema |
| `cmd_job` / `cmd_measure` / `cmd_camera` / `cmd_daily` / `cmd_details` / `cmd_save` / `cmd_help` | Un handler per comando |

`job_states()` e `process_states()` replicano `get_process_states()` della GUI
(§2.2 di `DOCUMENTATION.md`): scorrono `gpio_pins` saltando le voci con
`what_type: sensor` — un sensore non è un processo — e leggono i flag
`aeroponics_job_active`, `idroponics_job_active`, `general_jobs_active[nome]`.
Sono usati sia da `-job active` (solo i job) sia da `-details` (job + sistema).

Due funzioni di modulo completano il quadro:

- **`format_acq_date(ts)`** — converte i timestamp dei manager (`%Y/%m/%d %H:%M:%S`) nel
  formato leggibile `gg/mm/aaaa hh:mm`, restituendo `--` se il dato manca.
- **`cast_value(raw)`** — converte la stringa di `save set` nel tipo più plausibile,
  provando nell'ordine: `int` → `float` → booleano → stringa.

---

## 5. `-job` — gestione dei job

Equivalente della scheda **Gestione Job** della GUI. Quattro scelte possibili:
`list`, `active`, `activate`, `deactivate`.

### 5.1 `-job list`

Elenca **tutti** i job definiti in `config.yaml`, attivi o no, con i loro parametri. Include
anche le voci di tipo `sensor`, per dare il quadro completo dei pin usati.

```
aero> -job list
NOME            PIN      TIPO  INTERVAL  ON TIME
AEROPONICS       19      pump      1200        5
IDROPONICS       12      pump        29       65
MOISTURE         26    sensor        --       --
```

### 5.2 `-job active`

Mostra i **soli job attivi**. Lo stato è letto direttamente dai flag dei manager, non da
una copia locale: riflette quindi la realtà anche se un job si è fermato per conto suo.

```
aero> -job active
Job attivi:
  - AEROPONICS
```

Se non ce n'è nessuno:

```
aero> -job active
Nessun job attivo.
```

### 5.3 `-job activate <nome_job>`

Avvia il job indicato, con lo stesso dispatch per nome della GUI:

| Nome | Chiamata |
|---|---|
| `AEROPONICS` | `jobs.start_aeroponics()` |
| `IDROPONICS` | `jobs.start_idroponics()` |
| qualsiasi altro | `jobs.start_general(pin, on_time, interval, nome)` |

Per i job generici pin, `on_time` e `interval` sono letti **direttamente da `config.yaml`**.

```
aero> -job activate AEROPONICS
Job 'AEROPONICS' attivato.
```

Se era già in esecuzione, il valore di ritorno `False` di `start_*` lo segnala invece di
avviare un secondo thread sullo stesso pin:

```
aero> -job activate AEROPONICS
Job 'AEROPONICS' era gia' attivo.
```

Due controlli precedono l'avvio di un job generico: il nome deve esistere in `config.yaml`,
e non deve essere un sensore.

```
aero> -job activate POMPA_X
Job 'POMPA_X' non trovato in config.yaml.

aero> -job activate MOISTURE
'MOISTURE' e' un sensore, non un job attivabile.
```

### 5.4 `-job deactivate <nome_job>`

Speculare a `activate`, su `deactivate_aeroponics()` / `deactivate_idroponics()` /
`deactivate_general(nome)`.

```
aero> -job deactivate AEROPONICS
Job 'AEROPONICS' disattivato.
```

---

## 6. `-measure` — misure in tempo reale

Equivalente delle schede **Ambient** e **Livelli Serbatoio**. Due grandezze (`th` e
`water`), ciascuna con tre azioni: avvio continuo (default), `now`, `stop`.

### 6.1 `-measure th` — lettura continua di T, H e VPD

Senza argomenti aggiuntivi avvia la lettura periodica in un thread
(`ambient.start_reading`), con la cadenza `dht22.read_interval` di `config.yaml`. Ogni
lettura viene stampata appena disponibile; **il prompt resta utilizzabile**, quindi le
righe compaiono mescolate a ciò che si sta digitando.

```
aero> -measure th
Lettura T/H/VPD avviata ('-measure th stop' per fermarla).
[2026/07/19 14:32:10] T = 21.4 C | H = 63.2 % | VPD = 0.9384 kPa
[2026/07/19 14:37:10] T = 21.6 C | H = 62.8 % | VPD = 0.9571 kPa
```

### 6.2 `-measure th now` — lettura singola

Una sola misura immediata, senza avviare alcun thread.

```
aero> -measure th now
[2026/07/19 14:33:02] T = 21.5 C | H = 63.0 % | VPD = 0.9477 kPa
```

### 6.3 `-measure th stop`

```
aero> -measure th stop
Lettura T/H/VPD arrestata.
```

Se non era in corso nulla:

```
aero> -measure th stop
Nessuna lettura T/H/VPD in corso.
```

### 6.4 `-measure water` — lettura continua del serbatoio

Stessa struttura, su `TankManager` (sensore ultrasonico HC-SR04). La lettura periodica
**salva su file** e registra a log l'allarme di livello basso sotto
`tank.water_low_threshold_l`.

```
aero> -measure water
Lettura serbatoio avviata ('-measure water stop' per fermarla).
[2026/07/19 14:35:01] volume = 17.64 L | riempimento = 65.3 % | livello = 19.6 cm | distanza = 12.4 cm
```

### 6.5 `-measure water now`

```
aero> -measure water now
[2026/07/19 14:35:44] volume = 17.61 L | riempimento = 65.2 % | livello = 19.6 cm | distanza = 12.4 cm
```

`read_now()` scarta le misure fuori dal range operativo del sensore (2–400 cm) e i timeout,
restituendo `None`. La CLI lo traduce in un messaggio, non in un errore:

```
aero> -measure water now
Misura non valida: verificare il sensore ultrasonico.
```

### 6.6 `-measure water stop`

```
aero> -measure water stop
Lettura serbatoio arrestata.
```

---

## 7. `-camera` — foto e anteprima

Equivalente della scheda **Camera** della GUI. Quattro scelte: `start` (default), `stop`,
`now`, `preview`.

I due usi della camera **si escludono a vicenda**: la Picamera2 è una risorsa singola e
aprirla due volte farebbe fallire l'anteprima o lo scatto schedulato (§11.3 di
`DOCUMENTATION.md`). Il manager rifiuta l'operazione e la CLI stampa quale processo va
fermato prima.

### 7.1 `-camera` / `-camera start` — acquisizione periodica

Avvia lo scatto periodico in un thread, con la cadenza `camera.separation_hours` di
`config.yaml`. Come per `-measure`, ogni scatto viene stampato appena disponibile e il
prompt resta utilizzabile.

```
aero> -camera
Acquisizione foto avviata: uno scatto ogni 2 ore ('-camera stop' per fermarla).
[2026/07/19 15:34:08] foto salvata: /home/fishnplants/Desktop/data/IMG/2026-07-19_15-34-08.jpg
```

Se l'anteprima è aperta la camera è occupata:

```
aero> -camera start
Anteprima attiva: usa '-camera preview off' prima di avviare l'acquisizione.
```

### 7.2 `-camera now` — scatto singolo

Una sola foto immediata, senza avviare alcun thread. Come ogni scatto, produce **due file**:
lo storico con timestamp e la copia `image.jpg` che `uploader.py` carica su GitHub.

```
aero> -camera now
Foto salvata: /home/fishnplants/Desktop/data/IMG/2026-07-19_15-34-07.jpg
```

### 7.3 `-camera stop`

```
aero> -camera stop
Acquisizione foto arrestata.
```

### 7.4 `-camera preview on|off` — anteprima dal vivo

Apre o chiude la finestra di anteprima. Senza argomento fa da interruttore (apre se chiusa,
chiude se aperta).

```
aero> -camera preview on
Anteprima camera attivata ('-camera preview off' per chiuderla).

aero> -camera preview off
Anteprima camera disattivata.
```

> **Richiede un display.** Via SSH senza X forwarding la finestra QTGL non può aprirsi e
> `picamera2` solleva un errore, che la shell intercetta e stampa. È l'unico comando della
> CLI che non funziona da una sessione puramente testuale.

Con l'acquisizione in corso:

```
aero> -camera preview on
Acquisizione in corso: la camera e' gia' in uso. Usa '-camera stop' prima di attivare l'anteprima.
```

---

## 8. `-daily` — elaborazione giornaliera

Equivalente dei pulsanti **Attiva/Arresta Daily** della scheda Ambient. Elabora il file TH
del **giorno precedente** producendo statistiche e `plot.png` (§13.1 di `DOCUMENTATION.md`).
Quattro scelte: `start` (default), `stop`, `now`, `stats`.

### 8.1 `-daily` / `-daily start`

Avvia lo scheduler: il job gira ogni giorno alle **00:01**. All'avvio esegue anche un primo
giro immediato **senza upload**, per avere subito le statistiche disponibili — quei dati
sono già stati caricati dal giro precedente.

```
aero> -daily start
Elaborazione giornaliera avviata: job schedulato alle 00:01 ('-daily stop' per fermarla).
```

### 8.2 `-daily now` — elaborazione immediata

Esegue subito la pipeline completa **con** upload su GitHub, e stampa il risultato.

```
aero> -daily now
Giorno elaborato: 2026-07-18
                    MAX      MIN    MEDIA
Temperatura          25    22.04    23.39
Umidita'          64.99    55.09     60.1
VPD               1.139    0.778    0.953
Plot: /home/fishnplants/Desktop/data/PLOT/plot.png
```

Se il file del giorno prima non esiste, il job viene saltato senza errore:

```
aero> -daily now
Nessun dato da elaborare per il giorno precedente.
```

### 8.3 `-daily stats`

Ristampa il risultato dell'ultima elaborazione, senza rieseguirla.

```
aero> -daily stats
Nessuna elaborazione eseguita (--)
```

### 8.4 `-daily stop`

```
aero> -daily stop
Elaborazione giornaliera arrestata.
```

> Subito dopo lo `stop`, `-details` può ancora mostrare il processo come attivo: se il
> thread stava generando il plot, `is_running()` dice la verità — il thread esce appena
> quel lavoro finisce, tipicamente entro un paio di secondi.

---

## 9. `-details` — riepilogo generale

Equivalente testuale della scheda **Riepilogo** (§2.3 di `DOCUMENTATION.md`). Non prende
argomenti e **non esegue misure**: mostra l'ultimo dato noto di ciascun manager, così come
fa la GUI. Poiché i manager rileggono l'ultimo valore dai file all'avvio, il riepilogo è
popolato già alla prima esecuzione.

| Blocco | Fonte | Valori |
|---|---|---|
| Ambiente | `ambient.last_result` | temperatura, umidità, VPD |
| Serbatoio | `tank.last_result` | volume, riempimento |
| Indice MCARI2 | `spectro.history[0]` | indice, stato della pianta |
| Crescita | `plant_growth.history[-1]` | altezza |
| Camera | `camera.last_photo` | path e data dell'ultima foto |
| Elaborazione Giornaliera | `daily_th.last_stats` | max/min/media di T, H e VPD |
| Processi Attivi | `process_states()` | elenco dei soli processi in esecuzione |

> Le due history hanno **ordinamenti opposti**: lo spettrometro tiene il più recente in
> testa (`[0]`), la crescita in coda (`[-1]`). Sono indicizzate di conseguenza.

```
aero> -details
====================================================
RIEPILOGO
====================================================

-- Ambiente --
  Temperatura : 21.5 C
  Umidita'    : 63.0 %
  VPD         : 0.9477 kPa
  Acquisito   : 19/07/2026 14:33

-- Serbatoio --
  Volume      : 17.64 L
  Riempimento : 65.3 %
  Misurato    : 19/07/2026 14:35

-- Indice MCARI2 --
  MCARI2      : 0.72
  Stato       : SANA
  Valutato    : 19/07/2026 09:00

-- Crescita --
  Altezza     : 24.3 cm
  Misurato    : 18/07/2026 08:00

-- Camera --
  File        : /home/fishnplants/Desktop/data/IMG/2026-07-19_14-00-03.jpg
  Acquisita   : 19/07/2026 14:00

-- Elaborazione Giornaliera --
  Giorno      : 2026-07-18
  T media     : 23.39 C (max 25 / min 22.04)
  H media     : 60.1 % (max 64.99 / min 55.09)
  VPD medio   : 0.953 kPa (max 1.139 / min 0.778)

-- Processi Attivi --
  * Job - AEROPONICS
  * Lettura Ambient (T/H/VPD)
====================================================
```

Ogni blocco privo di dato stampa `Nessun dato disponibile (--)` invece di andare in errore,
e i processi attivi mostrano `Nessun processo attivo` quando la serra è ferma.

---

## 10. `-save` — lettura e modifica della configurazione

Equivalente della scheda **Configurazione**. A differenza della GUI, che espone un campo
per ogni parametro, la CLI usa **chiavi generiche in notazione puntata**: un solo
meccanismo copre tutte le sezioni di `config.yaml` e resta valido se il file cambia.

Gli **indici numerici attraversano le liste**, quindi `gpio_pins.0.interval` raggiunge
l'intervallo del primo job.

Quattro scelte: `list`, `get`, `set`, `write`.

### 10.1 `-save list`

Stampa l'intera configurazione corrente in YAML.

```
aero> -save list
T_var:
  Topt: 18.0
  Hopt: 65.0
dht22:
  pin: 27
  read_interval: 300
...
```

### 10.2 `-save get <chiave>`

```
aero> -save get dht22.read_interval
dht22.read_interval = 300

aero> -save get gpio_pins.0.interval
gpio_pins.0.interval = 1200
```

Chiave inesistente:

```
aero> -save get tank.pippo
Chiave non trovata: 'tank.pippo'
```

### 10.3 `-save set <chiave> <valore>`

Modifica il valore **in memoria**, stampando il vecchio e il nuovo. Il tipo è dedotto
automaticamente da `cast_value`:

| Scritto | Diventa |
|---|---|
| `900` | intero `900` |
| `18.5` | float `18.5` |
| `true` / `yes` / `on` | `True` |
| `false` / `no` / `off` | `False` |
| `/home/dati/` | stringa |

```
aero> -save set gpio_pins.0.interval 900
gpio_pins.0.interval: 1200 -> 900
(usa '-save write' per rendere la modifica permanente)

aero> -save set dht22.save false
dht22.save: True -> False
(usa '-save write' per rendere la modifica permanente)
```

La modifica è fatta **in place** sul dizionario che i manager tengono per riferimento,
quindi raggiunge anche i manager già istanziati senza riavviare il programma. Resta però
in memoria finché non si esegue `write`.

### 10.4 `-save write`

Scrive la configurazione corrente su `config.yaml`, con gli stessi parametri di `yaml.dump`
usati dalla GUI (`sort_keys=False`, quindi l'ordine delle chiavi del file è preservato).

```
aero> -save write
Configurazione salvata in config.yaml.
```

---

## 11. `help`, `exit`, `quit`

`help` stampa l'elenco dei comandi, ricavato dalla docstring del modulo — quindi
documentazione e codice non possono divergere.

```
aero> help
    -job list                    elenco dei job configurati
    -job active                  job attualmente attivi
    ...
```

`exit` e `quit` (come Ctrl+C e Ctrl+D) chiudono la shell:

```
aero> exit
Program Terminated
```

---

## 12. Tabella riassuntiva di tutti i comandi

Il `-` iniziale è sempre opzionale.

| Comando | Scelte | Effetto | Esempio |
|---|---|---|---|
| `-job list` | — | Elenca i job configurati | `-job list` |
| `-job active` | — | Elenca i job attivi | `-job active` |
| `-job activate` | `<nome_job>` | Avvia il job | `-job activate AEROPONICS` |
| `-job deactivate` | `<nome_job>` | Ferma il job | `-job deactivate IDROPONICS` |
| `-measure th` | — | Lettura continua T/H/VPD | `-measure th` |
| `-measure th now` | — | Lettura singola T/H/VPD | `-measure th now` |
| `-measure th stop` | — | Ferma la lettura continua | `-measure th stop` |
| `-measure water` | — | Lettura continua del serbatoio | `-measure water` |
| `-measure water now` | — | Lettura singola del serbatoio | `-measure water now` |
| `-measure water stop` | — | Ferma la lettura continua | `-measure water stop` |
| `-camera` | — | Avvia l'acquisizione periodica | `-camera` |
| `-camera now` | — | Scatto singolo immediato | `-camera now` |
| `-camera stop` | — | Ferma l'acquisizione periodica | `-camera stop` |
| `-camera preview` | `on` / `off` | Apre o chiude l'anteprima (serve un display) | `-camera preview on` |
| `-daily` | — | Avvia lo scheduler giornaliero (00:01) | `-daily` |
| `-daily now` | — | Elabora subito il giorno precedente | `-daily now` |
| `-daily stats` | — | Statistiche dell'ultima elaborazione | `-daily stats` |
| `-daily stop` | — | Ferma lo scheduler giornaliero | `-daily stop` |
| `-details` | — | Riepilogo generale | `-details` |
| `-save list` | — | Dump della configurazione | `-save list` |
| `-save get` | `<chiave>` | Legge un parametro | `-save get tank.trig_pin` |
| `-save set` | `<chiave> <valore>` | Modifica un parametro in memoria | `-save set tank.n_samples 5` |
| `-save write` | — | Salva su `config.yaml` | `-save write` |
| `help` | — | Elenco dei comandi | `help` |
| `exit` / `quit` | — | Cleanup GPIO e uscita | `exit` |

---

## 13. Sessione di esempio completa

Avvio della serra, verifica e chiusura:

```
$ python3 main.py
AeroGreenHouse CLI - 'help' per l'elenco dei comandi, 'exit' per uscire.

aero> -details                          # com'è la situazione?
...
-- Processi Attivi --
  Nessun processo attivo

aero> -measure water now                # quanta acqua c'è prima di partire?
[2026/07/19 14:35:44] volume = 17.61 L | riempimento = 65.2 % | livello = 19.6 cm | distanza = 12.4 cm

aero> -save get gpio_pins.0.interval    # ogni quanto irriga l'aeroponica?
gpio_pins.0.interval = 1200

aero> -save set gpio_pins.0.interval 900
gpio_pins.0.interval: 1200 -> 900
(usa '-save write' per rendere la modifica permanente)

aero> -save write
Configurazione salvata in config.yaml.

aero> -job activate AEROPONICS
Job 'AEROPONICS' attivato.

aero> -measure th                       # monitoraggio ambientale
Lettura T/H/VPD avviata ('-measure th stop' per fermarla).
[2026/07/19 14:40:12] T = 21.4 C | H = 63.2 % | VPD = 0.9384 kPa

aero> -job active
Job attivi:
  - AEROPONICS

aero> -measure th stop
Lettura T/H/VPD arrestata.

aero> -job deactivate AEROPONICS
Job 'AEROPONICS' disattivato.

aero> exit
Program Terminated
```

---

## 14. Differenze rispetto alla GUI

Tre scostamenti voluti rispetto a `gui.py`:

1. **Nessun avvio automatico dei job.** Il vecchio `main.py` avviava aeroponica e
   idroponica da solo; la shell richiede `-job activate`.
2. **Parametri letti dal config, non dall'interfaccia.** La GUI legge pin, `interval` e
   `on_time` dalle celle del Treeview; la CLI li legge da `config.yaml` — stessa fonte, un
   passaggio in meno.
3. **`save set` modifica davvero i manager.** Nella GUI il salvataggio scrive su un
   dizionario separato da quello dei manager, che restano quindi sui valori vecchi fino al
   riavvio; la CLI muta in place il dizionario condiviso.

Funzioni della GUI **non** esposte dalla CLI, perché fuori dalla richiesta: creazione,
modifica ed eliminazione dei job (`-save set` permette comunque di cambiarne i parametri),
controllo del climatizzatore, taratura dello spettrometro, calibrazione della crescita,
grafico dell'andamento e console dei log.

Due funzioni sono esposte ma **rese in modo diverso**, perché una shell non disegna:
la scheda Camera mostra l'ultima foto, la CLI ne stampa il path (`-details`); la scheda
Ambient mostra il plot giornaliero, la CLI stampa la tabella delle statistiche e il path
del PNG (`-daily stats`). L'anteprima della camera è l'unico comando che richiede comunque
un display.

---

## 15. Errori tipici e cosa significano

| Messaggio | Causa |
|---|---|
| `Comando sconosciuto: 'X'. Usa 'help'.` | Nome di comando errato |
| `Sotto-comando job sconosciuto: 'X'` | Dopo `-job` serve `list`, `active`, `activate` o `deactivate` |
| `Grandezza sconosciuta: 'X'. Usa 'th' o 'water'.` | Dopo `-measure` serve `th` o `water` |
| `Azione sconosciuta: 'X'. Usa 'now' o 'stop'.` | Terzo token non riconosciuto in `-measure` |
| `Azione sconosciuta: 'X'. Usa 'start', 'stop', 'now' o 'preview'.` | Secondo token non riconosciuto in `-camera` |
| `Azione sconosciuta: 'X'. Usa 'start', 'stop', 'now' o 'stats'.` | Secondo token non riconosciuto in `-daily` |
| `Anteprima attiva: usa '-camera preview off' ...` | La camera è occupata dall'anteprima |
| `Acquisizione in corso: la camera e' gia' in uso. ...` | La camera è occupata dall'acquisizione periodica |
| `Nessun dato da elaborare per il giorno precedente.` | Manca il file `TH_<ieri>.txt` in `Daily_Data.th_data_dir` |
| `Job 'X' non trovato in config.yaml.` | Nome del job errato — attenzione al maiuscolo |
| `'X' e' un sensore, non un job attivabile.` | La voce ha `what_type: sensor` |
| `Chiave non trovata: 'X'` | Dot-path inesistente in `-save get`/`set` |
| `Misura non valida: verificare il sensore ultrasonico.` | Lettura del serbatoio fuori range o in timeout |
| `Comando malformato: ...` | Virgolette non chiuse nella riga |
| `Errore nell'esecuzione di 'X': ...` | Eccezione risalita da un manager (tipicamente hardware) |
