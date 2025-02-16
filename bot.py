import logging
import os
import qrcode
import sqlite3
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Этапы диалога:
# DESIGN - выбор темы или загрузка фото
# PHOTO_UPLOAD - загрузка фото для фона (если выбрана опция "Загрузить своё фото")
# PAGE1, PAGE2, PAGE3 - ввод текста страниц
# SENDER - ввод имени (или псевдонима) отправителя
# TIMES - варианты времени для приглашения
DESIGN, PHOTO_UPLOAD, PAGE1, PAGE2, PAGE3, SENDER, TIMES = range(7)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

PUBLIC_URL = "https://svety.uz"  # публичный URL (с HTTPS)
DB_PATH = "app.db"

def create_table_if_not_exists():
    """Создаёт таблицу invitations с нужными полями, если её нет."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS invitations (
            id TEXT PRIMARY KEY,
            design TEXT,
            bg_image TEXT,
            page1 TEXT,
            page2 TEXT,
            page3 TEXT,
            sender TEXT,
            times TEXT,
            chat_id TEXT
        )
    ''')
    conn.commit()
    conn.close()

create_table_if_not_exists()

# Создаем новый event loop для работы с асинхронными операциями Telegram
loop = asyncio.new_event_loop()
def run_loop(loop):
    import asyncio
    asyncio.set_event_loop(loop)
    loop.run_forever()

import asyncio
import threading
threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

def send_message_sync(chat_id, message):
    """Отправляет сообщение в Telegram, используя глобальный event loop."""
    future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id=chat_id, text=message),
        loop
    )
    return future.result(timeout=10)

def get_invitation(invite_id):
    """Получает данные приглашения из БД и возвращает их в виде словаря."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT design, bg_image, page1, page2, page3, sender, times, chat_id FROM invitations WHERE id = ?', (invite_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": invite_id,
            "design": row[0],
            "bg_image": row[1],
            "page1": row[2],
            "page2": row[3],
            "page3": row[4],
            "sender": row[5],
            "times": row[6].split("\n"),
            "chat_id": row[7]
        }
    return None

def save_invitation(design, bg_image, page1, page2, page3, sender, times, chat_id):
    """
    Сохраняет данные приглашения в БД.
    Возвращает сгенерированный invite_id (UUID).
    """
    invite_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO invitations (id, design, bg_image, page1, page2, page3, sender, times, chat_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        invite_id,
        design,
        bg_image,
        page1,
        page2,
        page3,
        sender,
        "\n".join(times),
        str(chat_id)
    ))
    conn.commit()
    conn.close()
    return invite_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Стартовая точка: предлагаем выбрать тему оформления или загрузить своё фото."""
    await update.message.reply_text(
        "Привет! Давай создадим красивое приглашение на свидание!\n\n"
        "Для начала выбери тему оформления или загрузи своё фото для фона:"
    )
    keyboard = [
        [InlineKeyboardButton("🎆 Элегантная ночь", callback_data="design_elegant")],
        [InlineKeyboardButton("🌹 Романтика", callback_data="design_romantic")],
        [InlineKeyboardButton("🎶 Музыка и кино", callback_data="design_music")],
        [InlineKeyboardButton("🖼 Загрузить своё фото", callback_data="design_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери вариант:", reply_markup=reply_markup)
    return DESIGN

async def design_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем выбранную тему. Если выбрано 'Загрузить своё фото' - переходим к загрузке, иначе устанавливаем фон из предопределённого набора."""
    query = update.callback_query
    await query.answer()
    choice = query.data
    context.user_data["design"] = choice

    if choice == "design_custom":
        await query.edit_message_text(
            text="Пожалуйста, отправь фотографию, которую хочешь использовать в качестве фона."
        )
        return PHOTO_UPLOAD
    else:
        # Предопределенные фоны для выбранных тем (администратор добавляет эти фото в папку static/designs)
        predefined_bg_images = {
            "design_elegant": "designs/elegant.jpg",
            "design_romantic": "designs/romantic.jpg",
            "design_music": "designs/music.jpg"
        }
        # Устанавливаем значение bg_image из словаря для выбранного дизайна
        context.user_data["bg_image"] = predefined_bg_images.get(choice, "")
        await query.edit_message_text(
            text=(
                "Отлично! Теперь введи **первую страницу** текста.\n\n"
                "Например:\n"
                "«Дорогая Настя! Хочу сказать, что ты... (и т.д.)»"
            )
        )
        return PAGE1

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатываем загруженное фото, сохраняем его и переходим к вводу текста."""
    if not update.message.photo:
        await update.message.reply_text("Это не фотография. Пожалуйста, отправь фото.")
        return PHOTO_UPLOAD

    photo = update.message.photo[-1]  # выбираем фото в наилучшем разрешении
    file = await photo.get_file()
    filename = f"{uuid.uuid4()}.jpg"
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    await file.download_to_drive(file_path)
    context.user_data["bg_image"] = "uploads/" + filename  # сохраняем путь относительно static/

    await update.message.reply_text(
        "Фото успешно загружено! Теперь введи **первую страницу** текста."
    )
    return PAGE1

async def get_page1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем текст первой страницы, переходим ко второй."""
    page1_text = update.message.text.strip()
    context.user_data["page1"] = page1_text

    await update.message.reply_text(
        "Хорошо! Теперь введи **вторую страницу**.\n\n"
        "Например:\n"
        "«Ты мне очень нравишься, и я решил(а) подготовить кое-что особенное... (и т.д.)»"
    )
    return PAGE2

