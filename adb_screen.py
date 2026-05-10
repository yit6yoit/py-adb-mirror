"""
1.1.0
ADB Screen Mirror & Control - Python Backend Server
This script runs a local web server that executes ADB commands and serves a web interface.

Requirements:
    pip install flask flask-cors pillow

Usage:
    1. Make sure ADB is installed and your device is connected
    2. Run: python adb_server.py
    3. Open your browser to: http://localhost:5000

Speed notes:
    - Uses `adb exec-out screencap -p` to stream screenshot bytes directly
      without writing a temp file on the device first (saves ~200-300ms).
    - Optional JPEG re-encoding on the server side reduces transfer size
      significantly (PNG from a 1080p screen can be 1-3 MB; JPEG at q=60
      is typically 80-200 KB), which cuts the pull time noticeably on USB2.
    - The frontend uses a tight async loop (no setInterval drift) so the
      next request fires the moment the previous frame is fully rendered.
"""

from flask import Flask, send_file, jsonify, request, render_template_string
from flask_cors import CORS
import subprocess
import io
import os
from PIL import Image

app = Flask(__name__)
CORS(app)

# ── Configuration ────────────────────────────────────────────────────────────
# JPEG quality for the optional re-encode path (1-95).  Lower = faster transfer
# but more compression artefacts.  80 is a good balance; drop to 60 for speed.
JPEG_QUALITY = 75

# If True the server always re-encodes to JPEG before sending.
# The client can also request JPEG via ?fmt=jpeg query param.
SERVER_DEFAULT_JPEG = False
# ─────────────────────────────────────────────────────────────────────────────


