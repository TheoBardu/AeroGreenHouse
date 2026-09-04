/*
  ================================================================
  FnP AeroGreenHouse - fish_n_plant_reading_module_atlas.ino
  ================================================================
  Modulo Arduino UNO GENERALE per le misure via seriale USB verso il
  Raspberry Pi: Arduino resta in ascolto di un comando testuale,
  esegue la lettura richiesta con lo strumento giusto e rimanda il
  dato indietro sulla seriale.

  Pensato per essere ESTESO nel tempo: ogni nuova sonda si aggiunge
  come una funzione dedicata + una riga nella tabella COMMANDS qui
  sotto, senza dover toccare loop()/setup().

  ----------------------------------------------------------------
  I PIN NON SONO PIU' CABLATI NELLO SKETCH
  Il comando porta con se' i pin da usare, cosi' cambiare cablaggio
  significa modificare config.yaml sul Raspberry e NON ricompilare
  l'Arduino. Gli argomenti si separano con la virgola; i due punti
  restano riservati al separatore comando/valore, quindi il lato
  Raspberry puo' continuare a fare riga.split(':').

  ----------------------------------------------------------------
  COMANDI SUPPORTATI (stringa + invio, terminata da '\n' o '\r'):

    read_pH,<pin>            legge il pH con la sonda Atlas Scientific
                             (Surveyor V3.0 + Lab Grade pH Probe Gen 3)
                             collegata al pin analogico indicato.
                             Esempio: read_pH,A0

    read_EC,<indirizzo>      legge la conducibilita' elettrica con il
                             circuito Atlas Scientific EZO-EC via I2C
                             all'indirizzo indicato (default 100).
                             Esempio: read_EC,100

    read_us,<trig>,<echo>    misura la distanza con un sensore
                             ultrasonico HC-SR04 collegato ai due pin
                             digitali indicati. Un solo comando serve
                             TUTTI gli HC-SR04 della scheda: e' la
                             coppia di pin a distinguerli.
                             Esempio: read_us,2,3   (livello acqua)
                                      read_us,4,5   (altezza piante)

  ----------------------------------------------------------------
  PROTOCOLLO DI RISPOSTA
  Per ogni comando valido Arduino risponde con UNA riga nel formato

      <comando completo>:<valore>

  cioe' il comando ricevuto viene rieccheggiato per intero, cosi' il
  Raspberry puo' verificare di aver ricevuto la risposta giusta.
  Esempi:
      read_pH,A0:6.87
      read_EC,100:1250.0,625.0,0.62      (EC uS/cm, TDS ppm, SAL PSU)
      read_us,2,3:12.40

  Se la lettura non e' attendibile <valore> e' "ERR".
  Se un pin indicato non e' utilizzabile <valore> e' "ERRPIN".
  Un comando non riconosciuto risponde con "ERR:<comando>".

  ----------------------------------------------------------------
  CALIBRAZIONE pH
  Invia da seriale uno di questi comandi con la sonda immersa nella
  soluzione tampone corrispondente:
      CAL,7      -> calibra il punto medio (pH 7)
      CAL,4      -> calibra il punto basso (pH 4)
      CAL,10     -> calibra il punto alto (pH 10)
      CAL,CLEAR  -> azzera la calibrazione (torna ai valori di default)
  I valori vengono salvati in EEPROM e ricaricati automaticamente al
  prossimo avvio.

  CALIBRAZIONE EC
  Comandi inoltrati tali e quali al circuito EZO-EC, che risponde con
  il proprio messaggio testuale:
      ECCAL,dry            punto a secco (sonda asciutta)
      ECCAL,low,12880      punto basso, con la soluzione indicata
      ECCAL,high,80000     punto alto, con la soluzione indicata
      ECCAL,clear          azzera la calibrazione
  Esiste anche ECCMD,<comando> per inviare un comando EZO qualunque
  (es. ECCMD,K,1.0 per dichiarare la costante di cella della sonda).

  ----------------------------------------------------------------
  LIBRERIE RICHIESTE (da installare nell'IDE Arduino)
    - Atlas Scientific "Surveyor"  (ph_surveyor.h/.cpp, base_surveyor.h)
      zip in  Esempi/lettura_pH/Libraries/atlas_surveyor.zip
    - Atlas Scientific "Ezo_I2c_lib"  (Ezo_i2c.h/.cpp)
      zip in  Esempi/lettura_EC/Libraries/Ezo_i2c_lib-master.zip

  ================================================================
*/

