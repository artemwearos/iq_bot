import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, User
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"  # твой токен
GROUP_ID = -1001941069892  # твоя группа
ADMIN_ID = 6878462090  # твой айди

EMOJIS = ["🎉", "👽", "😵‍💫", "🤢", "🤯", "💀", "👻", "🔥", "❌", "💩", "🤡"]

lock = asyncio.Lock()

users = {}  # user_id: {"iq": int, "last_degrade": datetime, "diseases": list of dicts, "points": int, "username": str}
degrade_actions = []  # dicts {text:str, iq_change:int}
diseases_list = []  # dicts {name:str, multiplier:float, duration_min:int, duration_max:int}
user_custom_commands = []  # dicts {user_id:int, text:str}


def now():
    return datetime.utcnow()


async def ensure_user(user: User):
    async with lock:
        if user.id not in users:
            users[user.id] = {
                "iq": 100,
                "last_degrade": datetime.fromtimestamp(0),
                "diseases": [],
                "points": 0,
                "username": user.username or f"{user.first_name or 'User'}",
            }
        else:
            # Обновляем username если изменился
            if users[user.id]["username"] != (user.username or user.first_name):
                users[user.id]["username"] = user.username or user.first_name


async def clean_expired_diseases(user_id):
    async with lock:
        if user_id not in users:
            return
        now_dt = now()
        before = len(users[user_id]["diseases"])
        users[user_id]["diseases"] = [
            d for d in users[user_id]["diseases"] if d["end_time"] > now_dt
        ]
        after = len(users[user_id]["diseases"])
        if before != after:
            logger.info(f"Очистка болезней у {user_id}: удалено {before - after}")


def calculate_iq_penalty(base_penalty, user_id):
    mult = 1.0
    for disease in users[user_id]["diseases"]:
        mult += disease["multiplier"]
    return int(base_penalty * mult)


