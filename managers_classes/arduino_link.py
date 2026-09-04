'''
Ponte fra Raspberry e Arduino UNO (comunicazione seriale USB).

E' l'UNICO modulo del progetto che apre una porta seriale: i manager non
sanno nulla di pyserial, chiedono soltanto "leggimi il sensore X".

Qui NON c'e' alcuna logica di temporizzazione. Il tempo resta al Raspberry:
sono i manager (tank, water, plant_growth) a decidere quando e' scaduto
l'intervallo di un job e a chiamare una lettura. Questo modulo si limita a
comporre il comando, mandarlo sulla seriale e interpretare la risposta.

Protocollo, lato Arduino in fish_n_plant_reading_module_atlas.ino:

    read_pH,A0     ->  read_pH,A0:6.87
    read_EC,100    ->  read_EC,100:1250.0,625.0,0.62
    read_us,2,3    ->  read_us,2,3:12.40

I pin viaggiano DENTRO il comando, quindi cambiare cablaggio significa
modificare config.yaml e non ricompilare lo sketch.
'''

import threading
import time

import serial
import serial.tools.list_ports


# =====================================================================
# Tabella dei sensori - punto di estensione principale
# =====================================================================
# Per ogni sensore: il nome del comando Arduino (FISSO, non modificabile
# dall'utente), gli argomenti che l'utente deve compilare in configurazione
# e i valori che la risposta contiene, in ordine.
#
# 'args' e' una lista di (chiave in config.yaml, etichetta per la GUI, default).
# 'values' e' una lista di (nome del valore, unita' di misura).
#
# Aggiungere un sensore qui lo rende automaticamente disponibile sia nel
# pannello di configurazione della GUI sia alla CLI: nessuno dei due ha un
# elenco proprio di sensori.
SENSOR_SPECS = {
    'pH': {
        'command': 'read_pH',
        'label': 'sonda di pH',
        'args': [('pin', 'Pin analogico', 'A0')],
        'values': [('ph', '')],
    },
    'EC': {
        'command': 'read_EC',
        'label': 'sonda di conducibilità (EC)',
        'args': [('address', 'Indirizzo I2C', 100)],
        'values': [('ec_us_cm', 'µS/cm'), ('tds_ppm', 'ppm'),
                   ('salinity_psu', 'PSU')],
    },
    'US_water': {
        'command': 'read_us',
        'label': 'sensore ultrasonico del serbatoio',
        'args': [('trig', 'Pin TRIG', 2), ('echo', 'Pin ECHO', 3)],
        'values': [('distance_cm', 'cm')],
    },
    'US_plant': {
        'command': 'read_us',
        'label': 'sensore ultrasonico della crescita',
        'args': [('trig', 'Pin TRIG', 4), ('echo', 'Pin ECHO', 5)],
        'values': [('distance_cm', 'cm')],
    },
}

# Ordine stabile per la GUI e la CLI (i dict sono ordinati, ma qui l'ordine
# e' una scelta di presentazione e va reso esplicito).
SENSOR_KEYS = ('pH', 'EC', 'US_water', 'US_plant')

DEFAULT_BAUDRATE = 9600
DEFAULT_TIMEOUT_S = 15   # una read_pH impegna l'Arduino per ~8s
RESET_DELAY_S = 2        # aprire la USB resetta l'Arduino UNO: va aspettato


def sensor_label(sensor_key):
    '''Nome parlante del sensore, per i messaggi di errore e la GUI.'''
    spec = SENSOR_SPECS.get(sensor_key)
    return spec['label'] if spec else sensor_key


def build_command(sensor_key, sensor_cfg):
    '''
    Compone la stringa da mandare all'Arduino per un sensore.

    E' l'unico punto che sa come si scrive un comando: i manager chiedono
    per chiave ('pH', 'US_water', ...) e non compongono nulla.

    :param sensor_key: chiave in SENSOR_SPECS
    :param sensor_cfg: dict con i pin presi da config.yaml (es. {'trig': 2, 'echo': 3})
    :return: comando completo, es. 'read_us,2,3'
    '''
    spec = SENSOR_SPECS.get(sensor_key)
    if spec is None:
        raise ArduinoError(sensor_key, f"Sensore sconosciuto: '{sensor_key}'.")

    cfg = sensor_cfg or {}
    parti = [spec['command']]
    for chiave, _etichetta, default in spec['args']:
        valore = cfg.get(chiave, default)
        if valore is None or str(valore).strip() == '':
            raise ArduinoError(
                sensor_key,
                f"Manca il parametro '{chiave}' per {spec['label']}: "
                "compilalo nella schermata Configurazione."
            )
        parti.append(str(valore).strip())

    return ','.join(parti)


