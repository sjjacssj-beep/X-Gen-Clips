# 🎬 X Gen Clips

> **Autonomous Viral Short-Form (9:16) Video Generator** powered by Faster-Whisper, FFmpeg NVENC Hardware Acceleration, and Google Gemini Intelligence. Features an iOS-style Claymorphism interface with Camera Punch-Hole & Reel UI Safe-Zone auto-fitting.

[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue.svg)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)

---

## ✨ Features

- **⚡ Fast Audio-First Ingestion:** Pehle sirf 16kHz mono audio download aur transcribe hota hai. Pure 1-2 ghante ka video download kiye bina, Gemini clips select karta hai aur `yt-dlp --download-sections` se sirf required cuts extract hote hain.
- **🚀 Single-Pass FFmpeg GPU Render:** Hardware acceleration (`h264_nvenc`, `h264_qsv`, ya `h264_amf`) ke saath cut + 9:16 crop + dynamic zoom + subtitles ek hi pass mein render hote hain (zero re-encoding lag).
- **🎨 iOS-Style Claymorphism UI:** Deep Navy (`#0B132B`) & Sand (`#F4D6B0`) palette with Orange (`#D97706`) CTAs and Sky Blue accents. Floating bottom pill tab bar (Home, Library, Settings).
- **🛡️ Phone Camera & Reel UI Safe-Zone Engine:**
  - Hook Title & Watermarks safe zone (`y=340px`) me float karte hain taaki camera notch / dynamic island me na katein.
  - Subtitles lower-third sweet spot (`margin_v = 440px`) par render hote hain, Instagram Reels / YouTube Shorts ke channel name aur audio ticker ke upar.
  - Dynamic font scaling: 2-3 words per chunk auto-resizes to prevent screen clipping.
- **🔥 Trending Word-by-Word Captions:** 6 built-in themes (Hormozi Gold, MrBeast High-Contrast, Neon Cyan, Hot Pink, Electric Mint, Clean White) with active word karaoke pop and full Noto Sans Devanagari Hindi font support.
- **🔴 Direct YouTube Upload & OAuth 2.0:** 1-click resumable upload to YouTube as Private videos with automatic title, description, and hashtag injection. Includes post-upload locked-private detection and Hinglish error messages.
- **🤖 Autonomous Viral Kit:** Har clip ke saath automatically 3 Curiosity Titles, SEO Description, 8-12 Viral Hashtags, Hook Lines, aur Viral Scores generate hote hain with 1-click copy & platform tabs (YouTube Shorts, Instagram Reels, TikTok).
- **🎛️ Live Phone Mockup Preview:** In-browser interactive preview with 🛡️ Safe Area Guides toggle and A/B hook variant testing.

---

## 🚀 Quick Start (Windows 1-Click)

### 1. Installation
Clone the repository and run the setup script:
```bash
git clone https://github.com/sjjacssj-beep/X-Gen-Clips.git
cd X-Gen-Clips
setup.bat
```
`setup.bat` automatically sets up the Python virtual environment, installs all dependencies via `uv`, and checks for FFmpeg.

### 2. Launch Server
Double-click `run.bat` or run:
```bash
run.bat
```
Open **[http://localhost:9999](http://localhost:9999)** in your browser (or access via phone on your local Wi-Fi network).

### 3. Add Gemini API Key
1. Go to the **Settings** tab in the bottom bar.
2. Enter your free API key from [Google AI Studio](https://aistudio.google.com/).
3. Click **Test Connection** to verify latency and model access.

---

## 🛠️ Manual Installation (Cross-Platform)

```bash
# Clone the repository
git clone https://github.com/sjjacssj-beep/X-Gen-Clips.git
cd X-Gen-Clips

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI Server on port 9999
python -m uvicorn backend.main:app --host 0.0.0.0 --port 9999
```

---

## 📁 Project Architecture

```
X-Gen-Clips/
├── backend/
│   ├── main.py              # FastAPI server, endpoints & SSE broadcast
│   ├── pipeline.py          # Fast audio-first clipping & FFmpeg NVENC engine
│   ├── gemini_engine.py     # Gemini viral detection & metadata generation
│   ├── subtitle_engine.py   # ASS word-by-word karaoke & camera safe-zone engine
│   ├── queue_manager.py     # Background job queue & history store
│   └── system_diag.py       # Hardware, FFmpeg, yt-dlp & GPU diagnostics
├── frontend/
│   ├── index.html           # iOS 3-view claymorphic single-page app
│   ├── css/
│   │   ├── claymorphism.css # Deep Navy & Sand claymorphism variables & 3D cards
│   │   └── components.css   # iOS bottom floating pill tab bar & phone mockup
│   └── js/
│       ├── app.js           # View routing, SSE live progress & clip rendering
│       ├── player.js        # Phone mockup video player & hook selector
│       └── social.js        # Multi-platform social metadata & 1-click clipboard
├── sounds/
│   ├── pop.wav              # Clip complete chime
│   └── whoosh.wav           # Transition effect
├── outputs/                 # Exported 9:16 clips and subtitle files (.gitignored)
├── setup.bat                # 1-click Windows installer
├── run.bat                  # 1-click Windows launcher
├── requirements.txt         # Python dependencies
├── .env.example             # Example environment file
└── README.md                # Project documentation
```

---

## 📄 License

## 🔴 YouTube Direct Upload Setup (OAuth 2.0 Desktop)

X Gen Clips me direct YouTube upload feature built-in hai. Ye feature official Google YouTube Data API v3 aur OAuth 2.0 Desktop Flow use karta hai:

### Setup Steps:
1. **Google Cloud Console:**
   - [Google Cloud Console](https://console.cloud.google.com/) me jayein aur ek project banayein (`xgenclips`).
   - **APIs & Services > Library** me jaakar **YouTube Data API v3** enable karein.
   - **OAuth consent screen** me Publishing status **Testing** rakhein, aur apna Gmail ID **Test users** me add karein.
   - **Credentials > Create Credentials > OAuth client ID** me application type **Desktop app** choose karein.
   - Download ki gayi JSON file ko `secrets/client_secret.json` naam se project ke `secrets/` folder me rakhein (Note: Ye folder `.gitignore` me secure hai aur git me commit nahi hota).

2. **App me YouTube Jodo:**
   - App open karein (`http://localhost:9999`).
   - **Settings** tab me jayein, wahan **YouTube Direct Upload & OAuth** card dikhega.
   - **🔗 YouTube Jodo** button dabayein.
   - Aapke default browser me Google authorization window khulegi.
   - Apna Test User wala Gmail select karein aur permissions allow karein.
   - Browser me authorization successful hone par app me status **🟢 Connected** ho jayega.

3. **Clips Upload Karna:**
   - Kisi bhi clip card par **🔴 YouTube pe bhejo** dabayein ya sabhi clips ko ek saath upload karne ke liye **🚀 Sab YouTube pe bhejo** dabayein.
   - Video automatically **Private** mode me upload hogi aur AI-generated Title, Description, aur Hashtags YouTube par inject ho jayenge.
   - Upload hote hi direct YouTube video link (`https://youtu.be/...`) mil jayega!

---

## License

MIT License. Free to use for personal and commercial projects.
