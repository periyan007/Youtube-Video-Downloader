import os
import io
import re
import csv
import json
import sys
import threading
import datetime
import time
import shutil
from typing import Any, cast
from urllib import request, error
from urllib.parse import urlsplit, urlunsplit

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency when testing pure logic
    Image = None

GUI_RUNTIME_AVAILABLE = False

try:
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
    GUI_RUNTIME_AVAILABLE = True
except ImportError:  # pragma: no cover - GUI dependency is optional for headless validation
    ctk = None
    filedialog = None
    messagebox = None

try:
    import yt_dlp
except ImportError:  # pragma: no cover - optional dependency when testing core logic
    yt_dlp = None


class _TkStub:
    """Fallback container for headless environments and tests."""

    class CTkFrame:
        pass

    class CTkLabel:
        pass

    class CTkButton:
        pass

    class CTkEntry:
        pass

    class CTkProgressBar:
        pass

    class CTkScrollableFrame:
        pass

    class CTk:
        pass

    class CTkToplevel:
        pass

    class CTkImage:
        pass

    @staticmethod
    def set_appearance_mode(*_args, **_kwargs):
        return None

    @staticmethod
    def set_default_color_theme(*_args, **_kwargs):
        return None


if ctk is None:
    ctk = _TkStub()

if ctk is not None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("dark-blue")


def require_gui_dependencies():
    """Fail with a clear message when the desktop runtime dependencies are missing."""
    missing = []
    if not GUI_RUNTIME_AVAILABLE:
        missing.append("customtkinter")
    if Image is None:
        missing.append("pillow")
    if yt_dlp is None:
        missing.append("yt-dlp")
    if missing:
        raise RuntimeError(
            "Missing required runtime dependencies: "
            + ", ".join(missing)
            + ". Install them with: python -m pip install -r requirements.txt"
        )

APP_BG = ("#F2F6FC", "#101827")
APP_PANEL = ("#FFFFFF", "#182437")
APP_CARD = ("#FFFFFF", "#1D2B41")
APP_TEXT = ("#17324F", "#E6EDF7")
APP_MUTED = ("#647B95", "#A8B7CC")
APP_ACCENT = ("#2563EB", "#3569D4")
APP_ACCENT_DARK = ("#1D4ED8", "#2857B8")
APP_BORDER = ("#D8E3F0", "#34445C")
APP_GREEN = ("#16804A", "#1F754A")
APP_GREEN_DARK = ("#12683C", "#62CC91")
APP_SURFACE_ALT = ("#EAF1FA", "#26364D")
APP_HOVER = ("#DCE8F8", "#31445F")
APP_PROGRESS_TRACK = ("#DCE7F4", "#34445C")
APP_DANGER = ("#A33A3A", "#A83939")
APP_DANGER_DARK = ("#7D2929", "#862C2C")
APP_ON_ACCENT = ("#FFFFFF", "#FFFFFF")

CATEGORY_KEYWORDS = {
    "Music": ("music", "song", "album", "dj", "beats", "sing", "cover", "playlist", "rap", "rock"),
    "Gaming": ("game", "gaming", "minecraft", "fortnite", "valorant", "roblox", "stream", "playthrough", "fps"),
    "Learning": ("tutorial", "learn", "course", "guide", "study", "education", "data science", "how to", "training"),
    "Tech": ("python", "programming", "coding", "developer", "ai", "software", "tech", "linux", "server", "machine learning"),
    "News": ("news", "update", "breaking", "report", "world", "politics", "economy", "daily"),
    "Lifestyle": ("travel", "fitness", "cooking", "home", "beauty", "vlog", "daily", "lifestyle"),
    "Entertainment": ("funny", "comedy", "movie", "series", "reaction", "viral", "challenge", "meme"),
}

