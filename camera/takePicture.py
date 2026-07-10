#! /usr/bin/python
from picamera2 import Picamera2, Preview
from time import sleep
from datetime import datetime
import schedule

file_location = "/home/fishnplants/Desktop/data/IMG/"
name_data_out = '%s.jpg'
when =  ["09:00","13:00", "17:00","20:00"] #time to take the picture
separation_hours = 2 #ogni n ore scatta la foto



def take_picture():
        cam = Picamera2()

        cam_config = cam.create_still_configuration(
                main={"size": cam.sensor_resolution}
                )

        cam.configure(cam_config)
        cam.start()
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        cam.capture_file(f'/home/fishnplants/Desktop/data/IMG/{timestamp}.jpg')
        sleep(1)
        cam.capture_file(f'/home/fishnplants/Desktop/data/IMG/image.jpg')
        
        cam.stop()
        cam.close()
        


# for ora in when:
    # schedule.every().day.at(ora).do(take_picture)
    


schedule.every(separation_hours).hours.do(take_picture)

print(f'Scatto foto ogni {separation_hours}')

while True:
        schedule.run_pending()
        sleep(10)
