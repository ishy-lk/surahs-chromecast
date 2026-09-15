#!/usr/bin/env python3
"""
Casts Surah Al-Kahf to a Chromecast device/group at a scheduled daily time.

Sibling project to ../azan-chromecast — same Cast-discovery/playback pattern,
much simpler scheduling (one fixed time of day, optional day-of-week filter,
no timetable fetching).
"""
import time
import os
import sys
import json
import struct
import threading
import traceback
import http.server
import socketserver
import socket
import pychromecast
from datetime import datetime, timedelta, time as dt_time

# Ensure we always serve files from the script's own directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Force unbuffered output for logging
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None


def _log(level, msg, **fields):
    entry = {"ts": datetime.now().isoformat(timespec='seconds'), "level": level, "msg": msg}
    if fields:
        entry.update(fields)
    print(json.dumps(entry), flush=True)


def log_info(msg, **fields):  _log("info", msg, **fields)
def log_warn(msg, **fields):  _log("warn", msg, **fields)
def log_error(msg, **fields): _log("error", msg, **fields)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


# --- CONFIGURATION ---
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE) as f:
        _cfg = json.load(f)
else:
    log_warn("config_missing", hint="copy config.example.json to config.json and edit it")
    _cfg = {}

SPEAKER_OR_GROUP_NAME = _cfg.get("speaker_or_group_name", ["HomeGroup"])
LOCAL_IP = get_local_ip()
PORT = _cfg.get("port", 8001)
AUDIO_FILE = _cfg.get("audio_file", "surah-kahf-sudais.mp3")
BG_IMAGE = _cfg.get("bg_image", "makkah-1-wide-optimized.jpeg")
VOLUME = _cfg.get("volume", 0.5)

# When to play. 24h "HH:MM", local time. Change this and restart the service
# (sudo systemctl restart kahf-chromecast) to take effect.
PLAY_TIME = _cfg.get("play_time", "11:30")

# Days of week allowed to play. 0=Monday .. 6=Sunday. Defaults to every day;
# set to [4] for Friday-only (the traditional day for Surah Al-Kahf).
DAYS = set(_cfg.get("days", [0, 1, 2, 3, 4, 5, 6]))


# 1. Background Web Server (same pattern as azan-chromecast)
def start_server():
    handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", PORT), handler) as httpd:
            log_info("http_server_start", port=PORT)
            httpd.serve_forever()
    except OSError as e:
        log_warn("http_server_error", port=PORT, error=str(e))


def ensure_server_running():
    if not hasattr(ensure_server_running, '_started'):
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(1)
        ensure_server_running._started = True


# 2. MP3 duration — parse the first MPEG frame header for the bitrate, then
# duration = size * 8 / bitrate. Exact for CBR files (this one is 192kbps CBR).
# No extra dependency needed just for this.
_BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_SAMPLE_RATES_V1 = [44100, 48000, 32000, 0]