#include <Wire.h>          // bus I2C, usato dal circuito EZO-EC (pin A4/A5)
#include "ph_surveyor.h"   // libreria ufficiale Atlas per il Surveyor pH
#include "Ezo_i2c.h"       // libreria ufficiale Atlas per i circuiti EZO su I2C

// ================================================================
// CONFIGURAZIONE SERIALE
// ================================================================
// Deve combaciare con il lato Raspberry
const long BAUDRATE = 9600;


// ================================================================
// TABELLA DEI COMANDI - punto di estensione principale
// ================================================================
// Ogni comando e' una coppia (nome testuale ricevuto da seriale, funzione
// da eseguire). L'handler riceve anche gli argomenti (tutto cio' che segue
// la prima virgola) e stampa da solo la propria risposta, nel formato
// "<comando completo>:<valore>".
typedef void (*CommandHandler)(const String &comandoCompleto, const String &args);

struct Command {
  const char *name;
  CommandHandler handler;
};

// Handler dei comandi (implementati piu' sotto in questo file)
void handleReadPH(const String &comandoCompleto, const String &args);
void handleReadEC(const String &comandoCompleto, const String &args);
void handleReadUltrasonic(const String &comandoCompleto, const String &args);

// ---- COME AGGIUNGERE UN NUOVO COMANDO IN FUTURO -----------------
// 1) Scrivi una funzione
//        void handleReadXYZ(const String &comandoCompleto, const String &args)
//    che legge i propri pin da 'args' (con nextArg() + parsePin()), esegue
//    la misura rispettando i tempi dello strumento e chiude sempre con
//    replyValue(comandoCompleto, ...) oppure replyError(comandoCompleto, ...).
// 2) Aggiungi la sua dichiarazione qui sopra e una riga alla tabella
//    COMMANDS qui sotto.
// Non serve modificare loop(), setup() ne' processCommand(): il dispatch
// generale li trova gia' da solo.
// ------------------------------------------------------------------
Command COMMANDS[] = {
  { "read_pH", handleReadPH },
  { "read_EC", handleReadEC },
  { "read_us", handleReadUltrasonic },
};
const int N_COMMANDS = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

// Prototipi (funzioni usate prima della loro definizione nel file)
void processCommand(const String &cmd);
void parse_calibration_cmd(const String &cmd);
void parse_ec_calibration_cmd(const String &cmd);
String nextArg(String &args);
int parsePin(const String &token);
void replyValue(const String &comandoCompleto, const String &valore);
void replyError(const String &comandoCompleto, const char *motivo);
float readPHVoltageAveraged();
float measureDistanceCm(int trigPin, int echoPin);
void usePHPin(int pin);
void useECAddress(uint8_t address);

// ================================================================
// CONFIGURAZIONE SONDA pH
// (Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe Gen 3)
// ================================================================
// Il pin arriva dal comando: qui si tiene un solo oggetto Surveyor_pH,
// ricostruito soltanto quando il Raspberry chiede un pin diverso da
// quello attualmente in uso (ricostruirlo ad ogni lettura significherebbe
// rileggere la EEPROM inutilmente ad ogni misura).
const int PH_DEFAULT_PIN = A0;  // usato se il comando arriva senza argomenti

Surveyor_pH pH_probe = Surveyor_pH(PH_DEFAULT_PIN);
int pH_current_pin = PH_DEFAULT_PIN;

