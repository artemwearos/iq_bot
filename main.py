import logging
import random
import time
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Токен и настройки
BOT_TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
ADMIN_ID = 6878462090
ALLOWED_GROUP_ID = -1001941069892

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Данные пользователей, болезней и действий (в памяти)
users_iq = {}  # user_id: int IQ
users_last_degrade = {}  # user_id: timestamp последней деградации
users_points = {}  # user_id: int очков для добавления кастомных команд
users_diseases = {}  # user_id: list of dict {name, effect, expire_time}

degrade_actions = []  # список действий с текстом и минусом IQ
diseases = []  # список болезней с названием, эффектом (%) и диапазоном времени в часах
degrade_custom_cmds = []  # пользовательские команды, добавленные за очки

SMILES = ["🎉", "👽", "🤢", "🔥", "💀", "👾", "😵", "🧠", "🛑", "😈"]

DEGRADE_COOLDOWN = 3600  # 1 час в секундах

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def check_group(update: Update) -> bool:
    chat = update.effective_chat
    if chat and chat.id == ALLOWED_GROUP_ID:
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Это бот для деградации IQ. Используй /degrade в группе.")

async def ensure_user_initialized(user_id: int):
    if user_id not in users_iq:
        users_iq[user_id] = 100
    if user_id not in users_points:
        users_points[user_id] = 0
    if user_id not in users_last_degrade:
        users_last_degrade[user_id] = 0
    if user_id not in users_diseases:
        users_diseases[user_id] = []

def get_random_smile():
    return random.choice(SMILES)

def get_effective_iq_loss(base_loss, user_id):
    # Считаем суммарный эффект болезней
    total_percent = 0
    now = datetime.now()
    new_diseases = []
    for disease in users_diseases.get(user_id, []):
        if disease["expire_time"] > now:
            total_percent += disease["effect"]
            new_diseases.append(disease)
    users_diseases[user_id] = new_diseases
    final_loss = int(base_loss * (1 + total_percent / 100))
    return final_loss

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_group(update):
        return
    user_id = update.effective_user.id
    await ensure_user_initialized(user_id)
    now_ts = time.time()

    last = users_last_degrade.get(user_id, 0)
    if now_ts - last < DEGRADE_COOLDOWN:
        remain = int((DEGRADE_COOLDOWN - (now_ts - last)) / 60)
        await update.message.reply_text(f"⏳ Можно деградировать раз в час. Жди {remain} мин.")
        return

    if not degrade_actions:
        await update.message.reply_text("Пока нет настроенных действий деградации.")
        return

    action = random.choice(degrade_actions)
    base_iq_loss = action["iq_loss"]
    iq_loss = get_effective_iq_loss(base_iq_loss, user_id)

    users_iq[user_id] = users_iq.get(user_id, 100) - iq_loss
    users_last_degrade[user_id] = now_ts

    # Шанс подхватить болезнь
    if diseases:
        chance = random.randint(1, 100)
        # Например, 20% шанс
        if chance <= 20:
            disease = random.choice(diseases)
            # Срок болезни от min до max часов
            now = datetime.now()
            hours = random.randint(disease["min_hours"], disease["max_hours"])
            expire = now + timedelta(hours=hours)
            users_diseases[user_id].append({
                "name": disease["name"],
                "effect": disease["effect"],
                "expire_time": expire,
            })
            disease_text = f"\n{get_random_smile()} Вы подхватили болезнь: {disease['name']}! IQ будет падать на {disease['effect']}% больше."
        else:
            disease_text = ""
    else:
        disease_text = ""

    smile = get_random_smile()

    msg = (
        f"{action['text']}, твой IQ упал на {iq_loss} {smile}\n"
        f"Сейчас твой IQ: {users_iq[user_id]}{disease_text}"
    )
    await update.message.reply_text(msg)

async def my_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_user_initialized(user_id)

    now = datetime.now()
    diseases_list = users_diseases.get(user_id, [])
    if not diseases_list:
        await update.message.reply_text("У тебя нет болезней.")
        return

    msg = "Твои болезни:\n"
    for i, d in enumerate(diseases_list, 1):
        if d["expire_time"] > now:
            left = d["expire_time"] - now
            hours = left.total_seconds() // 3600
            minutes = (left.total_seconds() % 3600) // 60
            msg += f"{i}. {d['name']} — действует еще {int(hours)}ч {int(minutes)}м\n"
        else:
            msg += f"{i}. {d['name']} — болезнь истекла {d['expire_time'].strftime('%Y-%m-%d %H:%M:%S')} по МСК\n"
    await update.message.reply_text(msg)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_group(update):
        return

    sorted_users = sorted(users_iq.items(), key=lambda x: x[1], reverse=True)
    msg = "Топ по IQ:\n"
    for i, (user_id, iq) in enumerate(sorted_users[:10], 1):
        try:
            user = await context.bot.get_chat(user_id)
            name = user.first_name or str(user_id)
        except:
            name = str(user_id)
        msg += f"{i}. {name}: {iq}\n"
    await update.message.reply_text(msg)

# --- Админ команды ---

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return

    msg = "=== Админ панель ===\n\n"
    msg += "Действия деградации:\n"
    if degrade_actions:
        for i, a in enumerate(degrade_actions, 1):
            msg += f"{i}. {a['text']} | IQ: {a['iq_loss']}\n"
    else:
        msg += "Пока нет действий.\n"

    msg += "\nБолезни:\n"
    if diseases:
        for i, d in enumerate(diseases, 1):
            msg += f"{i}. {d['name']} | Эффект: {d['effect']}% | Время: {d['min_hours']}–{d['max_hours']} ч\n"
    else:
        msg += "Пока нет болезней.\n"

    msg += "\nПользовательские команды деградации:\n"
    if degrade_custom_cmds:
        for i, c in enumerate(degrade_custom_cmds, 1):
            msg += f"{i}. ({c['user_id']}) {c['text']}\n"
    else:
        msg += "Нет пользовательских команд.\n"

    await update.message.reply_text(msg)

