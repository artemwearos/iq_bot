import random
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
GROUP_ID = -1001941069892
ADMIN_ID = 6878462090

EMOJIS = ["🎉", "👽", "🤢", "😵", "🔥", "💀", "🤡", "🎈", "⚡️", "🧠"]

users = {}
degrade_actions = []
diseases = {}

DEGRADE_COOLDOWN = 3600  # в секундах (1 час)
DISEASE_CHANCE_PERCENT = 20  # шанс выпадения болезни в %

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {"iq": 100, "last_degrade": 0, "diseases": set()}
    return users[user_id]

def calculate_multiplier(user_id):
    mult = 1.0
    for d in get_user(user_id)["diseases"]:
        mult += diseases.get(d, 0)
    return mult

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    user_id = update.effective_user.id
    user = get_user(user_id)
    now = time.time()
    if now - user["last_degrade"] < DEGRADE_COOLDOWN:
        left = int(DEGRADE_COOLDOWN - (now - user["last_degrade"]))
        m, s = divmod(left, 60)
        await update.message.reply_text(f"⏳ Деградация доступна через {m} мин {s} сек.")
        return
    if not degrade_actions:
        await update.message.reply_text("⚠️ Нет действий для деградации, обратитесь к админу.")
        return

    action = random.choice(degrade_actions)
    base_loss = abs(action["iq_change"])
    multiplier = calculate_multiplier(user_id)
    iq_loss = int(base_loss * multiplier)

    user["iq"] -= iq_loss
    user["last_degrade"] = now

    emoji = random.choice(EMOJIS)
    msg = f"{action['text']}, твой IQ упал на {iq_loss} {emoji}\nСейчас твой IQ: {user['iq']} {random.choice(EMOJIS)}"

    # Шанс получить болезнь
    if diseases and random.randint(1, 100) <= DISEASE_CHANCE_PERCENT:
        disease_name = random.choice(list(diseases.keys()))
        if disease_name not in user["diseases"]:
            user["diseases"].add(disease_name)
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
    user = get_user(user_id)
    if not user["diseases"]:
        await update.message.reply_text("У вас нет болезней.")
        return
    msg = "Ваши болезни:\n" + "\n".join(user["diseases"])
    await update.message.reply_text(msg)

# --- Админ команды ---

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /add текст минус_iq\nПример: /add Купил айфон -3")
        return
    try:
        iq_change = int(context.args[-1])
        text = " ".join(context.args[:-1])
    except:
        await update.message.reply_text("❌ Последний аргумент должен быть числом")
        return
    degrade_actions.append({"text": text, "iq_change": iq_change})
    await update.message.reply_text(f"Добавлено действие: '{text}' с изменением IQ {iq_change}")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
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
    if update.effective_user.id != ADMIN_ID:
        return
    if not degrade_actions:
        await update.message.reply_text("Пока нет действий.")
        return
    msg = "Доступные действия деградации:\n"
    for i, action in enumerate(degrade_actions, 1):
        msg += f"{i}. {action['text']} ({action['iq_change']} IQ)\n"
    await update.message.reply_text(msg)

async def adddisease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
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
    if update.effective_user.id != ADMIN_ID:
        return
    users.clear()
    degrade_actions.clear()
    diseases.clear()
    global DISEASE_CHANCE_PERCENT
    DISEASE_CHANCE_PERCENT = 20
    await update.message.reply_text("Состояние бота сброшено (IQ, болезни, действия, шанс болезни)")

async def resettimers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    for user in users.values():
        user["last_degrade"] = 0
    await update.message.reply_text("⏱️ Таймеры деградации у всех пользователей сброшены.")

async def setdiseasechance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DISEASE_CHANCE_PERCENT
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Формат: /setdiseasechance число (процент от 0 до 100)")
        return
    val = int(context.args[0])
    if not 0 <= val <= 100:
        await update.message.reply_text("❌ Процент должен быть от 0 до 100")
        return
    DISEASE_CHANCE_PERCENT = val
    await update.message.reply_text(f"Шанс выпадения болезни установлен на {val}%")

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = (
        "🛠️ Админские команды:\n"
        "/add <текст> <минус_iq> — добавить действие деградации\n"
        "/del <номер> — удалить действие\n"
        "/list — показать все действия\n"
        "/adddisease <название> <множитель> — добавить болезнь\n"
        "/reset — сбросить IQ, болезни, действия и шанс болезни\n"
        "/resettimers — сбросить таймеры деградации всем\n"
        "/setdiseasechance <процент> — установить шанс выпадения болезни\n"
    )
    await update.message.reply_text(text)

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))

    # Админ
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("del", delete))
    app.add_handler(CommandHandler("list", list_actions))
    app.add_handler(CommandHandler("adddisease", adddisease))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("eair", eair))
    app.add_handler(CommandHandler("resettimers", resettimers))
    app.add_handler(CommandHandler("setdiseasechance", setdiseasechance))

    app.run_polling()

if __name__ == "__main__":
    main()
