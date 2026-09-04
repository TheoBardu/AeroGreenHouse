#
# FnP AeroGreenHouse - TEST: Raspberry Pi <-> Arduino via seriale USB
# ============================================================
# Cosa fa questo script (volutamente semplice, nessuna classe/funzione custom):
#   Apre la porta seriale USB verso l'Arduino Uno, gli manda uno dei COMANDI
#   TESTUALI dello sketch fish_n_plant_reading_module_atlas.ino (terminato da
#   newline, come lo sketch si aspetta), aspetta la risposta nel formato
#   "<comando>:<valore>" e la stampa a schermo.
#
#   I comandi portano con se' i pin da usare (es. "read_us,2,3"), quindi da
#   qui si puo' provare qualunque cablaggio senza ricompilare l'Arduino.
#
# Requisiti:
#   pip install pyserial
#
# Collegamento hardware: Arduino Uno collegato via cavo USB al Raspberry
# (l'USB fa sia da alimentazione che da canale seriale, non serve altro).
# ============================================================

import serial
import time

# --- Parametri di connessione ---

# Porta seriale a cui e' collegato l'Arduino. Su Raspberry Pi Zero e'
# tipicamente /dev/ttyACM0 (a volte /dev/ttyUSB0 con alcuni cloni di Arduino).
# Per verificare quale porta e' la tua: lancia "ls /dev/tty*" nel terminale
# PRIMA di collegare l'Arduino via USB, poi rilancialo DOPO: la porta nuova
# comparsa nell'elenco e' quella giusta da usare qui sotto.
PORTA = '/dev/ttyUSB0'

# Deve essere lo STESSO valore di Serial.begin(BAUDRATE) nello sketch
# Arduino, altrimenti i due lati "parlano" a velocita' diverse e i dati
# arrivano corrotti o illeggibili.
BAUDRATE = 9600

# Apre la connessione seriale.
# timeout=2: se l'Arduino non risponde entro 2 secondi, readline() qui sotto
# restituisce una stringa vuota invece di bloccare lo script per sempre.
arduino = serial.Serial(PORTA, BAUDRATE, timeout=10)

# Collegare/aprire la seriale USB fa RESETTARE automaticamente l'Arduino Uno
# (comportamento normale della scheda, dovuto al DTR sulla USB-seriale):
# serve qualche secondo prima che lo sketch sia ripartito e sia di nuovo
# pronto ad ascoltare. Senza questa pausa, il primo comando rischia di
# arrivare mentre l'Arduino si sta ancora riavviando e andrebbe perso.
time.sleep(2)

# Nel reset, l'Arduino manda subito un messaggio di benvenuto
# (Serial.println("FnP fish_n_plant_reading_module pronto.") in setup()).
# Lo svuotiamo dal buffer qui, cosi' non rischiamo di scambiarlo per la
# risposta a un comando quando facciamo la prima readline() piu' sotto.
arduino.reset_input_buffer()

# print(f"Connesso ad Arduino su {PORTA} a {BAUDRATE} baud. Premi Ctrl+C per uscire.")
# Comandi testuali riconosciuti dallo sketch Arduino (vedi tabella COMMANDS
# nel .ino). I pin viaggiano DENTRO il comando, separati da virgola: cosi'
# per provare un sensore su altri pin basta cambiare questi numeri, senza
# ricompilare la scheda.
#   read_pH,<pin>          pin analogico del Surveyor
#   read_EC,<indirizzo>    indirizzo I2C del circuito EZO-EC
#   read_us,<trig>,<echo>  coppia di pin dell'HC-SR04
cmds = {
    0: "quit",
    1: "read_us,2,3\n",     # livello del serbatoio
    2: "read_us,4,5\n",     # altezza delle piante
    3: "read_pH,A0\n",
    4: "read_EC,100\n",
}

try:
    while True:

        cosa = int(input(f'Cosa devo fare? {cmds}'))
        if cosa == 0:
            break

        # Manda il comando testuale, terminato da '\n': lo sketch Arduino
        # accumula i caratteri finche' non trova '\n' o '\r' e SOLO a quel
        # punto esegue processCommand(). Un byte singolo senza terminatore
        # (come nella versione precedente di questo script) non basta:
        # l'Arduino resta in attesa per sempre e non risponde mai.
        print(cmds[cosa])
        arduino.write((cmds[cosa]).encode('utf-8'))

        # Legge una riga di risposta dall'Arduino, fino al newline che lo
        # sketch manda con Serial.println(...).
        # .decode('utf-8') converte i byte grezzi ricevuti in una stringa di
        # testo leggibile; .strip() toglie newline/spazi bianchi finali.
        risposta = arduino.readline().decode('utf-8').strip()

        if not risposta:
            # readline() ha esaurito il timeout senza ricevere nulla:
            # possibile causa: Arduino non ancora pronto, cavo USB scollegato,
            # oppure lo sketch caricato non e' quello giusto.
            print("Nessuna risposta dall'Arduino (timeout)")
            continue

        # Lo sketch risponde nel formato "<comando>:<valore>", quindi
        # facciamo lo split come indicato nel commento del protocollo
        # nel file .ino.
        parti = risposta.split(':')
        if len(parti) != 2:
            print(f"Risposta inattesa: {risposta}")
            continue

        comando_ricevuto, valore = parti
        if valore == 'ERR':
            print(f"Lettura non attendibile per '{comando_ricevuto}' (ERR): "
                  f"controlla il collegamento del sensore.")
        else:
            print(f"{comando_ricevuto}: {valore}")

except KeyboardInterrupt:
    # Ctrl+C: interrompe il test in modo pulito, chiudendo la porta seriale.
    print("\nTest interrotto dall'utente.")

finally:
    arduino.close()