// Range di tensione atteso in uscita dal Surveyor (in mV, perche'
// pH_probe.read_voltage() della libreria restituisce millivolt e non volt):
//   265 mV -> pH 14      3000 mV -> pH 0
// Il margine sotto/sopra serve solo a lasciare passare letture vicine ai
// bordi senza scartarle; fuori da questo range la sonda e' quasi certamente
// scollegata o fuori scala.
const float PH_MV_MIN_VALID = 150.0;
const float PH_MV_MAX_VALID = 3100.0;

//   "Response Time: 95% in 1s"
// La lettura viene quindi mediata su un'INTERA finestra di 5000 ms (5
// campioni distanziati di 1s), invece che sui pochi campioni ravvicinati
// che pH_probe.read_voltage() fa gia' internamente (tutti nello stesso
// istante): e' cosi' che lo sketch rispetta il tempo che lo strumento
// dichiara di richiedere per assestarsi prima che il valore letto sia
// attendibile.
const unsigned long PH_READ_WINDOW_MS = 5000;      // finestra totale di lettura [ms]
const unsigned long PH_SAMPLE_INTERVAL_MS = 1000;  // intervallo fra due campioni [ms]
const int PH_N_SAMPLES = PH_READ_WINDOW_MS / PH_SAMPLE_INTERVAL_MS;  // N campioni

// ================================================================
// CONFIGURAZIONE SONDA EC (Atlas Scientific EZO-EC via I2C)
// ================================================================
// Collegamenti:
//   EZO-EC SDA -> Arduino A4
//   EZO-EC SCL -> Arduino A5
//   EZO-EC VCC -> Arduino 5V      EZO-EC GND -> Arduino GND
//
// Si e' scelto l'I2C e non l'UART (come nell'esempio Atlas, che usa
// SoftwareSerial su D2/D3) per due motivi concreti:
//   1. SoftwareSerial disabilita gli interrupt mentre riceve, e questo
//      corromperebbe il pulseIn() dei sensori ultrasonici;
//   2. l'I2C usa A4/A5 e non sottrae pin digitali, che ora devono restare
//      tutti liberi di essere assegnati da config.yaml.
// In piu' la sonda si indirizza per INDIRIZZO e non per pin, quindi in
// futuro si possono mettere piu' circuiti EZO sullo stesso bus.
const uint8_t EC_DEFAULT_ADDRESS = 100;  // indirizzo I2C di fabbrica dell'EZO-EC
const unsigned long EC_READ_DELAY_MS = 600;  // tempo di elaborazione dichiarato per "R"
const uint8_t EC_BUFFER_LEN = 32;

Ezo_board EC_probe = Ezo_board(EC_DEFAULT_ADDRESS, "EC");
uint8_t EC_current_address = EC_DEFAULT_ADDRESS;

// ================================================================
// CONFIGURAZIONE SENSORI ULTRASONICI HC-SR04
// ================================================================
// Collegamenti (per OGNI sensore):
//   HC-SR04 VCC  -> Arduino 5V
//   HC-SR04 GND  -> Arduino GND
//   HC-SR04 TRIG -> un pin digitale a scelta, dichiarato in config.yaml
//   HC-SR04 ECHO -> un altro pin digitale a scelta, idem
// I pin non sono piu' fissati qui: arrivano nel comando read_us.
const unsigned long US_TIMEOUT_US = 40000;  // ~6.8 m: oltre non c'e' eco utile


// ================================================================
// SETUP / LOOP
// ================================================================
String inputCommand = "";  // buffer per il comando in arrivo da seriale

