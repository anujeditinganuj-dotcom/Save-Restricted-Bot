"""
Shared helpers for direct-link downloader plugins (catbox, pixeldrain, gofile,
mediafire, streamtape, terabox, mega, gdrive, torrent, gallery).

Every plugin extracts a direct download URL (or list of files) on its own,
then calls into this module to actually stream the download to disk,
build a thumbnail/metadata for videos, and upload the result to Telegram.
"""

import os
import time
import random
import asyncio
import subprocess
import aiohttp
from pyrogram import enums

E_CHECK  = '<emoji id=5206607081334906820>✔️</emoji>'
E_CROSS  = '<emoji id=5210952531676504517>❌</emoji>'
E_ROCKET = '<emoji id=5456140674028019486>🚀</emoji>'
E_INFO   = '<emoji id=5334544901428229844>ℹ️</emoji>'

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

VIDEO_EXTS = ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.flv')
AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus')
PHOTO_EXTS = ('.jpg', '.jpeg', '.png', '.webp')


def make_output_folder(service: str) -> str:
    folder = os.path.join("downloads", service)
    os.makedirs(folder, exist_ok=True)
    return folder


def safe_filename(name: str, fallback: str) -> str:
    name = (name or "").strip().strip("/\\")
    if not name:
        return fallback
    # strip characters that break filesystem paths
    return "".join(c for c in name if c not in '\\/:*?"<>|') or fallback


async def stream_download(url: str, dest: str, status, label: str,
                           headers: dict = None, timeout: int = 300) -> int:
    """Streams url -> dest with periodic status.edit_text progress updates.
    Returns total bytes downloaded. Raises on HTTP/network failure."""
    headers = headers or DEFAULT_HEADERS
    downloaded = 0
    last_edit = 0.0
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status not in (200, 206):
                raise ValueError(f"HTTP {resp.status} while downloading")
            total = int(resp.headers.get("Content-Length", 0))

            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    if status is not None and now - last_edit >= 3:
                        last_edit = now
                        pct = f"{downloaded / total * 100:.1f}%" if total else "?"
                        done_mb = downloaded / (1024 * 1024)
                        total_mb = f"{total / (1024 * 1024):.1f} MB" if total else "unknown"
                        try:
                            await status.edit_text(
                                f"<b>{E_ROCKET} {label}</b>\n"
                                f"<code>{done_mb:.1f} MB / {total_mb}  ({pct})</code>",
                                parse_mode=enums.ParseMode.HTML
                            )
                        except Exception:
                            pass
    return downloaded


def extract_thumbnail(video_path: str, thumb_path: str) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = float(probe.stdout.strip() or "10")
    except ValueError:
        duration = 10.0
    seek = random.uniform(duration * 0.1, duration * 0.8) if duration > 1 else 0
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seek),
             "-i", video_path, "-vframes", "1", "-vf", "scale=320:-1", "-y", thumb_path],
            timeout=30, check=True
        )
        return os.path.exists(thumb_path)
    except Exception:
        return False


def get_video_metadata(video_path: str):
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = int(float(dur.stdout.strip() or "0"))
    except ValueError:
        duration = 0
    dim = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        w, h = dim.stdout.strip().split(",")
        width, height = int(w), int(h)
    except Exception:
        width, height = 1280, 720
    return duration, width, height


async def upload_file(client, message, path: str, status, caption: str):
    """Sends a downloaded file to Telegram as video/audio/photo/document
    based on its extension, then cleans up the local copy."""
    ext = os.path.splitext(path)[1].lower()
    thumb = None
    try:
        await status.edit_text(f"<b>{E_ROCKET} Uploading...</b>", parse_mode=enums.ParseMode.HTML)

        if ext in VIDEO_EXTS:
            thumb = path + ".jpg"
            has_thumb = await asyncio.to_thread(extract_thumbnail, path, thumb)
            duration, width, height = await asyncio.to_thread(get_video_metadata, path)
            await client.send_video(
                chat_id=message.chat.id, video=path,
                thumb=thumb if has_thumb else None,
                duration=duration, width=width, height=height,
                caption=caption, reply_to_message_id=message.id,
                supports_streaming=True, parse_mode=enums.ParseMode.HTML
            )
        elif ext in AUDIO_EXTS:
            await client.send_audio(
                chat_id=message.chat.id, audio=path,
                caption=caption, reply_to_message_id=message.id,
                parse_mode=enums.ParseMode.HTML
            )
        elif ext in PHOTO_EXTS:
            await client.send_photo(
                chat_id=message.chat.id, photo=path,
                caption=caption, reply_to_message_id=message.id,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await client.send_document(
                chat_id=message.chat.id, document=path,
                caption=caption, reply_to_message_id=message.id,
                parse_mode=enums.ParseMode.HTML
            )
        await status.delete()
    finally:
        for f in (path, thumb):
            if f:
                try:
                    os.remove(f)
                except Exception:
                    pass
