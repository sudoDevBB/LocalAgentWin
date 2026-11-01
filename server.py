from __future__ import annotations

import json
import array
import hashlib
import math
import os
import queue
import re
import secrets
import sqlite3
import socket
import struct
import subprocess
import sys
import threading
import time
import wave
try:
    import winsound
except ImportError:  # lets the interface preview run on non-Windows development machines
    winsound = None
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_sock import Sock
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TUNES = DATA / "tunes"
DB = DATA / "soundroom.db"
CONFIG = DATA / "config.json"
ALLOWED_TUNE_EXTENSIONS = {"wav"}
DEFAULT_PIN = "223344"
CONFIG_VERSION = 2
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

DATA.mkdir(exist_ok=True)
TUNES.mkdir(exist_ok=True)
if not CONFIG.exists():
    CONFIG.write_text(json.dumps({"pin": DEFAULT_PIN, "secret": secrets.token_hex(32), "version": CONFIG_VERSION}, indent=2))
config = json.loads(CONFIG.read_text())
if config.get("version", 0) < CONFIG_VERSION:
    config["pin"] = DEFAULT_PIN
    config["version"] = CONFIG_VERSION
    config.setdefault("secret", secrets.token_hex(32))
    CONFIG.write_text(json.dumps(config, indent=2))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.secret_key = config["secret"]
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
sock = Sock(app)
scheduler = BackgroundScheduler(daemon=True)
audio_lock = threading.Lock()
bell_state_lock = threading.Lock()
player_lock = threading.RLock()
extension_lock = threading.Lock()
extension_pending_lock = threading.Lock()
extension_outbound = queue.Queue()
extension_pending = {}
extension_connected = threading.Event()
extension_connection_id = None
extension_ws = None
active_bell = None
active_bell_stop = None
player_process = None
player_snapshot = {"state": "idle", "video_id": None, "title": "No video selected", "available": False}


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


BUILTIN_TUNES = {
    "Orchard_Rise.wav": [660, 784, 988, 1319],
    "Kitchen_Double.wav": [523, 523, 784, 523, 523, 784],
    "Reading_Bell.wav": [740, 587, 440],
    "Hall_Triple.wav": [880, 880, 659, 880, 880, 659],
    "Bedroom_Soft.wav": [523, 659],
    "Study_Low.wav": [440, 554, 392, 554],
}
TUNE_DESCRIPTIONS = {
    "Orchard_Rise.wav": "Four rising notes",
    "Kitchen_Double.wav": "Three quick double chimes",
    "Reading_Bell.wav": "Three descending notes",
    "Hall_Triple.wav": "Two low triple chimes",
    "Bedroom_Soft.wav": "Two soft rising notes",
    "Study_Low.wav": "A low alternating phrase",
}


def create_builtin_tunes():
    """Synthesize short, distinct PCM bell patterns on first launch."""
    sample_rate = 22050
    for index, (name, notes) in enumerate(BUILTIN_TUNES.items()):
        path = TUNES / name
        if path.exists():
            continue
        frames = bytearray()
        for note_index, frequency in enumerate(notes):
            duration = 0.30 if index in {0, 2, 4} else 0.19
            count = int(sample_rate * duration)
            for sample in range(count):
                t = sample / sample_rate
                envelope = min(1.0, t / 0.012) * math.exp(-t * (3.8 if index % 2 else 3.0))
                tone = math.sin(2 * math.pi * frequency * t)
                tone += 0.32 * math.sin(2 * math.pi * frequency * 2.01 * t)
                tone += 0.10 * math.sin(2 * math.pi * frequency * 3.98 * t)
                value = max(-32767, min(32767, int(tone * envelope * 8500)))
                frames.extend(struct.pack("<h", value))
            silence = int(sample_rate * (0.16 if note_index < len(notes) - 1 else 0.34))
            frames.extend(b"\x00\x00" * silence)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)


