#
# FnP AeroGreenHouse - TEST: pompa + sensore di flusso YF-S201
# ============================================================
# Cosa fa questo script (volutamente semplice, nessuna classe/funzione
# custom, sullo stesso schema di tests/test.py):
#   1) Accende la pompa tramite il GPIO indicato in PIN_POMPA.
#   2) Aspetta TEMPO_ATTESA_POMPA_S secondi, per lasciare che il flusso
#      d'acqua si stabilizzi prima di misurarlo.
#   3) Manda il comando testuale "read" all'Arduino (che deve avere
#      caricato lo sketch water_flux_test.ino) e aspetta la risposta
#      entro TIMEOUT_RISPOSTA_S secondi.
#   4) Stampa a schermo la risposta ricevuta.
#   5) Spegne SEMPRE la pompa alla fine (anche in caso di errore o
#      Ctrl+C), per non lasciarla accesa incustodita.
#
# Requisiti:
#   pip install pyserial RPi.GPIO
#
# Collegamento hardware: Arduino Uno collegato via cavo USB al Raspberry
# (l'USB fa sia da alimentazione che da canale seriale); pompa collegata
# a un rele' pilotato dal GPIO del Raspberry indicato in PIN_POMPA.
# ============================================================

import serial
import time
import RPi.GPIO as GPIO

# --- Parametri modificabili dall'utente ---

# Pin GPIO (numerazione BCM, come nel resto del progetto) collegato al
# rele' che alimenta la pompa da testare.
PIN_POMPA = 23

# Tempo di attesa (s) fra l'accensione della pompa e l'invio del comando
# "read": serve a lasciare che il flusso d'acqua si stabilizzi prima che
# l'Arduino inizi a misurarlo.
TEMPO_ATTESA_POMPA_S = 5

# Tempo massimo (s) di attesa della risposta dell'Arduino al comando
# "read". Deve restare maggiore dei 5 secondi che l'Arduino impiega a fare
# la sua misura (vedi water_flux_test.ino), altrimenti la risposta arriva
# sempre in timeout.
TIMEOUT_RISPOSTA_S = 10

# --- Parametri di connessione seriale ---

# Porta seriale a cui e' collegato l'Arduino. Su Raspberry Pi e'
# tipicamente /dev/ttyACM0 (vedi anche config.yaml). Per verificare quale
# porta e' la tua: lancia "ls /dev/tty*" nel terminale PRIMA di collegare
# l'Arduino via USB, poi rilancialo DOPO: la porta nuova comparsa
# nell'elenco e' quella giusta da usare qui sotto.
PORTA = '/dev/ttyACM0'

# Deve essere lo STESSO valore di Serial.begin(BAUDRATE) in
# water_flux_test.ino, altrimenti i due lati "parlano" a velocita'
# diverse e i dati arrivano corrotti o illeggibili.
BAUDRATE = 9600

# --- Preparazione GPIO pompa ---
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(PIN_POMPA, GPIO.OUT)

# Apre la connessione seriale verso l'Arduino.
# timeout=TIMEOUT_RISPOSTA_S: se l'Arduino non risponde entro quel tempo,
# readline() piu' sotto restituisce una stringa vuota invece di bloccare
# lo script per sempre.
arduino = serial.Serial(PORTA, BAUDRATE, timeout=TIMEOUT_RISPOSTA_S)

# Collegare/aprire la seriale USB fa RESETTARE automaticamente l'Arduino
# Uno (comportamento normale della scheda, dovuto al DTR sulla
# USB-seriale): serve qualche secondo prima che lo sketch sia ripartito e
# sia di nuovo pronto ad ascoltare.
time.sleep(2)

# Nel reset, l'Arduino manda subito un messaggio di benvenuto. Lo
# svuotiamo dal buffer qui, cosi' non rischiamo di scambiarlo per la
# risposta al comando "read" quando facciamo la readline() piu' sotto.
arduino.reset_input_buffer()

try:
    # Il rele' della pompa e' ATTIVO BASSO, come nel resto del progetto
    # (vedi managers_classes/jobs_manager.py): False/LOW accende la
    # pompa, True/HIGH la spegne.
    GPIO.output(PIN_POMPA, False)
    print("Pompa accesa.")

    print(f"Attendo {TEMPO_ATTESA_POMPA_S} secondi prima della lettura...")
    time.sleep(TEMPO_ATTESA_POMPA_S)

    # Manda il comando testuale, terminato da '\n': lo sketch Arduino
    # accumula i caratteri finche' non trova '\n' o '\r' e SOLO a quel
    # punto esegue la lettura.
    print('Invio comando "read" all\'Arduino...')
    arduino.write(b"read\n")

    # Legge una riga di risposta dall'Arduino, fino al newline che lo
    # sketch manda con Serial.println(...).
    risposta = arduino.readline().decode('utf-8').strip()

    if not risposta:
        # readline() ha esaurito il timeout senza ricevere nulla:
        # possibile causa: Arduino non ancora pronto, cavo USB
        # scollegato, oppure lo sketch caricato non e' quello giusto.
        print("Nessuna risposta dall'Arduino (timeout)")
    else:
        print(f"Risposta ricevuta: {risposta}")

except KeyboardInterrupt:
    # Ctrl+C: interrompe il test in modo pulito.
    print("\nTest interrotto dall'utente.")

finally:
    # Spegne SEMPRE la pompa, qualunque cosa sia successo sopra, cosi'
    # non resta accesa incustodita.
    GPIO.output(PIN_POMPA, True)
    print("Pompa spenta.")
    GPIO.cleanup()
    arduino.close()
