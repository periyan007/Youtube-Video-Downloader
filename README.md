# 📥 YT Archive

An intuitive, high-performance Windows desktop application built with **CustomTkinter** and **yt-dlp**. Inspect public metadata, browse channel uploads in an interactive paginated grid, and download highest-fidelity video/audio streams with seamless **FFmpeg** post-processing.

---

## 📸 Overview & UI Preview

| Channel Grid & Pagination | Interactive Loading Overlay |
| :---: | :---: |
| *Paginated cards (48 items/page) with debounced search* | *Real-time scanning metrics with dynamic thumbnail art* |

> 💡 **Tip:** Replace the placeholders above with screenshots of your running app (`assets/preview_grid.png`, `assets/preview_modal.png`) to make your repository stand out!

---

## ✨ Features

- **⚡ Fast Channel Discovery:** Enters any YouTube channel URL and extracts upload lists smoothly.
- **🖼️ Rich Video Cards:** Displays video thumbnails, duration, formatted view counts, and detected resolution tags.
- **📄 Clean Pagination:** Organizes large libraries into 48 items per page with persistent sorting and filtering across pages.
- **🔍 Debounced Search:** Filters by title in real-time without freezing or rebuilding the UI on every keystroke.
- **🎮 Dynamic Scanner HUD:** Game-inspired scanning overlay tracking elapsed time, items found, scan velocity (videos/sec), and dynamic background art.
- **🎯 Smart Quality Selector:**
  - **Best Available** (Combines separate uncompressed video + audio streams into `.mkv`)
  - **4K (2160p)** / **2K (1440p)** / **FHD (1080p)** / **HD (720p)** / **SD (480p, 360p)**
  - **Audio Only** (High-bitrate `.mp3` export at 320 kbps)
- **📋 Batch Download Queue:** Queue filtered results with `Queue Visible`, execute sequentially, and retry failed downloads with skip-on-completed logic.
- **🛡️ Integrity Checks:** Validates media file creation and non-zero byte size before reporting success.
- **🗂️ Metadata Automation:** Exports BOM-encoded UTF-8 CSVs and atomic `.metadata.json` sidecar files containing chapters, tags, and container codecs.

---

## ⚙️ Quality & FFmpeg Architecture

YouTube hosts its highest-resolution video (1080p, 1440p, 4K) separately from audio tracks. 

- **With FFmpeg (Recommended):** The app pulls the cleanest uncompressed video stream and highest-bitrate audio stream, then multiplexes them into an `.mkv` file **without re-encoding the video**, ensuring 100% source fidelity.
- **Without FFmpeg:** The engine falls back to legacy progressive streams, typically capped at 720p.
- **Fallback Engine:** Includes `imageio-ffmpeg` as an automatic fallback if no system binary is detected in `PATH`.

---

## 📋 Prerequisites

- **OS:** Windows 10 / 11 (64-bit)
- **Python:** `3.10` or higher
- **FFmpeg:** Recommended system-wide (or handled automatically via fallback)

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```powershell
git clone [https://github.com/your-username/yt-archive.git](https://github.com/your-username/yt-archive.git)
cd yt-archive
