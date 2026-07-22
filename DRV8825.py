import os
import time
import logging

log = logging.getLogger('petfeedr')

# Determine if we're running in simulation mode
# Auto-detect: if RPi.GPIO isn't available, we're not on a Pi
# Manual override: set PETFEEDR_SIMULATE=true to force simulation
SIMULATION_MODE = os.environ.get('PETFEEDR_SIMULATE', 'false').lower() == 'true'

if not SIMULATION_MODE:
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        # RPi.GPIO not available - automatically switch to simulation
        import mock_gpio as GPIO
        SIMULATION_MODE = True
        log.info("🔧 RPi.GPIO not found - running in SIMULATION mode")
else:
    import mock_gpio as GPIO
    log.info("🔧 PETFEEDR_SIMULATE=true - running in SIMULATION mode")

MotorDir = [
    'forward',
    'backward',
]

ControlMode = [
    'hardward',
    'softward',
]


class DRV8825():
    def __init__(self, dir_pin, step_pin, enable_pin, mode_pins):
        self.dir_pin = dir_pin
        self.step_pin = step_pin        
        self.enable_pin = enable_pin
        self.mode_pins = mode_pins
        self.simulation_mode = SIMULATION_MODE
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.dir_pin, GPIO.OUT)
        GPIO.setup(self.step_pin, GPIO.OUT)
        GPIO.setup(self.enable_pin, GPIO.OUT)
        GPIO.setup(self.mode_pins, GPIO.OUT)
        
    def digital_write(self, pin, value):
        GPIO.output(pin, value)
        
    def Stop(self):
        self.digital_write(self.enable_pin, 0)
    
    def SetMicroStep(self, mode, stepformat):
        """
        (1) mode
            'hardward' :    Use the switch on the module to control the microstep
            'software' :    Use software to control microstep pin levels
                Need to put the All switch to 0
        (2) stepformat
            ('fullstep', 'halfstep', '1/4step', '1/8step', '1/16step', '1/32step')
        """
        microstep = {'fullstep': (0, 0, 0),
                     'halfstep': (1, 0, 0),
                     '1/4step': (0, 1, 0),
                     '1/8step': (1, 1, 0),
                     '1/16step': (0, 0, 1),
                     '1/32step': (1, 0, 1)}

        if self.simulation_mode:
            log.info(f"[SIM] Motor microstep set to: {stepformat}")
        else:
            print("Control mode:", mode)
            
        if (mode == ControlMode[1]):
            if not self.simulation_mode:
                print("set pins")
            self.digital_write(self.mode_pins, microstep[stepformat])
        
    def TurnStep(self, Dir, steps, stepdelay=0.005):
        # In simulation mode, just log what would happen
        if self.simulation_mode:
            duration = steps * stepdelay * 2
            log.info(f"[SIM] 🔄 Motor turning {Dir} for {steps} steps "
                        f"(would take {duration:.2f}s)")
            # Brief delay to simulate some work without wasting time
            time.sleep(0.1)
            return
            
        if (Dir == MotorDir[0]):
            print("forward")
            self.digital_write(self.enable_pin, 1)
            self.digital_write(self.dir_pin, 0)
        elif (Dir == MotorDir[1]):
            print("backward")
            self.digital_write(self.enable_pin, 1)
            self.digital_write(self.dir_pin, 1)
        else:
            print("the dir must be : 'forward' or 'backward'")
            self.digital_write(self.enable_pin, 0)
            return

        if (steps == 0):
            return
            
        print("turn step:", steps)
        for i in range(steps):
            self.digital_write(self.step_pin, True)
            time.sleep(stepdelay)
            self.digital_write(self.step_pin, False)
            time.sleep(stepdelay)
