# app.py
from flask import Flask, render_template, request, redirect, url_for
import telegram
import asyncio
import threading
import sqlite3
import json
from flask import jsonify

TELEGRAM_BOT_TOKEN = "8046219766:AAGFsWXIFTEPe8aaTBimVyWm2au2f-uIYSs"
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

app = Flask(__name__, template_folder='templates')  # Убедитесь, что папка называется 'templates'
DB_PATH = "app.db"

def init_db():
    """
    Создаёт таблицу invitations (page1, page2, page3, times, design, chat_id), если её нет.
    """
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

init_db()

loop = asyncio.new_event_loop()

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

def send_message_sync(chat_id, message):
    """Отправка в Телеграм через глобальный event loop."""
    future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id=chat_id, text=message),
        loop
    )
    return future.result(timeout=10)

def get_invitation(invite_id):
    """Получаем данные из БД: page1, page2, page3, times, chat_id, design."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT design, page1, page2, page3, times, chat_id FROM invitations WHERE id = ?', (invite_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": invite_id,
            "design": row[0],
            "page1": row[1],
            "page2": row[2],
            "page3": row[3],
            "times": row[4].split("\n"),
            "chat_id": row[5]
        }
    return None


# ---------- 1) Страница 1 ----------
@app.route('/invite/<invite_id>/page1')
def page1(invite_id):
    """
    Показывает ТОЛЬКО text page1. Кнопка [Дальше] -> /invite/<id>/page2
    """
    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404
    return render_template('page1.html', data=data)


# ---------- 2) Страница 2 ----------
@app.route('/invite/<invite_id>/page2')
def page2(invite_id):
    """
    Показывает text page2. Кнопка [Дальше] -> /invite/<id>/page3
    """
    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404
    return render_template('page2.html', data=data)


# ---------- 3) Страница 3 ----------
@app.route('/invite/<invite_id>/page3')
def page3(invite_id):
    """
    Показывает text page3. Две кнопки: [Да] -> /invite/<id>/page4, [Нет] -> AJAX /response
    """
    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404
    return render_template('page3.html', data=data)


# ---------- 4) Страница 4 (выбор времени) ----------
@app.route('/invite/<invite_id>/page4', methods=['GET', 'POST'])
def page4(invite_id):
    """
    GET: Показываем варианты времени (times), без доп. заголовка.
    POST: обрабатываем выбранное время, отправляем в Телеграм -> редирект на page5.
    """
    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404

    if request.method == 'GET':
        return render_template('page4.html', data=data)

    # POST: пользователь выбрал время
    selected_time = request.form.get('selected_time')
    if not selected_time:
        return "Вы не выбрали время!", 400

    # Отправляем сообщение в Телеграм
    chat_id = data["chat_id"]
    msg = f"Девушка выбрала время: {selected_time}"
    try:
        send_message_sync(chat_id, msg)
    except Exception as e:
        print("Ошибка при отправке сообщения в Telegram:", e)

    # Перенаправляем на страницу 5, передавая выбранное время в URL
    return redirect(url_for('page5', invite_id=invite_id, selected_time=selected_time))


# ---------- 5) Страница 5 (Спасибо + комментарий) ----------
@app.route('/invite/<invite_id>/page5', methods=['GET'])
def page5(invite_id):
    """
    Спасибо за ответ! Вы выбрали время: <selected_time>
    Форма для комментария -> /comment (POST)
    """
    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404

    selected_time = request.args.get('selected_time', '')
    return render_template('page5.html', data=data, selected_time=selected_time)


# ---------- Кнопка "Извини, не могу" (AJAX), переиспользуем старую логику ----------
@app.route('/response', methods=['POST'])
def response():
    req_data = request.get_json()
    chat_id = req_data.get('chat_id')
    response_text = req_data.get('response', 'Извини, не могу')
    try:
        chat_id = int(chat_id)
        send_message_sync(chat_id, f"Девушка ответила: {response_text}")
    except Exception as e:
        print("Ошибка при отправке ответа в Telegram:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ---------- Обработка комментария (после выбора времени) ----------
@app.route('/comment', methods=['POST'])
def comment():
    """
    Принимаем invite_id и сам комментарий, отправляем в Телеграм
    """
    invite_id = request.form.get('invite_id')
    comment_text = request.form.get('comment', '').strip()

    data = get_invitation(invite_id)
    if not data:
        return "Приглашение не найдено.", 404

    chat_id = data["chat_id"]
    message = f"Девушка оставила комментарий: {comment_text}"

    try:
        chat_id = int(chat_id)
        send_message_sync(chat_id, message)
    except Exception as e:
        print("Ошибка при отправке комментария в Telegram:", e)
        return "Ошибка при отправке комментария.", 500

    return render_template('thanks_comment.html')


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
