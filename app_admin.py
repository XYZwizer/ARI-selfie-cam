#!/usr/bin/env python3
"""
Lightweight Raspberry Pi Camera Server with Flask
Uses picamera2 for both UVC camera (selfies) and CSI camera (interviews)
Now includes admin control page with ARI robot integration
"""

import os
import time
import threading
import signal
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, Response
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
import subprocess
import glob
import io
import base64
from PIL import Image

app = Flask(__name__)

# Configuration
GALLERY_PATH = 'static/gallery'
INTERVIEW_DURATION = 300  # 5 minutes max
ARI_BASE_URL = 'http://ari-Xc'  # Default ARI robot URL - change as needed

# Ensure gallery directory exists
os.makedirs(GALLERY_PATH, exist_ok=True)

class CameraManager:
    def __init__(self):
        self.csi_camera = None
        self.uvc_camera = None
        self.recording = False
        self.audio_process = None
        self.current_video = None
        self.current_audio = None
        self.available_cameras = []
        self.preview_active = False
        self.detect_cameras()
        
    def detect_cameras(self):
        """Detect available cameras"""
        try:
            self.available_cameras = Picamera2.global_camera_info()
            print(f"Available cameras: {self.available_cameras}")
            
            # Find CSI and UVC cameras
            self.csi_camera_num = None
            self.uvc_camera_num = None
            
            for i, cam_info in enumerate(self.available_cameras):
                model = cam_info.get('Model', '').lower()
                if 'imx' in model or 'ov' in model:  # Common CSI camera models
                    self.csi_camera_num = i
                    print(f"Found CSI camera at index {i}: {model}")
                elif 'usb' in model or 'uvc' in model or cam_info.get('Num', 99) > 0:
                    self.uvc_camera_num = i
                    print(f"Found UVC camera at index {i}: {model}")
                    
        except Exception as e:
            print(f"Error detecting cameras: {e}")
            # Fallback assumptions
            self.csi_camera_num = 0
            self.uvc_camera_num = 1 if len(self.available_cameras) > 1 else None
    
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
    
    def init_uvc_camera(self):
        """Initialize UVC camera for selfies"""
        try:
            if self.uvc_camera is None and self.uvc_camera_num is not None:
                self.uvc_camera = Picamera2(self.uvc_camera_num)
                # Configuration for still capture
                config = self.uvc_camera.create_still_configuration(
                    main={"size": (1280, 720)}
                )
                self.uvc_camera.configure(config)
            return True
        except Exception as e:
            print(f"Failed to initialize UVC camera: {e}")
            return False
    
    def init_uvc_preview(self):
        """Initialize UVC camera for preview (admin page)"""
        try:
            if self.uvc_camera is None and self.uvc_camera_num is not None:
                self.uvc_camera = Picamera2(self.uvc_camera_num)
                # Configuration for preview/streaming
                config = self.uvc_camera.create_preview_configuration(
                    main={"size": (640, 480)}  # Smaller size for streaming
                )
                self.uvc_camera.configure(config)
            return True
        except Exception as e:
            print(f"Failed to initialize UVC camera for preview: {e}")
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
    
    def cleanup_uvc_camera(self):
        """Clean up UVC camera resources"""
        if self.uvc_camera:
            try:
                if self.uvc_camera.started:
                    self.uvc_camera.stop()
                self.uvc_camera.close()
                self.uvc_camera = None
            except Exception as e:
                print(f"Error cleaning up UVC camera: {e}")
        self.preview_active = False

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
    """Selfie capture page"""
    return render_template('selfie.html')

@app.route('/interview')
def interview_page():
    """Interview recording page"""
    return render_template('interview.html')

