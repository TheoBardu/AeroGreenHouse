#! /usr/bin/python3
import tkinter as tk
from tkinter import ttk, messagebox
import yaml
import os
import sys
from datetime import datetime
import logging
from queue import Queue

from helper_aeroGreenHouse import aeroHelper
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
    def setup_style(self):
        """Definisce una palette coerente e uno stile leggero (adatto a Raspberry Pi)."""
        self.COL_BG = "#eef2ee"
        self.COL_HEADER = "#1b5e20"
        self.COL_PRIMARY = "#2e7d32"
        self.COL_ACCENT = "#388e3c"
        self.COL_OK = "#2e9e2e"     # spia verde
        self.COL_BAD = "#c62828"    # spia rossa
        self.COL_WARN = "#b26a00"   # spia arancione
        self.COL_TEXT = "#1f2d27"

        # Colore dello stato della pianta. Le chiavi sono quelle di
        # classifica_mcari2: le soglie numeriche restano nel modulo del sensore.
        self.MCARI2_COLORS = {
            spectro.STATO_STRESS: self.COL_BAD,
            spectro.STATO_LIMITE: self.COL_WARN,
            spectro.STATO_SANA: self.COL_OK,
            spectro.STATO_MOLTO_SANA: self.COL_HEADER,
        }

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('.', background=self.COL_BG, foreground=self.COL_TEXT, font=('Arial', 10))
        style.configure('TFrame', background=self.COL_BG)
        style.configure('TLabel', background=self.COL_BG)
        style.configure('TLabelframe', background=self.COL_BG, borderwidth=1, relief='groove')
        style.configure('TLabelframe.Label', background=self.COL_BG,
                        foreground=self.COL_PRIMARY, font=('Arial', 11, 'bold'))
        style.configure('TNotebook', background=self.COL_BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=[14, 7], font=('Arial', 10, 'bold'))
        style.map('TNotebook.Tab',
                  background=[('selected', self.COL_BG), ('!selected', '#cdd8cd')],
                  foreground=[('selected', self.COL_PRIMARY)])
        style.configure('TButton', padding=6)
        style.configure('Accent.TButton', background=self.COL_ACCENT,
                        foreground='white', font=('Arial', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', self.COL_PRIMARY)])
        style.configure('Stop.TButton', background=self.COL_BAD,
                        foreground='white', font=('Arial', 10, 'bold'))
        style.map('Stop.TButton', background=[('active', '#a01818')])
        style.configure('Treeview', background='white', fieldbackground='white', rowheight=26)
        style.configure('Treeview.Heading', background=self.COL_PRIMARY,
                        foreground='white', font=('Arial', 10, 'bold'))
        style.configure('TProgressbar', background=self.COL_ACCENT, troughcolor='#d6e0d6')

        self.root.configure(bg=self.COL_BG)

    def create_widgets(self):
        """Crea l'interfaccia grafica (sola UI)."""
        self.setup_style()

        # Header
        header = tk.Frame(self.root, bg=self.COL_HEADER, height=58)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)
        tk.Label(header, text="🌱 AeroGreenHouse", bg=self.COL_HEADER, fg="white",
                 font=('Arial', 18, 'bold')).pack(side=tk.LEFT, padx=18)
        self.header_clock = tk.Label(header, text="", bg=self.COL_HEADER,
                                     fg="#c8e6c9", font=('Arial', 11))
        self.header_clock.pack(side=tk.RIGHT, padx=18)

        # Notebook (tab widget)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Riepilogo (sintesi di tutte le altre schede)
        riepilogo_frame = ttk.Frame(notebook)
        notebook.add(riepilogo_frame, text="Riepilogo")
        self.create_riepilogo_tab(riepilogo_frame)

        # Tab 2: Configurazione (generalità)
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configurazione")
        self.create_config_tab(config_frame)

        # Tab 3: Processi Attivi
        status_frame = ttk.Frame(notebook)
        notebook.add(status_frame, text="Processi Attivi")
        self.create_status_tab(status_frame)

        # Tab 4: Gestione Job
        jobs_frame = ttk.Frame(notebook)
        notebook.add(jobs_frame, text="Gestione Job")
        self.create_jobs_tab(jobs_frame)

        # Tab 5: TH and VPD (ambient)
        ambient_frame = ttk.Frame(notebook)
        notebook.add(ambient_frame, text="Ambient")
        self.create_ambient_tab(ambient_frame)

        # Tab 6: IR controller
        ir_frame = ttk.Frame(notebook)
        notebook.add(ir_frame, text="Climatizzatore")
        self.create_climatizzatore_tab(ir_frame)

        # Tab 7: Livelli Serbatoio
        tank_frame = ttk.Frame(notebook)
        notebook.add(tank_frame, text="Livelli Serbatoio")
        self.create_tank_tab(tank_frame)

        # Tab 8: Spettrometro (MCARI2)
        spectro_frame = ttk.Frame(notebook)
        notebook.add(spectro_frame, text="Spettrometro")
        self.create_spectro_tab(spectro_frame)

        # Tab 9: Crescita (altezza pianta)
        growth_frame = ttk.Frame(notebook)
        notebook.add(growth_frame, text="Crescita")
        self.create_growth_tab(growth_frame)

        # Tab 10: Output/Log
        output_frame = ttk.Frame(notebook)
        notebook.add(output_frame, text="Output/Log")
        self.create_output_tab(output_frame)

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

        inner = ttk.Frame(canvas)
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
    # Tab: Configurazione
    # ------------------------------------------------------------------
    def create_config_tab(self, parent):
        """Tab per modificare la configurazione"""
        # Il contenuto e' piu' alto della finestra: va reso scrollabile.
        # Da qui in poi `parent` e' l'area interna scrollabile.
        parent, config_canvas = self._make_scrollable(parent)

        # Frame per T_var
        t_frame = ttk.LabelFrame(parent, text="Variabili Temperatura", padding=10)
        t_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(t_frame, text="T_opt (°C):").grid(row=0, column=0, sticky=tk.W)
        self.t_opt_var = tk.StringVar(value=str(self.config.get('T_var', {}).get('Topt', 18)))
        ttk.Entry(t_frame, textvariable=self.t_opt_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(t_frame, text="H_opt (%):").grid(row=0, column=2, sticky=tk.W)
        self.h_opt_var = tk.StringVar(value=str(self.config.get('T_var', {}).get('Hopt', 65)))
        ttk.Entry(t_frame, textvariable=self.h_opt_var, width=10).grid(row=0, column=3, sticky=tk.W)

        # Frame per DHT22
        dht_frame = ttk.LabelFrame(parent, text="DHT22 Sensor", padding=10)
        dht_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(dht_frame, text="Pin:").grid(row=0, column=0, sticky=tk.W)
        self.dht_pin_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('pin', 27)))
        ttk.Entry(dht_frame, textvariable=self.dht_pin_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(dht_frame, text="Intervallo Lettura (s):").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.dht_interval_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('read_interval', 5)))
        ttk.Entry(dht_frame, textvariable=self.dht_interval_var, width=10).grid(row=0, column=3, sticky=tk.W)

        # Frame per IR Control
        ir_frame = ttk.LabelFrame(parent, text="IR Control (Condizionatore)", padding=10)
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

        # Frame per Serbatoio (Tank)
        tank_cfg_frame = ttk.LabelFrame(parent, text="Serbatoio (Tank) — sensore ultrasonico HC-SR04", padding=10)
        tank_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        tank = self.config.get('tank', {})

        ttk.Label(tank_cfg_frame, text="TRIG Pin GPIO:").grid(row=0, column=0, sticky=tk.W)
        self.tank_trig_var = tk.StringVar(value=str(tank.get('trig_pin', 23)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_trig_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(tank_cfg_frame, text="ECHO Pin GPIO:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.tank_echo_var = tk.StringVar(value=str(tank.get('echo_pin', 24)))
        ttk.Entry(tank_cfg_frame, textvariable=self.tank_echo_var, width=10).grid(row=0, column=3, sticky=tk.W)

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
        spectro_cfg_frame = ttk.LabelFrame(parent, text="Spettrometro (AS7265x) — indice MCARI2", padding=10)
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
        growth_cfg_frame = ttk.LabelFrame(
            parent, text="Crescita (altezza pianta) — sensore ultrasonico HC-SR04", padding=10)
        growth_cfg_frame.pack(fill=tk.X, padx=10, pady=10)

        g = self.config.get('plant_growth', {})

        ttk.Label(growth_cfg_frame, text="Altezza riferimento (cm):").grid(row=0, column=0, sticky=tk.W)
        self.growth_ref_var = tk.StringVar(value=str(g.get('reference_height_cm', 70.0)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_ref_var, width=10).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(growth_cfg_frame, text="(impostata dal bottone 📐 Calibrazione nella tab Crescita)",
                  foreground='gray').grid(row=0, column=2, columnspan=2, sticky=tk.W, padx=(20, 0))

        ttk.Label(growth_cfg_frame, text="TRIG Pin GPIO:").grid(row=1, column=0, sticky=tk.W)
        self.growth_trig_var = tk.StringVar(value=str(g.get('trig_pin', 5)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_trig_var, width=10).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(growth_cfg_frame, text="ECHO Pin GPIO:").grid(row=1, column=2, sticky=tk.W, padx=(20, 0))
        self.growth_echo_var = tk.StringVar(value=str(g.get('echo_pin', 6)))
        ttk.Entry(growth_cfg_frame, textvariable=self.growth_echo_var, width=10).grid(row=1, column=3, sticky=tk.W)

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

        # Frame per Log
        log_frame = ttk.LabelFrame(parent, text="Impostazioni Log", padding=10)
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
        reload_frame = ttk.LabelFrame(parent, text="Impostazioni Sistema", padding=10)
        reload_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(reload_frame, text="Config Reload Interval (s):").grid(row=0, column=0, sticky=tk.W)
        self.reload_interval_var = tk.StringVar(value=str(self.config.get('config_reload_interval', 4)))
        ttk.Entry(reload_frame, textvariable=self.reload_interval_var, width=10).grid(row=0, column=1, sticky=tk.W)

        # Bottone Salva
        btn_frame = ttk.Frame(parent)
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

        grid = ttk.Frame(parent)
        grid.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform='riep')
        grid.rowconfigure(0, weight=3)
        grid.rowconfigure(1, weight=2)

        # --- Riga 0: i tre sensori con un fondo scala naturale ---
        self.riep_amb_gauge, self.riep_amb_labels, self.riep_amb_date = self._build_riep_card(
            grid, 0, 0, "Ambiente", ("Temperatura", "VPD"))

        self.riep_tank_gauge, self.riep_tank_labels, self.riep_tank_date = self._build_riep_card(
            grid, 0, 1, "Serbatoio", ("Volume",))

        self.riep_mcari_gauge, self.riep_mcari_labels, self.riep_mcari_date = self._build_riep_card(
            grid, 0, 2, "Indice MCARI2", ("Stato",))

        # --- Riga 1: crescita (numero grande) e processi attivi ---
        growth_card = ttk.LabelFrame(grid, text="Crescita", padding=10)
        growth_card.grid(row=1, column=0, sticky=tk.NSEW, padx=5, pady=5)
        inner = ttk.Frame(growth_card)
        inner.pack(expand=True)
        ttk.Label(inner, text="Altezza pianta", font=('Arial', 12, 'bold')).pack()
        self.riep_growth_value = ttk.Label(inner, text="--", font=('Arial', 30, 'bold'),
                                           foreground=self.COL_PRIMARY)
        self.riep_growth_value.pack()
        self.riep_growth_date = ttk.Label(inner, text="Nessuna misura", font=('Arial', 9, 'italic'),
                                          foreground='gray')
        self.riep_growth_date.pack(pady=(4, 0))

        proc_card = ttk.LabelFrame(grid, text="Processi Attivi", padding=10)
        proc_card.grid(row=1, column=1, columnspan=2, sticky=tk.NSEW, padx=5, pady=5)
        self.riep_proc_frame = ttk.Frame(proc_card)
        self.riep_proc_frame.pack(fill=tk.BOTH, expand=True)
        # Il ciclo di aggiornamento parte da __init__, con gli altri poller.

    def _build_riep_card(self, grid, row, col, titolo, campi):
        """
        Crea un blocco del Riepilogo: arco + valori testuali + data.

        :param campi: etichette dei valori testuali sotto l'arco
        :return: (canvas dell'arco, dict {campo: label del valore}, label della data)
        """
        card = ttk.LabelFrame(grid, text=titolo, padding=10)
        card.grid(row=row, column=col, sticky=tk.NSEW, padx=5, pady=5)

        canvas = tk.Canvas(card, height=110, highlightthickness=0, bg=self.COL_BG)
        canvas.pack(fill=tk.X)
        canvas.bind('<Configure>', lambda e: self.refresh_riepilogo_tab(force=True))

        labels = {}
        for campo in campi:
            riga = ttk.Frame(card)
            riga.pack(fill=tk.X, pady=1)
            ttk.Label(riga, text=f"{campo}:", font=('Arial', 10)).pack(side=tk.LEFT)
            valore = ttk.Label(riga, text="--", font=('Arial', 12, 'bold'))
            valore.pack(side=tk.RIGHT)
            labels[campo] = valore

        data = ttk.Label(card, text="Nessuna misura", font=('Arial', 9, 'italic'),
                         foreground='gray')
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

        spessore = 16
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
                          outline='#d0d8d0', width=spessore)

        # Arco del valore
        if value is not None and vmax > vmin:
            frazione = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
            if frazione > 0:
                canvas.create_arc(*box, start=180, extent=-180 * frazione, style=tk.ARC,
                                  outline=color, width=spessore)

        # Valore al centro
        cx = x0 + lato / 2
        cy = y0 + lato / 2
        canvas.create_text(cx, cy - 8, text=testo, font=('Arial', 20, 'bold'),
                           fill=color if value is not None else 'gray')
        if unita:
            canvas.create_text(cx, cy + 12, text=unita, font=('Arial', 9), fill='gray')

        # Etichette di fondo scala
        canvas.create_text(x0 + spessore / 2, cy + 12, text=self._fmt_scala(vmin),
                           font=('Arial', 8), fill='#666666')
        canvas.create_text(x0 + lato - spessore / 2, cy + 12, text=self._fmt_scala(vmax),
                           font=('Arial', 8), fill='#666666')

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
                             '#ff7f0e', f"{r['humidity']:.1f}", "Umidità (%)")
        self.riep_amb_labels['Temperatura'].config(text=f"{r['temperature']:.1f} °C",
                                                   foreground='#207abb')
        self.riep_amb_labels['VPD'].config(text=f"{r['vpd']:.4f} kPa", foreground='#2ca02c')
        self.riep_amb_date.config(text=f"Acquisito: {self._format_acq_date(r['timestamp'])}")

    def _refresh_riep_serbatoio(self, force):
        """Blocco Serbatoio: arco sul riempimento, numero per il volume."""
        r = self.ah.tank.last_result
        if not self._cambiato('serbatoio', None if r is None else tuple(r.values()), force):
            return

        if r is None:
            self._draw_arc_gauge(self.riep_tank_gauge, None, 0, 100, 'gray', "--", "Riempimento (%)")
            return

        # Il colore segue il livello: sotto un quarto la tanica va riempita
        fill = r['fill_percent']
        colore = self.COL_BAD if fill < 25 else (self.COL_WARN if fill < 50 else '#207abb')
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

        colore = self.MCARI2_COLORS.get(r['stato'], 'gray')
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
            self.riep_growth_value.config(text="--", foreground='gray')
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
                      font=('Arial', 11, 'italic'), foreground='gray').pack(anchor=tk.W, pady=4)
            return

        for nome in attivi:
            riga = ttk.Frame(self.riep_proc_frame)
            riga.pack(fill=tk.X, pady=2)
            spia = tk.Canvas(riga, width=16, height=16, highlightthickness=0, bg=self.COL_BG)
            spia.pack(side=tk.LEFT, padx=(2, 10))
            spia.create_oval(3, 3, 13, 13, fill=self.COL_OK, outline="#555555")
            ttk.Label(riga, text=nome, font=('Arial', 11)).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Tab: Processi Attivi
    # ------------------------------------------------------------------
    def create_status_tab(self, parent):
        """Tab che mostra lo stato (verde=attivo / rosso=fermo) dei processi."""
        container = ttk.LabelFrame(parent, text="Stato dei Processi", padding=15)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Legenda
        legend = ttk.Frame(container)
        legend.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(legend, text="●  Attivo", foreground=self.COL_OK,
                  font=('Arial', 11, 'bold')).pack(side=tk.LEFT, padx=(2, 20))
        ttk.Label(legend, text="●  Fermo", foreground=self.COL_BAD,
                  font=('Arial', 11, 'bold')).pack(side=tk.LEFT)

        # Contenitore delle righe (ricostruito quando cambia l'elenco processi)
        self.status_rows_frame = ttk.Frame(container)
        self.status_rows_frame.pack(fill=tk.BOTH, expand=True)

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
        states.append(("Lettura Spettrometro", self.ah.spectro.is_running()))
        states.append(("Misura Crescita", self.ah.plant_growth.is_running()))
        return states

    def _rebuild_status_rows(self, keys):
        """(Ri)crea le righe della tab Processi Attivi."""
        for child in self.status_rows_frame.winfo_children():
            child.destroy()
        self.status_indicators = {}

        for k in keys:
            row = ttk.Frame(self.status_rows_frame)
            row.pack(fill=tk.X, pady=5)

            canvas = tk.Canvas(row, width=22, height=22, highlightthickness=0, bg=self.COL_BG)
            canvas.pack(side=tk.LEFT, padx=(6, 14))
            oval = canvas.create_oval(4, 4, 18, 18, fill=self.COL_BAD, outline="#555555")

            ttk.Label(row, text=k, font=('Arial', 12)).pack(side=tk.LEFT)

            state_lbl = ttk.Label(row, text="Fermo", font=('Arial', 11, 'italic'),
                                  foreground=self.COL_BAD)
            state_lbl.pack(side=tk.RIGHT, padx=10)

            self.status_indicators[k] = (canvas, oval, state_lbl)

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
            state_lbl.config(text="Attivo" if active else "Fermo", foreground=color)

        self.root.after(1000, self.refresh_status_tab)

    # ------------------------------------------------------------------
    # Tab: Gestione Job
    # ------------------------------------------------------------------
    def create_jobs_tab(self, parent):
        """Tab per gestire i job (GPIO pins)"""
        # Frame lista job
        list_frame = ttk.LabelFrame(parent, text="Job Attuali", padding=10)
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
        btn_frame = ttk.LabelFrame(parent, text="Gestione Job", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="➕ Nuovo Job", command=self.add_job_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ Elimina Job", command=self.delete_job).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✏️ Modifica Job", command=self.edit_job_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Ricarica Lista", command=self.refresh_jobs_list).pack(side=tk.LEFT, padx=5)

        # Frame per attivazione/disattivazione
        toggle_frame = ttk.LabelFrame(parent, text="Controllo Job", padding=10)
        toggle_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(toggle_frame, text="✅ Attiva Job", style='Accent.TButton',
                   command=self.toggle_job_on).pack(side=tk.LEFT, padx=5)
        ttk.Button(toggle_frame, text="❌ Disattiva Job", style='Stop.TButton',
                   command=self.toggle_job_off).pack(side=tk.LEFT, padx=5)

    def create_output_tab(self, parent):
        """Tab per visualizzare gli output del terminale e log"""
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="🔄 Aggiorna", command=self.refresh_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Pulisci Output", command=self.clear_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📂 Apri File Log", command=self.open_log_file).pack(side=tk.LEFT, padx=5)

        # Info sul file log
        info_frame = ttk.Frame(parent)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(info_frame, text="File Log:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
        self.log_file_label = ttk.Label(info_frame, text="", foreground="blue")
        self.log_file_label.pack(side=tk.LEFT, padx=5)

        # Frame per il testo (output)
        text_frame = ttk.LabelFrame(parent, text="Output Terminale", padding=5)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Text widget con scrollbar
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.output_text = tk.Text(text_frame, yscrollcommand=scrollbar.set,
                                   wrap=tk.WORD, font=('Courier', 9), height=20,
                                   bg="#1e1e1e", fg="#dcdcdc", insertbackground="white")
        self.output_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.output_text.yview)

        # Configura i tag per i colori
        self.output_text.tag_config('info', foreground='#73d216')
        self.output_text.tag_config('warning', foreground='#fcaf3e')
        self.output_text.tag_config('error', foreground='#ef5350')
        self.output_text.tag_config('debug', foreground='#9e9e9e')

        # Aggiorna il label con il file log
        self.update_log_file_label()

        # Carica il contenuto iniziale
        self.refresh_output()

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

            # Sezione serbatoio (tank)
            self.config.setdefault('tank', {})
            self.config['tank']['trig_pin'] = int(self.tank_trig_var.get())
            self.config['tank']['echo_pin'] = int(self.tank_echo_var.get())
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
            self.config['plant_growth']['trig_pin'] = int(self.growth_trig_var.get())
            self.config['plant_growth']['echo_pin'] = int(self.growth_echo_var.get())
            self.config['plant_growth']['read_interval_days'] = float(self.growth_interval_var.get())
            self.config['plant_growth']['n_samples'] = int(self.growth_nsamples_var.get())
            self.config['plant_growth']['decimals'] = int(self.growth_decimals_var.get())
            self.config['plant_growth']['history_len'] = int(self.growth_history_var.get())
            self.config['plant_growth']['saving_dir'] = self.growth_dir_var.get()

            self.save_config()
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

        tank = self.config.get('tank', {})
        self.tank_trig_var.set(str(tank.get('trig_pin', 23)))
        self.tank_echo_var.set(str(tank.get('echo_pin', 24)))
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
        self.growth_trig_var.set(str(g.get('trig_pin', 5)))
        self.growth_echo_var.set(str(g.get('echo_pin', 6)))
        self.growth_interval_var.set(str(g.get('read_interval_days', 1)))
        self.growth_nsamples_var.set(str(g.get('n_samples', 3)))
        self.growth_decimals_var.set(str(g.get('decimals', 1)))
        self.growth_history_var.set(str(g.get('history_len', 30)))
        self.growth_dir_var.set(g.get('saving_dir', '/home/fishnplants/Desktop/data/GROWTH/'))

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
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_ambient_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_ambient_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📊 Leggi Adesso", command=self.read_ambient_now).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = ttk.LabelFrame(parent, text="AMBIENT", padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Crea un frame interno per centrare il contenuto
        inner_frame = ttk.Frame(main_frame)
        inner_frame.pack(expand=True)

        # Temperatura
        temp_frame = ttk.Frame(inner_frame)
        temp_frame.pack(pady=10)
        ttk.Label(temp_frame, text="Temperatura", font=('Arial', 16, 'bold')).pack()
        self.ambient_temp_label = ttk.Label(temp_frame, text="-- °C", font=('Arial', 24, 'bold'), foreground="#207abb")
        self.ambient_temp_label.pack()

        # Umidità
        humid_frame = ttk.Frame(inner_frame)
        humid_frame.pack(pady=10)
        ttk.Label(humid_frame, text="Umidità", font=('Arial', 16, 'bold')).pack()
        self.ambient_humid_label = ttk.Label(humid_frame, text="-- %", font=('Arial', 24, 'bold'), foreground='#ff7f0e')
        self.ambient_humid_label.pack()

        # VPD
        vpd_frame = ttk.Frame(inner_frame)
        vpd_frame.pack(pady=10)
        ttk.Label(vpd_frame, text="VPD", font=('Arial', 16, 'bold')).pack()
        self.ambient_vpd_label = ttk.Label(vpd_frame, text="-- kPa", font=('Arial', 24, 'bold'), foreground='#2ca02c')
        self.ambient_vpd_label.pack()

        # Timestamp della lettura
        self.ambient_timestamp_label = ttk.Label(inner_frame, text="Ultimo aggiornamento: --",
                                                 font=('Arial', 12, 'italic'), foreground='gray')
        self.ambient_timestamp_label.pack(pady=20)

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

        # Unica sezione: Sistema di Controllo AC
        ac_frame = ttk.LabelFrame(parent, text="Sistema di Controllo AC", padding=20)
        ac_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(ac_frame)
        inner.pack(expand=True)

        # Indicatore di stato
        ttk.Label(inner, text="Stato Controllo AC", font=('Arial', 14, 'bold')).pack(pady=(10, 5))
        self.ac_status_label = ttk.Label(
            inner, text="⏹ INATTIVO", font=('Arial', 20, 'bold'), foreground='gray'
        )
        self.ac_status_label.pack(pady=10)

        # Info parametri correnti
        params_frame = ttk.Frame(inner)
        params_frame.pack(pady=10)

        ttk.Label(params_frame, text="T_opt:", font=('Arial', 12)).grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ac_topt_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('T_max', '--')} °C",
            font=('Arial', 12, 'bold'), foreground='#207abb'
        )
        self.ac_topt_label.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="H_opt:", font=('Arial', 12)).grid(row=0, column=2, sticky=tk.W, padx=15)
        self.ac_hopt_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('H_max', '--')} %",
            font=('Arial', 12, 'bold'), foreground='#ff7f0e'
        )
        self.ac_hopt_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="Tempo max ON:", font=('Arial', 12)).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.ac_tmax_label = ttk.Label(
            params_frame,
            text=f"{self.config.get('ir_control', {}).get('time_max_on', '--')} min",
            font=('Arial', 12, 'bold')
        )
        self.ac_tmax_label.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(params_frame, text="Ultimo comando:", font=('Arial', 12)).grid(row=1, column=2, sticky=tk.W, padx=15)
        self.ac_last_cmd_label = ttk.Label(
            params_frame, text="--", font=('Arial', 12, 'bold'), foreground='#2ca02c'
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
        self.ac_status_label.config(text="▶ ATTIVO", foreground='green')

    def stop_ac_control(self):
        """Arresta immediatamente il controllo automatico del condizionatore."""
        stopped = self.ah.climate.stop()
        if not stopped:
            messagebox.showwarning("Avviso", "Il controllo AC non è attivo.")
            return

        # Aggiorna UI
        self.ac_status_label.config(text="⏹ INATTIVO", foreground='gray')
        self.ac_last_cmd_label.config(text="off")

    # ------------------------------------------------------------------
    # Tab: Livelli Serbatoio (wrapper sottili → TankManager)
    # ------------------------------------------------------------------
    def create_tank_tab(self, parent):
        """Tab per monitorare il livello dell'acqua nel serbatoio."""
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_tank_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_tank_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📊 Leggi Adesso", command=self.read_tank_now).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = ttk.LabelFrame(parent, text="LIVELLI SERBATOIO", padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(expand=True, fill=tk.X)

        # Volume (valore principale)
        vol_frame = ttk.Frame(inner)
        vol_frame.pack(pady=10)
        ttk.Label(vol_frame, text="Volume", font=('Arial', 16, 'bold')).pack()
        self.tank_volume_label = ttk.Label(vol_frame, text="-- L", font=('Arial', 28, 'bold'), foreground='#207abb')
        self.tank_volume_label.pack()

        # Barra di riempimento
        pb_frame = ttk.Frame(inner)
        pb_frame.pack(pady=10)
        self.tank_fill_var = tk.DoubleVar(value=0)
        self.tank_progress = ttk.Progressbar(pb_frame, orient=tk.HORIZONTAL, length=420,
                                             mode='determinate', variable=self.tank_fill_var, maximum=100)
        self.tank_progress.pack()
        self.tank_fill_label = ttk.Label(inner, text="Riempimento: -- %", font=('Arial', 14, 'bold'), foreground='#2ca02c')
        self.tank_fill_label.pack(pady=5)

        # Valori secondari
        sec = ttk.Frame(inner)
        sec.pack(pady=10)
        ttk.Label(sec, text="Livello:", font=('Arial', 12)).grid(row=0, column=0, sticky=tk.W, padx=5)
        self.tank_level_label = ttk.Label(sec, text="-- cm", font=('Arial', 12, 'bold'))
        self.tank_level_label.grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(sec, text="Distanza:", font=('Arial', 12)).grid(row=0, column=2, sticky=tk.W, padx=15)
        self.tank_dist_label = ttk.Label(sec, text="-- cm", font=('Arial', 12, 'bold'))
        self.tank_dist_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        # Timestamp della lettura
        self.tank_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                             font=('Arial', 12, 'italic'), foreground='gray')
        self.tank_timestamp_label.pack(pady=15)

        ttk.Label(inner, text="⚠️ Sensore ancora da tarare (parametri nella tab Configurazione)",
                  foreground='#b26a00', font=('Arial', 10, 'italic')).pack()

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
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="🔬 Misura Adesso", command=self.read_spectro_now).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_spectro_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_spectro_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⚪ Taratura (rif. bianco)",
                   command=self.calibrate_spectro).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = ttk.LabelFrame(parent, text="INDICE MCARI2", padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(fill=tk.BOTH, expand=True)

        # Valore dell'indice (valore principale)
        val_frame = ttk.Frame(inner)
        val_frame.pack(pady=5)
        ttk.Label(val_frame, text="MCARI2", font=('Arial', 16, 'bold')).pack()
        self.spectro_value_label = ttk.Label(val_frame, text="--", font=('Arial', 28, 'bold'),
                                             foreground='#207abb')
        self.spectro_value_label.pack()

        # Indicatore dello stato della pianta (spia + testo)
        state_frame = ttk.Frame(inner)
        state_frame.pack(pady=10)
        self.spectro_canvas = tk.Canvas(state_frame, width=28, height=28,
                                        highlightthickness=0, bg=self.COL_BG)
        self.spectro_canvas.pack(side=tk.LEFT, padx=(0, 10))
        self.spectro_oval = self.spectro_canvas.create_oval(4, 4, 24, 24,
                                                            fill='gray', outline="#555555")
        self.spectro_state_label = ttk.Label(state_frame, text="Nessuna misura disponibile",
                                             font=('Arial', 14, 'bold'), foreground='gray')
        self.spectro_state_label.pack(side=tk.LEFT)

        # Timestamp della lettura
        self.spectro_timestamp_label = ttk.Label(inner, text="Ultimo aggiornamento: --",
                                                 font=('Arial', 12, 'italic'), foreground='gray')
        self.spectro_timestamp_label.pack(pady=5)

        # Storico delle misure
        hist_frame = ttk.LabelFrame(inner, text="Storico Misure", padding=5)
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
        color = self.MCARI2_COLORS.get(result['stato'], 'gray')
        self.spectro_value_label.config(text=f"{result['mcari2']:.4f}", foreground=color)
        self.spectro_canvas.itemconfig(self.spectro_oval, fill=color)
        self.spectro_state_label.config(text=result['testo'], foreground=color)
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
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="📏 Misura Adesso", command=self.read_growth_now).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="▶️ Attiva Lettura", style='Accent.TButton',
                   command=self.start_growth_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", style='Stop.TButton',
                   command=self.stop_growth_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📐 Calibrazione",
                   command=self.calibrate_growth).pack(side=tk.LEFT, padx=5)

        # Frame principale per i dati
        main_frame = ttk.LabelFrame(parent, text="ALTEZZA PIANTA", padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inner = ttk.Frame(main_frame)
        inner.pack(fill=tk.BOTH, expand=True)

        # Altezza dell'ultima misura (valore principale)
        val_frame = ttk.Frame(inner)
        val_frame.pack(pady=5)
        ttk.Label(val_frame, text="h_plant", font=('Arial', 16, 'bold')).pack()
        self.growth_value_label = ttk.Label(val_frame, text="--", font=('Arial', 28, 'bold'),
                                            foreground=self.COL_PRIMARY)
        self.growth_value_label.pack()

        # Timestamp della lettura
        self.growth_timestamp_label = ttk.Label(inner, text="Ultima misurazione: --",
                                                font=('Arial', 12, 'italic'), foreground='gray')
        self.growth_timestamp_label.pack(pady=5)

        # Andamento nel tempo: Canvas nativo (nessuna dipendenza da matplotlib,
        # i punti sono pochi perche' la misura e' ogni N giorni)
        chart_frame = ttk.LabelFrame(inner, text="Andamento nel tempo", padding=5)
        chart_frame.pack(fill=tk.X, pady=10)
        self.growth_canvas = tk.Canvas(chart_frame, height=180, highlightthickness=0,
                                       bg='white')
        self.growth_canvas.pack(fill=tk.X, expand=True)
        self.growth_canvas.bind('<Configure>', lambda e: self._draw_growth_chart())

        # Storico delle misure
        hist_frame = ttk.LabelFrame(inner, text="Storico Misure", padding=5)
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
                               fill='gray', font=('Arial', 11, 'italic'))
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
        canvas.create_line(x0, y0, x0, y1, fill='#999999')
        canvas.create_line(x0, y1, x1, y1, fill='#999999')

        # Etichette in cm (min, medio, max)
        for frac in (0.0, 0.5, 1.0):
            value = h_min + (h_max - h_min) * frac
            y = y1 - (y1 - y0) * frac
            canvas.create_text(x0 - 5, y, text=f"{value:.1f}", anchor=tk.E,
                               fill='#666666', font=('Arial', 8))
            if frac > 0:  # Griglia orizzontale leggera
                canvas.create_line(x0, y, x1, y, fill='#e4e4e4')

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
                           anchor=tk.W, fill='#666666', font=('Arial', 8))
        canvas.create_text(x1, y1 + 12, text=self._short_date(history[-1]['timestamp']),
                           anchor=tk.E, fill='#666666', font=('Arial', 8))

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


if __name__ == "__main__":
    try:
        root = tk.Tk()
        gui = AeroGreenHouseGUI(root)
        root.mainloop()
    except KeyboardInterrupt:
        gui.ah.cleanup_gpios()
        print('Job forced to stop')
