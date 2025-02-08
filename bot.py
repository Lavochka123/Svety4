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
    ContextTypes
)

# Этапы диалога
DESIGN, PAGE1, PAGE2, PAGE3, TIMES = range(5)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

PUBLIC_URL = "http://svety.uz"  # Ваш домен
DB_PATH = "app.db"

def create_table_if_not_exists():
    """Создаёт таблицу invitations с нужными полями, если её нет."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS invitations (
            id TEXT PRIMARY KEY,
            design TEXT,
            page1 TEXT,
            page2 TEXT,
            page3 TEXT,
            times TEXT,
            chat_id TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_invitation(design, page1, page2, page3, times, chat_id):
    """
    Сохраняет все тексты (page1, page2, page3) + times в БД.
    Возвращает сгенерированный invite_id (UUID).
    """
    invite_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO invitations (id, design, page1, page2, page3, times, chat_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        invite_id,
        design,
        page1,
        page2,
        page3,
        "\n".join(times),
        str(chat_id)
    ))
    conn.commit()
    conn.close()
    return invite_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Стартовая точка: предлагаем выбрать дизайн."""
    create_table_if_not_exists()

    await update.message.reply_text(
        "Привет! Давай создадим красивое приглашение на свидание!\n\n"
        "Для начала выбери дизайн открытки:"
    )
    keyboard = [
        [InlineKeyboardButton("🎆 Элегантная ночь", callback_data="design_elegant")],
        [InlineKeyboardButton("🌹 Романтика", callback_data="design_romantic")],
        [InlineKeyboardButton("🎶 Музыка и кино", callback_data="design_music")],
        [InlineKeyboardButton("💡 Минимализм", callback_data="design_minimal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери вариант:", reply_markup=reply_markup)
    return DESIGN

async def design_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем выбранный дизайн, переходим к Page1."""
    query = update.callback_query
    await query.answer()
    context.user_data["design"] = query.data

    await query.edit_message_text(
        text=(
            "Отлично! Теперь введи **первую страницу** текста.\n\n"
            "Например:\n"
            "«Дорогая Настя! Хочу сказать, что ты... (и т.д.)»"
        )
    )
    return PAGE1

async def get_page1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем введённый текст Page1, переходим к Page2."""
    page1_text = update.message.text.strip()
    context.user_data["page1"] = page1_text

    await update.message.reply_text(
        "Хорошо! Теперь введи **вторую страницу**.\n\n"
        "Например:\n"
        "«Ты мне очень нравишься, и я решил(а) подготовить кое-что особенное... (и т.д.)»"
    )
    return PAGE2

async def get_page2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем Page2, переходим к Page3."""
    page2_text = update.message.text.strip()
    context.user_data["page2"] = page2_text

    await update.message.reply_text(
        "Отлично! Теперь введи **третью страницу** — само приглашение.\n\n"
        "Например:\n"
        "«Я хочу провести с тобой особенный вечер... Давай встретимся... (и т.д.)»"
    )
    return PAGE3

async def get_page3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем Page3, переходим к выбору времени."""
    page3_text = update.message.text.strip()
    context.user_data["page3"] = page3_text

    await update.message.reply_text(
        "Здорово! Наконец, укажи 3 варианта времени (каждый с новой строки). Например:\n\n"
        "🕗 19:00 | 21 января\n"
        "🌙 20:30 | 22 января\n"
        "☕ 17:00 | 23 января"
    )
    return TIMES

async def get_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняем варианты времени, генерируем ссылку."""
    times_text = update.message.text
    times_list = [line.strip() for line in times_text.splitlines() if line.strip()]

    design = context.user_data.get("design", "design_elegant")
    page1 = context.user_data.get("page1", "")
    page2 = context.user_data.get("page2", "")
    page3 = context.user_data.get("page3", "")
    chat_id = update.effective_chat.id

    invite_id = save_invitation(design, page1, page2, page3, times_list, chat_id)

    # Формируем короткий URL
    invite_url = f"{PUBLIC_URL}/invite/{invite_id}"

    # Генерация QR-кода
    img = qrcode.make(invite_url)
    img_path = "invite_qr.png"
    img.save(img_path)

    # Отправляем QR-код и ссылку
    with open(img_path, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=(
                f"Приглашение готово!\n\n"
                f"Вот твоя ссылка: {invite_url}\n\n"
                f"Отправь её девушке (или покажи QR-код)."
            )
        )

    os.remove(img_path)
    return ConversationHandler.END

def main():
    """Запуск бота."""
    BOT_TOKEN = "8046219766:AAGFsWXIFTEPe8aaTBimVyWm2au2f-uIYSs"

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DESIGN: [CallbackQueryHandler(design_choice)],
            PAGE1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page1)],
            PAGE2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page2)],
            PAGE3: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page3)],
            TIMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_times)]
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()