#! /usr/bin/python3
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
import yaml
import os
import sys
from datetime import datetime
import logging
from queue import Queue

from helper_aeroGreenHouse import aeroHelper
from managers_classes import arduino_link
from sensors.spectrometer import mcari2_as7265x as spectro


class GUILoggingHandler(logging.Handler):
    """Custom logging handler that sends log records to a GUI text widget queue"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put((msg, record.levelname))
        except Exception:
            self.handleError(record)


class Card(tk.Frame):
    """
    Contenitore piatto: superficie bianca, bordo sottile, titolo in
    maiuscoletto tenue. Sostituisce ttk.LabelFrame.

    Tk non sa disegnare angoli arrotondati (ne' ombre) su un Frame: farlo
    richiederebbe un Canvas ridisegnato a ogni <Configure>, che su Raspberry Pi
    si sente durante il ridimensionamento. La card resta quindi un rettangolo
    con bordo da 1px, ottenuto con highlightthickness (non con relief, che su
    'clam' disegna un incavo 3D).

    I widget si aggiungono a questo oggetto come si facevano dentro un
    LabelFrame; pack/grid vengono invece inoltrati al guscio esterno, che e'
    quello che porta bordo e padding. Cosi' i chiamanti restano invariati.
    """

    def __init__(self, parent, titolo=None, bg='#ffffff', border='#e6eae8',
                 title_fg='#7c8a83', title_font=('DejaVu Sans', 9, 'bold'),
                 padding=14, icona=None, icona_bg=None, icona_fg=None):
        self._shell = tk.Frame(parent, bg=bg, highlightthickness=1,
                               highlightbackground=border, highlightcolor=border,
                               bd=0)

        if titolo:
            head = tk.Frame(self._shell, bg=bg)
            head.pack(fill=tk.X, padx=padding, pady=(padding, 0))
            if icona:
                tk.Label(head, text=icona, bg=icona_bg or bg, fg=icona_fg or title_fg,
                         font=(title_font[0], 11), width=2,
                         padx=2, pady=2).pack(side=tk.LEFT, padx=(0, 8))
            # Maiuscoletto solo sui titoli brevi: in maiuscolo una riga lunga
            # come "Serbatoio (Tank) - sensore ultrasonico HC-SR04" urlerebbe.
            etichetta = titolo.upper() if len(titolo) <= 24 else titolo
            tk.Label(head, text=etichetta, bg=bg, fg=title_fg,
                     font=title_font).pack(side=tk.LEFT)
            self.head = head
        else:
            self.head = None

        super().__init__(self._shell, bg=bg)
        # NB: tk.Frame.pack esplicito — self.pack e' ridefinito piu' sotto per
        # posizionare il guscio, non il corpo.
        tk.Frame.pack(self, fill=tk.BOTH, expand=True,
                      padx=padding, pady=(8 if titolo else padding, padding))

    # -- geometria: inoltrata al guscio -------------------------------------
    def pack(self, **kw):
        self._shell.pack(**kw)
        return self

    def grid(self, **kw):
        self._shell.grid(**kw)
        return self

    def pack_forget(self):
        self._shell.pack_forget()

    def grid_forget(self):
        self._shell.grid_forget()


class AeroGreenHouseGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AeroGreenHouse Control Panel")
        self.root.geometry("1040x720")
        self.root.minsize(900, 600)

        self.config_file = 'config.yaml'
        self.config = self.load_config()
        self.active_jobs = {}  # Per tracciare i job attivi/inattivi (solo display)

        # Logging queue for GUI updates
        self.log_queue = Queue()

        # Tracciamento righe della tab "Processi Attivi"
        self.status_indicators = {}
        self._status_keys = None

        # Modulo helper: tutta la logica dei processi vive qui
        self.ah = aeroHelper()

        # Costruzione interfaccia (richiede self.ah per le tab di stato/controllo)
        self.create_widgets()
        self.refresh_jobs_list()

        # Setup GUI logging handler
        self.setup_gui_logging_handler()

        # Avvio dei loop periodici della GUI
        self.process_log_queue()
        self.refresh_status_tab()
        self.refresh_riepilogo_tab()
        self._update_clock()

    # ------------------------------------------------------------------
    # Config / logging
    # ------------------------------------------------------------------
    def load_config(self):
        """Carica la configurazione dal file YAML"""
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nel caricamento del config: {e}")
            return {}

    def setup_gui_logging_handler(self):
        """Setup custom logging handler to display logs in GUI"""
        gui_handler = GUILoggingHandler(self.log_queue)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        gui_handler.setFormatter(formatter)

        # Add handler to the aeroHelper logger
        self.ah.logger.addHandler(gui_handler)

    def process_log_queue(self):
        """Process log messages from queue and display in GUI text widget"""
        try:
            while True:
                msg, level = self.log_queue.get_nowait()
                # Determine tag based on log level
                if level in ['ERROR', 'CRITICAL']:
                    tag = 'error'
                elif level == 'WARNING':
                    tag = 'warning'
                elif level == 'DEBUG':
                    tag = 'debug'
                else:
                    tag = 'info'

                # Add message to output text widget
                self.output_text.config(state=tk.NORMAL)
                self.output_text.insert(tk.END, msg + '\n', tag)
                self.output_text.see(tk.END)
                self.output_text.config(state=tk.DISABLED)
        except:
            pass

        # La sezione Errori si aggiorna da sola: chi la guarda si aspetta di
        # vedere comparire un errore appena la lettura fallisce, senza dover
        # premere "Aggiorna". Il refresh e' piu' lento del log (2s) perche'
        # ridisegna tutto il Text.
        self._errors_refresh_countdown = getattr(self, '_errors_refresh_countdown', 0) - 1
        if self._errors_refresh_countdown <= 0:
            self._errors_refresh_countdown = 20  # 20 * 100ms = 2s
            try:
                self.refresh_errors()
            except AttributeError:
                pass  # la scheda Log non e' ancora stata costruita

        # Schedule next check
        self.root.after(100, self.process_log_queue)

    def save_config(self):
        """Salva la configurazione nel file YAML"""
        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            messagebox.showinfo("Successo", "Configurazione salvata!")
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nel salvataggio: {e}")

    # ------------------------------------------------------------------
    # Stile / struttura interfaccia
    # ------------------------------------------------------------------
    def _pick_font(self, candidati, fallback):
        """
        Primo font disponibile tra `candidati`.

        Su Raspberry Pi OS c'e' DejaVu; altrove (macchina di sviluppo) puo' non
        esserci, e Tk sostituirebbe in silenzio con una famiglia qualsiasi.
        """
        disponibili = set(tkfont.families())
        for nome in candidati:
            if nome in disponibili:
                return nome
        return fallback

    def setup_style(self):
        """Definisce una palette coerente e uno stile leggero (adatto a Raspberry Pi)."""
        # Palette del mockup (Presentazione/Mok-up/AeroGreenHouse UI.html).
        # I nomi COL_* restano quelli di prima: sono usati in tutto il file.
        self.COL_BG = "#f5f8f6"       # sfondo applicazione
        self.COL_CARD = "#ffffff"     # superficie delle card e della sidebar
        self.COL_BORDER = "#e6eae8"   # bordo delle card
        self.COL_DIV = "#f0f3f1"      # separatore fra righe di una lista
        self.COL_HEADER = "#1f7a45"   # verde scuro (logo, accenti forti)
        self.COL_PRIMARY = "#1f7a45"
        self.COL_ACCENT = "#2e9e5b"
        self.COL_SOFT = "#eaf5ee"     # verde tenue (chip, voce di menu attiva)
        self.COL_HOVER = "#eef4f0"
        self.COL_OK = "#1f7a45"       # spia verde
        self.COL_BAD = "#c62828"      # spia rossa
        self.COL_WARN = "#c4650a"     # spia arancione
        self.COL_WARN_BG = "#fdf0e0"
        self.COL_BLUE = "#1c7fa3"     # acqua / umidita'
        self.COL_BLUE_BG = "#e6f4fa"
        self.COL_TEXT = "#16211c"     # testo primario
        self.COL_MUTED = "#6d7b74"    # testo secondario
        self.COL_FAINT = "#7c8a83"    # etichette in maiuscoletto

        # Il mockup usa Instrument Sans + IBM Plex Mono: non sono installati sul
        # Pi, DejaVu ha proporzioni vicine ed e' sempre presente.
        self.FONT_UI = self._pick_font(
            ('Instrument Sans', 'DejaVu Sans', 'Helvetica Neue'), 'Arial')
        self.FONT_MONO = self._pick_font(
            ('IBM Plex Mono', 'DejaVu Sans Mono', 'Menlo'), 'Courier')

        # Colore dello stato della pianta. Le chiavi sono quelle di
        # classifica_mcari2: le soglie numeriche restano nel modulo del sensore.
        self.MCARI2_COLORS = {
            spectro.STATO_STRESS: self.COL_BAD,
            spectro.STATO_LIMITE: self.COL_WARN,
            spectro.STATO_SANA: self.COL_OK,
            spectro.STATO_MOLTO_SANA: self.COL_HEADER,
        }

        # Sfondo tenue della pill di stato, abbinato a MCARI2_COLORS
        self.MCARI2_CHIP_BG = {
            spectro.STATO_STRESS: "#fdecec",
            spectro.STATO_LIMITE: self.COL_WARN_BG,
            spectro.STATO_SANA: self.COL_SOFT,
            spectro.STATO_MOLTO_SANA: self.COL_SOFT,
        }

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        # I widget ttk vivono quasi sempre dentro una Card, quindi lo sfondo di
        # default e' quello della card (bianco). Le poche superfici grigie
        # (l'area scrollabile, le fasce fra le card) sono tk.Frame con bg
        # esplicito: vedi _make_scrollable e _screen_body.
        style.configure('.', background=self.COL_CARD, foreground=self.COL_TEXT,
                        font=(self.FONT_UI, 10))
        style.configure('TFrame', background=self.COL_CARD)
        style.configure('TLabel', background=self.COL_CARD)
        style.configure('Muted.TLabel', background=self.COL_CARD, foreground=self.COL_MUTED)
        style.configure('Caption.TLabel', background=self.COL_CARD,
                        foreground=self.COL_FAINT, font=(self.FONT_UI, 9))
        style.configure('Metric.TLabel', background=self.COL_CARD,
                        font=(self.FONT_MONO, 30))

        # Bottoni: pieni per le azioni primarie, contorno tenue per le altre.
        style.configure('TButton', padding=(14, 7), relief='flat', borderwidth=1,
                        background=self.COL_CARD, foreground=self.COL_TEXT,
                        bordercolor=self.COL_BORDER, font=(self.FONT_UI, 10))
        style.map('TButton',
                  background=[('active', self.COL_HOVER), ('pressed', self.COL_HOVER)],
                  bordercolor=[('active', self.COL_ACCENT)])
        style.configure('Accent.TButton', background=self.COL_PRIMARY,
                        foreground='white', bordercolor=self.COL_PRIMARY,
                        font=(self.FONT_UI, 10, 'bold'))
        style.map('Accent.TButton',
                  background=[('active', self.COL_ACCENT), ('pressed', self.COL_ACCENT)],
                  foreground=[('active', 'white')])
        style.configure('Stop.TButton', background=self.COL_BAD,
                        foreground='white', bordercolor=self.COL_BAD,
                        font=(self.FONT_UI, 10, 'bold'))
        style.map('Stop.TButton',
                  background=[('active', '#a01818'), ('pressed', '#a01818')],
                  foreground=[('active', 'white')])

        # Campi: bordo sottile, nessun incavo 3D
        for stile in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(stile, fieldbackground='white', background='white',
                            foreground=self.COL_TEXT, bordercolor=self.COL_BORDER,
                            lightcolor=self.COL_BORDER, darkcolor=self.COL_BORDER,
                            relief='flat', padding=4)
            style.map(stile, bordercolor=[('focus', self.COL_ACCENT)])

        style.configure('Treeview', background='white', fieldbackground='white',
                        foreground=self.COL_TEXT, rowheight=28, borderwidth=0,
                        font=(self.FONT_UI, 10))
        style.configure('Treeview.Heading', background=self.COL_CARD,
                        foreground=self.COL_FAINT, relief='flat', borderwidth=0,
                        padding=(6, 8), font=(self.FONT_UI, 9, 'bold'))
        style.map('Treeview.Heading', background=[('active', self.COL_HOVER)])
        style.map('Treeview', background=[('selected', self.COL_SOFT)],
                  foreground=[('selected', self.COL_PRIMARY)])

        style.configure('TProgressbar', background=self.COL_ACCENT,
                        troughcolor=self.COL_DIV, bordercolor=self.COL_DIV,
                        lightcolor=self.COL_ACCENT, darkcolor=self.COL_ACCENT,
                        thickness=8, borderwidth=0)
        style.configure('Vertical.TScrollbar', background=self.COL_BORDER,
                        troughcolor=self.COL_BG, bordercolor=self.COL_BG,
                        arrowcolor=self.COL_FAINT, relief='flat')

        self.root.configure(bg=self.COL_BG)

    # ------------------------------------------------------------------
    # Mattoncini dell'interfaccia
    # ------------------------------------------------------------------
    def _card(self, parent, titolo=None, icona=None, icona_bg=None, icona_fg=None,
              padding=14):
        """Card bianca con bordo sottile. Sostituisce ttk.LabelFrame."""
        return Card(parent, titolo=titolo, bg=self.COL_CARD, border=self.COL_BORDER,
                    title_fg=self.COL_FAINT, title_font=(self.FONT_UI, 9, 'bold'),
                    padding=padding, icona=icona, icona_bg=icona_bg, icona_fg=icona_fg)

    def _chip(self, parent, testo, fg, bg):
        """
        Pill di stato.

        Tk non arrotonda un Label: la pill e' un rettangolo con padding
        generoso, che a queste dimensioni legge comunque come badge.
        """
        return tk.Label(parent, text=testo, bg=bg, fg=fg, font=(self.FONT_UI, 10, 'bold'),
                        padx=12, pady=5)

    # Schermate: (chiave, icona, voce di menu, titolo, sottotitolo, costruttore).
    # Sostituisce la lista di notebook.add(): l'ordine e i contenuti sono gli
    # stessi delle vecchie schede, cambia solo il modo di raggiungerle.
    SCREENS = (
        ('riepilogo', '\u25a6', 'Riepilogo', 'Riepilogo',
         'Ultimo valore di ogni sensore e processi in esecuzione.',
         'create_riepilogo_tab'),
        ('config', '\u2699', 'Configurazione', 'Configurazione',
         'Parametri di sensori, job e sistema (config.yaml).',
         'create_config_tab'),
        ('status', '\u25c9', 'Processi', 'Processi attivi',
         'Stato di job, letture periodiche e acquisizioni.',
         'create_status_tab'),
        ('jobs', '\u26a1', 'Job', 'Gestione job',
         'Pompe e attuatori pilotati dai pin GPIO.',
         'create_jobs_tab'),
        ('ambient', '\U0001f321', 'Ambiente', 'Ambiente',
         'Temperatura, umidita\u0300 e VPD dal DHT22, con la sintesi giornaliera.',
         'create_ambient_tab'),
        ('clima', '\u2744', 'Clima', 'Climatizzatore',
         'Controllo automatico del condizionatore via infrarossi.',
         'create_climatizzatore_tab'),
        ('tank', '\U0001f4a7', 'H2O', 'H2O',
         'Livello del serbatoio, pH e conducibilita\u0300 elettrica dell\'acqua.',
         'create_tank_tab'),
        ('spectro', '\u25d0', 'Spettro', 'Spettrometro',
         'Indice MCARI2 e stato di salute della coltura.',
         'create_spectro_tab'),
        ('growth', '\U0001f331', 'Crescita', 'Crescita',
         'Altezza della pianta e andamento nel tempo.',
         'create_growth_tab'),
        ('camera', '\U0001f4f7', 'Camera', 'Camera',
         'Acquisizione periodica delle foto e anteprima dal vivo.',
         'create_camera_tab'),
        ('log', '\u2263', 'Log', 'Log e output',
         'Messaggi del sistema e file di log.',
         'create_output_tab'),
    )

    def create_widgets(self):
        """Crea l'interfaccia grafica (sola UI)."""
        self.setup_style()

        self._nav_buttons = {}
        self._screens = {}
        self._current_screen = None

        self._build_sidebar()

        # Colonna di destra: intestazione + area delle schermate
        main = tk.Frame(self.root, bg=self.COL_BG)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_header(main)

        content = tk.Frame(main, bg=self.COL_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        # Come il Notebook di prima, tutte le schermate nascono all'avvio e
        # restano vive: cambiare pagina e' solo un tkraise, senza ricostruzioni.
        for key, _icona, _voce, _titolo, _sub, builder in self.SCREENS:
            frame = tk.Frame(content, bg=self.COL_BG)
            frame.grid(row=0, column=0, sticky=tk.NSEW)
            self._screens[key] = frame
            getattr(self, builder)(frame)

        self._show_screen(self.SCREENS[0][0])

    def _build_sidebar(self):
        """Barra laterale a icone: sostituisce la fila di schede del Notebook."""
        bar = tk.Frame(self.root, bg=self.COL_CARD, width=84)
        bar.pack(side=tk.LEFT, fill=tk.Y)
        bar.pack_propagate(False)
        # Bordo destro: una riga di 1px, piu' economica di un highlight sul frame
        tk.Frame(self.root, bg=self.COL_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(bar, text='\U0001f331', bg=self.COL_PRIMARY, fg='white',
                 font=(self.FONT_UI, 16), width=2, height=1).pack(pady=(18, 16))

        for key, icona, voce, _titolo, _sub, _builder in self.SCREENS:
            b = tk.Label(bar, text=f"{icona}\n{voce}", bg=self.COL_CARD,
                         fg=self.COL_MUTED, font=(self.FONT_UI, 8),
                         width=9, pady=6, cursor='hand2')
            b.pack(pady=1)
            b.bind('<Button-1>', lambda e, k=key: self._show_screen(k))
            b.bind('<Enter>', lambda e, k=key: self._nav_hover(k, True))
            b.bind('<Leave>', lambda e, k=key: self._nav_hover(k, False))
            self._nav_buttons[key] = b

        # Spia di sistema in fondo, come il pallino del mockup
        tk.Frame(bar, bg=self.COL_CARD).pack(fill=tk.BOTH, expand=True)
        self.nav_pulse = tk.Label(bar, text='\u25cf', bg=self.COL_CARD,
                                  fg=self.COL_ACCENT, font=(self.FONT_UI, 12))
        self.nav_pulse.pack(pady=(0, 16))

    def _nav_hover(self, key, dentro):
        """Evidenzia la voce di menu sotto il puntatore (non quella attiva)."""
        if key == self._current_screen:
            return
        self._nav_buttons[key].config(bg=self.COL_HOVER if dentro else self.COL_CARD)

    def _build_header(self, parent):
        """Intestazione: briciole di pane, titolo della schermata, orologio."""
        head = tk.Frame(parent, bg=self.COL_BG)
        head.pack(fill=tk.X, padx=20, pady=(18, 14))

        sinistra = tk.Frame(head, bg=self.COL_BG)
        sinistra.pack(side=tk.LEFT, anchor=tk.W)

        tk.Label(sinistra, text="FISH & PLANTS   /   AEROGREENHOUSE", bg=self.COL_BG,
                 fg=self.COL_FAINT, font=(self.FONT_UI, 8, 'bold')).pack(anchor=tk.W)
        self.header_title = tk.Label(sinistra, text="", bg=self.COL_BG,
                                     fg=self.COL_TEXT, font=(self.FONT_UI, 22))
        self.header_title.pack(anchor=tk.W, pady=(4, 0))
        self.header_sub = tk.Label(sinistra, text="", bg=self.COL_BG,
                                   fg=self.COL_MUTED, font=(self.FONT_UI, 10))
        self.header_sub.pack(anchor=tk.W, pady=(3, 0))

        destra = tk.Frame(head, bg=self.COL_BG)
        destra.pack(side=tk.RIGHT, anchor=tk.E)
        self.header_clock = tk.Label(destra, text="", bg=self.COL_CARD,
                                     fg=self.COL_MUTED, font=(self.FONT_MONO, 10),
                                     padx=14, pady=7, highlightthickness=1,
                                     highlightbackground=self.COL_BORDER)
        self.header_clock.pack(side=tk.RIGHT)

    def _show_screen(self, key):
        """Porta in primo piano una schermata e aggiorna menu e intestazione."""
        if key == self._current_screen:
            return

        if self._current_screen is not None:
            self._nav_buttons[self._current_screen].config(
                bg=self.COL_CARD, fg=self.COL_MUTED)

        self._current_screen = key
        self._nav_buttons[key].config(bg=self.COL_SOFT, fg=self.COL_PRIMARY)
        self._screens[key].tkraise()

        for k, _icona, _voce, titolo, sub, _builder in self.SCREENS:
            if k == key:
                self.header_title.config(text=titolo)
                self.header_sub.config(text=sub)
                break

    def _update_clock(self):
        """Aggiorna l'orologio nell'header."""
        self.header_clock.config(text=datetime.now().strftime("%d/%m/%Y   %H:%M:%S"))
        self.root.after(1000, self._update_clock)

    # ------------------------------------------------------------------
    # Contenitore scrollabile (per le tab piu' alte della finestra)
    # ------------------------------------------------------------------
    def _make_scrollable(self, parent):
        """
        Crea dentro `parent` un'area verticale scrollabile.

        Tkinter non sa scrollare un Frame: serve un Canvas che ospiti il
        contenuto in una finestra interna. Il chiamante costruisce i widget nel
        frame restituito e, a costruzione finita, chiama _bind_mousewheel.

        :return: (frame in cui costruire i widget, canvas che lo scrolla)
        """
        canvas = tk.Canvas(parent, bg=self.COL_BG, highlightthickness=0)
        vbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # tk.Frame e non ttk.Frame: lo stile ttk di default e' bianco (le card),
        # mentre qui serve lo sfondo grigio della pagina fra un blocco e l'altro.
        inner = tk.Frame(canvas, bg=self.COL_BG)
        window = canvas.create_window((0, 0), window=inner, anchor='nw')

        # L'area scrollabile segue l'altezza effettiva del contenuto
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        # ...e la larghezza del canvas, cosi' i frame interni riempiono la tab
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfigure(window, width=e.width))

        return inner, canvas

    def _bind_mousewheel(self, widget, canvas):
        """
        Abilita la rotella del mouse su `widget` e su tutti i suoi discendenti.

        Va chiamata a costruzione finita (i binding sono per-widget: quelli
        creati dopo non li erediterebbero). Si evita bind_all perche' ruberebbe
        la rotella alle altre tab.
        """
        def _on_wheel(event):
            if event.num == 4:      # Linux / Raspberry Pi: rotella su
                delta = -1
            elif event.num == 5:    # Linux / Raspberry Pi: rotella giu'
                delta = 1
            else:                   # Windows / macOS
                delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta, 'units')
            # Blocca il binding di classe: sopra una Combobox la rotella
            # scrolla la pagina invece di cambiarne il valore.
            return 'break'

        def _bind(w):
            w.bind('<MouseWheel>', _on_wheel)   # Windows / macOS
            w.bind('<Button-4>', _on_wheel)     # X11 (Raspberry Pi)
            w.bind('<Button-5>', _on_wheel)
            for child in w.winfo_children():
                _bind(child)

        _bind(widget)
        _bind(canvas)

    # ------------------------------------------------------------------
    # Immagini (foto della camera, plot giornaliero)
    # ------------------------------------------------------------------
    def _show_image(self, label, path, max_w=760):
        """
        Carica `path` dentro `label`, ridimensionandola a `max_w` di larghezza.

        Serve Pillow: tk.PhotoImage legge solo PNG/GIF, mentre le foto della
        camera sono JPG. Se Pillow manca (o il file non c'e'), la label mostra
        un messaggio invece di far fallire la scheda.

        Il riferimento all'immagine va tenuto sulla label: Tk non lo conserva e
        senza di esso il garbage collector la fa sparire appena disegnata.

        :return: True se l'immagine e' stata mostrata
        """
        if not path or not os.path.exists(path):
            label.config(image='', text="Nessuna immagine disponibile", foreground=self.COL_FAINT)
            label.image = None
            return False

        try:
            from PIL import Image, ImageTk
        except ImportError:
            label.config(image='', foreground=self.COL_FAINT,
                         text="Pillow non installato: impossibile mostrare l'immagine\n"
                              "(sul Raspberry Pi: sudo apt install python3-pil.imagetk)")
            label.image = None
            return False

        try:
            img = Image.open(path)
            if img.width > max_w:
                altezza = round(img.height * max_w / img.width)
                img = img.resize((max_w, altezza), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception as e:
            label.config(image='', text=f"Errore nel caricamento immagine: {e}",
                         foreground=self.COL_BAD)
            label.image = None
            return False

        label.config(image=photo, text='')
        label.image = photo   # riferimento anti-GC
        return True

    # ------------------------------------------------------------------
    # Tab: Configurazione
    # ------------------------------------------------------------------
    def create_config_tab(self, parent):
        """Tab per modificare la configurazione"""
        # Il contenuto e' piu' alto della finestra: va reso scrollabile.
        # Da qui in poi `parent` e' l'area interna scrollabile.
        parent, config_canvas = self._make_scrollable(parent)

        # Frame per T_var
        t_frame = self._card(parent, "Variabili Temperatura")
        t_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(t_frame, text="T_opt (°C):").grid(row=0, column=0, sticky=tk.W)
        self.t_opt_var = tk.StringVar(value=str(self.config.get('T_var', {}).get('Topt', 18)))
        ttk.Entry(t_frame, textvariable=self.t_opt_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(t_frame, text="H_opt (%):").grid(row=0, column=2, sticky=tk.W)
        self.h_opt_var = tk.StringVar(value=str(self.config.get('T_var', {}).get('Hopt', 65)))
        ttk.Entry(t_frame, textvariable=self.h_opt_var, width=10).grid(row=0, column=3, sticky=tk.W)

        # Frame per DHT22
        dht_frame = self._card(parent, "DHT22 Sensor")
        dht_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(dht_frame, text="Pin:").grid(row=0, column=0, sticky=tk.W)
        self.dht_pin_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('pin', 27)))
        ttk.Entry(dht_frame, textvariable=self.dht_pin_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(dht_frame, text="Intervallo Lettura (s):").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.dht_interval_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('read_interval', 5)))
        ttk.Entry(dht_frame, textvariable=self.dht_interval_var, width=10).grid(row=0, column=3, sticky=tk.W)

        # Frame per IR Control
        ir_frame = self._card(parent, "IR Control (Condizionatore)")
        ir_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(ir_frame, text="TX Pin GPIO:").grid(row=0, column=0, sticky=tk.W)
        self.ir_tx_pin_var = tk.StringVar(value=str(self.config.get('ir_control', {}).get('tx_pin', 17)))
        ttk.Entry(ir_frame, textvariable=self.ir_tx_pin_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(ir_frame, text="File Comandi AC:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.ir_file_var = tk.StringVar(value=self.config.get('ir_control', {}).get('file_ac_name', 'ac_controller.json'))
        ttk.Entry(ir_frame, textvariable=self.ir_file_var, width=30).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(ir_frame, text="Tempo max accensione (min):").grid(row=1, column=0, sticky=tk.W)
        self.ir_time_max_var = tk.StringVar(value=str(self.config.get('ir_control', {}).get('time_max_on', 30.0)))
        ttk.Entry(ir_frame, textvariable=self.ir_time_max_var, width=10).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(ir_frame, text="Separazione controllo (min):").grid(row=1, column=2, sticky=tk.W)
        self.ir_time_sep_var = tk.StringVar(value=str(self.config.get('ir_control', {}).get('control_time', 15)))
        ttk.Entry(ir_frame, textvariable=self.ir_time_sep_var, width=10).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(ir_frame, text="Temp accensione (°C):").grid(row=2, column=0, sticky=tk.W)
        self.ir_T_max_var = tk.StringVar(value=str(self.config.get('ir_control', {}).get('T_max', 25.0)))
        ttk.Entry(ir_frame, textvariable=self.ir_T_max_var, width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(ir_frame, text="RH accensione (%):").grid(row=2, column=2, sticky=tk.W)
        self.ir_H_max_var = tk.StringVar(value=str(self.config.get('ir_control', {}).get('H_max', 65.0)))
        ttk.Entry(ir_frame, textvariable=self.ir_H_max_var, width=10).grid(row=2, column=3, sticky=tk.W)

        # Frame per le schede Arduino
        self._build_arduino_config_card(parent)

        # Frame per Acqua (pH / EC)
        water_cfg_frame = self._card(parent, "Acqua — pH e conducibilità elettrica")
        water_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        w = self.config.get('water', {})

        ttk.Label(water_cfg_frame, text="Intervallo lettura pH (s):").grid(row=0, column=0, sticky=tk.W)
        self.water_ph_interval_var = tk.StringVar(value=str(w.get('ph_read_interval', 1800)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ph_interval_var,
                  width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="Intervallo lettura EC (s):").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.water_ec_interval_var = tk.StringVar(value=str(w.get('ec_read_interval', 1800)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ec_interval_var,
                  width=10).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="pH minimo:").grid(row=1, column=0, sticky=tk.W)
        self.water_ph_min_var = tk.StringVar(value=str(w.get('ph_min', 5.5)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ph_min_var,
                  width=10).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="pH massimo:").grid(row=1, column=2, sticky=tk.W, padx=(20, 0))
        self.water_ph_max_var = tk.StringVar(value=str(w.get('ph_max', 6.5)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ph_max_var,
                  width=10).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="EC minima (µS/cm):").grid(row=2, column=0, sticky=tk.W)
        self.water_ec_min_var = tk.StringVar(value=str(w.get('ec_min', 800)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ec_min_var,
                  width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="EC massima (µS/cm):").grid(row=2, column=2, sticky=tk.W, padx=(20, 0))
        self.water_ec_max_var = tk.StringVar(value=str(w.get('ec_max', 2000)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_ec_max_var,
                  width=10).grid(row=2, column=3, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="Cifre decimali:").grid(row=3, column=0, sticky=tk.W)
        self.water_decimals_var = tk.StringVar(value=str(w.get('decimals', 2)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_decimals_var,
                  width=10).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="N. misure nello storico:").grid(row=3, column=2, sticky=tk.W, padx=(20, 0))
        self.water_history_var = tk.StringVar(value=str(w.get('history_len', 30)))
        ttk.Entry(water_cfg_frame, textvariable=self.water_history_var,
                  width=10).grid(row=3, column=3, sticky=tk.W)

        ttk.Label(water_cfg_frame, text="Directory dati:").grid(row=4, column=0, sticky=tk.W)
        self.water_dir_var = tk.StringVar(
            value=w.get('saving_dir', '/home/fishnplants/Desktop/data/WATER/'))
        ttk.Entry(water_cfg_frame, textvariable=self.water_dir_var, width=50).grid(
            row=4, column=1, columnspan=3, sticky=tk.W)

        # Frame per Serbatoio (Tank)
        tank_cfg_frame = self._card(parent, "Serbatoio (Tank) — taratura della tanica")
        tank_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        tank = self.config.get('tank', {})

        # I pin del sensore non stanno piu' qui: l'HC-SR04 e' collegato
        # all'Arduino, quindi si configurano nella card "Schede Arduino".
        ttk.Label(tank_cfg_frame,
                  text="Sensore ultrasonico collegato all'Arduino: i pin si impostano "
                       "nella card «Schede Arduino» (sensore US_water).",
                  foreground=self.COL_FAINT).grid(row=0, column=0, columnspan=4,
                                                  sticky=tk.W, pady=(0, 6))

        ttk.Label(tank_cfg_frame, text="Altezza tanica (cm):").grid(row=1, column=0, sticky=tk.W)
        self.tank_height_var = tk.StringVar(value=str(tank.get('tank_height_cm', 30.0)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_height_var, width=10).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="Offset sensore (cm):").grid(row=1, column=2, sticky=tk.W, padx=(20, 0))
        self.tank_offset_var = tk.StringVar(value=str(tank.get('sensor_offset_cm', 2.0)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_offset_var, width=10).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="Area sezione (cm²):").grid(row=2, column=0, sticky=tk.W)
        self.tank_area_var = tk.StringVar(value=str(tank.get('tank_area_cm2', 900.0)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_area_var, width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="Soglia minima (L):").grid(row=2, column=2, sticky=tk.W, padx=(20, 0))
        self.tank_low_var = tk.StringVar(value=str(tank.get('water_low_threshold_l', 3.0)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_low_var, width=10).grid(row=2, column=3, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="Intervallo lettura (s):").grid(row=3, column=0, sticky=tk.W)
        self.tank_interval_var = tk.StringVar(value=str(tank.get('read_interval', 300)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_interval_var, width=10).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="N. campioni:").grid(row=3, column=2, sticky=tk.W, padx=(20, 0))
        self.tank_nsamples_var = tk.StringVar(value=str(tank.get('n_samples', 5)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_nsamples_var, width=10).grid(row=3, column=3, sticky=tk.W)

        # Frame per Spettrometro (Spectro)
        spectro_cfg_frame = self._card(parent, "Spettrometro (AS7265x) — indice MCARI2")
        spectro_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        sp = self.config.get('spectro', {})

        ttk.Label(spectro_cfg_frame, text="Intervallo lettura (s):").grid(row=0, column=0, sticky=tk.W)
        self.spectro_interval_var = tk.StringVar(value=str(sp.get('read_interval', 3600)))
        ttk.Entry(spectro_cfg_frame, textvariable=self.spectro_interval_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(spectro_cfg_frame, text="N. misure nello storico:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.spectro_history_var = tk.StringVar(value=str(sp.get('history_len', 10)))
        ttk.Entry(spectro_cfg_frame, textvariable=self.spectro_history_var, width=10).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(spectro_cfg_frame, text="Directory dati:").grid(row=1, column=0, sticky=tk.W)
        self.spectro_dir_var = tk.StringVar(
            value=sp.get('saving_dir', '/home/fishnplants/Desktop/data/SPECTRO/'))
        ttk.Entry(spectro_cfg_frame, textvariable=self.spectro_dir_var, width=50).grid(
            row=1, column=1, columnspan=3, sticky=tk.EW)

        # Frame per Crescita (plant_growth)
        growth_cfg_frame = self._card(parent, "Crescita (altezza pianta)")
        growth_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        g = self.config.get('plant_growth', {})

        ttk.Label(growth_cfg_frame, text="Altezza riferimento (cm):").grid(row=0, column=0, sticky=tk.W)
        self.growth_ref_var = tk.StringVar(value=str(g.get('reference_height_cm', 70.0)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_ref_var, width=10).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(growth_cfg_frame, text="(impostata dal bottone 📐 Calibrazione nella tab Crescita)",
                  foreground=self.COL_FAINT).grid(row=0, column=2, columnspan=2, sticky=tk.W, padx=(20, 0))

        ttk.Label(growth_cfg_frame,
                  text="Sensore ultrasonico collegato all'Arduino: i pin si impostano "
                       "nella card «Schede Arduino» (sensore US_plant).",
                  foreground=self.COL_FAINT).grid(row=1, column=0, columnspan=4,
                                                  sticky=tk.W, pady=(4, 4))

        ttk.Label(growth_cfg_frame, text="Intervallo misura (giorni):").grid(row=2, column=0, sticky=tk.W)
        self.growth_interval_var = tk.StringVar(value=str(g.get('read_interval_days', 1)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_interval_var, width=10).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(growth_cfg_frame, text="N. campioni:").grid(row=2, column=2, sticky=tk.W, padx=(20, 0))
        self.growth_nsamples_var = tk.StringVar(value=str(g.get('n_samples', 3)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_nsamples_var, width=10).grid(row=2, column=3, sticky=tk.W)

        ttk.Label(growth_cfg_frame, text="Cifre decimali:").grid(row=3, column=0, sticky=tk.W)
        self.growth_decimals_var = tk.StringVar(value=str(g.get('decimals', 1)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_decimals_var, width=10).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(growth_cfg_frame, text="N. misure nello storico:").grid(row=3, column=2, sticky=tk.W, padx=(20, 0))
        self.growth_history_var = tk.StringVar(value=str(g.get('history_len', 30)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_history_var, width=10).grid(row=3, column=3, sticky=tk.W)

        ttk.Label(growth_cfg_frame, text="Directory dati:").grid(row=4, column=0, sticky=tk.W)
        self.growth_dir_var = tk.StringVar(
            value=g.get('saving_dir', '/home/fishnplants/Desktop/data/GROWTH/'))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_dir_var, width=50).grid(
            row=4, column=1, columnspan=3, sticky=tk.EW)

        # Frame per Camera
        camera_cfg_frame = self._card(parent, "Camera (Picamera2)")
        camera_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        cam = self.config.get('camera', {})

        ttk.Label(camera_cfg_frame, text="Separazione scatti (ore):").grid(row=0, column=0, sticky=tk.W)
        self.camera_hours_var = tk.StringVar(value=str(cam.get('separation_hours', 2)))
        ttk.Entry(camera_cfg_frame, textvariable=self.camera_hours_var, width=10).grid(
            row=0, column=1, sticky=tk.W)

        ttk.Label(camera_cfg_frame, text="Directory foto:").grid(row=1, column=0, sticky=tk.W)
        self.camera_dir_var = tk.StringVar(
            value=cam.get('saving_dir', '/home/fishnplants/Desktop/data/IMG/'))
        ttk.Entry(camera_cfg_frame, textvariable=self.camera_dir_var, width=50).grid(
            row=1, column=1, columnspan=3, sticky=tk.EW)

        # Frame per Daily Data (elaborazione giornaliera T/H/VPD)
        daily_cfg_frame = self._card(parent, "Daily Data — elaborazione giornaliera T/H/VPD")
        daily_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        dd = self.config.get('Daily_Data', {})

        ttk.Label(daily_cfg_frame, text="Directory dati TH:").grid(row=0, column=0, sticky=tk.W)
        self.daily_th_dir_var = tk.StringVar(
            value=dd.get('th_data_dir', '/home/fishnplants/Desktop/data/TH/'))
        ttk.Entry(daily_cfg_frame, textvariable=self.daily_th_dir_var, width=50).grid(
            row=0, column=1, sticky=tk.EW)

        ttk.Label(daily_cfg_frame, text="Directory plot:").grid(row=1, column=0, sticky=tk.W)
        self.daily_plot_dir_var = tk.StringVar(
            value=dd.get('plot_output_dir', '/home/fishnplants/Desktop/data/PLOT/'))
        ttk.Entry(daily_cfg_frame, textvariable=self.daily_plot_dir_var, width=50).grid(
            row=1, column=1, sticky=tk.EW)

        # Frame per Log
        log_frame = self._card(parent, "Impostazioni Log")
        log_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(log_frame, text="Directory:").grid(row=0, column=0, sticky=tk.W)
        self.log_dir_var = tk.StringVar(value=self.config.get('log', {}).get('directory', ''))
        ttk.Entry(log_frame, textvariable=self.log_dir_var, width=50).grid(row=0, column=1, sticky=tk.EW)

        ttk.Label(log_frame, text="Filename:").grid(row=1, column=0, sticky=tk.W)
        self.log_file_var = tk.StringVar(value=self.config.get('log', {}).get('filename', ''))
        ttk.Entry(log_frame, textvariable=self.log_file_var, width=50).grid(row=1, column=1, sticky=tk.EW)

        ttk.Label(log_frame, text="Level:").grid(row=2, column=0, sticky=tk.W)
        self.log_level_var = tk.StringVar(value=self.config.get('log', {}).get('level', 'INFO'))
        level_combo = ttk.Combobox(log_frame, textvariable=self.log_level_var,
                                   values=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], width=20)
        level_combo.grid(row=2, column=1, sticky=tk.W)

        # Frame per Config Reload Interval
        reload_frame = self._card(parent, "Impostazioni Sistema")
        reload_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(reload_frame, text="Config Reload Interval (s):").grid(row=0, column=0, sticky=tk.W)
        self.reload_interval_var = tk.StringVar(value=str(self.config.get('config_reload_interval', 4)))
        ttk.Entry(reload_frame, textvariable=self.reload_interval_var, width=10).grid(row=0, column=1, sticky=tk.W)

        # Bottone Salva
        btn_frame = tk.Frame(parent, bg=self.COL_BG)
        btn_frame.pack(fill=tk.X, padx=10, pady=20)

        ttk.Button(btn_frame, text="Salva Configurazione", style='Accent.TButton',
                   command=self.save_config_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Ricarica", command=self.reload_config_tab).pack(side=tk.LEFT, padx=5)

        # Rotella del mouse: da fare per ultimo, quando i widget esistono tutti
        self._bind_mousewheel(parent, config_canvas)

    # ------------------------------------------------------------------
    # Tab: Riepilogo (sintesi delle altre schede)
    # ------------------------------------------------------------------
    def create_riepilogo_tab(self, parent):
        """
        Scheda di sintesi: un blocco per categoria, con l'ultimo valore e la
        data della misura.

        E' la prima scheda costruita, quindi puo' leggere solo self.ah.* e
        self.config: i widget delle altre schede non esistono ancora.

        I valori arrivano dai manager, che li rileggono da file all'avvio: la
        scheda e' utile gia' prima di aver avviato una lettura.
        """
        # Cache dei valori disegnati: il refresh ridisegna un arco solo quando
        # il valore cambia (su un Pi Zero W ridisegnare 5 blocchi al secondo
        # sarebbe spreco puro).
        self._riep_cache = {}
        self._riep_active_keys = None

        parent, riep_canvas = self._make_scrollable(parent)

        grid = tk.Frame(parent, bg=self.COL_BG)
        grid.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform='riep')
        # minsize: dentro l'area scrollabile le righe hanno solo l'altezza che
        # chiedono, quindi i pesi da soli lascerebbero i blocchi schiacciati.
        grid.rowconfigure(0, weight=3, minsize=270)
        grid.rowconfigure(1, weight=2, minsize=190)

        # --- Riga 0: i tre sensori con un fondo scala naturale ---
        self.riep_amb_gauge, self.riep_amb_labels, self.riep_amb_date = self._build_riep_card(
            grid, 0, 0, "Ambiente", ("Temperatura", "VPD"))

        # Il blocco H2O riassume tutta l'acqua: quanta ce n'e' (arco sul
        # riempimento) e com'e' fatta (pH ed EC dalle sonde su Arduino).
        self.riep_tank_gauge, self.riep_tank_labels, self.riep_tank_date = self._build_riep_card(
            grid, 0, 1, "H2O", ("Volume", "pH", "EC"))

        self.riep_mcari_gauge, self.riep_mcari_labels, self.riep_mcari_date = self._build_riep_card(
            grid, 0, 2, "Indice MCARI2", ("Stato",))

        # --- Riga 1: crescita (numero grande) e processi attivi ---
        growth_card = self._card(grid, "Crescita")
        growth_card.grid(row=1, column=0, sticky=tk.NSEW, padx=5, pady=5)
        inner = ttk.Frame(growth_card)
        inner.pack(expand=True)
        ttk.Label(inner, text="ALTEZZA PIANTA", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.riep_growth_value = ttk.Label(inner, text="--", font=(self.FONT_MONO, 34),
                                           foreground=self.COL_PRIMARY)
        self.riep_growth_value.pack()
        self.riep_growth_date = ttk.Label(inner, text="Nessuna misura", font=(self.FONT_UI, 9),
                                          foreground=self.COL_FAINT)
        self.riep_growth_date.pack(pady=(4, 0))

        proc_card = self._card(grid, "Processi Attivi")
        proc_card.grid(row=1, column=1, columnspan=2, sticky=tk.NSEW, padx=5, pady=5)
        self.riep_proc_frame = ttk.Frame(proc_card)
        self.riep_proc_frame.pack(fill=tk.BOTH, expand=True)
        # Il ciclo di aggiornamento parte da __init__, con gli altri poller.

        self._bind_mousewheel(parent, riep_canvas)

    def _build_riep_card(self, grid, row, col, titolo, campi):
        """
        Crea un blocco del Riepilogo: arco + valori testuali + data.

        :param campi: etichette dei valori testuali sotto l'arco
        :return: (canvas dell'arco, dict {campo: label del valore}, label della data)
        """
        card = self._card(grid, titolo)
        card.grid(row=row, column=col, sticky=tk.NSEW, padx=5, pady=5)

        canvas = tk.Canvas(card, height=110, highlightthickness=0, bg=self.COL_CARD)
        canvas.pack(fill=tk.X)
        canvas.bind('<Configure>', lambda e: self.refresh_riepilogo_tab(force=True))

        labels = {}
        for campo in campi:
            riga = ttk.Frame(card)
            riga.pack(fill=tk.X, pady=1)
            ttk.Label(riga, text=f"{campo}:", font=(self.FONT_UI, 10)).pack(side=tk.LEFT)
            valore = ttk.Label(riga, text="--", font=(self.FONT_UI, 12, 'bold'))
            valore.pack(side=tk.RIGHT)
            labels[campo] = valore

        data = ttk.Label(card, text="Nessuna misura", font=(self.FONT_UI, 9),
                         foreground=self.COL_FAINT)
        data.pack(pady=(6, 0))
        return canvas, labels, data

    def _draw_arc_gauge(self, canvas, value, vmin, vmax, color, testo, unita=""):
        """
        Disegna un indicatore ad arco semicircolare sul Canvas.

        Come per il grafico della crescita, si usano le primitive native di Tk:
        su un Pi Zero W matplotlib costerebbe secondi di import e decine di MB
        di RAM per disegnare mezza ciambella.

        :param value: valore da rappresentare (None -> arco vuoto)
        :param vmin, vmax: fondo scala
        :param testo: testo grande al centro
        """
        canvas.delete('all')
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w <= 1 or h <= 1:  # Canvas non ancora disegnato
            return

        spessore = 12
        margine = 18
        lato = min(w - 2 * margine, (h - 14) * 2)
        if lato <= spessore * 2:
            return
        x0 = (w - lato) / 2
        y0 = 8
        box = (x0 + spessore / 2, y0 + spessore / 2,
               x0 + lato - spessore / 2, y0 + lato - spessore / 2)

        # Arco di sfondo (scala completa)
        canvas.create_arc(*box, start=180, extent=-180, style=tk.ARC,
                          outline=self.COL_DIV, width=spessore)

        # Arco del valore
        if value is not None and vmax > vmin:
            frazione = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
            if frazione > 0:
                canvas.create_arc(*box, start=180, extent=-180 * frazione, style=tk.ARC,
                                  outline=color, width=spessore)

        # Valore al centro
        cx = x0 + lato / 2
        cy = y0 + lato / 2
        canvas.create_text(cx, cy - 8, text=testo, font=(self.FONT_MONO, 22),
                           fill=color if value is not None else self.COL_FAINT)
        if unita:
            canvas.create_text(cx, cy + 12, text=unita, font=(self.FONT_UI, 9), fill=self.COL_FAINT)

        # Etichette di fondo scala
        canvas.create_text(x0 + spessore / 2, cy + 12, text=self._fmt_scala(vmin),
                           font=(self.FONT_UI, 8), fill=self.COL_FAINT)
        canvas.create_text(x0 + lato - spessore / 2, cy + 12, text=self._fmt_scala(vmax),
                           font=(self.FONT_UI, 8), fill=self.COL_FAINT)

    def _fmt_scala(self, v):
        """Formatta un fondo scala senza decimali inutili (100 invece di 100.0)."""
        return f"{v:g}"

    def _format_acq_date(self, ts):
        """Formatta la data di acquisizione: '2026/07/17 09:41:03' -> '17/07/2026 09:41'."""
        try:
            return datetime.strptime(ts, "%Y/%m/%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            return str(ts)

    def refresh_riepilogo_tab(self, force=False):
        """
        Aggiorna i blocchi del Riepilogo.

        Costruisce i widget una volta sola e poi tocca solo i valori, come fa
        refresh_status_tab: gli archi si ridisegnano soltanto quando il valore
        cambia (o su richiesta esplicita, es. al ridimensionamento).

        :param force: ridisegna gli archi anche se i valori non sono cambiati
        """
        self._refresh_riep_ambiente(force)
        self._refresh_riep_serbatoio(force)
        self._refresh_riep_mcari2(force)
        self._refresh_riep_crescita()
        self._refresh_riep_processi()

        # Il tick periodico parte solo dalla chiamata senza force, cosi' il
        # ridisegno da <Configure> non moltiplica i timer.
        if not force:
            self.root.after(1000, self.refresh_riepilogo_tab)

    def _cambiato(self, chiave, valore, force):
        """True se il valore da disegnare e' cambiato dall'ultimo ridisegno."""
        if not force and self._riep_cache.get(chiave, '_mai_') == valore:
            return False
        self._riep_cache[chiave] = valore
        return True

    def _refresh_riep_ambiente(self, force):
        """Blocco Ambiente: arco sull'umidita', numeri per temperatura e VPD."""
        r = self.ah.ambient.last_result
        if not self._cambiato('ambiente', None if r is None else tuple(r.values()), force):
            return

        if r is None:
            self._draw_arc_gauge(self.riep_amb_gauge, None, 0, 100, 'gray', "--", "Umidità (%)")
            return

        self._draw_arc_gauge(self.riep_amb_gauge, r['humidity'], 0, 100,
                             self.COL_WARN, f"{r['humidity']:.1f}", "Umidità (%)")
        self.riep_amb_labels['Temperatura'].config(text=f"{r['temperature']:.1f} °C",
                                                   foreground=self.COL_BLUE)
        self.riep_amb_labels['VPD'].config(text=f"{r['vpd']:.4f} kPa", foreground=self.COL_PRIMARY)
        self.riep_amb_date.config(text=f"Acquisito: {self._format_acq_date(r['timestamp'])}")

    def _refresh_riep_serbatoio(self, force):
        """Blocco H2O: arco sul riempimento, piu' volume, pH ed EC."""
        r = self.ah.tank.last_result
        ph = self.ah.water.last_ph
        ec = self.ah.water.last_ec

        # La firma comprende anche pH ed EC: le tre grandezze si aggiornano
        # con cadenze diverse, e il blocco va ridisegnato appena UNA cambia.
        firma = (
            None if r is None else tuple(r.values()),
            None if ph is None else ph.get('ph'),
            None if ec is None else ec.get('ec_us_cm'),
        )
        if not self._cambiato('serbatoio', firma, force):
            return

        self.riep_tank_labels['pH'].config(
            text="--" if ph is None else f"{ph['ph']:.2f}")
        self.riep_tank_labels['EC'].config(
            text="--" if ec is None else f"{ec['ec_us_cm']:.0f} µS/cm")

        if r is None:
            self._draw_arc_gauge(self.riep_tank_gauge, None, 0, 100, 'gray', "--", "Riempimento (%)")
            return

        # Il colore segue il livello: sotto un quarto la tanica va riempita
        fill = r['fill_percent']
        colore = self.COL_BAD if fill < 25 else (self.COL_WARN if fill < 50 else self.COL_BLUE)
        self._draw_arc_gauge(self.riep_tank_gauge, fill, 0, 100, colore,
                             f"{fill:.1f}", "Riempimento (%)")
        self.riep_tank_labels['Volume'].config(text=f"{r['volume_L']:.2f} L", foreground=colore)
        self.riep_tank_date.config(text=f"Misurato: {self._format_acq_date(r['timestamp'])}")

    def _refresh_riep_mcari2(self, force):
        """Blocco MCARI2: arco 0-1 colorato per fascia di salute della pianta."""
        storico = self.ah.spectro.history
        r = storico[0] if storico else None   # lo storico spectro ha il piu' recente in testa
        if not self._cambiato('mcari2', None if r is None else (r['timestamp'], r['mcari2']), force):
            return

        if r is None:
            self._draw_arc_gauge(self.riep_mcari_gauge, None, 0, 1, 'gray', "--", "MCARI2")
            return

        colore = self.MCARI2_COLORS.get(r['stato'], self.COL_FAINT)
        self._draw_arc_gauge(self.riep_mcari_gauge, r['mcari2'], 0, 1, colore,
                             f"{r['mcari2']:.3f}", "MCARI2")
        self.riep_mcari_labels['Stato'].config(text=r['stato'], foreground=colore)
        self.riep_mcari_date.config(text=f"Valutato: {self._format_acq_date(r['timestamp'])}")

    def _refresh_riep_crescita(self):
        """Blocco Crescita: altezza dell'ultima misura (nessun fondo scala naturale)."""
        storico = self.ah.plant_growth.history
        r = storico[-1] if storico else None   # lo storico crescita e' in ordine crescente
        if not self._cambiato('crescita', None if r is None else tuple(r.values()), False):
            return

        if r is None:
            self.riep_growth_value.config(text="--", foreground=self.COL_FAINT)
            self.riep_growth_date.config(text="Nessuna misura")
            return

        self.riep_growth_value.config(text=f"{r['h_plant_cm']:.1f} cm", foreground=self.COL_PRIMARY)
        self.riep_growth_date.config(text=f"Misurato: {self._format_acq_date(r['timestamp'])}")

    def _refresh_riep_processi(self):
        """Blocco Processi Attivi: solo quelli in esecuzione."""
        attivi = [nome for nome, acceso in self.get_process_states() if acceso]
        if attivi == self._riep_active_keys:
            return
        self._riep_active_keys = attivi

        for child in self.riep_proc_frame.winfo_children():
            child.destroy()

        if not attivi:
            ttk.Label(self.riep_proc_frame, text="Nessun processo attivo",
                      font=(self.FONT_UI, 10), foreground=self.COL_FAINT).pack(anchor=tk.W, pady=4)
            return

        for nome in attivi:
            riga = ttk.Frame(self.riep_proc_frame)
            riga.pack(fill=tk.X, pady=2)
            spia = tk.Canvas(riga, width=16, height=16, highlightthickness=0, bg=self.COL_CARD)
            spia.pack(side=tk.LEFT, padx=(2, 10))
            spia.create_oval(3, 3, 13, 13, fill=self.COL_OK, outline='')
            ttk.Label(riga, text=nome, font=(self.FONT_UI, 11)).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Tab: Processi Attivi
    # ------------------------------------------------------------------
    def create_status_tab(self, parent):
        """Tab che mostra lo stato (verde=attivo / rosso=fermo) dei processi."""
        parent, status_canvas = self._make_scrollable(parent)

        container = self._card(parent, "Stato dei Processi")
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Legenda
        legend = ttk.Frame(container)
        legend.pack(fill=tk.X, pady=(0, 12))
        self._chip(legend, "● ATTIVO", self.COL_PRIMARY, self.COL_SOFT).pack(
            side=tk.LEFT, padx=(0, 8))
        self._chip(legend, "● FERMO", self.COL_BAD, "#fdecec").pack(side=tk.LEFT)

        # Contenitore delle righe (ricostruito quando cambia l'elenco processi)
        self.status_rows_frame = ttk.Frame(container)
        self.status_rows_frame.pack(fill=tk.BOTH, expand=True)

        self._bind_mousewheel(parent, status_canvas)
        # Le righe nascono da _rebuild_status_rows, dopo questa bind: la rotella
        # va riagganciata li'.
        self._status_canvas = status_canvas

    def get_process_states(self):
        """Ritorna la lista ordinata (etichetta, attivo:bool) dei processi monitorati."""
        states = []
        jobs = self.ah.jobs

        # Job definiti in config (escludendo i sensori)
        for job in self.config.get('gpio_pins', []):
            if job.get('what_type') == 'sensor':
                continue
            name = job.get('name', '')
            if name == 'AEROPONICS':
                active = jobs.aeroponics_job_active
            elif name == 'IDROPONICS':
                active = jobs.idroponics_job_active
            else:
                active = jobs.general_jobs_active.get(name, False)
            states.append((f"Job · {name}", active))

        # Processi di sistema
        states.append(("Lettura Ambient (T/H)", self.ah.ambient.is_running()))
        states.append(("Controllo Climatizzatore", self.ah.climate.is_running()))
        states.append(("Lettura Serbatoio", self.ah.tank.is_running()))
        states.append(("Lettura pH", self.ah.water.is_ph_running()))
        states.append(("Lettura EC", self.ah.water.is_ec_running()))
        states.append(("Lettura Spettrometro", self.ah.spectro.is_running()))
        states.append(("Misura Crescita", self.ah.plant_growth.is_running()))
        states.append(("Acquisizione Camera", self.ah.camera.is_acquiring()))
        states.append(("Anteprima Camera", self.ah.camera.is_previewing()))
        states.append(("Daily TH VPD", self.ah.daily_th.is_running()))
        return states

    def _rebuild_status_rows(self, keys):
        """(Ri)crea le righe della tab Processi Attivi."""
        for child in self.status_rows_frame.winfo_children():
            child.destroy()
        self.status_indicators = {}

        for i, k in enumerate(keys):
            # Separatore sottile fra le righe (la prima non ce l'ha)
            if i:
                tk.Frame(self.status_rows_frame, bg=self.COL_DIV, height=1).pack(fill=tk.X)

            row = ttk.Frame(self.status_rows_frame)
            row.pack(fill=tk.X, pady=8)

            canvas = tk.Canvas(row, width=14, height=14, highlightthickness=0, bg=self.COL_CARD)
            canvas.pack(side=tk.LEFT, padx=(2, 14))
            oval = canvas.create_oval(3, 3, 13, 13, fill=self.COL_BAD, outline='')

            ttk.Label(row, text=k, font=(self.FONT_UI, 11)).pack(side=tk.LEFT)

            state_lbl = ttk.Label(row, text="FERMO", font=(self.FONT_UI, 9, 'bold'),
                                  foreground=self.COL_BAD)
            state_lbl.pack(side=tk.RIGHT, padx=6)

            self.status_indicators[k] = (canvas, oval, state_lbl)

        self._bind_mousewheel(self.status_rows_frame, self._status_canvas)

    def refresh_status_tab(self):
        """Aggiorna periodicamente le spie di stato dei processi."""
        states = self.get_process_states()
        keys = [s[0] for s in states]

        if keys != self._status_keys:
            self._rebuild_status_rows(keys)
            self._status_keys = keys

        for label, active in states:
            canvas, oval, state_lbl = self.status_indicators[label]
            color = self.COL_OK if active else self.COL_BAD
            canvas.itemconfig(oval, fill=color)
            state_lbl.config(text="ATTIVO" if active else "FERMO", foreground=color)

        self.root.after(1000, self.refresh_status_tab)

    # ------------------------------------------------------------------
    # Tab: Gestione Job
    # ------------------------------------------------------------------
    def create_jobs_tab(self, parent):
        """Tab per gestire i job (GPIO pins)"""
        parent, jobs_canvas = self._make_scrollable(parent)

        # Frame lista job
        list_frame = self._card(parent, "Job Attuali")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Treeview per visualizzare i job
        columns = ('Nome', 'Pin', 'Interval (min)', 'On Time (s)', 'Stato')
        self.jobs_tree = ttk.Treeview(list_frame, columns=columns, height=8)
        self.jobs_tree.heading('#0', text='ID')
        self.jobs_tree.heading('Nome', text='Nome')
        self.jobs_tree.heading('Pin', text='Pin')
        self.jobs_tree.heading('Interval (min)', text='Interval (min)')
        self.jobs_tree.heading('On Time (s)', text='On Time (s)')
        self.jobs_tree.heading('Stato', text='Stato')

        self.jobs_tree.column('#0', width=30)
        self.jobs_tree.column('Nome', width=120)
        self.jobs_tree.column('Pin', width=60)
        self.jobs_tree.column('Interval (min)', width=100)
        self.jobs_tree.column('On Time (s)', width=100)
        self.jobs_tree.column('Stato', width=80)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.jobs_tree.yview)
        self.jobs_tree.configure(yscroll=scrollbar.set)

        self.jobs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Frame per bottoni gestione
        btn_frame = self._card(parent, "Gestione Job")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="➕ Nuovo Job", command=self.add_job_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ Elimina Job", command=self.delete_job).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✏️ Modifica Job", command=self.edit_job_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Ricarica Lista", command=self.refresh_jobs_list).pack(side=tk.LEFT, padx=5)

        # Frame per attivazione/disattivazione
        toggle_frame = self._card(parent, "Controllo Job")
        toggle_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(toggle_frame, text="✅ Attiva Job", style='Accent.TButton',
                   command=self.toggle_job_on).pack(side=tk.LEFT, padx=5)
        ttk.Button(toggle_frame, text="❌ Disattiva Job", style='Stop.TButton',
                   command=self.toggle_job_off).pack(side=tk.LEFT, padx=5)

        self._bind_mousewheel(parent, jobs_canvas)

    def create_output_tab(self, parent):
        """Tab per visualizzare gli output del terminale e log"""
        parent, output_canvas = self._make_scrollable(parent)

        # Frame superiore con bottoni
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="🔄 Aggiorna", command=self.refresh_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Pulisci Output", command=self.clear_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📂 Apri File Log", command=self.open_log_file).pack(side=tk.LEFT, padx=5)

        # Info sul file log
        info_frame = tk.Frame(parent, bg=self.COL_BG)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(info_frame, text="File log:", bg=self.COL_BG, fg=self.COL_FAINT,
                 font=(self.FONT_UI, 9, 'bold')).pack(side=tk.LEFT)
        self.log_file_label = tk.Label(info_frame, text="", bg=self.COL_BG,
                                       fg=self.COL_PRIMARY, font=(self.FONT_MONO, 9))
        self.log_file_label.pack(side=tk.LEFT, padx=5)

        # Sezione dedicata ai soli errori di lettura delle sonde.
        # Sta prima dell'output completo perche' e' cio' che si va a
        # guardare per primo quando una misura non arriva: nel flusso del
        # log generale un errore si perde fra centinaia di righe INFO.
        errors_frame = self._card(parent, "Errori di lettura")
        errors_frame.pack(fill=tk.X, padx=10, pady=10)

        err_btns = tk.Frame(errors_frame, bg=self.COL_CARD)
        err_btns.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(err_btns, text="🔄 Aggiorna errori",
                   command=self.refresh_errors).pack(side=tk.LEFT, padx=5)
        ttk.Button(err_btns, text="🧹 Pulisci",
                   command=self.clear_errors).pack(side=tk.LEFT, padx=5)
        self.errors_count_label = tk.Label(err_btns, text="", bg=self.COL_CARD,
                                           fg=self.COL_FAINT, font=(self.FONT_UI, 9))
        self.errors_count_label.pack(side=tk.LEFT, padx=10)

        err_scroll = ttk.Scrollbar(errors_frame)
        err_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.errors_text = tk.Text(errors_frame, yscrollcommand=err_scroll.set,
                                   wrap=tk.WORD, font=(self.FONT_MONO, 9), height=8,
                                   bg="#16211c", fg="#dfe6e2", insertbackground="white",
                                   relief=tk.FLAT, borderwidth=0, padx=10, pady=8)
        self.errors_text.pack(fill=tk.BOTH, expand=True)
        err_scroll.config(command=self.errors_text.yview)
        self.errors_text.tag_config('error', foreground='#ff8a80')
        self.errors_text.tag_config('vuoto', foreground='#8a968f')

        # Frame per il testo (output)
        text_frame = self._card(parent, "Output Terminale")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Text widget con scrollbar
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.output_text = tk.Text(text_frame, yscrollcommand=scrollbar.set,
                                   wrap=tk.WORD, font=(self.FONT_MONO, 9), height=20,
                                   bg="#16211c", fg="#dfe6e2", insertbackground="white",
                                   relief=tk.FLAT, borderwidth=0, padx=10, pady=8)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.output_text.yview)

        # Configura i tag per i colori
        self.output_text.tag_config('info', foreground='#7fd6a2')
        self.output_text.tag_config('warning', foreground='#f0a75a')
        self.output_text.tag_config('error', foreground='#ff8a80')
        self.output_text.tag_config('debug', foreground='#8a968f')

        # Aggiorna il label con il file log
        self.update_log_file_label()

        # Carica il contenuto iniziale
        self.refresh_output()
        self.refresh_errors()

        # NB: la rotella non viene agganciata al Text dell'output — li' deve
        # scorrere il log, non la pagina. Il resto della scheda sì.
        self._bind_mousewheel(btn_frame, output_canvas)
        self._bind_mousewheel(info_frame, output_canvas)

    def refresh_errors(self):
        """
        Riempie la sezione "Errori di lettura" con gli errori registrati.

        La sorgente e' ErrorRecorder, non il file di log: contiene solo i
        fallimenti delle sonde, gia' con la frase che spiega cosa controllare.
        """
        errori = self.ah.errors.recent()

        self.errors_text.config(state=tk.NORMAL)
        self.errors_text.delete(1.0, tk.END)

        if not errori:
            self.errors_text.insert(tk.END, "Nessun errore di lettura registrato.\n", 'vuoto')
        else:
            for e in errori:
                self.errors_text.insert(
                    tk.END, f"[{e['timestamp']}] {e['source']} — {e['message']}\n", 'error')
            self.errors_text.see(tk.END)

        self.errors_text.config(state=tk.DISABLED)
        if not errori:
            testo = "nessun errore"
        else:
            testo = f"{len(errori)} errore registrato" if len(errori) == 1 \
                else f"{len(errori)} errori registrati"
        self.errors_count_label.config(text=testo)

    def clear_errors(self):
        """
        Svuota l'elenco degli errori mostrato.

        Pulisce solo la lista in memoria: i file ERRORS_*.txt su disco
        restano, perche' sono quelli che finiscono nell'upload giornaliero.
        """
        self.ah.errors.clear()
        self.refresh_errors()

    def refresh_jobs_list(self):
        """Aggiorna la lista dei job nel Treeview"""
        # Pulisci il treeview
        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)

        # Aggiungi i job dalla configurazione
        gpio_pins = self.config.get('gpio_pins', [])
        for idx, job in enumerate(gpio_pins):
            name = job.get('name', f'Job {idx}')
            pin = job.get('pin', 'N/A')
            interval = job.get('interval', 'N/A')
            on_time = job.get('on_time', 'N/A')
            stato = self.active_jobs.get(name, 'Inattivo')

            self.jobs_tree.insert('', 'end', text=str(idx), values=(
                name, pin, interval, on_time, stato
            ))

    def add_job_window(self):
        """Apre una finestra per aggiungere un nuovo job"""
        add_window = tk.Toplevel(self.root)
        add_window.title("Aggiungi Nuovo Job")
        add_window.geometry("400x300")

        ttk.Label(add_window, text="Nome:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        name_var = tk.StringVar()
        ttk.Entry(add_window, textvariable=name_var, width=30).grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(add_window, text="Pin GPIO:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        pin_var = tk.StringVar()
        ttk.Entry(add_window, textvariable=pin_var, width=30).grid(row=1, column=1, padx=10, pady=10)

        ttk.Label(add_window, text="Intervallo (minuti):").grid(row=2, column=0, sticky=tk.W, padx=10, pady=10)
        interval_var = tk.StringVar()
        ttk.Entry(add_window, textvariable=interval_var, width=30).grid(row=2, column=1, padx=10, pady=10)

        ttk.Label(add_window, text="Tempo Accensione (s):").grid(row=3, column=0, sticky=tk.W, padx=10, pady=10)
        on_time_var = tk.StringVar()
        ttk.Entry(add_window, textvariable=on_time_var, width=30).grid(row=3, column=1, padx=10, pady=10)

        def save_job():
            try:
                name = name_var.get().strip()
                pin = int(pin_var.get().strip())
                interval = int(interval_var.get().strip())
                on_time = int(on_time_var.get().strip())

                if not name:
                    messagebox.showwarning("Avviso", "Inserire un nome per il job")
                    return

                # Aggiungi il job
                new_job = {
                    'name': name,
                    'pin': pin,
                    'interval': interval,
                    'on_time': on_time
                }

                self.config['gpio_pins'].append(new_job)
                self.save_config()
                self.refresh_jobs_list()
                add_window.destroy()
                messagebox.showinfo("Successo", f"Job '{name}' aggiunto con successo!")

            except ValueError:
                messagebox.showerror("Errore", "Inserire valori numerici validi per pin, intervallo e on_time")

        ttk.Button(add_window, text="Salva Job", command=save_job).grid(row=4, column=0, columnspan=2, pady=20)

    def delete_job(self):
        """Elimina il job selezionato"""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da eliminare")
            return

        item = selected[0]
        idx = int(self.jobs_tree.item(item, 'text'))

        if messagebox.askyesno("Conferma", "Sei sicuro di voler eliminare questo job?"):
            self.config['gpio_pins'].pop(idx)
            self.save_config()
            self.refresh_jobs_list()
            messagebox.showinfo("Successo", "Job eliminato!")

    def edit_job_window(self):
        """Apre una finestra per modificare un job"""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da modificare")
            return

        item = selected[0]
        idx = int(self.jobs_tree.item(item, 'text'))
        job = self.config['gpio_pins'][idx]

        edit_window = tk.Toplevel(self.root)
        edit_window.title("Modifica Job")
        edit_window.geometry("400x300")

        ttk.Label(edit_window, text="Nome:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        name_var = tk.StringVar(value=job.get('name', ''))
        ttk.Entry(edit_window, textvariable=name_var, width=30).grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(edit_window, text="Pin GPIO:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        pin_var = tk.StringVar(value=str(job.get('pin', '')))
        ttk.Entry(edit_window, textvariable=pin_var, width=30).grid(row=1, column=1, padx=10, pady=10)

        ttk.Label(edit_window, text="Intervallo (minuti):").grid(row=2, column=0, sticky=tk.W, padx=10, pady=10)
        interval_var = tk.StringVar(value=str(job.get('interval', '')))
        ttk.Entry(edit_window, textvariable=interval_var, width=30).grid(row=2, column=1, padx=10, pady=10)

        ttk.Label(edit_window, text="Tempo Accensione (s):").grid(row=3, column=0, sticky=tk.W, padx=10, pady=10)
        on_time_var = tk.StringVar(value=str(job.get('on_time', '')))
        ttk.Entry(edit_window, textvariable=on_time_var, width=30).grid(row=3, column=1, padx=10, pady=10)

        def save_changes():
            try:
                job['name'] = name_var.get().strip()
                job['pin'] = int(pin_var.get().strip())
                job['interval'] = int(interval_var.get().strip())
                job['on_time'] = int(on_time_var.get().strip())

                self.save_config()
                self.refresh_jobs_list()
                edit_window.destroy()
                messagebox.showinfo("Successo", "Job modificato!")

            except ValueError:
                messagebox.showerror("Errore", "Inserire valori numerici validi")

        ttk.Button(edit_window, text="Salva Modifiche", command=save_changes).grid(row=4, column=0, columnspan=2, pady=20)

    # ------------------------------------------------------------------
    # JOB activation / deactivation (wrapper sottili → JobsManager)
    # ------------------------------------------------------------------
    def toggle_job_on(self):
        """Attiva il job selezionato tramite il JobsManager."""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da attivare")
            return

        item = selected[0]
        name = str(self.jobs_tree.item(item, 'values')[0])

        if name == 'AEROPONICS':
            started = self.ah.jobs.start_aeroponics()
        elif name == 'IDROPONICS':
            started = self.ah.jobs.start_idroponics()
        else:
            try:
                pin = int(self.jobs_tree.item(item, 'values')[1])
                interval = int(self.jobs_tree.item(item, 'values')[2])
                on_time = int(self.jobs_tree.item(item, 'values')[3])
            except (ValueError, IndexError):
                messagebox.showwarning("Avviso", f"Il job '{name}' non ha parametri validi per l'attivazione.")
                return
            started = self.ah.jobs.start_general(pin, on_time, interval, name)

        if not started:
            messagebox.showwarning("Avviso", f"Il job {name} è già in esecuzione!")
            return

        # UI update
        self.active_jobs[name] = 'Attivo'
        self.refresh_jobs_list()

    def toggle_job_off(self):
        """Disattiva il job selezionato (stop immediato) tramite il JobsManager."""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da disattivare")
            return

        item = selected[0]
        name = self.jobs_tree.item(item, 'values')[0]

        if name == 'AEROPONICS':
            self.ah.jobs.deactivate_aeroponics()
        elif name == 'IDROPONICS':
            self.ah.jobs.deactivate_idroponics()
        else:
            self.ah.jobs.deactivate_general(name)

        # UI update
        self.active_jobs[name] = 'Inattivo'
        self.refresh_jobs_list()

    # ------------------------------------------------------------------
    # Salvataggio / ricarica configurazione
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Configurazione: card "Schede Arduino"
    # ------------------------------------------------------------------
    def _build_arduino_config_card(self, parent):
        """
        Card di configurazione delle schede Arduino.

        A differenza delle altre card, che hanno campi fissi, questa e'
        ricostruita ogni volta: le porte USB disponibili si scoprono solo a
        run-time, e le schede possono essere piu' di una.

        L'elenco dei sensori e dei relativi comandi arriva da
        arduino_link.SENSOR_SPECS: i nomi dei comandi sono FISSI (li conosce
        solo lo sketch) e vengono mostrati in sola lettura, mentre i pin sono
        modificabili, perche' sono l'unica cosa che cambia col cablaggio.
        """
        card = self._card(parent, "Schede Arduino — porte USB e pin delle sonde")
        card.pack(fill=tk.X, padx=10, pady=10)

        a = self.config.get('arduino', {}) or {}

        top = tk.Frame(card, bg=self.COL_CARD)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(top, text="🔍 Rileva schede",
                   command=self.detect_arduino_boards).pack(side=tk.LEFT, padx=5)

        tk.Label(top, text="Baudrate:", bg=self.COL_CARD,
                 fg=self.COL_TEXT).pack(side=tk.LEFT, padx=(20, 4))
        self.arduino_baudrate_var = tk.StringVar(value=str(a.get('baudrate', 9600)))
        ttk.Entry(top, textvariable=self.arduino_baudrate_var, width=8).pack(side=tk.LEFT)

        tk.Label(top, text="Timeout (s):", bg=self.COL_CARD,
                 fg=self.COL_TEXT).pack(side=tk.LEFT, padx=(20, 4))
        self.arduino_timeout_var = tk.StringVar(value=str(a.get('timeout', 15)))
        ttk.Entry(top, textvariable=self.arduino_timeout_var, width=8).pack(side=tk.LEFT)

        # Contenitore delle schede: svuotato e ricostruito ad ogni scansione
        self.arduino_boards_frame = tk.Frame(card, bg=self.COL_CARD)
        self.arduino_boards_frame.pack(fill=tk.X)

        self._render_arduino_boards()

    def _arduino_boards_to_show(self):
        """
        Elenco delle schede da mostrare: quelle configurate piu' quelle rilevate.

        Una scheda gia' configurata ma non collegata in questo momento resta
        in elenco (segnalata come non collegata): toglierla dalla vista
        significherebbe perderne la configurazione al primo salvataggio.

        :return: lista di dict {'port', 'name', 'enabled', 'sensors', 'description', 'collegata'}
        """
        rilevate = {}
        for porta in getattr(self, '_arduino_detected', []):
            rilevate[porta['device']] = porta.get('description', '')

        schede = []
        configurate = set()
        for voce in (self.config.get('arduino', {}) or {}).get('boards', []) or []:
            porta = voce.get('port', '')
            configurate.add(porta)
            schede.append({
                'port': porta,
                'name': voce.get('name', porta),
                'enabled': voce.get('enabled', True),
                'sensors': voce.get('sensors', {}) or {},
                'description': rilevate.get(porta, ''),
                'collegata': porta in rilevate,
            })

        # Porte rilevate ma non ancora configurate: si offrono da spuntare
        for i, (porta, descrizione) in enumerate(sorted(rilevate.items()), start=1):
            if porta in configurate:
                continue
            schede.append({
                'port': porta,
                'name': f"Board{len(schede) + i}",
                'enabled': False,
                'sensors': {},
                'description': descrizione,
                'collegata': True,
            })

        return schede

    def _render_arduino_boards(self):
        """Ridisegna il blocco di ogni scheda e ricrea le variabili collegate."""
        for widget in self.arduino_boards_frame.winfo_children():
            widget.destroy()

        # Struttura da cui save_config_changes ricostruisce arduino.boards:
        # i widget nascono dalla scansione, quindi non esistono StringVar
        # fisse come nelle altre card.
        self.arduino_board_vars = []

        schede = self._arduino_boards_to_show()
        if not schede:
            tk.Label(self.arduino_boards_frame,
                     text="Nessuna scheda configurata. Premi «Rileva schede» con "
                          "l'Arduino collegato via USB.",
                     bg=self.COL_CARD, fg=self.COL_FAINT).pack(anchor=tk.W, pady=6)
            return

        for scheda in schede:
            self._render_one_board(scheda)

    def _render_one_board(self, scheda):
        """Disegna il blocco di una singola scheda, con le righe dei sensori."""
        blocco = tk.Frame(self.arduino_boards_frame, bg=self.COL_CARD,
                          highlightbackground=self.COL_BORDER, highlightthickness=1)
        blocco.pack(fill=tk.X, pady=6)

        intestazione = tk.Frame(blocco, bg=self.COL_CARD)
        intestazione.pack(fill=tk.X, padx=8, pady=(6, 2))

        enabled_var = tk.BooleanVar(value=scheda['enabled'])
        ttk.Checkbutton(intestazione, text="Usa questa scheda",
                        variable=enabled_var).pack(side=tk.LEFT)

        name_var = tk.StringVar(value=scheda['name'])
        tk.Label(intestazione, text="Nome:", bg=self.COL_CARD,
                 fg=self.COL_TEXT).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(intestazione, textvariable=name_var, width=12).pack(side=tk.LEFT)

        port_var = tk.StringVar(value=scheda['port'])
        tk.Label(intestazione, text="Porta:", bg=self.COL_CARD,
                 fg=self.COL_TEXT).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(intestazione, textvariable=port_var, width=18).pack(side=tk.LEFT)

        if scheda['collegata']:
            stato, colore = "● collegata", self.COL_OK
        else:
            stato, colore = "○ non collegata", self.COL_WARN
        tk.Label(intestazione, text=stato, bg=self.COL_CARD, fg=colore,
                 font=(self.FONT_UI, 9, 'bold')).pack(side=tk.LEFT, padx=(16, 0))

        if scheda['description']:
            tk.Label(blocco, text=scheda['description'], bg=self.COL_CARD,
                     fg=self.COL_FAINT, font=(self.FONT_UI, 9)).pack(anchor=tk.W, padx=8)

        sensori_vars = {}
        for key in arduino_link.SENSOR_KEYS:
            sensori_vars[key] = self._render_sensor_row(blocco, scheda, key, port_var)

        self.arduino_board_vars.append({
            'enabled': enabled_var,
            'name': name_var,
            'port': port_var,
            'sensors': sensori_vars,
        })

    def _render_sensor_row(self, blocco, scheda, key, port_var):
        """
        Una riga per sensore: comando (fisso), pin (modificabili), anteprima.

        :return: dict {'enabled': BooleanVar, 'args': {chiave: StringVar}}
        """
        spec = arduino_link.SENSOR_SPECS[key]
        cfg = scheda['sensors'].get(key, {}) or {}

        riga = tk.Frame(blocco, bg=self.COL_CARD)
        riga.pack(fill=tk.X, padx=8, pady=2)

        collegato_var = tk.BooleanVar(value=key in scheda['sensors'])
        ttk.Checkbutton(riga, text=key, variable=collegato_var,
                        width=10).pack(side=tk.LEFT)

        # Il nome del comando lo decide lo sketch, non l'utente: si mostra
        # come etichetta e non come campo, per non lasciar credere che
        # cambiarlo abbia un effetto.
        tk.Label(riga, text=spec['command'], bg=self.COL_CARD, fg=self.COL_PRIMARY,
                 font=(self.FONT_MONO, 9), width=10).pack(side=tk.LEFT, padx=(0, 8))

        args_vars = {}
        for chiave, etichetta, default in spec['args']:
            tk.Label(riga, text=f"{etichetta}:", bg=self.COL_CARD,
                     fg=self.COL_TEXT).pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value=str(cfg.get(chiave, default)))
            ttk.Entry(riga, textvariable=var, width=6).pack(side=tk.LEFT)
            args_vars[chiave] = var

        anteprima = tk.Label(riga, text="", bg=self.COL_CARD, fg=self.COL_FAINT,
                             font=(self.FONT_MONO, 9))
        anteprima.pack(side=tk.LEFT, padx=(16, 0))

        def aggiorna_anteprima(*_):
            """Mostra il comando che verra' realmente inviato all'Arduino."""
            valori = ','.join(v.get().strip() for _c, v in args_vars.items())
            anteprima.config(text=f"→ {spec['command']},{valori}" if valori
                             else f"→ {spec['command']}")

        for var in args_vars.values():
            var.trace_add('write', aggiorna_anteprima)
        aggiorna_anteprima()

        ttk.Button(riga, text="🔌 Prova",
                   command=lambda k=key: self.test_arduino_sensor(k)).pack(side=tk.RIGHT, padx=5)

        return {'enabled': collegato_var, 'args': args_vars}

    def detect_arduino_boards(self):
        """Cerca le porte USB collegate e ridisegna l'elenco delle schede."""
        try:
            self._arduino_detected = arduino_link.list_serial_ports()
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile elencare le porte USB: {e}")
            return

        self._render_arduino_boards()

        if not self._arduino_detected:
            messagebox.showwarning(
                "Avviso", "Nessuna porta USB rilevata.\n"
                          "Verifica che l'Arduino sia collegato e acceso.")
        else:
            elenco = "\n".join(f"{p['device']} — {p['description']}"
                                for p in self._arduino_detected)
            messagebox.showinfo("Schede rilevate", elenco)

    def test_arduino_sensor(self, sensor_key):
        """
        Legge subito un sensore con la configurazione attualmente salvata.

        Serve a verificare i pin senza uscire dalla schermata; usa la
        configurazione gia' applicata, quindi va premuto DOPO «Salva».
        """
        try:
            valori = self.ah.arduino.read_named(sensor_key)
        except Exception as e:
            messagebox.showerror(
                "Lettura fallita",
                f"{arduino_link.sensor_label(sensor_key)}:\n{e}\n\n"
                "Se hai appena modificato i pin, salva prima la configurazione.")
            return

        spec = arduino_link.SENSOR_SPECS[sensor_key]
        righe = [f"{nome}: {valori[nome]} {unita}".strip()
                 for nome, unita in spec['values']]
        messagebox.showinfo(f"Lettura {sensor_key}", "\n".join(righe))

    def _collect_arduino_boards(self):
        """
        Ricostruisce la lista arduino.boards dai widget della card.

        Le schede senza porta vengono scartate; per ogni scheda si tengono
        solo i sensori spuntati, con i loro pin convertiti nel tipo giusto
        (int per i pin digitali e l'indirizzo I2C, stringa per 'A0').
        """
        boards = []
        for board_vars in getattr(self, 'arduino_board_vars', []):
            porta = board_vars['port'].get().strip()
            if not porta:
                continue

            sensors = {}
            for key, sensore in board_vars['sensors'].items():
                if not sensore['enabled'].get():
                    continue
                args = {}
                for chiave, var in sensore['args'].items():
                    grezzo = var.get().strip()
                    if not grezzo:
                        continue
                    # 'A0' resta una stringa, '2' e '100' diventano numeri:
                    # e' cosi' che li scrive a mano chi edita config.yaml.
                    try:
                        args[chiave] = int(grezzo)
                    except ValueError:
                        args[chiave] = grezzo
                sensors[key] = args

            boards.append({
                'name': board_vars['name'].get().strip() or porta,
                'port': porta,
                'enabled': bool(board_vars['enabled'].get()),
                'sensors': sensors,
            })
        return boards

    def save_config_changes(self):
        """Salva i cambiamenti della configurazione"""
        try:
            self.config['T_var']['Topt'] = float(self.t_opt_var.get())
            self.config['T_var']['Hopt'] = float(self.h_opt_var.get())
            self.config['dht22']['pin'] = int(self.dht_pin_var.get())
            self.config['dht22']['read_interval'] = int(self.dht_interval_var.get())
            self.config['log']['directory'] = self.log_dir_var.get()
            self.config['log']['filename'] = self.log_file_var.get()
            self.config['log']['level'] = self.log_level_var.get()
            self.config['config_reload_interval'] = int(self.reload_interval_var.get())
            self.config.setdefault('ir_control', {})
            self.config['ir_control']['tx_pin'] = int(self.ir_tx_pin_var.get())
            self.config['ir_control']['file_ac_name'] = self.ir_file_var.get()
            self.config['ir_control']['time_max_on'] = float(self.ir_time_max_var.get())
            self.config['ir_control']['control_time'] = float(self.ir_time_sep_var.get())
            self.config['ir_control']['T_max'] = float(self.ir_T_max_var.get())
            self.config['ir_control']['H_max'] = float(self.ir_H_max_var.get())

            # Sezione schede Arduino
            self.config.setdefault('arduino', {})
            self.config['arduino']['baudrate'] = int(self.arduino_baudrate_var.get())
            self.config['arduino']['timeout'] = int(self.arduino_timeout_var.get())
            self.config['arduino']['boards'] = self._collect_arduino_boards()

            # Sezione acqua (pH / EC)
            self.config.setdefault('water', {})
            self.config['water']['ph_read_interval'] = int(self.water_ph_interval_var.get())
            self.config['water']['ec_read_interval'] = int(self.water_ec_interval_var.get())
            self.config['water']['ph_min'] = float(self.water_ph_min_var.get())
            self.config['water']['ph_max'] = float(self.water_ph_max_var.get())
            self.config['water']['ec_min'] = float(self.water_ec_min_var.get())
            self.config['water']['ec_max'] = float(self.water_ec_max_var.get())
            self.config['water']['decimals'] = int(self.water_decimals_var.get())
            self.config['water']['history_len'] = int(self.water_history_var.get())
            self.config['water']['saving_dir'] = self.water_dir_var.get()

            # Sezione serbatoio (tank)
            self.config.setdefault('tank', {})
            self.config['tank']['tank_height_cm'] = float(self.tank_height_var.get())
            self.config['tank']['sensor_offset_cm'] = float(self.tank_offset_var.get())
            self.config['tank']['tank_area_cm2'] = float(self.tank_area_var.get())
            self.config['tank']['water_low_threshold_l'] = float(self.tank_low_var.get())
            self.config['tank']['read_interval'] = int(self.tank_interval_var.get())
            self.config['tank']['n_samples'] = int(self.tank_nsamples_var.get())

            # Sezione spettrometro (spectro)
            self.config.setdefault('spectro', {})
            self.config['spectro']['read_interval'] = int(self.spectro_interval_var.get())
            self.config['spectro']['history_len'] = int(self.spectro_history_var.get())
            self.config['spectro']['saving_dir'] = self.spectro_dir_var.get()

            # Sezione crescita (plant_growth)
            self.config.setdefault('plant_growth', {})
            self.config['plant_growth']['reference_height_cm'] = float(self.growth_ref_var.get())
            self.config['plant_growth']['read_interval_days'] = float(self.growth_interval_var.get())
            self.config['plant_growth']['n_samples'] = int(self.growth_nsamples_var.get())
            self.config['plant_growth']['decimals'] = int(self.growth_decimals_var.get())
            self.config['plant_growth']['history_len'] = int(self.growth_history_var.get())
            self.config['plant_growth']['saving_dir'] = self.growth_dir_var.get()

            # Sezione camera
            self.config.setdefault('camera', {})
            self.config['camera']['separation_hours'] = int(self.camera_hours_var.get())
            self.config['camera']['saving_dir'] = self.camera_dir_var.get()

            # Sezione elaborazione giornaliera (Daily_Data)
            self.config.setdefault('Daily_Data', {})
            self.config['Daily_Data']['th_data_dir'] = self.daily_th_dir_var.get()
            self.config['Daily_Data']['plot_output_dir'] = self.daily_plot_dir_var.get()

            self.save_config()

            # I manager lavorano sul dizionario di aeroHelper, che e' un altro
            # oggetto: senza questo, porte e pin appena salvati resterebbero
            # ignorati fino al riavvio del programma.
            self.ah.configs['arduino'] = self.config['arduino']
            self.ah.configs['water'] = self.config['water']
            self.ah.configs['tank'] = self.config['tank']
            self.ah.configs['plant_growth'] = self.config['plant_growth']
            self.ah.arduino.reload()
        except ValueError:
            messagebox.showerror("Errore", "Inserire valori validi. Verificare i numeri.")

    def reload_config_tab(self):
        """Ricarica la configurazione dalla tab"""
        self.config = self.load_config()
        self.t_opt_var.set(str(self.config.get('T_var', {}).get('Topt', 18)))
        self.h_opt_var.set(str(self.config.get('T_var', {}).get('Hopt', 65)))
        self.dht_pin_var.set(str(self.config.get('dht22', {}).get('pin', 27)))
        self.dht_interval_var.set(str(self.config.get('dht22', {}).get('read_interval', 5)))
        self.log_dir_var.set(self.config.get('log', {}).get('directory', ''))
        self.log_file_var.set(self.config.get('log', {}).get('filename', ''))
        self.log_level_var.set(self.config.get('log', {}).get('level', 'INFO'))
        self.reload_interval_var.set(str(self.config.get('config_reload_interval', 4)))
        self.ir_tx_pin_var.set(str(self.config.get('ir_control', {}).get('tx_pin', 21)))
        self.ir_file_var.set(self.config.get('ir_control', {}).get('file_ac_name', 'ac_controller.json'))
        self.ir_time_max_var.set(str(self.config.get('ir_control', {}).get('time_max_on', 30)))
        self.ir_time_sep_var.set(str(self.config.get('ir_control', {}).get('control_time', 30)))
        self.ir_T_max_var.set(str(self.config.get('ir_control', {}).get('T_max', 25.0)))
        self.ir_H_max_var.set(str(self.config.get('ir_control', {}).get('H_max', 65.0)))

        a = self.config.get('arduino', {})
        self.arduino_baudrate_var.set(str(a.get('baudrate', 9600)))
        self.arduino_timeout_var.set(str(a.get('timeout', 15)))
        # La card delle schede e' costruita dai dati: si ridisegna invece di
        # aggiornare variabili che potrebbero non esistere piu'.
        self._render_arduino_boards()

        w = self.config.get('water', {})
        self.water_ph_interval_var.set(str(w.get('ph_read_interval', 1800)))
        self.water_ec_interval_var.set(str(w.get('ec_read_interval', 1800)))
        self.water_ph_min_var.set(str(w.get('ph_min', 5.5)))
        self.water_ph_max_var.set(str(w.get('ph_max', 6.5)))
        self.water_ec_min_var.set(str(w.get('ec_min', 800)))
        self.water_ec_max_var.set(str(w.get('ec_max', 2000)))
        self.water_decimals_var.set(str(w.get('decimals', 2)))
        self.water_history_var.set(str(w.get('history_len', 30)))
        self.water_dir_var.set(w.get('saving_dir', '/home/fishnplants/Desktop/data/WATER/'))

        tank = self.config.get('tank', {})
        self.tank_height_var.set(str(tank.get('tank_height_cm', 30.0)))
        self.tank_offset_var.set(str(tank.get('sensor_offset_cm', 2.0)))
        self.tank_area_var.set(str(tank.get('tank_area_cm2', 900.0)))
        self.tank_low_var.set(str(tank.get('water_low_threshold_l', 3.0)))
        self.tank_interval_var.set(str(tank.get('read_interval', 300)))
        self.tank_nsamples_var.set(str(tank.get('n_samples', 5)))

        sp = self.config.get('spectro', {})
        self.spectro_interval_var.set(str(sp.get('read_interval', 3600)))
        self.spectro_history_var.set(str(sp.get('history_len', 10)))
        self.spectro_dir_var.set(sp.get('saving_dir', '/home/fishnplants/Desktop/data/SPECTRO/'))

        g = self.config.get('plant_growth', {})
        self.growth_ref_var.set(str(g.get('reference_height_cm', 70.0)))
        self.growth_interval_var.set(str(g.get('read_interval_days', 1)))
        self.growth_nsamples_var.set(str(g.get('n_samples', 3)))
        self.growth_decimals_var.set(str(g.get('decimals', 1)))
        self.growth_history_var.set(str(g.get('history_len', 30)))
        self.growth_dir_var.set(g.get('saving_dir', '/home/fishnplants/Desktop/data/GROWTH/'))

        cam = self.config.get('camera', {})
        self.camera_hours_var.set(str(cam.get('separation_hours', 2)))
        self.camera_dir_var.set(cam.get('saving_dir', '/home/fishnplants/Desktop/data/IMG/'))

        dd = self.config.get('Daily_Data', {})
        self.daily_th_dir_var.set(dd.get('th_data_dir', '/home/fishnplants/Desktop/data/TH/'))
        self.daily_plot_dir_var.set(dd.get('plot_output_dir', '/home/fishnplants/Desktop/data/PLOT/'))

        messagebox.showinfo("Successo", "Configurazione ricaricata!")

    def update_log_file_label(self):
        """Aggiorna il label con il percorso del file log"""
        log_dir = self.config.get('log', {}).get('directory', '')
        log_file = self.config.get('log', {}).get('filename', '')
        full_path = os.path.join(log_dir, log_file) if log_dir and log_file else 'Non configurato'
        self.log_file_label.config(text=full_path)

    def get_log_file_path(self):
        """Ritorna il percorso completo del file log"""
        log_dir = self.config.get('log', {}).get('directory', '')
        log_file = self.config.get('log', {}).get('filename', '')
        return os.path.join(log_dir, log_file) if log_dir and log_file else None

    def refresh_output(self):
        """Carica e visualizza il contenuto del file di log"""
        try:
            log_path = self.get_log_file_path()

            if not log_path or not os.path.exists(log_path):
                self.output_text.config(state=tk.NORMAL)
                self.output_text.delete(1.0, tk.END)
                self.output_text.insert(tk.END, "❌ File di log non trovato o non configurato.\n", 'error')
                self.output_text.insert(tk.END, f"Percorso atteso: {log_path}", 'warning')
                self.output_text.config(state=tk.DISABLED)
                return

            # Leggi il file log
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Visualizza il contenuto
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)

            # Colora le linee in base al livello di log
            lines = content.split('\n')
            for line in lines:
                if '[ERROR]' in line or '[CRITICAL]' in line:
                    self.output_text.insert(tk.END, line + '\n', 'error')
                elif '[WARNING]' in line:
                    self.output_text.insert(tk.END, line + '\n', 'warning')
                elif '[DEBUG]' in line:
                    self.output_text.insert(tk.END, line + '\n', 'debug')
                elif '[INFO]' in line:
                    self.output_text.insert(tk.END, line + '\n', 'info')
                else:
                    self.output_text.insert(tk.END, line + '\n')

            # Scroll verso il fondo
            self.output_text.see(tk.END)
            self.output_text.config(state=tk.DISABLED)

        except Exception as e:
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, f"❌ Errore nel caricamento del log:\n{str(e)}", 'error')
            self.output_text.config(state=tk.DISABLED)

    def clear_output(self):
        """Pulisce il contenuto visualizzato (non il file vero)"""
        if messagebox.askyesno("Conferma", "Sei sicuro di voler pulire l'output visualizzato?"):
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, "Output pulito.\n")
            self.output_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Tab: Ambient (wrapper sottili → AmbientManager)
    # ------------------------------------------------------------------
    def create_ambient_tab(self, parent):
        """Tab per monitorare i dati di temperatura, umidità e VPD"""
        parent, ambient_canvas = self._make_scrollable(parent)

        # Frame superiore con bottoni
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_ambient_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_ambient_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📊 Leggi Adesso", command=self.read_ambient_now).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = self._card(parent, "AMBIENT")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Crea un frame interno per centrare il contenuto
        inner_frame = ttk.Frame(main_frame)
        inner_frame.pack(expand=True)

        # Temperatura
        temp_frame = ttk.Frame(inner_frame)
        temp_frame.pack(pady=10)
        ttk.Label(temp_frame, text="TEMPERATURA", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.ambient_temp_label = ttk.Label(temp_frame, text="-- °C", font=(self.FONT_MONO, 30), foreground=self.COL_BLUE)
        self.ambient_temp_label.pack()

        # Umidità
        humid_frame = ttk.Frame(inner_frame)
        humid_frame.pack(pady=10)
        ttk.Label(humid_frame, text="UMIDITÀ", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.ambient_humid_label = ttk.Label(humid_frame, text="-- %", font=(self.FONT_MONO, 30), foreground=self.COL_WARN)
        self.ambient_humid_label.pack()

        # VPD
        vpd_frame = ttk.Frame(inner_frame)
        vpd_frame.pack(pady=10)
        ttk.Label(vpd_frame, text="VPD", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.ambient_vpd_label = ttk.Label(vpd_frame, text="-- kPa", font=(self.FONT_MONO, 30), foreground=self.COL_PRIMARY)
        self.ambient_vpd_label.pack()

        # Timestamp della lettura
        self.ambient_timestamp_label = ttk.Label(inner_frame, text="Ultimo aggiornamento: --",
                                                 font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.ambient_timestamp_label.pack(pady=20)

        # --- Sezione elaborazione giornaliera (DailyTHManager) ---
        self._build_daily_section(parent)

        # Rotella del mouse: da fare per ultimo, quando i widget esistono tutti
        self._bind_mousewheel(parent, ambient_canvas)

    # ------------------------------------------------------------------
    # Ambiente: sezione elaborazione giornaliera (T/H/VPD del giorno prima)
    # ------------------------------------------------------------------
    def _build_daily_section(self, parent):
        """
        Blocco statistiche + plot giornaliero, sotto i valori istantanei.

        I valori vengono da DailyTHManager.last_stats, che il manager rilegge
        elaborando il file del giorno precedente: la sezione e' popolata appena
        si preme 'Attiva Daily', senza aspettare la mezzanotte.
        """
        daily_frame = self._card(parent, "Elaborazione giornaliera (T/H/VPD)")
        daily_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Controlli
        btn_frame = ttk.Frame(daily_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(btn_frame, text="▶️ Attiva Daily", style='Accent.TButton',
                   command=self.start_daily_processing).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Daily", style='Stop.TButton',
                   command=self.stop_daily_processing).pack(side=tk.LEFT, padx=5)

        self.daily_date_label = ttk.Label(daily_frame, text="Nessuna elaborazione eseguita",
                                          font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.daily_date_label.pack(anchor=tk.W, pady=(0, 8))

        # Tabella statistiche: righe T/H/VPD, colonne max/min/media
        stats_frame = ttk.Frame(daily_frame)
        stats_frame.pack(fill=tk.X, pady=(0, 12))
        for c in range(4):
            stats_frame.columnconfigure(c, weight=1, uniform='daily')

        for col, testo in enumerate(("", "Massimo", "Minimo", "Media"), start=0):
            ttk.Label(stats_frame, text=testo, font=(self.FONT_UI, 11, 'bold'),
                      foreground=self.COL_PRIMARY).grid(row=0, column=col, pady=4)

        # Chiavi come le restituisce compute_statistics (daily_th_processor.py)
        righe = (
            ("Temperatura (°C)", 'max_T', 'min_T', 'avg_temperature', self.COL_BLUE),
            ("Umidità (%)", 'max_H', 'min_H', 'avg_humidity', self.COL_WARN),
            ("VPD (kPa)", 'max_VPD', 'min_VPD', 'avg_vpd', self.COL_PRIMARY),
        )
        self.daily_stat_labels = {}
        for r, (titolo, k_max, k_min, k_avg, colore) in enumerate(righe, start=1):
            ttk.Label(stats_frame, text=titolo, font=(self.FONT_UI, 11, 'bold')).grid(
                row=r, column=0, sticky=tk.W, pady=4)
            for col, chiave in enumerate((k_max, k_min, k_avg), start=1):
                lbl = ttk.Label(stats_frame, text="--", font=(self.FONT_MONO, 15),
                                foreground=colore)
                lbl.grid(row=r, column=col, pady=4)
                self.daily_stat_labels[chiave] = lbl

        # Plot giornaliero
        ttk.Label(daily_frame, text="Andamento giornaliero",
                  font=(self.FONT_UI, 11, 'bold')).pack(anchor=tk.W, pady=(8, 4))
        self.daily_plot_label = ttk.Label(daily_frame, text="Nessun plot disponibile",
                                          foreground=self.COL_FAINT)
        self.daily_plot_label.pack(anchor=tk.W)

        # Cache dell'ultimo giorno disegnato: senza, ricaricheremmo il PNG da
        # disco ogni secondo (su un Pi Zero W e' spreco puro).
        self._daily_drawn = None
        self.refresh_daily_section()

    def refresh_daily_section(self):
        """Aggiorna statistiche e plot solo quando cambia il giorno elaborato."""
        daily = self.ah.daily_th
        if daily.last_stats is not None and daily.last_date_label != self._daily_drawn:
            self._daily_drawn = daily.last_date_label

            self.daily_date_label.config(
                text=f"Giorno elaborato: {daily.last_date_label}", foreground=self.COL_TEXT)
            for chiave, lbl in self.daily_stat_labels.items():
                lbl.config(text=f"{daily.last_stats[chiave]:g}")

            self._show_image(self.daily_plot_label, daily.last_plot_path)

        self.root.after(2000, self.refresh_daily_section)

    def start_daily_processing(self):
        """Avvia l'elaborazione giornaliera (DailyTHManager)."""
        started = self.ah.daily_th.start()
        if not started:
            messagebox.showwarning("Avviso", "Elaborazione giornaliera già attiva!")
            return
        messagebox.showinfo("Successo", "Elaborazione giornaliera avviata!")

    def stop_daily_processing(self):
        """Arresta l'elaborazione giornaliera."""
        stopped = self.ah.daily_th.stop()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna elaborazione in corso")
            return
        messagebox.showinfo("Successo", "Elaborazione giornaliera arrestata!")

    def _update_ambient_labels(self, temp, humidity, vpd, timestamp):
        """Aggiorna le label ambient (chiamata via root.after dal thread di lettura)."""
        self.ambient_temp_label.config(text=f"{temp:.1f} °C")
        self.ambient_humid_label.config(text=f"{humidity:.1f} %")
        self.ambient_vpd_label.config(text=f"{vpd:.2f} kPa")
        self.ambient_timestamp_label.config(text=f"Ultimo aggiornamento: {timestamp}")

    def start_ambient_reading(self):
        """Avvia la lettura temporizzata dei dati ambient (AmbientManager)."""
        def on_update(temp, humidity, vpd, timestamp):
            self.root.after(0, lambda: self._update_ambient_labels(temp, humidity, vpd, timestamp))

        started = self.ah.ambient.start_reading(on_update=on_update)
        if not started:
            messagebox.showwarning("Avviso", "Lettura ambient già in corso!")

    def stop_ambient_reading(self):
        """Arresta immediatamente la lettura temporizzata dei dati ambient."""
        stopped = self.ah.ambient.stop_reading()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna lettura in corso")
            return
        messagebox.showinfo("Successo", "Lettura ambient arrestata!")
        self.refresh_riepilogo_tab(force=True)

    def read_ambient_now(self):
        """Legge immediatamente i dati ambient (AmbientManager)."""
        try:
            temp, humidity, vpd, timestamp = self.ah.ambient.read_now()

            # Aggiorna GUI
            self.ambient_temp_label.config(text=f"{temp:.2f} °C")
            self.ambient_humid_label.config(text=f"{humidity:.2f} %")
            self.ambient_vpd_label.config(text=f"{vpd:.4f} kPa")
            self.ambient_timestamp_label.config(text=f"Ultimo aggiornamento: {timestamp}")

            messagebox.showinfo("Successo", f"Lettura completata:\nT={temp:.2f}°C\nH={humidity:.2f}%\nVPD={vpd:.4f}kPa")

        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura: {str(e)}")
            self.ah.logger.error(f"Errore lettura AMBIENT immediata: {str(e)}")

    def open_log_file(self):
        """Apre il file di log nell'editor predefinito"""
        try:
            log_path = self.get_log_file_path()

            if not log_path or not os.path.exists(log_path):
                messagebox.showwarning("Avviso", "File di log non trovato.")
                return

            # Windows
            if os.name == 'nt':
                os.startfile(log_path)
            # macOS
            elif sys.platform == 'darwin':
                os.system(f'open "{log_path}"')
            # Linux
            else:
                os.system(f'xdg-open "{log_path}"')

        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile aprire il file: {str(e)}")

    # ------------------------------------------------------------------
    # Tab: Climatizzatore (wrapper sottili → ClimateManager)
    # ------------------------------------------------------------------
    def create_climatizzatore_tab(self, parent):
        """Tab per il controllo automatico del condizionatore tramite IR."""
        parent, ir_canvas = self._make_scrollable(parent)

        # Unica sezione: Sistema di Controllo AC
        ac_frame = self._card(parent, "Sistema di Controllo AC")
        ac_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(ac_frame)
        inner.pack(expand=True)

        # Indicatore di stato
        ttk.Label(inner, text="Stato Controllo AC", font=(self.FONT_UI, 14, 'bold')).pack(pady=(10, 5))
        self.ac_status_label = self._chip(inner, "⏹ INATTIVO", self.COL_FAINT, self.COL_DIV)
        self.ac_status_label.pack(pady=10)

        # Info parametri correnti
        params_frame = ttk.Frame(inner)
        params_frame.pack(pady=10)

        ttk.Label(params_frame, text="T_opt:", font=(self.FONT_UI, 12)).grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ac_topt_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('T_max', '--')} °C",
            font=(self.FONT_UI, 12, 'bold'), foreground=self.COL_BLUE
        )
        self.ac_topt_label.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="H_opt:", font=(self.FONT_UI, 12)).grid(row=0, column=2, sticky=tk.W, padx=15)
        self.ac_hopt_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('H_max', '--')} %",
            font=(self.FONT_UI, 12, 'bold'), foreground=self.COL_WARN
        )
        self.ac_hopt_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="Tempo max ON:", font=(self.FONT_UI, 12)).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.ac_tmax_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('time_max_on', '--')} min",
            font=(self.FONT_UI, 12, 'bold')
        )
        self.ac_tmax_label.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="Ultimo comando:", font=(self.FONT_UI, 12)).grid(row=1, column=2, sticky=tk.W, padx=15)
        self.ac_last_cmd_label = ttk.Label(
            params_frame, text="--", font=(self.FONT_UI, 12, 'bold'), foreground=self.COL_PRIMARY
        )
        self.ac_last_cmd_label.grid(row=1, column=3, sticky=tk.W, padx=5)

        # Pulsanti attivazione / disattivazione
        btn_frame = ttk.Frame(inner)
        btn_frame.pack(pady=20)

        ttk.Button(
            btn_frame, text="▶️ Attiva Controllo AC", style='Accent.TButton', command=self.start_ac_control
        ).pack(side=tk.LEFT, padx=10)

        ttk.Button(
            btn_frame, text="⏹️ Disattiva Controllo AC", style='Stop.TButton', command=self.stop_ac_control
        ).pack(side=tk.LEFT, padx=10)

        self._bind_mousewheel(parent, ir_canvas)

    def start_ac_control(self):
        """Avvia il controllo automatico del condizionatore (ClimateManager)."""
        def on_command_sent(cmd):
            self.root.after(0, lambda c=cmd: self.ac_last_cmd_label.config(text=c))

        result = self.ah.climate.start(on_command_sent=on_command_sent)

        if result == 'already_active':
            messagebox.showwarning("Avviso", "Il controllo AC è già attivo!")
            return
        if result == 'no_ambient':
            messagebox.showwarning(
                "Avviso",
                "Nessuna lettura ambient disponibile.\n"
                "Attiva prima la lettura ambient (tab Ambient) prima di avviare il controllo AC."
            )
            return

        # Aggiorna UI
        self.ac_status_label.config(text="▶ ATTIVO", fg=self.COL_PRIMARY, bg=self.COL_SOFT)

    def stop_ac_control(self):
        """Arresta immediatamente il controllo automatico del condizionatore."""
        stopped = self.ah.climate.stop()
        if not stopped:
            messagebox.showwarning("Avviso", "Il controllo AC non è attivo.")
            return

        # Aggiorna UI
        self.ac_status_label.config(text="⏹ INATTIVO", fg=self.COL_FAINT, bg=self.COL_DIV)
        self.ac_last_cmd_label.config(text="off")

    # ------------------------------------------------------------------
    # Tab: Livelli Serbatoio (wrapper sottili → TankManager)
    # ------------------------------------------------------------------
    def create_tank_tab(self, parent):
        """Tab per monitorare il livello dell'acqua nel serbatoio."""
        parent, tank_canvas = self._make_scrollable(parent)

        # Frame superiore con bottoni
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_tank_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_tank_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📊 Leggi Adesso", command=self.read_tank_now).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = self._card(parent, "LIVELLI SERBATOIO")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(expand=True, fill=tk.X)

        # Volume (valore principale)
        vol_frame = ttk.Frame(inner)
        vol_frame.pack(pady=10)
        ttk.Label(vol_frame, text="VOLUME", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.tank_volume_label = ttk.Label(vol_frame, text="-- L", font=(self.FONT_MONO, 34), foreground=self.COL_BLUE)
        self.tank_volume_label.pack()

        # Barra di riempimento
        pb_frame = ttk.Frame(inner)
        pb_frame.pack(pady=10)
        self.tank_fill_var = tk.DoubleVar(value=0)
        self.tank_progress = ttk.Progressbar(pb_frame, orient=tk.HORIZONTAL, length=420,
                                             mode='determinate', variable=self.tank_fill_var, maximum=100)
        self.tank_progress.pack()
        self.tank_fill_label = self._chip(inner, "Riempimento: -- %",
                                          self.COL_BLUE, self.COL_BLUE_BG)
        self.tank_fill_label.pack(pady=8)

        # Valori secondari
        sec = ttk.Frame(inner)
        sec.pack(pady=10)
        ttk.Label(sec, text="Livello:", font=(self.FONT_UI, 12)).grid(row=0, column=0, sticky=tk.W, padx=5)
        self.tank_level_label = ttk.Label(sec, text="-- cm", font=(self.FONT_UI, 12, 'bold'))
        self.tank_level_label.grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(sec, text="Distanza:", font=(self.FONT_UI, 12)).grid(row=0, column=2, sticky=tk.W, padx=15)
        self.tank_dist_label = ttk.Label(sec, text="-- cm", font=(self.FONT_UI, 12, 'bold'))
        self.tank_dist_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        # Timestamp della lettura
        self.tank_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                             font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.tank_timestamp_label.pack(pady=15)

        self._chip(inner, "⚠  Sensore ancora da tarare — parametri nella schermata Configurazione",
                   self.COL_WARN, self.COL_WARN_BG).pack()

        # Le altre due grandezze dell'acqua, lette dalle sonde Atlas collegate
        # all'Arduino: stessa struttura della card del serbatoio.
        self._build_ph_card(parent)
        self._build_ec_card(parent)

        self._bind_mousewheel(parent, tank_canvas)

    # ------------------------------------------------------------------
    # Pagina H2O: card pH ed EC (wrapper sottili → WaterManager)
    # ------------------------------------------------------------------
    def _build_ph_card(self, parent):
        """Card del pH, con i suoi comandi di avvio/arresto indipendenti."""
        card = self._card(parent, "pH DELL'ACQUA")
        card.pack(fill=tk.X, padx=10, pady=10)

        btns = ttk.Frame(card)
        btns.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(btns, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_ph_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_ph_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="📊 Leggi Adesso",
                   command=self.read_ph_now).pack(side=tk.LEFT, padx=5)

        inner = ttk.Frame(card)
        inner.pack(expand=True, fill=tk.X)

        ttk.Label(inner, text="pH", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.ph_value_label = ttk.Label(inner, text="--", font=(self.FONT_MONO, 34),
                                        foreground=self.COL_BLUE)
        self.ph_value_label.pack()

        self.ph_status_chip = self._chip(inner, "Nessuna misura", self.COL_FAINT, self.COL_DIV)
        self.ph_status_chip.pack(pady=8)

        self.ph_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                            font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.ph_timestamp_label.pack(pady=(0, 8))

        # Se c'e' gia' una misura salvata, la si mostra subito
        if self.ah.water.last_ph:
            self._update_ph_labels(self.ah.water.last_ph)

    def _build_ec_card(self, parent):
        """
        Card della conducibilita' elettrica.

        Il circuito EZO-EC restituisce EC, TDS e salinita' in un'unica
        risposta, quindi la card li mostra tutti e tre insieme, ciascuno con
        la propria unita' di misura: sono tre facce della stessa lettura, non
        tre misure separate.
        """
        card = self._card(parent, "CONDUCIBILITÀ ELETTRICA DELL'ACQUA")
        card.pack(fill=tk.X, padx=10, pady=10)

        btns = ttk.Frame(card)
        btns.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(btns, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_ec_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_ec_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="📊 Leggi Adesso",
                   command=self.read_ec_now).pack(side=tk.LEFT, padx=5)

        inner = ttk.Frame(card)
        inner.pack(expand=True, fill=tk.X)

        ttk.Label(inner, text="CONDUCIBILITÀ", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.ec_value_label = ttk.Label(inner, text="-- µS/cm", font=(self.FONT_MONO, 34),
                                        foreground=self.COL_BLUE)
        self.ec_value_label.pack()

        self.ec_status_chip = self._chip(inner, "Nessuna misura", self.COL_FAINT, self.COL_DIV)
        self.ec_status_chip.pack(pady=8)

        sec = ttk.Frame(inner)
        sec.pack(pady=6)
        ttk.Label(sec, text="Solidi disciolti (TDS):",
                  font=(self.FONT_UI, 12)).grid(row=0, column=0, sticky=tk.W, padx=5)
        self.tds_value_label = ttk.Label(sec, text="-- ppm", font=(self.FONT_UI, 12, 'bold'))
        self.tds_value_label.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(sec, text="Salinità:",
                  font=(self.FONT_UI, 12)).grid(row=0, column=2, sticky=tk.W, padx=15)
        self.sal_value_label = ttk.Label(sec, text="-- PSU", font=(self.FONT_UI, 12, 'bold'))
        self.sal_value_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        self.ec_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                            font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.ec_timestamp_label.pack(pady=(8, 0))

        if self.ah.water.last_ec:
            self._update_ec_labels(self.ah.water.last_ec)

    def _water_params(self):
        """Soglie di allarme di pH ed EC, lette dalla configurazione."""
        w = self.config.get('water', {}) or {}
        return dict(ph_min=w.get('ph_min', 5.5), ph_max=w.get('ph_max', 6.5),
                    ec_min=w.get('ec_min', 800), ec_max=w.get('ec_max', 2000))

    def _range_chip(self, chip, valore, minimo, massimo, unita=''):
        """Colora una pill di stato secondo che il valore sia o meno in range."""
        suffisso = f" {unita}" if unita else ''
        if minimo <= valore <= massimo:
            chip.config(text=f"Nel range {minimo}–{massimo}{suffisso}",
                        fg=self.COL_OK, bg=self.COL_SOFT)
        else:
            chip.config(text=f"Fuori dal range {minimo}–{massimo}{suffisso}",
                        fg=self.COL_WARN, bg=self.COL_WARN_BG)

    def _update_ph_labels(self, result):
        """Aggiorna le label del pH (chiamata via root.after dal thread di lettura)."""
        p = self._water_params()
        self.ph_value_label.config(text=f"{result['ph']:.2f}")
        self._range_chip(self.ph_status_chip, result['ph'], p['ph_min'], p['ph_max'])
        self.ph_timestamp_label.config(text=f"Ultimo aggiornamento: {result['timestamp']}")

    def _update_ec_labels(self, result):
        """Aggiorna le label di EC/TDS/salinità (tutte da un'unica lettura)."""
        p = self._water_params()
        self.ec_value_label.config(text=f"{result['ec_us_cm']:.1f} µS/cm")
        self._range_chip(self.ec_status_chip, result['ec_us_cm'],
                         p['ec_min'], p['ec_max'], 'µS/cm')
        self.tds_value_label.config(text=f"{result['tds_ppm']:.1f} ppm")
        self.sal_value_label.config(text=f"{result['salinity_psu']:.2f} PSU")
        self.ec_timestamp_label.config(text=f"Ultimo aggiornamento: {result['timestamp']}")

    def start_ph_reading(self):
        """Avvia la lettura temporizzata del pH (WaterManager)."""
        def on_update(result):
            self.root.after(0, lambda r=result: self._update_ph_labels(r))

        if not self.ah.water.start_ph_reading(on_update=on_update):
            messagebox.showwarning("Avviso", "Lettura pH già in corso!")

    def stop_ph_reading(self):
        """Arresta immediatamente la lettura del pH."""
        if not self.ah.water.stop_ph_reading():
            messagebox.showwarning("Avviso", "Nessuna lettura pH in corso")
            return
        messagebox.showinfo("Successo", "Lettura pH arrestata!")

    def read_ph_now(self):
        """Legge immediatamente il pH (WaterManager)."""
        try:
            result = self.ah.water.read_ph_now()
            if result is None:
                messagebox.showwarning(
                    "Avviso", "Non è stato possibile leggere il sensore di pH.\n"
                              "Il motivo è indicato nella sezione Errori della schermata Log.")
                return
            self._update_ph_labels(result)
            messagebox.showinfo("Successo", f"pH: {result['ph']:.2f}")
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura del pH: {e}")

    def start_ec_reading(self):
        """Avvia la lettura temporizzata dell'EC (WaterManager)."""
        def on_update(result):
            self.root.after(0, lambda r=result: self._update_ec_labels(r))

        if not self.ah.water.start_ec_reading(on_update=on_update):
            messagebox.showwarning("Avviso", "Lettura EC già in corso!")

    def stop_ec_reading(self):
        """Arresta immediatamente la lettura dell'EC."""
        if not self.ah.water.stop_ec_reading():
            messagebox.showwarning("Avviso", "Nessuna lettura EC in corso")
            return
        messagebox.showinfo("Successo", "Lettura EC arrestata!")

    def read_ec_now(self):
        """Legge immediatamente EC, TDS e salinità (WaterManager)."""
        try:
            result = self.ah.water.read_ec_now()
            if result is None:
                messagebox.showwarning(
                    "Avviso", "Non è stato possibile leggere il sensore di conducibilità.\n"
                              "Il motivo è indicato nella sezione Errori della schermata Log.")
                return
            self._update_ec_labels(result)
            messagebox.showinfo(
                "Successo",
                f"Conducibilità: {result['ec_us_cm']:.1f} µS/cm\n"
                f"TDS: {result['tds_ppm']:.1f} ppm\n"
                f"Salinità: {result['salinity_psu']:.2f} PSU")
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura dell'EC: {e}")

    def _update_tank_labels(self, result):
        """Aggiorna le label del serbatoio (chiamata via root.after dal thread di lettura)."""
        self.tank_volume_label.config(text=f"{result['volume_L']:.2f} L")
        self.tank_fill_var.set(result['fill_percent'])
        self.tank_fill_label.config(text=f"Riempimento: {result['fill_percent']:.1f} %")
        self.tank_level_label.config(text=f"{result['water_level_cm']:.1f} cm")
        self.tank_dist_label.config(text=f"{result['distance_cm']:.1f} cm")
        self.tank_timestamp_label.config(text=f"Ultimo aggiornamento: {result['timestamp']}")

    def start_tank_reading(self):
        """Avvia la lettura temporizzata del livello serbatoio (TankManager)."""
        def on_update(result):
            self.root.after(0, lambda r=result: self._update_tank_labels(r))

        started = self.ah.tank.start_reading(on_update=on_update)
        if not started:
            messagebox.showwarning("Avviso", "Lettura serbatoio già in corso!")

    def stop_tank_reading(self):
        """Arresta immediatamente la lettura del livello serbatoio."""
        stopped = self.ah.tank.stop_reading()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna lettura serbatoio in corso")
            return
        messagebox.showinfo("Successo", "Lettura serbatoio arrestata!")

    def read_tank_now(self):
        """Legge immediatamente il livello del serbatoio (TankManager)."""
        try:
            result = self.ah.tank.read_now()
            if result is None:
                messagebox.showwarning("Avviso", "Misura non valida (timeout o fuori range). Verificare il sensore.")
                return

            self._update_tank_labels(result)
            messagebox.showinfo(
                "Successo",
                f"Volume: {result['volume_L']:.2f} L\n"
                f"Riempimento: {result['fill_percent']:.1f} %\n"
                f"Livello: {result['water_level_cm']:.1f} cm"
            )
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura serbatoio: {str(e)}")
            self.ah.logger.error(f"Errore lettura TANK: {str(e)}")


    # ------------------------------------------------------------------
    # Tab: Spettrometro / MCARI2 (wrapper sottili → SpectroManager)
    # ------------------------------------------------------------------
    def create_spectro_tab(self, parent):
        """Tab per monitorare l'indice di vegetazione MCARI2 e lo stato della pianta."""
        parent, spectro_canvas = self._make_scrollable(parent)

        # Frame superiore con bottoni
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="🔬 Misura Adesso", command=self.read_spectro_now).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_spectro_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_spectro_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⚪ Taratura (rif. bianco)",
                   command=self.calibrate_spectro).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = self._card(parent, "INDICE MCARI2")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(fill=tk.BOTH, expand=True)

        # Valore dell'indice (valore principale)
        val_frame = ttk.Frame(inner)
        val_frame.pack(pady=5)
        ttk.Label(val_frame, text="MCARI2", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.spectro_value_label = ttk.Label(val_frame, text="--", font=(self.FONT_MONO, 34),
                                             foreground=self.COL_BLUE)
        self.spectro_value_label.pack()

        # Indicatore dello stato della pianta (spia + testo)
        state_frame = ttk.Frame(inner)
        state_frame.pack(pady=10)
        self.spectro_canvas = tk.Canvas(state_frame, width=28, height=28,
                                        highlightthickness=0, bg=self.COL_CARD)
        self.spectro_canvas.pack(side=tk.LEFT, padx=(0, 10))
        self.spectro_oval = self.spectro_canvas.create_oval(6, 6, 22, 22,
                                                            fill=self.COL_FAINT, outline='')
        self.spectro_state_label = self._chip(state_frame, "Nessuna misura disponibile",
                                              self.COL_FAINT, self.COL_DIV)
        self.spectro_state_label.pack(side=tk.LEFT)

        # Timestamp della lettura
        self.spectro_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                                 font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.spectro_timestamp_label.pack(pady=5)

        # Storico delle misure
        hist_frame = self._card(inner, "Storico Misure")
        hist_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        columns = ('Data/Ora', 'MCARI2', 'Stato')
        self.spectro_tree = ttk.Treeview(hist_frame, columns=columns, show='headings', height=8)
        for col, width in (('Data/Ora', 150), ('MCARI2', 80), ('Stato', 420)):
            self.spectro_tree.heading(col, text=col)
            self.spectro_tree.column(col, width=width)

        scrollbar = ttk.Scrollbar(hist_frame, orient=tk.VERTICAL, command=self.spectro_tree.yview)
        self.spectro_tree.configure(yscroll=scrollbar.set)

        self.spectro_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Colore delle righe in base allo stato della pianta
        for stato, color in self.MCARI2_COLORS.items():
            self.spectro_tree.tag_configure(stato, foreground=color)

        # Popola con lo storico gia' letto dai file all'avvio
        self._refresh_spectro_history()

        self._bind_mousewheel(parent, spectro_canvas)

    def _refresh_spectro_history(self):
        """Ripopola la tabella dello storico dalle misure del SpectroManager."""
        for item in self.spectro_tree.get_children():
            self.spectro_tree.delete(item)

        for entry in self.ah.spectro.history:
            self.spectro_tree.insert('', 'end', tags=(entry['stato'],), values=(
                entry['timestamp'], f"{entry['mcari2']:.4f}", entry['testo']
            ))

    def _update_spectro_labels(self, result):
        """Aggiorna valore, spia e storico (chiamata via root.after dal thread di lettura)."""
        color = self.MCARI2_COLORS.get(result['stato'], self.COL_FAINT)
        self.spectro_value_label.config(text=f"{result['mcari2']:.4f}", foreground=color)
        self.spectro_canvas.itemconfig(self.spectro_oval, fill=color)
        self.spectro_state_label.config(
            text=result['testo'], fg=color,
            bg=self.MCARI2_CHIP_BG.get(result['stato'], self.COL_DIV))
        self.spectro_timestamp_label.config(text=f"Ultimo aggiornamento: {result['timestamp']}")
        self._refresh_spectro_history()

    def start_spectro_reading(self):
        """Avvia la lettura temporizzata dell'MCARI2 (SpectroManager)."""
        if not self._check_spectro_calibration():
            return

        def on_update(result):
            self.root.after(0, lambda r=result: self._update_spectro_labels(r))

        started = self.ah.spectro.start_reading(on_update=on_update)
        if not started:
            messagebox.showwarning("Avviso", "Lettura spettrometro già in corso!")

    def stop_spectro_reading(self):
        """Arresta immediatamente la lettura dell'MCARI2."""
        stopped = self.ah.spectro.stop_reading()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna lettura spettrometro in corso")
            return
        messagebox.showinfo("Successo", "Lettura spettrometro arrestata!")

    def _check_spectro_calibration(self):
        """True se esiste una taratura; altrimenti avvisa e indirizza alla taratura."""
        if self.ah.spectro.has_calibration():
            return True
        messagebox.showwarning(
            "Taratura mancante",
            "Nessuna taratura trovata.\n\n"
            "L'MCARI2 si calcola sulla riflettanza, quindi serve prima una misura "
            "del riferimento bianco: puntare il sensore sul pannello bianco e "
            "premere '⚪ Taratura (rif. bianco)'."
        )
        return False

    def read_spectro_now(self):
        """Legge immediatamente l'indice MCARI2 (SpectroManager)."""
        if not self._check_spectro_calibration():
            return

        try:
            result = self.ah.spectro.read_now()
            self._update_spectro_labels(result)
            messagebox.showinfo(
                "Successo",
                f"MCARI2: {result['mcari2']:.4f}\n"
                f"Stato: {result['testo']}"
            )
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura spettrometro: {str(e)}")
            self.ah.logger.error(f"Errore lettura SPECTRO: {str(e)}")

    def calibrate_spectro(self):
        """Esegue la taratura sul riferimento bianco (SpectroManager)."""
        if not messagebox.askyesno(
            "Taratura",
            "Puntare il sensore sul pannello bianco di riferimento.\n\n"
            "La misura verrà eseguita con il LED bianco integrato acceso e "
            "sostituirà la taratura precedente.\n\nProcedere?"
        ):
            return

        try:
            reference = self.ah.spectro.calibrate()
            messagebox.showinfo(
                "Successo",
                "Taratura completata.\nRiferimento bianco:\n"
                f"GREEN (560nm): {reference[spectro.GREEN_NM]:.2f}\n"
                f"RED   (680nm): {reference[spectro.RED_NM]:.2f}\n"
                f"NIR   (810nm): {reference[spectro.NIR_NM]:.2f}"
            )
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella taratura: {str(e)}")
            self.ah.logger.error(f"Errore taratura SPECTRO: {str(e)}")

    # ------------------------------------------------------------------
    # Tab: Crescita (wrapper sottili → PlantGrowthManager)
    # ------------------------------------------------------------------
    def create_growth_tab(self, parent):
        """Tab per monitorare l'altezza della pianta misurata dal sensore ultrasonico."""
        parent, growth_canvas = self._make_scrollable(parent)

        # Frame superiore con bottoni
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="📏 Misura Adesso", command=self.read_growth_now).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_growth_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_growth_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📐 Calibrazione",
                   command=self.calibrate_growth).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = self._card(parent, "ALTEZZA PIANTA")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(fill=tk.BOTH, expand=True)

        # Altezza dell'ultima misura (valore principale)
        val_frame = ttk.Frame(inner)
        val_frame.pack(pady=5)
        ttk.Label(val_frame, text="ALTEZZA PIANTA", font=(self.FONT_UI, 9, 'bold'),
                  foreground=self.COL_FAINT).pack()
        self.growth_value_label = ttk.Label(val_frame, text="--", font=(self.FONT_MONO, 34),
                                            foreground=self.COL_PRIMARY)
        self.growth_value_label.pack()

        # Timestamp della lettura
        self.growth_timestamp_label = ttk.Label(inner, text="Ultima misurazione: --",
                                                font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.growth_timestamp_label.pack(pady=5)

        # Andamento nel tempo: Canvas nativo (nessuna dipendenza da matplotlib,
        # i punti sono pochi perche' la misura e' ogni N giorni)
        chart_frame = self._card(inner, "Andamento nel tempo")
        chart_frame.pack(fill=tk.X, pady=10)
        self.growth_canvas = tk.Canvas(chart_frame, height=180, highlightthickness=0,
                                       bg='white')
        self.growth_canvas.pack(fill=tk.X, expand=True)
        self.growth_canvas.bind('<Configure>', lambda e: self._draw_growth_chart())

        # Storico delle misure
        hist_frame = self._card(inner, "Storico Misure")
        hist_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        columns = ('Data/Ora', 'Altezza (cm)')
        self.growth_tree = ttk.Treeview(hist_frame, columns=columns, show='headings', height=6)
        for col, width in (('Data/Ora', 200), ('Altezza (cm)', 120)):
            self.growth_tree.heading(col, text=col)
            self.growth_tree.column(col, width=width)

        scrollbar = ttk.Scrollbar(hist_frame, orient=tk.VERTICAL, command=self.growth_tree.yview)
        self.growth_tree.configure(yscroll=scrollbar.set)

        self.growth_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Popola con lo storico gia' letto dal file GROWTH.csv all'avvio
        self._refresh_growth_history()
        self._show_last_growth()

        self._bind_mousewheel(parent, growth_canvas)

    def _show_last_growth(self):
        """Mostra l'ultima misura disponibile (da file o da lettura) nelle label."""
        history = self.ah.plant_growth.history
        if not history:
            return
        last = history[-1]
        self.growth_value_label.config(text=f"{last['h_plant_cm']:.1f} cm")
        self.growth_timestamp_label.config(text=f"Ultima misurazione: {last['timestamp']}")

    def _refresh_growth_history(self):
        """Ripopola la tabella dello storico (misure piu' recenti in cima)."""
        for item in self.growth_tree.get_children():
            self.growth_tree.delete(item)

        for entry in reversed(self.ah.plant_growth.history):
            self.growth_tree.insert('', 'end', values=(
                entry['timestamp'], f"{entry['h_plant_cm']:.1f}"
            ))

    def _draw_growth_chart(self):
        """
        Disegna l'andamento dell'altezza pianta sul Canvas.

        Scelta deliberata di non usare matplotlib: sul Raspberry Pi Zero W
        costerebbe ~2-4s di import e decine di MB di RAM residenti, mentre qui
        i punti sono al massimo history_len e le primitive Tk bastano.
        """
        canvas = self.growth_canvas
        canvas.delete('all')

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1 or h <= 1:  # Canvas non ancora disegnato
            return

        history = self.ah.plant_growth.history
        if len(history) < 2:
            canvas.create_text(w // 2, h // 2, text="Servono almeno due misure per l'andamento",
                               fill=self.COL_FAINT, font=(self.FONT_UI, 11, 'italic'))
            return

        # Area di disegno (margini per le etichette)
        pad_l, pad_r, pad_t, pad_b = 45, 12, 12, 26
        x0, x1 = pad_l, w - pad_r
        y0, y1 = pad_t, h - pad_b
        if x1 <= x0 or y1 <= y0:
            return

        heights = [e['h_plant_cm'] for e in history]
        h_min, h_max = min(heights), max(heights)
        if h_max == h_min:  # Serie piatta: evita la divisione per zero
            h_min, h_max = h_min - 1.0, h_max + 1.0

        # Assi
        canvas.create_line(x0, y0, x0, y1, fill=self.COL_BORDER)
        canvas.create_line(x0, y1, x1, y1, fill=self.COL_BORDER)

        # Etichette in cm (min, medio, max)
        for frac in (0.0, 0.5, 1.0):
            value = h_min + (h_max - h_min) * frac
            y = y1 - (y1 - y0) * frac
            canvas.create_text(x0 - 5, y, text=f"{value:.1f}", anchor=tk.E,
                               fill=self.COL_FAINT, font=(self.FONT_UI, 8))
            if frac > 0:  # Griglia orizzontale leggera
                canvas.create_line(x0, y, x1, y, fill=self.COL_DIV)

        # Punti della spezzata
        step = (x1 - x0) / (len(history) - 1)
        points = []
        for i, entry in enumerate(history):
            x = x0 + step * i
            y = y1 - (y1 - y0) * (entry['h_plant_cm'] - h_min) / (h_max - h_min)
            points.extend((x, y))

        canvas.create_line(*points, fill=self.COL_PRIMARY, width=2, smooth=False)
        for i in range(0, len(points), 2):
            x, y = points[i], points[i + 1]
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2,
                               fill=self.COL_PRIMARY, outline=self.COL_PRIMARY)

        # Date di inizio e fine serie
        canvas.create_text(x0, y1 + 12, text=self._short_date(history[0]['timestamp']),
                           anchor=tk.W, fill=self.COL_FAINT, font=(self.FONT_UI, 8))
        canvas.create_text(x1, y1 + 12, text=self._short_date(history[-1]['timestamp']),
                           anchor=tk.E, fill=self.COL_FAINT, font=(self.FONT_UI, 8))

    def _short_date(self, timestamp):
        """Riduce un timestamp 'YYYY/mm/dd HH:MM:SS' a 'dd/mm' per le etichette del grafico."""
        try:
            return datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S").strftime("%d/%m")
        except ValueError:
            return timestamp

    def _update_growth_labels(self, result):
        """Aggiorna valore, grafico e storico (chiamata via root.after dal thread di misura)."""
        self.growth_value_label.config(text=f"{result['h_plant_cm']:.1f} cm")
        self.growth_timestamp_label.config(text=f"Ultima misurazione: {result['timestamp']}")
        self._refresh_growth_history()
        self._draw_growth_chart()

    def start_growth_reading(self):
        """Avvia la misura temporizzata dell'altezza pianta (PlantGrowthManager)."""
        def on_update(result):
            self.root.after(0, lambda r=result: self._update_growth_labels(r))

        started = self.ah.plant_growth.start_reading(on_update=on_update)
        if not started:
            messagebox.showwarning("Avviso", "Misura crescita già in corso!")

    def stop_growth_reading(self):
        """Arresta immediatamente la misura dell'altezza pianta."""
        stopped = self.ah.plant_growth.stop_reading()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna misura crescita in corso")
            return
        messagebox.showinfo("Successo", "Misura crescita arrestata!")

    def calibrate_growth(self):
        """Tara l'altezza di riferimento del sensore di crescita (PlantGrowthManager)."""
        # Il sensore e' uno solo: se la lettura periodica scattasse durante la
        # calibrazione, i due impulsi ultrasonici si disturberebbero a vicenda.
        if self.ah.plant_growth.is_running():
            messagebox.showwarning(
                "Lettura in corso",
                "È in corso la lettura periodica della crescita.\n\n"
                "Arrestare prima la lettura con '⏹️ Arresta Lettura', "
                "poi ripetere la calibrazione."
            )
            return

        if not messagebox.askyesno(
            "Attenzione",
            "Attenzione: Vuoi effettuare la calibrazione per il sensore di altezza?",
            icon='warning'
        ):
            return

        try:
            reference = self.ah.plant_growth.calibration_distance()
            if reference is None:
                messagebox.showwarning(
                    "Misura non valida",
                    "Il sensore non ha restituito una misura valida.\n\n"
                    "Verificare il posizionamento e il cablaggio del sensore."
                )
                return

            # Allinea il config della GUI e il campo della tab Configurazione:
            # senza, il prossimo 'Salva Configurazione' riscriverebbe sul file il
            # vecchio riferimento, annullando la calibrazione appena fatta.
            self.config.setdefault('plant_growth', {})['reference_height_cm'] = reference
            self.growth_ref_var.set(str(reference))

            messagebox.showinfo(
                "Successo",
                f"Calibrazione completata.\n\n"
                f"Altezza di riferimento: {reference} cm\n\n"
                "Da adesso questa distanza è lo zero: le prossime misure "
                "conteranno la crescita a partire da qui."
            )
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella calibrazione: {str(e)}")
            self.ah.logger.error(f"Errore calibrazione GROWTH: {str(e)}")

    def read_growth_now(self):
        """Misura immediatamente l'altezza della pianta (PlantGrowthManager)."""
        try:
            result = self.ah.plant_growth.read_now()
            if result is None:
                messagebox.showwarning(
                    "Misura non valida",
                    "Il sensore non ha restituito una misura valida.\n\n"
                    "Verificare il posizionamento e il cablaggio del sensore."
                )
                return

            self._update_growth_labels(result)
            messagebox.showinfo(
                "Successo",
                f"Altezza pianta: {result['h_plant_cm']:.1f} cm\n"
                f"Distanza misurata: {result['distance_cm']:.1f} cm"
            )
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella misura crescita: {str(e)}")
            self.ah.logger.error(f"Errore misura GROWTH: {str(e)}")

    # ------------------------------------------------------------------
    # Tab: Camera (wrapper sottili → CameraManager)
    # ------------------------------------------------------------------
    def create_camera_tab(self, parent):
        """Tab per l'acquisizione periodica delle foto e l'anteprima dal vivo."""
        parent, camera_canvas = self._make_scrollable(parent)

        # Controlli
        btn_frame = self._card(parent, "Controlli")
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="▶️ Attiva acquisizione", style='Accent.TButton',
                   command=self.start_camera_acquisition).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Disattiva acquisizione", style='Stop.TButton',
                   command=self.stop_camera_acquisition).pack(side=tk.LEFT, padx=5)
        self.camera_preview_btn = ttk.Button(btn_frame, text="📷 Attiva camera",
                                             command=self.toggle_camera_preview)
        self.camera_preview_btn.pack(side=tk.LEFT, padx=5)

        # Ultima foto acquisita
        photo_frame = self._card(parent, "Ultima foto acquisita")
        photo_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.camera_photo_date = ttk.Label(photo_frame, text="Nessuna foto acquisita",
                                           font=(self.FONT_UI, 10), foreground=self.COL_FAINT)
        self.camera_photo_date.pack(anchor=tk.W, pady=(0, 8))

        self.camera_photo_label = ttk.Label(photo_frame, text="Nessuna immagine disponibile",
                                            foreground=self.COL_FAINT)
        self.camera_photo_label.pack(anchor=tk.W)

        # Come per il plot giornaliero: si ricarica il JPG solo quando cambia
        self._camera_drawn = None
        self.refresh_camera_tab()

        self._bind_mousewheel(parent, camera_canvas)

    def refresh_camera_tab(self):
        """Tick periodico della scheda Camera."""
        self._refresh_camera_view()
        self.root.after(2000, self.refresh_camera_tab)

    def _refresh_camera_view(self):
        """
        Aggiorna anteprima dell'ultima foto e testo del bottone anteprima.

        Separata dal tick perche' il toggle dell'anteprima la richiama subito:
        se richiamasse refresh_camera_tab moltiplicherebbe i timer.
        """
        photo = self.ah.camera.last_photo
        if photo is not None and photo['path'] != self._camera_drawn:
            self._camera_drawn = photo['path']
            self.camera_photo_date.config(
                text=f"Acquisita: {self._format_acq_date(photo['timestamp'])}",
                foreground=self.COL_TEXT)
            self._show_image(self.camera_photo_label, photo['path'])

        self.camera_preview_btn.config(
            text="📷 Disattiva camera" if self.ah.camera.is_previewing()
            else "📷 Attiva camera")

    def start_camera_acquisition(self):
        """Avvia l'acquisizione periodica delle foto (CameraManager)."""
        def on_capture(photo):
            # Il thread del manager non puo' toccare Tk: il refresh periodico
            # se ne accorge da solo, qui basta loggare lo scatto.
            self.ah.logger.info(f"CAMERA: nuova foto disponibile ({photo['path']})")

        started = self.ah.camera.start_acquisition(on_capture=on_capture)
        if not started:
            if self.ah.camera.is_previewing():
                messagebox.showwarning(
                    "Avviso",
                    "L'anteprima della camera è attiva: disattivarla prima di "
                    "avviare l'acquisizione.")
            else:
                messagebox.showwarning("Avviso", "Acquisizione già in corso!")
            return
        messagebox.showinfo("Successo", "Acquisizione foto avviata!")

    def stop_camera_acquisition(self):
        """Arresta l'acquisizione periodica delle foto."""
        stopped = self.ah.camera.stop_acquisition()
        if not stopped:
            messagebox.showwarning("Avviso", "Nessuna acquisizione in corso")
            return
        messagebox.showinfo("Successo", "Acquisizione foto arrestata!")

    def toggle_camera_preview(self):
        """
        Apre o chiude l'anteprima dal vivo.

        La camera e' una risorsa singola: con l'acquisizione periodica attiva
        Picamera2 e' (o sara' a breve) gia' istanziata, quindi l'anteprima non
        puo' partire e l'utente va avvisato.
        """
        if not self.ah.camera.is_previewing() and self.ah.camera.is_acquiring():
            messagebox.showwarning(
                "Camera occupata",
                "L'acquisizione delle foto è attiva e la camera è già in uso.\n\n"
                "Disattivare l'acquisizione prima di attivare la camera.")
            return

        try:
            self.ah.camera.toggle_preview()
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nell'anteprima camera: {str(e)}")
            self.ah.logger.error(f"Errore anteprima CAMERA: {str(e)}")
            return

        self._refresh_camera_view()


if __name__ == "__main__":
    try:
        root = tk.Tk()
        gui = AeroGreenHouseGUI(root)
        root.mainloop()
    except KeyboardInterrupt:
        gui.ah.cleanup_gpios()
        print('Job forced to stop')