RESOLUTION_MAP = {
    "2160p (4K)": 2160,
    "1440p (2K)": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

VIDEO_GRID_BATCH_SIZE = 48


def get_ffmpeg_path():
    """Detect the system FFmpeg binary or fall back to imageio-ffmpeg."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def build_download_format(resolution_choice: str) -> str:
    """Return the yt-dlp format string for a given user selection."""
    if resolution_choice == "Audio Only (.mp3)":
        return "bestaudio/best"

    if resolution_choice == "Best Available":
        return "bestvideo+bestaudio/bestvideo/best"

    target_height = RESOLUTION_MAP.get(resolution_choice)
    if target_height:
        return f"bestvideo[height<={target_height}]+bestaudio/best[height<={target_height}]/best"

    return "bestvideo+bestaudio/best"


def build_download_options(video_url, resolution_choice, save_dir, progress_hook, postprocessor_hook=None):
    """Build one source-preserving yt-dlp configuration for every download path."""
    ffmpeg_exe = get_ffmpeg_path()
    format_selector = build_download_format(resolution_choice)

    if resolution_choice != "Audio Only (.mp3)" and not ffmpeg_exe:
        target_height = RESOLUTION_MAP.get(resolution_choice)
        # Without FFmpeg, select one complete progressive stream so a video is
        # still downloaded instead of leaving only the metadata sidecar.
        format_selector = f"best[height<={target_height}]/best" if target_height else "best"

    options = {
        "format": format_selector,
        "outtmpl": os.path.join(os.path.abspath(save_dir), "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "overwrites": False,
        "format_sort": ["res:desc", "fps:desc", "hdr:12", "vcodec:desc", "br:desc", "size:desc"],
        "writeinfojson": True,
        "clean_infojson": False,
        "embedmetadata": True,
    }

    if postprocessor_hook:
        options["postprocessor_hooks"] = [postprocessor_hook]

    if resolution_choice != "Audio Only (.mp3)" and ffmpeg_exe:
        # MKV avoids forcing a codec/container conversion when YouTube serves WebM.
        options["merge_output_format"] = "mkv"

    if ffmpeg_exe:
        options["ffmpeg_location"] = ffmpeg_exe

    if resolution_choice == "Audio Only (.mp3)":
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }]

    return options


def download_video_stream(video_url, resolution_choice, save_dir, progress_hook):
    save_dir = os.path.abspath(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    ydl_opts = build_download_options(video_url, resolution_choice, save_dir, progress_hook)

    with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
        ydl.download([video_url])


def download_video_with_metadata(video_info, video_url, resolution, save_dir, progress_hook, postprocessor_hook=None, cancel_event=None, before_metadata_hook=None):
    """Download one video, verify its media file, and write its metadata sidecar."""
    save_dir = os.path.abspath(save_dir)
    os.makedirs(save_dir, exist_ok=True)
    output_paths = set()

    def track_progress(data):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Download cancelled by user")
        filename = data.get("filename")
        if filename:
            output_paths.add(os.path.abspath(filename))
        if progress_hook:
            progress_hook(data)

    def track_postprocessor(data):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Download cancelled by user")
        filepath = data.get("info_dict", {}).get("filepath") or data.get("filepath")
        if filepath:
            output_paths.add(os.path.abspath(filepath))
        if postprocessor_hook:
            postprocessor_hook(data)

    ydl_opts = build_download_options(
        video_url,
        resolution,
        save_dir,
        track_progress,
        track_postprocessor,
    )
    with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
        ydl.download([video_url])

    completed_files = [
        path for path in output_paths
        if os.path.isfile(path) and os.path.getsize(path) > 0 and not path.endswith(".part")
    ]
    if not completed_files:
        raise RuntimeError(
            "yt-dlp finished without producing a media file. "
            "Check FFmpeg, disk space, and the video access permissions."
        )

    media_path = max(completed_files, key=os.path.getmtime)
    if before_metadata_hook:
        before_metadata_hook()
    write_metadata_sidecar(video_info, media_path, resolution)
    return media_path


def sanitize_channel_url(url: str) -> str:
    """Ensure the URL targets the clean uploads tab directly."""
    url = url.strip()
    if not url:
        return url

    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    lowered_path = path.lower()
    if lowered_path == "/watch" or lowered_path.startswith(("/shorts/", "/live/")) or parsed.netloc.lower() in {"youtu.be", "www.youtu.be"}:
        return url
    if path.endswith("/videos"):
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/videos", parsed.query, parsed.fragment))


def format_duration(seconds):
    if not seconds:
        return "N/A"
    try:
        return str(datetime.timedelta(seconds=int(seconds)))
    except (TypeError, ValueError):
        return "N/A"


def format_views(count):
    if count in (None, 0):
        return "N/A"
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "N/A"

    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M views"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K views"
    return f"{count} views"


def format_date(date_str):
    if not date_str or len(date_str) != 8:
        return "N/A"
    if not re.fullmatch(r"\d{8}", date_str):
        return "N/A"
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"


def sanitize_filename(value, fallback="video"):
    """Return a Windows-safe filename component without changing its meaning."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    if not cleaned:
        return fallback
    if cleaned.upper() in {"CON", "PRN", "AUX", "NUL"}:
        return f"_{cleaned}_"
    return cleaned[:180]


def normalize_video_metadata(video_info):
    """Keep stable, public metadata fields for JSON and CSV exports."""
    if not isinstance(video_info, dict):
        return {}

    return {
        "id": video_info.get("id"),
        "title": video_info.get("title"),
        "url": video_info.get("webpage_url") or video_info.get("url"),
        "description": video_info.get("description"),
        "channel": video_info.get("channel") or video_info.get("uploader"),
        "channel_id": video_info.get("channel_id") or video_info.get("uploader_id"),
        "channel_url": video_info.get("channel_url") or video_info.get("uploader_url"),
        "upload_date": video_info.get("upload_date"),
        "timestamp": video_info.get("timestamp"),
        "duration": video_info.get("duration"),
        "view_count": video_info.get("view_count"),
        "like_count": video_info.get("like_count"),
        "comment_count": video_info.get("comment_count"),
        "categories": video_info.get("categories") or [],
        "tags": video_info.get("tags") or [],
        "language": video_info.get("language"),
        "thumbnail": video_info.get("thumbnail"),
        "location": video_info.get("location") or video_info.get("release_location"),
        "chapters": video_info.get("chapters") or [],
        "width": video_info.get("width"),
        "height": video_info.get("height"),
        "fps": video_info.get("fps"),
        "vcodec": video_info.get("vcodec"),
        "acodec": video_info.get("acodec"),
        "ext": video_info.get("ext"),
    }


def write_metadata_sidecar(video_info, media_path, selected_format):
    """Write normalized metadata only after a media file has completed."""
    media_path = os.path.abspath(media_path)
    sidecar_path = os.path.splitext(media_path)[0] + ".metadata.json"
    payload = {
        "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "selected_format": selected_format,
        "media_path": media_path,
        "metadata": normalize_video_metadata(video_info),
    }
    temporary_path = f"{sidecar_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as sidecar_file:
        json.dump(payload, sidecar_file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, sidecar_path)
    return sidecar_path


def export_videos_csv(videos, destination):
    """Export stable channel metadata columns with safe CSV escaping."""
    fields = ["id", "title", "url", "channel_name", "channel_handle", "upload_date", "duration", "view_count", "real_quality", "location"]
    with open(destination, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for video in videos:
            writer.writerow({field: video.get(field, "") for field in fields})
    return destination


def get_real_video_quality(video_info):
    """Return the highest real resolution available from YouTube formats."""
    if not isinstance(video_info, dict):
        return "Quality unavailable"

    formats = video_info.get("formats") or []
    candidates = []
    for fmt in formats:
        if fmt.get("vcodec") not in (None, "none"):
            height = fmt.get("height")
            fps = fmt.get("fps") or 0
            if height:
                candidates.append((height, fps, fmt.get("ext") or "mp4"))

    if not candidates:
        return "Audio only"

    height, fps, ext = max(candidates, key=lambda item: (item[0], item[1]))
    label = f"{height}p"
    if fps:
        label += f" • {int(fps)}fps"
    if ext:
        label += f" • {ext.upper()}"
    return label


def get_video_location(video_info):
    if not isinstance(video_info, dict):
        return "Not publicly exposed"
    for key in ("location", "release_location", "geo"):
        value = video_info.get(key)
        if value:
            return str(value)
    return "Not publicly exposed"


def get_channel_identity(video_info):
    if not isinstance(video_info, dict):
        return "Unknown channel", "Unavailable", "Unavailable"

    channel_name = video_info.get("channel") or video_info.get("uploader") or "Unknown channel"
    channel_handle = video_info.get("channel_handle") or video_info.get("uploader_id") or "Unavailable"
    user_email = "Hidden / not exposed by YouTube"

    return channel_name, channel_handle, user_email


def infer_video_category(title: str) -> str:
    """Return a high-level category for smart filtering and browsing."""
    text = (title or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "General"


def build_video_summary(entry):
    """Create a lightweight channel-grid record without doing a full fetch for every video."""
    if not isinstance(entry, dict):
        return {}

    video_id = entry.get("id") or "unknown-video"
    title = entry.get("title") or "Unknown Title"
    thumbnail = entry.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

    return {
        "id": video_id,
        "title": title,
        "url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
        "duration": entry.get("duration"),
        "view_count": entry.get("view_count"),
        "upload_date": entry.get("upload_date"),
        "thumbnail": thumbnail,
        "channel_name": entry.get("channel") or entry.get("uploader") or "Unknown channel",
        "channel_handle": entry.get("channel_handle") or entry.get("uploader_id") or "Unavailable",
        "user_email": "Hidden / not exposed by YouTube",
        "real_quality": get_real_video_quality(entry) if entry.get("formats") else "Quality unavailable",
        "location": get_video_location(entry),
    }


def get_video_grid_batch(videos, start, batch_size=VIDEO_GRID_BATCH_SIZE):
    end = min(start + batch_size, len(videos))
    return videos[start:end], end


def get_video_page(videos, page_index, page_size=VIDEO_GRID_BATCH_SIZE):
    """Return one zero-based page and the total number of pages."""
    page_count = max(1, (len(videos) + page_size - 1) // page_size)
    page_index = min(max(page_index, 0), page_count - 1)
    start = page_index * page_size
    return videos[start:start + page_size], page_count, start


def build_queue_item(video_data, resolution="Best Available"):
    """Keep enough video data in a queue entry to start it later."""
    return {
        "id": video_data.get("id", "unknown-video"),
        "title": video_data.get("title", "Untitled Video"),
        "url": video_data.get("url"),
        "video_data": dict(video_data),
        "resolution": resolution,
        "status": "Queued",
    }


def get_pending_queue_items(queue):
    """Return queued and retryable items without restarting completed downloads."""
    retryable_statuses = {"Queued", "Failed", "Cancelled"}
    return [item for item in queue if item.get("status") in retryable_statuses]


class VideoCard(ctk.CTkFrame):
    """Grid item representing a single video."""

    def __init__(self, master, video_data, on_click_callback, **kwargs):
        super().__init__(master, corner_radius=14, fg_color=APP_CARD, border_width=1, border_color=APP_BORDER, **kwargs)
        self.video_data = video_data
        self.on_click = on_click_callback
        self.thumbnail_image = None

        self.thumb_label = ctk.CTkLabel(
            self,
            text="Loading preview...",
            width=230,
            height=130,
            fg_color=APP_SURFACE_ALT,
            text_color=APP_MUTED,
            corner_radius=10,
            font=("Segoe UI", 10, "bold"),
        )
        self.thumb_label.pack(padx=8, pady=(8, 4), fill="x")

        raw_title = video_data.get("title") or "Untitled Video"
        short_title = raw_title[:45] + "..." if len(raw_title) > 48 else raw_title
        self.title_label = ctk.CTkLabel(
            self,
            text=short_title,
            font=("Segoe UI", 12, "bold"),
            wraplength=225,
            justify="left",
            anchor="w",
            text_color=APP_TEXT,
        )
        self.title_label.pack(padx=8, pady=(2, 2), fill="x")

        meta_frame = ctk.CTkFrame(self, fg_color="transparent")
        meta_frame.pack(fill="x", padx=8, pady=(0, 6))

        ctk.CTkLabel(meta_frame, text=f"⏱ {format_duration(video_data.get('duration'))}", font=("Segoe UI", 10, "bold"), text_color=APP_ACCENT).pack(side="left")
        ctk.CTkLabel(meta_frame, text=f"• {format_views(video_data.get('view_count'))}", font=("Segoe UI", 10), text_color=APP_MUTED).pack(side="left", padx=5)

        quality_text = video_data.get("real_quality") or "Quality unavailable"
        self.quality_label = ctk.CTkLabel(
            self,
            text=quality_text,
            font=("Segoe UI", 9, "bold"),
            text_color=APP_GREEN_DARK,
            anchor="w",
        )
        self.quality_label.pack(fill="x", padx=8, pady=(0, 6))

        self.action_btn = ctk.CTkButton(
            self,
            text="Download",
            font=("Segoe UI", 11, "bold"),
            height=32,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_ON_ACCENT,
            corner_radius=10,
            command=lambda: self.on_click(self.video_data),
        )
        self.action_btn.pack(fill="x", padx=8, pady=(0, 8))

        threading.Thread(target=self._fetch_thumbnail, daemon=True).start()

    def _fetch_thumbnail(self):
        vid_id = self.video_data.get("id")
        thumb_url = self.video_data.get("thumbnail") or (f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg" if vid_id else None)

        if not thumb_url:
            self.after(0, lambda: self.thumb_label.configure(text="No Thumbnail"))
            return

        try:
            req = request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    image_data = resp.read()
                    pil_img = Image.open(io.BytesIO(image_data))
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(230, 130))
                    def apply_thumbnail():
                        if self.winfo_exists():
                            self.thumbnail_image = ctk_img
                            self.thumb_label.configure(image=self.thumbnail_image, text="")

                    self.after(0, apply_thumbnail)
                    return
        except (error.URLError, error.HTTPError, OSError, ValueError):
            pass

        self.after(0, lambda: self.thumb_label.configure(text="No Thumbnail"))


class GameLoadingOverlay(ctk.CTkFrame):
    """Animated in-window loading layer for startup and channel extraction."""

    def __init__(self, master):
        super().__init__(master, fg_color=APP_BG, corner_radius=0)
        self.background_image = None

        self.background_label = ctk.CTkLabel(self, text="", fg_color=APP_BG, corner_radius=0)
        self.background_label.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.background_label.lower()

        ctk.CTkLabel(
            self,
            text="YT ARCHIVE",
            font=("Segoe UI", 15, "bold"),
            text_color=APP_ACCENT,
        ).pack(pady=(170, 8))
        ctk.CTkLabel(
            self,
            text="SOURCE LOADER",
            font=("Segoe UI", 34, "bold"),
            text_color=APP_TEXT,
        ).pack(pady=(0, 10))

        self.status_label = ctk.CTkLabel(
            self,
            text="Preparing downloader...",
            font=("Segoe UI", 12),
            text_color=APP_MUTED,
        )
        self.status_label.pack(pady=(0, 18))

        self.progress_bar = ctk.CTkProgressBar(
            self,
            width=420,
            height=10,
            corner_radius=5,
            fg_color=APP_PROGRESS_TRACK,
            progress_color=APP_ACCENT,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack()

        self.detail_label = ctk.CTkLabel(
            self,
            text="INITIALIZING",
            font=("Segoe UI", 10, "bold"),
            text_color=APP_MUTED,
        )
        self.detail_label.pack(pady=(12, 0))

    def set_background(self, pil_image):
        width = max(self.winfo_width(), 920)
        height = max(self.winfo_height(), 600)
        self.background_image = ctk.CTkImage(
            light_image=pil_image,
            dark_image=pil_image,
            size=(width, height),
        )
        self.background_label.configure(image=self.background_image, fg_color=APP_BG)
        self.background_label.lower()

        if self.winfo_width() <= 1 or self.winfo_height() <= 1:
            self.after_idle(lambda: self.set_background(pil_image))

    def update_progress(self, progress, status, detail=None):
        self.progress_bar.set(max(0, min(float(progress), 1)))
        self.status_label.configure(text=status)
        if detail is not None:
            self.detail_label.configure(text=detail)


class ChannelGridApp(ctk.CTk):
    def __init__(self):
        require_gui_dependencies()
        super().__init__()

        self.configure(fg_color=APP_BG)
        self.title("Universal YouTube Channel Extractor & Downloader")
        self.geometry("1180x800")
        self.minsize(920, 600)

        self.videos = []
        self.filtered_videos = []
        self.save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.loading_overlay = None
        self._intro_pulse = 0
        self.theme_mode = "light"
        self.queue = []
        self.queue_active = False
        self.download_active = False
        self.queue_cancel_event = threading.Event()
        self.sort_mode = "Newest"
        self.fetch_active = False
        self.fetch_started_at = 0.0
        self._filter_after_id = None
        self._grid_videos = []
        self._grid_page_index = 0

        self._build_ui()
        self.after(80, self._show_startup_loading)

    def _show_startup_loading(self):
        if self.loading_overlay is not None:
            return
        self.loading_overlay = GameLoadingOverlay(self)
        self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.loading_overlay.lift()
        self._intro_pulse = 0
        self._animate_startup_loading()

    def _animate_startup_loading(self):
        if self.loading_overlay is None:
            return
        self._intro_pulse += 1
        progress = min(self._intro_pulse / 18, 0.92)
        self.loading_overlay.update_progress(progress, "Preparing downloader...", "LOADING COMPONENTS")
        if self._intro_pulse < 18:
            self.after(55, self._animate_startup_loading)
        else:
            self.after(350, self._hide_loading_overlay)

    def _show_channel_loading(self):
        if self.loading_overlay is None:
            self.loading_overlay = GameLoadingOverlay(self)
            self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.loading_overlay.lift()
        self.loading_overlay.update_progress(0.02, "Connecting to channel...", "NETWORK REQUEST")

    def _update_channel_loading(self, progress, status, detail):
        def update():
            if self.loading_overlay is not None:
                self.loading_overlay.update_progress(progress, status, detail)

        self.after(0, update)

    def _update_channel_loading_background(self, thumbnail_url, video_id=None):
        thumbnail_url = thumbnail_url or (
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None
        )
        if not thumbnail_url:
            return

        def load_thumbnail():
            try:
                req = request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                with request.urlopen(req, timeout=5) as response:
                    image_data = response.read()
                pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
            except (error.URLError, error.HTTPError, OSError, ValueError):
                return

            def apply_thumbnail():
                if self.loading_overlay is not None:
                    self.loading_overlay.set_background(pil_image)

            self.after(0, apply_thumbnail)

        threading.Thread(target=load_thumbnail, daemon=True).start()

    def _hide_loading_overlay(self):
        if self.loading_overlay is not None:
            self.loading_overlay.destroy()
            self.loading_overlay = None

    def _build_ui(self):
        header_card = ctk.CTkFrame(self, fg_color=APP_PANEL, corner_radius=18, border_width=1, border_color=APP_BORDER)
        header_card.pack(fill="x", padx=18, pady=(16, 10))

        ctk.CTkLabel(header_card, text="YT ARCHIVE - Premium Channel Scanner", font=("Segoe UI", 16, "bold"), text_color=APP_TEXT).pack(side="left", padx=(18, 8), pady=12)

        self.theme_btn = ctk.CTkButton(
            header_card,
            text="🌙 Dark mode",
            width=136,
            height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_ON_ACCENT,
            corner_radius=12,
            command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", padx=(0, 18), pady=10)

        top_bar = ctk.CTkFrame(self, fg_color=APP_PANEL, corner_radius=18, border_width=1, border_color=APP_BORDER)
        top_bar.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkLabel(top_bar, text="Channel URL", font=("Segoe UI", 12, "bold"), text_color=APP_TEXT).pack(side="left", padx=(16, 8), pady=12)
        self.url_entry = ctk.CTkEntry(
            top_bar,
            placeholder_text="https://www.youtube.com/@ChannelName",
            width=420,
            height=38,
            fg_color=APP_CARD,
            border_color=APP_BORDER,
            text_color=APP_TEXT,
        )
        self.url_entry.pack(side="left", padx=6, pady=10, fill="x", expand=True)

        self.fetch_btn = ctk.CTkButton(
            top_bar,
            text="Fetch All Uploads",
            width=150,
            height=40,
            font=("Segoe UI", 11, "bold"),
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_ON_ACCENT,
            corner_radius=12,
            command=self.start_fetch,
        )
        self.fetch_btn.pack(side="left", padx=(8, 16), pady=10)

        self.refresh_btn = ctk.CTkButton(
            top_bar,
            text="Refresh",
            width=100,
            height=38,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self.start_fetch,
        )
        self.refresh_btn.pack(side="left", pady=10)

        link_panel = ctk.CTkFrame(self, fg_color=APP_PANEL, corner_radius=18, border_width=1, border_color=APP_BORDER)
        link_panel.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(link_panel, text="Download by link", font=("Segoe UI", 12, "bold"), text_color=APP_TEXT).pack(side="left", padx=(16, 8), pady=10)
        self.video_link_entry = ctk.CTkEntry(
            link_panel,
            placeholder_text="Paste a video URL",
            height=36,
            fg_color=APP_CARD,
            border_color=APP_BORDER,
            text_color=APP_TEXT,
        )
        self.video_link_entry.pack(side="left", padx=6, pady=8, fill="x", expand=True)
        self.direct_download_btn = ctk.CTkButton(
            link_panel,
            text="Choose Quality",
            width=145,
            height=38,
            font=("Segoe UI", 11, "bold"),
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_ON_ACCENT,
            corner_radius=12,
            command=self._start_link_download,
        )
        self.direct_download_btn.pack(side="left", padx=(8, 16), pady=8)

        stats_bar = ctk.CTkFrame(self, fg_color="transparent")
        stats_bar.pack(fill="x", padx=18, pady=(0, 10))

        self.stats_cards = {}
        for name, value, accent in [
            ("Videos", "0", APP_ACCENT),
            ("Queued", "0", APP_GREEN),
            ("Folder", self.save_dir, APP_ACCENT_DARK),
        ]:
            card = ctk.CTkFrame(stats_bar, fg_color=APP_PANEL, corner_radius=14, border_width=1, border_color=APP_BORDER)
            card.pack(side="left", fill="y", padx=(0, 10), expand=True)
            ctk.CTkLabel(card, text=name, font=("Segoe UI", 10, "bold"), text_color=APP_MUTED).pack(anchor="w", padx=14, pady=(12, 0))
            label = ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 18, "bold"), text_color=accent, wraplength=220, justify="left")
            label.pack(anchor="w", padx=14, pady=(0, 12))
            self.stats_cards[name] = label

        self.category_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.category_frame.pack(fill="x", padx=18, pady=(0, 8))
        self.category_buttons = {}
        self.active_category = "All"
        for category in ["All", "Music", "Learning", "Tech", "Gaming", "News", "Entertainment", "Lifestyle"]:
            button = ctk.CTkButton(
                self.category_frame,
                text=category,
                width=90,
                height=30,
                fg_color=APP_SURFACE_ALT if category != "All" else APP_ACCENT,
                hover_color=APP_HOVER,
                text_color=APP_TEXT if category != "All" else APP_ON_ACCENT,
                border_color=APP_BORDER,
                border_width=1,
                corner_radius=14,
                font=("Segoe UI", 10, "bold"),
                command=lambda cat=category: self._set_category_filter(cat),
            )
            button.pack(side="left", padx=(0, 8))
            self.category_buttons[category] = button

        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.pack(fill="x", padx=18, pady=(0, 8))

        self.sort_combo = ctk.CTkComboBox(
            action_row,
            values=["Newest", "Oldest", "Title A-Z", "Title Z-A"],
            width=150,
            height=32,
            fg_color=APP_CARD,
            border_color=APP_BORDER,
            dropdown_fg_color=APP_CARD,
            text_color=APP_TEXT,
            dropdown_text_color=APP_TEXT,
        )
        self.sort_combo.set(self.sort_mode)
        self.sort_combo.pack(side="left")
        self.sort_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_sorting())

        self.queue_visible_btn = ctk.CTkButton(
            action_row,
            text="Queue Visible",
            width=120,
            height=32,
            fg_color=APP_GREEN,
            hover_color=APP_GREEN_DARK,
            text_color=APP_ON_ACCENT,
            font=("Segoe UI", 10, "bold"),
            corner_radius=10,
            command=self._queue_visible_videos,
        )
        self.queue_visible_btn.pack(side="left", padx=(8, 0))

        self.clear_queue_btn = ctk.CTkButton(
            action_row,
            text="Clear Queue",
            width=120,
            height=32,
            fg_color=APP_DANGER,
            hover_color=APP_DANGER_DARK,
            corner_radius=10,
            command=self._clear_queue,
        )
        self.clear_queue_btn.pack(side="left", padx=(8, 0))

        self.start_queue_btn = ctk.CTkButton(
            action_row,
            text="Start Queue",
            width=115,
            height=32,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_ON_ACCENT,
            font=("Segoe UI", 10, "bold"),
            corner_radius=10,
            command=self._start_queue_downloads,
        )
        self.start_queue_btn.pack(side="left", padx=(8, 0))

        self.stop_queue_btn = ctk.CTkButton(
            action_row,
            text="Stop Queue",
            width=105,
            height=32,
            fg_color=APP_DANGER,
            hover_color=APP_DANGER_DARK,
            text_color=APP_ON_ACCENT,
            font=("Segoe UI", 10, "bold"),
            corner_radius=10,
            command=self._stop_queue_downloads,
            state="disabled",
        )
        self.stop_queue_btn.pack(side="left", padx=(8, 0))

        ctrl_bar = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_bar.pack(fill="x", padx=18, pady=(0, 10))

        self.search_entry = ctk.CTkEntry(
            ctrl_bar,
            placeholder_text="🔍 Filter videos by title...",
            width=330,
            height=36,
            fg_color=APP_CARD,
            border_color=APP_BORDER,
            text_color=APP_TEXT,
        )
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self._filter_videos)

        self.clear_filters_btn = ctk.CTkButton(
            ctrl_bar,
            text="Clear Filters",
            width=105,
            height=36,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._clear_filters,
        )
        self.clear_filters_btn.pack(side="left", padx=(0, 10))

        self.counter_label = ctk.CTkLabel(ctrl_bar, text="0 videos loaded", font=("Segoe UI", 11), text_color=APP_MUTED)
        self.counter_label.pack(side="left")

        self.choose_folder_btn = ctk.CTkButton(
            ctrl_bar,
            text="Choose Folder",
            width=130,
            height=36,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._choose_directory,
        )
        self.choose_folder_btn.pack(side="right")

        self.open_folder_btn = ctk.CTkButton(
            ctrl_bar,
            text="📁 Open Folder",
            width=150,
            height=36,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._open_download_folder,
        )
        self.open_folder_btn.pack(side="right")

        self.copy_link_btn = ctk.CTkButton(
            ctrl_bar,
            text="Copy Link",
            width=110,
            height=36,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._copy_selected_link,
        )
        self.copy_link_btn.pack(side="right", padx=(0, 8))

        self.export_btn = ctk.CTkButton(
            ctrl_bar,
            text="Export CSV",
            width=110,
            height=36,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._export_metadata_csv,
        )
        self.export_btn.pack(side="right", padx=(0, 8))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        self.grid_container = ctk.CTkScrollableFrame(content, label_text="Channel Uploads", fg_color=APP_BG, label_fg_color=APP_PANEL, label_text_color=APP_TEXT)
        self.grid_container.pack(side="left", fill="both", expand=True, padx=(0, 8))

        sidebar = ctk.CTkFrame(content, fg_color="transparent")
        sidebar.pack(side="right", fill="y")

        self.queue_panel = ctk.CTkFrame(sidebar, fg_color=APP_PANEL, corner_radius=16, border_width=1, border_color=APP_BORDER)
        self.queue_panel.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(self.queue_panel, text="Download Queue", font=("Segoe UI", 12, "bold"), text_color=APP_TEXT).pack(anchor="w", padx=12, pady=(12, 8))
        self.queue_container = ctk.CTkScrollableFrame(self.queue_panel, fg_color=APP_PANEL)
        self.queue_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.pagination_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.pagination_bar.pack(fill="x", padx=18, pady=(0, 6))
        self.previous_page_btn = ctk.CTkButton(
            self.pagination_bar,
            text="← Previous",
            width=120,
            height=32,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._show_previous_page,
        )
        self.previous_page_btn.pack(side="left")
        self.page_label = ctk.CTkLabel(
            self.pagination_bar,
            text="Page 1 of 1",
            font=("Segoe UI", 10, "bold"),
            text_color=APP_MUTED,
        )
        self.page_label.pack(side="left", expand=True)
        self.next_page_btn = ctk.CTkButton(
            self.pagination_bar,
            text="Next →",
            width=120,
            height=32,
            fg_color=APP_SURFACE_ALT,
            hover_color=APP_HOVER,
            text_color=APP_TEXT,
            border_color=APP_BORDER,
            border_width=1,
            corner_radius=10,
            command=self._show_next_page,
        )
        self.next_page_btn.pack(side="right")

        self.status_bar = ctk.CTkLabel(self, text="Ready", anchor="w", font=("Segoe UI", 11, "bold"), text_color=APP_MUTED)
        self.status_bar.pack(fill="x", padx=20, pady=(4, 12))

        self._update_dashboard_stats()

    def _clear_filters(self):
        self.search_entry.delete(0, "end")
        self.active_category = "All"
        for name, button in self.category_buttons.items():
            button.configure(
                fg_color=APP_ACCENT if name == "All" else APP_SURFACE_ALT,
                text_color=APP_ON_ACCENT if name == "All" else APP_TEXT,
            )
        self._apply_category_filter()
        self.status_bar.configure(text="Search and category filters cleared.")

    def _choose_directory(self):
        if self.queue_active:
            self.status_bar.configure(text="Stop the active queue before changing its output folder.")
            return
        chosen = filedialog.askdirectory(initialdir=self.save_dir)
        if chosen:
            self.save_dir = chosen
            self._update_dashboard_stats()
            messagebox.showinfo("Directory Updated", f"Videos will download to:\n{self.save_dir}")

    def _toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        mode = "light" if self.theme_mode == "light" else "dark"
        ctk.set_appearance_mode(mode)
        self.theme_btn.configure(text="☀️ Light mode" if mode == "dark" else "🌙 Dark mode")
        self.status_bar.configure(text=f"Theme switched to {mode.title()} mode.")

    def _open_download_folder(self):
        os.makedirs(self.save_dir, exist_ok=True)
        try:
            if hasattr(os, "startfile"):
                os.startfile(self.save_dir)
            else:
                self.status_bar.configure(text=f"Download folder ready: {self.save_dir}")
        except OSError:
            self.status_bar.configure(text=f"Folder location: {self.save_dir}")

    def _copy_selected_link(self):
        if self.filtered_videos:
            link = self.filtered_videos[0].get("url") or self.url_entry.get().strip()
            try:
                self.clipboard_clear()
                self.clipboard_append(link)
                self.status_bar.configure(text=f"Copied: {link}")
            except Exception:
                self.status_bar.configure(text="Clipboard access unavailable.")
        else:
            self.status_bar.configure(text="No video selected yet.")

    def _update_dashboard_stats(self):
        if hasattr(self, "stats_cards"):
            self.stats_cards["Videos"].configure(text=str(len(self.videos)))
            self.stats_cards["Queued"].configure(text=str(len(self.queue)))
            self.stats_cards["Folder"].configure(text=self.save_dir[:40] + ("..." if len(self.save_dir) > 40 else ""))

    def add_to_queue(self, video_data, resolution="Best Available"):
        if not isinstance(video_data, dict):
            return
        item = build_queue_item(video_data, resolution)
        existing = next((entry for entry in self.queue if entry["id"] == item["id"]), None)
        if existing is None:
            self.queue.append(item)
        else:
            existing["url"] = item["url"]
            existing["video_data"] = item["video_data"]
            existing["resolution"] = resolution
            existing["status"] = "Queued"
        self._refresh_queue_panel()
        self._update_dashboard_stats()

    def _refresh_queue_panel(self):
        if not hasattr(self, "queue_container"):
            return
        for widget in self.queue_container.winfo_children():
            widget.destroy()

        if not self.queue:
            ctk.CTkLabel(self.queue_container, text="Queue is empty.", text_color=APP_MUTED).pack(anchor="w", padx=8, pady=8)
            return

        for item in self.queue:
            card = ctk.CTkFrame(self.queue_container, fg_color=APP_SURFACE_ALT, corner_radius=10, border_width=1, border_color=APP_BORDER)
            card.pack(fill="x", padx=4, pady=4)
            ctk.CTkLabel(card, text=item["title"][:42] + ("..." if len(item["title"]) > 42 else ""), text_color=APP_TEXT, anchor="w", justify="left").pack(anchor="w", padx=8, pady=(8, 0))
            ctk.CTkLabel(card, text=f"{item['resolution']} • {item['status']}", text_color=APP_MUTED, anchor="w").pack(anchor="w", padx=8, pady=(0, 8))

    def _set_category_filter(self, category):
        self.active_category = category
        for name, button in self.category_buttons.items():
            button.configure(
                fg_color=APP_ACCENT if name == category else APP_SURFACE_ALT,
                text_color=APP_ON_ACCENT if name == category else APP_TEXT,
            )
        self._apply_category_filter()

    def _apply_sorting(self):
        self.sort_mode = self.sort_combo.get() if hasattr(self.sort_combo, "get") else self.sort_mode
        self._apply_category_filter()

    def _apply_category_filter(self):
        query = self.search_entry.get().strip().lower()
        filtered = list(self.videos)
        if query:
            filtered = [video for video in filtered if query in video["title"].lower()]
        if self.active_category != "All":
            filtered = [video for video in filtered if infer_video_category(video.get("title", "")) == self.active_category]

        if self.sort_mode == "Newest":
            filtered.sort(key=lambda video: (video.get("upload_date") or "00000000", video.get("title") or ""), reverse=True)
        elif self.sort_mode == "Oldest":
            filtered.sort(key=lambda video: (video.get("upload_date") or "00000000", video.get("title") or ""))
        elif self.sort_mode == "Title A-Z":
            filtered.sort(key=lambda video: (video.get("title") or "").lower())
        elif self.sort_mode == "Title Z-A":
            filtered.sort(key=lambda video: (video.get("title") or "").lower(), reverse=True)

        self.filtered_videos = filtered
        self.counter_label.configure(text=f"{len(self.filtered_videos)} of {len(self.videos)} videos shown")
        self._update_dashboard_stats()
        self._populate_grid(self.filtered_videos)

    def _queue_visible_videos(self):
        if self.queue_active:
            self.status_bar.configure(text="Stop the active queue before adding more videos.")
            return
        visible = list(self.filtered_videos)
        if not visible:
            self.status_bar.configure(text="No visible videos to queue.")
            return
        for video in visible:
            self.add_to_queue(video, "Best Available")
        self.status_bar.configure(text=f"Queued {len(visible)} visible videos.")

    def _clear_queue(self):
        if self.queue_active:
            self.status_bar.configure(text="Stop the active queue before clearing it.")
            return
        self.queue.clear()
        self._refresh_queue_panel()
        self._update_dashboard_stats()
        self.status_bar.configure(text="Queue cleared.")

    def _set_queue_item_status(self, video_id, status):
        for item in self.queue:
            if item["id"] == video_id:
                item["status"] = status
                break
        self._refresh_queue_panel()
        self._update_dashboard_stats()

    def _finish_individual_download(self, video_id, status):
        self.download_active = False
        self._set_queue_item_status(video_id, status)

    def _start_queue_downloads(self):
        if self.queue_active:
            return
        if self.download_active:
            self.status_bar.configure(text="Finish or cancel the active video download before starting the queue.")
            return
        pending_items = get_pending_queue_items(self.queue)
        if not pending_items:
            self.status_bar.configure(text="No queued or retryable downloads.")
            return

        self.queue_active = True
        self.queue_cancel_event.clear()
        self.start_queue_btn.configure(state="disabled")
        self.stop_queue_btn.configure(state="normal")
        self.clear_queue_btn.configure(state="disabled")
        self.queue_visible_btn.configure(state="disabled")
        self.choose_folder_btn.configure(state="disabled")
        self.status_bar.configure(text=f"Starting queue: {len(pending_items)} video(s).")
        threading.Thread(
            target=self._queue_download_worker,
            args=(list(pending_items), self.save_dir),
            daemon=True,
        ).start()

    def _stop_queue_downloads(self):
        if not self.queue_active:
            return
        self.queue_cancel_event.set()
        self.stop_queue_btn.configure(state="disabled")
        self.status_bar.configure(text="Stopping queue after the current download reaches a safe checkpoint...")

    def _queue_download_worker(self, items, save_dir):
        failures = []
        cancelled = False

        for item in items:
            if self.queue_cancel_event.is_set():
                cancelled = True
                break

            video_id = item["id"]
            self.after(0, lambda current_id=video_id: self._set_queue_item_status(current_id, "Downloading"))

            def update_progress(data, title=item["title"]):
                if data.get("status") != "downloading":
                    return
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes", 0)
                if total:
                    percent = min(downloaded / total, 1.0)
                    self.after(
                        0,
                        lambda current_title=title, current_percent=percent: self.status_bar.configure(
                            text=f"Downloading {current_title}: {current_percent:.0%}"
                        ),
                    )

            try:
                video_data = item.get("video_data") or {
                    "id": video_id,
                    "title": item["title"],
                    "url": item.get("url"),
                }
                video_url = item.get("url") or video_data.get("url")
                if not video_url:
                    raise ValueError("The queue item has no video URL.")
                download_video_with_metadata(
                    video_data,
                    video_url,
                    item["resolution"],
                    save_dir,
                    update_progress,
                    cancel_event=self.queue_cancel_event,
                )
                self.after(0, lambda current_id=video_id: self._set_queue_item_status(current_id, "Done"))
            except Exception as exc:
                if self.queue_cancel_event.is_set():
                    cancelled = True
                    self.after(0, lambda current_id=video_id: self._set_queue_item_status(current_id, "Cancelled"))
                    break
                error_message = str(exc)
                failures.append(f"{item['title']}: {error_message}")
                self.after(0, lambda current_id=video_id: self._set_queue_item_status(current_id, "Failed"))

        if self.queue_cancel_event.is_set():
            cancelled = True
        self.after(0, lambda: self._finish_queue_downloads(failures, cancelled))

    def _finish_queue_downloads(self, failures, cancelled):
        self.queue_active = False
        self.start_queue_btn.configure(state="normal")
        self.stop_queue_btn.configure(state="disabled")
        self.clear_queue_btn.configure(state="normal")
        self.queue_visible_btn.configure(state="normal")
        self.choose_folder_btn.configure(state="normal")
        if failures:
            self.status_bar.configure(text=f"Queue finished with {len(failures)} failed download(s).")
            messagebox.showwarning("Queue Finished with Errors", "\n".join(failures[:8]))
        elif cancelled:
            self.status_bar.configure(text="Queue stopped. Unfinished items remain available to retry.")
        else:
            self.status_bar.configure(text="Queue completed successfully.")

    def _export_metadata_csv(self):
        if not self.videos:
            messagebox.showinfo("Nothing to Export", "Fetch a channel before exporting metadata.")
            return

        destination = filedialog.asksaveasfilename(
            initialdir=self.save_dir,
            initialfile="channel_metadata.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not destination:
            return

        try:
            export_videos_csv(self.videos, destination)
            messagebox.showinfo("Export Complete", f"Metadata exported to:\n{destination}")
        except OSError as exc:
            messagebox.showerror("Export Error", str(exc))

    def start_fetch(self):
        raw_url = self.url_entry.get().strip()
        if not raw_url:
            messagebox.showwarning("Input Error", "Please provide a valid YouTube channel URL.")
            return

        target_url = sanitize_channel_url(raw_url)
        self.fetch_started_at = time.perf_counter()
        self.fetch_active = True
        self.fetch_btn.configure(state="disabled")
        self.status_bar.configure(text="Connecting to channel... 0.0s elapsed")
        self._show_channel_loading()
        self.after(250, self._update_fetch_elapsed)

        threading.Thread(target=self._fetch_worker, args=(target_url,), daemon=True).start()

    def _start_link_download(self):
        video_url = self.video_link_entry.get().strip()
        parsed_url = urlsplit(video_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            messagebox.showwarning("Input Error", "Enter a valid video URL starting with http:// or https://.")
            return

        self.direct_download_btn.configure(state="disabled")
        self.status_bar.configure(text="Loading video details from link...")
        threading.Thread(target=self._fetch_link_worker, args=(video_url,), daemon=True).start()

    def _fetch_link_worker(self, video_url):
        try:
            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
                video_info = ydl.extract_info(video_url, download=False)

            if not isinstance(video_info, dict) or not video_info.get("id"):
                raise ValueError("No video details were returned for this link.")

            video_data = build_video_summary(video_info)
            video_data["url"] = video_info.get("webpage_url") or video_url
            self.after(0, lambda: self._open_link_download(video_data))
        except Exception as exc:
            error_message = str(exc)
            self.after(0, lambda: messagebox.showerror("Video Link Error", error_message))
            self.after(0, lambda: self.status_bar.configure(text="Could not load video details from that link."))
        finally:
            self.after(0, lambda: self.direct_download_btn.configure(state="normal"))

    def _open_link_download(self, video_data):
        self.status_bar.configure(text=f"Video ready: {video_data.get('title') or 'Untitled Video'}")
        self.open_download_modal(video_data)

    def _update_fetch_elapsed(self):
        if not self.fetch_active:
            return
        elapsed = time.perf_counter() - self.fetch_started_at
        self.status_bar.configure(text=f"Gathering channel videos... {elapsed:.1f}s elapsed")
        self.after(250, self._update_fetch_elapsed)

    def _finish_fetch(self):
        self.fetch_active = False

    def _fetch_video_detail(self, video_id):
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        detail_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web", "ios", "android"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        try:
            with yt_dlp.YoutubeDL(cast(Any, detail_opts)) as ydl:
                return ydl.extract_info(video_url, download=False) or {}
        except Exception:
            return {}

    def _fetch_worker(self, channel_url):
        ydl_opts = {
            "extract_flat": True,
            "skip_download": True,
            "quiet": True,
            "ignoreerrors": True,
            "no_warnings": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["web", "ios", "android"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        try:
            with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = ydl.extract_info(channel_url, download=False) or {}
                entries = list(cast(Any, info.get("entries") or [])) if isinstance(info, dict) else []
                total_entries = len(entries)
                scan_started_at = time.perf_counter()
                extraction_elapsed = scan_started_at - self.fetch_started_at
                self._update_channel_loading(
                    0.12,
                    "Upload list ready",
                    f"FOUND {total_entries} VIDEOS • LIST LOADED IN {extraction_elapsed:.1f}s",
                )

                self.videos = []
                last_progress_update = scan_started_at
                for index, entry in enumerate(entries, start=1):
                    if not entry:
                        continue

                    vid_id = entry.get("id")
                    if not vid_id or entry.get("title") in ["[Private video]", "[Deleted video]"]:
                        continue

                    summary = build_video_summary(entry)
                    if summary:
                        self.videos.append(summary)

                    now = time.perf_counter()
                    if index == 1 or index == total_entries or now - last_progress_update >= 0.25:
                        elapsed = max(now - scan_started_at, 0.001)
                        videos_per_second = index / elapsed
                        remaining = max(total_entries - index, 0)
                        eta = remaining / videos_per_second if videos_per_second else 0
                        progress = 0.12 + (0.82 * index / max(total_entries, 1))
                        self._update_channel_loading(
                            progress,
                            "Building quick preview list...",
                            f"{index} / {total_entries} VIDEOS • {videos_per_second:.1f}/s • ETA {eta:.0f}s",
                        )
                        last_progress_update = now

                scan_elapsed = max(time.perf_counter() - scan_started_at, 0.001)
                scan_speed = total_entries / scan_elapsed if total_entries else 0
                self._update_channel_loading(
                    0.94,
                    "Video list ready",
                    f"{len(self.videos)} VIDEOS • SCANNED AT {scan_speed:.1f}/s",
                )

            self.after(0, self._render_grid_initial)
        except Exception as exc:  # pragma: no cover - UI path only
            self.after(0, self._hide_loading_overlay)
            self.after(0, lambda: messagebox.showerror("Extraction Error", f"Failed: {str(exc)}"))
            self.after(0, lambda: self.status_bar.configure(text="Metadata retrieval failed."))
        finally:
            self.after(0, self._hide_loading_overlay)
            self.after(0, lambda: self.fetch_btn.configure(state="normal"))
            self.after(0, self._finish_fetch)

    def _render_grid_initial(self):
        self.filtered_videos = list(self.videos)
        self.counter_label.configure(text=f"{len(self.videos)} total uploads extracted")
        elapsed = max(time.perf_counter() - self.fetch_started_at, 0.001)
        videos_per_second = len(self.videos) / elapsed
        self.status_bar.configure(
            text=f"Loaded {len(self.videos)} videos in {elapsed:.1f}s ({videos_per_second:.1f} videos/s)."
        )
        self._update_dashboard_stats()
        self._populate_grid(self.filtered_videos)

    def _populate_grid(self, video_list):
        for widget in self.grid_container.winfo_children():
            widget.destroy()

        self._grid_videos = list(video_list)
        self._grid_page_index = 0
        self._render_grid_page()

    def _render_grid_page(self):
        for widget in self.grid_container.winfo_children():
            widget.destroy()

        columns = 4
        page, page_count, start_index = get_video_page(
            self._grid_videos,
            self._grid_page_index,
        )
        for idx, video in enumerate(page):
            row = idx // columns
            col = idx % columns
            card = VideoCard(self.grid_container, video, on_click_callback=self.open_download_modal)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        for col in range(columns):
            self.grid_container.grid_columnconfigure(col, weight=1)

        first_video = start_index + 1 if page else 0
        last_video = start_index + len(page)
        self.page_label.configure(
            text=f"Page {self._grid_page_index + 1} of {page_count} • Videos {first_video}-{last_video} of {len(self._grid_videos)}"
        )
        self.previous_page_btn.configure(state="normal" if self._grid_page_index > 0 else "disabled")
        self.next_page_btn.configure(state="normal" if self._grid_page_index + 1 < page_count else "disabled")

    def _show_previous_page(self):
        if self._grid_page_index <= 0:
            return
        self._grid_page_index -= 1
        self._render_grid_page()

    def _show_next_page(self):
        _, page_count, _ = get_video_page(self._grid_videos, self._grid_page_index)
        if self._grid_page_index + 1 >= page_count:
            return
        self._grid_page_index += 1
        self._render_grid_page()

    def _filter_videos(self, event=None):
        if self._filter_after_id is not None:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(180, self._run_debounced_filter)

    def _run_debounced_filter(self):
        self._filter_after_id = None
        self._apply_category_filter()

    def open_download_modal(self, video_data):
        DownloadModal(self, video_data, self.save_dir)


class DownloadModal(ctk.CTkToplevel):
    """Download modal with robust format selection and UI state handling."""

    def __init__(self, parent, video_data, save_dir):
        super().__init__(parent)
        self.video_data = video_data
        self.save_dir = save_dir
        self.cancel_event = threading.Event()
        self.download_running = False

        self.configure(fg_color=APP_BG)
        self.title("Download Video")
        self.geometry("520x560")
        self.minsize(520, 560)
        self.resizable(False, True)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text=self.video_data["title"], font=("Segoe UI", 12, "bold"), wraplength=480, justify="left", text_color=APP_TEXT).pack(padx=20, pady=(20, 10), fill="x")

        details_box = ctk.CTkFrame(self, fg_color=APP_PANEL, corner_radius=14, border_width=1, border_color=APP_BORDER)
        details_box.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(
            details_box,
            text=f"Duration: {format_duration(self.video_data.get('duration'))}  |  Views: {format_views(self.video_data.get('view_count'))}  |  Date: {format_date(self.video_data.get('upload_date'))}",
            font=("Segoe UI", 11),
            text_color=APP_MUTED,
        ).pack(padx=10, pady=6)

        info_box = ctk.CTkFrame(self, fg_color=APP_PANEL, corner_radius=12, border_width=1, border_color=APP_BORDER)
        info_box.pack(fill="x", padx=20, pady=(8, 0))

        ctk.CTkLabel(info_box, text=f"Channel: {self.video_data.get('channel_name') or 'Unknown'}", font=("Segoe UI", 10), text_color=APP_TEXT, anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(info_box, text=f"Handle / ID: {self.video_data.get('channel_handle') or 'Unavailable'}", font=("Segoe UI", 10), text_color=APP_MUTED, anchor="w").pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(info_box, text=f"Real quality: {self.video_data.get('real_quality') or 'Quality unavailable'}", font=("Segoe UI", 10, "bold"), text_color=APP_GREEN_DARK, anchor="w").pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(info_box, text=f"Location: {self.video_data.get('location') or 'Not publicly exposed'}", font=("Segoe UI", 10), text_color=APP_MUTED, anchor="w").pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(info_box, text="Location values are public metadata only.", font=("Segoe UI", 10), text_color=APP_MUTED, anchor="w").pack(fill="x", padx=12, pady=(2, 10))

        ctk.CTkLabel(self, text="Select Target Resolution:", font=("Segoe UI", 11, "bold"), text_color=APP_TEXT).pack(anchor="w", padx=20, pady=(15, 2))
        self.quality_combo = ctk.CTkComboBox(
            self,
            values=["Best Available", "2160p (4K)", "1440p (2K)", "1080p", "720p", "480p", "360p", "Audio Only (.mp3)"],
            width=480,
            height=38,
            fg_color=APP_CARD,
            border_color=APP_BORDER,
            dropdown_fg_color=APP_CARD,
            dropdown_text_color=APP_TEXT,
            button_color=APP_ACCENT,
            button_hover_color=APP_ACCENT_DARK,
            text_color=APP_TEXT,
        )
        self.quality_combo.set("Best Available")
        self.quality_combo.pack(padx=20, pady=5)

        self.progress_bar = ctk.CTkProgressBar(self, width=480, progress_color=APP_ACCENT, fg_color=APP_PROGRESS_TRACK)
        self.progress_bar.set(0)
        self.progress_bar.pack(padx=20, pady=(20, 5))

        self.lbl_status = ctk.CTkLabel(self, text="Ready", font=("Segoe UI", 11), text_color=APP_MUTED)
        self.lbl_status.pack(padx=20, pady=2)

        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(padx=20, pady=(15, 10), fill="x")

        self.btn_download = ctk.CTkButton(
            action_frame,
            text="Start Download",
            fg_color=APP_GREEN,
            hover_color=APP_GREEN_DARK,
            text_color=APP_ON_ACCENT,
            command=self._start_download_task,
            height=38,
            font=("Segoe UI", 11, "bold"),
            corner_radius=12,
        )
        self.btn_download.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.btn_cancel = ctk.CTkButton(
            action_frame,
            text="Cancel",
            fg_color=APP_DANGER,
            hover_color=APP_DANGER_DARK,
            text_color=APP_ON_ACCENT,
            command=self._cancel_download,
            height=38,
            font=("Segoe UI", 11, "bold"),
            corner_radius=10,
            state="disabled",
        )
        self.btn_cancel.pack(side="right", padx=(6, 0))

    def _start_download_task(self):
        if getattr(self.master, "queue_active", False) or getattr(self.master, "download_active", False):
            messagebox.showinfo("Download Active", "Finish or cancel the active download before starting another.")
            return
        self.cancel_event.clear()
        self.download_running = True
        if hasattr(self.master, "download_active"):
            self.master.download_active = True
        self.btn_download.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.lbl_status.configure(text="Connecting to video stream...")
        resolution = self.quality_combo.get()
        if hasattr(self.master, "add_to_queue"):
            self.master.add_to_queue(self.video_data, resolution)
            if hasattr(self.master, "_set_queue_item_status"):
                self.master._set_queue_item_status(self.video_data.get("id"), "Downloading")
        threading.Thread(target=self._download_worker, args=(self.video_data["url"], resolution), daemon=True).start()

    def _handle_close(self):
        if self.download_running:
            self._cancel_download()
            return
        self.destroy()

    def _cancel_download(self):
        self.cancel_event.set()
        self.btn_cancel.configure(state="disabled")
        self.lbl_status.configure(text="Cancelling download...")

    def _download_hook(self, d):
        if self.cancel_event.is_set():
            raise RuntimeError("Download cancelled by user")

        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                pct = min(downloaded / total, 1.0)
                speed = d.get("speed") or 0
                speed_str = f"{speed / (1024 * 1024):.1f} MB/s" if speed else "N/A"
                eta = d.get("eta", 0)
                self.after(0, lambda: self.progress_bar.set(pct))
                self.after(0, lambda: self.lbl_status.configure(text=f"{int(pct * 100)}% • {speed_str} • ETA {eta}s"))
        elif d.get("status") == "finished":
            self.after(0, lambda: self.lbl_status.configure(text="Muxing audio & video..."))

    def _download_worker(self, video_url, resolution):
        try:
            download_video_with_metadata(
                self.video_data,
                video_url,
                resolution,
                self.save_dir,
                self._download_hook,
                cancel_event=self.cancel_event,
                before_metadata_hook=lambda: self.after(
                    0,
                    lambda: self.lbl_status.configure(text="Writing metadata sidecar..."),
                ),
            )

            if hasattr(self.master, "_finish_individual_download"):
                video_id = self.video_data.get("id")
                self.after(0, lambda: self.master._finish_individual_download(video_id, "Done"))

            self.after(0, self._mark_download_finished)
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.lbl_status.configure(text="Download Complete!"))
            self.after(0, lambda: messagebox.showinfo("Saved", "Video saved successfully."))
            self.after(0, self.destroy)
        except Exception as exc:
            message = "Download cancelled." if self.cancel_event.is_set() else str(exc)
            if hasattr(self.master, "_finish_individual_download"):
                status = "Cancelled" if self.cancel_event.is_set() else "Failed"
                video_id = self.video_data.get("id")
                self.after(0, lambda: self.master._finish_individual_download(video_id, status))
            self.after(0, self._mark_download_finished)
            self.after(0, lambda: messagebox.showerror("Download Error", message))
            self.after(0, lambda: self.lbl_status.configure(text=message))
            self.after(0, lambda: self.btn_download.configure(state="normal"))
            self.after(0, lambda: self.btn_cancel.configure(state="disabled"))

    def _mark_download_finished(self):
        self.download_running = False


def main() -> int:
    """Start the GUI app with a clean headless-terminal fallback."""
    try:
        require_gui_dependencies()
    except RuntimeError as exc:
        print(
            "Desktop GUI runtime is unavailable. Install the app dependencies and run this program from a desktop session. "
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        app = ChannelGridApp()
    except Exception as exc:  # pragma: no cover - GUI startup path only
        message = str(exc).lower()
        if any(token in message for token in ("display", "tcl", "tk", "no display", "cannot connect to display")):
            print(
                "Desktop GUI runtime is unavailable. This app cannot run in a headless terminal or CI environment.",
                file=sys.stderr,
            )
            return 1
        raise

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
