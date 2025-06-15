#!/usr/bin/env python3
"""
Lightweight Raspberry Pi Camera Server with Flask
Uses picamera2 for CSI camera (interviews) and DroidCam for selfies
Now includes admin control page with ARI robot integration
"""

import os
import time
import threading
import signal
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, Response, send_file
# from picamera2 import Picamera2
# from picamera2.encoders import H264Encoder
import subprocess
import glob
import io
import base64   
from PIL import Image
import json
from pathlib import Path

app = Flask(__name__)

# Add CORS headers
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Handle OPTIONS method for CORS preflight requests
@app.route('/api/delete_file/<filename>', methods=['OPTIONS'])
def delete_file_options(filename):
    return '', 200

@app.route('/api/clear_gallery', methods=['OPTIONS'])
def clear_gallery_options():
    return '', 200

# Configuration
GALLERY_PATH = Path('static/gallery')
INTERVIEW_DURATION = 300  # 5 minutes max
ARI_BASE_URL = 'http://192.168.0.103'  # Default ARI robot URL - change as needed
# DROIDCAM_IP = '172.20.24.0'
DROIDCAM_IP = '192.168.0.126'

DROIDCAM_PORT = 4747
DROIDCAM_URL = "http://192.168.0.126:4747/video"
SLIDESHOW = "http://192.168.0.133:8080"
UPLOAD_ENDPOINT = f"{SLIDESHOW}/upload"

# Ensure gallery directory exists
GALLERY_PATH.mkdir(exist_ok=True)

# Global variable to store the current interview prompt
current_interview_prompt = "Nice outfit, tell me about it"

# New global variable for interview trigger
interview_trigger = False

# Global variables
interview_events = []
event_lock = threading.Lock()

def add_interview_event(event_type, data):
    """Add a new event to the interview events list"""
    with event_lock:
        interview_events.append({
            'type': event_type,
            'data': data,
            'timestamp': time.time()
        })
        # Keep only last 10 events
        if len(interview_events) > 10:
            interview_events.pop(0)

