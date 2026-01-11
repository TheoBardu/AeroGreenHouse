import schedule
from time import sleep
import threading

def job_1():
    print('Job1')

def job_2():
    print('Job2')



def activate_job1():
    print('Job1 activated')
    schedule_1 = schedule.Scheduler()
    schedule_1.every(2).seconds.do(job_1).tag('j1')

    while active1:
        schedule_1.run_pending()
        sleep(1)
    else:
        print('Job1 Terminated')


def activate_job2():
    print('Job2 activated')
    schedule_2 = schedule.Scheduler()
    schedule_2.every(3).seconds.do(job_2).tag('j2')
    while active2:
        schedule_2.run_pending()
        sleep(1)
    else:
        print('Job 2 Terminated')


try:
    active1 = True
    active2 = True
    activation1 = threading.Thread(target=activate_job1, daemon = True)
    activation2 = threading.Thread(target=activate_job2, daemon = True)
    activation1.start()
    activation2.start()

    sleep(5)

    active1 = False
    sleep(2)
    active2 = False
    sleep(2)
except KeyboardInterrupt:
    print('Job Terminated')


