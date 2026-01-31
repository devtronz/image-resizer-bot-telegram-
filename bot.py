# bot.py

import os
import logging
import asyncio
from io import BytesIO

from flask import Flask, request, Response
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from PIL import Image

# ────────────────────────────────────────────────
# Logging setup
# ────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Configuration & Application initialization
# ────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set")

# Build application
application = Application.builder().token(TOKEN).build()

# VERY IMPORTANT for webhook mode
asyncio.run(application.initialize())
asyncio.run(application.start())

# You can also add shutdown later if needed:
# import atexit
# atexit.register(lambda: asyncio.run(application.stop()))
# atexit.register(lambda: asyncio.run(application.shutdown()))

# ────────────────────────────────────────────────
# Handlers
# ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message"""
    await update.message.reply_text(
        "Hi! 👋\n\n"
        "Send me a photo or image file.\n"
        "Then **reply** to my response with the desired <b>width</b> in pixels "
        "(I will keep the aspect ratio).\n\n"
        "Examples:\n"
        "• <code>1080</code>\n"
        "• <code>800</code>\n"
        "• <code>500</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive photo / image document and ask for width"""
    message = update.message

    # Get highest quality photo or document
    photo = message.photo[-1] if message.photo else None
    document = message.document

    if not photo and not (document and document.mime_type and document.mime_type.startswith("image/")):
        await message.reply_text("Please send a photo or an image file.")
        return

    file = await (photo.get_file() if photo else document.get_file())

    bio = BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)

    try:
        img = Image.open(bio)
        img.load()  # make sure it's loaded
    except Exception as e:
        logger.warning(f"Cannot open image: {e}")
        await message.reply_text("Sorry, I couldn't process this image 😔")
        return

    # Store image in context
    context.user_data["last_image"] = img.copy()  # copy to be safe
    context.user_data["last_image_format"] = img.format or "JPEG"

    await message.reply_text(
        f"Got it! Original: <b>{img.width} × {img.height}</b>\n\n"
        "Now reply to <b>this</b> message with the desired <b>width</b> in pixels.\n"
        "(10–8000 recommended)",
        parse_mode="HTML"
    )


async def handle_resize_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resize image when user replies with a number"""
    message = update.message

    if not message.reply_to_message:
        return  # ignore messages that are not replies

    img: Image.Image = context.user_data.get("last_image")
    if not img:
        await message.reply_text("No recent image found. Please send a photo first.")
        return

    try:
        width = int(message.text.strip())
        if width < 10 or width > 12000:
            raise ValueError("unreasonable size")
    except ValueError:
        await message.reply_text("Please send a number between 10 and 12000.")
        return

    # Calculate new height
    new_height = int(img.height * (width / img.width))
    if new_height < 1:
        new_height = 1

    try:
        resized = img.resize((width, new_height), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.error(f"Resize failed: {e}")
        await message.reply_text("Sorry, resizing failed 😓")
        return

    # Prepare to send
    bio = BytesIO()
    fmt = context.user_data.get("last_image_format", "JPEG")
    resized.save(bio, format=fmt, quality=92, optimize=True)
    bio.name = f"resized.{fmt.lower()}"
    bio.seek(0)

    await message.reply_document(
        document=bio,
        filename=bio.name,
        caption=f"Resized to {width} × {new_height}"
    )

    # Cleanup
    context.user_data.pop("last_image", None)
    context.user_data.pop("last_image_format", None)


# ────────────────────────────────────────────────
# Flask application
# ────────────────────────────────────────────────

flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "Image Resizer Bot is alive 🚀"


@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json(silent=True)
        if json_data:
            update = Update.de_json(json_data, application.bot)
            if update:
                try:
                    asyncio.run(application.process_update(update))
                except Exception as e:
                    logger.error("Error processing update", exc_info=True)
                    # We return 200 anyway → Telegram won't retry endlessly
        return Response(status=200)

    return Response("Bad request", status=400)


# Register all handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(
    filters.PHOTO | filters.Document.IMAGE,
    handle_photo
))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    handle_resize_request
))


# Local development (polling mode)
if __name__ == "__main__":
    print("Starting polling mode for local development...")
    asyncio.run(application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    ))