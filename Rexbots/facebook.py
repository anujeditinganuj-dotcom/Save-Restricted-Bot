import os
import re
import json
import time
import random
import asyncio
import subprocess
import http.cookiejar
import requests
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import FB_COOKIES

E_CHECK  = '<emoji id=5206607081334906820>✔️</emoji>'
E_CROSS  = '<emoji id=5210952531676504517>❌</emoji>'
E_ROCKET = '<emoji id=5456140674028019486>🚀</emoji>'
E_INFO   = '<emoji id=5334544901428229844>ℹ️</emoji>'

OUTPUT_FOLDER = "downloads/facebook"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

FB_PATTERN = re.compile(
    r"(https?://)?(www\.)?(facebook\.com|fb\.watch|fb\.com)/\S+", re.IGNORECASE
)

FETCH_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
}
DOWNLOAD_HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36'
}


def _load_fb_session() -> requests.Session:
    """Builds a requests Session with FB_COOKIES loaded (Netscape format),
    so both public and private (logged-in-only) video links can be fetched."""
    session = requests.Session()
    if FB_COOKIES and os.path.exists(FB_COOKIES):
        jar = http.cookiejar.MozillaCookieJar()
        try:
            jar.load(FB_COOKIES, ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)
        except Exception:
            pass  # empty/placeholder cookie file — fall back to public-only access
    return session


def extract_fb_url(text: str):
    m = FB_PATTERN.search(text)
    return m.group(0) if m else None


def _extract_fb_links_sync(link: str):
    """Returns (video_url, audio_url, video_id). Raises ValueError on failure."""
    session = _load_fb_session()
    try:
        resp = session.get(link, headers=FETCH_HEADERS, timeout=30)
    except Exception as e:
        raise ValueError(f"Failed to fetch page: {e}")

    resolved_url = resp.url.split('?')[0]
    html = resp.text

    video_id = ''
    for seg in resolved_url.split('/'):
        if seg.isdigit():
            video_id = seg
            break
    if not video_id:
        raw_params = resp.url.split('?')
        if len(raw_params) > 1:
            for param in raw_params[1].split('&'):
                if param.startswith('v=') and param[2:].isdigit():
                    video_id = param[2:]
                    break
    if not video_id:
        raise ValueError("Could not find video ID. Is this a valid Facebook video link?")

    try:
        target = html.split(f'"id":"{video_id}"')[1].split('"dash_prefetch_experimental":[')[1].split(']')[0].strip()
    except IndexError:
        try:
            target = html.split(f'"video_id":"{video_id}"')[1].split('"dash_prefetch_experimental":[')[1].split(']')[0].strip()
        except IndexError:
            raise ValueError(
                "Could not find video stream data. It may be private, age-restricted, "
                "or a story/reel (not supported)."
            )

    try:
        sources = json.loads(f"[{target}]")
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse stream sources: {e}")
    if len(sources) < 2:
        raise ValueError(f"Expected at least 2 stream sources, got {len(sources)}.")

    try:
        video_link = html.split(f'"representation_id":"{sources[0]}"')[1].split('"base_url":"')[1].split('"')[0].replace('\\', '')
    except IndexError:
        raise ValueError("Could not extract video stream URL.")
    try:
        audio_link = html.split(f'"representation_id":"{sources[1]}"')[1].split('"base_url":"')[1].split('"')[0].replace('\\', '')
    except IndexError:
        raise ValueError("Could not extract audio stream URL.")

    return video_link, audio_link, video_id


def _download_file_sync(url: str, dest: str) -> bool:
    try:
        resp = requests.get(url, headers=DOWNLOAD_HEADERS, stream=True, timeout=60)
        resp.raise_for_status()
    except Exception:
        return False
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=512 * 1024):
            if chunk:
                f.write(chunk)
    return True


def _merge_streams(video_path: str, audio_path: str, out_path: str) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", video_path,
           "-i", audio_path, "-c", "copy", "-y", out_path]
    try:
        subprocess.run(cmd, timeout=300, check=True)
        return True
    except Exception:
        return False


