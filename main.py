import random
import sqlite3
import time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

GROUP_ID = -1001941069892
ADMIN_ID = 6878462090
DEGRADE_COOLDOWN = 3600  # 1 час

SMILEYS = ['🎉', '👽', '🤢', '💥', '😵', '🔥', '🍄', '🐒', '🍌', '🤡', '🤠', '🦠', '🧟', '🧠', '🤖']

DB = 'degrade_bot.db'

def get_random_smiley():
    return random.choice(SMILEYS)

# ====== Работа с БД ======

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        iq INTEGER DEFAULT 100,
        last_degrade INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS degrade_cmds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        iq_loss INTEGER NOT NULL,
        photo_url TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS diseases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        iq_multiplier REAL NOT NULL
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS user_diseases (
        user_id INTEGER,
        disease_id INTEGER,
        PRIMARY KEY(user_id, disease_id)
    )''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT iq, last_degrade FROM users WHERE user_id=?', (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute('INSERT INTO users (user_id, iq) VALUES (?, ?)', (user_id, 100))
        conn.commit()
        iq, last_degrade = 100, 0
    else:
        iq, last_degrade = row
    conn.close()
    return iq, last_degrade

def update_user_iq(user_id, new_iq):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('UPDATE users SET iq=? WHERE user_id=?', (new_iq, user_id))
    conn.commit()
    conn.close()

def update_user_last_degrade(user_id, timestamp):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('UPDATE users SET last_degrade=? WHERE user_id=?', (timestamp, user_id))
    conn.commit()
    conn.close()

def add_degrade_cmd(text, iq_loss, photo_url=None):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('INSERT INTO degrade_cmds (text, iq_loss, photo_url) VALUES (?, ?, ?)', (text, iq_loss, photo_url))
    conn.commit()
    conn.close()

