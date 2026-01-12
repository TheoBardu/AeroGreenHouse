import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yaml
import json
import os
import sys
from pathlib import Path
from helper_aeroGreenHouse import aeroHelper
import schedule
import threading
from time import sleep
import logging
from queue import Queue


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
        self.root.geometry("1000x700")
        
        self.config_file = 'config.yaml'
        self.config = self.load_config()
        self.active_jobs = {}  # Per tracciare i job attivi/inattivi
        
        # Thread tracking for active jobs
        self.job_threads = {}  # {job_name: thread_object}
        self.job_stop_flags = {}  # {job_name: stop_flag}
        self.thread_lock = threading.Lock()  # For thread-safe operations
        
        # Thread tracking for ambient reading
        self.ambient_thread = None
        self.ambient_stop_flag = False
        
        # Logging queue for GUI updates
        self.log_queue = Queue()
        
        self.create_widgets()
        self.refresh_jobs_list()
        self.ah = aeroHelper()
        
        # Setup GUI logging handler
        self.setup_gui_logging_handler()
        
        # Start the log queue processor
        self.process_log_queue()
        
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
    
    def create_widgets(self):
        """Crea l'interfaccia grafica"""
        # Notebook (tab widget)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: Configurazione
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configurazione")
        self.create_config_tab(config_frame)
        
        # Tab 2: Gestione Job
        jobs_frame = ttk.Frame(notebook)
        notebook.add(jobs_frame, text="Gestione Job")
        self.create_jobs_tab(jobs_frame)
        
        # Tab 3: Output/Log
        output_frame = ttk.Frame(notebook)
        notebook.add(output_frame, text="Output/Log")
        self.create_output_tab(output_frame)

        # Tab 4: TH and VPD (ambient)
        ambient_frame = ttk.Frame(notebook)
        notebook.add(ambient_frame, text="Ambient")
        self.create_ambient_tab(ambient_frame)
        
    def create_config_tab(self, parent):
        """Tab per modificare la configurazione"""
        # Frame per T_var
        t_frame = ttk.LabelFrame(parent, text="Variabili Temperatura", padding=10)
        t_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(t_frame, text="T_opt (°C):").grid(row=0, column=0, sticky=tk.W)
        self.t_opt_var = tk.StringVar(value=str(self.config.get('T_var', {}).get('Topt', 18)))
        ttk.Entry(t_frame, textvariable=self.t_opt_var, width=10).grid(row=0, column=1, sticky=tk.W)
        
        # Frame per DHT22
        dht_frame = ttk.LabelFrame(parent, text="DHT22 Sensor", padding=10)
        dht_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(dht_frame, text="Pin:").grid(row=0, column=0, sticky=tk.W)
        self.dht_pin_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('pin', 27)))
        ttk.Entry(dht_frame, textvariable=self.dht_pin_var, width=10).grid(row=0, column=1, sticky=tk.W)
        
        ttk.Label(dht_frame, text="Intervallo Lettura (s):").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.dht_interval_var = tk.StringVar(value=str(self.config.get('dht22', {}).get('read_interval', 5)))
        ttk.Entry(dht_frame, textvariable=self.dht_interval_var, width=10).grid(row=0, column=3, sticky=tk.W)
        
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
        
        ttk.Button(btn_frame, text="Salva Configurazione", command=self.save_config_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Ricarica", command=self.reload_config_tab).pack(side=tk.LEFT, padx=5)
    
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
        
        ttk.Button(toggle_frame, text="✅ Attiva Job", command=self.toggle_job_on).pack(side=tk.LEFT, padx=5)
        ttk.Button(toggle_frame, text="❌ Disattiva Job", command=self.toggle_job_off).pack(side=tk.LEFT, padx=5)
        
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
                                    wrap=tk.WORD, font=('Courier', 9), height=20)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.output_text.yview)
        
        # Configura i tag per i colori
        self.output_text.tag_config('info', foreground='green')
        self.output_text.tag_config('warning', foreground='orange')
        self.output_text.tag_config('error', foreground='red')
        self.output_text.tag_config('debug', foreground='gray')
        
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
    

    
    def toggle_job_on(self):
        """Attiva il job selezionato in un thread separato"""
        selected = self.jobs_tree.selection()
        
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da attivare")
            return
        
        # Get the values 
        item = selected[0]
        name = str(self.jobs_tree.item(item, 'values')[0])
        pin = int(self.jobs_tree.item(item, 'values')[1])
        interval = int(self.jobs_tree.item(item, 'values')[2])
        on_time = int(self.jobs_tree.item(item, 'values')[3])

        # parte di codice legata ad AEROPONICS
        if name == 'AEROPONICS':
            
            # check if the job is already running
            if self.ah.aeroponics_job_active:
                messagebox.showwarning("Avviso", f"Il job {name} è già in esecuzione!")
                return
            
            self.ah.aeroponics_job_active = True # set to True the aeroponics activation value

            job_thread_aeroponics = threading.Thread(target=self.ah.activate_aeroponics, daemon=True)
            job_thread_aeroponics.start()

            #UI Update
            self.active_jobs[name] = 'Attivo'
        

        # parte di codice legata ad IDROPONICS
        elif name == 'IDROPONICS':

            # check if the job is already running
            if self.ah.idroponics_job_active:
                messagebox.showwarning("Avviso", f"Il job {name} è già in esecuzione!")
                return
            
            self.ah.idroponics_job_active = True # set to True the idroponics activation value

            job_thread_idroponics = threading.Thread(target=self.ah.activate_idroponics, daemon=True)
            job_thread_idroponics.start()
            
            #UI Update
            self.active_jobs[name] = 'Attivo'

        else:
            messagebox.showwarning("Avviso", f"Job '{name}' non riconosciuto per l'attivazione.")
            return
    
        
        # Update UI
        self.refresh_jobs_list()
        # messagebox.showinfo("Successo", f"Job '{name}' attivato!")

    
    def toggle_job_off(self):
        """Disattiva il job selezionato"""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da disattivare")
            return
        
        item = selected[0]
        name = self.jobs_tree.item(item, 'values')[0]
        
        # parte di codice legata ad AEROPONICS
        if name == 'AEROPONICS':
            self.ah.aeroponics_job_active = False # Set the deactivation for aeroponics job
            self.active_jobs[name] = 'Inattivo'
        
        elif name == 'IDROPONICS':
            self.ah.idroponics_job_active = False # Set the deactivation for idroponics job
            self.active_jobs[name] = 'Inattivo'
        else:
            messagebox.showwarning("Avviso", f"Job '{name}' non riconosciuto per la disattivazione.")
            return
        
        # Update UI

        self.refresh_jobs_list()
        # messagebox.showinfo("Successo", f"Job '{name}' disattivato!")
    




    def save_config_changes(self):
        """Salva i cambiamenti della configurazione"""
        try:
            self.config['T_var']['Topt'] = float(self.t_opt_var.get())
            self.config['dht22']['pin'] = int(self.dht_pin_var.get())
            self.config['dht22']['read_interval'] = int(self.dht_interval_var.get())
            self.config['log']['directory'] = self.log_dir_var.get()
            self.config['log']['filename'] = self.log_file_var.get()
            self.config['log']['level'] = self.log_level_var.get()
            self.config['config_reload_interval'] = int(self.reload_interval_var.get())
            
            self.save_config()
        except ValueError:
            messagebox.showerror("Errore", "Inserire valori validi. Verificare i numeri.")
    
    def reload_config_tab(self):
        """Ricarica la configurazione dalla tab"""
        self.config = self.load_config()
        self.t_opt_var.set(str(self.config.get('T_var', {}).get('Topt', 18)))
        self.dht_pin_var.set(str(self.config.get('dht22', {}).get('pin', 27)))
        self.dht_interval_var.set(str(self.config.get('dht22', {}).get('read_interval', 5)))
        self.log_dir_var.set(self.config.get('log', {}).get('directory', ''))
        self.log_file_var.set(self.config.get('log', {}).get('filename', ''))
        self.log_level_var.set(self.config.get('log', {}).get('level', 'INFO'))
        self.reload_interval_var.set(str(self.config.get('config_reload_interval', 4)))
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
    
    def create_ambient_tab(self, parent):
        """Tab per monitorare i dati di temperatura, umidità e VPD"""
        from datetime import datetime
        
        # Frame superiore con bottoni
        btn_frame = ttk.LabelFrame(parent, text="Controlli", padding=10)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(btn_frame, text="▶️ Attiva Lettura", command=self.start_ambient_reading).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="⏹️ Arresta Lettura", command=self.stop_ambient_reading).pack(side=tk.LEFT, padx=5)
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
    
    def start_ambient_reading(self):
        """Avvia la lettura temporizzata dei dati ambient"""
        if self.ambient_thread is not None and self.ambient_thread.is_alive():
            messagebox.showwarning("Avviso", "Lettura ambient già in corso!")
            return
        
        
        
        def ambient_read_loop():
            """Loop per letture periodiche"""
            import time
            from datetime import datetime
            
            interval = self.config.get('dht22', {}).get('read_interval', 5)
            pin = self.config.get('dht22', {}).get('pin', 27)
            
            self.ah.logger.info(f"Inizio lettura AMBIENT. Intervallo: {interval}s, Pin: {pin}")
            
            while not self.ambient_stop_flag:
                try:
                    # Leggi i dati
                    temp, humidity = self.ah.measure_dht22(pin)
                    vpd = self.ah.VPD(temp, humidity)

                    
                    # Ottieni timestamp
                    timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                    file_name = datetime.now().strftime("%Y_%m_%d")
                    

                    # Aggiorna GUI
                    self.ambient_temp_label.config(text=f"{temp:.1f} °C")
                    self.ambient_humid_label.config(text=f"{humidity:.1f} %")
                    self.ambient_vpd_label.config(text=f"{vpd:.2f} kPa")
                    self.ambient_timestamp_label.config(text=f"Ultimo aggiornamento: {timestamp}")
                    
                    self.ah.logger.info(f"AMBIENT: T={temp:.2f}°C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")
                    
                    # salva file
                    format_data_out= "%s\t %5.2f°C\t %5.2f%%\t %5.4fkPa \n"
                    fid = open(self.config.get('dht22', {}).get('saving_dir', '/home/fishnplants/Desktop/data/TH/')+'TH_'+file_name+'.txt','a')
                    fid.write(format_data_out%(timestamp, temp, humidity, vpd))
                    fid.close()


                    # Attendi l'intervallo
                    time.sleep(interval)
                    
                except Exception as e:
                    self.ah.logger.error(f"Errore lettura AMBIENT: {str(e)}")
                    time.sleep(interval)
            
            self.ah.logger.info("Lettura AMBIENT interrotta")
        
        self.ambient_thread = threading.Thread(target=ambient_read_loop, daemon=True)
        self.ambient_thread.start()
        # messagebox.showinfo("Successo", "Lettura ambient avviata!")
    
    def stop_ambient_reading(self):
        """Arresta la lettura temporizzata dei dati ambient"""
        if self.ambient_thread is None or not self.ambient_thread.is_alive():
            messagebox.showwarning("Avviso", "Nessuna lettura in corso")
            return
        
        self.ambient_stop_flag = True
        
        # Attendi che il thread finisca
        timeout = 5
        start_time = threading.Event()
        start_time.set()
        wait_time = 0
        while wait_time < timeout:
            if not self.ambient_thread.is_alive():
                break
            sleep(0.5)
            wait_time += 0.5
        
        messagebox.showinfo("Successo", "Lettura ambient arrestata!")
    
    def read_ambient_now(self):
        """Legge immediatamente i dati ambient"""
        try:
            from datetime import datetime
            
            pin = self.config.get('dht22', {}).get('pin', 27)
            
            # Leggi i dati
            temp, humidity = self.ah.measure_dht22(pin)
            vpd = self.ah.VPD(temp, humidity)
            
            # Ottieni timestamp
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            
            # Aggiorna GUI
            self.ambient_temp_label.config(text=f"{temp:.2f} °C")
            self.ambient_humid_label.config(text=f"{humidity:.2f} %")
            self.ambient_vpd_label.config(text=f"{vpd:.4f} kPa")
            self.ambient_timestamp_label.config(text=f"Ultimo aggiornamento: {timestamp}")
            
            self.ah.logger.info(f"AMBIENT (lettura immediata): T={temp:.2f}°C, H={humidity:.2f}%, VPD={vpd:.4f}kPa")
            messagebox.showinfo("Successo", f"Lettura completata:\nT={temp:.2f}°C\nH={humidity:.2f}%\nVPD={vpd:.4f}kPa")
            
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nella lettura: {str(e)}")
            self.ah.logger.error(f"Errore lettura AMBIENT immediata: {str(e)}")
    
    def open_log_file(self):
        """Apre il file di log nell'editor predefinito"""
        try:
            import sys
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
    
if __name__ == "__main__":
    try:
        root = tk.Tk()
        gui = AeroGreenHouseGUI(root)
        root.mainloop()
    except KeyboardInterrupt:
        gui.ah.cleanup_gpios()
        print('Job forced to stop')

