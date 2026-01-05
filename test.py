from helper_aeroGreenHouse import aeroHelper
import yaml
import schedule
from time import sleep
import threading
import datetime

ah = aeroHelper()
configs = ah.configs
# t = configs['gpio_pins'][0]['interval']

CONFIG_FILE = "config.yaml" #nome del file di configurazione .yaml


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def job1(what):
    config = load_config()
    print(datetime.datetime.now(),config[what])



def run_thread(job, *args, **kwargs):
    job_thread = threading.Thread(target=job, args=args, kwargs=kwargs)
    job_thread.start()



schedule.every(2).seconds.do(run_thread,job1,what='T_var')
schedule.every(3).seconds.do(run_thread,job1,what='dht22')


print(datetime.datetime.now())
while True:
    schedule.run_pending()
    sleep(1)


