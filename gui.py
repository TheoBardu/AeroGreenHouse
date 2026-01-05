import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yaml
import json
import os
from pathlib import Path

class AeroGreenHouseGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AeroGreenHouse Control Panel")
        self.root.geometry("1000x700")
        
        self.config_file = 'config.yaml'
        self.config = self.load_config()
        self.active_jobs = {}  # Per tracciare i job attivi/inattivi
        
        self.create_widgets()
        self.refresh_jobs_list()
        
    def load_config(self):
        """Carica la configurazione dal file YAML"""
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            messagebox.showerror("Errore", f"Errore nel caricamento del config: {e}")
            return {}
    
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
        """Attiva il job selezionato"""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da attivare")
            return
        
        item = selected[0]
        name = self.jobs_tree.item(item, 'values')[0]
        self.active_jobs[name] = 'Attivo'
        self.refresh_jobs_list()
        messagebox.showinfo("Successo", f"Job '{name}' attivato!")
    
    def toggle_job_off(self):
        """Disattiva il job selezionato"""
        selected = self.jobs_tree.selection()
        if not selected:
            messagebox.showwarning("Avviso", "Selezionare un job da disattivare")
            return
        
        item = selected[0]
        name = self.jobs_tree.item(item, 'values')[0]
        self.active_jobs[name] = 'Inattivo'
        self.refresh_jobs_list()
        messagebox.showinfo("Successo", f"Job '{name}' disattivato!")
    
    def save_config_changes(self):
        """Salva i cambiamenti della configurazione"""
        try:
            self.config['T_var']['Topt'] = float(self.t_opt_var.get())
            self.config['dht22']['pin'] = int(self.dht_pin_var.get())
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
        self.log_dir_var.set(self.config.get('log', {}).get('directory', ''))
        self.log_file_var.set(self.config.get('log', {}).get('filename', ''))
        self.log_level_var.set(self.config.get('log', {}).get('level', 'INFO'))
        self.reload_interval_var.set(str(self.config.get('config_reload_interval', 4)))
        messagebox.showinfo("Successo", "Configurazione ricaricata!")


if __name__ == '__main__':
    root = tk.Tk()
    gui = AeroGreenHouseGUI(root)
    root.mainloop()
