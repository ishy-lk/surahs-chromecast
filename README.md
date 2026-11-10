# 📖 Surahs Chromecast

Automatically plays Quran Surahs on Google Chromecast devices, each on its own daily schedule (time of day + optional day-of-week filter), all from one service.

Sibling project to [azan-chromecast](https://github.com/ishy-lk/azan-chromecast) — same Cast-discovery/playback approach, much simpler: fixed times of day per surah instead of a prayer timetable.

## Changing the schedule

Edit the `surahs` list in `config.json`, then restart the service:

```bash
nano config.json          # e.g. change a surah's "play_time" or "days"
sudo systemctl restart surahs-chromecast
```

That's it — no code changes needed. Add a new surah by adding another entry to the `surahs` list (drop the mp3 in this folder first).

## Surahs

| Surah | Reciter | Schedule | Duration |
|---|---|---|---|
| Al-Kahf | Abdur-Rahman as-Sudays | Friday 12:00 | 23m 41s (1420.86s, 192kbps CBR, 34MB) |
| Al-Baqarah | Abdulrahman Alsudaes | Daily 09:00 | 93m 46s (5626.02s, ~128kbps VBR, 90MB) |

Sources: `surah-kahf-sudais.mp3` from quranicaudio.com, `surah-baqarah-sudais.mp3` from mp3quran.net.

## Quick Commands

```bash
python3 surahs.py --duration           # print each surah's audio duration and exit
python3 surahs.py --next               # print each surah's next scheduled run, and exit
python3 surahs.py --test               # cast the first configured surah immediately
python3 surahs.py --test Al-Baqarah    # cast a specific surah by name immediately
python3 surahs.py                      # run the scheduler
```

## Configuration (`config.json`)

```json
{
  "speaker_or_group_name": ["HomeGroup"],
  "volume": 0.25,
  "bg_image": "makkah-1-wide-optimized.jpeg",
  "port": 8001,
  "surahs": [
    {
      "name": "Al-Kahf",
      "artist": "Abdur-Rahman as-Sudays",
      "audio_file": "surah-kahf-sudais.mp3",
      "play_time": "12:00",
      "days": [4]
    },
    {
      "name": "Al-Baqarah",
      "artist": "Abdulrahman Alsudaes",
      "audio_file": "surah-baqarah-sudais.mp3",
      "play_time": "09:00",
      "days": [0, 1, 2, 3, 4, 5, 6]
    }
  ]
}
```

- `speaker_or_group_name` — Chromecast device or group name(s) to cast to
- `volume` — Cast volume, `0.0`–`1.0`, shared by all surahs
- `port` — local HTTP server port that serves the audio/image to the Cast device. Defaults to `8001` so it doesn't clash with azan-chromecast's `8000` if both run on the same Pi
- `surahs` — one entry per surah:
  - `name` / `artist` — shown on the Google Home/Nest Hub display
  - `audio_file` — mp3 filename in this folder
  - `play_time` — 24h `HH:MM`, local time
  - `days` — which days to play on, `0`=Monday .. `6`=Sunday. Defaults to every day. For the traditional Friday-only sunnah, use `[4]`

Copy `config.example.json` to `config.json` and edit as needed (`config.json` is gitignored so your device names stay local).

## Setup

```bash
git clone https://github.com/ishy-lk/surahs-chromecast.git
cd surahs-chromecast
./setup.sh
cp config.example.json config.json
nano config.json
```

Test before installing as a service:

```bash
source venv/bin/activate
python3 surahs.py --duration
python3 surahs.py --next
python3 surahs.py --test
```

## Service Management (Linux / Raspberry Pi / systemd)

```bash
sed "s/YOUR_USERNAME/$USER/g" surahs.service | sudo tee /etc/systemd/system/surahs-chromecast.service
sudo systemctl daemon-reload
sudo systemctl enable --now surahs-chromecast

# Check status / logs
sudo systemctl status surahs-chromecast
sudo journalctl -u surahs-chromecast -f
# or: tail -f /var/log/surahs_chromecast.log
```

### Shell shortcuts on this Pi

These shortcuts are defined in `~/.bashrc` on this Pi, not installed by
`setup.sh`. To add them on another machine, put this in `~/.bashrc` (adjust the
project path if needed):

```bash
alias start-surahs='sudo systemctl start surahs-chromecast'
alias stop-surahs='sudo systemctl stop surahs-chromecast'
play-surahs() {
    sudo systemctl start surahs-chromecast &&
        "$HOME/git/surahs-chromecast/venv/bin/python3" "$HOME/git/surahs-chromecast/surahs.py" --test "$@"
}
```

Reload your shell with `source ~/.bashrc`, then:

```bash
start-surahs              # start the scheduler (waits for the scheduled time)
stop-surahs               # stop the service
play-surahs               # start the service and immediately cast the first configured surah
play-surahs Al-Baqarah    # immediately cast a specific configured surah
play-surahs Al-Kahf       # immediately cast Al-Kahf
```

`play-surahs` starts playback immediately, regardless of the configured time or
day, including when the service was stopped. It replaces current media on the
configured Chromecast device/group and starts the requested surah from the
beginning; unrelated speakers are unaffected.

It also resumes scheduled playback and keeps the service running to serve the
full audio after the immediate-cast command exits. Use an exact configured surah
name: the existing `--test` mode falls back to the first surah if a name is not
found.

The immediate-cast command may print `http_server_error` / `Address already in
use` because the running service already owns the audio server port. Playback
uses that existing server.

## Updating

```bash
git pull
sudo systemctl restart surahs-chromecast
```

`setup.sh` only needs to be run once (or again if `requirements.txt` changes). Your `config.json` is untouched by updates.

## Features

- Plays any number of Quran Surahs on a Chromecast device/group, each on its own configurable daily time
- Optional day-of-week filter per surah (defaults to every day)
- Visual display on Google Home/Nest Hub screens: title, reciter, and a Makkah background image
- Seekable/bufferable playback (not a live stream) so the progress bar works on-screen
- Duration detection via `ffprobe` (falls back to a CBR frame-header estimate if `ffprobe` is unavailable) — correct for both CBR and VBR files
- Auto-detects local IP address for serving the audio files