def run_adb_command(command: str, timeout: int = 10):
    """Execute an ADB command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def capture_screenshot(use_jpeg: bool = False):
    """
    Capture a screenshot using the fastest available method.

    Priority:
      1. `adb exec-out screencap -p`  – streams PNG bytes directly, no temp
         file written on the device.  Available on Android 5+ / ADB 1.0.32+.
      2. Fallback to the original write-pull-delete approach if exec-out fails.

    Returns (True, bytes) or (False, error_string).
    """
    # ── Fast path: exec-out (no temp file) ──────────────────────────────────
    try:
        result = subprocess.run(
            "adb exec-out screencap -p",
            shell=True,
            capture_output=True,
            timeout=12,
        )
        if result.returncode == 0 and result.stdout:
            img_bytes = result.stdout
            if use_jpeg:
                img_bytes = _png_to_jpeg(img_bytes)
            return True, img_bytes
    except subprocess.TimeoutExpired:
        return False, "exec-out timed out"
    except Exception as e:
        pass  # fall through to the slower path

    # ── Slow path: write to /data/local/tmp then pull ────────────────────────
    SCREENSHOT_PATH = "/data/local/tmp/screen.png"
    LOCAL_SCREENSHOT = "screen_tmp.png"

    success, _, error = run_adb_command(f"adb shell screencap -p {SCREENSHOT_PATH}")
    if not success:
        return False, f"Failed to capture screenshot: {error}"

    try:
        result = subprocess.run(
            f"adb pull {SCREENSHOT_PATH} -",
            shell=True,
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            run_adb_command(f"adb shell rm {SCREENSHOT_PATH}")
            img_bytes = result.stdout
            if use_jpeg:
                img_bytes = _png_to_jpeg(img_bytes)
            return True, img_bytes
    except subprocess.TimeoutExpired:
        return False, "Pull timed out"

    # Last resort: pull to disk
    success, _, error = run_adb_command(f"adb pull {SCREENSHOT_PATH} {LOCAL_SCREENSHOT}")
    if not success:
        return False, f"Failed to pull screenshot: {error}"

    run_adb_command(f"adb shell rm {SCREENSHOT_PATH}")
    with open(LOCAL_SCREENSHOT, "rb") as f:
        img_bytes = f.read()
    os.remove(LOCAL_SCREENSHOT)

    if use_jpeg:
        img_bytes = _png_to_jpeg(img_bytes)
    return True, img_bytes


def _png_to_jpeg(png_bytes: bytes) -> bytes:
    """Re-encode raw PNG bytes to JPEG for smaller payload."""
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=False)
        return buf.getvalue()
    except Exception:
        return png_bytes  # fall back to original if conversion fails


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/test')
def test_connection():
    success, output, error = run_adb_command("adb devices")
    if success and output:
        lines = output.strip().split('\n')
        if len(lines) > 1:
            device = lines[1].split('\t')[0] if '\t' in lines[1] else "Unknown"
            return jsonify({"success": True, "device": device})
    return jsonify({"success": False, "error": error or "No devices found"})


@app.route('/screenshot')
def screenshot():
    """
    Capture and return screenshot.
    Query params:
        fmt=jpeg   → server re-encodes to JPEG before sending
        fmt=png    → always PNG (default)
    """
    fmt = request.args.get('fmt', 'jpeg' if SERVER_DEFAULT_JPEG else 'png')
    use_jpeg = fmt.lower() == 'jpeg'
    success, result = capture_screenshot(use_jpeg=use_jpeg)
    if success:
        mime = 'image/jpeg' if use_jpeg else 'image/png'
        return send_file(io.BytesIO(result), mimetype=mime)
    return jsonify({"success": False, "error": result}), 500


@app.route('/screen')
def get_screen():
    return screenshot()


@app.route('/tap', methods=['POST'])
def tap():
    data = request.json
    x, y = data.get('x'), data.get('y')
    if x is None or y is None:
        return jsonify({"success": False, "error": "Missing x or y coordinate"})
    success, _, error = run_adb_command(f"adb shell input tap {x} {y}")
    return jsonify({"success": success, "error": error if not success else None})


@app.route('/swipe', methods=['POST'])
def swipe():
    data = request.json
    x1, y1, x2, y2 = data.get('x1'), data.get('y1'), data.get('x2'), data.get('y2')
    duration = data.get('duration', 300)
    if None in [x1, y1, x2, y2]:
        return jsonify({"success": False, "error": "Missing coordinates"})
    success, _, error = run_adb_command(
        f"adb shell input swipe {x1} {y1} {x2} {y2} {duration}"
    )
    return jsonify({"success": success, "error": error if not success else None})


@app.route('/key', methods=['POST'])
def send_key():
    data = request.json
    key = data.get('key')
    if key is None:
        return jsonify({"success": False, "error": "Missing key"})
    success, _, error = run_adb_command(f"adb shell input keyevent {key}")
    return jsonify({"success": success, "error": error if not success else None})


@app.route('/adb', methods=['POST'])
def adb_command():
    """
    Execute an arbitrary ADB command from the web UI.

    Body JSON:
        { "command": "devices" }          → runs: adb devices
        { "command": "shell getprop ro.build.version.release" }
                                           → runs: adb shell getprop ...

    The 'adb' prefix is added automatically if it isn't already present.
    """
    data = request.json or {}
    cmd = (data.get('command') or '').strip()
    if not cmd:
        return jsonify({"success": False, "error": "No command provided"})

    # Safety: block obviously dangerous host-side commands
    if any(bad in cmd for bad in [';', '&&', '||', '`', '$(']):
        return jsonify({"success": False,
                        "error": "Shell metacharacters not allowed. "
                                 "Send one ADB command at a time."})

    if not cmd.startswith('adb '):
        cmd = 'adb ' + cmd

    success, stdout, stderr = run_adb_command(cmd, timeout=30)
    return jsonify({
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "command": cmd,
    })


@app.route('/adb/shell', methods=['POST'])
def adb_shell_command():
    """
    Execute a command inside `adb shell`.

    Body JSON:
        { "command": "getprop ro.product.model" }
        → runs: adb shell getprop ro.product.model
    """
    data = request.json or {}
    cmd = (data.get('command') or '').strip()
    if not cmd:
        return jsonify({"success": False, "error": "No command provided"})

    if any(bad in cmd for bad in ['`', '$(']):
        return jsonify({"success": False,
                        "error": "Backtick/subshell not allowed."})

    full_cmd = f'adb shell {cmd}'
    success, stdout, stderr = run_adb_command(full_cmd, timeout=30)
    return jsonify({
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "command": full_cmd,
    })


# ── HTML ─────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADB Screen Mirror & Control (1.1.0)</title>
    <style>
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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
            max-width: 1300px;
            width: 100%;
        }

        h1 { color: #333; margin-bottom: 6px; font-size: 26px; }
        .subtitle { color: #666; margin-bottom: 24px; font-size: 13px; }

        /* ── Controls bar ── */
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 20px;
            align-items: flex-end;
        }
        .control-group { display: flex; flex-direction: column; gap: 6px; }
        label { font-weight: 600; color: #444; font-size: 13px; }
        select, input[type=number] {
            padding: 10px 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 13px;
            transition: border-color .2s;
        }
        select:focus, input:focus { outline: none; border-color: #667eea; }

        button {
            padding: 10px 18px;
            border: none; border-radius: 8px;
            font-size: 13px; font-weight: 600;
            cursor: pointer; transition: all .2s;
            white-space: nowrap;
        }
        .btn-primary  { background: #667eea; color: white; }
        .btn-primary:hover:not(:disabled)  { background: #5568d3; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(102,126,234,.4); }
        .btn-danger   { background: #dc3545; color: white; }
        .btn-danger:hover:not(:disabled)   { background: #c82333; transform: translateY(-1px); }
        .btn-success  { background: #28a745; color: white; }
        .btn-success:hover:not(:disabled)  { background: #218838; transform: translateY(-1px); }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover:not(:disabled){ background: #5a6268; transform: translateY(-1px); }
        button:disabled { opacity: .45; cursor: not-allowed; }

        /* ── Status ── */
        .status {
            padding: 12px 16px; border-radius: 8px;
            margin-bottom: 16px; font-weight: 500; font-size: 14px;
        }
        .status.info    { background:#cfe2ff; color:#084298; border:1px solid #b6d4fe; }
        .status.success { background:#d1e7dd; color:#0f5132; border:1px solid #badbcc; }
        .status.error   { background:#f8d7da; color:#842029; border:1px solid #f5c2c7; }

        /* ── Main layout: screen left, terminal right ── */
        .main-layout {
            display: grid;
            grid-template-columns: 1fr 420px;
            gap: 20px;
            align-items: start;
        }
        @media (max-width: 900px) { .main-layout { grid-template-columns: 1fr; } }

        /* ── Screen ── */
        .screen-container {
            background: #000; border-radius: 12px; overflow: hidden;
            position: relative;
            box-shadow: 0 10px 30px rgba(0,0,0,.3);
            display: flex; justify-content: center; align-items: center;
            min-height: 340px;
        }
        #screenImage { max-width: 100%; height: auto; display: none; cursor: crosshair; }
        .screen-placeholder {
            padding: 80px 20px; text-align: center; color: #666;
        }
        .screen-placeholder svg { width: 80px; height: 80px; margin-bottom: 16px; opacity: .3; }

        /* ── Terminal panel ── */
        .terminal-panel {
            display: flex; flex-direction: column; gap: 12px;
        }
        .terminal-section {
            border: 2px solid #e0e0e0; border-radius: 12px; overflow: hidden;
        }
        .terminal-header {
            background: #2d2d2d; color: #eee;
            padding: 10px 14px; font-size: 13px; font-weight: 600;
            display: flex; justify-content: space-between; align-items: center;
        }
        .terminal-header span { opacity: .6; font-size: 11px; font-weight: 400; }
        .terminal-input-row {
            display: flex; gap: 0;
        }
        .cmd-prefix {
            background: #f0f0f0; color: #555;
            padding: 10px 12px; font-family: monospace; font-size: 13px;
            border-right: 1px solid #ddd; white-space: nowrap;
            display: flex; align-items: center;
        }
        .terminal-input-row input[type=text] {
            flex: 1; border: none; border-radius: 0;
            padding: 10px 12px; font-family: monospace; font-size: 13px;
            border-bottom: none;
        }
        .terminal-input-row input[type=text]:focus { outline: none; background: #fafff0; }
        .terminal-input-row button { border-radius: 0; padding: 10px 14px; }
        .terminal-output {
            background: #1a1a2e; color: #a8ff78;
            font-family: monospace; font-size: 12px;
            padding: 10px 12px; min-height: 90px; max-height: 220px;
            overflow-y: auto; white-space: pre-wrap; word-break: break-all;
        }
        .terminal-output .cmd-echo  { color: #7ec8e3; }
        .terminal-output .err-line  { color: #ff6b6b; }
        .terminal-output .ok-line   { color: #a8ff78; }
        .terminal-output .meta-line { color: #888; font-style: italic; }

        /* ── Stats ── */
        .stats {
            display: flex; flex-wrap: wrap; gap: 10px;
            margin-top: 16px; padding: 16px;
            background: #f8f9fa; border-radius: 8px;
            justify-content: space-around;
        }
        .stat-item { text-align: center; }
        .stat-value { font-size: 22px; font-weight: 700; color: #667eea; }
        .stat-label { font-size: 11px; color: #666; margin-top: 3px; }

        .loading {
            display: inline-block; width: 16px; height: 16px;
            border: 2px solid rgba(102,126,234,.3); border-radius: 50%;
            border-top-color: #667eea; animation: spin 1s linear infinite;
            vertical-align: middle; margin-left: 6px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes ripple { to { transform: scale(2); opacity: 0; } }
    </style>
</head>
<body>
<div class="container">
    <h1>ADB Screen Mirror &amp; Control <small style="font-size:14px;color:#999">1.1.0</small></h1>
    <p class="subtitle">Control your Android device · Python backend running</p>

    <div id="status" class="status info">Ready. Click "Start Mirroring" to begin.</div>

    <!-- Controls -->
    <div class="controls">
        <div class="control-group">
            <label for="refreshRate">Interval (ms)</label>
            <select id="refreshRate">
                <option value="200">200ms (5 FPS)</option>
                <option value="350">350ms (3 FPS)</option>
                <option value="500" selected>500ms (2 FPS)</option>
                <option value="750">750ms (1.3 FPS)</option>
                <option value="1000">1000ms (1 FPS)</option>
                <option value="1500">1500ms</option>
            </select>
        </div>
        <div class="control-group">
            <label for="imgFormat">Image format</label>
            <select id="imgFormat">
                <option value="jpeg" selected>JPEG (faster)</option>
                <option value="png">PNG (lossless)</option>
            </select>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button id="startBtn" class="btn-primary">▶ Start Mirroring</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button id="stopBtn" class="btn-danger" disabled>⏹ Stop</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button id="testBtn" class="btn-secondary">🔍 Test ADB</button>
        </div>
        <!-- Hardware buttons -->
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('3')">🏠</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('4')">🔙</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('187')">📑</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('24')">🔊</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('25')">🔉</button>
        </div>
        <div class="control-group" style="justify-content:flex-end">
            <button class="btn-primary" onclick="sendKey('26')">⏻</button>
        </div>
    </div>

    <!-- Main layout -->
    <div class="main-layout">
        <!-- Screen -->
        <div>
            <div class="screen-container">
                <div id="placeholder" class="screen-placeholder">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
                        <line x1="12" y1="18" x2="12.01" y2="18"></line>
                    </svg>
                    <p>Screen will appear here</p>
                </div>
                <img id="screenImage" alt="Android Screen">
            </div>
            <div class="stats">
                <div class="stat-item"><div class="stat-value" id="frameCount">0</div><div class="stat-label">Frames</div></div>
                <div class="stat-item"><div class="stat-value" id="tapCount">0</div><div class="stat-label">Taps</div></div>
                <div class="stat-item"><div class="stat-value" id="swipeCount">0</div><div class="stat-label">Swipes</div></div>
                <div class="stat-item"><div class="stat-value" id="errorCount">0</div><div class="stat-label">Errors</div></div>
                <div class="stat-item"><div class="stat-value" id="latency">–</div><div class="stat-label">Avg Latency</div></div>
                <div class="stat-item"><div class="stat-value" id="fps">–</div><div class="stat-label">Real FPS</div></div>
            </div>
        </div>

        <!-- Terminal panel -->
        <div class="terminal-panel">

            <!-- ADB command -->
            <div class="terminal-section">
                <div class="terminal-header">
                    ADB Command
                    <span>runs: adb &lt;your command&gt;</span>
                </div>
                <div class="terminal-input-row">
                    <div class="cmd-prefix">adb&nbsp;</div>
                    <input type="text" id="adbInput" placeholder="devices / install app.apk / …" />
                    <button class="btn-primary" onclick="runAdb()">Run</button>
                </div>
                <div class="terminal-output" id="adbOutput"><span class="meta-line">Output will appear here…</span></div>
            </div>

            <!-- ADB Shell command -->
            <div class="terminal-section">
                <div class="terminal-header">
                    ADB Shell
                    <span>runs: adb shell &lt;your command&gt;</span>
                </div>
                <div class="terminal-input-row">
                    <div class="cmd-prefix">adb shell&nbsp;</div>
                    <input type="text" id="shellInput" placeholder="getprop / pm list packages / …" />
                    <button class="btn-success" onclick="runShell()">Run</button>
                </div>
                <div class="terminal-output" id="shellOutput"><span class="meta-line">Output will appear here…</span></div>
            </div>

            <!-- History -->
            <div class="terminal-section">
                <div class="terminal-header">
                    Command History
                    <button class="btn-secondary" style="padding:4px 8px;font-size:11px" onclick="clearHistory()">Clear</button>
                </div>
                <div class="terminal-output" id="historyOutput" style="max-height:160px"><span class="meta-line">No commands yet.</span></div>
            </div>
        </div>
    </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
let isRunning = false;
let loopActive = false;
let frameCount = 0, tapCount = 0, swipeCount = 0, errorCount = 0;
let latencies = [];
let fpsTimes = [];
let isRightMouseDown = false, swipeStartX = 0, swipeStartY = 0, swipePath = [], swipeStartTime = 0;
let cmdHistory = [];

const startBtn  = document.getElementById('startBtn');
const stopBtn   = document.getElementById('stopBtn');
const testBtn   = document.getElementById('testBtn');
const screenImg = document.getElementById('screenImage');
const placeholder = document.getElementById('placeholder');
const statusDiv = document.getElementById('status');
const refreshSel = document.getElementById('refreshRate');
const fmtSel    = document.getElementById('imgFormat');

// ── Helpers ──────────────────────────────────────────────────────────────────
function updateStatus(msg, type = 'info') {
    statusDiv.className = 'status ' + type;
    const icons = { info:'ℹ️', success:'✅', error:'❌' };
    statusDiv.innerHTML = `${icons[type] || ''} ${msg}`;
}

function updateStats() {
    document.getElementById('frameCount').textContent = frameCount;
    document.getElementById('tapCount').textContent   = tapCount;
    document.getElementById('swipeCount').textContent = swipeCount;
    document.getElementById('errorCount').textContent = errorCount;
    if (latencies.length) {
        const avg = Math.round(latencies.reduce((a,b)=>a+b) / latencies.length);
        document.getElementById('latency').textContent = avg + 'ms';
    }
    if (fpsTimes.length > 1) {
        const span = fpsTimes[fpsTimes.length-1] - fpsTimes[0];
        const fps = ((fpsTimes.length - 1) / (span / 1000)).toFixed(1);
        document.getElementById('fps').textContent = fps;
    }
}

function appendToTerminal(elId, text, cls = 'ok-line') {
    const el = document.getElementById(elId);
    const line = document.createElement('div');
    line.className = cls;
    line.textContent = text;
    // Clear placeholder if present
    const meta = el.querySelector('.meta-line');
    if (meta) meta.remove();
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

function addHistory(cmd) {
    cmdHistory.unshift(cmd);
    if (cmdHistory.length > 50) cmdHistory.pop();
    const el = document.getElementById('historyOutput');
    const meta = el.querySelector('.meta-line');
    if (meta) meta.remove();
    // Rebuild (simple)
    el.innerHTML = '';
    cmdHistory.forEach(c => {
        const d = document.createElement('div');
        d.className = 'cmd-echo';
        d.textContent = c;
        d.style.cursor = 'pointer';
        d.title = 'Click to copy';
        d.onclick = () => navigator.clipboard?.writeText(c);
        el.appendChild(d);
    });
}

function clearHistory() {
    cmdHistory = [];
    document.getElementById('historyOutput').innerHTML = '<span class="meta-line">Cleared.</span>';
}

// ── Screenshot loop ──────────────────────────────────────────────────────────
// Uses a self-rescheduling async loop instead of setInterval to avoid
// piling up requests when the device is slow.

async function captureFrame() {
    if (!loopActive) return;

    const t0 = performance.now();
    const fmt = fmtSel.value;
    const url = `/screenshot?fmt=${fmt}&_=${t0}`;

    await new Promise(resolve => {
        const img = new Image();
        img.onload = () => {
            screenImg.src = img.src;
            screenImg.style.display = 'block';
            placeholder.style.display = 'none';
            frameCount++;

            const lat = Math.round(performance.now() - t0);
            latencies.push(lat);
            if (latencies.length > 20) latencies.shift();

            fpsTimes.push(performance.now());
            if (fpsTimes.length > 30) fpsTimes.shift();

            updateStats();
            updateStatus(`Mirroring · last frame ${lat}ms · ${fmt.toUpperCase()}`, 'success');
            resolve();
        };
        img.onerror = () => {
            errorCount++;
            updateStats();
            updateStatus('Error capturing frame', 'error');
            resolve();
        };
        img.src = url;
    });

    if (!loopActive) return;

    // Wait remaining interval time (or 0 if we were slow)
    const elapsed = performance.now() - t0;
    const interval = parseInt(refreshSel.value, 10);
    const wait = Math.max(0, interval - elapsed);

    setTimeout(captureFrame, wait);
}

startBtn.addEventListener('click', async () => {
    if (isRunning) return;
    isRunning = true; loopActive = true;
    startBtn.disabled = true; stopBtn.disabled = false; refreshSel.disabled = true;
    updateStatus('Starting…<span class="loading"></span>', 'info');
    captureFrame();
});

stopBtn.addEventListener('click', () => {
    isRunning = false; loopActive = false;
    startBtn.disabled = false; stopBtn.disabled = true; refreshSel.disabled = false;
    updateStatus('Mirroring stopped', 'info');
});

testBtn.addEventListener('click', async () => {
    updateStatus('Testing connection…<span class="loading"></span>', 'info');
    testBtn.disabled = true;
    try {
        const r = await fetch('/test');
        const d = await r.json();
        if (d.success) updateStatus(`Connected · Device: ${d.device}`, 'success');
        else updateStatus(`Connection failed: ${d.error}`, 'error');
    } catch(e) {
        updateStatus(`Backend unreachable: ${e.message}`, 'error');
    } finally { testBtn.disabled = false; }
});

// ── ADB Terminal ─────────────────────────────────────────────────────────────
async function runAdb() {
    const input = document.getElementById('adbInput');
    const cmd = input.value.trim();
    if (!cmd) return;

    appendToTerminal('adbOutput', '$ adb ' + cmd, 'cmd-echo');
    addHistory('adb ' + cmd);
    input.value = '';

    try {
        const r = await fetch('/adb', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({command: cmd})
        });
        const d = await r.json();
        if (d.stdout) appendToTerminal('adbOutput', d.stdout.trimEnd(), 'ok-line');
        if (d.stderr) appendToTerminal('adbOutput', d.stderr.trimEnd(), 'err-line');
        if (!d.stdout && !d.stderr) appendToTerminal('adbOutput', d.success ? '(no output)' : d.error, d.success ? 'meta-line' : 'err-line');
    } catch(e) {
        appendToTerminal('adbOutput', 'Request failed: ' + e.message, 'err-line');
    }
}

async function runShell() {
    const input = document.getElementById('shellInput');
    const cmd = input.value.trim();
    if (!cmd) return;

    appendToTerminal('shellOutput', '$ adb shell ' + cmd, 'cmd-echo');
    addHistory('adb shell ' + cmd);
    input.value = '';

    try {
        const r = await fetch('/adb/shell', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({command: cmd})
        });
        const d = await r.json();
        if (d.stdout) appendToTerminal('shellOutput', d.stdout.trimEnd(), 'ok-line');
        if (d.stderr) appendToTerminal('shellOutput', d.stderr.trimEnd(), 'err-line');
        if (!d.stdout && !d.stderr) appendToTerminal('shellOutput', d.success ? '(no output)' : d.error, d.success ? 'meta-line' : 'err-line');
    } catch(e) {
        appendToTerminal('shellOutput', 'Request failed: ' + e.message, 'err-line');
    }
}

// Enter key support for terminals
document.getElementById('adbInput').addEventListener('keydown', e => { if (e.key==='Enter') runAdb(); });
document.getElementById('shellInput').addEventListener('keydown', e => { if (e.key==='Enter') runShell(); });

// ── Send key ─────────────────────────────────────────────────────────────────
async function sendKey(keycode) {
    try {
        const r = await fetch('/key', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({key: keycode})
        });
        const d = await r.json();
        if (!d.success) updateStatus('Key failed: ' + d.error, 'error');
        else updateStatus('Key sent (code ' + keycode + ')', 'success');
    } catch(e) { updateStatus('Error: ' + e.message, 'error'); }
}

// ── Tap ──────────────────────────────────────────────────────────────────────
screenImg.addEventListener('click', async e => {
    if (e.button !== 0) return;
    const rect = screenImg.getBoundingClientRect();
    const sx = screenImg.naturalWidth / rect.width;
    const sy = screenImg.naturalHeight / rect.height;
    const x = Math.round((e.clientX - rect.left) * sx);
    const y = Math.round((e.clientY - rect.top) * sy);
    try {
        const r = await fetch('/tap', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({x,y})});
        const d = await r.json();
        if (d.success) {
            tapCount++; updateStats();
            const ripple = document.createElement('div');
            ripple.style.cssText = `position:absolute;left:${e.clientX-rect.left}px;top:${e.clientY-rect.top}px;width:40px;height:40px;margin:-20px 0 0 -20px;border:2px solid #667eea;border-radius:50%;pointer-events:none;animation:ripple .6s ease-out`;
            screenImg.parentElement.appendChild(ripple);
            setTimeout(() => ripple.remove(), 600);
        } else { errorCount++; updateStats(); updateStatus('Tap failed: ' + d.error, 'error'); }
    } catch(e) { errorCount++; updateStats(); }
});

// ── Swipe ────────────────────────────────────────────────────────────────────
screenImg.addEventListener('mousedown', e => {
    if (e.button !== 2) return;
    e.preventDefault(); isRightMouseDown = true;
    const rect = screenImg.getBoundingClientRect();
    swipeStartX = e.clientX - rect.left; swipeStartY = e.clientY - rect.top;
    swipeStartTime = Date.now(); swipePath = [{x:swipeStartX, y:swipeStartY}];
    drawSwipePoint(swipeStartX, swipeStartY);
    updateStatus('🖱️ Recording swipe…', 'info');
});

screenImg.addEventListener('mousemove', e => {
    if (!isRightMouseDown) return;
    const rect = screenImg.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    if (swipePath.length) drawSwipeLine(swipePath[swipePath.length-1], {x:cx, y:cy});
    swipePath.push({x:cx, y:cy});
});

screenImg.addEventListener('mouseup', async e => {
    if (e.button !== 2 || !isRightMouseDown) return;
    e.preventDefault(); isRightMouseDown = false;
    const rect = screenImg.getBoundingClientRect();
    const sx = screenImg.naturalWidth / rect.width;
    const sy = screenImg.naturalHeight / rect.height;
    const x1 = Math.round(swipeStartX * sx), y1 = Math.round(swipeStartY * sy);
    const x2 = Math.round((e.clientX - rect.left) * sx), y2 = Math.round((e.clientY - rect.top) * sy);
    const duration = Math.min(Math.max(Date.now() - swipeStartTime, 100), 1000);
    try {
        const r = await fetch('/swipe', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({x1,y1,x2,y2,duration})});
        const d = await r.json();
        if (d.success) { swipeCount++; updateStats(); updateStatus(`Swipe (${x1},${y1})→(${x2},${y2}) ${duration}ms`, 'success'); }
        else { errorCount++; updateStats(); updateStatus('Swipe failed: ' + d.error, 'error'); }
    } catch(e) { errorCount++; updateStats(); }
    setTimeout(clearSwipeViz, 800);
});

screenImg.addEventListener('contextmenu', e => e.preventDefault());

function drawSwipePoint(x, y) {
    const p = document.createElement('div');
    p.className = 'swipe-point';
    p.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:12px;height:12px;margin:-6px 0 0 -6px;background:#28a745;border:2px solid white;border-radius:50%;pointer-events:none;z-index:1000`;
    screenImg.parentElement.appendChild(p);
}
function drawSwipeLine(from, to) {
    const len = Math.hypot(to.x-from.x, to.y-from.y);
    const ang = Math.atan2(to.y-from.y, to.x-from.x) * 180/Math.PI;
    const l = document.createElement('div');
    l.className = 'swipe-line';
    l.style.cssText = `position:absolute;left:${from.x}px;top:${from.y}px;width:${len}px;height:3px;background:linear-gradient(to right,#28a745,#20c997);transform-origin:0 0;transform:rotate(${ang}deg);pointer-events:none;z-index:999`;
    screenImg.parentElement.appendChild(l);
}
function clearSwipeViz() {
    screenImg.parentElement.querySelectorAll('.swipe-point,.swipe-line').forEach(el => {
        el.style.transition = 'opacity .3s'; el.style.opacity = '0';
        setTimeout(() => el.remove(), 300);
    });
}
</script>
</body>
</html>"""


if __name__ == '__main__':
    print("=" * 60)
    print("🚀  ADB Screen Mirror & Control  v1.1.0")
    print("=" * 60)
    print("\n✅  Server starting…")
    print("📱  Make sure your Android device is connected via USB")
    print("🔌  USB debugging must be enabled on the device")
    print("\n🌐  Open: http://localhost:5000")
    print("\n⏹   Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
