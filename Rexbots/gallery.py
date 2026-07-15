import os
import glob
import shutil
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import make_output_folder, upload_file, E_CHECK, E_CROSS, E_INFO

GALLERY_SITES = [
    "twitter.com", "x.com", "pinterest.com", "pixiv.net", "deviantart.com",
    "artstation.com", "flickr.com", "tumblr.com", "reddit.com", "imgur.com",
    "danbooru.donmai.us", "gelbooru.com", "konachan.com", "yande.re",
    "safebooru.org", "zerochan.net", "furaffinity.net", "bsky.app",
]


def extract_url(text: str):
    text = text.strip()
    if not text.startswith("http"):
        return None
    lower = text.lower()
    return text if any(site in lower for site in GALLERY_SITES) else None


def _gallery_dl_available() -> bool:
    return shutil.which("gallery-dl") is not None


async def _handle(client: Client, message: Message, url: str):
    status = await message.reply_text(f"<b>{E_INFO} Gallery link detected...</b>", parse_mode=enums.ParseMode.HTML)

    if not _gallery_dl_available():
        return await status.edit_text(
            f"<b>{E_CROSS} 'gallery-dl' is not installed.</b>\n"
            f"<i>Install it first: <code>pip install gallery-dl</code></i>",
            parse_mode=enums.ParseMode.HTML
        )

    base = make_output_folder("gallery")
    gallery_dir = os.path.join(base, f"g_{message.id}")
    os.makedirs(gallery_dir, exist_ok=True)

    await status.edit_text(f"<b>{E_INFO} Downloading gallery...</b>", parse_mode=enums.ParseMode.HTML)

    cmd = ["gallery-dl", "--directory", gallery_dir, "--no-mtime", url]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()[:300] or f"gallery-dl exited with code {proc.returncode}"
        return await status.edit_text(f"<b>{E_CROSS} Gallery download failed:</b>\n<code>{err}</code>", parse_mode=enums.ParseMode.HTML)

    exts = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.mp4", "*.webm", "*.mkv")
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(gallery_dir, "**", ext), recursive=True))
    files.sort()

    if not files:
        return await status.edit_text(f"<b>{E_CROSS} No media found at this link.</b>", parse_mode=enums.ParseMode.HTML)

    total = len(files)
    for i, path in enumerate(files, 1):
        fname = os.path.basename(path)
        await upload_file(client, message, path, status, f"<b>{E_CHECK} Gallery ({i}/{total})</b>\n<code>{fname}</code>")
        if i < total:
            status = await message.reply_text(f"<b>{E_INFO} Uploading {i + 1}/{total}...</b>", parse_mode=enums.ParseMode.HTML)

    shutil.rmtree(gallery_dir, ignore_errors=True)


@Client.on_message(filters.command("gallery") & filters.private)
async def gallery_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/gallery &lt;twitter/pinterest/reddit/... URL&gt;</code>\n"
            f"<i>Auto-detection is off for this one to avoid clashing with normal chat links — "
            f"use the command directly.</i>",
            parse_mode=enums.ParseMode.HTML
        )
    url = extract_url(message.command[1]) or message.command[1]
    await _handle(client, message, url)