void setup() {
  Serial.begin(BAUDRATE);
  Serial.println("FnP fish_n_plant_reading_module pronto.");

  // Carica dalla EEPROM l'ultima calibrazione pH salvata (se presente).
  // Se non c'e' mai stata una calibrazione, la libreria usa i suoi valori
  // di default e begin() ritorna false: non e' un errore bloccante.
  if (pH_probe.begin()) {
    Serial.println("pH: calibrazione caricata da EEPROM.");
  } else {
    Serial.println("pH: nessuna calibrazione salvata, uso valori di default.");
  }

  Wire.begin();

  // Sceglie quali valori l'EZO-EC deve includere nella risposta al comando
  // "R". Sono queste righe a determinare che la risposta contenga
  // esattamente la terna EC,TDS,SAL attesa da handleReadEC() e mostrata
  // nell'interfaccia: la gravita' specifica (SG) resta disattivata.
  EC_probe.send_cmd("O,EC,1");
  delay(300);
  EC_probe.send_cmd("O,TDS,1");
  delay(300);
  EC_probe.send_cmd("O,S,1");
  delay(300);
  EC_probe.send_cmd("O,SG,0");
  delay(300);
  Serial.println("EC: uscite EZO impostate su EC,TDS,SAL.");
}

void loop() {
  // Legge i caratteri disponibili sulla seriale, uno alla volta, e li
  // accumula in inputCommand finche' non arriva un carattere di fine riga.
  // Il loop non si blocca in attesa di dati: se non e' arrivato nulla
  // semplicemente non fa niente a questo giro e ricontrolla al successivo.
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      inputCommand.trim();
      if (inputCommand.length() > 0) {
        processCommand(inputCommand);
      }
      inputCommand = "";
    } else {
      inputCommand += c;
    }
  }
}

// ================================================================
// DISPATCH GENERALE: dal testo del comando alla funzione da eseguire
// ================================================================
// Spezza la riga alla PRIMA virgola: la parte davanti e' il nome da cercare
// in COMMANDS, il resto sono gli argomenti (i pin) passati all'handler.
// E' l'UNICO punto dello sketch che deve conoscere tutti i comandi
// disponibili: aggiungerne uno non richiede toccare questa funzione.
// Gestisce anche i comandi di calibrazione (CAL,... per il pH e ECCAL,... /
// ECCMD,... per l'EC), che non stanno nella tabella COMMANDS perche' non
// seguono il protocollo "<comando>:<valore>" ma restituiscono solo un
// messaggio di conferma testuale al Raspberry.
void processCommand(const String &cmd) {
  if (cmd.startsWith("CAL,") || cmd.startsWith("cal,")) {
    parse_calibration_cmd(cmd);
    return;
  }

  if (cmd.startsWith("ECCAL,") || cmd.startsWith("eccal,") ||
      cmd.startsWith("ECCMD,") || cmd.startsWith("eccmd,")) {
    parse_ec_calibration_cmd(cmd);
    return;
  }

  int virgola = cmd.indexOf(',');
  String nome = (virgola < 0) ? cmd : cmd.substring(0, virgola);
  String args = (virgola < 0) ? String("") : cmd.substring(virgola + 1);
  nome.trim();
  args.trim();

  for (int i = 0; i < N_COMMANDS; i++) {
    if (nome.equalsIgnoreCase(COMMANDS[i].name)) {
      COMMANDS[i].handler(cmd, args);
      return;
    }
  }

  // Nessun comando corrispondente: risponde con un errore invece di
  // restare muto, cosi' il lato Raspberry si accorge subito di un
  // comando scritto male o non ancora implementato.
  Serial.print("ERR:");
  Serial.println(cmd);
}

// ================================================================
// UTILITA' PER GLI ARGOMENTI E LE RISPOSTE
// ================================================================

// Stacca il primo argomento da 'args' (consumandolo) e lo restituisce.
// "2,3" -> ritorna "2" e lascia in args "3". Stringa vuota se non c'e'
// piu' nulla da leggere.
String nextArg(String &args) {
  args.trim();
  if (args.length() == 0) {
    return String("");
  }

  int virgola = args.indexOf(',');
  String primo;
  if (virgola < 0) {
    primo = args;
    args = "";
  } else {
    primo = args.substring(0, virgola);
    args = args.substring(virgola + 1);
  }
  primo.trim();
  return primo;
}

