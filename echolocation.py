import lgpio
import time
import subprocess
from collections import deque

# -------------------------------
# GPIO PIN SETUP
# -------------------------------

TRIG_LEFT = 23
ECHO_LEFT = 24

TRIG_RIGHT = 5
ECHO_RIGHT = 6

chip = lgpio.gpiochip_open(0)

lgpio.gpio_claim_output(chip, TRIG_LEFT)
lgpio.gpio_claim_input(chip, ECHO_LEFT)

lgpio.gpio_claim_output(chip, TRIG_RIGHT)
lgpio.gpio_claim_input(chip, ECHO_RIGHT)

# -------------------------------
# DISTANCE PARAMETERS
# -------------------------------

MAX_DISTANCE = 200  # cm
MIN_DISTANCE = 10   # cm

CRITICAL_DISTANCE = 15  # cm for continuous warning

# smoothing buffer
BUFFER_SIZE = 5
left_buffer = deque(maxlen=BUFFER_SIZE)
right_buffer = deque(maxlen=BUFFER_SIZE)

# -------------------------------
# GENERATE BEEP FILE
# -------------------------------

subprocess.run([
    'sox', '-n', '-r', '48000', '-c', '2', '/tmp/beep.wav',
    'synth', '0.1', 'sine', '1000'
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# -------------------------------
# DISTANCE FUNCTION
# -------------------------------

def get_distance(trig, echo):

    lgpio.gpio_write(chip, trig, 0)
    time.sleep(0.002)

    lgpio.gpio_write(chip, trig, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(chip, trig, 0)

    timeout = time.time() + 0.05

    while lgpio.gpio_read(chip, echo) == 0:
        pulse_start = time.time()
        if time.time() > timeout:
            return None

    while lgpio.gpio_read(chip, echo) == 1:
        pulse_end = time.time()
        if time.time() > timeout:
            return None

    duration = pulse_end - pulse_start
    distance = duration * 17150

    return round(distance, 2)

# -------------------------------
# AUDIO FUNCTIONS
# -------------------------------

def beep_left():
    subprocess.run(
        ['aplay', '-D', 'plughw:2,0', '/tmp/beep.wav'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def beep_right():
    subprocess.run(
        ['aplay', '-D', 'plughw:2,0', '/tmp/beep.wav'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def warning_tone():
    subprocess.run(
        ['speaker-test', '-t', 'sine', '-f', '1500', '-l', '1'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# -------------------------------
# DISTANCE TO BEEP INTERVAL
# -------------------------------

def compute_interval(distance):

    if distance > MAX_DISTANCE:
        return None

    clamped = max(MIN_DISTANCE, min(distance, MAX_DISTANCE))

    interval = 0.1 + ((clamped - MIN_DISTANCE) /
               (MAX_DISTANCE - MIN_DISTANCE)) * 1.4

    return interval

# -------------------------------
# MAIN LOOP
# -------------------------------

try:

    while True:

        left_distance = get_distance(TRIG_LEFT, ECHO_LEFT)
        right_distance = get_distance(TRIG_RIGHT, ECHO_RIGHT)

        if left_distance:
            left_buffer.append(left_distance)

        if right_distance:
            right_buffer.append(right_distance)

        if len(left_buffer) == 0 or len(right_buffer) == 0:
            continue

        left_avg = sum(left_buffer) / len(left_buffer)
        right_avg = sum(right_buffer) / len(right_buffer)

        print(f"Left: {left_avg:.1f} cm | Right: {right_avg:.1f} cm")

        # critical warning
        if left_avg < CRITICAL_DISTANCE or right_avg < CRITICAL_DISTANCE:
            warning_tone()
            time.sleep(0.1)
            continue

        left_interval = compute_interval(left_avg)
        right_interval = compute_interval(right_avg)

        if left_interval:
            beep_left()

        if right_interval:
            beep_right()

        sleep_time = min(
            left_interval if left_interval else 1,
            right_interval if right_interval else 1
        )

        time.sleep(sleep_time)

except KeyboardInterrupt:

    print("Stopped")

finally:

    lgpio.gpiochip_close(chip)