   - 2160p (4K)

The channel grid displays 48 videos per page. Use the previous/next arrow buttons to navigate pages; filtering and sorting apply across the full fetched list.
# YT Archive

A Windows desktop application for discovering videos from a YouTube channel, inspecting public metadata, and downloading the best available encoded video/audio streams with yt-dlp.

The application uses CustomTkinter for the interface and FFmpeg for combining separate video and audio streams. It is designed for content you are authorized to access and download.

## Features

- Fetches uploads from a YouTube channel URL.
- Displays video cards with thumbnails, duration, views, and detected quality.
- Displays 48 video cards per page, with previous/next arrow navigation.
- Debounces title filtering to avoid rebuilding the grid on every keystroke.
- Shows a game-inspired loading overlay while scanning a channel.
- Uses upload thumbnails as the scanning background when available.
- Downloads the best available source streams without video transcoding when FFmpeg is available.
- Preserves source codecs where possible by merging into MKV.
- Supports explicit resolution limits:
   - Best Available
   - 2160p (4K)
   - 1440p (2K)
   - 1080p
   - 720p
   - 480p
   - 360p
   - Audio Only (.mp3)
- Provides progress, speed, and ETA information during downloads.
- Supports retry and resume behavior for interrupted downloads.
- Provides a Cancel button for active downloads.
- Supports sequential batch downloads with Start Queue and cooperative Stop Queue controls.
- Allows failed or cancelled queue items to be retried without rerunning completed items.
- Includes clear-filter and download-folder selection controls.
- Verifies that a media file was created before reporting success.
- Writes yt-dlp information JSON during extraction.
- Writes a normalized `.metadata.json` sidecar after a verified media download.
- Exports fetched channel metadata to CSV.
- Shows public video/channel/location metadata.
- Includes automated regression tests for the core pure functions.

## Important Quality Note

YouTube does not normally expose the private original camera file. This application downloads the highest-quality encoded streams that YouTube makes available to yt-dlp.

The default `Best Available` mode requests separate best video and audio streams when possible. FFmpeg then combines them without re-encoding the video. This preserves the downloaded source quality, but it cannot restore quality that was removed during YouTube processing.

MP3 mode is intentionally lossy because it converts audio to MP3 at 320 kbps.

## Requirements

- Windows 10 or later is recommended.
- Python 3.10 or later.
- Internet access.
- FFmpeg for maximum quality and separate video/audio merging.

The project includes `imageio-ffmpeg` as a fallback FFmpeg provider. A system FFmpeg installation is still recommended for predictable performance and codec support.

## Installation

Open PowerShell in the project directory:

