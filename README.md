# ARI-selfie-cam
<img src="https://github.com/user-attachments/assets/9c378336-4cb4-4fd5-9f05-a0682a221205" width="500" >
<img src="https://github.com/user-attachments/assets/507ea10c-0f5d-4f71-80da-b9b85901bd2d" width="500" >

<img src="https://github.com/user-attachments/assets/c6c46409-a802-460d-bb4e-117b84424847" width="500" >
<img src="https://github.com/user-attachments/assets/46c10264-137e-40d0-b7c5-729bd530f078" width="500" >
## Admin control from phone - will update with controller as as ARI's webcomander
<img src="https://github.com/user-attachments/assets/21aa0166-592f-4600-b705-4c1de918ebad" width="200" >


# Raspberry Pi Camera Server Setup

## Project Structure
Create the following folder structure:

```
flask_camera_app/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── templates/            # HTML templates folder
│   ├── base.html         # Base template
│   ├── index.html        # Main menu
│   ├── selfie.html       # Selfie page
│   ├── interview.html    # Interview page
│   └── gallery.html      # Gallery page
├── static/
│   └── gallery/          # Where photos/videos are saved (auto-created)
└── README.md            # This file
```

## Hardware Requirements
- Raspberry Pi 3B with latest 64-bit Raspberry Pi OS
- CSI Camera (for interviews)
- UVC USB Camera (for selfies)
- USB Microphone
- MicroSD card (32GB+ recommended)

## Software Installation

### 1. Update your Raspberry Pi
```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Install system dependencies
```bash
# Install camera and audio tools
sudo apt install -y python3-pip python3-venv
sudo apt install -y ffmpeg alsa-utils
sudo apt install -y libcamera-apps

# Install OpenCV dependencies
sudo apt install -y python3-opencv

# Enable camera interface
sudo raspi-config
# Navigate to Interface Options -> Camera -> Enable
```

### 3. Set up the project
```bash
# Create project directory
mkdir ~/flask_camera_app
cd ~/flask_camera_app

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt

# Create templates directory
mkdir templates

# Create static directory
mkdir -p static/gallery
```

### 4. Configure Audio (if using USB microphone)
```bash
# List audio devices
arecord -l

# Test USB microphone (replace hw:1,0 with your device)
arecord -D plughw:1,0 -f cd -t wav -d 5 test.wav
aplay test.wav
```

### 5. Configure UVC Camera
```bash
# Check if UVC camera is detected
lsusb
ls /dev/video*

# Test UVC camera
ffmpeg -f v4l2 -i /dev/video0 -t 5 -y test_uvc.mp4
```

## File Setup

1. **Create all the files in their respective locations:**
   - Save `app.py` in the root directory
   - Save all HTML templates in the `templates/` folder
   - Save `requirements.txt` in the root directory

2. **Set file permissions:**
```bash
chmod +x app.py
```

## Configuration

### Camera Device Configuration
Edit `app.py` and update these variables if needed:

```python
UVC_DEVICE = '/dev/video0'  # Change if your UVC camera is on different device
CSI_CAMERA_INDEX = 0        # Usually 0 for CSI camera
```

### Audio Device Configuration
In the `start_interview()` function, update the audio recording command:

```python
# Change 'plughw:1,0' to match your USB microphone device
audio_process = subprocess.Popen([
    'arecord', '-D', 'plughw:1,0', '-f', 'cd', '-t', 'wav', audio_file
])
```

## Running the Application

### 1. Start the server
```bash
cd ~/flask_camera_app
source venv/bin/activate
python app.py
```

### 2. Access the interface
- **On the Pi:** Open browser and go to `http://localhost:5000`
- **From other devices:** Go to `http://[PI_IP_ADDRESS]:5000`

### 3. Find your Pi's IP address
```bash
hostname -I
```

## Usage

### Taking Selfies
1. Click "Take a Selfie"
2. Position yourself in front of the UVC camera
3. Click "Take Selfie" button
4. Camera will count down from 6
5. On the last second, screen shows "#issobellatherobot"
6. Photo is taken and displayed for 5 seconds
7. Photo is saved to gallery

### Recording Interviews
1. Click "Interview"
2. Position yourself in front of the CSI camera
3. Click "Start Interview"
4. Answer the displayed question
5. Click "Stop Interview" when done
6. Video with audio is saved to gallery

