import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
GROUP_ID = -1001941069892
ADMIN_ID = 6878462090
INITIAL_IQ = 100

EMOJIS = ["🎉", "👽", "🤢", "😵", "🧠", "💥", "🔥", "❌"]

def random_emoji():
    return random.choice(EMOJIS)

users = {}  # user_id: {"iq": int, "last_degrade": datetime, "diseases": [disease_names]}
actions = []  # {"text": str, "iq_drop": int}
diseases = []  # {"name": str, "multiplier": float}

def is_admin(user_id):
    return user_id == ADMIN_ID

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user_id = update.effective_user.id
    now = datetime.utcnow()

    if user_id not in users:
        users[user_id] = {"iq": INITIAL_IQ, "last_degrade": None, "diseases": []}

    user = users[user_id]

    # Проверка таймера (1 час)
    if user["last_degrade"] and now - user["last_degrade"] < timedelta(hours=1):
        left = timedelta(hours=1) - (now - user["last_degrade"])
        mins, secs = divmod(left.seconds, 60)
        await update.message.reply_text(f"⏳ Подожди {mins} мин {secs} сек до следующей деградации.")
        return

    if not actions:
        await update.message.reply_text("⚠️ Админ еще не добавил действия для деградации.")
        return

    action = random.choice(actions)

    base_drop = action["iq_drop"]
    # Считаем множитель болезней
    multiplier = 1.0 + sum(d["multiplier"] for d in diseases if d["name"] in user["diseases"])

    drop = int(base_drop * multiplier)
    user["iq"] -= drop
    user["last_degrade"] = now

    text = f"{action['text']}, твой IQ упал на {drop} {random_emoji()}\nСейчас IQ: {user['iq']} {random_emoji()}"

    # Рандомная вероятность подхватить болезнь 10%
    if diseases and random.random() < 0.1:
        new_disease = random.choice(diseases)
        if new_disease["name"] not in user["diseases"]:
            user["diseases"].append(new_disease["name"])
            text += f"\n\n🤢 Ты подхватил болезнь: {new_disease['name']}! Теперь твой IQ падает на {int(new_disease['multiplier']*100)}% больше."

    await update.message.reply_text(text)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    if not users:
        await update.message.reply_text("Пока нет данных по IQ.")
        return

    top_list = sorted(users.items(), key=lambda x: x[1]["iq"], reverse=True)[:10]
    text = "🏆 Топ по IQ:\n"
    for i, (uid, data) in enumerate(top_list, 1):
        text += f"{i}. Пользователь {uid}: IQ {data['iq']} {random_emoji()}\n"
    await update.message.reply_text(text)

async def my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("Ты еще не деградировал, IQ 100.")
        return

    if not user["diseases"]:
        await update.message.reply_text("У тебя нет болезней.")
    else:
        text = "Твои болезни:\n" + "\n".join(user["diseases"])
        await update.message.reply_text(text)

# Админка: /add <текст> <минус_iq>
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Формат: /add <текст> <минус_iq>")
        return

    try:
        iq_drop = int(args[-1])
    except ValueError:
        await update.message.reply_text("❌ Последний аргумент должен быть числом (минус IQ).")
        return

    text = " ".join(args[:-1])
    actions.append({"text": text, "iq_drop": iq_drop})
    await update.message.reply_text(f"✅ Добавлено действие: {text} (-{iq_drop} IQ)")

# Админка: /del <номер>
async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("❌ Формат: /del <номер>")
        return

    idx = int(args[0]) - 1
    if idx < 0 or idx >= len(actions):
        await update.message.reply_text("❌ Неверный номер.")
        return

    removed = actions.pop(idx)
    await update.message.reply_text(f"✅ Удалено действие: {removed['text']}")

# Показать все действия /list
async def list_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not actions:
        await update.message.reply_text("Пока нет добавленных действий.")
        return

    text = "Действия:\n"
    for i, a in enumerate(actions, 1):
        text += f"{i}. {a['text']} (-{a['iq_drop']} IQ)\n"
    await update.message.reply_text(text)

# Добавить болезнь: /adddisease <название> <множитель>
async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Формат: /adddisease <название> <множитель>")
        return

    try:
        multiplier = float(args[-1])
    except ValueError:
        await update.message.reply_text("❌ Множитель должен быть числом (например 0.3 для +30%).")
        return

    name = " ".join(args[:-1])
    diseases.append({"name": name, "multiplier": multiplier})
    await update.message.reply_text(f"✅ Добавлена болезнь: {name} (IQ падает на {int(multiplier*100)}% больше)")

# Сбросить IQ и болезни у всех: /reset
async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    for user in users.values():
        user["iq"] = INITIAL_IQ
        user["diseases"] = []
        user["last_degrade"] = None

    await update.message.reply_text("✅ Все IQ и болезни сброшены.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот для деградации IQ запущен!")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Неизвестная команда.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))

    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("del", delete))
    app.add_handler(CommandHandler("list", list_actions))
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("reset", reset_all))

    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.run_polling()

if __name__ == "__main__":
    main()
