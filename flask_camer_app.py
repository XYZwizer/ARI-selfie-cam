#!/usr/bin/env python3
"""
Raspberry Pi Camera Server with Flask
Supports UVC camera for selfies and CSI camera for interviews
"""

import os
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import FileOutput
import cv2
import subprocess
import glob

app = Flask(__name__)

# Configuration
GALLERY_PATH = 'static/gallery'
UVC_DEVICE = '/dev/video0'  # Default, will be configurable
INTERVIEW_DURATION = 300  # 5 minutes max
CSI_CAMERA_INDEX = 0

# Ensure gallery directory exists
os.makedirs(GALLERY_PATH, exist_ok=True)

class CameraManager:
    def __init__(self):
        self.picam2 = None
        self.recording = False
        self.countdown_active = False
        
    def init_csi_camera(self):
        """Initialize CSI camera with picamera2"""
        try:
            if self.picam2 is None:
                self.picam2 = Picamera2()
                config = self.picam2.create_video_configuration(
                    main={"size": (1920, 1080)},
                    lores={"size": (640, 480)},
                    display="lores"
                )
                self.picam2.configure(config)
            return True
        except Exception as e:
            print(f"Failed to initialize CSI camera: {e}")
            return False
    
    def cleanup_csi_camera(self):
        """Clean up CSI camera resources"""
        if self.picam2:
            try:
                if self.recording:
                    self.picam2.stop_recording()
                    self.recording = False
                self.picam2.stop()
                self.picam2.close()
                self.picam2 = None
            except Exception as e:
                print(f"Error cleaning up CSI camera: {e}")

camera_manager = CameraManager()

@app.route('/')
def index():
    """Main menu page"""
    return render_template('index.html')

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

@app.route('/api/take_selfie', methods=['POST'])
def take_selfie():
    """API endpoint to take a selfie using UVC camera"""
    try:
        # Check if UVC camera is available
        if not os.path.exists(UVC_DEVICE):
            return jsonify({'error': f'UVC camera not found at {UVC_DEVICE}'}), 400
        
        # Generate timestamp filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'selfie_{timestamp}.jpg'
        filepath = os.path.join(GALLERY_PATH, filename)
        
        # Initialize camera
        cap = cv2.VideoCapture(UVC_DEVICE)
        if not cap.isOpened():
            return jsonify({'error': 'Failed to open UVC camera'}), 500
        
        # Set camera properties for better quality
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        # Take the photo
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            # Save the image
            cv2.imwrite(filepath, frame)
            return jsonify({
                'success': True, 
                'filename': filename,
                'message': 'Selfie captured successfully!'
            })
        else:
            return jsonify({'error': 'Failed to capture image'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error taking selfie: {str(e)}'}), 500

@app.route('/api/start_interview', methods=['POST'])
def start_interview():
    """API endpoint to start interview recording"""
    try:
        if camera_manager.recording:
            return jsonify({'error': 'Already recording'}), 400
        
        # Initialize CSI camera
        if not camera_manager.init_csi_camera():
            return jsonify({'error': 'Failed to initialize CSI camera'}), 500
        
        # Generate timestamp filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'interview_{timestamp}.mp4'
        filepath = os.path.join(GALLERY_PATH, filename)
        
        # Start camera
        camera_manager.picam2.start()
        time.sleep(2)  # 2 second delay as requested
        
        # Start recording with audio
        encoder = H264Encoder(bitrate=10000000)
        
        # For audio recording, we'll use a separate process
        audio_file = os.path.join(GALLERY_PATH, f'interview_{timestamp}.wav')
        audio_process = subprocess.Popen([
            'arecord', '-D', 'plughw:1,0', '-f', 'cd', '-t', 'wav', audio_file
        ])
        
        camera_manager.picam2.start_recording(encoder, filepath)
        camera_manager.recording = True
        
        # Store audio process for cleanup
        camera_manager.audio_process = audio_process
        camera_manager.current_video = filepath
        camera_manager.current_audio = audio_file
        
        return jsonify({
            'success': True,
            'message': 'Interview recording started',
            'filename': filename
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
        
        # Stop recording
        camera_manager.picam2.stop_recording()
        camera_manager.recording = False
        
        # Stop audio recording
        if hasattr(camera_manager, 'audio_process'):
            camera_manager.audio_process.terminate()
            camera_manager.audio_process.wait()
        
        # Combine audio and video using ffmpeg
        if hasattr(camera_manager, 'current_video') and hasattr(camera_manager, 'current_audio'):
            combined_file = camera_manager.current_video.replace('.mp4', '_combined.mp4')
            try:
                subprocess.run([
                    'ffmpeg', '-i', camera_manager.current_video,
                    '-i', camera_manager.current_audio,
                    '-c:v', 'copy', '-c:a', 'aac',
                    '-shortest', combined_file
                ], check=True)
                
                # Remove original files and rename combined
                os.remove(camera_manager.current_video)
                os.remove(camera_manager.current_audio)
                os.rename(combined_file, camera_manager.current_video)
                
            except subprocess.CalledProcessError:
                print("Warning: Failed to combine audio and video")
        
        camera_manager.cleanup_csi_camera()
        
        return jsonify({
            'success': True,
            'message': 'Interview recording stopped'
        })
        
    except Exception as e:
        camera_manager.cleanup_csi_camera()
        return jsonify({'error': f'Error stopping interview: {str(e)}'}), 500

@app.route('/api/selfie_stream')
def selfie_stream():
    """Stream from UVC camera for selfie preview"""
    def generate():
        cap = cv2.VideoCapture(UVC_DEVICE)
        if not cap.isOpened():
            return
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Encode frame as JPEG
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_bytes = buffer.tobytes()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                time.sleep(0.033)  # ~30 FPS
        finally:
            cap.release()
    
    from flask import Response
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/interview_stream')
def interview_stream():
    """Stream from CSI camera for interview preview"""
    def generate():
        if not camera_manager.picam2:
            return
        
        try:
            while camera_manager.recording:
                # Get frame from lores stream
                frame = camera_manager.picam2.capture_array("lores")
                
                # Convert from RGB to BGR for OpenCV
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                
                # Encode frame as JPEG
                _, buffer = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_bytes = buffer.tobytes()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                time.sleep(0.033)  # ~30 FPS
        except Exception as e:
            print(f"Streaming error: {e}")
    
    from flask import Response
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

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

@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

if __name__ == '__main__':
    try:
        # Run the Flask app
        app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
    finally:
        # Cleanup on exit
        camera_manager.cleanup_csi_camera()
