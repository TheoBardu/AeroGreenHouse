from helper_aeroGreenHouse import aeroHelper
import schedule
from time import sleep
import threading
import datetime

ah = aeroHelper()


#Setting up aerophonics
aeroJOB = schedule.every(ah.configs['gpio_pins'][0]['interval']).minutes.do(ah.runner, ah.pump_aerophonics, gpio=ah.configs['gpio_pins'][0]['pin'] , irrigation_time=ah.configs['gpio_pins'][0]['on_time'])

#Setting up Idrophonics
idroJOB = schedule.every(ah.configs['gpio_pins'][1]['interval']).minutes.do(ah.runner, ah.pump_idrophonics, gpio_pump = ah.configs['gpio_pins'][1]['pin'], gpio_sensor = ah.configs['gpio_pins'][2]['pin'], max_irrigation_time = ah.configs['gpio_pins'][1]['on_time'] )

try:
    while True:
        schedule.run_pending()
        sleep(1)
except KeyboardInterrupt:
    ah.cleanup_gpios()
    print('Program Terminated')



