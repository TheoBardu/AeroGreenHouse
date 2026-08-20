/*
  ================================================================
  FnP AeroGreenHouse - fish_n_plant_reading_module.ino
  ================================================================
  Modulo Arduino UNO GENERALE per le misure via seriale USB verso il
  Raspberry Pi 3B+: Arduino resta in ascolto di un comando testuale,
  esegue la lettura richiesta con lo strumento giusto e rimanda il
  dato indietro sulla seriale.

  Pensato per essere ESTESO nel tempo: ogni nuova sonda (EC, livello
  acqua, ...) si aggiunge come una funzione dedicata + una riga nella
  tabella COMMANDS qui sotto, senza dover toccare loop()/setup().

  ----------------------------------------------------------------
  COMANDI SUPPORTATI (stringa + invio, terminata da '\n' o '\r'):
    read_pH   -> legge il pH con la sonda Atlas Scientific
                 (Surveyor V3.0 + Lab Grade pH Probe Gen 3)
                 usando la libreria ufficiale Atlas Scientific
                 "Surveyor" (ph_surveyor.h/.cpp + base_surveyor.h)
    read_water_level -> misura la distanza dal sensore HC-SR04
                       finché non trova l'eco (livello acqua / distanza)

  ----------------------------------------------------------------
  PROTOCOLLO DI RISPOSTA
  Per ogni comando valido Arduino risponde con UNA riga nel formato

      <comando>:<valore>

  cosi' il lato Raspberry puo' fare semplicemente riga.split(':').
  Se la lettura non è attendibile, <valore> è "ERR". Un comando non
  riconosciuto risponde con "ERR:<comando>".
  Esempio:
      read_pH:6.87

  ----------------------------------------------------------------
  CALIBRAZIONE pH (nuovo, grazie alla libreria Surveyor)
  Invia da seriale uno di questi comandi con la sonda immersa nella
  soluzione tampone corrispondente:
      CAL,7      -> calibra il punto medio (pH 7)
      CAL,4      -> calibra il punto basso (pH 4)
      CAL,10     -> calibra il punto alto (pH 10)
      CAL,CLEAR  -> azzera la calibrazione (torna ai valori di default)
  I valori vengono salvati in EEPROM e ricaricati automaticamente al
  prossimo avvio da pH_probe.begin() in setup().

  ================================================================
*/

// Libreria ufficiale Atlas Scientific per il modulo Surveyor pH.
// Deve trovarsi nella cartella dello sketch (o nella cartella libraries
// di Arduino) insieme a ph_surveyor.cpp e base_surveyor.h.
#include "ph_surveyor.h"

// ================================================================
// CONFIGURAZIONE SERIALE
// ================================================================
// Deve combaciare con il lato Raspberry
const long BAUDRATE = 9600;


// ================================================================
// TABELLA DEI COMANDI - punto di estensione principale
// ================================================================
// Ogni comando è una coppia (nome testuale ricevuto da seriale, funzione
// da eseguire). La funzione stampa da sola la propria risposta, nel
// formato "<comando>:<valore>".
typedef void (*CommandHandler)(const char *nomeComando);

struct Command {
  const char *name;
  CommandHandler handler;
};

// Handler dei comandi (implementati più sotto in questo file)
void handleReadPH(const char *nomeComando);
void handleReadWaterLevel(const char *nomeComando);

// ---- COME AGGIUNGERE UN NUOVO COMANDO IN FUTURO -----------------
// 1) Scrivi una funzione
//        void handleReadXYZ(const char *nomeComando) { ... }
//    che esegue la misura (rispettando i tempi dello strumento, come
//    fatto qui per il pH) e chiude sempre con:
//        Serial.print(nomeComando);
//        Serial.print(":");
//        Serial.println(valore, decimali);   // oppure "ERR" se non valida
// 2) Aggiungi la sua dichiarazione qui sopra e una riga alla tabella
//    COMMANDS qui sotto, ad esempio:
//        { "read_EC",          handleReadEC },
// Non serve modificare loop(), setup() né processCommand(): il
// dispatch generale li trova già da solo.
// ------------------------------------------------------------------
Command COMMANDS[] = {
  { "read_pH", handleReadPH },
  // { "read_EC",          handleReadEC },         // TODO: conducimetro EZO-EC
  { "read_water_level", handleReadWaterLevel },
};
const int N_COMMANDS = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