def list_serial_ports():
    '''
    Elenca le porte seriali USB attualmente collegate.

    Usata dal bottone "Rileva schede" del pannello di configurazione, cosi'
    l'utente sceglie la porta da un elenco invece di ricordarsela.

    :return: lista di dict {'device', 'description', 'hwid'}
    '''
    porte = []
    for p in serial.tools.list_ports.comports():
        porte.append({
            'device': p.device,
            'description': p.description or '',
            'hwid': p.hwid or '',
        })
    return sorted(porte, key=lambda d: d['device'])


# =====================================================================
# Errore di lettura
# =====================================================================
class ArduinoError(Exception):
    '''
    Lettura non riuscita: porta assente, timeout, risposta ERR o malformata.

    Il messaggio e' gia' scritto in italiano e pensato per finire tale e
    quale nella sezione "Errori di lettura" dell'interfaccia.
    '''

    def __init__(self, sensor, message):
        super().__init__(message)
        self.sensor = sensor
        self.message = message


# =====================================================================
# Una scheda Arduino = una porta seriale
# =====================================================================
class ArduinoBoard():
    '''
    Una singola scheda Arduino collegata via USB, con le sonde che le sono
    state assegnate in configurazione.

    La connessione e' PIGRA: si apre alla prima lettura e resta aperta.
    Se cade (cavo staccato), viene invalidata e il tentativo successivo
    riapre da solo, senza bisogno di riavviare il programma.
    '''

    def __init__(self, port, sensors, name=None, baudrate=DEFAULT_BAUDRATE,
                 timeout=DEFAULT_TIMEOUT_S, reset_delay=RESET_DELAY_S, logger=None):
        '''
        :param port:        porta seriale, es. '/dev/ttyACM0'
        :param sensors:     dict {chiave_sensore: {pin/argomenti}} da config.yaml
        :param name:        nome descrittivo della scheda (solo per i log)
        :param baudrate:    deve combaciare con Serial.begin() dello sketch
        :param timeout:     secondi di attesa di una risposta
        :param reset_delay: secondi da aspettare dopo l'apertura della porta
        :param logger:      logger condiviso
        '''
        self.port = port
        self.sensors = sensors or {}
        self.name = name or port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reset_delay = reset_delay
        self.logger = logger

        self._serial = None
        # I job (pH, EC, serbatoio, crescita) girano su thread distinti e
        # possono condividere la stessa scheda: il lock serializza la coppia
        # comando+risposta, altrimenti due letture contemporanee si
        # scambierebbero le risposte.
        self._lock = threading.Lock()

    def has_sensor(self, sensor_key):
        '''True se questa scheda dichiara il sensore indicato.'''
        return sensor_key in self.sensors

    def _ensure_open(self, sensor_key=None):
        '''
        Apre la porta se non e' gia' aperta.

        Aprire la seriale USB fa RESETTARE l'Arduino UNO (comportamento
        normale della scheda, dovuto al DTR): serve qualche secondo prima
        che lo sketch sia ripartito, altrimenti il primo comando arriva
        mentre l'Arduino si sta ancora riavviando e va perso. Subito dopo
        si svuota il buffer, dove intanto e' finito il messaggio di
        benvenuto stampato da setup().
        '''
        if self._serial is not None and self._serial.is_open:
            return self._serial

        try:
            self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        except (serial.SerialException, OSError) as e:
            self._serial = None
            raise ArduinoError(
                sensor_key,
                f"Scheda Arduino '{self.name}' non raggiungibile sulla porta "
                f"{self.port}: controlla che il cavo USB sia collegato ({e})."
            )

        time.sleep(self.reset_delay)
        self._serial.reset_input_buffer()

        if self.logger is not None:
            self.logger.info(f"ARDUINO: connesso a '{self.name}' su {self.port} "
                             f"a {self.baudrate} baud")
        return self._serial

    def close(self):
        '''Chiude la porta seriale (idempotente).'''
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def _invalidate(self):
        '''Butta via la connessione: il prossimo tentativo la riaprira'.'''
        self.close()

    def send_command(self, command, sensor_key=None):
        '''
        Manda un comando e restituisce la parte "valore" della risposta.

        :param command:    comando completo, es. 'read_us,2,3'
        :param sensor_key: solo per arricchire il messaggio d'errore
        :return: stringa del valore, es. '12.40' oppure '1250.0,625.0,0.62'
        :raises ArduinoError: porta assente, timeout, ERR/ERRPIN, risposta
                              malformata o riferita a un altro comando.
        '''
        with self._lock:
            conn = self._ensure_open(sensor_key)

            try:
                conn.write((command + '\n').encode('utf-8'))
                risposta = conn.readline().decode('utf-8', errors='replace').strip()
            except (serial.SerialException, OSError) as e:
                self._invalidate()
                raise ArduinoError(
                    sensor_key,
                    f"Comunicazione interrotta con la scheda '{self.name}' "
                    f"({self.port}) durante '{command}': {e}."
                )

        if not risposta:
            raise ArduinoError(
                sensor_key,
                f"Nessuna risposta dalla scheda '{self.name}' ({self.port}) al "
                f"comando '{command}' entro {self.timeout}s."
            )

        # Lo sketch risponde "<comando completo>:<valore>": lo split e'
        # sicuro perche' gli argomenti usano la virgola, non i due punti.
        parti = risposta.split(':')
        if len(parti) != 2:
            raise ArduinoError(
                sensor_key,
                f"Risposta inattesa dalla scheda '{self.name}' al comando "
                f"'{command}': {risposta!r}."
            )

        comando_ricevuto, valore = parti[0].strip(), parti[1].strip()

        # L'Arduino rieccheggia il comando: se non combacia, stiamo leggendo
        # la risposta di un'altra richiesta (buffer disallineato). Si scarta
        # tutto e si riparte pulito al giro successivo.
        if comando_ricevuto.lower() != command.lower():
            self._invalidate()
            raise ArduinoError(
                sensor_key,
                f"Risposta fuori sincrono dalla scheda '{self.name}': atteso "
                f"'{command}', ricevuto '{comando_ricevuto}'."
            )

        if valore == 'ERRPIN':
            raise ArduinoError(
                sensor_key,
                f"Pin non validi per {sensor_label(sensor_key)} (comando "
                f"'{command}'): correggili nella schermata Configurazione."
            )

        if valore == 'ERR':
            raise ArduinoError(
                sensor_key,
                f"lettura non attendibile, controlla il collegamento della "
                f"sonda alla scheda '{self.name}'."
            )

        return valore

    def read_sensor(self, sensor_key):
        '''Compone ed esegue il comando del sensore indicato.'''
        command = build_command(sensor_key, self.sensors.get(sensor_key))
        return self.send_command(command, sensor_key=sensor_key)

    def command_preview(self, sensor_key):
        '''Comando che verrebbe inviato (per l'anteprima nella GUI).'''
        try:
            return build_command(sensor_key, self.sensors.get(sensor_key))
        except ArduinoError:
            return ''


