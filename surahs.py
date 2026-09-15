#!/usr/bin/env python3
"""
Casts one or more Surahs to a Chromecast device/group, each on its own daily
schedule (time of day + allowed days of week), from a single service.

Sibling project to ../azan-chromecast — same Cast-discovery/playback pattern,
much simpler scheduling (fixed times of day per surah, no timetable fetching).
"""
import time
import os
import sys
import json
import struct
import subprocess
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
BG_IMAGE = _cfg.get("bg_image", "makkah-1-wide-optimized.jpeg")
VOLUME = _cfg.get("volume", 0.5)

# Each entry: name, artist, audio_file, play_time ("HH:MM", 24h local time),
# days (0=Mon..6=Sun, defaults to every day). Edit these and restart the
# service (sudo systemctl restart surahs-chromecast) to change the schedule.
SURAHS = _cfg.get("surahs", [])
for _s in SURAHS:
    _s.setdefault("days", [0, 1, 2, 3, 4, 5, 6])


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


# 2. MP3 duration. Prefer ffprobe (already installed on this Pi, handles both
# CBR and VBR files correctly). Fall back to parsing the first MPEG frame
# header and assuming CBR if ffprobe isn't available — good enough estimate,
# but only exact for CBR files.
_BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]


def _mp3_duration_ffprobe(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _mp3_duration_cbr_estimate(path):
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
                    return (size * 8) / (bitrate_kbps * 1000)
            offset += 1
    except Exception as e:
        log_warn("duration_parse_failed", file=path, error=str(e))
    return None


def mp3_duration(path):
    """Return duration in seconds, or None on failure."""
    return _mp3_duration_ffprobe(path) or _mp3_duration_cbr_estimate(path)


def human_duration(seconds):
    if seconds is None:
        return "unknown"
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}m {s:02d}s"


# 3. Playback (same discovery/cast pattern as azan-chromecast's play_azan)
def play_surah(surah, test_mode=False):
    chromecasts = []
    browser = None
    try:
        name = surah["name"]
        artist = surah.get("artist", "")
        audio_file = surah["audio_file"]

        log_info("playback_start", surah=name, test=test_mode)

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

        duration_s = mp3_duration(audio_file)
        title_text = name
        artist_text = artist
        album_text = f"Quran · {human_duration(duration_s)}"

        current_ip = get_local_ip()
        url = f"http://{current_ip}:{PORT}/{audio_file}"
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
                # BUFFERED (not LIVE): these are long recitations, not short
                # clips, so they should show a seekable progress bar on-screen.
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

        log_info("playback_complete", surah=name, devices_succeeded=len(media_controllers))

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


# 4. Scheduling — next allowed HH:MM on/after now for a given surah, honouring its days
def next_run(surah, now):
    h, m = map(int, surah["play_time"].split(':'))
    days = set(surah.get("days", [0, 1, 2, 3, 4, 5, 6]))
    for offset in range(8):  # look up to a week ahead
        cand_date = now.date() + timedelta(days=offset)
        cand = datetime.combine(cand_date, dt_time(hour=h, minute=m))
        if cand > now and cand.weekday() in days:
            return cand
    return None  # days is empty


def next_run_all(now):
    """Return (surah, run_datetime) for whichever configured surah runs soonest."""
    best = None
    for surah in SURAHS:
        nxt = next_run(surah, now)
        if nxt is not None and (best is None or nxt < best[1]):
            best = (surah, nxt)
    return best


# --- STARTUP ---
if not SURAHS:
    log_warn("no_surahs_configured", hint="add entries to the 'surahs' list in config.json")

for _s in SURAHS:
    _dur = mp3_duration(_s["audio_file"]) if os.path.exists(_s["audio_file"]) else None
    log_info("surah_loaded",
             name=_s["name"],
             audio_file=_s["audio_file"],
             duration_seconds=round(_dur, 2) if _dur else None,
             duration_human=human_duration(_dur),
             play_time=_s["play_time"],
             days=sorted(_s.get("days", [0, 1, 2, 3, 4, 5, 6])))

log_info("service_start",
         surahs=[s["name"] for s in SURAHS],
         devices=list(SPEAKER_OR_GROUP_NAME),
         volume=VOLUME,
         ip=LOCAL_IP,
         port=PORT)

# --duration: print each surah's audio duration and exit
if '--duration' in sys.argv:
    for s in SURAHS:
        d = mp3_duration(s["audio_file"])
        if d is None:
            print(f"{s['name']} ({s['audio_file']}): could not determine duration")
        else:
            print(f"{s['name']} ({s['audio_file']}): {d:.2f}s ({human_duration(d)})")
    sys.exit(0)

# --next: print the next scheduled run for each surah, and overall, and exit
if '--next' in sys.argv:
    now = datetime.now()
    for s in SURAHS:
        nxt = next_run(s, now)
        if nxt is None:
            print(f"{s['name']}: no days enabled")
        else:
            print(f"{s['name']}: {nxt.strftime('%A %Y-%m-%d %H:%M')}")
    overall = next_run_all(now)
    if overall:
        print(f"--> next overall: {overall[0]['name']} at {overall[1].strftime('%A %Y-%m-%d %H:%M')}")
    sys.exit(0)

# All modes below need the HTTP server
ensure_server_running()

# --test [name]: cast a surah immediately and exit. Defaults to the first configured surah.
if '--test' in sys.argv:
    target = None
    idx = sys.argv.index('--test')
    if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith('--'):
        wanted = sys.argv[idx + 1].lower()
        target = next((s for s in SURAHS if s["name"].lower() == wanted), None)
    if target is None:
        target = SURAHS[0] if SURAHS else None
    if target is None:
        log_error("test_no_surahs")
        sys.exit(1)
    log_info("test_mode_start", surah=target["name"])
    play_surah(target, test_mode=True)
    time.sleep(30)
    log_info("test_complete")
    sys.exit(0)

# Normal scheduling mode
while True:
    now = datetime.now()
    picked = next_run_all(now)

    if picked is None:
        log_error("no_playback_scheduled", hint="no surahs configured, or all have empty 'days'")
        time.sleep(3600)
        continue

    surah, nxt = picked
    wait_secs = (nxt - now).total_seconds()
    log_info("next_playback", surah=surah["name"], at=nxt.strftime('%Y-%m-%d %H:%M'),
             wait_seconds=int(wait_secs))

    time.sleep(max(wait_secs, 0))

    log_info("playback_time", surah=surah["name"], scheduled=nxt.strftime('%Y-%m-%d %H:%M'))
    play_surah(surah)

    # Wait past the minute to avoid re-triggering the same slot
    time.sleep(61)