class CameraManager:
    def __init__(self):
        self.csi_camera = None
        self.recording = False
        self.audio_process = None
        self.current_video = None
        self.current_audio = None
        self.available_cameras = []
        self.preview_active = False
        self.droidcam_active = False
        self.droidcam_stream = None
        self.detect_cameras()
        
    def detect_cameras(self):
        """Detect available cameras"""
        try:
            self.available_cameras = Picamera2.global_camera_info()
            print(f"Available cameras: {self.available_cameras}")
            
            # Find CSI camera
            self.csi_camera_num = None
            
            for i, cam_info in enumerate(self.available_cameras):
                model = cam_info.get('Model', '').lower()
                if 'imx' in model or 'ov' in model:  # Common CSI camera models
                    self.csi_camera_num = i
                    print(f"Found CSI camera at index {i}: {model}")
                    break
                    
        except Exception as e:
            print(f"Error detecting cameras: {e}")
            # Fallback assumption
            self.csi_camera_num = 0
    
    def init_csi_camera(self):
        """Initialize CSI camera for interview recording"""
        try:
            if self.csi_camera is None and self.csi_camera_num is not None:
                self.csi_camera = Picamera2(self.csi_camera_num)
                # Simple video configuration - no preview stream to save resources
                config = self.csi_camera.create_video_configuration(
                    main={"size": (1280, 720)}  # Lower resolution for Pi 3B
                )
                self.csi_camera.configure(config)
            return True
        except Exception as e:
            print(f"Failed to initialize CSI camera: {e}")
            return False
    
    def start_droidcam_preview(self):
        """Start DroidCam preview stream"""
        try:
            # Test connection to DroidCam
            response = requests.get(DROIDCAM_URL, timeout=5, stream=True)
            if response.status_code == 200:
                self.droidcam_active = True
                self.droidcam_stream = response
                print("DroidCam preview started")
                return True
            else:
                print(f"Failed to connect to DroidCam: {response.status_code}")
                return False
        except Exception as e:
            print(f"Error starting DroidCam preview: {e}")
            return False
    
    def stop_droidcam_preview(self):
        """Stop DroidCam preview stream"""
        try:
            if self.droidcam_stream:
                self.droidcam_stream.close()
                self.droidcam_stream = None
            self.droidcam_active = False
            print("DroidCam preview stopped")
        except Exception as e:
            print(f"Error stopping DroidCam preview: {e}")
    
    def capture_droidcam_image(self, filepath):
        """Capture a still image from DroidCam video stream (MJPEG) by extracting the first JPEG frame."""
        try:
            response = requests.get(DROIDCAM_URL, timeout=10, stream=True)
            if response.status_code == 200:
                buffer = b''
                jpeg_start = None
                for chunk in response.iter_content(chunk_size=4096):
                    if not chunk:
                        break
                    buffer += chunk
                    # Look for JPEG start marker
                    if jpeg_start is None:
                        jpeg_start = buffer.find(b'\xff\xd8')
                        if jpeg_start == -1:
                            buffer = buffer[-10:]
                            continue
                    # Look for JPEG end marker
                    jpeg_end = buffer.find(b'\xff\xd9', jpeg_start)
                    if jpeg_end != -1:
                        jpeg_data = buffer[jpeg_start:jpeg_end + 2]
                        with open(filepath, 'wb') as f:
                            f.write(jpeg_data)
                        response.close()
                        print(f"Captured JPEG frame: {len(jpeg_data)} bytes")
                        return True
                response.close()
                print("No complete JPEG frame found in stream")
                return False
            else:
                print(f"Failed to capture DroidCam image: {response.status_code}")
                return False
        except Exception as e:
            print(f"Error capturing DroidCam image: {e}")
            return False
    
    def cleanup_csi_camera(self):
        """Clean up CSI camera resources"""
        if self.csi_camera:
            try:
                if self.recording:
                    self.csi_camera.stop_recording()
                    self.recording = False
                if self.csi_camera.started:
                    self.csi_camera.stop()
                self.csi_camera.close()
                self.csi_camera = None
            except Exception as e:
                print(f"Error cleaning up CSI camera: {e}")
        
        # Clean up audio process
        if self.audio_process:
            try:
                self.audio_process.terminate()
                self.audio_process.wait(timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.audio_process.kill()
                except ProcessLookupError:
                    pass
            self.audio_process = None

camera_manager = CameraManager()

# ARI Robot Integration Functions
def send_ari_tts(text, lang_id="en_GB"):
    """Send text-to-speech command to ARI robot"""
    try:
        url = f"{ARI_BASE_URL}/action/tts"
        payload = {
            "rawtext": {
                "text": text,
                "lang_id": lang_id
            }
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"Error sending TTS to ARI: {e}")
        return None

def send_ari_motion(motion_name):
    """Send motion command to ARI robot"""
    try:
        url = f"{ARI_BASE_URL}/action/motion_manager"
        payload = {"filename": motion_name}
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"Error sending motion to ARI: {e}")
        return None

@app.route('/')
def index():
    """Main menu page"""
    return render_template('index.html')

@app.route('/admin')
def admin_page():
    """Admin/Operator control page"""
    return render_template('admin.html')

@app.route('/selfie')
def selfie_page():
    """Selfie capture page with countdown"""
    return render_template('selfie.html')

@app.route('/interview')
def interview_page():
    """Interview recording page"""
    return render_template('interview.html')

@app.route('/admin-gallery')
def admin_gallery_page():
    """Admin Gallery page showing all captured media with delete options"""
    # Get all files from gallery directory
    image_files = glob.glob(os.path.join(GALLERY_PATH, '*.jpg'))
    video_files = glob.glob(os.path.join(GALLERY_PATH, '*.mp4'))
    
    # Sort by modification time (newest first)
    all_files = image_files + video_files
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # Extract just the filename for template
    files = [os.path.basename(f) for f in all_files]
    
    return render_template('admin-gallery.html', files=files)

