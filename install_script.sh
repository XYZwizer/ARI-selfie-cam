#!/bin/bash

# Raspberry Pi Camera Server Installation Script
echo "🎥 Installing Raspberry Pi Camera Server..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    print_warning "This script is designed for Raspberry Pi. Continuing anyway..."
fi

# Update system
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install system dependencies
print_status "Installing system dependencies..."
sudo apt install -y python3-pip python3-venv python3-opencv
sudo apt install -y ffmpeg alsa-utils libcamera-apps
sudo apt install -y git curl

# Enable camera interface
print_status "Checking camera interface..."
if ! raspi-config nonint get_camera | grep -q "0"; then
    print_warning "Camera interface may not be enabled. Please run 'sudo raspi-config' and enable camera."
fi

# Create project directory
PROJECT_DIR="$HOME/flask_camera_app"
print_status "Creating project directory at $PROJECT_DIR..."

if [ -d "$PROJECT_DIR" ]; then
    print_warning "Project directory already exists. Backing up..."
    mv "$PROJECT_DIR" "${PROJECT_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
fi

mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Create directory structure
print_status "Creating directory structure..."
mkdir -p templates
mkdir -p static/gallery

# Create virtual environment
print_status "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Create requirements.txt
print_status "Creating requirements.txt..."
cat > requirements.txt << 'EOF'
Flask==2.3.3
picamera2==0.3.12
opencv-python==4.8.1.78
numpy==1.24.3
EOF

# Install Python packages
print_status "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Check for cameras
print_status "Checking for cameras..."
if ls /dev/video* 1> /dev/null 2>&1; then
    print_status "Found video devices: $(ls /dev/video*)"
else
    print_warning "No video devices found. Make sure cameras are connected."
fi

# Check for audio devices
print_status "Checking for audio devices..."
if arecord -l | grep -q "card"; then
    print_status "Audio devices found:"
    arecord -l | grep "card"
else
    print_warning "No audio devices found. USB microphone may not be connected."
fi

# Add user to video and audio groups
print_status "Adding user to video and audio groups..."
sudo usermod -a -G video $USER
sudo usermod -a -G audio $USER

print_status "Installation completed!"
print_status ""
print_status "Next steps:"
print_status "1. Copy all the Python and HTML files to $PROJECT_DIR"
print_status "2. Update camera and audio device paths in app.py if needed"
print_status "3. Run the server with: cd $PROJECT_DIR && source venv/bin/activate && python app.py"
print_status "4. Access the interface at http://localhost:5000"
print_status ""
print_warning "You may need to reboot for group membership changes to take effect."

# Create a simple start script
cat > start_server.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python app.py
EOF

chmod +x start_server.sh
print_status "Created start_server.sh script for easy startup"

echo ""
echo "🎉 Installation complete! Follow the setup instructions to copy your files and start the server."