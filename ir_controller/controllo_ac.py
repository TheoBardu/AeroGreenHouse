import pigpio
import piir
import time
import os
# import pandas as pd

MAIN_DIR = "/home/fishnplants/Desktop/codes/python/AeroGreenHouse/ir_controller/"
DATA_TH_DIR = "/home/fishnplants/Desktop/data/TH/"

os.chdir(MAIN_DIR)


def check_air_conditioner():
    l = sorted(os.listdir(DATA_TH_DIR))

    fid = open(DATA_TH_DIR+l[-1],'r')
    lines = fid.readlines()
    last_line = lines[-1].split()
    # print(last_line)
    T = float(last_line[2].split('°')[0])
    H = float(last_line[3].split('%')[0])
    # print(T,H)
    fid.close()


    trasmission_pin = 20


    if T < 26.0:
        os.system(f"piir play --gpio {trasmission_pin} -f ac_remote.json T22")
        print("T22 command Sent")
    else:
        os.system(f"piir play --gpio {trasmission_pin} -f ac_remote.json off")
        print("OFF command Sent")
    

try:
    while True:
        check_air_conditioner()
        time.sleep(1)
except KeyboardInterrupt:
    print('Ending program')


