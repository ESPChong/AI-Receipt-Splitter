# tg_bot.py
import os
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import requests

from ocr import extract_text_from_image
from ai_parser import parse_receipt_text
from split_calc import compute_splits

load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
APP = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hi! Send me a photo of a receipt and (optionally) a list of participants as a reply like: [Alice,Bob,Charlie]')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    photos = msg.photo
    if not photos:
        await msg.reply_text('No photo?')
        return
    file = await photos[-1].get_file()
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"{file.file_id}.jpg")
    await file.download_to_drive(path)

    # check if the user replied with participants in text
    participants = []
    if msg.reply_to_message and msg.reply_to_message.text:
        txt = msg.reply_to_message.text.strip()
        if txt.startswith('[') and txt.endswith(']'):
            try:
                participants = eval(txt)
            except Exception:
                participants = []

    ocr_text = extract_text_from_image(path)
    parsed = parse_receipt_text(ocr_text, participants)
    splits = compute_splits(parsed, participants)

    # build summary message
    lines = ['Here is the split:']
    for p, amt in splits.items():
        lines.append(f"{p}: {amt:.2f}")
    await msg.reply_text('\n'.join(lines))


if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print('Bot started (polling)')
    app.run_polling()