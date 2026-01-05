from helper_aeroGreenHouse import aeroHelper
import yaml
import schedule
from time import sleep
import threading
import datetime



ah = aeroHelper()
CONFIG_FILE = "config.yaml" #nome del file di configurazione .yaml


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def job1():
    config = load_config()
    print(datetime.datetime.now(),config['T_var'])

def job2():
    config = load_config()
    print(datetime.datetime.now(), config['dht22'])


def run_thread(job):
    job_thread = threading.Thread(target = job)
    job_thread.start()



schedule.every(2).seconds.do(run_thread,job1)
schedule.every(3).seconds.do(run_thread,job2)

print(datetime.datetime.now())
while True:
    schedule.run_pending()
    sleep(1)


