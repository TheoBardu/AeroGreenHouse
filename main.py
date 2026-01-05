from helper_aeroGreenHouse import aeroHelper
import schedule
from time import sleep
import threading
import datetime

ah = aeroHelper()

def runner(job,*args, **kwargs):
    '''
    Function that runs in multi-thread the AeroSystems jobs
    
    :param job: Name of the function to run
    :param args: Arguments of the function <job>
    :param kwargs: Keyworkds arguments of the function <job>
    '''
    job_thread = threading.Thread(target=job, args=args, kwargs=kwargs)
    job_thread.start()


#Setting up aerophonics
schedule.every(ah.configs['gpio_pins'][0]['interval']).minutes.do(runner, ah.pump_aerophonics, gpio=ah.configs['gpio_pins'][0]['pin'] , irrigation_time=ah.configs['gpio_pins'][0]['on_time'])

#Setting up Idrophonics
schedule.every(ah.configs['gpio_pins'][1]['interval']).minutes.do(runner, ah.pump_idrophonics, gpio_pump = ah.configs['gpio_pins'][1]['pin_pump'], gpio_sensor = ah.configs['gpio_pins'][1]['pin_sensor'], max_irrigation_time = ah.configs['gpio_pins'][1]['on_time'] )


while True:
    schedule.run_pending()
    sleep(1)



