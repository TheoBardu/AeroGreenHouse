import glob
import os
import threading
from datetime import datetime


# Nome dei file scritti da _acquisition_loop
IMG_FILE_GLOB = "*.jpg"

# Copia sempre sovrascritta con l'ultimo scatto (attesa da uploader.py):
# va esclusa dalla ricerca dell'ultima foto, altrimenti sarebbe sempre lei.
LAST_IMAGE_NAME = "image.jpg"

# Default usati se config.yaml non ha la sezione 'camera'
DEFAULT_SAVING_DIR = "/home/fishnplants/Desktop/data/IMG/"
DEFAULT_SEPARATION_HOURS = 2


# =====================================================================
# Rilettura dell'ultimo scatto salvato
# =====================================================================

def load_last_photo(save_dir: str) -> dict:
    '''
    Trova l'ultima foto salvata su disco.

    Serve alla scheda Camera: senza, all'avvio del pannello l'anteprima
    resterebbe vuota fino al primo scatto (che con separation_hours=2 puo'
    voler dire due ore di riquadro grigio).

    Il nome file e' il timestamp dello scatto (%Y-%m-%d_%H-%M-%S.jpg), quindi
    ordina cronologicamente anche come stringa; la data si rilegge dal nome e
    non dal mtime, che una copia del file falserebbe.

    :param save_dir: directory delle immagini
    :return: dict con path e timestamp (stringa nel formato standard del
             progetto, %Y/%m/%d %H:%M:%S), oppure None se non c'e' nessuna foto.
    '''
    try:
        files = sorted(glob.glob(os.path.join(save_dir, IMG_FILE_GLOB)))
    except OSError:
        return None

    for path in reversed(files):
        if os.path.basename(path) == LAST_IMAGE_NAME:
            continue
        nome = os.path.splitext(os.path.basename(path))[0]
        try:
            scatto = datetime.strptime(nome, "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            continue  # file non prodotto da noi (nome non interpretabile)
        return {'path': path, 'timestamp': scatto.strftime("%Y/%m/%d %H:%M:%S")}

    return None


# =====================================================================
# Categoria CAMERA (acquisizione periodica e anteprima dal vivo)
# =====================================================================
class CameraManager():
    '''
    Class per la gestione della camera del Raspberry Pi (Picamera2):
    acquisizione periodica di foto e anteprima dal vivo.

    I due usi sono mutuamente esclusivi: la Picamera2 e' una risorsa singola e
    aprirla due volte fa fallire l'anteprima o, peggio, lo scatto schedulato.
    Per questo start_preview() si rifiuta di partire se l'acquisizione e'
    attiva; il chiamante (la GUI) traduce il False in un pop-up di avviso.
    '''

    def __init__(self, configs, logger):
        '''
        :param configs: dizionario di configurazione (config.yaml)
        :param logger:  logger condiviso
        '''
        self.configs = configs
        self.logger = logger

        # Ultimo scatto (path + data) per la scheda Camera. Come last_result di
        # AmbientManager si puo' rileggere da disco: e' solo informativo.
        self.last_photo = load_last_photo(self.saving_dir())

        # Acquisizione periodica
        self._thread = None
        self._stop_event = threading.Event()

        # Anteprima dal vivo: l'oggetto Picamera2 resta aperto finche' e' attiva
        self._preview_cam = None

        # Protegge l'accesso alla camera fra thread di acquisizione e anteprima
        self._lock = threading.Lock()

    ###########################################
    # Configurazione
    ###########################################
    def saving_dir(self):
        '''Directory in cui salvare le foto (sezione camera del config).'''
        return self.configs.get('camera', {}).get('saving_dir', DEFAULT_SAVING_DIR)

    def separation_hours(self):
        '''Ore fra uno scatto e il successivo (sezione camera del config).'''
        return self.configs.get('camera', {}).get('separation_hours',
                                                  DEFAULT_SEPARATION_HOURS)

    ###########################################
    # Scatto singolo
    ###########################################
    def take_picture(self):
        '''
        Scatta una foto e la salva due volte: con il timestamp nel nome (storico)
        e come image.jpg (ultima foto, quella che uploader.py si aspetta).

        :return: dict con path e timestamp dello scatto
        '''
        from picamera2 import Picamera2
        from time import sleep

        save_dir = self.saving_dir()
        os.makedirs(save_dir, exist_ok=True)

        with self._lock:
            cam = Picamera2()
            try:
                cam_config = cam.create_still_configuration(
                    main={"size": cam.sensor_resolution}
                )
                cam.configure(cam_config)
                cam.start()

                now = datetime.now()
                path = os.path.join(save_dir, now.strftime("%Y-%m-%d_%H-%M-%S") + ".jpg")
                cam.capture_file(path)
                sleep(1)
                cam.capture_file(os.path.join(save_dir, LAST_IMAGE_NAME))
            finally:
                cam.stop()
                cam.close()

        self.last_photo = {'path': path, 'timestamp': now.strftime("%Y/%m/%d %H:%M:%S")}
        self.logger.info(f"CAMERA: foto salvata in {path}")
        return self.last_photo

    ###########################################
    # Acquisizione periodica
    ###########################################
    def is_acquiring(self):
        '''True se il thread di acquisizione periodica e' attivo.'''
        return self._thread is not None and self._thread.is_alive()

    # Alias per uniformita' con gli altri manager (usato da get_process_states)
    is_running = is_acquiring

    def start_acquisition(self, on_capture=None):
        '''
        Avvia l'acquisizione periodica delle foto in un thread.

        :param on_capture: callback opzionale on_capture(photo) con il dict
                           dell'ultimo scatto, usata dalla GUI per aggiornare
                           l'anteprima.
        :return: False se l'acquisizione e' gia' in corso o se l'anteprima e'
                 attiva (la camera sarebbe occupata), True altrimenti.
        '''
        if self.is_acquiring() or self.is_previewing():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._acquisition_loop,
                                        args=(on_capture,), daemon=True)
        self._thread.start()
        return True

    def stop_acquisition(self):
        '''Arresta l'acquisizione periodica. False se non era in corso.'''
        if not self.is_acquiring():
            return False
        self._stop_event.set()
        return True

    def _acquisition_loop(self, on_capture):
        '''
        Loop di acquisizione: uno scatto ogni separation_hours ore.

        L'attesa usa _stop_event.wait invece di sleep, altrimenti "Disattiva
        acquisizione" resterebbe senza effetto fino allo scatto successivo (con
        separation_hours=2, fino a due ore).
        '''
        interval = self.separation_hours() * 3600

        self.logger.info(f"Inizio acquisizione CAMERA. Uno scatto ogni "
                         f"{self.separation_hours()} ore")

        while not self._stop_event.is_set():
            try:
                photo = self.take_picture()
                if on_capture is not None:
                    on_capture(photo)
            except Exception as e:
                self.logger.error(f"Errore scatto CAMERA: {str(e)}")

            self._stop_event.wait(interval)

        self.logger.info("Acquisizione CAMERA interrotta")

    ###########################################
    # Anteprima dal vivo
    ###########################################
    def is_previewing(self):
        '''True se l'anteprima dal vivo e' aperta.'''
        return self._preview_cam is not None

    def start_preview(self):
        '''
        Apre l'anteprima dal vivo (finestra QTGL).

        :return: False se l'anteprima e' gia' aperta o se l'acquisizione
                 periodica e' attiva (Picamera2 non e' condivisibile),
                 True altrimenti.
        '''
        if self.is_previewing() or self.is_acquiring():
            return False

        from picamera2 import Picamera2, Preview

        with self._lock:
            cam = Picamera2()
            try:
                cam.start_preview(Preview.QTGL)
                cam.start()
            except Exception:
                cam.close()
                raise
            self._preview_cam = cam

        self.logger.info("CAMERA: anteprima attivata")
        return True

    def stop_preview(self):
        '''Chiude l'anteprima dal vivo. False se non era aperta.'''
        if not self.is_previewing():
            return False

        with self._lock:
            cam = self._preview_cam
            self._preview_cam = None
            try:
                cam.stop()
                cam.stop_preview()
            finally:
                cam.close()

        self.logger.info("CAMERA: anteprima disattivata")
        return True

    def toggle_preview(self):
        '''
        Apre l'anteprima se chiusa, la chiude se aperta.

        :return: True se l'operazione e' riuscita, False se l'anteprima non ha
                 potuto partire (acquisizione in corso).
        '''
        if self.is_previewing():
            return self.stop_preview()
        return self.start_preview()