// Prototipi (funzioni usate prima della loro definizione nel file)
void processCommand(const String &cmd);
void parse_calibration_cmd(const String &cmd);
float readPHVoltageAveraged();

// ================================================================
// CONFIGURAZIONE SONDA pH
// (Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe Gen 3)
// ================================================================
const int PH_PIN = A0;  // uscita "A" del Surveyor -> A0 Arduino

// Oggetto della libreria Surveyor: gestisce lettura voltaggio,
// conversione in pH e calibrazione/EEPROM al posto nostro.
Surveyor_pH pH_probe = Surveyor_pH(PH_PIN);

// Range di tensione atteso in uscita dal Surveyor (in mV, perché
// pH_probe.read_voltage() della libreria restituisce millivolt e non volt):
//   265 mV -> pH 14      3000 mV -> pH 0
// Il margine sotto/sopra serve solo a lasciare passare letture vicine ai
// bordi senza scartarle; fuori da questo range la sonda è quasi certamente
// scollegata o fuori scala.
const float PH_MV_MIN_VALID = 150.0;
const float PH_MV_MAX_VALID = 3100.0;

//   "Response Time: 95% in 1s"
// La lettura viene quindi mediata su un'INTERA finestra di 5000 ms (5
// campioni distanziati di 1s), invece che sui pochi campioni ravvicinati
// che pH_probe.read_voltage() fa già internamente (tutti nello stesso
// istante): è così che lo sketch rispetta il tempo che lo strumento
// dichiara di richiedere per assestarsi prima che il valore letto sia
// attendibile.
const unsigned long PH_READ_WINDOW_MS = 5000;      // finestra totale di lettura [ms]
const unsigned long PH_SAMPLE_INTERVAL_MS = 1000;  // intervallo fra due campioni [ms]
const int PH_N_SAMPLES = PH_READ_WINDOW_MS / PH_SAMPLE_INTERVAL_MS;  // N campioni

// ================================================================
// CONFIGURAZIONE sensore Ultrasonico per livello H2O
// ================================================================
// Connections:
//   HC-SR04 VCC  -> Arduino 5V
//   HC-SR04 GND  -> Arduino GND
//   HC-SR04 TRIG -> Arduino D2
//   HC-SR04 ECHO -> Arduino D3

#define TRIG_PIN_WATER 2  // pin collegato al TRIG del sensore (Arduino lo pilota in uscita)
#define ECHO_PIN_WATER 3  // pin collegato all'ECHO del sensore (Arduino lo legge in ingresso)

long duration;      // durata dell'impulso di eco, in microsecondi
float distance_cm;  // distanza calcolata, in centimetri


// ================================================================
// SETUP / LOOP
// ================================================================
String inputCommand = "";  // buffer per il comando in arrivo da seriale

void setup() {
  Serial.begin(BAUDRATE);
  Serial.println("FnP fish_n_plant_reading_module pronto.");
  pinMode(TRIG_PIN_WATER, OUTPUT);  // Arduino invia l'impulso di trigger
  pinMode(ECHO_PIN_WATER, INPUT);   // Arduino riceve la risposta (eco)

  // Carica dalla EEPROM l'ultima calibrazione pH salvata (se presente).
  // Se non c'è mai stata una calibrazione, la libreria usa i suoi valori
  // di default e begin() ritorna false: non è un errore bloccante.
  if (pH_probe.begin()) {
    Serial.println("pH: calibrazione caricata da EEPROM.");
  } else {
    Serial.println("pH: nessuna calibrazione salvata, uso valori di default.");
  }
}

