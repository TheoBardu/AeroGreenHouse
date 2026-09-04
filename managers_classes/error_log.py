'''
Registro degli errori di lettura delle sonde.

Serve a due consumatori diversi, ed e' per questo che non e' un semplice
handler di logging in memoria:
  - la sezione "Errori di lettura" della schermata Log e Output, che vuole
    gli ultimi errori con timestamp e una frase leggibile;
  - l'uploader, che deve poter caricare sul sito gli errori del giorno
    (quindi devono sopravvivere al riavvio del programma).

Ogni errore viene comunque anche passato al logger condiviso, cosi' finisce
nel file di log e nell'output a terminale come tutto il resto.
'''

import os
import threading
from collections import deque
from datetime import datetime, date


# Formato dei timestamp, lo stesso usato da tutti gli altri manager.
TS_FORMAT = "%Y/%m/%d %H:%M:%S"

# Nome dei file giornalieri: ordina cronologicamente anche come stringa.
NAME_FORMAT = "ERRORS_%Y_%m_%d.txt"

DEFAULT_SAVE_DIR = "/home/fishnplants/Desktop/data/ERRORS/"
DEFAULT_HISTORY_LEN = 200

HEADER = "datetime\tsource\tmessage\n"


def error_filename(giorno=None):
    '''Nome del file degli errori per un giorno (oggi se non indicato).'''
    if giorno is None:
        giorno = date.today()
    return giorno.strftime(NAME_FORMAT)


def load_errors(save_dir, giorno=None, logger=None):
    '''
    Rilegge da file gli errori registrati in un giorno.

    :param save_dir: directory dei file ERRORS_*.txt
    :param giorno:   date da rileggere (oggi se None)
    :param logger:   logger opzionale per segnalare le righe malformate
    :return: lista di dict {'timestamp', 'source', 'message'} in ordine
             cronologico crescente (lista vuota se il file non esiste)
    '''
    file_path = os.path.join(save_dir, error_filename(giorno))
    if not os.path.exists(file_path):
        return []

    errori = []
    try:
        with open(file_path, "r") as f:
            righe = f.readlines()
    except OSError as e:
        if logger is not None:
            logger.error(f"ERRORI: impossibile rileggere {file_path}: {e}")
        return []

    for line in righe:
        line = line.rstrip("\n")
        # Salta righe vuote e header
        if not line.strip() or line.startswith("datetime"):
            continue
        campi = line.split("\t")
        if len(campi) < 3:
            if logger is not None:
                logger.warning(f"ERRORI: riga ignorata in {file_path}: {line!r}")
            continue
        errori.append({
            'timestamp': campi[0].strip(),
            'source': campi[1].strip(),
            # Il messaggio puo' contenere altri tab: si ricompone per intero.
            'message': "\t".join(campi[2:]).strip(),
        })

    return errori


# =====================================================================
# Registratore degli errori
# =====================================================================
class ErrorRecorder():
    '''
    Raccoglie gli errori di lettura delle sonde.

    Tiene in memoria gli ultimi 'history_len' errori (per la GUI) e li
    appende al file giornaliero (per l'uploader e per la storia).
    I parametri sono letti dalla sezione 'error_log' di config.yaml.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        p = self._params()
        # Le letture arrivano da thread diversi (un job per sonda): sia il
        # deque sia la scrittura su file vanno protetti.
        self._lock = threading.Lock()
        self._history = deque(maxlen=p['history_len'])

        # All'avvio si ripopola con gli errori gia' registrati oggi, cosi'
        # la schermata Log non riparte vuota dopo un riavvio.
        for errore in load_errors(p['save_dir'], logger=self.logger):
            self._history.append(errore)

    def _params(self):
        '''Legge la sezione 'error_log' di config.yaml con i default del modulo.'''
        e = self.configs.get('error_log', {}) or {}
        return dict(
            save_dir=e.get('saving_dir', DEFAULT_SAVE_DIR),
            history_len=e.get('history_len', DEFAULT_HISTORY_LEN),
        )

    def record(self, source, message):
        '''
        Registra un errore: memoria + file + logger.

        :param source:  sorgente, es. 'pH', 'EC', 'US_water', 'US_plant'
        :param message: frase leggibile che spiega cosa non ha funzionato
        :return: il dict dell'errore appena registrato
        '''
        errore = {
            'timestamp': datetime.now().strftime(TS_FORMAT),
            'source': source or '-',
            # I tab spezzerebbero il formato del file: si normalizzano.
            'message': str(message).replace("\t", " ").replace("\n", " ").strip(),
        }

        with self._lock:
            self._history.append(errore)
            self._append_to_file(errore)

        self.logger.error(f"{errore['source']}: {errore['message']}")
        return errore

    def _append_to_file(self, errore):
        '''Appende una riga al file giornaliero (va chiamata sotto lock).'''
        p = self._params()
        try:
            os.makedirs(p['save_dir'], exist_ok=True)
            file_path = os.path.join(p['save_dir'], error_filename())

            # Header scritto solo se il file non esiste ancora
            write_header = not os.path.exists(file_path)
            with open(file_path, "a") as f:
                if write_header:
                    f.write(HEADER)
                f.write(f"{errore['timestamp']}\t{errore['source']}\t{errore['message']}\n")
        except OSError as e:
            # Un errore nello scrivere gli errori non deve far cadere la
            # lettura in corso: resta comunque in memoria e nel log.
            self.logger.error(f"ERRORI: impossibile salvare su file: {e}")

    def recent(self, n=None):
        '''
        Ultimi errori registrati, dal piu' vecchio al piu' recente.

        :param n: quanti errori restituire (tutti quelli in memoria se None)
        '''
        with self._lock:
            elenco = list(self._history)
        return elenco if n is None else elenco[-n:]

    def clear(self):
        '''Svuota la lista in memoria (i file su disco restano).'''
        with self._lock:
            self._history.clear()

    def load_for_date(self, giorno):
        '''Rilegge da file gli errori di un giorno preciso (per l'uploader).'''
        return load_errors(self._params()['save_dir'], giorno, logger=self.logger)

    def load_today(self):
        '''Rilegge da file gli errori di oggi.'''
        return self.load_for_date(date.today())