# =====================================================================
# Insieme delle schede collegate
# =====================================================================
class ArduinoHub():
    '''
    Tutte le schede Arduino dichiarate in config.yaml, indicizzate per sensore.

    Il resto del programma chiede solo `hub.read_float('US_water')`: quale
    scheda risponda, su quale porta e con quali pin, e' un dettaglio che
    vive qui e in configurazione.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        self.boards = []
        self._by_sensor = {}
        self.reload()

    def _params(self):
        '''Parametri della sezione 'arduino' con i default del modulo.'''
        a = self.configs.get('arduino', {}) or {}
        return dict(
            baudrate=a.get('baudrate', DEFAULT_BAUDRATE),
            timeout=a.get('timeout', DEFAULT_TIMEOUT_S),
            reset_delay=a.get('reset_delay', RESET_DELAY_S),
            boards=a.get('boards', []) or [],
        )

    def reload(self):
        '''
        Ricostruisce le schede dalla configurazione corrente.

        Chiamata dalla GUI dopo un salvataggio, cosi' un cambio di porta o
        di pin ha effetto senza riavviare il programma.
        '''
        self.close_all()

        p = self._params()
        boards = []
        by_sensor = {}

        for voce in p['boards']:
            if not voce.get('enabled', True):
                continue

            port = voce.get('port')
            if not port:
                if self.logger is not None:
                    self.logger.warning("ARDUINO: scheda senza porta in config.yaml, ignorata.")
                continue

            board = ArduinoBoard(
                port=port,
                sensors=voce.get('sensors', {}) or {},
                name=voce.get('name'),
                baudrate=p['baudrate'],
                timeout=p['timeout'],
                reset_delay=p['reset_delay'],
                logger=self.logger,
            )
            boards.append(board)

            for sensor_key in board.sensors:
                if sensor_key not in SENSOR_SPECS:
                    if self.logger is not None:
                        self.logger.warning(
                            f"ARDUINO: sensore sconosciuto '{sensor_key}' sulla scheda "
                            f"'{board.name}', ignorato.")
                    continue
                if sensor_key in by_sensor:
                    # Due schede che dichiarano la stessa sonda: e' quasi
                    # certamente un errore di configurazione, ma non deve
                    # bloccare il programma. Vince la prima.
                    if self.logger is not None:
                        self.logger.warning(
                            f"ARDUINO: '{sensor_key}' dichiarato sia su "
                            f"'{by_sensor[sensor_key].name}' sia su '{board.name}': "
                            f"uso la prima.")
                    continue
                by_sensor[sensor_key] = board

        self.boards = boards
        self._by_sensor = by_sensor

        if self.logger is not None:
            self.logger.info(f"ARDUINO: {len(boards)} scheda/e configurata/e, "
                             f"sensori disponibili: {sorted(by_sensor) or 'nessuno'}")

    def is_available(self, sensor_key):
        '''True se il sensore e' assegnato a una scheda abilitata.'''
        return sensor_key in self._by_sensor

    def board_for(self, sensor_key):
        '''Scheda a cui e' assegnato il sensore (None se non configurato).'''
        return self._by_sensor.get(sensor_key)

    def _board_or_raise(self, sensor_key):
        board = self._by_sensor.get(sensor_key)
        if board is None:
            raise ArduinoError(
                sensor_key,
                f"Nessuna scheda Arduino configurata per {sensor_label(sensor_key)}: "
                "aggiungila nella card 'Schede Arduino' della schermata Configurazione."
            )
        return board

    def read_raw(self, sensor_key):
        '''Valore grezzo (stringa) restituito dall'Arduino.'''
        return self._board_or_raise(sensor_key).read_sensor(sensor_key)

    def read_values(self, sensor_key):
        '''
        Tutti i valori della risposta, convertiti in float.

        Serve alle sonde che restituiscono piu' grandezze in una sola
        lettura, come l'EZO-EC (EC, TDS, salinita').

        :return: lista di float
        :raises ArduinoError: anche se la risposta non e' numerica.
        '''
        grezzo = self.read_raw(sensor_key)
        try:
            return [float(v) for v in grezzo.split(',')]
        except ValueError:
            raise ArduinoError(
                sensor_key,
                f"Valore non numerico da {sensor_label(sensor_key)}: {grezzo!r}."
            )

    def read_float(self, sensor_key):
        '''Primo (e di norma unico) valore della risposta, come float.'''
        valori = self.read_values(sensor_key)
        if not valori:
            raise ArduinoError(
                sensor_key,
                f"Risposta vuota da {sensor_label(sensor_key)}."
            )
        return valori[0]

    def read_named(self, sensor_key):
        '''
        Risposta come dict {nome_valore: float}, secondo SENSOR_SPECS.

        Es. per l'EC: {'ec_us_cm': 1250.0, 'tds_ppm': 625.0, 'salinity_psu': 0.62}
        '''
        valori = self.read_values(sensor_key)
        nomi = [nome for nome, _unita in SENSOR_SPECS[sensor_key]['values']]

        if len(valori) < len(nomi):
            raise ArduinoError(
                sensor_key,
                f"Risposta incompleta da {sensor_label(sensor_key)}: attesi "
                f"{len(nomi)} valori, ricevuti {len(valori)}."
            )
        return dict(zip(nomi, valori))

    def close_all(self):
        '''Chiude tutte le porte seriali aperte.'''
        for board in getattr(self, 'boards', []):
            board.close()
