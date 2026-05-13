// Force fullscreen on first user interaction (hides mobile browser chrome)
function requestFullscreen() {
    const el = document.documentElement;
    if (el.requestFullscreen) {
        el.requestFullscreen();
    } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
    }
}
['click', 'touchstart'].forEach(evt =>
    document.addEventListener(evt, requestFullscreen, { once: true })
);

// IP Constants
const ARI_IP = '192.168.0.100';
const SLIDESHOW_IP = '192.168.0.133';
let ws;
let movementEnabled = false;
let isFastMode = false;
let volumeTimer = null;

// Speed toggle functionality
document.getElementById('speedToggle').addEventListener('change', function(e) {
    isFastMode = e.target.checked;
    const speedStatus = document.getElementById('speedStatus');
    
    if (isFastMode) {
        speedStatus.textContent = 'Fast';
        speedStatus.style.color = '#28a745';
    } else {
        speedStatus.textContent = 'Slow';
        speedStatus.style.color = '#ffc107';
    }
});

// Chatbot toggle functionality
document.getElementById('chatbotToggle').addEventListener('change', function(e) {
    const isActive = e.target.checked;
    const chatbotStatus = document.getElementById('chatbotStatus');
    
    // Send the boolean to the active_listening topic
    if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = {
            op: "publish",
            topic: "/active_listening",
            msg: {
                data: isActive
            }
        };
        ws.send(JSON.stringify(msg));
    }
    
    // Update status display
    if (isActive) {
        chatbotStatus.textContent = 'On';
        chatbotStatus.style.color = '#28a745';
    } else {
        chatbotStatus.textContent = 'Off';
        chatbotStatus.style.color = '#6c757d';
    }
});

// Volume control
function checkVolume() {
    fetch(`http://${ARI_IP}/touch_web_mgr`)
        .then(response => response.json())
        .then(data => {
            if (data && data.volume !== undefined) {
                const volume = data.volume;
                const volumeSlider = document.getElementById('volume');
                const volumeValue = document.getElementById('volumeValue');
                
                // Only update if the slider isn't being dragged
                if (!volumeSlider.matches(':active')) {
                    volumeSlider.value = volume;
                    volumeValue.textContent = volume;
                }
            }
        })
        .catch(error => console.error('Error checking volume:', error));
}

// Set volume
function setVolume(value) {
    fetch(`http://${ARI_IP}/param/volume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parseInt(value)) 
    })
    .catch(error => console.error('Error setting volume:', error));
}

// Initialize volume control
document.addEventListener('DOMContentLoaded', function() {
    const volumeSlider = document.getElementById('volume');
    const volumeValue = document.getElementById('volumeValue');
    
    // Start volume check interval
    volumeTimer = setInterval(checkVolume, 1000);
    
    // Update volume value display while sliding
    volumeSlider.addEventListener('input', function() {
        volumeValue.textContent = this.value;
    });

    // Send volume change when slider is released
    volumeSlider.addEventListener('change', function() {
        setVolume(this.value);
    });
});

// Clean up interval when page is unloaded
window.addEventListener('beforeunload', function() {
    if (volumeTimer) {
        clearInterval(volumeTimer);
    }
});

// Movement lock functionality
document.getElementById('movementLock').addEventListener('change', function(e) {
    movementEnabled = e.target.checked;
    const joystickArea = document.getElementById('joystickArea');
    const lockStatus = document.getElementById('lockStatus');
    
    if (movementEnabled) {
        joystickArea.classList.remove('disabled');
        lockStatus.textContent = '🔓 Unlocked';
        lockStatus.style.color = '#28a745';
    } else {
        joystickArea.classList.add('disabled');
        lockStatus.textContent = '🔒 Locked';
        lockStatus.style.color = '#dc3545';
        // Send stop command when locking
        sendTwist(0, 0);
    }
});

// WebSocket connection
function connectWebSocket() {
    ws = new WebSocket(`ws://${ARI_IP}:9090`);

    ws.onopen = () => {
        document.getElementById('joystickStatus').innerText = '✅ Connected to ROS bridge';
    };

    ws.onclose = () => {
        document.getElementById('joystickStatus').innerText = '❌ Disconnected from ROS bridge';
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        document.getElementById('joystickStatus').innerText = '❌ Connection error';
    };
}

function sendTwist(linear_x, angular_z) {
    if (!movementEnabled) {
        return; // Don't send commands if movement is locked
    }
    
    // Apply speed reduction in slow mode
    if (!isFastMode) {
        linear_x *= 0.5;
        angular_z *= 0.5;
    }
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = {
            op: "publish",
            topic: "/rviz_joy_vel",
            msg: {
                linear: { x: linear_x, y: 0, z: 0 },
                angular: { x: 0, y: 0, z: angular_z }
            }
        };
        ws.send(JSON.stringify(msg));
    }
}