@app.route('/gallery')
def gallery_page():
    """Public Gallery page showing all captured media (no delete)"""
    # Get all files from gallery directory
    image_files = glob.glob(os.path.join(GALLERY_PATH, '*.jpg'))
    video_files = glob.glob(os.path.join(GALLERY_PATH, '*.mp4'))
    
    # Sort by modification time (newest first)
    all_files = image_files + video_files
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # Extract just the filename for template
    files = [os.path.basename(f) for f in all_files]
    
    return render_template('public-gallery.html', files=files)

# DroidCam selfie endpoints
@app.route('/api/selfie_stream')
def selfie_stream():
    """Stream DroidCam video feed with proper MJPEG format"""
    def generate():
        try:
            response = requests.get(DROIDCAM_URL, timeout=10, stream=True)
            if response.status_code == 200:
                print("DroidCam stream connected successfully")
                
                # Check the content type from DroidCam
                content_type = response.headers.get('content-type', '')
                print(f"DroidCam content-type: {content_type}")
                
                # If it's already MJPEG, forward it directly
                if 'multipart' in content_type.lower():
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk
                else:
                    # If it's raw video data, we need to process it frame by frame
                    buffer = b''
                    frame_count = 0
                    
                    for chunk in response.iter_content(chunk_size=4096):
                        if not chunk:
                            break
                            
                        buffer += chunk
                        
                        # Look for JPEG frames
                        while True:
                            jpeg_start = buffer.find(b'\xff\xd8')
                            if jpeg_start == -1:
                                break
                                
                            jpeg_end = buffer.find(b'\xff\xd9', jpeg_start)
                            if jpeg_end == -1:
                                # Incomplete frame, wait for more data
                                buffer = buffer[jpeg_start:]
                                break
                            
                            # Extract complete JPEG frame
                            jpeg_frame = buffer[jpeg_start:jpeg_end + 2]
                            
                            # Yield frame in MJPEG format
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n'
                                   b'Content-Length: ' + str(len(jpeg_frame)).encode() + b'\r\n'
                                   b'\r\n' + jpeg_frame + b'\r\n')
                            
                            frame_count += 1
                            if frame_count % 30 == 0:  # Log every 30 frames
                                print(f"Streamed {frame_count} frames")
                            
                            # Remove processed frame from buffer
                            buffer = buffer[jpeg_end + 2:]
            else:
                print(f"DroidCam connection failed: {response.status_code}")
                yield b'--frame\r\n' b'Content-Type: text/plain\r\n\r\n' b'Camera connection failed\r\n'
                
        except Exception as e:
            print(f"Error streaming DroidCam: {e}")
            yield b'--frame\r\n' b'Content-Type: text/plain\r\n\r\n' b'Stream error\r\n'
    
    # Return the stream with proper MJPEG headers
    return Response(generate(), 
                   mimetype='multipart/x-mixed-replace; boundary=frame')

# Simplify the start_selfie function since stream should work immediately
@app.route('/api/start_selfie', methods=['POST'])
def start_selfie():
    """Start selfie process - just test DroidCam availability"""
    try:
        # Quick test of DroidCam availability
        test_response = requests.get(DROIDCAM_URL, timeout=3)
        if test_response.status_code != 200:
            return jsonify({'error': f'DroidCam not accessible at {DROIDCAM_IP}:{DROIDCAM_PORT}'}), 500
        
        test_response.close()
        
        return jsonify({
            'success': True,
            'message': 'DroidCam is available',
            'stream_url': '/api/selfie_stream'
        })
        
    except requests.exceptions.ConnectTimeout:
        return jsonify({'error': f'DroidCam connection timeout - check if DroidCam is running on {DROIDCAM_IP}'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'Cannot connect to DroidCam at {DROIDCAM_IP}:{DROIDCAM_PORT}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error checking DroidCam: {str(e)}'}), 500

