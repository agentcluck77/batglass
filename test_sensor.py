import lgpio
import time

TRIG = 23
ECHO = 24

chip = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(chip, TRIG)
lgpio.gpio_claim_input(chip, ECHO)

def get_distance():
    lgpio.gpio_write(chip, TRIG, 0)
    time.sleep(0.05)

    lgpio.gpio_write(chip, TRIG, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(chip, TRIG, 0)

    while lgpio.gpio_read(chip, ECHO) == 0:
        pulse_start = time.time()

    while lgpio.gpio_read(chip, ECHO) == 1:
        pulse_end = time.time()

    pulse_duration = pulse_end - pulse_start
    distance = round(pulse_duration * 17150, 2)
    return distance

try:
    while True:
        dist = get_distance()
        print(f"Distance: {dist} cm")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
    lgpio.gpiochip_close(chip)