def random_emoji():
    return random.choice(EMOJIS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Это бот деградации. Используй /degrade в группе.")


async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    user = update.effective_user
    await ensure_user(user)
    await clean_expired_diseases(user.id)

    user_data = users[user.id]
    now_dt = now()
    if (now_dt - user_data["last_degrade"]).total_seconds() < 3600:
        left = 3600 - int((now_dt - user_data["last_degrade"]).total_seconds())
        await update.message.reply_text(f"Деградировать можно раз в час. Осталось: {left} секунд.")
        return

    if not degrade_actions:
        await update.message.reply_text("Действий для деградации пока нет.")
        return

    action = random.choice(degrade_actions)
    base_penalty = abs(action["iq_change"])
    penalty = calculate_iq_penalty(base_penalty, user.id)
    iq_change = penalty if action["iq_change"] > 0 else -penalty

    user_data["iq"] += iq_change
    user_data["last_degrade"] = now_dt

    text = (
        f"{action['text']}\n"
        f"Твой IQ изменился на {iq_change} {random_emoji()}\n"
        f"Сейчас IQ: {user_data['iq']}"
    )

    chance = 20  # шанс подхватить болезнь
    if diseases_list and random.randint(1, 100) <= chance:
        disease = random.choice(diseases_list)
        duration_hours = random.randint(disease["duration_min"], disease["duration_max"])
        end_time = now_dt + timedelta(hours=duration_hours)
        user_data["diseases"].append(
            {
                "name": disease["name"],
                "multiplier": disease["multiplier"],
                "end_time": end_time,
                "start_time": now_dt,
            }
        )
        text += (
            f"\n{random_emoji()} Вы подхватили болезнь: {disease['name']}! "
            f"IQ теперь падает на {int(disease['multiplier'] * 100)}% больше. "
            f"Болезнь действует до {end_time.strftime('%d.%m %H:%M')} (UTC)."
        )

    await update.message.reply_text(text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    async with lock:
        sorted_users = sorted(users.items(), key=lambda x: x[1]["iq"], reverse=True)[:10]
        if not sorted_users:
            await update.message.reply_text("Пока нет пользователей.")
            return
        msg = "🏆 Топ IQ:\n"
        for i, (uid, data) in enumerate(sorted_users, 1):
            username = data.get("username", f"User{uid}")
            msg += f"{i}. {username} — IQ {data['iq']} {random_emoji()}\n"
    await update.message.reply_text(msg)


async def my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user)
    await clean_expired_diseases(user.id)

    user_data = users[user.id]
    if not user_data["diseases"]:
        await update.message.reply_text("У тебя нет болезней.")
        return

    text = "Твои болезни:\n"
    now_dt = now()
    for d in user_data["diseases"]:
        remaining = d["end_time"] - now_dt
        if remaining.total_seconds() > 0:
            rem_str = f"Осталось: {str(remaining).split('.')[0]}"
        else:
            rem_str = f"Истекла {d['end_time'].strftime('%d.%m %H:%M')} (UTC)"
        start_str = d["start_time"].strftime('%d.%m %H:%M')
        text += f"{start_str} - {d['name']} - {rem_str}\n"
    await update.message.reply_text(text)


# --- Админка ---

async def is_admin(update: Update):
    return update.effective_user.id == ADMIN_ID


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование:\n/add текст iq_change")
        return
    try:
        iq_change = int(context.args[-1])
    except:
        await update.message.reply_text("Последний аргумент должен быть числом (iq_change).")
        return
    text = " ".join(context.args[:-1])
    async with lock:
        degrade_actions.append({"text": text, "iq_change": iq_change})
    await update.message.reply_text(f"Добавлено действие:\n{text} ({iq_change} IQ)")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Использование:\n/del номер")
        return
    try:
        idx = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Нужно число.")
        return
    async with lock:
        if 0 <= idx < len(degrade_actions):
            removed = degrade_actions.pop(idx)
            await update.message.reply_text(f"Удалено: {removed['text']}")
        else:
            await update.message.reply_text("Неверный номер.")


async def list_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        if not degrade_actions:
            await update.message.reply_text("Действий пока нет.")
            return
        msg = "Действия деградации:\n"
        for i, action in enumerate(degrade_actions, 1):
            iq_ch = action["iq_change"]
            sign = "+" if iq_ch > 0 else ""
            msg += f"{i}. {action['text']} ({sign}{iq_ch} IQ)\n"
    await update.message.reply_text(msg)


# --- Болезни ---

async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    # Формат: /adddisease имя множитель длительность_мин длительность_макс
    if len(context.args) != 4:
        await update.message.reply_text("Использование:\n/adddisease имя множитель дл_мин дл_макс")
        return
    name = context.args[0]
    try:
        multiplier = float(context.args[1])
        dur_min = int(context.args[2])
        dur_max = int(context.args[3])
    except:
        await update.message.reply_text("Ошибка в формате аргументов.")
        return
    async with lock:
        diseases_list.append(
            {"name": name, "multiplier": multiplier, "duration_min": dur_min, "duration_max": dur_max}
        )
    await update.message.reply_text(f"Добавлена болезнь: {name} (множитель {multiplier}, длительность {dur_min}-{dur_max} ч.)")


async def list_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        if not diseases_list:
            await update.message.reply_text("Болезней пока нет.")
            return
        msg = "Список болезней:\n"
        for i, d in enumerate(diseases_list, 1):
            msg += f"{i}. {d['name']} — множитель: {d['multiplier']}, длительность: {d['duration_min']}-{d['duration_max']} ч.\n"
    await update.message.reply_text(msg)


async def del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Использование:\n/deldisease номер")
        return
    try:
        idx = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Нужно число.")
        return
    async with lock:
        if 0 <= idx < len(diseases_list):
            removed = diseases_list.pop(idx)
            await update.message.reply_text(f"Удалена болезнь: {removed['name']}")
        else:
            await update.message.reply_text("Неверный номер.")


# --- Очки и команды за очки ---

async def points_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Использование:\n/points_add @ник кол-во")
        return
    username = context.args[0].lstrip("@")
    try:
        amount = int(context.args[1])
    except:
        await update.message.reply_text("Количество должно быть числом.")
        return

    async with lock:
        # ищем пользователя по нику
        found_id = None
        for uid, data in users.items():
            if data.get("username", "").lower() == username.lower():
                found_id = uid
                break
        if found_id is None:
            await update.message.reply_text("Пользователь не найден.")
            return
        users[found_id]["points"] = users[found_id].get("points", 0) + amount
        await update.message.reply_text(f"Добавлено {amount} очков пользователю @{username}. Теперь: {users[found_id]['points']}.")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user)
    if len(context.args) < 1:
        await update.message.reply_text("Использование:\n/d текст команды (за очки)")
        return

    text = " ".join(context.args)
    user_data = users[user.id]
    cost = 20  # цена за добавление команды

    if user_data.get("points", 0) < cost:
        await update.message.reply_text(f"Недостаточно очков. Нужно {cost}, у вас {user_data.get('points', 0)}.")
        return

    async with lock:
        user_data["points"] -= cost
        user_custom_commands.append({"user_id": user.id, "text": text})

    await update.message.reply_text(f"Команда добавлена за {cost} очков. Остаток очков: {user_data['points']}.")


async def list_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        if not user_custom_commands:
            await update.message.reply_text("Пользовательских команд пока нет.")
            return
        msg = "Пользовательские команды:\n"
        for i, cmd in enumerate(user_custom_commands, 1):
            uid = cmd["user_id"]
            uname = users.get(uid, {}).get("username", f"User{uid}")
            msg += f"{i}. @{uname}: {cmd['text']}\n"
    await update.message.reply_text(msg)


# --- Сбросы ---

async def reset_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        for u in users.values():
            u["iq"] = 100
    await update.message.reply_text("IQ всех пользователей сброшен на 100.")


async def reset_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        for u in users.values():
            u["diseases"] = []
    await update.message.reply_text("Все болезни удалены у всех пользователей.")


async def reset_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    async with lock:
        for u in users.values():
            u["points"] = 0
    await update.message.reply_text("Очки всех пользователей сброшены.")


# --- Регистрация хэндлеров ---

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))

    # Админ команды для действий деградации
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("del", delete))
    app.add_handler(CommandHandler("list", list_actions))

    # Болезни
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("listdisease", list_diseases))
    app.add_handler(CommandHandler("deldisease", del_disease))

    # Очки и пользовательские команды
    app.add_handler(CommandHandler("points_add", points_add))
    app.add_handler(CommandHandler("d", add_command))
    app.add_handler(CommandHandler("listcmd", list_commands))

    # Сбросы
    app.add_handler(CommandHandler("reset_iq", reset_iq))
    app.add_handler(CommandHandler("reset_diseases", reset_diseases))
    app.add_handler(CommandHandler("reset_points", reset_points))

    print("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
