# Manuale d'uso — AeroGreenHouse

> 🇮🇹 Italiano · [🇬🇧 English](User_Manual_EN.md)
>
> Questo è il manuale per **chi usa** la serra. Non serve saper programmare e non c'è nulla da
> installare o da scrivere al computer: si guarda, si preme, si legge.
> Se invece cerchi il funzionamento interno del programma, il documento è
> [`DOCUMENTATION.md`](DOCUMENTATION.md).

---

## Indice

1. [Che cos'è questo programma](#1-che-cosè-questo-programma)
2. [Accendere e spegnere](#2-accendere-e-spegnere)
3. [Come ci si muove nel programma](#3-come-ci-si-muove-nel-programma)
4. [Come si legge un valore](#4-come-si-legge-un-valore)
5. [Riepilogo](#5-riepilogo)
6. [Configurazione](#6-configurazione)
7. [Processi attivi](#7-processi-attivi)
8. [Job](#8-job)
9. [Ambiente](#9-ambiente)
10. [Clima](#10-clima)
11. [H2O](#11-h2o)
12. [Spettro](#12-spettro)
13. [Crescita](#13-crescita)
14. [Camera](#14-camera)
15. [Log](#15-log)
16. [Quando qualcosa non va](#16-quando-qualcosa-non-va)
17. [Manutenzione periodica](#17-manutenzione-periodica)
18. [Domande frequenti](#18-domande-frequenti)
19. [Glossario](#19-glossario)

---

## 1. Che cos'è questo programma

AeroGreenHouse è il **pannello di controllo di una serra**. La serra coltiva piante senza
terra: le radici stanno in una camera chiusa e ricevono acqua e sostanze nutritive da una
pompa, a intervalli regolari.

Il programma fa tre cose:

1. **Comanda** ciò che si accende e si spegne da solo — le pompe dell'acqua e il
   condizionatore.
2. **Misura** com'è l'aria, com'è l'acqua e come stanno le piante, a intervalli che decidi tu.
3. **Conserva e mostra** tutto quello che ha misurato: sullo schermo, in archivio e, se
   configurato, su un sito internet.

### I pezzi della serra, in una frase ciascuno

| Pezzo | Cos'è | Dove lo vedi nel programma |
|---|---|---|
| Il **computer** | un piccolo computer sempre acceso, che fa girare questo programma | è la macchina davanti a cui sei |
| La **scatola delle sonde** | una scatoletta elettronica collegata al computer con un cavo USB, a cui sono attaccate le sonde dell'acqua e i misuratori di distanza | schermata **Configurazione**, riquadro "Schede Arduino" |
| Le **pompe** | portano l'acqua alle radici, si accendono da sole | schermata **Job** |
| Il **sensore dell'aria** | misura temperatura e umidità | schermata **Ambiente** |
| Il **condizionatore** | viene acceso e spento dal programma con un telecomando a infrarossi | schermata **Clima** |
| Le **sonde dell'acqua** | due sonde immerse nella soluzione nutritiva: una misura l'acidità, l'altra la concentrazione | schermata **H2O** |
| I **misuratori di distanza** | due piccoli sensori a ultrasuoni: uno guarda l'acqua nel serbatoio, l'altro guarda le piante dall'alto | schermate **H2O** e **Crescita** |
| Lo **spettrometro** | misura il colore della luce riflessa dalle foglie, per capire se la pianta sta bene | schermata **Spettro** |
| La **fotocamera** | scatta foto delle piante a intervalli regolari | schermata **Camera** |

> **Una cosa importante da sapere fin da subito.** Le sonde dell'acqua e i misuratori di
> distanza **non** sono attaccati al computer: sono attaccati alla scatola delle sonde, che a
> sua volta è attaccata al computer con **un solo cavo USB**. Se quel cavo si stacca, quelle
> quattro misure smettono di funzionare **tutte insieme**, mentre temperatura, umidità, foto e
> spettrometro continuano. È il primo controllo da fare quando qualcosa non va.

---

## 2. Accendere e spegnere

### Avviare il programma

Apri il programma e aspetta qualche secondo: si apre una finestra con una **striscia scura di
icone sul lato sinistro** e, a destra, il contenuto.

La prima cosa che vedi è il **Riepilogo**, già pieno di numeri. Non sono misure appena fatte:
sono le **ultime misure conosciute**, rilette dall'archivio. Accanto a ognuna c'è la sua data,
proprio perché tu possa capire se sono di cinque minuti fa o di tre giorni fa.

### Chiudere il programma

Chiudendo la finestra **si ferma tutto**: le letture automatiche, le pompe comandate dal
programma, l'invio dei dati al sito. Nulla continua di nascosto.

I dati già misurati **non si perdono mai**: sono salvati su disco man mano che vengono presi.
Alla riapertura ritrovi tutto.

> **Vale la pena ripeterlo:** se la serra deve funzionare da sola, la finestra va **lasciata
> aperta**. Chiuderla è come spegnere il quadro comandi.

---

## 3. Come ci si muove nel programma

### La barra laterale

A sinistra c'è una colonna di icone: sono le **undici schermate** del programma. Ne premi una
e il contenuto a destra cambia. Non si perde nulla cambiando schermata: le letture in corso
continuano.

| Icona | Nome | A cosa serve |
|---|---|---|
| ▦ | **Riepilogo** | tutto lo stato della serra a colpo d'occhio |
| ⚙ | **Configurazione** | ogni impostazione: ogni quanto misurare, quali valori considerare buoni, dove sono attaccate le sonde |
| ◉ | **Processi** | quali automatismi sono in funzione in questo momento |
| ⚡ | **Job** | le pompe: quando si accendono e per quanto |
| 🌡 | **Ambiente** | temperatura, umidità e riepilogo della giornata |
| ❄ | **Clima** | accensione automatica del condizionatore |
| 💧 | **H2O** | quanta acqua c'è nel serbatoio e com'è fatta (acidità e concentrazione) |
| ◐ | **Spettro** | l'indice di salute delle piante |
| 🌱 | **Crescita** | quanto sono alte le piante e come crescono nel tempo |
| 📷 | **Camera** | le foto |
| ☰ | **Log** | il diario del programma e **l'elenco degli errori** |

In alto trovi il titolo della schermata, una riga che ne spiega lo scopo e l'**orologio**.

### I colori, ovunque nel programma

| Colore | Significato |
|---|---|
| 🟢 **Verde** | funziona / è attivo / il valore è quello desiderato |
| 🟠 **Arancione** | attenzione: il valore si sta avvicinando a un limite |
| 🔴 **Rosso** | fermo, oppure un valore fuori da quello che hai indicato come accettabile |
| ⚪ **Grigio** | nessuna misura disponibile |

### I tre pulsanti che trovi quasi ovunque

Quasi ogni schermata di misura ha gli stessi tre pulsanti. Vale la pena impararli una volta
sola:

| Pulsante | Cosa fa |
|---|---|
| **📊 Leggi Adesso** (o *Misura Adesso*) | prende **una** misura, subito, e basta. Serve per controllare che una sonda funzioni |
| **▶️ Attiva Lettura** | avvia la misurazione **automatica e ripetuta**: da qui in avanti il programma misura da solo, con l'intervallo scelto in Configurazione. La prima misura parte subito |
| **⏹️ Arresta Lettura** | ferma la misurazione automatica. L'effetto è immediato, anche se il prossimo controllo era previsto fra un giorno |

> **La distinzione che conta:** *Leggi Adesso* è una fotografia, *Attiva Lettura* è una
> sorveglianza. Per far funzionare la serra da sola, quello che serve è **Attiva Lettura**.

---

## 4. Come si legge un valore

### Gli indicatori ad arco

Diversi valori sono mostrati come un **arco a semicerchio**, con una lancetta e il numero al
centro. L'arco si riempie da sinistra a destra e dice **a che punto sei rispetto al massimo**.

Sull'arco possono esserci **bande colorate**: segnano l'intervallo che tu hai indicato come
desiderabile in Configurazione. Se la lancetta è dentro la banda verde, quel valore va bene.

L'arco si usa solo dove esiste un massimo che ha senso (l'umidità va da 0 a 100 %, il
serbatoio da vuoto a pieno). L'altezza delle piante, che non ha un massimo, è mostrata come
semplice numero.

### La data sotto ogni valore

Sotto ogni misura c'è **quando è stata presa**. È l'informazione più importante della
schermata dopo il numero stesso: un pH perfetto misurato tre giorni fa non dice niente
sull'acqua di oggi.

Se leggi **"Nessuna misura"**, quella sonda non è mai stata letta: avvia la lettura, oppure
premi *Leggi Adesso*.

### Le pillole di stato

Sotto certi valori compare una **pillola colorata** con una parola: *Nella norma*,
*Fuori range*, *Nessuna misura*. È la traduzione in parole del confronto fra la misura e i
limiti che hai impostato.

---

## 5. Riepilogo

È la schermata di partenza e risponde a una domanda sola: **come sta la serra adesso?**

È divisa in riquadri:

- **Ambiente** — temperatura, umidità e VPD dell'aria (il VPD è spiegato al §9).
- **H2O** — acidità (pH) e concentrazione (conducibilità) dell'acqua. Questo riquadro ha
  **due date separate**, una per ciascuna delle due sonde: sono due misure indipendenti,
  prese in momenti diversi.
- **Serbatoio** — quanta acqua è rimasta.
- **Indice MCARI2** — quanto stanno bene le piante secondo lo spettrometro.
- **Crescita** — l'altezza dell'ultima misura.
- **Processi Attivi** — l'elenco di ciò che sta funzionando in automatico **in questo
  momento**. Se un automatismo non è avviato, qui non compare affatto.

Questa schermata **non misura niente**: mostra solo i valori raccolti dalle altre. Se un
numero è vecchio, è perché la lettura automatica di quella grandezza non è attiva.

---

## 6. Configurazione

Qui si imposta tutto. È l'unica schermata in cui **quello che scrivi non ha effetto finché non
premi Salva**.

> ⚠️ **Premi sempre "Salva Configurazione" in fondo alla pagina.** Cambiando schermata senza
> salvare, le modifiche vengono perse senza avviso.

La pagina è divisa in riquadri, uno per argomento. In ognuno trovi caselle da compilare;
scorrendo verso il basso li trovi tutti.

### Cosa si imposta, riquadro per riquadro

| Riquadro | Le impostazioni che userai di più |
|---|---|
| **Aria (T/H)** | ogni quanti secondi misurare temperatura e umidità |
| **Acqua — pH e conducibilità** | ogni quanto misurare pH e conducibilità (separatamente), e **quali valori considerare buoni**: pH minimo e massimo, conducibilità minima e massima |
| **Serbatoio** | dimensioni della tanica, quanti litri di riserva far scattare come allarme, ogni quanto controllare il livello |
| **Crescita** | ogni quanti giorni misurare l'altezza, quante misure fare ogni volta |
| **Spettrometro** | ogni quanto misurare l'indice di salute |
| **Camera** | ogni quante ore scattare una foto |
| **Clima** | temperatura e umidità oltre le quali accendere il condizionatore |
| **Schede Arduino** | dove sono attaccate le sonde (vedi sotto) |

### Il riquadro "Schede Arduino"

È il riquadro che descrive **la scatola delle sonde**: a quale presa del computer è collegata
e in quale morsetto è infilata ciascuna sonda. Sembra tecnico, ma nell'uso quotidiano serve
solo in due occasioni: la prima installazione, e quando si sposta un cavo.

**Se la scatola non è mai stata configurata**, o se il programma dice che non la trova:

1. Controlla che il cavo USB sia collegato da entrambe le parti.
2. Premi **🔍 Rileva schede**. Il programma elenca gli apparecchi collegati.
3. Scegli quello comparso (di solito ce n'è uno solo).
4. Premi **Salva Configurazione**.

Sotto trovi una riga per ciascuna delle quattro sonde:

| Sonda | Cosa devi scrivere |
|---|---|
| **pH** | il morsetto in cui è infilata (di norma `A0`) |
| **EC** (conducibilità) | il numero identificativo della sonda (di norma `100`) |
| **US_water** (misuratore del serbatoio) | i due morsetti, "TRIG" ed "ECHO" |
| **US_plant** (misuratore delle piante) | gli altri due morsetti, "TRIG" ed "ECHO" |

I numeri devono corrispondere a **dove i cavi sono realmente infilati**. Se non ne sei sicuro,
non tirare a indovinare: c'è un modo di verificarlo, ed è il pulsante seguente.

### Il pulsante "Prova"

Accanto a ogni sonda c'è un pulsante **Prova**. Premilo: il programma chiede *subito* una
misura a quella sonda e ti dice com'è andata.

| Cosa risponde | Cosa significa | Cosa fai |
|---|---|---|
| Un numero sensato | è tutto a posto | niente, hai finito |
| «pin non validi» | i morsetti che hai scritto non esistono o sono sbagliati | correggi i numeri e riprova |
| «lettura non attendibile» | i morsetti sono validi ma la sonda non risponde | controlla che il cavo della sonda sia inserito bene e che la sonda sia immersa |
| «scheda non raggiungibile» | il problema non è la sonda, è il cavo USB | ricollega il cavo, poi «Rileva schede» |

Questo pulsante è il modo più veloce per verificare un collegamento: non devi avviare niente
né aspettare il prossimo controllo automatico.

### Una nota che troverai nei riquadri Serbatoio e Crescita

Sotto quei due riquadri c'è scritto che i morsetti dei misuratori di distanza si impostano nel
riquadro "Schede Arduino". Non è una svista: **tutti** i collegamenti alla scatola delle sonde
stanno in un posto solo, per non doverli cercare in due punti diversi.

---

## 7. Processi attivi

Un elenco di spie, una per automatismo, aggiornato ogni secondo.

- 🟢 **verde** = sta funzionando;
- 🔴 **rosso** = è fermo.

Rosso **non significa guasto**: significa "non l'hai avviato" o "l'hai fermato tu". È normale
che quasi tutto sia rosso appena aperto il programma: gli automatismi vanno avviati dalle
rispettive schermate.

Nota che **pH ed EC hanno due spie separate**: sono due sorveglianze indipendenti, e puoi
tenerne attiva una sola.

Se hai avviato qualcosa e la spia resta rossa, la spiegazione è nella schermata **Log**, in
fondo, nella sezione "Errori di lettura".

---

## 8. Job

"Job" è il nome che il programma dà a **un'accensione automatica e ripetuta**: tipicamente una
pompa. Un job dice tre cose: *cosa* accendere, *ogni quanto*, e *per quanto tempo*.

I due job già presenti sono:

- **AEROPONICS** — la nebulizzazione alle radici;
- **IDROPONICS** — il ricircolo dell'acqua.

Nella tabella vedi, per ciascuno, l'intervallo, la durata e se è attivo.

| Pulsante | Cosa fa |
|---|---|
| **➕ Nuovo Job** | crea un'accensione automatica per un altro apparecchio |
| **✏️ Modifica Job** | cambia intervallo e durata di quello selezionato |
| **🗑️ Elimina Job** | lo rimuove |
| **✅ Attiva Job** | lo mette in funzione: da qui in avanti si accende da solo |
| **❌ Disattiva Job** | lo ferma |
| **🔄 Ricarica Lista** | rilegge l'elenco |

Per modificare qualcosa: **seleziona prima la riga** nella tabella, poi premi il pulsante.

> ⚠️ **Attenzione ai due tempi, che hanno unità diverse.** L'*intervallo* è in **minuti**
> (ogni quanto si riaccende), la *durata* è in **secondi** (quanto resta accesa). Scambiarli
> significa irrigare per venti minuti invece che per cinque secondi.

---

## 9. Ambiente

### La parte alta: l'aria adesso

Tre valori, presi tutti insieme dallo stesso sensore:

- **Temperatura** in gradi;
- **Umidità** in percentuale;
- **VPD** — la grandezza meno familiare delle tre, e la più utile.

> **Che cos'è il VPD, senza formule.** È **quanta sete ha l'aria**: quanto vapore
> riuscirebbe ancora ad assorbire prima di essere satura. Aria calda e secca ha un VPD alto e
> "tira" acqua dalle foglie; aria fredda e umida ha un VPD basso e non la tira affatto.
>
> Serve perché né la temperatura né l'umidità, da sole, dicono come *la pianta* vive l'aria:
> il 60 % di umidità a 30 °C e il 60 % a 15 °C sono due situazioni completamente diverse per
> una foglia. Il VPD le distingue in un numero solo.
>
> In pratica: **troppo alto** → le piante traspirano più di quanto assorbono e soffrono;
> **troppo basso** → smettono di traspirare, e con la traspirazione si ferma anche il
> trasporto dei nutrimenti.

I tre pulsanti sono i soliti: *Leggi Adesso*, *Attiva Lettura*, *Arresta Lettura*.

### La parte bassa: il riassunto della giornata

Sotto c'è **l'elaborazione giornaliera**: una volta al giorno il programma legge tutte le
misure delle ultime 24 ore e produce medie, minimi, massimi e un **grafico dell'andamento**.

I pulsanti **▶️ Attiva Daily** e **⏹️ Arresta Daily** avviano e fermano questo riassunto
automatico. È anche il riassunto che, se il sito è configurato, viene pubblicato online.

---

## 10. Clima

Il programma può accendere e spegnere il condizionatore da solo, usando un telecomando a
infrarossi: nella serra c'è un piccolo emettitore che imita il telecomando originale.

| Pulsante | Cosa fa |
|---|---|
| **▶️ Attiva Controllo AC** | da ora in poi il programma decide da solo quando accendere e spegnere |
| **⏹️ Disattiva Controllo AC** | smette di intervenire; il condizionatore resta com'è in questo momento |

Una pillola indica **▶ ATTIVO** o **⏹ INATTIVO**, ed è mostrato l'ultimo comando inviato al
condizionatore, con l'ora.

**La regola che segue**, in parole semplici: se la temperatura supera il valore massimo che hai
impostato in Configurazione, oppure lo supera l'umidità, il condizionatore viene acceso.
Resta acceso al massimo per il tempo che hai indicato, poi viene comunque spento: serve a
evitare che resti in funzione per ore se qualcosa non torna. La valutazione viene rifatta a
intervalli regolari.

> Se l'ultimo comando è vecchio di ore e il controllo risulta attivo, vuol dire semplicemente
> che non c'è stato bisogno di intervenire.

---

## 11. H2O

La schermata dell'acqua, divisa in **tre riquadri indipendenti**. Ognuno ha i suoi tre
pulsanti, e ognuno si avvia e si ferma per conto proprio.

### Riquadro 1 — Livello del serbatoio

Quanta acqua è rimasta. Il valore principale è il **volume in litri**; accanto trovi la
percentuale di riempimento e l'altezza dell'acqua.

La misura viene fatta con un misuratore di distanza montato sopra l'acqua: misura **quanto è
lontana la superficie**, e da lì il programma ricava quanta acqua c'è. Perché il conto torni,
in Configurazione devono essere corrette le dimensioni della tanica.

Quando il volume scende sotto la riserva che hai impostato, il programma lo segnala nel
diario. **È il momento di rabboccare.**

### Riquadro 2 — pH dell'acqua

> **Che cos'è il pH.** È **quanto l'acqua è acida**. La scala va da 0 a 14: 7 è neutro, sotto
> è acido, sopra è basico. Nella coltivazione senza terra il pH è decisivo per un motivo
> preciso: **se è sbagliato, le piante non riescono ad assorbire i nutrimenti anche se ci
> sono**. Si può avere una soluzione perfetta e piante affamate.
>
> Il valore desiderato per la maggior parte delle colture sta fra **5.5 e 6.5** — sono i
> limiti preimpostati in Configurazione, e puoi cambiarli.

Il valore compare grande al centro, con una pillola che dice se è nella norma e la data
dell'ultima misura.

**Se il pH è fuori range:** non è un guasto, è un'indicazione agronomica. Si corregge
aggiungendo alla soluzione una piccola quantità di correttore (*pH-* per abbassarlo, *pH+*
per alzarlo), mescolando bene e rimisurando dopo qualche minuto con *📊 Leggi Adesso*. Sempre
poco per volta: il pH si muove più di quanto ci si aspetti.

> ⏱️ **Una misura di pH richiede circa 8 secondi.** È normale: la sonda ha bisogno di
> assestarsi, e il programma aspetta apposta. Se dopo aver premuto *Leggi Adesso* non succede
> nulla per qualche secondo, non premere di nuovo.

### Riquadro 3 — Conducibilità elettrica

> **Che cos'è la conducibilità (EC).** È **quanto la soluzione è concentrata**: quanti sali
> nutritivi ci sono disciolti. L'acqua pura non conduce elettricità; più sali contiene, più
> conduce. Misurando quanto conduce si sa quanto è "ricca".
>
> Troppo bassa: le piante hanno fame. Troppo alta: la soluzione è così concentrata che le
> radici non riescono più ad assorbire acqua — e la pianta appassisce pur essendo immersa
> nell'acqua.

Questo riquadro mostra **tre numeri**, che vengono tutti da un'unica misura:

| Valore | Unità | Cosa dice |
|---|---|---|
| **Conducibilità** | µS/cm | il valore principale, quello da confrontare con i limiti |
| **TDS** | ppm | gli stessi sali espressi come "quanti milligrammi per litro": è la stessa cosa detta in un'altra unità, usata da molti fertilizzanti |
| **Salinità** | PSU | quanto è salata la soluzione |

Non sono tre misure separate: sono tre modi di dire la stessa cosa, ed è per questo che
compaiono e si aggiornano sempre insieme.

**Se la conducibilità è fuori range:** troppo alta → si diluisce aggiungendo acqua; troppo
bassa → si aggiunge fertilizzante. In entrambi i casi poco per volta, si mescola e si
rimisura. Dopo aver corretto la concentrazione conviene **ricontrollare anche il pH**, perché
il fertilizzante lo sposta.

---

## 12. Spettro

Lo spettrometro guarda la luce riflessa dalle foglie e la traduce in un unico numero fra 0 e
1, l'**indice MCARI2**. Detto semplicemente: **le foglie sane riflettono la luce in modo
diverso dalle foglie sofferenti**, e questo strumento se ne accorge prima che il problema sia
visibile a occhio.

Una pillola colorata traduce il numero in una frase:

| Colore | Stato | Cosa vuol dire |
|---|---|---|
| 🔴 Rosso | **Stress** | possibile carenza d'acqua o di nutrimenti (spesso azoto) |
| 🟠 Arancione | **Al limite** | tenere sotto osservazione |
| 🟢 Verde chiaro | **Sana** | tutto bene |
| 🟢 Verde scuro | **Molto sana** | nessuna carenza rilevata |

Sotto trovi lo **storico** delle ultime misure: è più utile del valore singolo, perché quello
che conta è la **tendenza**. Un indice che scende giorno dopo giorno segnala un problema
molto prima che le foglie cambino colore.

I pulsanti sono **🔬 Misura Adesso**, **▶️ Attiva Lettura** e **⏹️ Arresta Lettura**.

> **Come si prende una misura sensata.** Lo strumento va tenuto sempre alla **stessa distanza
> e con la stessa inclinazione** rispetto alle foglie, e possibilmente con la stessa luce
> ambiente. Misure prese in condizioni diverse non sono confrontabili fra loro, e l'indice ha
> senso solo se confrontato con quelli dei giorni precedenti.

---

## 13. Crescita

Quanto sono alte le piante. La misura è fatta da un misuratore di distanza montato **sopra**
le piante e puntato verso il basso: misura quanto è lontana la cima e, sapendo quant'è alto
il punto di partenza, ricava l'altezza.

Sulla schermata trovi l'altezza dell'ultima misura, la sua data, un **grafico** dell'andamento
nel tempo e una tabella con tutte le misure.

| Pulsante | Cosa fa |
|---|---|
| **📏 Misura Adesso** | una misura singola |
| **▶️ Attiva Lettura** | misurazione automatica, normalmente una volta al giorno |
| **⏹️ Arresta Lettura** | ferma la misurazione automatica |
| **📐 Calibrazione** | dice al programma dov'è lo "zero" — vedi sotto |

### La calibrazione: da fare una volta, e fatta bene

Il programma non sa da solo dove finiscono le piante e dove comincia il ripiano. Glielo devi
insegnare **una volta**, all'inizio, e da quel momento tutte le misure si contano da lì.

**Procedura:**

1. Falla **prima che le piante siano cresciute**, o comunque con il campo di misura sgombro.
2. Togli tutto ciò che sta sotto il sensore e che non è il piano di riferimento.
3. Assicurati che la misurazione automatica **non** sia in corso: se lo è, premi prima
   *⏹️ Arresta Lettura*. Il programma si rifiuta di calibrare mentre sta misurando, ed è una
   protezione, non un malfunzionamento.
4. Premi **📐 Calibrazione** e conferma.
5. Il programma misura la distanza attuale e la memorizza come "altezza zero".

Dopo la calibrazione, una misura fatta subito deve dare **0 cm**. Se dà un altro numero,
qualcosa era rimasto sotto il sensore: ripeti.

> ⚠️ **Perché ci si mette cura.** Un errore in questo passaggio si trasferisce **identico su
> tutte le misure future**: se lo zero è sbagliato di 3 cm, ogni altezza sarà sbagliata di
> 3 cm, per sempre, e nessun grafico lo farà notare. È l'unica operazione del programma in cui
> vale la pena essere pignoli.

Se sposti il sensore, o cambi l'altezza del ripiano, **la calibrazione va rifatta**.

---

## 14. Camera

Foto delle piante, per vedere a distanza di settimane quello che giorno per giorno non si
nota.

| Pulsante | Cosa fa |
|---|---|
| **▶️ Attiva acquisizione** | comincia a scattare foto da solo, ogni N ore (N si imposta in Configurazione) |
| **⏹️ Disattiva acquisizione** | smette |
| **📷 Attiva camera** | mostra l'**immagine dal vivo**, per inquadrare bene. Lo stesso pulsante la spegne |

Sotto vedi l'**ultima foto scattata**, con data e ora.

> **Le due funzioni non possono stare accese insieme.** La fotocamera è una sola e non può
> essere usata da due cose contemporaneamente: se provi ad attivare l'anteprima mentre gli
> scatti automatici sono in corso, il programma te lo dice invece di bloccarsi. Spegni una,
> accendi l'altra.

Uso tipico: attivi l'anteprima, sistemi l'inquadratura, spegni l'anteprima, avvii gli scatti
automatici.

---

## 15. Log

Due parti, e la seconda è quella che ti interessa davvero.

### In alto: il diario

Tutto quello che il programma fa, riga per riga, in tempo reale: letture riuscite, pompe
accese, comandi al condizionatore. Le righe sono colorate — rosso per gli errori, arancione
per gli avvisi. Serve soprattutto se devi raccontare a qualcun altro cosa è successo.

### In basso: **Errori di lettura**

Questa sezione elenca **solo le volte in cui una sonda non si è lasciata leggere**, con:

- **quando** è successo;
- **quale sonda** (`pH`, `EC`, `US_water` = serbatoio, `US_plant` = piante);
- **una frase in italiano** che spiega la causa e, quasi sempre, cosa fare.

I messaggi sono scritti per essere letti da chi usa la serra, non da un tecnico: dicono cose
come *«controlla che il cavo USB sia collegato»* o *«correggili nella schermata
Configurazione»*.

L'elenco **si aggiorna da solo** ogni paio di secondi: un errore compare senza che tu debba
fare nulla. C'è comunque un pulsante **🔄 Aggiorna errori**.

Gli errori **restano anche dopo aver chiuso e riaperto** il programma: riaprendo, quelli di
oggi sono ancora lì.

> **Se una spia è rossa e non capisci perché, questa è la sezione da guardare.** In pratica è
> l'unica pagina di diagnostica che devi conoscere.

Nota su cosa **non** trovi qui: un serbatoio in riserva o un pH fuori range non sono errori di
lettura — sono misure riuscite che dicono qualcosa di spiacevole. Compaiono nel diario in alto
e nelle rispettive schermate, non in questo elenco.

---

## 16. Quando qualcosa non va

### Le frasi che puoi leggere, e cosa farne

| Cosa leggi | Cosa significa davvero | Cosa fare |
|---|---|---|
| «scheda non raggiungibile ... controlla che il cavo USB sia collegato» | il computer non trova la scatola delle sonde | ricollega il cavo USB da entrambe le parti; aspetta una decina di secondi; poi Configurazione → **🔍 Rileva schede** → **Salva** |
| «nessuna risposta ... entro 15 secondi» | la scatola è collegata ma non risponde: probabilmente si è bloccata | stacca e riattacca il cavo USB, aspetta qualche secondo, riprova con **Prova** |
| «pin non validi ... correggili nella schermata Configurazione» | i morsetti indicati per quella sonda non corrispondono | Configurazione → "Schede Arduino" → correggi i numeri di quella sonda → **Salva** → **Prova** |
| «lettura non attendibile, controlla il collegamento della sonda» | i collegamenti sono giusti ma la sonda non dà un valore sensato | controlla che il cavetto della sonda sia inserito a fondo e che la sonda sia immersa (per pH ed EC) o che davanti al misuratore di distanza non ci siano ostacoli |
| «valore ... fuori dalla scala 0-14» (pH) | non è una misura, è un guasto | la sonda è scollegata o rotta: verifica il cavetto, poi **Prova** |
| «distanza ... fuori dal range operativo (2-400cm)» | il misuratore vede qualcosa di troppo vicino o non vede niente | togli ostacoli, verifica che il sensore sia puntato dove deve |
| «nessuna scheda Arduino configurata per...» | quella sonda non è mai stata dichiarata | Configurazione → "Schede Arduino" → compila i suoi campi → **Salva** |
| «pH FUORI RANGE» / «EC FUORI RANGE» | **non è un guasto**: la misura è riuscita, il valore non ti piace | correggi la soluzione nutritiva (§11) |
| «LOW WATER ... Riempire la tanica» | **non è un guasto**: il serbatoio è in riserva | rabbocca |

### Se non funziona nessuna misura dell'acqua né delle distanze

Quattro sonde che smettono tutte insieme = **quasi certamente il cavo USB**. È il primo
controllo, prima di toccare qualsiasi impostazione. Temperatura, umidità, foto e spettrometro
che continuano a funzionare confermano la diagnosi: quelli non passano da lì.

**Non serve riavviare il programma**: appena la scatola torna raggiungibile, la lettura
successiva riparte da sola.

### Se un valore resta fermo su un numero vecchio

Non è un guasto: la lettura automatica di quella grandezza non è avviata. Vai nella sua
schermata e premi **▶️ Attiva Lettura**. Per verificare che davvero non funzioni nulla, prova
prima con **📊 Leggi Adesso**.

### Se hai cambiato un'impostazione e non cambia niente

Hai premuto **Salva Configurazione**? È l'errore più comune. Dopo il salvataggio le modifiche
valgono subito e **non serve riavviare il programma**, nemmeno per un cambio di collegamento.

---

## 17. Manutenzione periodica

| Ogni | Cosa fare |
|---|---|
| **Ogni giorno** | uno sguardo al Riepilogo: le date delle misure sono recenti? Il serbatoio ha ancora acqua? |
| **Ogni giorno** | uno sguardo agli "Errori di lettura" in fondo alla schermata Log |
| **Ogni settimana** | sciacquare con acqua pulita le sonde di pH ed EC e asciugarle delicatamente, senza strofinare la punta |
| **Ogni settimana** | controllare che davanti ai due misuratori di distanza non ci siano foglie, condensa o ragnatele |
| **Ogni mese circa** | far ricalibrare le sonde di pH ed EC |
| **A ogni cambio di ciclo colturale** | rifare la calibrazione della crescita (§13) |

### La calibrazione delle sonde di pH ed EC

È l'unica operazione che **non si fa dalle schermate descritte in questo manuale**. Serve
personale che sappia usare la scatola delle sonde direttamente, e serve materiale specifico:

- per il **pH**: soluzioni tampone a pH 7, pH 4 e pH 10;
- per l'**EC**: soluzioni di riferimento a conducibilità nota.

Le sonde perdono progressivamente precisione con l'uso: senza ricalibrazione periodica
continuano a dare numeri, ma numeri sempre meno veri. **Se i valori misurati non tornano con
quello che ti aspetti, il sospetto principale è la calibrazione, non la pianta.**

Rivolgiti a chi ha installato l'impianto: la procedura è descritta nella documentazione
tecnica.

---

## 18. Domande frequenti

**Devo lasciare la finestra sempre aperta?**
Sì, se vuoi che le letture automatiche e le pompe continuino. Chiudere la finestra ferma tutto.

**Se salta la corrente, perdo i dati?**
No. Le misure sono salvate su disco appena prese. Alla riaccensione ritrovi tutto, e gli
errori di oggi sono ancora nell'elenco. Devi però **riavviare le letture automatiche**: non
riprendono da sole.

**Posso tenere attivo solo il pH e non la conducibilità?**
Sì. Ogni misura si avvia e si ferma per conto proprio.

**Ho premuto "Leggi Adesso" sul pH e non succede niente.**
Aspetta una decina di secondi: quella misura richiede circa 8 secondi. Non premere più volte.

**Ho spostato il sensore delle piante. Devo fare qualcosa?**
Sì: rifare la calibrazione della crescita (§13). Altrimenti tutte le altezze future saranno
sbagliate della stessa quantità.

**Ho cambiato il cavo di una sonda di posto.**
Aggiorna i morsetti in Configurazione → "Schede Arduino", **Salva**, poi verifica con
**Prova**. Nessun riavvio.

**Cosa vuol dire che una spia è rossa?**
Che quell'automatismo non è in funzione. Se pensavi di averlo avviato, guarda gli "Errori di
lettura" nella schermata Log.

**Il valore di pH è fuori range: è rotto qualcosa?**
No. È una misura riuscita che dice che l'acqua va corretta. Un guasto produce un messaggio
negli "Errori di lettura", non un valore fuori range.

---

## 19. Glossario

**Aeroponica** — coltivazione in cui le radici stanno in aria e vengono nebulizzate a
intervalli con una soluzione di acqua e nutrimenti.

**Idroponica** — coltivazione senza terra in cui le radici sono a contatto con una soluzione
nutritiva.

**Soluzione nutritiva** — l'acqua con dentro i sali che fanno da cibo alle piante.

**pH** — quanto l'acqua è acida. Scala da 0 a 14, 7 è neutro. Se è sbagliato, le piante non
assorbono i nutrimenti anche se ci sono. Valore desiderato tipico: 5.5–6.5.

**EC (conducibilità elettrica)** — quanto la soluzione è concentrata di sali nutritivi, dedotta
da quanto conduce elettricità. Si misura in µS/cm (microsiemens per centimetro).

**TDS** — gli stessi sali dell'EC, espressi in ppm (parti per milione, cioè milligrammi per
litro). È la stessa informazione in un'altra unità.

**Salinità** — quanto è salata la soluzione, in PSU. Deriva anch'essa dalla misura di EC.

**VPD** — "quanta sete ha l'aria": la spinta che l'aria esercita sulle foglie per farle
traspirare. Combina temperatura e umidità in un numero solo.

**MCARI2** — un numero fra 0 e 1 che riassume lo stato di salute delle piante, ricavato dal
colore della luce che le foglie riflettono.

**Job** — un'accensione automatica e ripetuta di un apparecchio (tipicamente una pompa),
definita da un intervallo e da una durata.

**Ultrasuoni** — il principio con cui funzionano i due misuratori di distanza: emettono un
suono troppo acuto per essere udito e cronometrano quanto ci mette l'eco a tornare. Più
l'eco tarda, più l'oggetto è lontano.

**Calibrazione** — insegnare a uno strumento qual è il valore giusto in una situazione nota,
perché da lì in poi possa misurare correttamente tutte le altre.

**Scheda Arduino** — la "scatola delle sonde": l'apparecchio collegato via USB a cui sono
attaccate le sonde di pH ed EC e i due misuratori di distanza.

**Log** — il diario del programma, cioè l'elenco in ordine di tempo di tutto ciò che ha fatto.