// Converte il token di un pin nel numero da passare alle funzioni Arduino.
// Accetta sia la forma analogica "A0".."A5" sia il numero digitale "2".."13".
// Ritorna -1 se il token non e' un pin utilizzabile: cosi' un errore di
// configurazione diventa una risposta ERRPIN e non una scrittura su un pin
// a caso (che potrebbe essere quello di un attuatore).
int parsePin(const String &token) {
  if (token.length() == 0) {
    return -1;
  }

  String t = token;
  t.trim();
  t.toUpperCase();

  if (t.charAt(0) == 'A') {
    String numero = t.substring(1);
    if (numero.length() == 0) {
      return -1;
    }
    for (unsigned int i = 0; i < numero.length(); i++) {
      if (!isDigit(numero.charAt(i))) {
        return -1;
      }
    }
    int idx = numero.toInt();
    if (idx < 0 || idx > 5) {   // l'Arduino UNO ha A0..A5
      return -1;
    }
    return A0 + idx;
  }

  for (unsigned int i = 0; i < t.length(); i++) {
    if (!isDigit(t.charAt(i))) {
      return -1;
    }
  }
  int pin = t.toInt();
  // D0/D1 sono la seriale USB verso il Raspberry: usarli farebbe cadere la
  // comunicazione, quindi si rifiutano esplicitamente.
  if (pin < 2 || pin > 13) {
    return -1;
  }
  return pin;
}

// Unica forma di risposta valida: "<comando completo>:<valore>".
void replyValue(const String &comandoCompleto, const String &valore) {
  Serial.print(comandoCompleto);
  Serial.print(":");
  Serial.println(valore);
}

// motivo: "ERR" (lettura non attendibile) oppure "ERRPIN" (pin non valido).
void replyError(const String &comandoCompleto, const char *motivo) {
  Serial.print(comandoCompleto);
  Serial.print(":");
  Serial.println(motivo);
}

// ================================================================
// COMANDI DI CALIBRAZIONE pH (CAL,7 / CAL,4 / CAL,10 / CAL,CLEAR)
// ================================================================
// Usa direttamente le funzioni di calibrazione della libreria Surveyor,
// che leggono la tensione attuale e la salvano in EEPROM come punto di
// riferimento per pH 7 (mid), pH 4 (low) o pH 10 (high).
void parse_calibration_cmd(const String &cmd) {
  String upper = cmd;
  upper.toUpperCase();

  if (upper == "CAL,7") {
    pH_probe.cal_mid();
    Serial.println("MID CALIBRATED");
  } else if (upper == "CAL,4") {
    pH_probe.cal_low();
    Serial.println("LOW CALIBRATED");
  } else if (upper == "CAL,10") {
    pH_probe.cal_high();
    Serial.println("HIGH CALIBRATED");
  } else if (upper == "CAL,CLEAR") {
    pH_probe.cal_clear();
    Serial.println("CALIBRATION CLEARED");
  } else {
    Serial.print("ERR:");
    Serial.println(cmd);
  }
}

// ================================================================
// COMANDI DI CALIBRAZIONE EC (ECCAL,... / ECCMD,...)
// ================================================================
// A differenza del pH, la calibrazione dell'EC non si fa da libreria ma
// mandando un comando al circuito EZO, che la esegue e la salva da solo.
// Qui si fa quindi da semplice ponte: si traduce ECCAL,<x> in "Cal,<x>",
// si aspetta il tempo di elaborazione dichiarato da Atlas e si rimanda al
// Raspberry la risposta testuale della sonda.
void parse_ec_calibration_cmd(const String &cmd) {
  int virgola = cmd.indexOf(',');
  String resto = cmd.substring(virgola + 1);
  resto.trim();

  if (resto.length() == 0) {
    Serial.print("ERR:");
    Serial.println(cmd);
    return;
  }

  String daInviare;
  if (cmd.startsWith("ECCAL") || cmd.startsWith("eccal")) {
    daInviare = "Cal," + resto;
  } else {
    daInviare = resto;   // ECCMD: comando EZO passato tale e quale
  }

  char buffer[EC_BUFFER_LEN];
  EC_probe.send_cmd(daInviare.c_str());
  delay(1600);  // la calibrazione EZO e' l'operazione piu' lenta (fino a 1.5s)
  EC_probe.receive_cmd(buffer, EC_BUFFER_LEN);

  if (EC_probe.get_error() != Ezo_board::SUCCESS) {
    Serial.print("ERR:");
    Serial.println(cmd);
    return;
  }

  Serial.println(buffer);
}