async def get_page2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем текст второй страницы, переходим к третьей."""
    page2_text = update.message.text.strip()
    context.user_data["page2"] = page2_text

    await update.message.reply_text(
        "Отлично! Теперь введи **третью страницу** — само приглашение.\n\n"
        "Например:\n"
        "«Я хочу провести с тобой особенный вечер... Давай встретимся... (и т.д.)»"
    )
    return PAGE3

async def get_page3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем текст третьей страницы, переходим к вводу имени отправителя."""
    page3_text = update.message.text.strip()
    context.user_data["page3"] = page3_text

    await update.message.reply_text(
        "Прекрасно! Теперь введи своё имя или псевдоним, от кого это письмо."
    )
    return SENDER

async def get_sender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем имя отправителя и переходим к вводу вариантов времени."""
    sender_text = update.message.text.strip()
    context.user_data["sender"] = sender_text

    await update.message.reply_text(
        f"Отлично, {sender_text}! Теперь укажи 3 варианта времени (каждый с новой строки). Например:\n\n"
        "🕗 19:00 | 21 января\n"
        "🌙 20:30 | 22 января\n"
        "☕ 17:00 | 23 января"
    )
    return TIMES

async def get_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем варианты времени, генерируем ссылку и QR-код."""
    times_text = update.message.text
    times_list = [line.strip() for line in times_text.splitlines() if line.strip()]

    design = context.user_data.get("design", "design_elegant")
    bg_image = context.user_data.get("bg_image", "")
    page1 = context.user_data.get("page1", "")
    page2 = context.user_data.get("page2", "")
    page3 = context.user_data.get("page3", "")
    sender = context.user_data.get("sender", "")
    chat_id = update.effective_chat.id

    invite_id = save_invitation(design, bg_image, page1, page2, page3, sender, times_list, chat_id)

    # Формируем URL приглашения
    invite_url = f"{PUBLIC_URL}/invite/{invite_id}"

    # Генерируем QR-код
    img = qrcode.make(invite_url)
    img_path = "invite_qr.png"
    img.save(img_path)

    with open(img_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                f"Приглашение готово!\n\n"
                f"Вот твоя ссылка: {invite_url}\n\n"
                f"Отправь её возлюбленной (или покажи QR-код)."
            )
        )

    os.remove(img_path)
    return ConversationHandler.END

def main():
    """Запуск бота."""
    BOT_TOKEN = "8046219766:AAGFsWXIFTEPe8aaTBimVyWm2au2f-uIYSs"  # замените на ваш токен

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DESIGN: [CallbackQueryHandler(design_choice)],
            PHOTO_UPLOAD: [MessageHandler(filters.PHOTO, handle_photo_upload)],
            PAGE1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page1)],
            PAGE2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page2)],
            PAGE3: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page3)],
            SENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sender)],
            TIMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_times)]
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