```powershell
cd "D:\Python Projects\Yt Video Download"
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

The application can also be run without activating the environment by using the explicit interpreter path:

```powershell
.venv\Scripts\python.exe app.py
```

## Running the Application

```powershell
.venv\Scripts\python.exe app.py
```

The main window opens with:

1. A channel URL field.
2. A `Fetch All Uploads` button.
3. A title filter.
4. An `Export CSV` action.
5. A download-folder selector.
6. A grid of discovered videos.

### Fetching a Channel

1. Enter a channel URL, for example:

   ```text
   https://www.youtube.com/@ChannelName
   ```

2. Select `Fetch All Uploads`.
3. The app normalizes the URL to the channel videos page.
4. The loading overlay shows elapsed time, scan progress, videos per second, and an estimated time remaining.
5. The app builds a quick preview list from the channel's upload data without making a separate detail request for every video.
6. The completed video cards appear in the grid.

Supported channel URL styles depend on what yt-dlp currently accepts. Private, deleted, unavailable, age-restricted, or region-restricted content may not be extractable.

### Downloading a Video

1. Select `Download` on a video card.
2. Choose a quality mode.
3. Select `Start Download`.
4. Monitor progress, speed, and ETA.
5. Use `Cancel` to request cooperative cancellation.
6. Wait for media verification and metadata sidecar creation.

The app only displays success after a non-empty output media file has been detected.

To download a video without fetching its channel, paste its URL into `Download by link` and select `Choose Quality`. The app loads the video's details, then opens the same quality and download dialog used by video cards.

### Download Queue

1. Select `Queue Visible` to add the currently filtered and sorted videos, or start an individual download to add that video to the queue.
2. Select `Start Queue` to download queued items sequentially using the selected output folder.
3. Use `Stop Queue` to stop after the current download reaches a cancellation checkpoint. Unfinished items remain retryable.
4. Failed and cancelled items can be retried with `Start Queue`; completed items are skipped.
5. Select `Clear Queue` when no queue is running to remove the queue entries.

The queue is held in memory for the current app session and is not restored after closing the app.

### Quality Modes

`Best Available` uses:

```text
bestvideo+bestaudio/bestvideo/best
```

When FFmpeg is available, yt-dlp can download separate high-quality streams and merge them into MKV. The format sorting policy prioritizes resolution, FPS, HDR, codec, bitrate, and size.

Resolution modes add a maximum height constraint. They are quality caps, not enhancement modes.

If FFmpeg is unavailable, the app falls back to a complete progressive format. This produces a playable video but may be lower quality than separate video/audio streams.

### CSV Export

After fetching a channel:

1. Select `Export CSV`.
2. Choose a destination path.
3. The app writes UTF-8 CSV with a BOM for spreadsheet compatibility.

The export includes:

- Video ID
- Title
- URL
- Channel name
- Channel handle or ID
- Upload date
- Duration
- View count
- Detected quality
- Public location

### Metadata Files

The downloader may create two metadata files:

- yt-dlp's `.info.json`, containing the extractor's detailed public result.
- The app's `.metadata.json`, written after media completion and containing normalized fields, selected format, media path, and download timestamp.

The normalized sidecar contains fields such as title, description, channel, dates, duration, views, likes, comments, tags, categories, language, thumbnail, public location, chapters, dimensions, FPS, video codec, audio codec, and extension when available.

## Output Naming

The default output template is:

```text
<title>.<extension>
```

Files are written to the selected download directory. yt-dlp applies its own filename handling. The application also provides a Windows-safe filename helper for generated metadata paths and future output workflows.

## Project Structure

```text
.
|-- app.py             Main CustomTkinter application
|-- requirements.txt   Pinned Python dependencies
|-- test_app.py        Standard-library regression tests
|-- README.md          This documentation
|-- .venv/             Local virtual environment, not committed
```

## Architecture

### UI Layer

`ChannelGridApp` owns the main window, channel URL input, filtering, download folder, loading overlay, video grid, and CSV export.

`VideoCard` displays one video and asynchronously loads its thumbnail. Thumbnail widget changes are scheduled on Tkinter's main thread with `after`.

`GameLoadingOverlay` displays startup and channel-scan progress. Thumbnail images are downloaded in worker threads and applied on the Tkinter thread.

`DownloadModal` displays video metadata, quality choices, download progress, cancellation, and completion/error states.

### Download Layer

`build_download_format()` converts the visible quality choice into a yt-dlp format selector.

`build_download_options()` is the single source of truth for download behavior. It configures:

- Format selection
- Output template
- Progress hooks
- Retry counts
- Fragment retries
- Resume support
- Non-overwrite behavior
- Quality sorting
- Metadata writing
- FFmpeg location
- MKV merging
- MP3 postprocessing

`get_ffmpeg_path()` checks for a system FFmpeg binary and then attempts the `imageio-ffmpeg` fallback.

### Metadata Layer

`normalize_video_metadata()` creates a stable public metadata shape.

`write_metadata_sidecar()` writes an atomic normalized JSON sidecar using a temporary file followed by `os.replace`.

`export_videos_csv()` writes stable channel-level CSV columns using Python's CSV writer, which correctly escapes commas and quotes.

## Testing

Run the regression suite:

```powershell
.venv\Scripts\python.exe -m unittest -v test_app.py
```

Compile the application and tests:

```powershell
.venv\Scripts\python.exe -m py_compile app.py test_app.py
```

The tests currently cover:

- Best-available format selection.
- MP3 postprocessing configuration.
- Resume and retry settings.
- Windows filename safety.
- Public metadata normalization.
- Atomic JSON sidecar creation.
- CSV escaping and round-trip reading.

A real network download is intentionally not part of the automated test suite because it depends on YouTube availability, network conditions, content access, and potentially large files.

## Troubleshooting

### Only a JSON file appears

A JSON file may be created early by yt-dlp during extraction. It is not proof that the media completed.

Check the following:

1. Confirm that FFmpeg is available:

   ```powershell
   .venv\Scripts\python.exe -c "import app; print(app.get_ffmpeg_path())"
   ```

2. Confirm there is enough disk space.
3. Try the same URL with `Best Available`.
4. Check whether the video is private, deleted, age restricted, or region restricted.
5. Look for a media file and a `.metadata.json` sidecar. The normalized sidecar is only written after media verification.
6. Remove or rename an old sidecar before retesting if its title matches a previous failed attempt.

### Download quality is low

1. Use `Best Available` instead of a resolution cap.
2. Install system FFmpeg or ensure `imageio-ffmpeg` is installed.
3. Avoid judging quality from an old `.info.json` file created by a previous 360p run.
4. Inspect available formats manually:

   ```powershell
   .venv\Scripts\python.exe -m yt_dlp -F "VIDEO_URL"
   ```

5. Confirm that high-resolution video-only formats and audio-only formats are exposed.

### The loading thumbnail is blank

The app first uses the thumbnail URL returned by yt-dlp and then falls back to:

```text
https://i.ytimg.com/vi/<VIDEO_ID>/hqdefault.jpg
```

A blank image can still occur if the network blocks the image host, the video ID is invalid, or the thumbnail request times out.

### FFmpeg is not found

The app checks `PATH` first and then `imageio-ffmpeg`. Reinstall dependencies if necessary:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### A channel scan is slow

Detailed extraction currently processes video entries sequentially. Large channels can therefore take a long time. Keep the window open while the loading overlay is active and avoid starting duplicate scans.

## Privacy and Data Boundaries

The app reads public metadata exposed by yt-dlp and downloads media from the selected service. It does not provide:

- YouTube account passwords or login email addresses.
- Private device GPS.
- Viewer location.
- Private uploader data.
- Original camera files unavailable from YouTube.

The location shown by the app is public metadata such as release location when available. It must not be interpreted as a precise camera or viewer location.

## Legal and Responsible Use

Only download material when you have permission or a lawful basis to do so. Respect copyright, privacy, platform terms, creator rights, age restrictions, and regional laws. Do not use the application to bypass access controls, download private content, or redistribute material without authorization.

The application is a local client around yt-dlp. Service behavior, available formats, authentication requirements, and platform policies can change independently of this project.

## Maintenance Guidelines

- Keep dependencies pinned and update them deliberately.
- Run tests and compile checks before releases.
- Do not treat a metadata sidecar as proof of media completion.
- Keep all Tkinter widget updates on the main thread.
- Preserve source streams whenever possible; do not add video transcoding unless explicitly requested.
- Test with a small, permitted public video before attempting a large channel.
- Avoid committing `.venv`, downloaded media, metadata sidecars, or cache files.

## Known Limitations

- The app is currently a single-file GUI implementation.
- Channel metadata extraction is sequential.
- The download queue is session-only; queue state and download history are not persisted.
- Cancellation is cooperative and depends on yt-dlp reaching a progress hook.
- There is no automated live YouTube download test.
- YouTube may expose different formats depending on region, account state, client, content, and time.
- Some containers and codecs may require an external media player.

## License

No license has been declared for this project. Add an explicit license before distributing the application publicly.