// Joystick functionality
class VirtualJoystick {
    constructor(container, knob) {
        this.container = container;
        this.knob = knob;
        this.isDragging = false;
        this.centerX = 0;
        this.centerY = 0;
        this.currentX = 0;
        this.currentY = 0;
        this.maxDistance = 40;
        
        this.init();
    }
    
    init() {
        const rect = this.container.getBoundingClientRect();
        this.centerX = rect.width / 2;
        this.centerY = rect.height / 2;
        const computedMax = Math.round(rect.width * 0.33);
        if (computedMax > 0) this.maxDistance = computedMax;

        this.knob.addEventListener('mousedown', this.startDrag.bind(this));
        this.knob.addEventListener('touchstart', this.startDrag.bind(this));
        
        document.addEventListener('mousemove', this.drag.bind(this));
        document.addEventListener('touchmove', this.drag.bind(this));
        
        document.addEventListener('mouseup', this.stopDrag.bind(this));
        document.addEventListener('touchend', this.stopDrag.bind(this));
        
        this.container.addEventListener('click', this.moveToClick.bind(this));
        this.container.addEventListener('contextmenu', e => e.preventDefault());
    }
    
    startDrag(e) {
        if (!movementEnabled) {
            e.preventDefault();
            return;
        }
        this.isDragging = true;
        this.knob.style.transition = 'none';
        e.preventDefault();
    }
    
    drag(e) {
        if (!this.isDragging || !movementEnabled) return;
        
        const rect = this.container.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        
        const x = clientX - rect.left - this.centerX;
        const y = clientY - rect.top - this.centerY;
        
        this.updatePosition(this.normalize(x), this.normalize(y));
        e.preventDefault();
    }
    
    stopDrag() {
        if (!this.isDragging) return;
        this.isDragging = false;
        this.knob.style.transition = 'all 0.2s ease-out';
        this.returnToCenter();
    }
    
    moveToClick(e) {
        if (this.isDragging || !movementEnabled) return;
        
        const rect = this.container.getBoundingClientRect();
        const x = e.clientX - rect.left - this.centerX;
        const y = e.clientY - rect.top - this.centerY;
        
        this.knob.style.transition = 'all 0.2s ease-out';
        this.updatePosition(this.normalize(x), this.normalize(y));

        setTimeout(() => this.returnToCenter(), 200);
    }

    normalize(v) {
        const normalizedV = v / this.maxDistance;
        return normalizedV;
    }

    updatePosition(x, y) {
        //limit by max
        const distance = Math.sqrt(x * x + y * y);    
        if (distance > 1) {
            const angle = Math.atan2(y, x);
            x = Math.cos(angle);
            y = Math.sin(angle);
        }
        
        this.currentX = x;
        this.currentY = y;
        
        const half_knob = this.knob.offsetWidth / 2;
        this.knob.style.transform = `translate(${(x * this.maxDistance) - half_knob}px, ${(y * this.maxDistance) - half_knob}px)`;
                
        // Send joystick data to server (rotated 90° clockwise to match API orientation)
        sendTwist(y, x);
    }
    
    
    returnToCenter() {
        this.updatePosition(0,0);
}
}
var movemnt_joystick = null;
// Initialize joystick when page loads
document.addEventListener('DOMContentLoaded', function() {
    const joystickArea = document.getElementById('joystickArea');
    const joystickKnob = document.getElementById('joystickKnob');
    movemnt_joystick = new VirtualJoystick(joystickArea, joystickKnob);
    connectWebSocket();
});

