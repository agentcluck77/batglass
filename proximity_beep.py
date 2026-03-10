import lgpio
import time
import subprocess

TRIG = 23
ECHO = 24

chip = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(chip, TRIG)
lgpio.gpio_claim_input(chip, ECHO)

# Pre-generate a short beep WAV file
subprocess.run([
    'sox', '-n', '-r', '48000', '-c', '2', '/tmp/beep.wav',
    'synth', '0.1', 'sine', '1000'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_distance():
    lgpio.gpio_write(chip, TRIG, 0)
    time.sleep(0.05)

    lgpio.gpio_write(chip, TRIG, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(chip, TRIG, 0)

    timeout = time.time() + 1
    while lgpio.gpio_read(chip, ECHO) == 0:
        pulse_start = time.time()
        if time.time() > timeout:
            return None

    timeout = time.time() + 1
    while lgpio.gpio_read(chip, ECHO) == 1:
        pulse_end = time.time()
        if time.time() > timeout:
            return None

    pulse_duration = pulse_end - pulse_start
    distance = round(pulse_duration * 17150, 2)
    return distance

def beep():
    subprocess.run(
        ['aplay', '-D', 'hw:2,0', '/tmp/beep.wav'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

MAX_DISTANCE = 200  # beyond this, no beeping
MIN_DISTANCE = 10   # at this distance, beep interval is shortest

try:
    while True:
        distance = get_distance()

        if distance is None:
            time.sleep(0.5)
            continue

        print(f"Distance: {distance} cm")

        if distance > MAX_DISTANCE:
            # Nothing detected, stay silent
            time.sleep(0.5)
        else:
            # Clamp distance to range
            clamped = max(MIN_DISTANCE, min(distance, MAX_DISTANCE))

            # Scale silence between 0.1s (very close) and 1.5s (far)
            silence = 0.1 + ((clamped - MIN_DISTANCE) / (MAX_DISTANCE - MIN_DISTANCE)) * 1.4

            beep()          # plays for 0.1s
            time.sleep(silence)

except KeyboardInterrupt:
    print("Stopped")
    lgpio.gpiochip_close(chip)