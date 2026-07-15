import os
import re
import shutil
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import upload_file, E_CHECK, E_CROSS, E_INFO

MAGNET_PATTERN = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+\S*")
TORRENT_URL_PATTERN = re.compile(r"https?://\S+\.torrent", re.IGNORECASE)


def extract_link(text: str):
    m = MAGNET_PATTERN.search(text) or TORRENT_URL_PATTERN.search(text)
    return m.group(0) if m else None


def _aria2c_available() -> bool:
    return shutil.which("aria2c") is not None


async def _handle(client: Client, message: Message, link: str):
    status = await message.reply_text(f"<b>{E_INFO} Torrent/magnet link detected...</b>", parse_mode=enums.ParseMode.HTML)

    if not _aria2c_available():
        return await status.edit_text(
            f"<b>{E_CROSS} 'aria2c' is not installed on this host.</b>\n"
            f"<i>Install it first (Debian/Ubuntu: <code>apt install aria2</code>) "
            f"then torrent/magnet links will work.</i>",
            parse_mode=enums.ParseMode.HTML
        )

    # Unique per-task folder — prevents concurrent downloads from different
    # users/messages colliding or getting mixed up in a shared directory.
    folder = os.path.join("downloads", "torrent", f"task_{message.id}")
    os.makedirs(folder, exist_ok=True)

    cmd = [
        "aria2c",
        f"--dir={folder}",
        "--seed-time=0",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--continue=true",
        "--summary-interval=5",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        "--console-log-level=warn",
        link,
    ]

    await status.edit_text(f"<b>{E_INFO} Downloading via aria2c...</b>\n<i>(no live progress in this mode)</i>", parse_mode=enums.ParseMode.HTML)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()[:300] or f"aria2c exited with code {proc.returncode}"
        shutil.rmtree(folder, ignore_errors=True)
        return await status.edit_text(f"<b>{E_CROSS} Torrent download failed:</b>\n<code>{err}</code>", parse_mode=enums.ParseMode.HTML)

    files = []
    for root, _, fnames in os.walk(folder):
        for f in fnames:
            if f.endswith(('.aria2',)):  # skip aria2 control files
                continue
            files.append(os.path.join(root, f))
    files.sort()

    if not files:
        shutil.rmtree(folder, ignore_errors=True)
        return await status.edit_text(f"<b>{E_CROSS} No file was downloaded.</b>", parse_mode=enums.ParseMode.HTML)

    for i, path in enumerate(files):
        fname = os.path.basename(path)
        await upload_file(client, message, path, status, f"<b>{E_CHECK} Torrent File</b>\n<code>{fname}</code>")
        if i < len(files) - 1:
            status = await message.reply_text(f"<b>{E_INFO} Uploading next file...</b>", parse_mode=enums.ParseMode.HTML)

    shutil.rmtree(folder, ignore_errors=True)


@Client.on_message(filters.text & filters.private & filters.regex(MAGNET_PATTERN), group=1)
async def torrent_auto_detect_magnet(client: Client, message: Message):
    link = extract_link(message.text)
    if link:
        await _handle(client, message, link)


@Client.on_message(filters.command("torrent") & filters.private)
async def torrent_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/torrent &lt;magnet link or .torrent URL&gt;</code>",
            parse_mode=enums.ParseMode.HTML
        )
    link = extract_link(message.command[1]) or message.command[1]
    await _handle(client, message, link)
