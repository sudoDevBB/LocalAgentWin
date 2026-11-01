from __future__ import annotations

import json
import array
import atexit
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
import urllib.error
import urllib.request
import wave
try:
    import winsound
except ImportError:  # lets the interface preview run on non-Windows development machines
    winsound = None
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TUNES = DATA / "tunes"
DB = DATA / "soundroom.db"
CONFIG = DATA / "config.json"
ALLOWED_TUNE_EXTENSIONS = {"wav"}
DEFAULT_PIN = "223344"
CONFIG_VERSION = 2
CHROME_DEBUG_PORT = 9222
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
scheduler = BackgroundScheduler(daemon=True)
audio_lock = threading.Lock()
bell_state_lock = threading.Lock()
player_lock = threading.RLock()
player_commands = queue.Queue()
player_ready = threading.Event()
active_bell = None
active_bell_stop = None
player_process = None
player_playwright = None
player_context = None
player_page = None
player_thread = None
player_start_error = None
player_snapshot = {"state": "idle", "video_id": None, "title": "No video selected"}


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


def chrome_profile_path():
    return str((DATA / "chrome-profile").resolve())


def close_normal_chrome_youtube_tabs():
    """Close YouTube tabs in the user's regular Chrome windows, leaving other tabs alone."""
    if sys.platform != "win32":
        return 0
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    managed_profile = os.path.normcase(chrome_profile_path())
    closed = 0
    for window in Desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1"):
        try:
            command = " ".join(__import__("psutil").Process(window.process_id()).cmdline())
            if managed_profile in os.path.normcase(command):
                continue
            for _ in range(50):
                youtube_tab = next((tab for tab in window.descendants(control_type="TabItem")
                                    if "youtube" in tab.window_text().lower()), None)
                if youtube_tab is None:
                    break
                youtube_tab.click_input()
                window.set_focus()
                send_keys("^w")
                closed += 1
                time.sleep(0.15)
        except Exception:
            continue
    return closed


def player_worker():
    """Own Playwright and its browser objects on one thread for their full lifetime."""
    global player_playwright, player_context, player_page, player_process, player_start_error, player_snapshot
    if sys.platform != "win32":
        player_start_error = "Server-side YouTube playback requires Chrome on the Windows server."
        player_ready.set()
        return
    try:
        from playwright.sync_api import sync_playwright
        import psutil
        player_playwright = sync_playwright().start()
        player_context = player_playwright.chromium.launch_persistent_context(
            user_data_dir=chrome_profile_path(),
            headless=False,
            args=["--autoplay-policy=no-user-gesture-required", "--no-first-run"],
        )
        player_page = player_context.pages[0] if player_context.pages else player_context.new_page()
        profile = os.path.normcase(chrome_profile_path())
        for _ in range(40):
            player_process = next((process for process in psutil.process_iter(["name", "cmdline"])
                                   if process.info["name"] and process.info["name"].lower() == "chrome.exe"
                                   and profile in os.path.normcase(" ".join(process.info["cmdline"] or []))), None)
            if player_process:
                break
            time.sleep(0.25)
        player_ready.set()
        while True:
            try:
                command, value, response = player_commands.get(timeout=1)
            except queue.Empty:
                command = "status"
                value = None
                response = None
            try:
                if command == "shutdown":
                    if player_context:
                        player_context.close()
                    if response:
                        response.put((True, {"ok": True}))
                    break
                elif command == "reset":
                    # Kill the managed browser process tree first so a stuck media
                    # renderer cannot keep the old player session alive.
                    if player_process:
                        try:
                            descendants = player_process.children(recursive=True)
                            for process in reversed(descendants):
                                try:
                                    process.kill()
                                except psutil.Error:
                                    pass
                            player_process.kill()
                        except psutil.Error:
                            pass
                    try:
                        if player_context:
                            player_context.close()
                    except Exception:
                        pass
                    try:
                        player_playwright.stop()
                    except Exception:
                        pass
                    player_playwright = sync_playwright().start()
                    player_context = player_playwright.chromium.launch_persistent_context(
                        user_data_dir=chrome_profile_path(),
                        headless=False,
                        args=["--autoplay-policy=no-user-gesture-required", "--no-first-run"],
                    )
                    player_page = player_context.pages[0] if player_context.pages else player_context.new_page()
                    player_process = None
                    profile = os.path.normcase(chrome_profile_path())
                    for _ in range(40):
                        player_process = next((process for process in psutil.process_iter(["name", "cmdline"])
                                               if process.info["name"] and process.info["name"].lower() in {"chrome.exe", "chromium.exe"}
                                               and profile in os.path.normcase(" ".join(process.info["cmdline"] or []))), None)
                        if player_process:
                            break
                        time.sleep(0.25)
                    player_snapshot = {"state": "idle", "video_id": None, "title": "No video selected"}
                    result = dict(player_snapshot)
                elif command == "play":
                    for extra_page in player_context.pages:
                        if extra_page != player_page and ("youtube.com" in extra_page.url.lower() or "youtu.be" in extra_page.url.lower()):
                            extra_page.close()
                    player_page.goto(f"https://www.youtube.com/watch?v={value}", wait_until="domcontentloaded", timeout=45000)
                    player_page.wait_for_selector("video", timeout=30000)
                    player_page.locator("video").evaluate("video => video.play()")
                    player_snapshot = {"state": "playing", "video_id": value, "title": player_page.title()}
                    result = dict(player_snapshot)
                elif command == "pause":
                    player_page.locator("video").evaluate("video => video.pause()", timeout=5000)
                    player_snapshot = {**player_snapshot, "state": "paused"}
                    result = {"ok": True}
                elif command == "resume":
                    player_page.locator("video").evaluate("video => video.play()", timeout=5000)
                    player_snapshot = {**player_snapshot, "state": "playing"}
                    result = {"ok": True}
                else:
                    if player_page:
                        try:
                            state = player_page.locator("video").evaluate("video => video.paused ? 'paused' : 'playing'", timeout=1500)
                            match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", player_page.url)
                            player_snapshot = {"state": state, "video_id": match.group(1) if match else None, "title": player_page.title()}
                        except Exception:
                            pass
                    result = dict(player_snapshot)
                if response:
                    response.put((True, result))
            except Exception as exc:
                if response:
                    response.put((False, exc))
    except Exception as exc:
        player_start_error = f"Could not start Google Chrome on the server: {exc}"
        player_ready.set()
        if player_playwright:
            try:
                player_playwright.stop()
            except Exception:
                pass
            player_playwright = None