def sound_signature(path):
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            total = audio.getnframes()
            data = audio.readframes(total)
        samples = array.array("h", data)
        if sys.byteorder != "little":
            samples.byteswap()
        if channels > 1:
            samples = array.array("h", [sum(samples[i:i + channels]) // channels for i in range(0, len(samples), channels)])
        if not samples:
            return [24, 24, 24, 24, 24, 24]
        result = []
        for index in range(6):
            start = index * len(samples) // 6
            end = max(start + 1, (index + 1) * len(samples) // 6)
            segment = samples[start:end]
            rms = math.sqrt(sum(value * value for value in segment) / len(segment))
            result.append(max(18, min(100, round(rms / 95))))
        return result
    except (OSError, wave.Error, EOFError):
        return [24, 24, 24, 24, 24, 24]


create_builtin_tunes()


def init_db():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                default_tune TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS bells (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                label TEXT NOT NULL DEFAULT '',
                fire_at TEXT NOT NULL,
                tune TEXT NOT NULL,
                duration INTEGER NOT NULL DEFAULT 10,
                enabled INTEGER NOT NULL DEFAULT 1
            );
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(rooms)")}
        if "default_tune" not in columns:
            db.execute("ALTER TABLE rooms ADD COLUMN default_tune TEXT NOT NULL DEFAULT ''")
        if db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            db.executemany("INSERT INTO rooms(name, default_tune) VALUES (?, ?)", [
                ("Orchard Room", "Orchard_Rise.wav"),
                ("Kitchen", "Kitchen_Double.wav"),
                ("Reading Room", "Reading_Bell.wav"),
            ])
        assigned = {row[0] for row in db.execute("SELECT default_tune FROM rooms WHERE default_tune<>''")}
        available = [path.name for path in sorted(TUNES.glob("*.wav")) if path.name not in assigned]
        for row, tune in zip(db.execute("SELECT id FROM rooms WHERE default_tune='' ORDER BY id").fetchall(), available):
            db.execute("UPDATE rooms SET default_tune=? WHERE id=?", (tune, row["id"]))


def manage_wake_task(mode, bell_id, fire_at=None):
    if sys.platform != "win32":
        return None
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "manage_bell_task.ps1"), "-Mode", mode, "-BellId", str(bell_id)]
    if fire_at:
        command.extend(["-FireAt", fire_at])
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return True
    except Exception as exc:
        details = getattr(exc, "stderr", "")
        print(f"Could not {mode.lower()} Windows wake task for bell {bell_id}: {exc} {details}".strip())
        return False


def show_server_alert(room_name):
    if sys.platform != "win32":
        return
    try:
        subprocess.Popen(
            [sys.executable, str(ROOT / "alert_window.py"), room_name],
            cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError as exc:
        print(f"Could not show the server room alert: {exc}")


def pycaw_endpoint():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def get_system_volume():
    comtypes = None
    try:
        import comtypes as comtypes_module
        comtypes = comtypes_module
        comtypes.CoInitialize()
        return round(pycaw_endpoint().GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return None
    finally:
        if comtypes:
            comtypes.CoUninitialize()


def get_output_name():
    comtypes = None
    try:
        import comtypes as comtypes_module
        comtypes = comtypes_module
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().FriendlyName
    except Exception:
        return "Windows default output"
    finally:
        if comtypes:
            comtypes.CoUninitialize()


def set_system_volume(percent):
    import comtypes
    percent = max(0, min(100, int(percent)))
    comtypes.CoInitialize()
    try:
        pycaw_endpoint().SetMasterVolumeLevelScalar(percent / 100, None)
        return percent
    finally:
        comtypes.CoUninitialize()


def find_chrome_executable():
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def open_chrome_on_server():
    if sys.platform != "win32":
        raise RuntimeError("The signed-in Chrome player is available on the Windows server.")
    executable = find_chrome_executable()
    if not executable:
        raise RuntimeError("Install Google Chrome on the Windows server, then open Chrome once to load the Soundroom extension.")
    subprocess.Popen([str(executable), "https://www.youtube.com"], close_fds=True)
    return {"ok": True}


def find_chrome_main_process():
    if sys.platform != "win32":
        return None
    try:
        import psutil
        for process in psutil.process_iter(["name", "cmdline"]):
            if (process.info["name"] and process.info["name"].lower() == "chrome.exe"
                    and not any(argument.startswith("--type=") for argument in (process.info["cmdline"] or []))):
                return psutil.Process(process.pid)
    except Exception:
        pass
    return None


def player_command(command, value=None, timeout=60):
    if sys.platform != "win32":
        raise RuntimeError("The signed-in Chrome player is available on the Windows server.")
    if not extension_connected.is_set():
        raise RuntimeError("Open Chrome on the server and load the Soundroom extension from the extension folder. Keep Chrome running while using Soundroom.")
    command_id = secrets.token_hex(12)
    response = queue.Queue(maxsize=1)
    with player_lock:
        with extension_pending_lock:
            extension_pending[command_id] = response
        extension_outbound.put({"type": "command", "id": command_id, "command": command, "value": value})
        try:
            result = response.get(timeout=timeout)
        except queue.Empty as exc:
            with extension_pending_lock:
                extension_pending.pop(command_id, None)
            raise RuntimeError("Chrome did not respond to Soundroom. Check that the Soundroom extension is enabled and Chrome is open on the server.") from exc
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "Chrome could not complete the Soundroom request.")
    player = result.get("result") or {}
    if isinstance(player, dict) and "state" in player:
        player_snapshot.update(player)
        player_snapshot["available"] = True
    return player


def play_server_video(video_id):
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("Enter a valid YouTube video link.")
    return player_command("play", video_id, timeout=90)


def pause_server_video():
    if not player_snapshot.get("video_id"):
        return False
    player_command("pause", timeout=10)
    return True


def server_player_status():
    if not extension_connected.is_set():
        return {"state": "idle", "video_id": None, "title": "Chrome extension offline", "available": False}
    return {**player_snapshot, "available": True}


def windows_audio_sessions():
    """Find audio sessions belonging to the server's regular Chrome process tree."""
    from pycaw.pycaw import AudioUtilities
    managed_pids = set()
    if player_process:
        try:
            import psutil
            process = psutil.Process(player_process.pid)
            managed_pids = {process.pid, *(child.pid for child in process.children(recursive=True))}
        except Exception:
            managed_pids = set()
    sessions = []
    for audio_session in AudioUtilities.GetAllSessions():
        try:
            process = audio_session.Process
            if process and process.name().lower() == "chrome.exe" and (not managed_pids or process.pid in managed_pids):
                sessions.append(audio_session)
        except Exception:
            continue
    return sessions if managed_pids else []


def duck_and_play(tune, seconds, stop_event):
    global active_bell, active_bell_stop
    comtypes = None
    initialized = False
    saved = []
    try:
        import comtypes as comtypes_module
        comtypes = comtypes_module
        comtypes.CoInitialize()
        initialized = True
        with audio_lock:
            sessions = windows_audio_sessions()
            saved = [(item, item.SimpleAudioVolume.GetMasterVolume()) for item in sessions]
            for step in range(1, 9):
                factor = 1 - (step / 8) * 0.72
                for item, original in saved:
                    item.SimpleAudioVolume.SetMasterVolume(original * factor, None)
                if stop_event.wait(0.12):
                    break
            if stop_event.is_set():
                return
            tune_path = TUNES / tune
            if winsound and tune_path.exists() and tune_path.suffix.lower() == ".wav":
                winsound.PlaySound(str(tune_path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            elif winsound:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            stop_event.wait(max(2, min(90, int(seconds))))
            if winsound:
                winsound.PlaySound(None, 0)
    finally:
        if saved:
            for step in range(1, 9):
                for item, original in saved:
                    try:
                        item.SimpleAudioVolume.SetMasterVolume(original * (0.28 + (step / 8) * 0.72), None)
                    except Exception:
                        pass
                time.sleep(0.08)
        if initialized:
            comtypes.CoUninitialize()
        with bell_state_lock:
            active_bell = None
            active_bell_stop = None


def start_bell(room_id, room_name, tune, duration, label="", bell_id=None):
    global active_bell, active_bell_stop
    with bell_state_lock:
        if active_bell:
            return False
        stop_event = threading.Event()
        active_bell_stop = stop_event
        active_bell = {
            "id": bell_id,
            "room_id": room_id,
            "room": room_name,
            "label": label,
            "duration": duration,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    show_server_alert(room_name)
    threading.Thread(target=duck_and_play, args=(tune, duration, stop_event), daemon=True).start()
    return True


def fire_bell(bell_id):
    with connect() as db:
        row = db.execute("""
            SELECT b.id, b.room_id, b.label, b.fire_at, r.default_tune AS tune,
                   b.duration, b.enabled, r.name AS room_name FROM bells b
            JOIN rooms r ON r.id=b.room_id WHERE b.id=? AND b.enabled=1
        """, (bell_id,)).fetchone()
        db.execute("UPDATE bells SET enabled=0 WHERE id=?", (bell_id,))
    if not row:
        return
    start_bell(row["room_id"], row["room_name"], row["tune"], row["duration"], row["label"], row["id"])
    manage_wake_task("Remove", bell_id)


def schedule_bell(row):
    job_id = f"bell-{row['id']}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    if not row["enabled"]:
        manage_wake_task("Remove", row["id"])
        return None
    fire_at = datetime.fromisoformat(row["fire_at"])
    if fire_at <= datetime.now():
        return None
    scheduler.add_job(fire_bell, "date", run_date=fire_at, args=[row["id"]], id=job_id, replace_existing=True)
    return manage_wake_task("Register", row["id"], fire_at.isoformat(timespec="seconds"))


def reload_schedules():
    now = datetime.now()
    with connect() as db:
        expired_ids = [row[0] for row in db.execute("SELECT id FROM bells WHERE enabled=1 AND fire_at<=?", (now.isoformat(timespec="seconds"),))]
        db.execute("UPDATE bells SET enabled=0 WHERE enabled=1 AND fire_at<=?", (now.isoformat(timespec="seconds"),))
        for row in db.execute("SELECT * FROM bells WHERE enabled=1"):
            schedule_bell(row)
    for bell_id in expired_ids:
        manage_wake_task("Remove", bell_id)


@app.before_request
def require_pin():
    if request.endpoint == "chrome_extension_bridge":
        if request.remote_addr not in {"127.0.0.1", "::1"} or not request.headers.get("Origin", "").startswith("chrome-extension://"):
            return jsonify({"error": "The Soundroom Chrome extension must connect locally."}), 403
        return None
    if request.endpoint == "scheduled_wake_bell":
        wake_key = request.headers.get("X-Soundroom-Wake-Key", "")
        return None if secrets.compare_digest(wake_key, config["secret"]) else (jsonify({"error": "Invalid wake-task key."}), 403)
    if request.endpoint in {"login", "login_post", "static"} or session.get("authenticated"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Enter the local access PIN to continue."}), 401
    return redirect(url_for("login"))


@sock.route("/internal/chrome-extension")
def chrome_extension_bridge(ws):
    global player_process, extension_connection_id, extension_ws
    connection_id = secrets.token_hex(12)
    with extension_lock:
        previous_ws = extension_ws
        extension_ws = ws
        extension_connection_id = connection_id
        extension_connected.set()
        player_snapshot["available"] = True
        player_process = find_chrome_main_process()
    if previous_ws and previous_ws is not ws:
        try:
            previous_ws.close()
        except Exception:
            pass
    try:
        ws.send(json.dumps({"type": "connected"}))
        while True:
            try:
                raw = ws.receive(timeout=0.25)
            except TimeoutError:
                raw = ""
            except Exception:
                break
            if raw is None:
                if not ws.connected:
                    break
                raw = ""
            if raw:
                try:
                    message = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    message = {}
                if message.get("type") == "status" and isinstance(message.get("player"), dict):
                    player_snapshot.update(message["player"])
                    player_snapshot["available"] = True
                elif message.get("type") == "result":
                    with extension_pending_lock:
                        response = extension_pending.pop(str(message.get("id", "")), None)
                    if response:
                        response.put({"ok": bool(message.get("ok")), "result": message.get("result"), "error": message.get("error")})
            try:
                outgoing = extension_outbound.get_nowait()
                ws.send(json.dumps(outgoing))
            except queue.Empty:
                pass
            except Exception:
                break
    finally:
        is_current = False
        with extension_lock:
            if extension_connection_id == connection_id:
                extension_connected.clear()
                extension_connection_id = None
                extension_ws = None
                player_snapshot["available"] = False
                player_process = None
                is_current = True
        if is_current:
            with extension_pending_lock:
                pending = list(extension_pending.values())
                extension_pending.clear()
            for response in pending:
                try:
                    response.put_nowait({"ok": False, "error": "Chrome disconnected from Soundroom."})
                except queue.Full:
                    pass
            while True:
                try:
                    extension_outbound.get_nowait()
                except queue.Empty:
                    break


@app.get("/login")
def login():
    return render_template("login.html", error=None)


@app.post("/login")
def login_post():
    if request.form.get("pin", "") == config["pin"]:
        session.clear()
        session["authenticated"] = True
        session.permanent = request.form.get("remember_device") == "on"
        return redirect(url_for("index"))
    return render_template("login.html", error="That PIN did not match. Use the PIN configured in Soundroom settings."), 401


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return render_template("index.html")


def local_network_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


@app.get("/api/status")
def status():
    with connect() as db:
        bells = db.execute("""
            SELECT a.id, a.room_id, a.label, a.fire_at, r.default_tune AS tune, a.duration, a.enabled, r.name AS room
            FROM bells a JOIN rooms r ON r.id=a.room_id WHERE a.enabled=1
            ORDER BY a.fire_at LIMIT 8
        """).fetchall()
        rooms = db.execute("SELECT id, name, default_tune FROM rooms ORDER BY name").fetchall()
    return jsonify({
        "volume": get_system_volume(),
        "output_name": get_output_name(),
        "rooms": [dict(row,
                       sound_pattern=sound_signature(TUNES / row["default_tune"]),
                       sound_description=TUNE_DESCRIPTIONS.get(row["default_tune"], "Custom WAV tune · preview before use")) for row in rooms],
        "bells": [dict(row) for row in bells],
        "tunes": sorted(p.name for p in TUNES.glob("*.wav")),
        "active_bell": active_bell,
        "player": server_player_status(),
        "server_url": f"http://{local_network_address()}:8765",
    })


@app.post("/api/player/play")
def player_play():
    data = request.json or {}
    video_id = str(data.get("video_id", ""))
    try:
        return jsonify(play_server_video(video_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.post("/api/player/pause")
def player_pause():
    if not pause_server_video():
        return jsonify({"error": "There is no server video playing to pause."}), 409
    return jsonify({"ok": True})


@app.post("/api/player/resume")
def player_resume():
    try:
        player_command("resume", timeout=8)
    except Exception as exc:
        return jsonify({"error": f"Could not resume the server video: {exc}"}), 409
    return jsonify({"ok": True})


@app.post("/api/player/reset")
def player_reset():
    try:
        return jsonify(player_command("reset", timeout=45))
    except Exception as exc:
        return jsonify({"error": f"Could not reset the server player: {exc}"}), 503


@app.post("/api/player/open-chrome")
def player_open_chrome():
    try:
        return jsonify(open_chrome_on_server())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.post("/api/bluetooth/settings")
def bluetooth_settings():
    if sys.platform != "win32":
        return jsonify({"error": "Bluetooth settings are available on the Windows server."}), 503
    try:
        os.startfile("ms-settings:bluetooth")
    except OSError as exc:
        return jsonify({"error": f"Windows could not open Bluetooth settings: {exc}"}), 503
    return jsonify({"ok": True})


@app.put("/api/settings/pin")
def update_pin():
    global config
    new_pin = str((request.json or {}).get("pin", ""))
    if not re.fullmatch(r"\d{6}", new_pin):
        return jsonify({"error": "Use exactly six digits for the access PIN."}), 400
    config["pin"] = new_pin
    config["secret"] = secrets.token_hex(32)
    config["version"] = CONFIG_VERSION
    temporary_config = CONFIG.with_suffix(".tmp")
    temporary_config.write_text(json.dumps(config, indent=2))
    temporary_config.replace(CONFIG)
    app.secret_key = config["secret"]
    session.clear()
    return jsonify({"ok": True, "message": "PIN changed. Sign in again with the new PIN."})


@app.post("/api/rooms/<int:room_id>/ring")
def ring_room(room_id):
    if sys.platform != "win32":
        return jsonify({"error": "Room bells play through the Windows audio output."}), 503
    try:
        duration = int((request.json or {}).get("duration", 5))
    except (TypeError, ValueError):
        return jsonify({"error": "Choose a 5 or 10 second bell."}), 400
    if duration not in {5, 10}:
        return jsonify({"error": "Choose a 5 or 10 second bell."}), 400
    with connect() as db:
        room = db.execute("SELECT id, name, default_tune FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not room or not room["default_tune"] or not (TUNES / room["default_tune"]).is_file():
        return jsonify({"error": "Assign a room sound before ringing this room."}), 400
    if not start_bell(room["id"], room["name"], room["default_tune"], duration):
        return jsonify({"error": f"{active_bell['room']} bell is already playing. Stop it before ringing another room."}), 409
    return jsonify({"ok": True, "room": room["name"], "duration": duration})


@app.post("/api/bells/stop")
def stop_bell():
    with bell_state_lock:
        if not active_bell_stop:
            return jsonify({"error": "No room bell is playing."}), 409
        active_bell_stop.set()
    return jsonify({"ok": True})


@app.post("/internal/wake-bell/<int:bell_id>")
def scheduled_wake_bell(bell_id):
    fire_bell(bell_id)
    return jsonify({"ok": True})


@app.put("/api/volume")
def volume():
    try:
        value = set_system_volume(request.json.get("volume"))
    except Exception as exc:
        return jsonify({"error": f"Windows volume control is unavailable: {exc}"}), 503
    return jsonify({"volume": value})


@app.post("/api/rooms")
def add_room():
    name = str(request.json.get("name", "")).strip()[:48]
    if not name:
        return jsonify({"error": "Enter a room name."}), 400
    with connect() as db:
        conflict = db.execute("SELECT id FROM rooms WHERE lower(name)=lower(?)", (name,)).fetchone()
        if conflict:
            return jsonify({"error": "That room already exists."}), 409
        assigned = {row[0] for row in db.execute("SELECT default_tune FROM rooms")}
    available = [tune for tune in sorted(p.name for p in TUNES.glob("*.wav")) if tune not in assigned]
    if not available:
        return jsonify({"error": "Every available bell sound is in use. Upload another distinct sound, then add this room."}), 409
    try:
        with connect() as db:
            cursor = db.execute("INSERT INTO rooms(name, default_tune) VALUES (?, ?)", (name, available[0]))
            return jsonify({"id": cursor.lastrowid, "name": name, "default_tune": available[0]}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "That room already exists."}), 409


@app.put("/api/rooms/<int:room_id>")
def update_room(room_id):
    data = request.json or {}
    name = str(data.get("name", "")).strip()[:48] if "name" in data else None
    tune = secure_filename(str(data.get("default_tune", ""))) if "default_tune" in data else None
    if name is not None and not name:
        return jsonify({"error": "Enter a room name."}), 400
    if name is not None:
        with connect() as db:
            conflict = db.execute("SELECT id FROM rooms WHERE lower(name)=lower(?) AND id<>?", (name, room_id)).fetchone()
        if conflict:
            return jsonify({"error": "That room name is already in use."}), 409
    if tune is not None and (not tune or Path(tune).suffix.lower() != ".wav" or not (TUNES / tune).is_file()):
        return jsonify({"error": "Choose one of the available WAV tunes."}), 400
    updates = []
    values = []
    if name is not None:
        updates.append("name=?")
        values.append(name)
    if tune is not None:
        updates.append("default_tune=?")
        values.append(tune)
    if not updates:
        return jsonify({"error": "Change the room name or sound."}), 400
    with connect() as db:
        if tune is not None:
            conflict = db.execute("SELECT name FROM rooms WHERE default_tune=? AND id<>?", (tune, room_id)).fetchone()
            if conflict:
                return jsonify({"error": f"That sound is already assigned to {conflict['name']}. Choose a different tune so each room remains recognizable."}), 409
        values.append(room_id)
        cursor = db.execute(f"UPDATE rooms SET {', '.join(updates)} WHERE id=?", values)
    if not cursor.rowcount:
        return jsonify({"error": "Room not found."}), 404
    return jsonify({"ok": True, "name": name, "default_tune": tune})


@app.delete("/api/rooms/<int:room_id>")
def delete_room(room_id):
    global active_bell_stop
    with connect() as db:
        room = db.execute("SELECT id, name FROM rooms WHERE id=?", (room_id,)).fetchone()
        if not room:
            return jsonify({"error": "Room not found."}), 404
        bell_ids = [row[0] for row in db.execute("SELECT id FROM bells WHERE room_id=?", (room_id,))]
        db.execute("DELETE FROM bells WHERE room_id=?", (room_id,))
        db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
    for bell_id in bell_ids:
        try:
            scheduler.remove_job(f"bell-{bell_id}")
        except Exception:
            pass
        manage_wake_task("Remove", bell_id)
    with bell_state_lock:
        if active_bell and active_bell["room_id"] == room_id and active_bell_stop:
            active_bell_stop.set()
    return jsonify({"ok": True, "removed": room["name"], "cancelled_bells": len(bell_ids)})


@app.post("/api/bells")
def add_bell():
    data = request.json or {}
    try:
        room_id = int(data["room_id"])
        fire_at = datetime.fromisoformat(data["fire_at"])
        duration = max(2, min(90, int(data.get("duration", 10))))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Choose a room, future time, and bell duration."}), 400
    if fire_at <= datetime.now():
        return jsonify({"error": "Choose a time in the future."}), 400
    with connect() as db:
        room = db.execute("SELECT id, default_tune FROM rooms WHERE id=?", (room_id,)).fetchone()
        if not room:
            return jsonify({"error": "Choose an available room."}), 400
        tune = room["default_tune"]
        if not tune or not (TUNES / tune).is_file():
            return jsonify({"error": "Assign a distinct bell sound to this room before scheduling a bell."}), 400
        cursor = db.execute("INSERT INTO bells(room_id,label,fire_at,tune,duration) VALUES(?,?,?,?,?)", (room_id, str(data.get("label", "")).strip()[:80], fire_at.isoformat(timespec="seconds"), tune, duration))
        row = db.execute("SELECT * FROM bells WHERE id=?", (cursor.lastrowid,)).fetchone()
        wake_enabled = schedule_bell(row)
        return jsonify({"id": cursor.lastrowid, "wake_enabled": wake_enabled}), 201


@app.delete("/api/bells/<int:bell_id>")
def delete_bell(bell_id):
    with connect() as db:
        db.execute("DELETE FROM bells WHERE id=?", (bell_id,))
    try:
        scheduler.remove_job(f"bell-{bell_id}")
    except Exception:
        pass
    return jsonify({"ok": True})


@app.post("/api/tunes")
def upload_tune():
    if "tune" not in request.files:
        return jsonify({"error": "Choose a WAV audio file."}), 400
    file = request.files["tune"]
    filename = secure_filename(file.filename or "")
    if Path(filename).suffix.lower().lstrip(".") not in ALLOWED_TUNE_EXTENSIONS:
        return jsonify({"error": "Only WAV tune files are supported."}), 400
    if not filename:
        return jsonify({"error": "Choose a named WAV tune file."}), 400
    target = TUNES / filename
    if target.exists():
        return jsonify({"error": "A tune with that filename already exists. Rename the file and try again."}), 409
    content = file.read()
    digest = hashlib.sha256(content).hexdigest()
    for existing in TUNES.glob("*.wav"):
        if hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
            return jsonify({"error": "This exact tune is already in the library. Use a different sound so rooms remain recognizable."}), 409
    try:
        import io
        with wave.open(io.BytesIO(content), "rb") as audio:
            if audio.getcomptype() != "NONE" or audio.getnchannels() not in {1, 2} or audio.getsampwidth() != 2 or audio.getframerate() > 96000:
                raise wave.Error("unsupported WAV format")
    except (wave.Error, EOFError):
        return jsonify({"error": "Choose an uncompressed 16-bit PCM WAV tune with one or two channels."}), 400
    target.write_bytes(content)
    return jsonify({"name": filename}), 201


@app.post("/api/tunes/preview")
def preview_tune():
    if not winsound:
        return jsonify({"error": "Tune preview uses the Windows audio output."}), 503
    if active_bell:
        return jsonify({"error": "Wait until the current room bell finishes before previewing another sound."}), 409
    tune = secure_filename(str((request.json or {}).get("tune", "")))
    path = TUNES / tune
    if not path.is_file() or path.suffix.lower() != ".wav":
        return jsonify({"error": "Choose an available tune."}), 404
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    return jsonify({"ok": True})


if __name__ == "__main__":
    if sys.stdout is None:
        startup_log = (DATA / "server.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = startup_log
        sys.stderr = startup_log
    init_db()
    scheduler.start()
    reload_schedules()
    print(f"Soundroom is starting at http://{local_network_address()}:8765")
    print(f"Local network access PIN: {config['pin']}")
    print("Keep this service on your trusted local network; do not forward its port to the internet.")
    app.run(host="0.0.0.0", port=8765, threaded=True)