// ================================================================
// COMANDO: read_pH,<pin>
// ================================================================
// Sonda Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe (Gen 3).
// La lettura del voltaggio e la conversione in pH sono delegate alla
// libreria ufficiale Surveyor (read_voltage() / read_ph()), che usa i punti
// di calibrazione salvati in EEPROM invece di una formula lineare fissa.
void handleReadPH(const String &comandoCompleto, const String &args) {
  String resto = args;
  String token = nextArg(resto);

  int pin = (token.length() == 0) ? PH_DEFAULT_PIN : parsePin(token);
  if (pin < 0) {
    replyError(comandoCompleto, "ERRPIN");
    return;
  }
  usePHPin(pin);

  float voltage_mV = readPHVoltageAveraged();

  // Fuori dal range di uscita fisico del Surveyor (con margine): la
  // lettura non e' attendibile, es. sonda scollegata o non ancora immersa.
  if (voltage_mV < PH_MV_MIN_VALID || voltage_mV > PH_MV_MAX_VALID) {
    replyError(comandoCompleto, "ERR");
    return;
  }

  // Conversione in pH tramite la libreria, usando i punti di calibrazione
  // salvati (o quelli di default se non e' mai stata fatta una CAL,x).
  float ph1 = pH_probe.read_ph();
  delay(1000);
  float ph2 = pH_probe.read_ph();
  delay(1000);
  float ph3 = pH_probe.read_ph();
  float ph = (ph1 + ph2 + ph3) / 3.0;

  replyValue(comandoCompleto, String(ph, 2));  // 2 cifre decimali
}

// Ricostruisce l'oggetto Surveyor solo se il pin richiesto e' cambiato:
// begin() rilegge la EEPROM, quindi non ha senso rifarlo ad ogni misura.
void usePHPin(int pin) {
  if (pin == pH_current_pin) {
    return;
  }
  pH_probe = Surveyor_pH(pin);
  pH_probe.begin();
  pH_current_pin = pin;
}

// Media la tensione letta dalla sonda lungo l'intera finestra di risposta
// (PH_READ_WINDOW_MS = 5000 ms, un campione al secondo), invece che sui
// pochi campioni ravvicinati che pH_probe.read_voltage() fa gia' da sola
// internamente: e' il modo in cui lo sketch "aspetta" il tempo che lo
// strumento dichiara di richiedere per assestarsi (Response Time 95% in
// 1s) prima di considerare buona la lettura, oltre a ridurre il rumore.
float readPHVoltageAveraged() {
  float sum_mV = 0;
  for (int i = 0; i < PH_N_SAMPLES; i++) {
    sum_mV += pH_probe.read_voltage();
    delay(PH_SAMPLE_INTERVAL_MS);
  }
  return sum_mV / PH_N_SAMPLES;
}