def shutdown_player():
    if player_thread and player_thread.is_alive() and player_ready.is_set() and not player_start_error:
        response = queue.Queue(maxsize=1)
        player_commands.put(("shutdown", None, response))
        try:
            response.get(timeout=5)
            player_thread.join(timeout=5)
        except queue.Empty:
            pass
    if player_playwright:
        try:
            player_playwright.stop()
        except Exception:
            pass


def player_command(command, value=None, timeout=60):
    global player_thread, player_start_error
    if sys.platform != "win32":
        raise RuntimeError("Server-side YouTube playback requires Chrome on the Windows server.")
    with player_lock:
        if not player_thread or not player_thread.is_alive():
            player_ready.clear()
            player_start_error = None
            player_thread = threading.Thread(target=player_worker, name="Soundroom Chrome controller", daemon=True)
            player_thread.start()
        if not player_ready.wait(timeout=30):
            raise RuntimeError("Chrome did not start in time. Check that Google Chrome is installed on the server.")
        if player_start_error:
            raise RuntimeError(player_start_error)
        response = queue.Queue(maxsize=1)
        player_commands.put((command, value, response))
    try:
        succeeded, result = response.get(timeout=timeout)
    except queue.Empty as exc:
        raise RuntimeError("Chrome did not respond in time. Check the server display and internet connection.") from exc
    if not succeeded:
        if command == "play":
            raise RuntimeError("Chrome opened YouTube, but playback did not start. Check the server's internet connection or any YouTube sign-in prompt.") from result
        if command == "pause":
            return False
        raise result
    return result


def play_server_video(video_id):
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("Enter a valid YouTube video link.")
    closed_tabs = close_normal_chrome_youtube_tabs()
    result = player_command("play", video_id, timeout=60)
    result["closed_tabs"] = closed_tabs
    return result


def pause_server_video():
    if not player_thread or not player_thread.is_alive() or not player_snapshot.get("video_id"):
        return False
    return bool(player_command("pause", timeout=8))


def server_player_status():
    if not player_thread or not player_thread.is_alive():
        return {"state": "idle", "video_id": None, "title": "No video selected"}
    try:
        return player_command("status", timeout=3)
    except Exception:
        return dict(player_snapshot)


def windows_audio_sessions():
    """Find audio sessions that belong to Soundroom's managed Chrome process tree."""
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


def schedule_bell(row):
    job_id = f"bell-{row['id']}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    if not row["enabled"]:
        return
    fire_at = datetime.fromisoformat(row["fire_at"])
    if fire_at <= datetime.now():
        return
    scheduler.add_job(fire_bell, "date", run_date=fire_at, args=[row["id"]], id=job_id, replace_existing=True)


def reload_schedules():
    now = datetime.now()
    with connect() as db:
        db.execute("UPDATE bells SET enabled=0 WHERE enabled=1 AND fire_at<=?", (now.isoformat(timespec="seconds"),))
        for row in db.execute("SELECT * FROM bells WHERE enabled=1"):
            schedule_bell(row)


@app.before_request
def require_pin():
    if request.endpoint in {"login", "login_post", "static"} or session.get("authenticated"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Enter the local access PIN to continue."}), 401
    return redirect(url_for("login"))


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
    tune = secure_filename(str((request.json or {}).get("default_tune", "")))
    if not tune or Path(tune).suffix.lower() != ".wav" or not (TUNES / tune).is_file():
        return jsonify({"error": "Choose one of the available WAV tunes."}), 400
    with connect() as db:
        conflict = db.execute("SELECT name FROM rooms WHERE default_tune=? AND id<>?", (tune, room_id)).fetchone()
        if conflict:
            return jsonify({"error": f"That sound is already assigned to {conflict['name']}. Choose a different tune so each room remains recognizable."}), 409
        cursor = db.execute("UPDATE rooms SET default_tune=? WHERE id=?", (tune, room_id))
    if not cursor.rowcount:
        return jsonify({"error": "Room not found."}), 404
    return jsonify({"ok": True, "default_tune": tune})


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
        schedule_bell(row)
        return jsonify({"id": cursor.lastrowid}), 201


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
    atexit.register(shutdown_player)
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
