import RPi.GPIO as GPIO
from scene_description import run_scene_description

BUTTON_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Scene description system ready")

while True:
    if GPIO.input(BUTTON_PIN) == GPIO.LOW:
        print("Button pressed - describing scene")
        run_scene_description()