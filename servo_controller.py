import RPi.GPIO as GPIO
import time
from DRV8825 import DRV8825

def trigger_servo():
    start_time = time.time()  # record the start time

    try:
        Motor1 = DRV8825(dir_pin=13, step_pin=19, enable_pin=12, mode_pins=(16, 17, 20))

        Motor1.SetMicroStep('softward','fullstep')

        # Rotate 360 degrees forward
        Motor1.TurnStep(Dir='forward', steps=75, stepdelay = 0.005)
        time.sleep(0.1)

        # Rotate 360 degrees backward
        Motor1.TurnStep(Dir='backward', steps=75, stepdelay = 0.005)
        Motor1.Stop()

    except:
        # GPIO.cleanup()
        print ("\nMotor stop")
        Motor1.Stop()
        exit()