@app.route('/gallery')
def gallery_page():
    """Gallery page showing all captured media"""
    # Get all files from gallery directory
    image_files = glob.glob(os.path.join(GALLERY_PATH, '*.jpg'))
    video_files = glob.glob(os.path.join(GALLERY_PATH, '*.mp4'))
    
    # Sort by modification time (newest first)
    all_files = image_files + video_files
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    # Extract just the filename for template
    files = [os.path.basename(f) for f in all_files]
    
    return render_template('gallery.html', files=files)

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
    """Start camera preview for admin"""
    try:
        if camera_manager.preview_active:
            return jsonify({'error': 'Preview already active'}), 400
        
        if not camera_manager.init_uvc_preview():
            return jsonify({'error': 'Failed to initialize camera for preview'}), 500
        
        camera_manager.uvc_camera.start()
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
        
        camera_manager.cleanup_uvc_camera()
        
        return jsonify({'success': True, 'message': 'Preview stopped'})
        
    except Exception as e:
        return jsonify({'error': f'Error stopping preview: {str(e)}'}), 500

@app.route('/admin/camera_feed')
def camera_feed():
    """Video feed for admin preview"""
    def generate():
        while camera_manager.preview_active and camera_manager.uvc_camera:
            try:
                # Capture frame
                frame = camera_manager.uvc_camera.capture_array()
                
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

# Original API endpoints (unchanged)
@app.route('/api/take_selfie', methods=['POST'])
def take_selfie():
    """API endpoint to take a selfie using UVC camera with picamera2"""
    try:
        # Check if UVC camera is available
        if camera_manager.uvc_camera_num is None:
            return jsonify({'error': 'UVC camera not found'}), 400
        
        # Stop preview if active
        was_preview_active = camera_manager.preview_active
        if camera_manager.preview_active:
            camera_manager.cleanup_uvc_camera()
        
        # Initialize UVC camera
        if not camera_manager.init_uvc_camera():
            return jsonify({'error': 'Failed to initialize UVC camera'}), 500
        
        # Generate timestamp filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'selfie_{timestamp}.jpg'
        filepath = os.path.join(GALLERY_PATH, filename)
        
        try:
            # Start camera, capture image, then stop
            camera_manager.uvc_camera.start()
            time.sleep(2)  # Let camera warm up
            
            # Capture the image
            camera_manager.uvc_camera.capture_file(filepath)
            
            camera_manager.uvc_camera.stop()
            
            # Restart preview if it was active
            if was_preview_active:
                camera_manager.init_uvc_preview()
                camera_manager.uvc_camera.start()
                camera_manager.preview_active = True
            
            return jsonify({
                'success': True, 
                'filename': filename,
                'message': 'Selfie captured successfully!'
            })
            
        except Exception as e:
            return jsonify({'error': f'Failed to capture selfie: {e}'}), 500
        finally:
            if not was_preview_active:
                camera_manager.cleanup_uvc_camera()
            
    except Exception as e:
        camera_manager.cleanup_uvc_camera()
        return jsonify({'error': f'Error taking selfie: {str(e)}'}), 500

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
        
        video_filepath = os.path.join(GALLERY_PATH, video_filename)
        audio_filepath = os.path.join(GALLERY_PATH, audio_filename)
        
        # Start camera
        camera_manager.csi_camera.start()
        time.sleep(2)  # 2 second delay as requested
        
        # Start audio recording first
        try:
            # Try different audio devices/methods
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
        filepath = os.path.join(GALLERY_PATH, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True, 'message': 'File deleted'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': f'Error deleting file: {str(e)}'}), 500

@app.route('/api/status')
def get_status():
    """Get current recording status and camera info"""
    return jsonify({
        'recording': camera_manager.recording,
        'audio_active': camera_manager.audio_process is not None and camera_manager.audio_process.poll() is None,
        'available_cameras': len(camera_manager.available_cameras),
        'csi_camera': camera_manager.csi_camera_num is not None,
        'uvc_camera': camera_manager.uvc_camera_num is not None,
        'preview_active': camera_manager.preview_active
    })

@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("\nShutting down...")
    camera_manager.cleanup_csi_camera()
    camera_manager.cleanup_uvc_camera()
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
        camera_manager.cleanup_uvc_camera()