def _extract_thumbnail(video_path: str, thumb_path: str) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = float(probe.stdout.strip() or "10")
    except ValueError:
        duration = 10.0
    seek = random.uniform(duration * 0.10, duration * 0.80)
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seek),
             "-i", video_path, "-vframes", "1", "-vf", "scale=320:-1", "-y", thumb_path],
            timeout=30, check=True
        )
        return os.path.exists(thumb_path)
    except Exception:
        return False


def _get_video_metadata(video_path: str):
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


async def _handle_fb_download(client: Client, message: Message, url: str):
    status = await message.reply_text(
        f"<b>{E_INFO} Facebook link detected — extracting...</b>", parse_mode=enums.ParseMode.HTML
    )

    try:
        video_url, audio_url, video_id = await asyncio.to_thread(_extract_fb_links_sync, url)
    except ValueError as e:
        return await status.edit_text(
            f"<b>{E_CROSS} Extraction failed:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML
        )

    raw_video = os.path.join(OUTPUT_FOLDER, f"{video_id}_v.mp4")
    raw_audio = os.path.join(OUTPUT_FOLDER, f"{video_id}_a.mp4")
    merged    = os.path.join(OUTPUT_FOLDER, f"{video_id}.mp4")
    thumb     = os.path.join(OUTPUT_FOLDER, f"{video_id}.jpg")

    try:
        await status.edit_text(f"<b>{E_ROCKET} Downloading video stream...</b>", parse_mode=enums.ParseMode.HTML)
        if not await asyncio.to_thread(_download_file_sync, video_url, raw_video):
            return await status.edit_text(f"<b>{E_CROSS} Video stream download failed.</b>", parse_mode=enums.ParseMode.HTML)

        await status.edit_text(f"<b>{E_ROCKET} Downloading audio stream...</b>", parse_mode=enums.ParseMode.HTML)
        if not await asyncio.to_thread(_download_file_sync, audio_url, raw_audio):
            return await status.edit_text(f"<b>{E_CROSS} Audio stream download failed.</b>", parse_mode=enums.ParseMode.HTML)

        await status.edit_text(f"<b>⚙️ Merging streams (ffmpeg)...</b>", parse_mode=enums.ParseMode.HTML)
        if not await asyncio.to_thread(_merge_streams, raw_video, raw_audio, merged):
            return await status.edit_text(
                f"<b>{E_CROSS} Merge failed.</b>\n<i>Is ffmpeg installed on the host?</i>",
                parse_mode=enums.ParseMode.HTML
            )

        has_thumb = await asyncio.to_thread(_extract_thumbnail, merged, thumb)
        duration, width, height = await asyncio.to_thread(_get_video_metadata, merged)

        await status.edit_text(f"<b>{E_ROCKET} Uploading...</b>", parse_mode=enums.ParseMode.HTML)
        await client.send_video(
            chat_id=message.chat.id,
            video=merged,
            thumb=thumb if has_thumb else None,
            duration=duration, width=width, height=height,
            caption=f"<b>{E_CHECK} Facebook Video</b>\n🆔 <code>{video_id}</code>",
            reply_to_message_id=message.id,
            supports_streaming=True,
            parse_mode=enums.ParseMode.HTML
        )
        await status.delete()
    except Exception as e:
        await status.edit_text(f"<b>{E_CROSS} Error:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        for f in (raw_video, raw_audio, merged, thumb):
            try:
                os.remove(f)
            except Exception:
                pass


# Registered in a SEPARATE handler group (1) so it runs independently of the
# main t.me link-saving handler in start.py — both get a chance to process
# the same message instead of one silently swallowing the other.
@Client.on_message(filters.text & filters.private & filters.regex(FB_PATTERN), group=1)
async def facebook_auto_detect(client: Client, message: Message):
    url = extract_fb_url(message.text)
    if url:
        await _handle_fb_download(client, message, url)


@Client.on_message(filters.command("fb") & filters.private)
async def fb_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/fb &lt;facebook video URL&gt;</code>\n"
            f"<i>Or just paste a facebook.com / fb.watch link directly.</i>",
            parse_mode=enums.ParseMode.HTML
        )
    url = extract_fb_url(message.command[1]) or message.command[1]
    await _handle_fb_download(client, message, url)
