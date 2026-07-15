import os
import re
import shutil
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import upload_file, E_CHECK, E_CROSS, E_INFO

PATTERN = re.compile(r"(https?://)?(www\.)?mega\.nz/\S+", re.IGNORECASE)


def extract_url(text: str):
    m = PATTERN.search(text)
    return m.group(0) if m else None


def _megatools_available() -> bool:
    return shutil.which("megadl") is not None


async def _handle(client: Client, message: Message, url: str):
    status = await message.reply_text(f"<b>{E_INFO} Mega.nz link detected...</b>", parse_mode=enums.ParseMode.HTML)

    if not _megatools_available():
        return await status.edit_text(
            f"<b>{E_CROSS} 'megatools' is not installed on this host.</b>\n"
            f"<i>Install it first (Debian/Ubuntu: <code>apt install megatools</code>) "
            f"then this link will work.</i>",
            parse_mode=enums.ParseMode.HTML
        )

    # Unique per-task folder — prevents concurrent downloads from different
    # users/messages colliding or getting mixed up in a shared directory.
    folder = os.path.join("downloads", "mega", f"task_{message.id}")
    os.makedirs(folder, exist_ok=True)

    await status.edit_text(f"<b>{E_INFO} Downloading via megatools...</b>", parse_mode=enums.ParseMode.HTML)
    proc = await asyncio.create_subprocess_exec(
        "megadl", "--no-ask-password", "--path", folder, url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()[:300] or "Unknown megatools error"
        shutil.rmtree(folder, ignore_errors=True)
        return await status.edit_text(f"<b>{E_CROSS} Mega download failed:</b>\n<code>{err}</code>", parse_mode=enums.ParseMode.HTML)

    new_files = []
    for root, _, fnames in os.walk(folder):
        for f in fnames:
            new_files.append(os.path.join(root, f))

    if not new_files:
        shutil.rmtree(folder, ignore_errors=True)
        return await status.edit_text(f"<b>{E_CROSS} No file was downloaded.</b>", parse_mode=enums.ParseMode.HTML)

    new_files.sort()
    for i, path in enumerate(new_files):
        fname = os.path.basename(path)
        await upload_file(client, message, path, status, f"<b>{E_CHECK} Mega File</b>\n<code>{fname}</code>")
        if i < len(new_files) - 1:
            status = await message.reply_text(f"<b>{E_INFO} Uploading next file...</b>", parse_mode=enums.ParseMode.HTML)

    shutil.rmtree(folder, ignore_errors=True)


@Client.on_message(filters.text & filters.private & filters.regex(PATTERN), group=1)
async def mega_auto_detect(client: Client, message: Message):
    url = extract_url(message.text)
    if url:
        await _handle(client, message, url)


@Client.on_message(filters.command("mega") & filters.private)
async def mega_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/mega &lt;mega.nz URL&gt;</code>",
            parse_mode=enums.ParseMode.HTML
        )
    url = extract_url(message.command[1]) or message.command[1]
    await _handle(client, message, url)
