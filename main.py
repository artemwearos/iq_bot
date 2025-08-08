import asyncio
import random
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
ADMIN_ID = 6878462090
GROUP_ID = -1001941069892

lock = asyncio.Lock()

# Данные
users = {}  # user_id: {"iq": int, "last_degrade": datetime, "points": int, "d_commands": [str], "d_used": int}
degrade_actions = []  # [{"text": str, "iq_change": int}]
d_user_commands = []  # пользовательские команды для деградации (список dict {"user_id", "text"})
diseases = []  # [{"name": str, "iq_multiplier": float, "min_hours": int, "max_hours": int}]
user_diseases = {}  
# user_id: [{"name": str, "start": datetime, "duration": timedelta}]

emojis = ["🎉", "👽", "🤢", "🔥", "😵", "🧠", "💥", "😈", "😱", "🤡"]

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def now_utc():
    return datetime.utcnow()

async def add_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /add <текст действия> <отрицательное IQ>")
        return
    try:
        iq_change = int(context.args[-1])
        if iq_change >= 0:
            await update.message.reply_text("IQ должно быть отрицательным числом!")
            return
    except:
        await update.message.reply_text("Последний аргумент должен быть числом (отрицательным).")
        return
    text = " ".join(context.args[:-1])
    async with lock:
        degrade_actions.append({"text": text, "iq_change": iq_change})
    await update.message.reply_text(f"Добавлено действие: {text} ({iq_change} IQ)")

async def del_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Использование: /del <номер действия>")
        return
    try:
        idx = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Введите номер действия (число).")
        return
    async with lock:
        if 0 <= idx < len(degrade_actions):
            removed = degrade_actions.pop(idx)
            await update.message.reply_text(f"Удалено действие: {removed['text']}")
        else:
            await update.message.reply_text("Неверный номер действия.")

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = "Действия деградации:\n"
    async with lock:
        if degrade_actions:
            for i, a in enumerate(degrade_actions, 1):
                msg += f"{i}. {a['text']} ({a['iq_change']} IQ)\n"
        else:
            msg += "Пока нет действий.\n"
        msg += "\nБолезни:\n"
        if diseases:
            for i, d in enumerate(diseases,1):
                msg += f"{i}. {d['name']} | Множитель IQ: {d['iq_multiplier']} | Срок (часы): {d['min_hours']}–{d['max_hours']}\n"
        else:
            msg += "Пока нет болезней.\n"
        msg += "\nПользовательские команды деградации:\n"
        if d_user_commands:
            for i, cmd in enumerate(d_user_commands,1):
                msg += f"{i}. {cmd['text']} (от {cmd['user_id']})\n"
        else:
            msg += "Нет пользовательских команд.\n"
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=msg)
    except:
        await update.message.reply_text("Напиши боту в ЛС, чтобы получить сообщения.")

async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 4:
        await update.message.reply_text("Использование: /adddisease <название> <множитель IQ (например 1.3)> <мин часы> <макс часы>")
        return
    try:
        iq_mult = float(context.args[-3])
        min_h = int(context.args[-2])
        max_h = int(context.args[-1])
        if min_h > max_h or min_h <= 0:
            await update.message.reply_text("Проверьте диапазон часов.")
            return
    except:
        await update.message.reply_text("Неверные аргументы. Множитель - число, часы - целые.")
        return
    name = " ".join(context.args[:-3])
    async with lock:
        diseases.append({"name": name, "iq_multiplier": iq_mult, "min_hours": min_h, "max_hours": max_h})
    await update.message.reply_text(f"Добавлена болезнь: {name}, множитель IQ: {iq_mult}, срок {min_h}–{max_h} часов.")

async def del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Использование: /deldisease <номер болезни>")
        return
    try:
        idx = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Введите номер болезни.")
        return
    async with lock:
        if 0 <= idx < len(diseases):
            removed = diseases.pop(idx)
            await update.message.reply_text(f"Удалена болезнь: {removed['name']}")
        else:
            await update.message.reply_text("Неверный номер.")

