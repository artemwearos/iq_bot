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
GROUP_ID = -1001941069892
ADMIN_ID = 6878462090

INITIAL_IQ = 100

users = {}  # user_id: {"iq": int, "last_degrade": datetime, "diseases": [], "degrade_multiplier": float}
degrade_messages = []  # {"text": str, "iq_drop": int, "photo": str or None}
diseases_list = []  # {"name": str, "multiplier": float}

EMOJIS = ["🎉", "👽", "🤢", "😵", "🧠", "💥", "🔥", "❌"]

def random_emoji():
    return random.choice(EMOJIS)

def is_admin(user_id):
    return user_id == ADMIN_ID

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    user_id = update.effective_user.id
    now = datetime.utcnow()

    user = users.get(user_id)
    if not user:
        users[user_id] = {"iq": INITIAL_IQ, "last_degrade": None, "diseases": [], "degrade_multiplier": 1.0}
        user = users[user_id]

    if user["last_degrade"] and now - user["last_degrade"] < timedelta(hours=1):
        left = timedelta(hours=1) - (now - user["last_degrade"])
        mins, secs = divmod(left.seconds, 60)
        await update.message.reply_text(
            f"⏳ Подожди еще {mins} мин {secs} сек до следующей деградации."
        )
        return

    if not degrade_messages:
        await update.message.reply_text("⚠️ Нет доступных действий для деградации. Админ не добавил их.")
        return

    action = random.choice(degrade_messages)
    base_drop = action["iq_drop"]

    multiplier = 0.0
    for dis in user["diseases"]:
        multiplier += dis["multiplier"]
    multiplier = 1.0 + multiplier

    drop = int(base_drop * multiplier)

    user["iq"] -= drop
    user["last_degrade"] = now

    text = f"{action['text']}, твой IQ упал на {drop} {random_emoji()}\nСейчас IQ: {user['iq']} {random_emoji()}"

    # Болезни с вероятностью 10%
    if diseases_list and random.random() < 0.10:
        new_disease = random.choice(diseases_list)
        if new_disease not in user["diseases"]:
            user["diseases"].append(new_disease)
            text += f"\n\n🤢 Вы подхватили болезнь: {new_disease['name']}. Теперь ваш IQ падает на {int(new_disease['multiplier']*100)}% больше."

    if action.get("photo"):
        await update.message.reply_photo(action["photo"], caption=text)
    else:
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
        await update.message.reply_text(f"У тебя нет болезней.\nIQ: {user['iq']}")
        return

    dis_text = "\n".join([f"• {d['name']}" for d in user["diseases"]])
    await update.message.reply_text(f"Твои болезни:\n{dis_text}\nIQ: {user['iq']}")

async def add_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /add <текст> <iq_падение>")
        return
    try:
        iq_drop = int(context.args[-1])
    except:
        await update.message.reply_text("❌ Последний аргумент должен быть числом.")
        return
    text = " ".join(context.args[:-1])
    degrade_messages.append({"text": text, "iq_drop": abs(iq_drop), "photo": None})
    await update.message.reply_text(f"✅ Добавлено: '{text}' с падением IQ {abs(iq_drop)}")

async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /adddisease <название> <множитель (например 0.3)>")
        return
    try:
        multiplier = float(context.args[-1])
    except:
        await update.message.reply_text("❌ Последний аргумент должен быть числом с плавающей точкой (например 0.3).")
        return
    name = " ".join(context.args[:-1])
    diseases_list.append({"name": name, "multiplier": multiplier})
    await update.message.reply_text(f"✅ Добавлена болезнь '{name}' с множителем {multiplier}")

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    for u in users.values():
        u["iq"] = INITIAL_IQ
        u["last_degrade"] = None
        u["diseases"] = []
        u["degrade_multiplier"] = 1.0
    await update.message.reply_text("✅ Все IQ и болезни сброшены!")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/degrade - деградация IQ (в группе)\n"
        "/top - топ IQ (в группе)\n"
        "/my - мои болезни\n"
        "/add <текст> <число> - добавить сообщение (админка, в лс)\n"
        "/adddisease <название> <множитель> - добавить болезнь (админка, в лс)\n"
        "/reset - сбросить всем IQ и болезни (админка, в лс)\n"
        "/help - показать это сообщение\n"
    )

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", help_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))
    app.add_handler(CommandHandler("add", add_degrade))
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("reset", reset_all))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
