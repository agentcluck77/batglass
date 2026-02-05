#!/usr/bin/env python3
"""
Calibration script for HC-SR04 ultrasonic distance sensor.
Place an object at a known distance and calibrate the sensor.
"""

import RPi.GPIO as GPIO
import time
import json
import os

TRIG_PIN = 17
ECHO_PIN = 27
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")
NUM_SAMPLES = 10

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    GPIO.output(TRIG_PIN, False)
    time.sleep(0.1)

def measure_distance():
    """Measure distance in cm using HC-SR04 sensor."""
    # Send trigger pulse
    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)  # 10 microseconds
    GPIO.output(TRIG_PIN, False)

    # Wait for echo start (with timeout)
    timeout_start = time.time()
    while GPIO.input(ECHO_PIN) == 0:
        pulse_start = time.time()
        if pulse_start - timeout_start > 0.1:
            return None  # Timeout

    # Wait for echo end (with timeout)
    timeout_start = time.time()
    while GPIO.input(ECHO_PIN) == 1:
        pulse_end = time.time()
        if pulse_end - timeout_start > 0.1:
            return None  # Timeout

    # Calculate distance
    pulse_duration = pulse_end - pulse_start
    # Speed of sound = 34300 cm/s, divide by 2 for round trip
    distance = pulse_duration * 17150

    return round(distance, 2)

def take_samples(num_samples=NUM_SAMPLES):
    """Take multiple samples and return average."""
    readings = []
    print(f"Taking {num_samples} samples...")

    for i in range(num_samples):
        distance = measure_distance()
        if distance is not None:
            readings.append(distance)
            print(f"  Sample {i+1}: {distance:.2f} cm")
        else:
            print(f"  Sample {i+1}: timeout")
        time.sleep(0.2)

    if not readings:
        return None

    avg = sum(readings) / len(readings)
    return avg

def save_calibration(offset):
    """Save calibration to file."""
    cal = {
        'offset': offset,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(CALIBRATION_FILE, 'w') as f:
        json.dump(cal, f, indent=2)
    print(f"Calibration saved to {CALIBRATION_FILE}")

def main():
    setup()

    print("=" * 40)
    print("HC-SR04 Ultrasonic Sensor Calibration")
    print("=" * 40)
    print()
    print("Place an object at a KNOWN distance from the sensor.")
    print()

    try:
        known_distance = float(input("Enter the actual distance in cm: "))
    except ValueError:
        print("Invalid input. Please enter a number.")
        GPIO.cleanup()
        return

    print()
    input("Press Enter when ready to calibrate...")
    print()

    try:
        measured = take_samples()

        if measured is None:
            print("\nError: Could not get readings. Check sensor connection.")
            return

        print()
        print(f"Average measured distance: {measured:.2f} cm")
        print(f"Actual distance: {known_distance:.2f} cm")

        offset = known_distance - measured
        print(f"Calibration offset: {offset:.2f} cm")
        print()

        save = input("Save this calibration? (y/n): ").lower().strip()
        if save == 'y':
            save_calibration(offset)
        else:
            print("Calibration not saved.")

    except KeyboardInterrupt:
        print("\nCalibration cancelled.")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