var gamepad_poll_intervl = null;
var gamepad = null;

window.addEventListener("gamepadconnected", (event) => {
    if (gamepad != null) return;
    gamepad = event.gamepad;
    document.getElementById('joystickStatus').innerText = `🎮 Gamepad: ${gamepad.id.slice(0, 28)}`;
    gamepad_poll_intervl = setInterval(function() {
        const pads = navigator.getGamepads();
        const freshPad = pads[gamepad.index];
        if (!freshPad || !movementEnabled) return;
        movemnt_joystick.updatePosition(freshPad.axes[0], freshPad.axes[1]);
    }, 30);
});

window.addEventListener("gamepaddisconnected", (event) => {
    if (gamepad == event.gamepad) {
        gamepad = null;
        clearInterval(gamepad_poll_intervl);
        gamepad_poll_intervl = null;
        document.getElementById('joystickStatus').innerText = '🎮 Gamepad disconnected';
        movemnt_joystick.returnToCenter();
    }
});

// Re-compute joystick dimensions after orientation change
window.addEventListener('orientationchange', () => {
    setTimeout(() => {
        if (movemnt_joystick) {
            const rect = movemnt_joystick.container.getBoundingClientRect();
            movemnt_joystick.centerX = rect.width / 2;
            movemnt_joystick.centerY = rect.height / 2;
            const computedMax = Math.round(rect.width * 0.33);
            if (computedMax > 0) movemnt_joystick.maxDistance = computedMax;
        }
    }, 150);
});

function sendAriTTS(text) {
    fetch('/api/admin/ari_speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
    });
}

// Add keyboard event listeners for all sound inputs
document.querySelectorAll('.sound-input').forEach(input => {
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendAriTTS(this.value);
        }
    });
});

async function sendInterviewPrompt() {
    const input = document.getElementById('interviewInput');
    const text = input.value.trim();
    if (!text) return;
    
    const status = document.getElementById('interviewStatus');
    status.textContent = 'Sending prompt...';
    
    try {
        // Send to ARI TTS
        sendAriTTS(text);
        
        // Send to interview prompt endpoint
        const response = await fetch('/api/interview_prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: text })
        });
        
        if (response.ok) {
            status.textContent = 'Prompt sent successfully!';
            input.value = '';
        } else {
            throw new Error('Failed to send prompt');
        }
    } catch (error) {
        status.textContent = `Error: ${error.message}`;
    }
}

async function remoteStartInterview() {
    const status = document.getElementById('interviewStatus');
    status.textContent = 'Sending start command...';
// sendMotionGoal('raise_mic', 10);
        // sendAriMotion("raise_mic") 
sendAriMotion("raise_mic",10)
    try {
        const response = await fetch('/api/interview_events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'start_interview' })
        });
        
        if (response.ok) {
            status.textContent = 'Start command sent!';
        } else {
            throw new Error('Failed to send start command');
        }
    } catch (error) {
        status.textContent = `Error: ${error.message}`;
    }
}

async function remoteStopInterview() {
    const status = document.getElementById('interviewStatus');
    status.textContent = 'Sending stop command...';
    sendAriMotion("alive_1",20)
    try {
        const response = await fetch('/api/interview_events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'stop_interview' })
        });
        
        if (response.ok) {
            status.textContent = 'Stop command sent!';
        } else {
            throw new Error('Failed to send stop command');
        }
    } catch (error) {
        status.textContent = `Error: ${error.message}`;
    }
}

