# bot.py
import os
import logging
from io import BytesIO

from flask import Flask, request, abort
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from PIL import Image

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable not set")

# Global application
application = Application.builder().token(TOKEN).build()

# Your existing handlers (copy-paste them here)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me any photo...\nThen reply with desired <b>width</b> in pixels",
        parse_mode="HTML"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (your full photo handling code here - copy from previous version)
    pass  # ← paste your code

async def handle_resize_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (your full resize logic here - copy from previous)
    pass  # ← paste your code

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_request))

# Flask app
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
async def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)
        if update:
            await application.process_update(update)
        return '', 200
    abort(403)

@app.route('/')
def index():
    return "Image Resizer Bot is running!"

if __name__ == "__main__":
    # Local testing
    import asyncio
    asyncio.run(application.run_polling())
