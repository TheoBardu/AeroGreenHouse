/*
  ================================================================
  FnP AeroGreenHouse - TEST: water_flux_test.ino
  ================================================================
  Sketch di TEST (volutamente semplice, non integrato nella tabella
  comandi estendibile del modulo principale) per il sensore di
  flusso ad effetto Hall YF-S201.

  Arduino resta in ascolto sulla porta seriale USB verso il
  Raspberry Pi. Quando riceve il comando testuale "read" (terminato
  da '\n' o '\r', come manda water_flux_test.py), misura la portata
  per 5 secondi (5 campioni da 1 secondo, poi ne fa la media) e
  rimanda al Raspberry il valore medio in L/min, nel formato
  "read:<valore>" (stesso protocollo "<comando>:<valore>" usato dagli
  altri sketch di questo progetto).

  Collegamento YF-S201:
    Rosso  -> 5V
    Nero   -> GND
    Giallo -> pin segnale (impulsi), vedi PIN_SENSORE_FLUSSO qui sotto
              (deve essere un pin con interrupt: su Uno solo 2 o 3)
  ================================================================
*/

// ================================================================
// CONFIGURAZIONE SENSORE DI FLUSSO
// ================================================================

// Pin a cui e' collegato il filo giallo (segnale) del YF-S201.
// Deve essere un pin che supporta gli interrupt: su Arduino Uno solo
// i pin 2 e 3 li supportano.
const int PIN_SENSORE_FLUSSO = 2;

// Fattore di calibrazione del YF-S201 (da datasheet): il sensore
// genera 7.5 impulsi al secondo per ogni L/min di portata, quindi
// portata (L/min) = impulsi_al_secondo / 7.5.
const float FATTORE_CALIBRAZIONE = 7.5;

// Finestra totale di lettura e durata di ogni singolo campione: 5
// campioni da 1 secondo ciascuno, poi se ne fa la media (stesso
// schema di campionamento usato per il pH nel modulo principale).
const unsigned long FLUSSO_READ_WINDOW_MS = 5000;
const unsigned long FLUSSO_SAMPLE_INTERVAL_MS = 1000;
const int FLUSSO_N_SAMPLES = FLUSSO_READ_WINDOW_MS / FLUSSO_SAMPLE_INTERVAL_MS;

// ================================================================
// CONFIGURAZIONE SERIALE
// ================================================================
// Deve combaciare con il lato Raspberry (BAUDRATE in water_flux_test.py)
const long BAUDRATE = 9600;

// Conteggio impulsi aggiornato dall'interrupt: volatile perche' viene
// modificato "in background", fuori dal normale flusso del programma.
volatile unsigned long pulseCount = 0;

void contaImpulso() {
  pulseCount++;
}

// ================================================================
// SETUP / LOOP
// ================================================================
String inputCommand = "";  // buffer per il comando in arrivo da seriale

void setup() {
  Serial.begin(BAUDRATE);
  Serial.println("FnP water_flux_test pronto.");

  pinMode(PIN_SENSORE_FLUSSO, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_SENSORE_FLUSSO), contaImpulso, FALLING);
}

void loop() {
  // Non bloccante: accumula i caratteri in arrivo finche' non trova un
  // fine riga, poi esegue il comando (stesso schema del modulo principale).
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

void processCommand(const String &cmd) {
  if (cmd.equalsIgnoreCase("read")) {
    leggiFlusso();
  } else {
    // Comando non riconosciuto: risponde con un errore invece di
    // restare muto, cosi' il lato Raspberry se ne accorge subito.
    Serial.print("ERR:");
    Serial.println(cmd);
  }
}

// ================================================================
// COMANDO: read
// ================================================================
// Misura la portata su FLUSSO_N_SAMPLES campioni da 1 secondo,
// azzerando il conteggio impulsi a inizio di ogni campione, e rimanda
// al Raspberry la media dei campioni ottenuti.
void leggiFlusso() {
  float sommaLitriMin = 0;

  for (int i = 0; i < FLUSSO_N_SAMPLES; i++) {
    noInterrupts();
    pulseCount = 0;
    interrupts();

    delay(FLUSSO_SAMPLE_INTERVAL_MS);

    // Disabilita brevemente gli interrupt per leggere il contatore
    // senza rischiare che venga aggiornato a meta' lettura.
    noInterrupts();
    unsigned long impulsi = pulseCount;
    interrupts();

    float litriMin = impulsi / FATTORE_CALIBRAZIONE;
    sommaLitriMin += litriMin;
  }

  float media = sommaLitriMin / FLUSSO_N_SAMPLES;

  Serial.print("read:");
  Serial.println(media, 2);  // 2 cifre decimali
}
