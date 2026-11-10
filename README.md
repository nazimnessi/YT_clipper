# YouTube Clipper

One long YouTube video in, vertical Shorts (1080×1920) with animated subtitles out.

```
ingest → highlight → for each clip: fetch → transcribe → frame → render → (publish, off by default)
```

| Step | File | What it does |
|---|---|---|
| ingest | `ingest.py` | Video details, YouTube captions, the most-replayed heatmap, chapters and top comments. Doesn't download the video. |
| highlight | `highlight.py` | Picks the best moments using a ranked Claude, Gemini, and Groq model chain, then a free heuristic. |
| fetch | `fetch.py` | Downloads only each clip's time range. |
| transcribe | `transcribe.py` | Whisper gives exact word timings, then each clip's start and end are moved onto natural pauses. |
| frame | `frame.py` | Finds shot changes and faces, then picks **single** (one face), **stacked** (two people, one on top of the other) or **wide** (whole frame) for each shot. |
| render | `render.py` | Crops or stacks each shot, adds karaoke subtitles and a hook title, and evens out the volume. |
| publish | `publish.py` | Uploads to YouTube. Off unless you pass `--upload`. |

---

## 1. Install (one time)

### a) Python 3.11 or 3.12
Download it from https://www.python.org/downloads/. On Windows, tick **"Add python.exe to PATH"** during setup.

### b) ffmpeg (cutting and rendering)
```powershell
winget install Gyan.FFmpeg          # Windows
brew install ffmpeg                 # Mac
sudo apt install ffmpeg             # Linux
```
Close and reopen the terminal, then check that it works: `ffmpeg -version`

### c) Deno (yt-dlp needs it for YouTube)
```powershell
winget install DenoLand.Deno        # Windows
brew install deno                   # Mac
curl -fsSL https://deno.land/install.sh | sh   # Linux
```

### d) Python packages
Run these in the `clipper` folder:
```powershell
python -m venv .venv
.venv\Scripts\activate              # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

### e) API keys
Copy `.env.example` to `.env` and fill in your keys:

| Key | Where to get it | Needed? |
|---|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API keys | Optional: enables Claude models in the ranked highlight chain. |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Optional: enables Gemini models in the ranked highlight chain. On the free tier, Google may use your prompts to improve its products. |
| `GROQ_API_KEY` | https://console.groq.com/keys | Optional: enables Groq models in the ranked highlight chain. |

If none of these keys is set, the free heuristic picks the clips. It works, but the picks are worse.

### Downloaded automatically on first run
| What | Size | Saved to |
|---|---|---|
| Whisper model (`small`) | ~470 MB | Hugging Face cache in your user folder |
| Face detection model (YuNet) | ~230 KB | `models/` |

---

## 2. Run

```powershell
python main.py --url "https://youtu.be/k8W0Eb7sKss"
```

If you don't give `--url`, the script uses the **first row of `input_video.xlsx`**:

| video_url | yt_account |
|---|---|
| https://youtu.be/k8W0Eb7sKss | @MyClipsChannel |

`yt_account` is only for your records. It's written to the logs and to `results.json`. The Excel file is optional.

### Options
| Option | Default | Meaning |
|---|---|---|
| `--url` | – | YouTube link |
| `--excel` | `input_video.xlsx` | input Excel file |
| `--clips` | 3 | number of clips |
| `--min-sec` / `--max-sec` | 20 / 59 | allowed clip length |
| `--layout` | auto | `auto` / `single` / `stacked` / `wide` (use `stacked` to force two people top and bottom) |
| `--ai` | auto | `auto` (ranked Claude, Gemini, and Groq models, then heuristic) / `claude` / `gemini` / `groq` / `heuristic` |
| `--whisper-model` | small | `tiny` / `base` / `small` / `medium` / `large-v3` |
| `--whisper-device` | auto | `auto` / `cpu` / `cuda` |
| `--language` | auto | spoken language, for example `en`, `hi`, `ml` |
| `--upload` | **off** | upload the finished clips to YouTube |
| `--privacy` | private | privacy setting when uploading |
| `--out` | data | output folder |
| `--cookies-from-browser` | – | `chrome` / `edge` / `firefox`, if YouTube says "confirm you're not a bot" |
| `--force` | off | redo every step (otherwise the run resumes) |
| `--insecure` | off | skip SSL certificate checks (company network workaround) |
| `--verbose` | off | show debug lines in the console |
| `--config` | config.yaml | settings file |

Command-line options override `config.yaml`, which overrides the built-in defaults.
`config.yaml` contains the mixed-provider `ai_model_hierarchy`, ordered for
quality first. The app skips providers without keys and tries each remaining
model in sequence before falling back to the heuristic picker. Edit the list to
change its priority or match the models enabled for your API keys. Set
`GROQ_API_KEY` in `.env` to enable Groq models. Use `--ai groq` to restrict a
run to Groq models.

### Examples
```powershell
python main.py --url "https://youtu.be/ID" --clips 5 --max-sec 45
python main.py --url "https://youtu.be/ID" --layout stacked          # podcast / meeting
python main.py --url "https://youtu.be/ID" --ai gemini --whisper-model base
python main.py --url "https://youtu.be/ID" --ai groq
python main.py --url "https://youtu.be/ID" --upload --privacy unlisted
```

### Run a single step (for testing or re-doing one part)
```powershell
python frame.py  --video k8W0Eb7sKss --clip 2 --layout stacked --force
python render.py --video k8W0Eb7sKss --clip 2 --force
```

---

## 3. Output

```
data/<video_id>/
  output/01_<title>.mp4  02_...      <- finished clips
  info.json captions.json heatmap.json comments.json
  highlights.json                    <- chosen clips, scores, which AI picked them
  results.json   run.log   state.json
  clip_1/ source.mp4 words.json clip.json frame.json subs.ass filter.txt final.mp4