async def user_diseases_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = now_utc()
    async with lock:
        ud = user_diseases.get(user_id, [])
    if not ud:
        await update.message.reply_text("У вас нет болезней.")
        return
    msg = "Ваши болезни:\n"
    for d in ud:
        end_time = d["start"] + d["duration"]
        if now > end_time:
            msg += f"{d['name']} — истекла в {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        else:
            remain = end_time - now
            hrs = remain.total_seconds() // 3600
            mins = (remain.total_seconds() % 3600) // 60
            msg += f"{d['name']} — осталось {int(hrs)} ч {int(mins)} мин\n"
    await update.message.reply_text(msg)

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    async with lock:
        users.clear()
        user_diseases.clear()
    await update.message.reply_text("Сброшены IQ, таймеры и болезни у всех.")

async def reset_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    async with lock:
        user_diseases.clear()
    await update.message.reply_text("Сброшены все болезни у всех.")

async def change_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /changeiq <user_id> <новый IQ>")
        return
    try:
        uid = int(context.args[0])
        new_iq = int(context.args[1])
    except:
        await update.message.reply_text("Аргументы должны быть числами.")
        return
    async with lock:
        u = users.get(uid)
        if not u:
            u = {"iq": new_iq, "last_degrade": datetime.min, "points": 0, "d_used":0}
            users[uid] = u
        else:
            u["iq"] = new_iq
    await update.message.reply_text(f"У пользователя {uid} IQ установлен в {new_iq}.")