// ================================================================
// COMANDO: read_EC,<indirizzo I2C>
// ================================================================
// Circuito Atlas Scientific EZO-EC interrogato via I2C. Il comando "R"
// restituisce in UNA sola risposta i valori abilitati in setup(), separati
// da virgola: conducibilita' (uS/cm), solidi disciolti totali (ppm) e
// salinita' (PSU). Vengono rimandati tutti e tre al Raspberry nello stesso
// ordine, cosi' una sola lettura popola tutta la scheda EC dell'interfaccia.
void handleReadEC(const String &comandoCompleto, const String &args) {
  String resto = args;
  String token = nextArg(resto);

  uint8_t address = EC_DEFAULT_ADDRESS;
  if (token.length() > 0) {
    long value = token.toInt();
    // Gli indirizzi I2C a 7 bit validi vanno da 1 a 127.
    if (value < 1 || value > 127) {
      replyError(comandoCompleto, "ERRPIN");
      return;
    }
    address = (uint8_t)value;
  }
  useECAddress(address);

  char buffer[EC_BUFFER_LEN];
  EC_probe.send_cmd("R");
  delay(EC_READ_DELAY_MS);
  EC_probe.receive_cmd(buffer, EC_BUFFER_LEN);

  // Sonda che non risponde, ancora occupata o senza dati: lettura da buttare.
  if (EC_probe.get_error() != Ezo_board::SUCCESS) {
    replyError(comandoCompleto, "ERR");
    return;
  }

  // Come nell'esempio Atlas: se il primo carattere non e' una cifra la
  // risposta non e' una misura ma un messaggio di stato del circuito.
  if (!isDigit(buffer[0])) {
    replyError(comandoCompleto, "ERR");
    return;
  }

  // I valori sono gia' nel formato "EC,TDS,SAL": si rimandano cosi' come
  // sono, senza riformattarli, per non perdere cifre significative.
  replyValue(comandoCompleto, String(buffer));
}

// Cambia l'indirizzo dell'oggetto EZO solo se necessario.
void useECAddress(uint8_t address) {
  if (address == EC_current_address) {
    return;
  }
  EC_probe.set_address(address);
  EC_current_address = address;
}

// ================================================================
// COMANDO: read_us,<trig>,<echo>
// ================================================================
// Sensore ultrasonico HC-SR04: misura la distanza in cm sui due pin
// indicati nel comando. Un unico handler serve tutti gli HC-SR04 collegati
// alla scheda (livello del serbatoio, altezza delle piante, ...): quale
// sensore venga letto lo decide la coppia di pin che arriva dal Raspberry.
void handleReadUltrasonic(const String &comandoCompleto, const String &args) {
  String resto = args;
  int trigPin = parsePin(nextArg(resto));
  int echoPin = parsePin(nextArg(resto));

  // Servono entrambi i pin, e devono essere diversi fra loro.
  if (trigPin < 0 || echoPin < 0 || trigPin == echoPin) {
    replyError(comandoCompleto, "ERRPIN");
    return;
  }

  float distance_cm = measureDistanceCm(trigPin, echoPin);

  if (distance_cm < 0) {
    replyError(comandoCompleto, "ERR");
    return;
  }

  replyValue(comandoCompleto, String(distance_cm, 2));
}

// Misura vera e propria: emette l'impulso di trigger e cronometra l'eco.
// I pinMode() si fanno qui e non in setup() proprio perche' i pin non sono
// piu' noti a tempo di compilazione. Ritorna -1.0 se non arriva nessun eco.
float measureDistanceCm(int trigPin, int echoPin) {
  pinMode(trigPin, OUTPUT);  // Arduino invia l'impulso di trigger
  pinMode(echoPin, INPUT);   // Arduino riceve la risposta (eco)

  // 1) Porta il TRIG basso per un istante
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  // 2) Impulso di TRIG di 10 microsecondi
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // 3) Misura il tempo di ECHO alto
  long duration = pulseIn(echoPin, HIGH, US_TIMEOUT_US);

  // Se non arriva nessun eco entro il timeout, la lettura non e' valida
  if (duration == 0) {
    return -1.0;
  }

  // 4) Conversione tempo -> distanza
  // Velocita' del suono in aria ~343 m/s = 0.0343 cm/microsecondo
  // Si divide per 2 perche' duration include andata + ritorno
  return (duration * 0.0343) / 2.0;
}
