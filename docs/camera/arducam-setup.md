Arducam 64MP (Hawkeye) Setup

1. Install Arducam Pivariety stack
- `wget -O install_pivariety_pkgs.sh https://github.com/ArduCAM/Arducam-Pivariety-V4L2-Driver/releases/download/install_script/install_pivariety_pkgs.sh`
- `chmod +x install_pivariety_pkgs.sh`
- `./install_pivariety_pkgs.sh -p libcamera_dev`
- `./install_pivariety_pkgs.sh -p libcamera_apps`
- `./install_pivariety_pkgs.sh -p 64mp_pi_hawk_eye_kernel_driver`

2. Configure overlay (Bookworm/Trixie)
- Edit `/boot/firmware/config.txt`
- Set:
  - `camera_auto_detect=0`
  - `dtoverlay=arducam-64mp,cam0`
- Reboot: `sudo reboot`

3. Verify camera
- `rpicam-still --list-cameras`
- Expected sensor name: `arducam_64mp`
- `ls -l /usr/share/libcamera/ipa/rpi/pisp/arducam_64mp.json`
- `rpicam-still -t 1000 -o /tmp/arducam-test.jpg`

4. Verify OCR CLI
- Quick test: `uv run scripts/ocr_camera.py capture-interval --interval-ms 1000 --no-save --count 3`
- Continuous mode: `uv run scripts/ocr_camera.py capture-interval --interval-ms 1000 --no-save`

Troubleshooting
- Error `arducam_64mp.json not found` means mixed stack.
- Keep `dtoverlay=arducam-64mp,cam0` only when Arducam Pivariety packages are installed.
