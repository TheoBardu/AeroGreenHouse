import schedule

def job_1():
    print('Foo')

def job_2():
    print('Bar')

schedule.every(2).seconds.do(job_1)
schedule.every(3).seconds.do(job_2)

schedule.run_pending()
