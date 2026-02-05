OCR Script Plan (Arducam -> text)

Requirements (confirmed)
- Input: still images
- Runtime: on Pi only, offline
- Latency: near real time
- Language: Python
- OCR language: English
- Output: plain text printed to terminal

Assumptions
- Raspberry Pi OS Bookworm/Trixie with Arducam Hawkeye already working.
- Using `picamera2` for faster capture (avoids shelling out each frame).
- OCR quality can be improved with basic preprocessing (grayscale/resize/threshold).

Proposed tech stack
- Python 3
- `picamera2` (camera capture)
- `tesseract-ocr` + `pytesseract` (offline OCR)
- `opencv-python` (optional preprocessing; Pillow fallback if needed)

Implementation outline
1. Dependencies (apt/uv):
   - `sudo apt install -y tesseract-ocr libtesseract-dev python3-picamera2`
   - `uv pip install pytesseract opencv-python` (or `pillow` if avoiding OpenCV)
2. Script structure:
   - Init camera with a modest resolution (e.g., 1280x720 for speed).
   - Loop every N ms:
     - Capture still frame to memory.
     - Preprocess: grayscale -> resize (2x) -> adaptive threshold.
     - Run `pytesseract.image_to_string` with `--oem 1 --psm 6`.
     - Print text to terminal (trim empty lines).
3. CLI options to support:
   - `--interval-ms` (default 1000)
   - `--width/--height`
   - `--rotate` (0/90/180/270)
   - `--roi` (x,y,w,h) to limit OCR area for speed/accuracy
4. Validation:
   - Run OCR on a saved image first (`arducam-test.jpg`) to confirm accuracy.
   - Then switch to live capture loop.

Notes
- If OCR is slow, lower resolution or tighten ROI.
- For small text, increase resolution or apply stronger resize before OCR.