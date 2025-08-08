import random
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
GROUP_ID = -1001941069892
ADMIN_ID = 6878462090

# Смайлы для сообщений
EMOJIS = ["🎉", "👽", "🤢", "😵", "🔥", "💀", "🤡", "🎈", "⚡️", "🧠"]

# Данные пользователей: {user_id: {"iq": int, "last_degrade": timestamp, "diseases": set()}}
users = {}

# Действия деградации: [{"text": str, "iq_change": int}]
degrade_actions = []

# Болезни: {name: multiplier}
diseases = {}

# Таймаут деградации (в секундах)
DEGRADE_COOLDOWN = 3600  # 1 час

def save_state():
    # Пока заглушка (можно подключить файл или БД)
    pass

def load_state():
    # Пока заглушка
    pass

def get_iq(user_id):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    return users[user_id]["iq"]

def set_iq(user_id, iq):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    users[user_id]["iq"] = iq

def get_diseases(user_id):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    return users[user_id]["diseases"]

def get_last_degrade(user_id):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    return users[user_id]["last_degrade"]

def set_last_degrade(user_id, timestamp):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    users[user_id]["last_degrade"] = timestamp

def calculate_multiplier(user_id):
    mult = 1.0
    for d in get_diseases(user_id):
        mult += diseases.get(d, 0)
    return mult

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user_id = update.effective_user.id
    now = time.time()

    last = get_last_degrade(user_id)
    if now - last < DEGRADE_COOLDOWN:
        left = int(DEGRADE_COOLDOWN - (now - last))
        m, s = divmod(left, 60)
        await update.message.reply_text(f"⏳ Ты уже деградировал, подожди {m} мин {s} сек.")
        return

    if not degrade_actions:
        await update.message.reply_text("⚠️ Нет доступных действий деградации. Обратитесь к админу.")
        return

    action = random.choice(degrade_actions)
    base_iq_loss = abs(action["iq_change"])
    multiplier = calculate_multiplier(user_id)
    iq_loss = int(base_iq_loss * multiplier)

    # Обновляем IQ
    iq = get_iq(user_id) - iq_loss
    set_iq(user_id, iq)
    set_last_degrade(user_id, now)

    emoji = random.choice(EMOJIS)

    msg = f"{action['text']}, твой IQ упал на {iq_loss} {emoji}\nСейчас твой IQ: {iq} {random.choice(EMOJIS)}"

    # Шанс получить болезнь
    if diseases and random.random() < 0.2:  # 20% шанс заболеть
        disease_name = random.choice(list(diseases.keys()))
        if disease_name not in get_diseases(user_id):
            get_diseases(user_id).add(disease_name)
            msg += f"\n{random.choice(EMOJIS)} Вы подхватили болезнь: {disease_name}. Теперь IQ падает на {int(diseases[disease_name]*100)}% больше!"

    await update.message.reply_text(msg)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    if not users:
        await update.message.reply_text("Пока нет данных о пользователях.")
        return

    sorted_users = sorted(users.items(), key=lambda x: x[1]["iq"], reverse=True)[:10]

    msg = "🏆 Топ IQ:\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        emoji = random.choice(EMOJIS)
        msg += f"{i}. Пользователь {uid}: IQ {data['iq']} {emoji}\n"
    await update.message.reply_text(msg)

async def my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dis = get_diseases(user_id)
    if not dis:
        await update.message.reply_text("У вас нет болезней.")
        return
    msg = "Ваши болезни:\n" + "\n".join(dis)
    await update.message.reply_text(msg)

# --- Админ команды ---

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Формат: /add текст минус_iq\nПример: /add Купил айфон в кредит -3")
        return

    try:
        iq_change = int(args[-1])
        text = " ".join(args[:-1])
    except:
        await update.message.reply_text("❌ Последний аргумент должен быть числом (отрицательным)")
        return

    degrade_actions.append({"text": text, "iq_change": iq_change})
    await update.message.reply_text(f"Добавлено действие: '{text}' с изменением IQ {iq_change}")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Формат: /del номер")
        return
    idx = int(context.args[0]) - 1
    if 0 <= idx < len(degrade_actions):
        action = degrade_actions.pop(idx)
        await update.message.reply_text(f"Удалено действие: '{action['text']}'")
    else:
        await update.message.reply_text("❌ Неверный номер")

async def list_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if not degrade_actions:
        await update.message.reply_text("Пока нет действий.")
        return
    msg = "Доступные действия деградации:\n"
    for i, action in enumerate(degrade_actions, 1):
        msg += f"{i}. {action['text']} ({action['iq_change']} IQ)\n"
    await update.message.reply_text(msg)

async def adddisease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /adddisease название множитель (пример: 0.3)")
        return
    name = " ".join(context.args[:-1])
    try:
        mult = float(context.args[-1])
    except:
        await update.message.reply_text("❌ Множитель должен быть числом, например 0.3")
        return
    diseases[name] = mult
    await update.message.reply_text(f"Добавлена болезнь '{name}' с множителем {mult}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    users.clear()
    degrade_actions.clear()
    diseases.clear()
    await update.message.reply_text("Состояние бота сброшено (IQ, болезни, действия)")

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    text = (
        "🛠️ Админские команды:\n"
        "/add <текст> <минус_iq> — добавить действие деградации\n"
        "/del <номер> — удалить действие\n"
        "/list — показать все действия\n"
        "/adddisease <название> <множитель> — добавить болезнь\n"
        "/reset — сбросить IQ и болезни у всех\n"
    )
    await update.message.reply_text(text)

# --- Основной запуск ---

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))

    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("del", delete))
    app.add_handler(CommandHandler("list", list_actions))
    app.add_handler(CommandHandler("adddisease", adddisease))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("eair", eair))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
