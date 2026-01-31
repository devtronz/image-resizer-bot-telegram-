# bot.py

import os
import logging
import asyncio
from concurrent.futures import TimeoutError
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

# ──────────────────────────────────────────────── Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────── Config
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set")

# Build application
application = Application.builder().token(TOKEN).build()

# Persistent event loop
loop = asyncio.get_event_loop()

# Initialize & start once at startup
loop.run_until_complete(application.initialize())
loop.run_until_complete(application.start())

# Optional shutdown (good practice)
import atexit
def shutdown():
    loop.run_until_complete(application.stop())
    loop.run_until_complete(application.shutdown())
atexit.register(shutdown)

# ──────────────────────────────────────────────── Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! 👋\n\n"
        "Send me a photo or image file.\n"
        "Then **reply** to my message with the desired <b>width</b> in pixels "
        "(aspect ratio will be preserved).\n\n"
        "Examples: <code>1080</code>  <code>800</code>  <code>500</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

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
        img.load()
    except Exception as e:
        logger.warning(f"Failed to open image: {e}")
        await message.reply_text("Sorry, I couldn't process this image 😔")
        return

    context.user_data["last_image"] = img.copy()
    context.user_data["last_image_format"] = img.format or "JPEG"

    await message.reply_text(
        f"Image received! Original size: <b>{img.width} × {img.height}</b>\n\n"
        "Reply to <b>this</b> message with the desired <b>width</b> in pixels.\n"
        "(recommended: 10–8000)",
        parse_mode="HTML"
    )


async def handle_resize_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message.reply_to_message:
        return

    img: Image.Image = context.user_data.get("last_image")
    if not img:
        await message.reply_text("No recent image found. Please send a photo first.")
        return

    try:
        width = int(message.text.strip())
        if width < 10 or width > 12000:
            raise ValueError("Size out of range")
    except ValueError:
        await message.reply_text("Please send a number between 10 and 12000.")
        return

    height = int(img.height * (width / img.width))
    if height < 1:
        height = 1

    try:
        resized = img.resize((width, height), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.error(f"Resize failed: {e}")
        await message.reply_text("Sorry, resizing failed 😓")
        return

    bio = BytesIO()
    fmt = context.user_data.get("last_image_format", "JPEG")
    resized.save(bio, format=fmt, quality=92, optimize=True)
    bio.name = f"resized.{fmt.lower()}"
    bio.seek(0)

    await message.reply_document(
        document=bio,
        filename=bio.name,
        caption=f"Resized to {width} × {height}"
    )

    # Cleanup
    context.user_data.pop("last_image", None)
    context.user_data.pop("last_image_format", None)


# ──────────────────────────────────────────────── Flask App

flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "Image Resizer Bot is running"


@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        return Response("Bad request", status=400)

    json_data = request.get_json(silent=True)
    if not json_data:
        return Response(status=200)

    update = Update.de_json(json_data, application.bot)
    if not update:
        return Response(status=200)

    try:
        logger.info(f"Processing update {update.update_id} from {update.effective_user.id if update.effective_user else 'unknown'}")

        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            loop
        )

        # Increased timeout – Render cold start + large photo can take time
        future.result(timeout=60)

        logger.info(f"Update {update.update_id} processed successfully")

    except TimeoutError:
        logger.warning(f"Update {update.update_id} timed out after 60 seconds")
        # Try to send error message if possible
        try:
            if update.effective_message:
                err_future = asyncio.run_coroutine_threadsafe(
                    update.effective_message.reply_text("Processing took too long – please try again 😔"),
                    loop
                )
                err_future.result(timeout=10)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error processing update {update.update_id}", exc_info=True)
        # Try fallback reply
        try:
            if update.effective_message:
                err_future = asyncio.run_coroutine_threadsafe(
                    update.effective_message.reply_text("Something went wrong – try again later"),
                    loop
                )
                err_future.result(timeout=10)
        except Exception:
            pass

    return Response(status=200)


# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_request))


# Local testing (polling mode)
if __name__ == "__main__":
    print("Starting polling mode for local testing...")
    asyncio.run(application.run_polling(drop_pending_updates=True))