def mp3_duration(path):
    """Return (duration_seconds, bitrate_kbps) for a CBR MP3, or (None, None) on failure."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            data = f.read(64 * 1024)  # skip any ID3v2 tag, then find the first frame sync
        offset = 0
        if data[:3] == b'ID3':
            tag_size = ((data[6] & 0x7f) << 21) | ((data[7] & 0x7f) << 14) | \
                       ((data[8] & 0x7f) << 7) | (data[9] & 0x7f)
            offset = 10 + tag_size
        while offset < len(data) - 4:
            if data[offset] == 0xFF and (data[offset + 1] & 0xE0) == 0xE0:
                header = struct.unpack('>I', data[offset:offset + 4])[0]
                version = (header >> 19) & 0x3
                layer = (header >> 17) & 0x3
                bitrate_idx = (header >> 12) & 0xF
                if version == 3 and layer == 1 and 0 < bitrate_idx < 15:  # MPEG1 Layer III
                    bitrate_kbps = _BITRATES_V1_L3[bitrate_idx]
                    duration = (size * 8) / (bitrate_kbps * 1000)
                    return duration, bitrate_kbps
            offset += 1
    except Exception as e:
        log_warn("duration_parse_failed", file=path, error=str(e))
    return None, None


def human_duration(seconds):
    if seconds is None:
        return "unknown"
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}m {s:02d}s"


# 3. Playback (same discovery/cast pattern as azan-chromecast's play_azan)
def play_kahf(test_mode=False):
    chromecasts = []
    browser = None
    try:
        log_info("playback_start", test=test_mode)

        chromecasts, browser = None, None
        discovery_start = time.time()
        for attempt in range(1, 4):
            if browser is not None:
                try:
                    browser.stop_discovery()
                except Exception:
                    pass
            chromecasts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=list(SPEAKER_OR_GROUP_NAME), discovery_timeout=20)
            if chromecasts:
                break
            log_warn("playback_discovery_retry", attempt=attempt,
                     targets=list(SPEAKER_OR_GROUP_NAME))
        discovery_elapsed = round(time.time() - discovery_start, 2)
        if not chromecasts:
            log_error("playback_no_devices", targets=list(SPEAKER_OR_GROUP_NAME),
                      elapsed_seconds=discovery_elapsed)
            return

        log_info("playback_devices_found", count=len(chromecasts),
                 devices=[c.name for c in chromecasts],
                 attempts=attempt, elapsed_seconds=discovery_elapsed)

        duration_s, _ = mp3_duration(AUDIO_FILE)
        title_text = "Surah Al-Kahf"
        artist_text = "Abdur-Rahman as-Sudays"
        album_text = f"Quran · 18:114 · {human_duration(duration_s)}"

        current_ip = get_local_ip()
        url = f"http://{current_ip}:{PORT}/{AUDIO_FILE}"
        thumb_url = f"http://{current_ip}:{PORT}/{BG_IMAGE}"

        log_info("playback_urls", audio=url, image=thumb_url, ip=current_ip)

        media_controllers = []

        for cast in chromecasts:
            try:
                cast.wait()
                log_info("playback_device_connect", device=cast.name,
                         type=cast.cast_type, model=cast.model_name)

                mc = cast.media_controller
                mc.update_status()
                if mc.status.player_state in ['PLAYING', 'BUFFERING', 'PAUSED']:
                    log_info("playback_stop_existing", device=cast.name,
                             state=mc.status.player_state)
                    mc.stop()
                    time.sleep(0.3)

                cast.set_volume(VOLUME)
                log_info("playback_volume_set", device=cast.name, volume=round(VOLUME, 2))

                is_group = cast.cast_type == 'group'
                is_audio_only = 'audio' in cast.model_name.lower() or 'mini' in cast.model_name.lower()
                use_images = not is_group and not is_audio_only

                metadata = {
                    'metadataType': 3,
                    'title': title_text,
                    'artist': artist_text,
                    'albumName': album_text,
                }
                if use_images:
                    metadata['images'] = [{'url': thumb_url}]

                if is_group:
                    log_info("playback_no_art", device=cast.name, reason="group_cast")
                elif is_audio_only:
                    log_info("playback_no_art", device=cast.name, reason="audio_only")

                log_info("playback_send", device=cast.name, title=title_text)
                # BUFFERED (not LIVE): this is a ~24min recitation, not a short
                # clip, so it should show a seekable progress bar on-screen.
                mc.play_media(
                    url,
                    'audio/mpeg',
                    title=title_text,
                    thumb=thumb_url if use_images else None,
                    current_time=0,
                    autoplay=True,
                    stream_type='BUFFERED',
                    metadata=metadata
                )
                wait_start = time.time()
                while time.time() - wait_start < 15:
                    mc.update_status()
                    if mc.status and mc.status.player_state in ['PLAYING', 'BUFFERING']:
                        break
                    time.sleep(0.5)
                log_info("playback_ok", device=cast.name, title=title_text)
                media_controllers.append((mc, cast.name))

                time.sleep(0.5)
            except Exception as e:
                log_error("playback_device_error", device=cast.name, error=str(e))
                traceback.print_exc()

        log_info("playback_complete", devices_succeeded=len(media_controllers))

    except Exception as e:
        log_error("playback_error", error=str(e))
        traceback.print_exc()

    finally:
        for cast in chromecasts:
            try:
                cast.disconnect()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:
                pass


# 4. Scheduling — next allowed HH:MM on/after now, honouring DAYS
def next_run(now):
    h, m = map(int, PLAY_TIME.split(':'))
    for offset in range(8):  # look up to a week ahead
        cand_date = now.date() + timedelta(days=offset)
        cand = datetime.combine(cand_date, dt_time(hour=h, minute=m))
        if cand > now and cand.weekday() in DAYS:
            return cand
    return None  # DAYS is empty


# --- STARTUP ---
duration_s, bitrate_kbps = mp3_duration(AUDIO_FILE) if os.path.exists(AUDIO_FILE) else (None, None)
log_info("service_start",
         audio_file=AUDIO_FILE,
         duration_seconds=round(duration_s, 2) if duration_s else None,
         duration_human=human_duration(duration_s),
         play_time=PLAY_TIME,
         days=sorted(DAYS),
         devices=list(SPEAKER_OR_GROUP_NAME),
         volume=VOLUME,
         ip=LOCAL_IP,
         port=PORT)

# --duration: print audio duration and exit
if '--duration' in sys.argv:
    if duration_s is None:
        print("Could not determine duration (file missing or unparseable).")
        sys.exit(1)
    print(f"{AUDIO_FILE}: {duration_s:.2f}s ({human_duration(duration_s)}), {bitrate_kbps}kbps")
    sys.exit(0)

# --next: print the next scheduled run and exit
if '--next' in sys.argv:
    nxt = next_run(datetime.now())
    if nxt is None:
        print("No days enabled in config (days: []).")
    else:
        print(f"Next Kahf playback: {nxt.strftime('%A %Y-%m-%d %H:%M')}")
    sys.exit(0)

# All modes below need the HTTP server
ensure_server_running()

# --test: cast immediately and exit
if '--test' in sys.argv:
    log_info("test_mode_start")
    play_kahf(test_mode=True)
    time.sleep(30)
    log_info("test_complete")
    sys.exit(0)

# Normal scheduling mode
while True:
    now = datetime.now()
    nxt = next_run(now)

    if nxt is None:
        log_error("no_days_enabled", hint="config.json 'days' list is empty")
        time.sleep(3600)
        continue

    wait_secs = (nxt - now).total_seconds()
    log_info("next_kahf", at=nxt.strftime('%Y-%m-%d %H:%M'), wait_seconds=int(wait_secs))

    time.sleep(max(wait_secs, 0))

    log_info("kahf_time", scheduled=nxt.strftime('%Y-%m-%d %H:%M'))
    play_kahf()

    # Wait past the minute to avoid re-triggering the same slot
    time.sleep(61)
