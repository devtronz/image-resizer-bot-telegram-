# bot.py

import os
import logging
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
import asyncio

# ──────────────────────────────────────── Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────── Config
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set")

# Create global application
application = Application.builder().token(TOKEN).build()

# ──────────────────────────────────────── Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me any photo or image file.\n"
        "Then **reply** to my message with the desired <b>width</b> in pixels\n"
        "(aspect ratio will be preserved)\n\n"
        "Examples:  <code>800</code>   <code>1080</code>   <code>500</code>",
        parse_mode="HTML"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    photo = message.photo[-1] if message.photo else None
    document = message.document

    if not photo and not (document and document.mime_type and document.mime_type.startswith("image/")):
        await message.reply_text("Please send a photo or an image file.")
        return

    # Download file
    if photo:
        file = await photo.get_file()
    else:
        file = await document.get_file()

    bio = BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)

    try:
        img = Image.open(bio)
        img.load()  # force load
    except Exception as e:
        logger.warning(f"Failed to open image: {e}")
        await message.reply_text("Sorry, I couldn't open this image 😔")
        return

    # Store in user_data
    context.user_data["last_image"] = img
    context.user_data["last_image_format"] = img.format or "JPEG"

    reply_text = (
        f"Image received! Original size: {img.width} × {img.height}\n\n"
        "Reply to <b>this</b> message with the desired <b>width</b> (in pixels).\n"
        "I will keep the aspect ratio."
    )
    await message.reply_text(reply_text, parse_mode="HTML")


async def handle_resize_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if not message.reply_to_message:
        return  # not a reply → ignore

    img: Image.Image = context.user_data.get("last_image")
    if not img:
        await message.reply_text("No recent image found. Please send a photo first.")
        return

    try:
        width = int(message.text.strip())
        if width < 10 or width > 12000:
            raise ValueError("Width out of reasonable range")
    except Exception:
        await message.reply_text("Please send a valid number (10–12000)")
        return

    # Calculate height (keep aspect ratio)
    ratio = width / img.width
    height = int(img.height * ratio)

    if height < 1:
        height = 1

    # Resize
    resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

    # Prepare output
    output_bio = BytesIO()
    format_ = context.user_data.get("last_image_format", "JPEG")
    resized_img.save(output_bio, format=format_, quality=92, optimize=True)
    output_bio.name = f"resized.{format_.lower()}"
    output_bio.seek(0)

    await message.reply_document(
        document=output_bio,
        filename=output_bio.name,
        caption=f"Resized to {width} × {height}"
    )

    # Clean up
    if "last_image" in context.user_data:
        del context.user_data["last_image"]
    if "last_image_format" in context.user_data:
        del context.user_data["last_image_format"]


# ──────────────────────────────────────── Flask app

app = Flask(__name__)

@app.route('/')
def index():
    return "Image Resizer Bot is running!"


@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json(silent=True)
        if json_data:
            update = Update.de_json(json_data, application.bot)
            if update:
                try:
                    asyncio.run(application.process_update(update))
                except Exception as e:
                    logger.error("Error while processing update", exc_info=True)
                    # We still return 200 so Telegram doesn't keep retrying
        return Response(status=200)

    return Response("Wrong content type", status=403)


# Register handlers (must be after app definition but before running)
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_request))


# For local testing only
if __name__ == "__main__":
    import asyncio
    asyncio.run(application.run_polling(allowed_updates=Update.ALL_TYPES))