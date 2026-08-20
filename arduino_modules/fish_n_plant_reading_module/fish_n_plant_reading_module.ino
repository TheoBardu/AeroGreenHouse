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

  ================================================================
*/

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
//        { "read_EC", handleReadEC },
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
float readPHVoltageAveraged();


// ================================================================
// CONFIGURAZIONE SONDA pH
// (Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe Gen 3)
// ================================================================
const int PH_PIN = A0;               // uscita "A" del Surveyor -> A0 Arduino
const float PH_VCC = 3.3;            // tensione di riferimento ADC dell'Arduino UNO
const int PH_ADC_RESOLUTION = 1023;  // risoluzione ADC 10 bit (0-1023)

// Range di tensione atteso in uscita dal Surveyor:
//   0.265V -> pH 14      3.00V -> pH 0
// Il margine sotto/sopra serve solo a lasciare passare letture vicine ai
// bordi senza scartarle; fuori da questo range la sonda è quasi certamente
// scollegata o fuori scala.
const float PH_V_MIN_VALID = 0.15;
const float PH_V_MAX_VALID = 3.10;


//   "Response Time: 95% in 1s"
// La lettura viene quindi mediata su un'INTERA finestra di 1000 ms (molti
// campioni ravvicinati), invece che su pochi campioni presi in pochi
// millisecondi come in un test rapido: è così che lo sketch rispetta il
// tempo che lo strumento dichiara di richiedere per assestarsi prima che
// il valore letto sia attendibile.
const unsigned long PH_READ_WINDOW_MS = 5000;    // finestra totale di lettura [ms]
const unsigned long PH_SAMPLE_INTERVAL_MS = 1000;  // intervallo fra due campioni [ms]
const int PH_N_SAMPLES = PH_READ_WINDOW_MS / PH_SAMPLE_INTERVAL_MS;  // N campioni

// ================================================================
// CONFIGURAZIONE sensore Ultrasonico
// ================================================================
// Connections:
//   HC-SR04 VCC  -> Arduino 5V
//   HC-SR04 GND  -> Arduino GND
//   HC-SR04 TRIG -> Arduino D2
//   HC-SR04 ECHO -> Arduino D3

#define TRIG_PIN_WATER 2   // pin collegato al TRIG del sensore (Arduino lo pilota in uscita)
#define ECHO_PIN_WATER 3   // pin collegato all'ECHO del sensore (Arduino lo legge in ingresso)

long duration;       // durata dell'impulso di eco, in microsecondi
float distance_cm;   // distanza calcolata, in centimetri


// ================================================================
// SETUP / LOOP
// ================================================================
String inputCommand = "";  // buffer per il comando in arrivo da seriale

void setup() {
  Serial.begin(BAUDRATE);
  Serial.println("FnP fish_n_plant_reading_module pronto.");
  pinMode(TRIG_PIN_WATER, OUTPUT); // Arduino invia l'impulso di trigger
  pinMode(ECHO_PIN_WATER, INPUT);  // Arduino riceve la risposta (eco)
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
void processCommand(const String &cmd) {
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
// COMANDO: read_pH
// ================================================================
// Sonda Atlas Scientific Surveyor V3.0 + Lab Grade pH Probe (Gen 3).
// Metodo di lettura e formula di conversione presi da
// lettura_pH_Surveyor.ino (FnP), confermati dalla pagina Notion
// "pH and EC": https://app.notion.com/p/pH-and-EC-3bdeec0d28bc80fdb120ccff0dacd762
void handleReadPH(const char *nomeComando) {
  float voltage = readPHVoltageAveraged();

  // Fuori dal range di uscita fisico del Surveyor (0.265V-3.00V, con
  // margine): la lettura non è attendibile, es. sonda scollegata o non
  // ancora immersa.
  if (voltage < PH_V_MIN_VALID || voltage > PH_V_MAX_VALID) {
    Serial.print(nomeComando);
    Serial.println(":ERR");
    return;
  }

  // Equazione dal datasheet Atlas Scientific, riportata anche su Notion
  // FnP "pH and EC":  pH = (-5.6548 * V) + 15.509
  // (accuratezza finale dichiarata: ±0.2 punti di pH)
  float ph = (-5.6548 * voltage) + 15.509;

  Serial.print(nomeComando);
  Serial.print(":");
  Serial.println(ph, 2);  // 2 cifre decimali, come nello sketch di partenza
}

// Media la tensione letta su A0 lungo l'intera finestra di risposta della
// sonda (PH_READ_WINDOW_MS = 1000 ms), invece che su pochi campioni
// ravvicinati: è il modo in cui lo sketch "aspetta" il tempo che lo
// strumento dichiara di richiedere per assestarsi (Notion "pH and EC":
// Response Time 95% in 1s) prima di considerare buona la lettura, oltre
// a ridurre il rumore sul segnale analogico.
float readPHVoltageAveraged() {
  long sum = 0;
  for (int i = 0; i < PH_N_SAMPLES; i++) {
    sum += analogRead(PH_PIN);
    delay(PH_SAMPLE_INTERVAL_MS);
  }
  float adcAverage = (float)sum / PH_N_SAMPLES;
  return adcAverage * (PH_VCC / PH_ADC_RESOLUTION);
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