async def add_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Используй: /add <текст действия> <число IQ>")
        return
    try:
        iq_loss = int(context.args[-1])
        text = " ".join(context.args[:-1])
        degrade_actions.append({"text": text, "iq_loss": iq_loss})
        await update.message.reply_text(f"Добавлено действие: {text} с IQ {iq_loss}")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def del_degrade(update: Update, context: ContextTypes
                      async def del_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /del <номер действия>")
        return
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(degrade_actions):
            removed = degrade_actions.pop(idx)
            await update.message.reply_text(f"Удалено действие: {removed['text']}")
        else:
            await update.message.reply_text("Неверный номер действия.")
    except:
        await update.message.reply_text("Ошибка при удалении действия.")

async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 4:
        await update.message.reply_text(
            "Используй: /adddisease <название> <эффект%> <мин.часы> <макс.часы>"
        )
        return
    try:
        name = context.args[0]
        effect = int(context.args[1])
        min_hours = int(context.args[2])
        max_hours = int(context.args[3])
        diseases.append({
            "name": name,
            "effect": effect,
            "min_hours": min_hours,
            "max_hours": max_hours,
        })
        await update.message.reply_text(f"Добавлена болезнь: {name}")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /deldisease <номер>")
        return
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(diseases):
            removed = diseases.pop(idx)
            await update.message.reply_text(f"Удалена болезнь: {removed['name']}")
        else:
            await update.message.reply_text("Неверный номер болезни.")
    except:
        await update.message.reply_text("Ошибка при удалении болезни.")

async def list_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if not diseases:
        await update.message.reply_text("Пока нет болезней.")
        return
    msg = "Список болезней:\n"
    for i, d in enumerate(diseases, 1):
        msg += f"{i}. {d['name']} | Эффект: {d['effect']}% | Время: {d['min_hours']}–{d['max_hours']} ч\n"
    await update.message.reply_text(msg)

async def reset_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    for uid in users_diseases.keys():
        users_diseases[uid] = []
    await update.message.reply_text("Все болезни сброшены у всех пользователей.")

async def reset_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    for uid in users_iq.keys():
        users_iq[uid] = 100
    await update.message.reply_text("IQ всех пользователей сброшен до 100.")

async def set_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Используй: /setiq <user_id> <значение>")
        return
    try:
        target_id = int(context.args[0])
        iq_val = int(context.args[1])
        users_iq[target_id] = iq_val
        await update.message.reply_text(f"У пользователя {target_id} установлен IQ = {iq_val}")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def add_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Используй: /addpoint <user_id> <кол-во>")
        return
    try:
        target_id = int(context.args[0])
        pts = int(context.args[1])
        users_points[target_id] = users_points.get(target_id, 0) + pts
        await update.message.reply_text(f"Пользователю {target_id} добавлено {pts} очков.")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def my_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pts = users_points.get(user_id, 0)
    await update.message.reply_text(f"У тебя {pts} очков.")

async def add_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pts = users_points.get(user_id, 0)
    if pts < 1:
        await update.message.reply_text("У тебя нет очков для добавления команды (нужно 1).")
        return
    if not context.args:
        await update.message.reply_text("Используй: /d <текст действия>")
        return
    text = " ".join(context.args)
    degrade_custom_cmds.append({
        "user_id": user_id,
        "text": text,
        "iq_loss": 1,
    })
    users_points[user_id] = pts - 1
    await update.message.reply_text("Пользовательская команда добавлена.")

async def list_custom_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if not degrade_custom_cmds:
        await update.message.reply_text("Пользовательских команд нет.")
        return
    msg = "Пользовательские команды деградации:\n"
    for i, c in enumerate(degrade_custom_cmds, 1):
        msg += f"{i}. ({c['user_id']}) {c['text']} IQ: {c['iq_loss']}\n"
    await update.message.reply_text(msg)

async def reset_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    for uid in users_last_degrade.keys():
        users_last_degrade[uid] = 0
    await update.message.reply_text("Таймеры деградации у всех сброшены.")

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Пользовательские команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("degrade", degrade))
    application.add_handler(CommandHandler("mydiseases", my_diseases))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("d", add_custom_command))
    application.add_handler(CommandHandler("mypoints", my_points))

    # Админ команды
    application.add_handler(CommandHandler("eair", eair))
    application.add_handler(CommandHandler("add", add_degrade))
    application.add_handler(CommandHandler("del", del_degrade))
    application.add_handler(CommandHandler("adddisease", add_disease))
    application.add_handler(CommandHandler("deldisease", del_disease))
    application.add_handler(CommandHandler("listdiseases", list_diseases))
    application.add_handler(CommandHandler("resetdiseases", reset_diseases))
    application.add_handler(CommandHandler("resetiq", reset_iq))
    application.add_handler(CommandHandler("setiq", set_iq))
    application.add_handler(CommandHandler("addpoint", add_point))
    application.add_handler(CommandHandler("listcustom", list_custom_commands))
    application.add_handler(CommandHandler("resettimer", reset_timer))

    application.run_polling()

if __name__ == "__main__":
    main()