def del_degrade_cmd(cmd_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('DELETE FROM degrade_cmds WHERE id=?', (cmd_id,))
    conn.commit()
    conn.close()

def get_all_degrade_cmds():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT id, text, iq_loss, photo_url FROM degrade_cmds')
    rows = cur.fetchall()
    conn.close()
    return rows

def add_disease(name, description, iq_multiplier):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('INSERT INTO diseases (name, description, iq_multiplier) VALUES (?, ?, ?)', (name, description, iq_multiplier))
    conn.commit()
    conn.close()

def del_disease(disease_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('DELETE FROM diseases WHERE id=?', (disease_id,))
    conn.commit()
    conn.close()

def get_all_diseases():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT id, name, description, iq_multiplier FROM diseases')
    rows = cur.fetchall()
    conn.close()
    return rows

def get_user_diseases(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('''
        SELECT d.id, d.name, d.description, d.iq_multiplier
        FROM diseases d
        JOIN user_diseases ud ON d.id = ud.disease_id
        WHERE ud.user_id=?
    ''', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def add_disease_to_user(user_id, disease_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO user_diseases (user_id, disease_id) VALUES (?, ?)', (user_id, disease_id))
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()

def reset_all_users():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('UPDATE users SET iq=100, last_degrade=0')
    cur.execute('DELETE FROM user_diseases')
    conn.commit()
    conn.close()

def get_top_users(limit=10):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT user_id, iq FROM users ORDER BY iq ASC LIMIT ?', (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_iq_multiplier(user_id):
    diseases = get_user_diseases(user_id)
    total_mult = 0.0
    for _, _, _, mult in diseases:
        total_mult += mult
    return total_mult

# ====== Хэндлеры ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот для деградации IQ. Используй /degrade в группе.")

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user_id = update.effective_user.id
    iq, last_degrade = get_user(user_id)
    now = int(time.time())

    diff = now - last_degrade
    if diff < DEGRADE_COOLDOWN:
        left = DEGRADE_COOLDOWN - diff
        await update.message.reply_text(
            f"Деградировать можно раз в час.\nОсталось ждать {left//60} мин {left%60} сек {get_random_smiley()}"
        )
        return

    cmds = get_all_degrade_cmds()
    if not cmds:
        await update.message.reply_text("Админ пока не добавил команды деградации.")
        return

    cmd = random.choice(cmds)
    cmd_id, text, base_iq_loss, photo_url = cmd

    multiplier = get_iq_multiplier(user_id)
    total_iq_loss = max(1, int(base_iq_loss * (1 + multiplier)))

    new_iq = iq - total_iq_loss
    if new_iq < 0:
        new_iq = 0

    update_user_iq(user_id, new_iq)
    update_user_last_degrade(user_id, now)

    diseases = get_all_diseases()
    got_disease_msg = ''
    if diseases and random.random() < 0.15:
        disease = random.choice(diseases)
        disease_id, d_name, d_desc, d_mult = disease
        user_diseases = [d[0] for d in get_user_diseases(user_id)]
        if disease_id not in user_diseases:
            add_disease_to_user(user_id, disease_id)
            got_disease_msg = (
                f"\n\n{get_random_smiley()} Вы подхватили болезнь: *{d_name}*!\n"
                f"Эффект: {d_desc}\n"
                f"Теперь ваш IQ будет падать на {int(d_mult*100)}% больше, чем ранее."
            )

    message = (
        f"{text}\n{get_random_smiley()} Твой IQ упал на {total_iq_loss}.\n"
        f"Сейчас IQ: {new_iq} {get_random_smiley()}"
        f"{got_disease_msg}"
    )

    if photo_url:
        await update.message.reply_photo(photo=photo_url, caption=message, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    cmds = get_all_degrade_cmds()
    if not cmds:
        await update.message.reply_text("Нет команд деградации.")
        return
    text = "\n".join(f"{cmd[0]}. {cmd[1]} (IQ {cmd[2]})" for cmd in cmds)
    await update.message.reply_text(text)

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Формат: /add <текст> <минус_iq> [url_фото]")
        return
    try:
        iq_loss = int(args[-2]) if len(args) > 2 else int(args[-1])
    except:
        await update.message.reply_text("❌ Ошибка: IQ должен быть числом.")
        return
    if len(args) > 2:
        text = " ".join(args[:-2])
        photo_url = args[-1]
    else:
        text = " ".join(args[:-1])
        photo_url = None
    add_degrade_cmd(text, iq_loss, photo_url)
    await update.message.reply_text(f"Команда добавлена: \"{text}\" с IQ {iq_loss} и фото: {photo_url or 'нет'}")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("❌ Формат: /del <номер>")
        return
    cmd_id = int(context.args[0])
    del_degrade_cmd(cmd_id)
    await update.message.reply_text(f"Команда #{cmd_id} удалена.")

async def adddis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Формат: /adddis <название> <описание> <множитель (например 0.3)>")
        return
    name = args[0]
    iq_multiplier = None
    try:
        iq_multiplier = float(args[-1])
    except:
        await update.message.reply_text("❌ Ошибка: множитель должен быть числом с плавающей точкой, например 0.3")
        return
    description = " ".join(args[1:-1])
    add_disease(name, description, iq_multiplier)
    await update.message.reply_text(f"Болезнь \"{name}\" добавлена с множителем IQ {iq_multiplier}")

async def deldis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("❌ Формат: /deldis <номер>")
        return
    disease_id = int(context.args[0])
    del_disease(disease_id)
    await update.message.reply_text(f"Болезнь #{disease_id} удалена.")

async def my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    iq, _ = get_user(user_id)
    diseases = get_user_diseases(user_id)
    if diseases:
        dis_text = "\n".join(f"- {d[1]}: {d[2]}" for d in diseases)
    else:
        dis_text = "У вас нет болезней."
    await update.message.reply_text(f"Ваш IQ: {iq}\nБолезни:\n{dis_text}")

async def resetall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    reset_all_users()
    await update.message.reply_text("Сброс IQ и болезней у всех пользователей выполнен.")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_top_users(10)
    if not users:
        await update.message.reply_text("Нет данных для топа.")
        return
    lines = []
    for i, (user_id, iq) in enumerate(users, start=1):
        lines.append(f"{i}. [ID:{user_id}] IQ: {iq}")
    await update.message.reply_text("Топ по деградации:\n" + "\n".join(lines))

def main():
    init_db()
    app = ApplicationBuilder().token("YOUR_TOKEN_HERE").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("eair", eair))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("del", delete))
    app.add_handler(CommandHandler("adddis", adddis))
    app.add_handler(CommandHandler("deldis", deldis))
    app.add_handler(CommandHandler("my", my))
    app.add_handler(CommandHandler("resetall", resetall))
    app.add_handler(CommandHandler("top", top))

    app.run_polling()

if __name__ == "__main__":
    main()
