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

# Tempo massimo di attesa della risposta a un comando, in secondi. Una
# read_pH impegna l'Arduino per ~8s (5 campioni di tensione + 3 di pH), quindi
# va tenuto abbondante. Scaduto questo tempo lo script stampa "Nessuna
# risposta" invece di restare bloccato per sempre.
TIMEOUT_S = 15

# Attesa MINIMA dopo l'apertura della porta, prima di considerare l'Arduino
# pronto (vedi sotto).
RESET_DELAY_S = 4

# Valori (uS/cm) delle soluzioni di calibrazione EC usate con ECCAL,low e
# ECCAL,high (vedi sotto): tipici Atlas Scientific, cambiali qui se usi
# soluzioni diverse.
EC_CAL_LOW_VALUE = 84
EC_CAL_HIGH_VALUE = 1413

# Costante di cella (K) della sonda EC in uso: sonda K 0.1 di Atlas Scientific.
# Default di fabbrica dell'EZO-EC e' K 1.0: va dichiarata una volta sola (resta salvata
# nell'EEPROM del circuito EZO, non nell'Arduino). Cambiala qui se monti una sonda con
# costante di cella diversa.
EC_PROBE_K = 0.1

# Apre la connessione seriale.
arduino = serial.Serial(PORTA, BAUDRATE, timeout=TIMEOUT_S)

# Collegare/aprire la seriale USB fa RESETTARE automaticamente l'Arduino Uno
# (comportamento normale della scheda, dovuto al DTR sulla USB-seriale):
# serve qualche secondo prima che lo sketch sia ripartito e sia di nuovo
# pronto ad ascoltare. Senza questa pausa, il primo comando rischia di
# arrivare mentre l'Arduino si sta ancora riavviando e andrebbe perso.
#
# Nel reset, setup() stampa PIU' righe di benvenuto, e l'ultima
# ("EC: uscite EZO impostate...") arriva solo dopo la configurazione
# dell'EZO-EC (~1.2s di delay, oltre ai ~2s del bootloader). Un semplice
# sleep(2) + reset_input_buffer() NON basta: il buffer viene svuotato prima
# che arrivi l'ultima riga, che poi viene letta come risposta al primo
# comando, e da li' ogni risposta e' sfasata di un comando.
# Qui invece si leggono (e stampano) le righe di benvenuto finche' la
# seriale non tace per mezzo secondo, e comunque per almeno RESET_DELAY_S.
print("Attendo l'avvio dell'Arduino...")
inizio = time.time()
arduino.timeout = 0.5
while True:
    riga = arduino.readline().decode('utf-8', errors='replace').strip()
    if riga:
        print(f"  [avvio] {riga}")
        continue
    if time.time() - inizio >= RESET_DELAY_S:
        break
arduino.timeout = TIMEOUT_S
arduino.reset_input_buffer()
print("Arduino pronto.")

# print(f"Connesso ad Arduino su {PORTA} a {BAUDRATE} baud. Premi Ctrl+C per uscire.")
# Comandi testuali riconosciuti dallo sketch Arduino (vedi tabella COMMANDS
# nel .ino). I pin viaggiano DENTRO il comando, separati da virgola: cosi'
# per provare un sensore su altri pin basta cambiare questi numeri, senza
# ricompilare la scheda.
#   read_pH,<pin>          pin analogico del Surveyor
#   read_EC,<indirizzo>    indirizzo I2C del circuito EZO-EC
#   read_us,<trig>,<echo>  coppia di pin dell'HC-SR04
#   CAL,7 / CAL,4 / CAL,10 / CAL,CLEAR    calibrazione pH (punto medio/basso/
#                                         alto/azzeramento), con la sonda
#                                         immersa nella soluzione tampone
#   ECCAL,dry / low / high / clear       calibrazione EC, inoltrata cosi'
#                                         com'e' al circuito EZO-EC
#   ECCMD,<comando>        comando EZO libero (es. K,1.0 per la costante
#                          di cella); il comando viene chiesto a runtime
cmds = {
    0: "quit",
    1: "read_us,2,3\n",     # livello del serbatoio
    2: "read_us,4,5\n",     # altezza delle piante
    3: "read_pH,A0\n",
    4: "read_EC,100\n",
    5: "CAL,7\n",                             # calibrazione pH punto medio
    6: "CAL,4\n",                             # calibrazione pH punto basso
    7: "CAL,10\n",                            # calibrazione pH punto alto
    8: "CAL,CLEAR\n",                         # azzera calibrazione pH
    9: "ECCAL,dry\n",                         # calibrazione EC punto a secco
    10: f"ECCAL,low,{EC_CAL_LOW_VALUE}\n",    # calibrazione EC punto basso
    11: f"ECCAL,high,{EC_CAL_HIGH_VALUE}\n",  # calibrazione EC punto alto
    12: "ECCAL,clear\n",                      # azzera calibrazione EC
    13: "ECCMD,<comando EZO>\n",              # comando EZO libero, chiesto a runtime
    14: f"ECCMD,K,{EC_PROBE_K}\n",             # dichiara la costante di cella K della sonda EC
}