### Viewing Gallery
1. Click "Gallery"
2. View all photos and videos
3. Download files or delete individual items
4. Files are organized by timestamp

## Troubleshooting

### Camera Issues
```bash
# Check camera detection
vcgencmd get_camera

# For CSI camera issues
sudo modprobe bcm2835-v4l2

# For UVC camera issues
lsusb
ls /dev/video*
```

### Audio Issues
```bash
# Check audio devices
arecord -l
aplay -l

# Test microphone
arecord -D plughw:1,0 -f cd -t wav -d 3 test.wav && aplay test.wav
```

### Permission Issues
```bash
# Add user to video and audio groups
sudo usermod -a -G video $USER
sudo usermod -a -G audio $USER

# Reboot to apply changes
sudo reboot
```

### Port Already in Use
```bash
# Kill existing Flask processes
sudo pkill -f flask
sudo pkill -f python

# Or use a different port in app.py:
# app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
```

## Auto-Start on Boot (Optional)

Create a systemd service to start the camera server automatically:

```bash
sudo nano /etc/systemd/system/camera-server.service
```

Add this content:
```ini
[Unit]
Description=Camera Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/flask_camera_app
Environment=PATH=/home/pi/flask_camera_app/venv/bin
ExecStart=/home/pi/flask_camera_app/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-server.service
sudo systemctl start camera-server.service
```

## Features

- **Selfie Mode**: Uses UVC camera with countdown and flash screen
- **Interview Mode**: Uses CSI camera with audio recording
- **Gallery**: View, download, and delete captured media
- **Responsive Design**: Works on Pi screen and external devices
- **Auto-combine**: Audio and video automatically combined for interviews
- **Timestamp Naming**: All files named with date/time stamps
- **Error Handling**: Graceful error handling and user feedback

## Admin page

Perfect! I've created a comprehensive admin control page for your Flask camera app with ARI robot integration. Here's what I've added:

## Key Features of the Admin Page:

### 🤖 **ARI Robot Control**
- Text input area for sending speech to ARI robot
- "Send to ARI" button that calls the TTS API
- 4 motion control buttons:
  - Wave Hello
  - Shake Left  
  - Nod Yes
  - Shake No
- Real-time feedback for all ARI commands

### 📹 **Camera Preview**
- Live camera feed preview (selfie camera)
- Start/Stop preview controls
- Helps ensure camera is positioned correctly
- Preview uses streaming endpoint for real-time view

### 📸 **Quick Actions**
- Take Selfie button
- Start/Stop Interview recording toggle
- Real-time recording status indicators

### 🧭 **Navigation** 
- Quick access to Home and Gallery pages
- Maintains navigation to all existing features

### ⚡ **System Status**
- Real-time status indicators for:
  - Camera availability
  - Preview status
  - Recording status
- Auto-updates every 2 seconds

## Mobile-Optimized Design:
- Responsive layout sized for mobile devices
- Touch-friendly buttons with hover effects
- Modern gradient design with clear visual hierarchy
- Alert system for user feedback
- Grid layouts that adapt to screen size

## Updated Flask App Features:

### New API Endpoints:
- `/api/admin/ari_speak` - Send text to ARI TTS
- `/api/admin/ari_motion` - Send motion commands to ARI
- `/api/admin/start_preview` - Start camera preview
- `/api/admin/stop_preview` - Stop camera preview
- `/admin/camera_feed` - Live camera streaming endpoint

### ARI Integration:
- Configurable ARI robot URL (`ARI_BASE_URL`)
- Error handling for robot communication
- Support for different languages (defaulting to en_GB)

## To Use This:

1. **Update your ARI robot URL** - Change `ARI_BASE_URL` in the Flask app to match your robot's IP
2. **Install additional dependency** - Add `requests` to your requirements.txt:
   ```
   requests>=2.31.0
   ```

## Access the Admin Page:
- Navigate to `http://your-pi-ip:5000/admin`
- The page is optimized for mobile devices but works on desktop too

## Motion Names:
The motion names (wave_hello, shake_left, nod_yes, shake_no) are examples. You can easily modify these in the HTML template to match your ARI robot's actual motion file names.

The admin page provides complete control over both camera functions and ARI robot interactions in one convenient mobile-friendly interface!


