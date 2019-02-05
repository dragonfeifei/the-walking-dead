#!/usr/bin/env python
from kazoo.client import KazooClient

import subprocess
import socket
import signal
import sys

name = socket.gethostname()
scheduler = None

def on_exit(signum, frame):
    global scheduler
    print scheduler
    if scheduler:
        scheduler.terminate()
	output = scheduler.wait()
        print("Scheduler was killed with output: " + str(output))
    sys.exit(0)

def start_scheduler():
    print(name + " becomes master!")
    global scheduler
    scheduler = subprocess.Popen(["airflow", "scheduler"], stderr=subprocess.PIPE)
    output = scheduler.communicate()
    print("Scheduler was shutdown with output: " + str(output))

signal.signal(signal.SIGINT, on_exit)
signal.signal(signal.SIGTERM, on_exit)

zk = KazooClient(hosts='10.0.0.6:2181,10.0.0.11:2181,10.0.0.4:2181,10.0.0.7:2181')
zk.start()

election = zk.Election("/master-scheduler", name)

print(name + " is ready to become master")

election.run(start_scheduler)

zk.stop()