try:
    while True:

        cosa = int(input(f'Cosa devo fare? {cmds}'))
        if cosa == 0:
            break

        # ECCMD e' l'unico comando che non viaggia gia' completo nel
        # dizionario: il comando EZO vero e proprio dipende da cosa serve
        # fare in quel momento, quindi si chiede qui, senza toccare cmds.
        riga_da_inviare = cmds[cosa]
        if cosa == 13:
            comando_ezo = input("Comando EZO da inviare (es. K,1.0): ").strip()
            riga_da_inviare = f"ECCMD,{comando_ezo}\n"

        # Manda il comando testuale, terminato da '\n': lo sketch Arduino
        # accumula i caratteri finche' non trova '\n' o '\r' e SOLO a quel
        # punto esegue processCommand(). Un byte singolo senza terminatore
        # (come nella versione precedente di questo script) non basta:
        # l'Arduino resta in attesa per sempre e non risponde mai.
        print(riga_da_inviare)
        comando = riga_da_inviare.strip()
        # Butta via eventuali residui (es. una risposta arrivata dopo il
        # timeout della lettura precedente), cosi' non vengono scambiati
        # per la risposta a QUESTO comando.
        arduino.reset_input_buffer()
        arduino.write(riga_da_inviare.encode('utf-8'))

        # I comandi di calibrazione pH (CAL,..) rispondono con una riga di
        # conferma testuale libera (es. "MID CALIBRATED"), non echeggiata.
        # I comandi EC (ECCAL,.. / ECCMD,..) rispondono invece sempre nel
        # formato "<comando>:<esito>", dove <esito> e' OK (successo),
        # ERR_SYNTAX (l'EZO ha rifiutato il comando), ERR_NOT_READY (l'EZO
        # stava ancora elaborando) o ERR_NODATA (nessuna risposta I2C dal
        # chip: cablaggio/indirizzo), oppure "ERR:<cmd>" se il comando non
        # e' riconosciuto dallo sketch stesso (es. argomento mancante). Si
        # stampa quindi la prima riga non vuota ricevuta, interpretandola
        # secondo questi formati.
        if comando.upper().startswith(("CAL,", "ECCAL,", "ECCMD,")):
            scadenza = time.time() + TIMEOUT_S
            risposta = ''
            while time.time() < scadenza:
                arduino.timeout = max(0.1, scadenza - time.time())
                riga = arduino.readline().decode('utf-8', errors='replace').strip()
                if riga:
                    risposta = riga
                    break
            arduino.timeout = TIMEOUT_S

            prefisso_esito = comando.lower() + ':'
            if not risposta:
                print(f"Nessuna risposta dall'Arduino a '{comando}' entro {TIMEOUT_S}s (timeout): "
                      f"il comando non e' arrivato allo sketch (USB scollegato? Arduino bloccato?).")
            elif risposta.lower() == ('ERR:' + comando).lower():
                print(f"Comando '{comando}' non riconosciuto dallo sketch Arduino.")
            elif risposta.lower().startswith(prefisso_esito):
                esito = risposta[len(prefisso_esito):]
                if esito.upper() == 'OK':
                    print(f"'{comando}' eseguito con successo dall'EZO.")
                elif esito.upper() == 'ERR_SYNTAX':
                    print(f"'{comando}': l'EZO ha ricevuto il comando ma lo ha rifiutato (sintassi errata).")
                elif esito.upper() == 'ERR_NOT_READY':
                    print(f"'{comando}': l'EZO segnala di essere ancora occupato (letto troppo presto).")
                elif esito.upper() == 'ERR_NODATA':
                    print(f"'{comando}': nessuna risposta dal circuito EZO sul bus I2C "
                          f"(controlla cablaggio/indirizzo).")
                else:
                    print(f"'{comando}': {esito}")
            else:
                print(risposta)
            continue

        # Aspetta la risposta per al massimo TIMEOUT_S secondi COMPLESSIVI.
        # Lo sketch rieccheggia il comando ("<comando>:<valore>"), quindi si
        # accetta solo la riga che inizia con il comando inviato; ogni altra
        # riga (messaggi di stato, risposte in ritardo) viene mostrata e
        # ignorata, senza allungare l'attesa.
        # .decode('utf-8') converte i byte grezzi ricevuti in una stringa di
        # testo leggibile; .strip() toglie newline/spazi bianchi finali.
        scadenza = time.time() + TIMEOUT_S
        risposta = ''
        while time.time() < scadenza:
            arduino.timeout = max(0.1, scadenza - time.time())
            riga = arduino.readline().decode('utf-8', errors='replace').strip()
            if not riga:
                continue
            if riga.lower().startswith(comando.lower() + ':') \
                    or riga.lower() == ('ERR:' + comando).lower():
                risposta = riga
                break
            print(f"  [ignorata] {riga}")
        arduino.timeout = TIMEOUT_S

        if not risposta:
            # Scaduto TIMEOUT_S senza una risposta pertinente:
            # possibile causa: Arduino non ancora pronto, cavo USB scollegato,
            # oppure lo sketch caricato non e' quello giusto.
            print(f"Nessuna risposta dall'Arduino a '{comando}' entro {TIMEOUT_S}s (timeout)")
            continue

        if risposta.lower() == ('ERR:' + comando).lower():
            print(f"Comando '{comando}' non riconosciuto dallo sketch Arduino.")
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