import os
import time
import shutil
import asyncio
import uuid
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from config import YTDL_MAX_FILESIZE, YT_COOKIES, INSTA_COOKIES

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

E_ROCKET = '<emoji id=5456140674028019486>🚀</emoji>'
E_CROSS  = '<emoji id=5210952531676504517>❌</emoji>'
E_CHECK  = '<emoji id=5206607081334906820>✔️</emoji>'
E_BOLT   = '<emoji id=5456140674028019486>⚡️</emoji>'

DOWNLOAD_DIR = "yt_downloads"


def _cookies_for(url: str):
    if "instagram.com" in url and INSTA_COOKIES and os.path.exists(INSTA_COOKIES):
        return INSTA_COOKIES
    if YT_COOKIES and os.path.exists(YT_COOKIES):
        return YT_COOKIES
    return None


def _download(url: str, out_dir: str, audio_only: bool) -> str:
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(title).80s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": YTDL_MAX_FILESIZE,
    }
    cookies = _cookies_for(url)
    if cookies:
        ydl_opts["cookiefile"] = cookies

    if audio_only:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"
        }]
    else:
        ydl_opts["format"] = f"best[filesize<{YTDL_MAX_FILESIZE}]/best"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info) if not audio_only else \
            os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3"


async def _run(client: Client, message: Message, url: str, audio_only: bool):
    if yt_dlp is None:
        return await message.reply_text(
            f"<b>{E_CROSS} yt-dlp not installed.</b>\n<i>Run <code>pip install yt-dlp</code> on the host.</i>",
            parse_mode=enums.ParseMode.HTML
        )

    session_dir = os.path.join(DOWNLOAD_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)
    status = await message.reply_text(
        f"<b>{E_ROCKET} Downloading...</b>", parse_mode=enums.ParseMode.HTML
    )

    try:
        filepath = await asyncio.get_event_loop().run_in_executor(
            None, _download, url, session_dir, audio_only
        )
        if not os.path.exists(filepath):
            raise FileNotFoundError("Download finished but file was not found (likely size limit).")

        size = os.path.getsize(filepath)
        if size > YTDL_MAX_FILESIZE:
            raise ValueError(f"File too large ({round(size / (1024*1024))} MB) to upload to Telegram.")

        await status.edit_text(f"<b>{E_BOLT} Uploading...</b>", parse_mode=enums.ParseMode.HTML)
        caption = f"<b>{E_CHECK} Downloaded via yt-dlp</b>"
        if audio_only:
            await client.send_audio(message.chat.id, filepath, caption=caption,
                                     reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_video(message.chat.id, filepath, caption=caption,
                                     reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML,
                                     supports_streaming=True)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"<b>{E_CROSS} Download failed:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


@Client.on_message(filters.command(["yt", "dl"]) & filters.private)
async def yt_video_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_BOLT} Usage:</b> <code>/yt &lt;video URL&gt;</code>\n"
            f"<i>Supports YouTube, Instagram, and most yt-dlp-compatible sites.</i>",
            parse_mode=enums.ParseMode.HTML
        )
    await _run(client, message, message.command[1], audio_only=False)


@Client.on_message(filters.command(["yta", "song", "adl"]) & filters.private)
async def yt_audio_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_BOLT} Usage:</b> <code>/yta &lt;video URL&gt;</code> — extracts audio (mp3)",
            parse_mode=enums.ParseMode.HTML
        )
    await _run(client, message, message.command[1], audio_only=True)
