# 📖 Surah Al-Kahf Chromecast

Automatically plays Surah Al-Kahf on Google Chromecast devices at a scheduled time every day (or on chosen days of the week).

Sibling project to [azan-chromecast](https://github.com/ishy-lk/azan-chromecast) — same Cast-discovery/playback approach, much simpler: one fixed daily time instead of a prayer timetable.

## Changing the time

Edit `play_time` in `config.json`, then restart the service:

```bash
nano config.json          # e.g. "play_time": "11:30"
sudo systemctl restart kahf-chromecast
```

That's it — no code changes needed.

## Audio

`surah-kahf-sudais.mp3` — Surat Al-Kahf recited by Abdur-Rahman as-Sudays (source: quranicaudio.com).

- **Duration: 23m 41s** (1420.86s), 192kbps CBR, 34MB

## Quick Commands

```bash
python3 kahf.py --duration   # print the audio duration and exit
python3 kahf.py --next       # print the next scheduled playback time and exit
python3 kahf.py --test       # cast immediately (ignores schedule)
python3 kahf.py              # run the scheduler
```

## Configuration (`config.json`)

```json
{
  "speaker_or_group_name": ["HomeGroup"],
  "play_time": "11:30",
  "days": [0, 1, 2, 3, 4, 5, 6],
  "volume": 0.5,
  "audio_file": "surah-kahf-sudais.mp3",
  "bg_image": "makkah-1-wide-optimized.jpeg",
  "port": 8001
}
```

- `speaker_or_group_name` — Chromecast device or group name(s) to cast to
- `play_time` — 24h `HH:MM`, local time
- `days` — which days to play on, `0`=Monday .. `6`=Sunday. Defaults to every day. For the traditional Friday-only sunnah, use `[4]`
- `volume` — Cast volume, `0.0`–`1.0`
- `port` — local HTTP server port that serves the audio/image to the Cast device. Defaults to `8001` so it doesn't clash with azan-chromecast's `8000` if both run on the same Pi

Copy `config.example.json` to `config.json` and edit as needed (`config.json` is gitignored so your device names stay local).

## Setup

```bash
git clone https://github.com/ishy-lk/kahf-chromecast.git
cd kahf-chromecast
./setup.sh
cp config.example.json config.json
nano config.json
```

Test before installing as a service:

```bash
source venv/bin/activate
python3 kahf.py --duration
python3 kahf.py --next
python3 kahf.py --test
```

## Service Management (Linux / Raspberry Pi / systemd)

```bash
sed "s/YOUR_USERNAME/$USER/g" kahf.service | sudo tee /etc/systemd/system/kahf-chromecast.service
sudo systemctl daemon-reload
sudo systemctl enable --now kahf-chromecast

# Check status / logs
sudo systemctl status kahf-chromecast
sudo journalctl -u kahf-chromecast -f
```

## Updating

```bash
git pull
sudo systemctl restart kahf-chromecast
```

`setup.sh` only needs to be run once (or again if `requirements.txt` changes). Your `config.json` is untouched by updates.

## Features

- Plays Surah Al-Kahf on a Chromecast device/group at a configurable daily time
- Optional day-of-week filter (defaults to every day)
- Visual display on Google Home/Nest Hub screens: title, reciter, and a Makkah background image
- Seekable/bufferable playback (not a live stream) so the progress bar works on-screen
- Auto-detects local IP address for serving the audio file