logs/run_YYYYMMDD_HHMMSS.log         <- full debug log for each run
```

- **Progress:** the console shows an overall bar with the estimated time left, a bar for the current step, short log lines, and a summary table at the end.
- **Resume:** if a run stops (an error, or you press Ctrl+C), run the same command again and finished steps are skipped. If one clip fails, the other clips still finish.

---

## 4. Upload setup (only if you use `--upload`)
1. Go to https://console.cloud.google.com and create a project. Enable **YouTube Data API v3**.
2. Open **APIs & Services → OAuth consent screen**. Choose External and add your Google account as a **test user**.
3. Open **Credentials → Create credentials → OAuth client ID → Desktop app**, download the JSON and save it as `client_secret.json` in this folder.
4. On the first `--upload` run a browser opens so you can log in. The login is then saved to `token.json`.

Limits:
- About **6 uploads a day** on the default quota.
- Uploads stay **private** until Google approves your project in its API audit.

---

## 5. Troubleshooting
| Problem | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | Usually a company network. Ask IT for the root certificate and set `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to it, or run with `--insecure` for testing. |
| `ffmpeg is not installed` / `not found on PATH` | Install ffmpeg (step 1b), then **reopen the terminal**. |
| "Sign in to confirm you're not a bot" | `--cookies-from-browser chrome`. Be logged in to YouTube in that browser, and close the browser first. |
| No JS runtime / missing formats warning | Install Deno (step 1c), then run `pip install -U "yt-dlp[default]"`. |
| Second person is cut off | `--layout stacked` |
| Whisper is slow | `--whisper-model base`, or use an NVIDIA GPU (`--whisper-device cuda`). |
| A clip looks wrong | Look at `clip_N/frame.json` and `filter.txt`, then re-run `frame.py` or `render.py` for that clip with `--force`. |

Only clip creators who allow it, and always credit them. The uploaded description includes the credit automatically.
