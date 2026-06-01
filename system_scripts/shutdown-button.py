import RPi.GPIO as GPIO
import subprocess
import time

BUTTON_PIN = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

try:
    while True:
        GPIO.wait_for_edge(BUTTON_PIN, GPIO.FALLING)
        time.sleep(0.1)  # debounce
        if GPIO.input(BUTTON_PIN) == GPIO.LOW:
            subprocess.run(['shutdown', '-h', 'now'])
finally:
    GPIO.cleanup()
