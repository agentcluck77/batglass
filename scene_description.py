import cv2
import subprocess
from picamera2 import Picamera2
from transformers import BlipProcessor, BlipForConditionalGeneration
import torch

processor = BlipProcessor.from_pretrained(
    "Salesforce/blip-image-captioning-base"
)

model = BlipForConditionalGeneration.from_pretrained(
    "Salesforce/blip-image-captioning-base"
)

device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

picam2 = Picamera2()
picam2.start()


def capture_image():
    frame = picam2.capture_array()
    return frame


def describe_scene(frame):

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    inputs = processor(images=rgb, return_tensors="pt").to(device)

    out = model.generate(**inputs)

    caption = processor.decode(out[0], skip_special_tokens=True)

    return caption


def speak(text):
    subprocess.run(["espeak", text])


def run_scene_description():

    frame = capture_image()

    description = describe_scene(frame)

    print("Scene:", description)

    speak(description)