void loop() {
  // Legge i caratteri disponibili sulla seriale, uno alla volta, e li
  // accumula in inputCommand finché non arriva un carattere di fine riga.
  // Come in arduino_ultrasonic_test.ino, il loop non si blocca in attesa
  // di dati: se non è arrivato nulla semplicemente non fa niente a questo
  // giro e ricontrolla al giro successivo.
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
// Cerca cmd nella tabella COMMANDS e, se lo trova, esegue l'handler
// corrispondente. È l'UNICO punto dello sketch che deve conoscere tutti
// i comandi disponibili, ed è già pronto per la tabella COMMANDS futura:
// aggiungere un comando non richiede toccare questa funzione.
// Gestisce anche i comandi di calibrazione pH (CAL,7 / CAL,4 / CAL,10 /
// CAL,CLEAR), che non stanno nella tabella COMMANDS perché non seguono
// il protocollo "<comando>:<valore>" ma restituiscono solo un messaggio
// di conferma testuale al Raspberry.
void processCommand(const String &cmd) {
  if (cmd.startsWith("CAL,") || cmd.startsWith("cal,")) {
    parse_calibration_cmd(cmd);
    return;
  }

  for (int i = 0; i < N_COMMANDS; i++) {
    if (cmd.equalsIgnoreCase(COMMANDS[i].name)) {
      COMMANDS[i].handler(COMMANDS[i].name);
      return;
    }
  }

  // Nessun comando corrispondente: risponde con un errore invece di
  // restare muto, così il lato Raspberry si accorge subito di un
  // comando scritto male o non ancora implementato.
  Serial.print("ERR:");
  Serial.println(cmd);
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
// COMANDO: read_pH
// ================================================================
// Sonda Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe (Gen 3).
// La lettura del voltaggio e la conversione in pH sono ora delegate
// alla libreria ufficiale Surveyor (pH_probe.read_voltage() /
// pH_probe.read_ph()), che usa i punti di calibrazione salvati in
// EEPROM invece della formula lineare fissa usata in precedenza.
void handleReadPH(const char *nomeComando) {
  float voltage_mV = readPHVoltageAveraged();

  // Fuori dal range di uscita fisico del Surveyor (con margine): la
  // lettura non è attendibile, es. sonda scollegata o non ancora immersa.
  if (voltage_mV < PH_MV_MIN_VALID || voltage_mV > PH_MV_MAX_VALID) {
    Serial.print(nomeComando);
    Serial.println(":ERR");
    return;
  }

  // Conversione in pH tramite la libreria, usando i punti di calibrazione
  // salvati (o quelli di default se non è mai stata fatta una CAL,x).
  float ph1 = pH_probe.read_ph(voltage_mV);
  delay(1000);
  float ph2 = pH_probe.read_ph(voltage_mV);
  delay(1000);
  float ph3 = pH_probe.read_ph(voltage_mV);
  float ph = (ph1 + ph2 + ph3)/3


  Serial.print(nomeComando);
  Serial.print(":");
  Serial.println(ph, 2);  // 2 cifre decimali, come nello sketch di partenza
}

// Media la tensione letta dalla sonda lungo l'intera finestra di risposta
// (PH_READ_WINDOW_MS = 5000 ms, un campione al secondo), invece che sui
// pochi campioni ravvicinati che pH_probe.read_voltage() fa già da sola
// internamente: è il modo in cui lo sketch "aspetta" il tempo che lo
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
// COMANDO: read_water_level
// ================================================================
// Sensore ultrasonico HC-SR04: misura la distanza in cm e la rispedisce
// sul seriale nel formato "<comando>:<valore>".
void handleReadWaterLevel(const char *nomeComando) {
  // 1) Porta il TRIG basso per un istante
  digitalWrite(TRIG_PIN_WATER, LOW);
  delayMicroseconds(2);

  // 2) Impulso di TRIG di 10 microsecondi
  digitalWrite(TRIG_PIN_WATER, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN_WATER, LOW);

  // 3) Misura il tempo di ECHO alto
  duration = pulseIn(ECHO_PIN_WATER, HIGH);

  // Se non arriva nessun eco, la lettura non è valida
  if (duration == 0) {
    Serial.print(nomeComando);
    Serial.println(":ERR");
    return;
  }

  // 4) Conversione tempo -> distanza
  // Velocita' del suono in aria ~343 m/s = 0.0343 cm/microsecondo
  // Si divide per 2 perche' duration include andata + ritorno
  distance_cm = (duration * 0.0343) / 2.0;

  Serial.print(nomeComando);
  Serial.print(":");
  Serial.println(distance_cm, 2);
}
