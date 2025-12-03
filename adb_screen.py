"""
ADB Screen Mirror & Control - Python Backend Server
This script runs a local web server that executes ADB commands and serves a web interface.

Requirements:
    pip install flask flask-cors pillow

Usage:
    1. Make sure ADB is installed and your device is connected
    2. Run: python adb_server.py
    3. Open your browser to: http://localhost:5000
"""

from flask import Flask, send_file, jsonify, request, render_template_string
from flask_cors import CORS
import subprocess
import time
import os
import io
from PIL import Image
import base64

app = Flask(__name__)
CORS(app)

# Configuration
SCREENSHOT_PATH = "/data/local/tmp/screen.png"
LOCAL_SCREENSHOT = "screen.png"

def run_adb_command(command):
    """Execute an ADB command and return the result"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def capture_screenshot():
    """Capture screenshot from Android device"""
    # Take screenshot on device
    success, _, error = run_adb_command(f"adb shell screencap -p {SCREENSHOT_PATH}")
    if not success:
        return False, f"Failed to capture screenshot: {error}"

    # Pull screenshot to computer
    success, _, error = run_adb_command(f"adb pull {SCREENSHOT_PATH} {LOCAL_SCREENSHOT}")
    if not success:
        return False, f"Failed to pull screenshot: {error}"

    # Delete screenshot from device
    run_adb_command(f"adb shell rm {SCREENSHOT_PATH}")

    return True, LOCAL_SCREENSHOT

def send_tap(x, y):
    """Send tap command to device"""
    success, _, error = run_adb_command(f"adb shell input tap {x} {y}")
    return success, error

@app.route('/')
def index():
    """Serve the web interface"""
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADB Screen Mirror & Control(1.0)</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 30px;
            max-width: 1200px;
            width: 100%;
        }

        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }

        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }

        .control-group {
            display: flex;
            flex-direction: column;
        }

        label {
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
            font-size: 14px;
        }

        select {
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }

        select:focus {
            outline: none;
            border-color: #667eea;
        }

        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }

        .btn-primary {
            background: #667eea;
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        .btn-danger {
            background: #dc3545;
            color: white;
        }

        .btn-danger:hover:not(:disabled) {
            background: #c82333;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(220, 53, 69, 0.4);
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .status {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 500;
        }

        .status.info {
            background: #cfe2ff;
            color: #084298;
            border: 1px solid #b6d4fe;
        }

        .status.success {
            background: #d1e7dd;
            color: #0f5132;
            border: 1px solid #badbcc;
        }

        .status.error {
            background: #f8d7da;
            color: #842029;
            border: 1px solid #f5c2c7;
        }

        .screen-container {
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
            margin-top: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            max-width: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 400px;
        }

        #screenImage {
            max-width: 100%;
            height: auto;
            display: none;
            cursor: crosshair;
        }

        .screen-placeholder {
            padding: 100px 20px;
            text-align: center;
            color: #666;
        }

        .screen-placeholder svg {
            width: 100px;
            height: 100px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .stats {
            display: flex;
            justify-content: space-around;
            margin-top: 20px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }

        .stat-item {
            text-align: center;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: #667eea;
        }

        .stat-label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }

        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(102, 126, 234, 0.3);
            border-radius: 50%;
            border-top-color: #667eea;
            animation: spin 1s ease-in-out infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>ADB Screen Mirror & Control(1.0)</h1>
        <p class="subtitle">Control your Android device - Python backend is running!</p>

        <div id="status" class="status info">
            Ready to connect. Click "Start Mirroring" to begin.
        </div>

        <div class="controls">
            <div class="control-group">
                <label for="refreshRate">Refresh Rate (ms)</label>
                <select id="refreshRate">
                    <option value="500">500ms (2 FPS)</option>
                    <option value="750">750ms (1.3 FPS)</option>
                    <option value="1000" selected>1000ms (1 FPS)</option>
                    <option value="1500">1500ms (0.7 FPS)</option>
                    <option value="2000">2000ms (0.5 FPS)</option>
                </select>
            </div>

            <div class="control-group">
                <button id="startBtn" class="btn-primary">▶ Start Mirroring</button>
            </div>

            <div class="control-group">
                <button id="stopBtn" class="btn-danger" disabled>⏹ Stop Mirroring</button>
            </div>

            <div class="control-group">
                <button id="testBtn" class="btn-primary">🔍 Test ADB Connection</button>
            </div>
        </div>

        <div class="screen-container">
            <div id="placeholder" class="screen-placeholder">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
                    <line x1="12" y1="18" x2="12.01" y2="18"></line>
                </svg>
                <p>Screen will appear here once mirroring starts</p>
            </div>
            <img id="screenImage" alt="Android Screen">
        </div>

        <div class="stats">
            <div class="stat-item">
                <div class="stat-value" id="frameCount">0</div>
                <div class="stat-label">Frames Captured</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="tapCount">0</div>
                <div class="stat-label">Taps Sent</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="swipeCount">0</div>
                <div class="stat-label">Swipes Sent</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="errorCount">0</div>
                <div class="stat-label">Errors</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="latency">0ms</div>
                <div class="stat-label">Avg Latency</div>
            </div>
        </div>
    </div>

    <script>
        let intervalId = null;
        let frameCount = 0;
        let tapCount = 0;
        let swipeCount = 0;
        let errorCount = 0;
        let latencies = [];
        let isRunning = false;

        // Swipe tracking
        let isRightMouseDown = false;
        let swipeStartX = 0;
        let swipeStartY = 0;
        let swipePath = [];
        let swipeStartTime = 0;

        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        const testBtn = document.getElementById('testBtn');
        const screenImage = document.getElementById('screenImage');
        const placeholder = document.getElementById('placeholder');
        const statusDiv = document.getElementById('status');
        const refreshRateSelect = document.getElementById('refreshRate');

        function updateStatus(message, type = 'info') {
            statusDiv.className = `status ${type}`;
            const icons = { info: 'ℹ️', success: '✅', error: '❌' };
            statusDiv.innerHTML = `${icons[type]} ${message}`;
        }

        function updateStats() {
            document.getElementById('frameCount').textContent = frameCount;
            document.getElementById('tapCount').textContent = tapCount;
            document.getElementById('swipeCount').textContent = swipeCount;
            document.getElementById('errorCount').textContent = errorCount;

            if (latencies.length > 0) {
                const avgLatency = Math.round(latencies.reduce((a, b) => a + b) / latencies.length);
                document.getElementById('latency').textContent = avgLatency + 'ms';
            }
        }

        async function captureScreen() {
            const startTime = Date.now();

            try {
                const response = await fetch('/screenshot');
                const data = await response.json();

                if (data.success) {
                    screenImage.src = '/screen?' + new Date().getTime();
                    screenImage.style.display = 'block';
                    placeholder.style.display = 'none';
                    frameCount++;

                    const latency = Date.now() - startTime;
                    latencies.push(latency);
                    if (latencies.length > 10) latencies.shift();

                    updateStats();
                    updateStatus(`Mirroring active - Last frame: ${latency}ms`, 'success');
                } else {
                    throw new Error(data.error);
                }
            } catch (error) {
                errorCount++;
                updateStats();
                updateStatus(`Error: ${error.message}`, 'error');
            }
        }

        startBtn.addEventListener('click', async () => {
            if (isRunning) return;

            isRunning = true;
            startBtn.disabled = true;
            stopBtn.disabled = false;
            refreshRateSelect.disabled = true;

            updateStatus('Starting mirroring... <span class="loading"></span>', 'info');

            const refreshRate = parseInt(refreshRateSelect.value);

            // Capture first frame
            await captureScreen();

            // Start interval
            intervalId = setInterval(captureScreen, refreshRate);
        });

        stopBtn.addEventListener('click', () => {
            if (!isRunning) return;

            isRunning = false;
            clearInterval(intervalId);
            intervalId = null;

            startBtn.disabled = false;
            stopBtn.disabled = true;
            refreshRateSelect.disabled = false;

            updateStatus('Mirroring stopped', 'info');
        });

        testBtn.addEventListener('click', async () => {
            updateStatus('Testing ADB connection... <span class="loading"></span>', 'info');
            testBtn.disabled = true;

            try {
                const response = await fetch('/test');
                const data = await response.json();

                if (data.success) {
                    updateStatus(`✅ Connection successful! Device: ${data.device}`, 'success');
                } else {
                    updateStatus(`❌ Connection failed: ${data.error}`, 'error');
                }
            } catch (error) {
                updateStatus(`❌ Cannot connect to backend: ${error.message}`, 'error');
            } finally {
                testBtn.disabled = false;
            }
        });

        screenImage.addEventListener('click', async (e) => {
            // Prevent if right mouse button was used for swipe
            if (e.button !== 0) return;

            const rect = screenImage.getBoundingClientRect();
            const scaleX = screenImage.naturalWidth / rect.width;
            const scaleY = screenImage.naturalHeight / rect.height;

            const x = Math.round((e.clientX - rect.left) * scaleX);
            const y = Math.round((e.clientY - rect.top) * scaleY);

            try {
                const response = await fetch('/tap', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ x, y })
                });

                const data = await response.json();

                if (data.success) {
                    tapCount++;
                    updateStats();

                    // Visual feedback
                    const ripple = document.createElement('div');
                    ripple.style.cssText = `
                        position: absolute;
                        left: ${e.clientX - rect.left}px;
                        top: ${e.clientY - rect.top}px;
                        width: 40px;
                        height: 40px;
                        margin-left: -20px;
                        margin-top: -20px;
                        border: 2px solid #667eea;
                        border-radius: 50%;
                        pointer-events: none;
                        animation: ripple 0.6s ease-out;
                    `;
                    screenImage.parentElement.appendChild(ripple);
                    setTimeout(() => ripple.remove(), 600);
                } else {
                    throw new Error(data.error);
                }
            } catch (error) {
                errorCount++;
                updateStats();
                updateStatus(`Tap failed: ${error.message}`, 'error');
            }
        });

        // Right-click swipe functionality
        screenImage.addEventListener('mousedown', (e) => {
            if (e.button === 2) { // Right mouse button
                e.preventDefault();
                isRightMouseDown = true;

                const rect = screenImage.getBoundingClientRect();
                swipeStartX = e.clientX - rect.left;
                swipeStartY = e.clientY - rect.top;
                swipeStartTime = Date.now();
                swipePath = [{ x: swipeStartX, y: swipeStartY }];

                // Draw starting point
                drawSwipePoint(swipeStartX, swipeStartY);
                updateStatus('🖱️ Recording swipe... Release right button to execute', 'info');
            }
        });

        screenImage.addEventListener('mousemove', (e) => {
            if (isRightMouseDown) {
                const rect = screenImage.getBoundingClientRect();
                const currentX = e.clientX - rect.left;
                const currentY = e.clientY - rect.top;

                swipePath.push({ x: currentX, y: currentY });

                // Draw swipe line
                drawSwipeLine(swipePath[swipePath.length - 2], swipePath[swipePath.length - 1]);
            }
        });

        screenImage.addEventListener('mouseup', async (e) => {
            if (e.button === 2 && isRightMouseDown) {
                e.preventDefault();
                isRightMouseDown = false;

                const rect = screenImage.getBoundingClientRect();
                const scaleX = screenImage.naturalWidth / rect.width;
                const scaleY = screenImage.naturalHeight / rect.height;

                const endX = e.clientX - rect.left;
                const endY = e.clientY - rect.top;

                // Convert to device coordinates
                const x1 = Math.round(swipeStartX * scaleX);
                const y1 = Math.round(swipeStartY * scaleY);
                const x2 = Math.round(endX * scaleX);
                const y2 = Math.round(endY * scaleY);

                // Calculate swipe duration based on mouse movement time
                const duration = Math.min(Math.max(Date.now() - swipeStartTime, 100), 1000);

                try {
                    const response = await fetch('/swipe', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ x1, y1, x2, y2, duration })
                    });

                    const data = await response.json();

                    if (data.success) {
                        swipeCount++;
                        updateStats();
                        updateStatus(`✅ Swipe executed: (${x1},${y1}) → (${x2},${y2}) in ${duration}ms`, 'success');
                    } else {
                        throw new Error(data.error);
                    }
                } catch (error) {
                    errorCount++;
                    updateStats();
                    updateStatus(`Swipe failed: ${error.message}`, 'error');
                }

                // Clear swipe visualization after a moment
                setTimeout(clearSwipeVisualization, 800);
            }
        });

        // Prevent context menu on right-click
        screenImage.addEventListener('contextmenu', (e) => {
            e.preventDefault();
        });

        function drawSwipePoint(x, y) {
            const point = document.createElement('div');
            point.className = 'swipe-point';
            point.style.cssText = `
                position: absolute;
                left: ${x}px;
                top: ${y}px;
                width: 12px;
                height: 12px;
                margin-left: -6px;
                margin-top: -6px;
                background: #28a745;
                border: 2px solid white;
                border-radius: 50%;
                pointer-events: none;
                z-index: 1000;
                box-shadow: 0 2px 8px rgba(40, 167, 69, 0.5);
            `;
            screenImage.parentElement.appendChild(point);
        }

        function drawSwipeLine(from, to) {
            const line = document.createElement('div');
            line.className = 'swipe-line';

            const length = Math.sqrt(Math.pow(to.x - from.x, 2) + Math.pow(to.y - from.y, 2));
            const angle = Math.atan2(to.y - from.y, to.x - from.x) * 180 / Math.PI;

            line.style.cssText = `
                position: absolute;
                left: ${from.x}px;
                top: ${from.y}px;
                width: ${length}px;
                height: 3px;
                background: linear-gradient(to right, #28a745, #20c997);
                transform-origin: 0 0;
                transform: rotate(${angle}deg);
                pointer-events: none;
                z-index: 999;
                box-shadow: 0 1px 4px rgba(40, 167, 69, 0.4);
            `;
            screenImage.parentElement.appendChild(line);
        }

        function clearSwipeVisualization() {
            const swipeElements = screenImage.parentElement.querySelectorAll('.swipe-point, .swipe-line');
            swipeElements.forEach(el => {
                el.style.transition = 'opacity 0.3s';
                el.style.opacity = '0';
                setTimeout(() => el.remove(), 300);
            });
        }

        // Add ripple animation
        const style = document.createElement('style');
        style.textContent = `
            @keyframes ripple {
                to {
                    transform: scale(2);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    </script>
</body>
</html>
    """
    return render_template_string(html)