def send_to_remote_display(filepath):
    """Send a file to the remote display"""
    try:
        # Send the actual file to the remote display
        with open(filepath, 'rb') as image_file:
            files = {'image': (os.path.basename(filepath), image_file, 'image/jpeg')}
            data = {
                'duration': '10'  # 10 seconds
            }
            response = requests.post(
                UPLOAD_ENDPOINT,
                files=files,
                data=data,
                timeout=5
            )
            if response.ok:
                print(f"Successfully sent {os.path.basename(filepath)} to remote display")
            else:
                print(f"Failed to send {os.path.basename(filepath)} to remote display: {response.status_code}")
                print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error sending to remote display: {e}")

# Update take_selfie to use the new capture method
@app.route('/api/take_selfie', methods=['POST'])
def take_selfie():
    """Capture selfie from DroidCam stream or accept base64 image from browser."""
    try:
        # Send 'selfie' motion to ARI before taking the photo
        send_ari_motion('selfie')
        data = request.get_json(silent=True)
        if data and 'image' in data:
            # Handle base64 image from browser
            import base64
            header, encoded = data['image'].split(',', 1) if ',' in data['image'] else ('', data['image'])
            img_bytes = base64.b64decode(encoded)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'selfie_{timestamp}.jpg'
            filepath = GALLERY_PATH / filename
            with open(filepath, 'wb') as f:
                f.write(img_bytes)
            # Send to remote display
            send_to_remote_display(filepath)
            # Send 'natural' motion to ARI after photo is taken
            send_ari_motion('natural')
            return jsonify({
                'success': True,
                'filename': filename,
                'message': 'Selfie captured successfully!'
            })
        else:
            # Fallback: try to capture from DroidCam stream (legacy)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'selfie_{timestamp}.jpg'
            filepath = GALLERY_PATH / filename
            if camera_manager.capture_droidcam_image(filepath):
                # Send to remote display
                send_to_remote_display(filepath)
                # Send 'natural' motion to ARI after photo is taken
                send_ari_motion('natural')
                return jsonify({
                    'success': True, 
                    'filename': filename,
                    'message': 'Selfie captured successfully!'
                })
            else:
                send_ari_motion('natural')
                return jsonify({'error': 'Failed to capture frame from DroidCam'}), 500
    except Exception as e:
        send_ari_motion('natural')
        return jsonify({'error': f'Error taking selfie: {str(e)}'}), 500

