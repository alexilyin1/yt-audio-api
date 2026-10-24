# 🎧 YouTube Audio Converter API

> Developed with precision by **Alperen Sümeroğlu** — turning YouTube audio into clean, downloadable MP3s with elegance.

A high-performance Flask API that transforms any public YouTube video into a high-quality MP3 audio file — instantly, securely, and reliably. Powered by `yt-dlp` and `FFmpeg`, this API handles downloading, conversion, and secure delivery through expiring token-based access. Designed for developers, content tools, automation pipelines, and all who need clean audio from video sources — fast.

---

## 📚 Table of Contents
1. [Features](#-features)
2. [Getting Started (Mac app)](#️-getting-started-mac-app-no-technical-knowledge-needed)
3. [Installation](#-installation)
4. [Example Usage](#-example-usage)
5. [API Endpoints](#-api-endpoints)
6. [Internals (How It Works)](#️-internals-how-it-works)
7. [Tech Stack](#-tech-stack)
8. [Ideal For](#-ideal-for)
9. [Author](#-author)
10. [Weekly Rewind](#-weekly-rewind-tech-ai--entrepreneurship)
11. [License](#-license)

---

## 🌟 Features
- 🔗 Accepts any public YouTube URL
- 🎵 Downloads best audio using `yt-dlp`
- ✨ Converts audio to high-quality `.mp3` via `FFmpeg`
- 🔐 Returns a one-time secure token to download the file
- ⏱️ Tokens expire automatically (default: 5 mins)
- 🧹 Expired files are auto-deleted (clean disk usage)
- 🚀 Built for fast local or cloud deployment

---

## 🖥️ Getting Started (Mac app, no technical knowledge needed)

### 1. Install the app
1. Open the [Releases page](../../releases) and download the **Latest build** zip for your Mac:
   - **apple-silicon**: any Mac from late 2020 or newer (M1, M2, M3, M4...)
   - **intel**: older Macs. Not sure? Click the Apple menu → *About This Mac*; "Chip: Apple M…" means apple-silicon.
2. Double-click the zip to unzip it, then drag **YT Audio** into your **Applications** folder.
3. Open **YT Audio**. The first time, macOS will refuse because the app isn't signed by Apple. This is expected and only needed once:
   - **macOS 15 (Sequoia) or newer:** click *Done*, open **System Settings → Privacy & Security**, scroll down to the message about "YT Audio" and click **Open Anyway**, then confirm with your password.
   - **Older macOS:** right-click (or Control-click) the app, choose **Open**, then **Open** again.
4. Your web browser opens on the app's page (it runs only on your own computer). Paste a YouTube link and click **Convert to MP3**; the file goes to your usual Downloads folder.
5. When you're finished, click **Quit YT Audio** at the bottom of the page. Closing the browser tab doesn't stop the app.

The app is rebuilt every Monday so it keeps working when YouTube changes things. If downloads suddenly stop working, download the newest zip from the Releases page.

### 2. Optional: Spotify song suggestions
"Find similar songs" needs a free Spotify key. It takes about 3 minutes and only has to be done once. The app walks you through this on its **Set up Spotify** page; here are the same steps:

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in with your normal Spotify account (a free account works). Accept the terms if asked.
2. Click **Create app** and fill in:
   - **App name** and **App description**: anything, e.g. `My Music Helper` / `Personal use`
   - **Redirect URI:** `http://127.0.0.1:5000/callback`, then click **Add**
   - **Which API/SDKs:** tick **Web API**
3. Tick the terms box and click **Save**.
4. On your app's page, click **Settings**. Your **Client ID** is shown there; click **View client secret** to reveal the **Client secret**.
5. In YT Audio, click **Set up Spotify song recommendations**, paste both values and click **Check and save**. The app tests the keys with Spotify first and tells you if something was mistyped.

Your keys are stored only on your computer, in `~/Library/Application Support/YT Audio/.env` (readable only by you), and are never shown again. To change them, repeat step 5. The **Find similar songs** button stays greyed out until keys are saved.

> **Note:** Spotify no longer offers its own "recommendations" feature to new apps, so the suggestions come from songs that appear in the same playlists as your song (plus other songs by the same artist). Results are good but not perfect.

### 3. Importing a list of songs
Use **Import a list of songs** on the main page. Paste names (one per line, or separated by commas, tabs or semicolons) or choose a `.txt`/`.csv` file. CSV exports with *Track Name* and *Artist* columns work too. Each song gets a YouTube link and a **Download MP3** button, and **Download all as ZIP** converts the whole list and gives you one zip file (songs that can't be downloaded are skipped and listed).

### For developers
- Run from source: `pip install -r requirements.txt` then `python main.py` and open <http://localhost:5000>.
- Build the Mac app: push a tag (`git tag v1.0.0 && git push origin v1.0.0`) to publish a versioned release, or run the *Build Mac app* workflow by hand. A weekly job replaces the **Latest build** release. To build locally on a Mac: `pip install -r requirements.txt -r requirements-build.txt`, then the `pyinstaller` command in `.github/workflows/build-mac.yml`.

---

## 📦 Installation

### Requirements & Launch
Required packages are listed in [`requirements.txt`](./requirements.txt). To install all of them simply run:
```bash
pip install -r requirements.txt
```

Make sure FFmpeg is installed on your system:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

Clone and run the project:
```bash
git clone https://github.com/alperensumeroglu/yt-audio-api.git
cd yt-audio-api
python3 main.py
```

---

## 📗 Example Usage
### Step 1: Request Token
```
GET /convert?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```
Response:
```json
{
  "token": "CGIroH6G-8JDL3DllsUhM6_CfYc"
}
```

### Step 2: Download Audio
```
GET /download?token=CGIroH6G-8JDL3DllsUhM6_CfYc
```
Result: `yourfile.mp3` will download automatically 🎶

---

## 🔄 API Endpoints
| Method | Route                | Description                                                        |
|--------|----------------------|--------------------------------------------------------------------|
| GET    | `/`                  | The web page (paste a link, similar songs, import a list)          |
| GET    | `/convert`           | Accepts `?url=<video_url>`, converts and returns a token           |
| GET    | `/start`, `/progress`| Same conversion in the background: `/start?url=` returns a job id, `/progress?job=` its percent and token |
| GET    | `/download`          | Accepts `?token=<token>`, returns the audio file                   |
| GET    | `/similar`           | Accepts `?url=<video_url>`, returns 10 related songs with YouTube links |
| POST   | `/import`            | JSON `{"text": "..."}`; returns each parsed song with a YouTube link |
| GET/POST | `/spotify`, `/spotify/status`, `/spotify/save` | Spotify key setup page and checks |

--------|---------------|----------------------------------------------|
| GET    | `/`           | Accepts `?url=<video_url>`, returns token    |
| GET    | `/download`   | Accepts `?token=<token>`, returns audio file |

---

## ⚖️ Internals (How It Works)
- Downloads audio using `yt-dlp`
- Converts it to `.mp3` using FFmpeg (192kbps)
- Stores audio in `/downloads` directory
- Generates expiring token for each file
- A background daemon removes expired tokens/files

---

## 📊 Tech Stack
- Python 3.8+
- Flask 2.x
- yt-dlp
- FFmpeg

---

## 🤝 Ideal For
- Developers building podcast/audio tools
- Automation pipelines for archiving
- Students & hobbyists learning API development

---

## 👤 Author
**Alperen Sümeroğlu**  
Computer Engineer • Entrepreneur • Global Explorer 🌍  
15+ European countries explored ✈️ 

- 🔗 [LinkedIn](https://www.linkedin.com/in/alperensumeroglu/)
- 🧠 [LeetCode](https://leetcode.com/u/alperensumeroglu/)
- 🚀 [daily.dev](https://app.daily.dev/alperensumeroglu)

> “Let your code be as clean as the audio you deliver.”

---

## 🗓 Weekly Rewind: Tech, AI & Entrepreneurship

> 🚀 What does it take to grow as a Computer Engineering student, build projects, and explore global innovation?

This API is part of a bigger journey I share in **Weekly Rewind** — my real-time documentary **podcast series**, where I reflect weekly on coding breakthroughs, innovation insights, startup stories, and lessons from around the world.

### 💡 What is Weekly Rewind?
A behind-the-scenes look at real-world experiences, global insights, and hands-on learning. Each episode includes:

- 🔹 Inside My Coding & Engineering Projects
- 🔹 Startup Ideas & Entrepreneurial Lessons
- 🔹 Trends in Tech & AI
- 🔹 Innovation from 15+ Countries
- 🔹 Guest Conversations with Builders & Engineers
- 🔹 Productivity, Learning & Growth Strategies

### 🌍 Redefining Learning
> “True learning isn’t confined to tutorials — it comes from building real projects, exploring the world, and sharing the story.”

### 🎧 Listen Now:
- 🎙 [Spotify](https://open.spotify.com/show/3Lc5ofiXh93wYI8Sx7MFCK)
- ▶️ [YouTube](https://www.youtube.com/playlist?list=PLSN_hxkfsxbbd_qD87kn1SVvnR41IbuGc)
- ✍️ [Medium](https://medium.com/@alperensumeroglu)
- 💼 [LinkedIn](https://www.linkedin.com/company/weekly-rewind-tech-ai-entrepreneurship-podcast/)

> This is not just a podcast — it’s a journey of building, sharing, and scaling real-world impact.

---

## 📆 License
MIT License — free for personal and commercial use.