@app.route('/test')
def test_connection():
    """Test ADB connection"""
    success, output, error = run_adb_command("adb devices")

    if success and output:
        lines = output.strip().split('\n')
        if len(lines) > 1:
            device = lines[1].split('\t')[0] if '\t' in lines[1] else "Unknown"
            return jsonify({"success": True, "device": device})

    return jsonify({"success": False, "error": error or "No devices found"})

@app.route('/screenshot')
def screenshot():
    """Capture and return screenshot status"""
    success, result = capture_screenshot()

    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": result})

@app.route('/screen')
def get_screen():
    """Serve the screenshot image"""
    if os.path.exists(LOCAL_SCREENSHOT):
        return send_file(LOCAL_SCREENSHOT, mimetype='image/png')
    else:
        return jsonify({"error": "No screenshot available"}), 404

@app.route('/tap', methods=['POST'])
def tap():
    """Handle tap command"""
    data = request.json
    x = data.get('x')
    y = data.get('y')

    if x is None or y is None:
        return jsonify({"success": False, "error": "Missing x or y coordinate"})

    success, error = send_tap(x, y)

    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": error})

@app.route('/swipe', methods=['POST'])
def swipe():
    """Handle swipe command"""
    data = request.json
    x1 = data.get('x1')
    y1 = data.get('y1')
    x2 = data.get('x2')
    y2 = data.get('y2')
    duration = data.get('duration', 300)  # Default 300ms swipe duration

    if None in [x1, y1, x2, y2]:
        return jsonify({"success": False, "error": "Missing coordinates"})

    # ADB swipe command: adb shell input swipe x1 y1 x2 y2 duration
    success, _, error = run_adb_command(f"adb shell input swipe {x1} {y1} {x2} {y2} {duration}")

    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": error})

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 ADB Screen Mirror & Control Server")
    print("=" * 60)
    print("\n✅ Server starting...")
    print("📱 Make sure your Android device is connected via USB")
    print("🔌 Make sure USB debugging is enabled")
    print("\n🌐 Open your browser and go to:")
    print("   http://localhost:5000")
    print("\n⏹  Press Ctrl+C to stop the server")
    print("=" * 60)
    print()

    app.run(host='0.0.0.0', port=5000, debug=False)