# Admin API endpoints
@app.route('/api/admin/ari_speak', methods=['POST'])
def admin_ari_speak():
    """Send text to ARI for speech"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        lang_id = data.get('lang_id', 'en_GB')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        result = send_ari_tts(text, lang_id)
        if result:
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({'error': 'Failed to send TTS to ARI'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/admin/ari_motion', methods=['POST'])
def admin_ari_motion():
    """Send motion command to ARI"""
    try:
        data = request.get_json()
        motion = data.get('motion', '')
        
        if not motion:
            return jsonify({'error': 'No motion specified'}), 400
        
        result = send_ari_motion(motion)
        if result:
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({'error': 'Failed to send motion to ARI'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/api/admin/start_preview', methods=['POST'])
def start_preview():
    """Start camera preview for admin (CSI camera)"""
    try:
        if camera_manager.preview_active:
            return jsonify({'error': 'Preview already active'}), 400
        
        if not camera_manager.init_csi_camera():
            return jsonify({'error': 'Failed to initialize CSI camera for preview'}), 500
        
        # Create preview configuration for CSI camera
        config = camera_manager.csi_camera.create_preview_configuration(
            main={"size": (640, 480)}
        )
        camera_manager.csi_camera.configure(config)
        camera_manager.csi_camera.start()
        camera_manager.preview_active = True
        
        return jsonify({'success': True, 'message': 'Preview started'})
        
    except Exception as e:
        return jsonify({'error': f'Error starting preview: {str(e)}'}), 500

@app.route('/api/admin/stop_preview', methods=['POST'])
def stop_preview():
    """Stop camera preview"""
    try:
        if not camera_manager.preview_active:
            return jsonify({'error': 'Preview not active'}), 400
        
        if camera_manager.csi_camera and camera_manager.csi_camera.started:
            camera_manager.csi_camera.stop()
        camera_manager.preview_active = False
        
        return jsonify({'success': True, 'message': 'Preview stopped'})
        
    except Exception as e:
        return jsonify({'error': f'Error stopping preview: {str(e)}'}), 500

@app.route('/admin/camera_feed')
def camera_feed():
    """Video feed for admin preview (CSI camera)"""
    def generate():
        while camera_manager.preview_active and camera_manager.csi_camera:
            try:
                # Capture frame from CSI camera
                frame = camera_manager.csi_camera.capture_array()
                
                # Convert to PIL Image
                img = Image.fromarray(frame)
                
                # Convert to JPEG
                img_io = io.BytesIO()
                img.save(img_io, 'JPEG', quality=70)
                img_io.seek(0)
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + img_io.read() + b'\r\n')
                
                time.sleep(0.1)  # ~10 FPS
                
            except Exception as e:
                print(f"Error in camera feed: {e}")
                break
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# Interview recording endpoints (unchanged)
@app.route('/api/start_interview', methods=['POST'])
def start_interview():
    """API endpoint to start interview recording"""
    try:
        if camera_manager.recording:
            return jsonify({'error': 'Already recording'}), 400
        
        # Check if CSI camera is available
        if camera_manager.csi_camera_num is None:
            return jsonify({'error': 'CSI camera not found'}), 400
        
        # Initialize CSI camera
        if not camera_manager.init_csi_camera():
            return jsonify({'error': 'Failed to initialize CSI camera'}), 500
        
        # Generate timestamp filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_filename = f'interview_{timestamp}.mp4'
        audio_filename = f'interview_{timestamp}.wav'
        
        video_filepath = GALLERY_PATH / video_filename
        audio_filepath = GALLERY_PATH / audio_filename
        
        # Start camera
        camera_manager.csi_camera.start()
        time.sleep(2)  # 2 second delay as requested
        
        # Start audio recording first
        try:
            # Try different audio devices/methodsx
            audio_commands = [
                ['arecord', '-D', 'plughw:1,0', '-f', 'cd', '-t', 'wav', audio_filepath],
                ['arecord', '-D', 'hw:1,0', '-f', 'cd', '-t', 'wav', audio_filepath],
                ['arecord', '-D', 'plughw:0,0', '-f', 'cd', '-t', 'wav', audio_filepath],
                ['arecord', '-f', 'cd', '-t', 'wav', audio_filepath]  # Use default device
            ]
            
            audio_started = False
            for cmd in audio_commands:
                try:
                    camera_manager.audio_process = subprocess.Popen(
                        cmd, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL
                    )
                    time.sleep(0.5)  # Brief test
                    if camera_manager.audio_process.poll() is None:  # Still running
                        audio_started = True
                        print(f"Audio recording started with command: {' '.join(cmd)}")
                        break
                    else:
                        camera_manager.audio_process = None
                except Exception as e:
                    print(f"Audio command failed: {cmd} - {e}")
                    camera_manager.audio_process = None
            
            if not audio_started:
                print("Warning: Could not start audio recording")
                
        except Exception as e:
            print(f"Audio setup error: {e}")
        
        # Start video recording
        encoder = H264Encoder(bitrate=2000000)  # Lower bitrate for Pi 3B
        camera_manager.csi_camera.start_recording(encoder, video_filepath)
        camera_manager.recording = True
        
        # Store file paths for cleanup
        camera_manager.current_video = video_filepath
        camera_manager.current_audio = audio_filepath
        
        return jsonify({
            'success': True,
            'message': 'Interview recording started',
            'filename': video_filename
        })
        
    except Exception as e:
        camera_manager.cleanup_csi_camera()
        return jsonify({'error': f'Error starting interview: {str(e)}'}), 500

@app.route('/api/stop_interview', methods=['POST'])
def stop_interview():
    """API endpoint to stop interview recording"""
    try:
        if not camera_manager.recording:
            return jsonify({'error': 'Not currently recording'}), 400
        
        # Stop video recording
        camera_manager.csi_camera.stop_recording()
        camera_manager.recording = False
        
        # Stop audio recording
        if camera_manager.audio_process:
            try:
                camera_manager.audio_process.terminate()
                camera_manager.audio_process.wait(timeout=5)
                print("Audio recording stopped")
            except subprocess.TimeoutExpired:
                camera_manager.audio_process.kill()
                print("Audio recording force killed")
            except Exception as e:
                print(f"Error stopping audio: {e}")
        
        # Combine audio and video if both exist
        final_video = camera_manager.current_video
        if (camera_manager.current_audio and 
            os.path.exists(camera_manager.current_audio) and 
            os.path.getsize(camera_manager.current_audio) > 1000):  # Audio file has content
            
            combined_file = camera_manager.current_video.replace('.mp4', '_combined.mp4')
            try:
                # Use ffmpeg to combine audio and video
                result = subprocess.run([
                    'ffmpeg', '-y',  # Overwrite output file
                    '-i', camera_manager.current_video,
                    '-i', camera_manager.current_audio,
                    '-c:v', 'copy',  # Copy video stream
                    '-c:a', 'aac',   # Encode audio to AAC
                    '-shortest',     # Stop when shortest stream ends
                    combined_file
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    # Success - replace original with combined
                    os.remove(camera_manager.current_video)
                    os.remove(camera_manager.current_audio)
                    os.rename(combined_file, camera_manager.current_video)
                    print("Audio and video combined successfully")
                else:
                    print(f"FFmpeg error: {result.stderr}")
                    # Keep original video file, remove audio
                    if os.path.exists(camera_manager.current_audio):
                        os.remove(camera_manager.current_audio)
                
            except subprocess.TimeoutExpired:
                print("FFmpeg timeout - keeping original video")
                if os.path.exists(camera_manager.current_audio):
                    os.remove(camera_manager.current_audio)
            except Exception as e:
                print(f"Error combining audio/video: {e}")
                if os.path.exists(camera_manager.current_audio):
                    os.remove(camera_manager.current_audio)
        else:
            print("No valid audio file found - keeping video only")
            if camera_manager.current_audio and os.path.exists(camera_manager.current_audio):
                os.remove(camera_manager.current_audio)
        
        # Send the final video to remote display
        if os.path.exists(camera_manager.current_video):
            send_to_remote_display(camera_manager.current_video)
        
        camera_manager.cleanup_csi_camera()
        
        return jsonify({
            'success': True,
            'message': 'Interview recording stopped and saved'
        })
        
    except Exception as e:
        camera_manager.cleanup_csi_camera()
        return jsonify({'error': f'Error stopping interview: {str(e)}'}), 500

@app.route('/gallery/<filename>')
def serve_gallery_file(filename):
    """Serve files from gallery directory"""
    return send_from_directory(GALLERY_PATH, filename)

@app.route('/api/delete_file/<filename>', methods=['DELETE'])
def delete_file(filename):
    """Delete a file from gallery"""
    try:
        print(f"\n=== Delete File Request ===")
        print(f"Filename: {filename}")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        
        file_path = GALLERY_PATH / filename
        print(f"Full path: {file_path.absolute()}")
        print(f"File exists: {file_path.exists()}")
        
        if file_path.exists():
            try:
                file_path.unlink()
                print(f"Successfully deleted file: {filename}")
                return jsonify({
                    'success': True,
                    'message': 'File deleted',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                print(f"Error during deletion: {str(e)}")
                return jsonify({'error': f'Error deleting file: {str(e)}'}), 500
        else:
            print(f"File not found: {file_path}")
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        print(f"Exception in delete_file: {str(e)}")
        return jsonify({'error': f'Error deleting file: {str(e)}'}), 500

@app.route('/api/download_all', methods=['GET'])
def download_all():
    """Create a zip file of all gallery files and send it"""
    try:
        import tempfile
        import subprocess
        
        # Create a temporary file for the zip
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip.close()  # Close so we can use it with subprocess
        
        print(f"Creating zip file at: {temp_zip.name}")
        
        # Use zip command to create archive
        result = subprocess.run(['zip', '-j', temp_zip.name, f'{GALLERY_PATH}/*'], 
                              capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Error creating zip: {result.stderr}")
            raise Exception(f"zip command failed: {result.stderr}")
        
        print("Zip file created successfully")
        
        # Send the zip file
        return send_file(
            temp_zip.name,
            mimetype='application/zip',
            as_attachment=True,
            download_name='gallery.zip'
        )
    except Exception as e:
        print(f"Error in download_all: {str(e)}")
        return jsonify({'error': f'Error creating zip file: {str(e)}'}), 500
    finally:
        # Clean up the temporary file
        try:
            os.unlink(temp_zip.name)
            print(f"Cleaned up temporary zip file: {temp_zip.name}")
        except Exception as e:
            print(f"Error cleaning up temp file: {str(e)}")

@app.route('/api/clear_gallery', methods=['POST'])
def clear_gallery():
    """Delete all files from the gallery"""
    try:
        print(f"\n=== Clear Gallery Request ===")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Gallery path: {GALLERY_PATH.absolute()}")
        
        count = 0
        for file_path in GALLERY_PATH.glob('*'):
            if file_path.is_file():
                try:
                    file_path.unlink()
                    count += 1
                    print(f"Deleted file: {file_path}")
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")
        
        print(f"Gallery cleared. Removed {count} files.")
        return jsonify({
            'success': True,
            'cleared_count': count,
            'message': f'Successfully cleared {count} files',
            'timestamp': datetime.now().isoformat()
        })
            
    except Exception as e:
        print(f"Exception in clear_gallery: {str(e)}")
        return jsonify({'error': f'Error clearing gallery: {str(e)}'}), 500

@app.route('/api/status')
def get_status():
    """Get current recording status and camera info"""
    return jsonify({
        'recording': camera_manager.recording,
        'audio_active': camera_manager.audio_process is not None and camera_manager.audio_process.poll() is None,
        'available_cameras': len(camera_manager.available_cameras),
        'csi_camera': camera_manager.csi_camera_num is not None,
        'droidcam_active': camera_manager.droidcam_active,
        'preview_active': camera_manager.preview_active
    })

@app.route('/api/interview_events')
def interview_events_stream():
    """Stream interview events to clients"""
    def generate():
        last_timestamp = 0
        while True:
            with event_lock:
                # Send any new events
                for event in interview_events:
                    if event['timestamp'] > last_timestamp:
                        yield f"data: {json.dumps(event)}\n\n"
                        last_timestamp = event['timestamp']
            time.sleep(1)  # Check every second
    
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache',
                           'Connection': 'keep-alive'})

@app.route('/api/interview_prompt', methods=['GET', 'POST'])
def interview_prompt():
    """Handle interview prompt setting and retrieval"""
    global current_interview_prompt
    if request.method == 'POST':
        try:
            data = request.get_json()
            prompt = data.get('prompt', '').strip()
            if prompt:
                current_interview_prompt = prompt
                # Add event for interview page
                add_interview_event('new_prompt', {
                    'prompt': prompt,
                    'auto_start': True
                })
                return jsonify({'success': True, 'prompt': current_interview_prompt})
            else:
                return jsonify({'error': 'No prompt provided'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:  # GET
        return jsonify({'prompt': current_interview_prompt})

@app.route('/api/interview_trigger', methods=['GET', 'POST'])
def interview_trigger_route():
    global interview_trigger
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if data.get('reset'):
            interview_trigger = False
            return jsonify({'success': True, 'reset': True})
        else:
            interview_trigger = True
            # Start the interview when trigger is set
            try:
                if not camera_manager.recording:
                    start_interview()
            except Exception as e:
                print(f"Error starting interview from trigger: {e}")
            return jsonify({'success': True})
    else:
        return jsonify({'trigger': interview_trigger})

@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("\nShutting down...")
    camera_manager.cleanup_csi_camera()
    camera_manager.stop_droidcam_preview()
    exit(0)

if __name__ == '__main__':
    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Run the Flask app
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        # Cleanup on exit
        camera_manager.cleanup_csi_camera()
        camera_manager.stop_droidcam_preview()