// Save soundboard settings to localStorage
function saveSoundboardSettings() {
    const sounds = {};
    document.querySelectorAll('.sound-input').forEach(input => {
        sounds[input.id] = input.value;
    });
    localStorage.setItem('soundboardSettings', JSON.stringify(sounds));
}

// Load soundboard settings from localStorage
function loadSoundboardSettings() {
    const savedSettings = localStorage.getItem('soundboardSettings');
    if (savedSettings) {
        const sounds = JSON.parse(savedSettings);
        Object.entries(sounds).forEach(([id, value]) => {
            const input = document.getElementById(id);
            if (input) {
                input.value = value;
            }
        });
    }
}

// Save settings when inputs change
document.querySelectorAll('.sound-input').forEach(input => {
    input.addEventListener('change', saveSoundboardSettings);
});

// Load settings when page loads
document.addEventListener('DOMContentLoaded', loadSoundboardSettings);

function sendAriMotion(motion,priority) {
    fetch('/api/admin/ari_motion', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motion: motion,priority: priority })
    });
}

// Battery status
function updateBatteryStatus() {
    fetch(`http://${ARI_IP}/topic/power_diagnostic`)
        .then(response => response.json())
        .then(data => {
            if (data && data.msg) {
                const power = data.msg;
                
                // Update battery level
                const batteryLevel = power.charge;
                document.getElementById('batteryCharge').textContent = Math.round(batteryLevel);
                
                // Update battery color based on level
                const batteryCharge = document.getElementById('batteryCharge');
                if (batteryLevel >= 50) {
                    batteryCharge.style.color = '#4a8e4c'; // Green
                } else if (batteryLevel > 19) {
                    batteryCharge.style.color = '#ffc400'; // Yellow
                } else {
                    batteryCharge.style.color = '#bf360c'; // Red
                }

                // Update voltage
                document.getElementById('batteryVoltage').textContent = power.input.toFixed(1);

                // Update dock status
                document.getElementById('batteryDocked').textContent = 
                    power.dock > 0 ? 'Yes' : 'No';

                // Update emergency status
                document.getElementById('emergencyState').textContent = 
                    power.is_emergency ? 'Yes' : 'No';
                
                // Update emergency state color
                const emergencyState = document.getElementById('emergencyState');
                emergencyState.style.color = power.is_emergency ? '#dc3545' : '#28a745';
            }
        })
        .catch(error => {
            console.error('Error fetching power diagnostic:', error);
            document.getElementById('batteryCharge').textContent = '--';
            document.getElementById('batteryVoltage').textContent = '--';
            document.getElementById('batteryDocked').textContent = '--';
            document.getElementById('emergencyState').textContent = '--';
        });
}

// Update battery status every 5 seconds
updateBatteryStatus();
setInterval(updateBatteryStatus, 5000);

// Function to send the message to the ROS bridge
function sendWebGoToMessage() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = {
            op: "publish",
            topic: "/web_go_to",
            msg: { "type": 4, "value": "list_our_pages" }
        };
        ws.send(JSON.stringify(msg));
    }
}

// Add a small floating button to the bottom right corner
const floatingButton = document.createElement('button');
floatingButton.innerHTML = '🔗';
floatingButton.style.position = 'fixed';
floatingButton.style.bottom = '20px';
floatingButton.style.right = '20px';
floatingButton.style.padding = '10px';
floatingButton.style.borderRadius = '50%';
floatingButton.style.backgroundColor = '#667eea';
floatingButton.style.color = 'white';
floatingButton.style.border = 'none';
floatingButton.style.cursor = 'pointer';
floatingButton.style.fontSize = '20px';
floatingButton.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
floatingButton.style.transition = 'transform 0.2s';
floatingButton.addEventListener('click', sendWebGoToMessage);
floatingButton.addEventListener('mouseenter', () => {
    floatingButton.style.transform = 'scale(1.1)';
});
floatingButton.addEventListener('mouseleave', () => {
    floatingButton.style.transform = 'scale(1)';
});
document.body.appendChild(floatingButton);