def get_iq_multiplier(user_id: int):
    now = now_utc()
    mult = 1.0
    async def _mult():
        nonlocal mult
        async with lock:
            ud = user_diseases.get(user_id, [])
            for d in ud:
                end = d["start"] + d["duration"]
                if now < end:
                    mult += d["iq_multiplier"] - 1
    return mult

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    user_id = update.effective_user.id
    now = now_utc()
    async with lock:
        user = users.get(user_id)
        if not user:
            user = {"iq": 100, "last_degrade": datetime.min, "points": 0, "d_used": 0}
            users[user_id] = user
        elapsed = (now - user["last_degrade"]).total_seconds()
        if elapsed < 3600:
            left = int((3600 - elapsed) // 60)
            await update.message.reply_text(f"Можно раз в час. Осталось {left} мин.")
            return
        if not degrade_actions:
            await update.message.reply_text("Нет действий деградации.")
            return

        # Бонус множитель от болезней
        mult = 1.0
        ud = user_diseases.get(user_id, [])
        for d in ud:
            end = d["start"] + d["duration"]
            if now < end:
                mult += d["iq_multiplier"] - 1

        action = random.choice(degrade_actions)
        base_iq_drop = action["iq_change"]
        iq_drop = int(base_iq_drop * mult)
        emoji = random.choice(emojis)
        user["iq"] += iq_drop
        user["last_degrade"] = now

        # Шанс подхватить болезнь
        chance = 10  # например 10%
        if diseases and random.randint(1, 100) <= chance:
            disease = random.choice(diseases)
            duration_hours = random.randint(disease["min_hours"], disease["max_hours"])
            duration = timedelta(hours=duration_hours)
            if user_id not in user_diseases:
                user_diseases[user_id] = []
            user_diseases[user_id].append({
                "name": disease["name"],
                "start": now,
                "duration": duration,
                "iq_multiplier": disease["iq_multiplier"],
            })
            disease_msg = f"\n🤢 Вы подхватили {disease['name']}! Теперь ваш IQ падает на {int((disease['iq_multiplier'] -1)*100)}% больше."
        else:
            disease_msg = ""

    msg = f"{update.effective_user.first_name}, {action['text']} {emoji}\nIQ изменился на {iq_drop} и теперь: {user['iq']}{disease_msg}"
    await update.message.reply_text(msg)

async def add_d_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 1:
        await update.message.reply_text("Использование: /d <текст вашей команды>")
        return
    text = " ".join(context.args)
    async with lock:
        user = users.get(user_id)
        if not user:
            users[user_id] = {"iq": 100, "last_degrade": datetime.min, "points": 0, "d_used": 0}
            user = users[user_id]
        if user["points"] < 1:
            await update.message.reply_text("У вас нет очков для добавления команды деградации.")
            return
        d_user_commands.append({"user_id": user_id, "text": text})
        user["points"] -= 1
    await update.message.reply_text(f"Ваша команда добавлена и стоит 1 очко. Осталось очков: {user['points']}")

async def admin_show_d_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    async with lock:
        if not d_user_commands:
            await update.message.reply_text("Пользовательских команд нет.")
            return
        msg = "Пользовательские команды деградации:\n"
        for i, cmd in enumerate(d_user_commands, 1):
            msg += f"{i}. {cmd['text']} (от {cmd['user_id']})\n"
    await update.message.reply_text(msg)

async def admin_remove_d_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Использование: /del_d <номер>")
        return
    try:
        idx = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Введите номер команды.")
        return
    async with lock:
        if 0 <= idx < len(d_user_commands):
            d_user_commands.pop(idx)
            await update.message.reply_text("Удалено.")
        else:
            await update.message.reply_text("Неверный номер.")

async def add_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /addpoints <user_id> <кол-во>")
        return
    try:
        uid = int(context.args[0])
        pts = int(context.args[1])
    except:
        await update.message.reply_text("Аргументы должны быть числами.")
        return
    async with lock:
        user = users.get(uid)
        if not user:
            users[uid] = {"iq": 100, "last_degrade": datetime.min, "points": pts, "d_used":0}
        else:
            user["points"] += pts
    await update.message.reply_text(f"Пользователю {uid} добавлено {pts} очков.")

async def show_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with lock:
        user = users.get(user_id)
        pts = user["points"] if user else 0
    await update.message.reply_text(f"У вас {pts} очков.")

async def show_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with lock:
        user = users.get(user_id)
        iq = user["iq"] if user else 100
    await update.message.reply_text(f"Ваш IQ: {iq}")

async def my_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await user_diseases_list(update, context)

async def top_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock:
        sorted_users = sorted(users.items(), key=lambda x: x[1].get("iq", 0), reverse=True)[:10]
    msg = "Топ IQ:\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name
        except:
            name = str(uid)
        msg += f"{i}. {name} - {data.get('iq', 100)}\n"
    await update.message.reply_text(msg)

async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = (
        "/add <текст> <отрицательное IQ> - добавить действие деградации\n"
        "/del <номер> - удалить действие\n"
        "/eair - список всех действий, болезней, пользовательских команд\n"
        "/adddisease <название> <множитель> <мин часы> <макс часы> - добавить болезнь\n"
        "/deldisease <номер> - удалить болезнь\n"
        "/resetall - сбросить IQ, болезни и таймеры всем\n"
        "/resetdiseases - сбросить болезни всем\n"
        "/changeiq <user_id> <значение> - изменить IQ пользователя\n"
        "/addpoints <user_id> <кол-во> - добавить очки\n"
        "/dcommands - показать пользовательские команды\n"
        "/del_d <номер> - удалить пользовательскую команду\n"
    )
    await update.message.reply_text(msg)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Используй /help для списка команд.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_admin))
    app.add_handler(CommandHandler("add", add_action))
    app.add_handler(CommandHandler("del", del_action))
    app.add_handler(CommandHandler("eair", eair))
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("deldisease", del_disease))
    app.add_handler(CommandHandler("my", my_diseases))
    app.add_handler(CommandHandler("resetall", reset_all))
    app.add_handler(CommandHandler("resetdiseases", reset_diseases))
    app.add_handler(CommandHandler("changeiq", change_iq))
    app.add_handler(CommandHandler("addpoints", add_points))
    app.add_handler(CommandHandler("d", add_d_command))
    app.add_handler(CommandHandler("dcommands", admin_show_d_commands))
    app.add_handler(CommandHandler("del_d", admin_remove_d_command))
    app.add_handler(CommandHandler("points", show_points))
    app.add_handler(CommandHandler("iq", show_iq))
    app.add_handler(CommandHandler("top", top_iq))
    app.add_handler(CommandHandler("degrade", degrade))

    app.run_polling()

if __name__ == "__main__":
    main()
