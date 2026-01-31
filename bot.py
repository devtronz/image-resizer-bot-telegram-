# bot.py

import os
import logging
from io import BytesIO

from quart import Quart, request, Response
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

application = Application.builder().token(TOKEN).build()

# Initialize & start application
async def init_app():
    await application.initialize()
    await application.start()
    logger.info("Application initialized and started")

# Run initialization at startup
import asyncio
asyncio.run(init_app())

# ──────────────────────────────────────────────── Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! 👋\n\n"
        "Send me any photo or image file.\n"
        "Then **reply** to this message with the desired <b>width</b> in pixels.\n"
        "(aspect ratio preserved)\n\n"
        "Examples:\n"
        "• 1080\n"
        "• 800\n"
        "• 500",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    photo = message.photo[-1] if message.photo else None
    document = message.document

    if not photo and not (document and document.mime_type and document.mime_type.startswith("image/")):
        await message.reply_text("Please send a photo or image file.")
        return

    file = await (photo.get_file() if photo else document.get_file())

    bio = BytesIO()
    try:
        await file.download_to_memory(out=bio, read_timeout=30, write_timeout=30, connect_timeout=30)
        bio.seek(0)
    except Exception as e:
        logger.warning(f"Download failed: {e}")
        await message.reply_text("Failed to download image. Try a smaller file.")
        return

    try:
        img = Image.open(bio)
        img.load()
    except Exception as e:
        logger.warning(f"Image open failed: {e}")
        await message.reply_text("Couldn't process this image 😔")
        return

    context.user_data["last_image"] = img.copy()
    context.user_data["last_image_format"] = img.format or "JPEG"

    await message.reply_text(
        f"Image received! Original: <b>{img.width} × {img.height}</b>\n\n"
        "Reply to <b>this</b> message with desired <b>width</b> (10–8000).",
        parse_mode="HTML"
    )


async def handle_resize_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message.reply_to_message:
        return

    img: Image.Image = context.user_data.get("last_image")
    if not img:
        await message.reply_text("No recent image found. Send a photo first.")
        return

    try:
        width = int(message.text.strip())
        if width < 10 or width > 12000:
            raise ValueError
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
        await message.reply_text("Resizing failed 😓")
        return

    bio = BytesIO()
    fmt = context.user_data.get("last_image_format", "JPEG")
    resized.save(bio, format=fmt, quality=85, optimize=True)
    bio.name = f"resized.{fmt.lower()}"
    bio.seek(0)

    await message.reply_document(
        document=bio,
        filename=bio.name,
        caption=f"Resized → {width} × {height}"
    )

    context.user_data.pop("last_image", None)
    context.user_data.pop("last_image_format", None)


# ──────────────────────────────────────────────── Quart App

app = Quart(__name__)

@app.route('/')
async def index():
    return "Image Resizer Bot is running"


@app.route('/webhook', methods=['POST'])
async def webhook():
    if request.headers.get('content-type') != 'application/json':
        return Response("Bad request", status=400)

    json_data = await request.get_json()
    if json_data:
        update = Update.de_json(json_data, application.bot)
        if update:
            try:
                logger.info(f"Processing update {update.update_id}")
                await application.process_update(update)
                logger.info(f"Update {update.update_id} processed")
            except Exception as e:
                logger.error("Update processing error", exc_info=True)
                try:
                    if update.effective_message:
                        await update.effective_message.reply_text(
                            "Something went wrong – please try again later 😔"
                        )
                except Exception:
                    pass  # best effort

    return Response(status=200)


# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resize_request))


# Local polling for testing
if __name__ == "__main__":
    import asyncio
    asyncio.run(application.run_polling(drop_pending_updates=True))