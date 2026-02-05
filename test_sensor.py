#!/usr/bin/env python3
"""
Test script for HC-SR04 ultrasonic distance sensor.
Returns the distance measured by the sensor.
"""

import RPi.GPIO as GPIO
import time
import json
import os
import sys

TRIG_PIN = 17
ECHO_PIN = 27
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")

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

def load_calibration():
    """Load calibration offset if available."""
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, 'r') as f:
                cal = json.load(f)
                return cal.get('offset', 0)
        except:
            pass
    return 0

def main():
    continuous = '-c' in sys.argv or '--continuous' in sys.argv

    setup()
    offset = load_calibration()

    if offset != 0:
        print(f"Calibration loaded (offset: {offset:.2f} cm)")

    try:
        if continuous:
            print("Continuous mode (Ctrl+C to stop)")
            print("-" * 30)
            while True:
                distance = measure_distance()
                if distance is not None:
                    calibrated = distance + offset
                    print(f"Distance: {calibrated:.2f} cm")
                else:
                    print("Timeout - check sensor connection")
                time.sleep(0.5)
        else:
            distance = measure_distance()
            if distance is not None:
                calibrated = distance + offset
                print(f"Distance: {calibrated:.2f} cm")
            else:
                print("Timeout - check sensor connection")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
