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
        self.COL_TEXT = "#1f2d27"

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

        # Tab 1: Configurazione (generalità)
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configurazione")
        self.create_config_tab(config_frame)

        # Tab 2: Processi Attivi (nuova, subito dopo le generalità)
        status_frame = ttk.Frame(notebook)
        notebook.add(status_frame, text="Processi Attivi")
        self.create_status_tab(status_frame)

        # Tab 3: Gestione Job
        jobs_frame = ttk.Frame(notebook)
        notebook.add(jobs_frame, text="Gestione Job")
        self.create_jobs_tab(jobs_frame)

        # Tab 4: TH and VPD (ambient)
        ambient_frame = ttk.Frame(notebook)
        notebook.add(ambient_frame, text="Ambient")
        self.create_ambient_tab(ambient_frame)

        # Tab 5: IR controller
        ir_frame = ttk.Frame(notebook)
        notebook.add(ir_frame, text="Climatizzatore")
        self.create_climatizzatore_tab(ir_frame)

        # Tab 6: Livelli Serbatoio (nuova)
        tank_frame = ttk.Frame(notebook)
        notebook.add(tank_frame, text="Livelli Serbatoio")
        self.create_tank_tab(tank_frame)

        # Tab 7: Output/Log
        output_frame = ttk.Frame(notebook)
        notebook.add(output_frame, text="Output/Log")
        self.create_output_tab(output_frame)

    def _update_clock(self):
        """Aggiorna l'orologio nell'header."""
        self.header_clock.config(text=datetime.now().strftime("%d/%m/%Y   %H:%M:%S"))
        self.root.after(1000, self._update_clock)

    # ------------------------------------------------------------------
    # Tab: Configurazione
    # ------------------------------------------------------------------
    def create_config_tab(self, parent):
        """Tab per modificare la configurazione"""
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


if __name__ == "__main__":
    try:
        root = tk.Tk()
        gui = AeroGreenHouseGUI(root)
        root.mainloop()
    except KeyboardInterrupt:
        gui.ah.cleanup_gpios()
        print('Job forced to stop')
