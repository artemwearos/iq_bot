import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# --- НАСТРОЙКИ ---
TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
GROUP_ID = -1001941069892
ADMIN_IDS = {6878462090}  # твой айди сюда

# --- ГЛОБАЛЬНЫЕ ДАННЫЕ ---

# Действия деградации: список словарей с 'text' и 'iq_delta' (отрицательное число)
degrade_actions: List[Dict[str, Any]] = []

# Болезни: список словарей с 'name', 'iq_multiplier', 'min_duration', 'max_duration' (часы)
diseases: List[Dict[str, Any]] = []

# Пользовательские команды деградации: список словарей с 'text', 'iq_delta', 'user_id'
user_commands: List[Dict[str, Any]] = []

# Пользовательские данные:
# user_id -> {"iq": int, "ultra": int, "last_degrade": datetime, "diseases": List[Dict]}
users: Dict[int, Dict[str, Any]] = {}

# Шанс получить болезнь при деградации в процентах
disease_chance = 20

# Смайлы для сообщений (рандом)
smiles = ["🎉", "👽", "🤢", "😵‍💫", "🧠", "💥", "🔥", "❌", "⚡", "💀"]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_user_data(user_id: int) -> Dict[str, Any]:
    if user_id not in users:
        users[user_id] = {
            "iq": 100,
            "ultra": 0,
            "last_degrade": datetime.min,
            "diseases": [],  # каждая болезнь: {"name": str, "end_time": datetime, "iq_multiplier": float}
        }
    return users[user_id]


def calc_iq_loss(base_iq_loss: int, user_data: Dict[str, Any]) -> int:
    # Применить мультипликатор болезней
    multiplier = 1.0
    now = datetime.utcnow()
    # Убираем просроченные болезни
    user_data["diseases"] = [
        dis for dis in user_data["diseases"] if dis["end_time"] > now
    ]
    for dis in user_data["diseases"]:
        multiplier += dis["iq_multiplier"]
    total_loss = int(base_iq_loss * multiplier)
    return total_loss


def format_diseases(user_data: Dict[str, Any]) -> str:
    if not user_data["diseases"]:
        return "Нет болезней."
    now = datetime.utcnow()
    lines = []
    for dis in user_data["diseases"]:
        remain = dis["end_time"] - now
        if remain.total_seconds() > 0:
            h = remain.total_seconds() // 3600
            m = (remain.total_seconds() % 3600) // 60
            lines.append(
                f"{dis['name']} — осталось {int(h)}ч {int(m)}м"
            )
        else:
            lines.append(f"{dis['name']} — болезнь закончилась")
    return "\n".join(lines)


def random_smile() -> str:
    return random.choice(smiles)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для деградации IQ. Используй /degrade для деградации, /top для топа и другие команды."
    )


async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    now = datetime.utcnow()
    if (now - user_data["last_degrade"]).total_seconds() < 3600:
        remain = 3600 - (now - user_data["last_degrade"]).total_seconds()
        m = int(remain // 60)
        s = int(remain % 60)
        await update.message.reply_text(f"⏳ Деградация доступна через {m} мин {s} сек")
        return

    # Выбираем случайное действие из общего списка + пользовательских
    all_actions = degrade_actions + user_commands
    if not all_actions:
        await update.message.reply_text("Пока нет доступных действий деградации.")
        return

    action = random.choice(all_actions)
    base_iq_loss = abs(action["iq_delta"])

    # Применяем болезни
    iq_loss = calc_iq_loss(base_iq_loss, user_data)

    # Минус IQ
    user_data["iq"] -= iq_loss

    # Вероятность получить болезнь
    if diseases and random.randint(1, 100) <= disease_chance:
        new_disease = random.choice(diseases)
        dur_hours = random.randint(new_disease["min_duration"], new_disease["max_duration"])
        end_time = now + timedelta(hours=dur_hours)
        user_data["diseases"].append({
            "name": new_disease["name"],
            "iq_multiplier": new_disease["iq_multiplier"],
            "end_time": end_time,
        })
        disease_msg = (
            f"\n{random_smile()} Вы подхватили болезнь: {new_disease['name']}! "
            f"Теперь ваш IQ будет падать на {int(new_disease['iq_multiplier'] * 100)}% больше."
        )
    else:
        disease_msg = ""

    user_data["last_degrade"] = now

    text = f"{action['text']}, твой IQ упал на {iq_loss} {random_smile()}\nСейчас IQ: {user_data['iq']}{disease_msg}"
    await update.message.reply_text(text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    if not users:
        await update.message.reply_text("Нет данных по пользователям.")
        return
    # Сортируем по IQ по убыванию
    sorted_users = sorted(users.items(), key=lambda x: x[1]["iq"], reverse=True)
    msg = "🏆 Топ по IQ:\n"
    for i, (uid, data) in enumerate(sorted_users[:10], 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name
        except Exception:
            name = str(uid)
        msg += f"{i}. {name} — IQ: {data['iq']}\n"
    await update.message.reply_text(msg)


async def my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    iq = user_data["iq"]
    ultra = user_data["ultra"]
    diseases_text = format_diseases(user_data)
    last_deg = user_data["last_degrade"]
    now = datetime.utcnow()
    cooldown = max(0, 3600 - (now - last_deg).total_seconds())
    m = int(cooldown // 60)
    s = int(cooldown % 60)

    text = (
        f"Твой IQ: {iq}\n"
        f"Ultra очков: {ultra}\n"
        f"Болезни:\n{diseases_text}\n"
        f"Деградация доступна через: {m} мин {s} сек"
    )
    await update.message.reply_text(text)


async def add_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /add <текст> <минус_iq>")
        return
    *text_parts, iq_str = context.args
    text = " ".join(text_parts)
    try:
        iq_delta = int(iq_str)
    except ValueError:
        await update.message.reply_text("❌ IQ должен быть числом (отрицательным).")
        return
    if iq_delta >= 0:
        await update.message.reply_text("❌ IQ должен быть отрицательным числом.")
        return

    degrade_actions.append({"text": text, "iq_delta": iq_delta})
    await update.message.reply_text(f"✅ Добавлено действие деградации:\n{text} ({iq_delta} IQ)")


async def del_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if not context.args:
        await update.message.reply_text("❌ Формат: /del <номер действия>")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ Номер должен быть числом.")
        return
    if 0 <= idx < len(degrade_actions):
        removed = degrade_actions.pop(idx)
        await update.message.reply_text(f"✅ Удалено действие: {removed['text']}")
    else:
        await update.message.reply_text("❌ Неверный номер действия.")


async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 4:
        await update.message.reply_text("❌ Формат: /adddisease <название> <множитель> <мин. часы> <макс. часы>")
        return
    name = context.args[0]
    try:
        multiplier = float(context.args[1])
        min_h = int(context.args[2])
        max_h = int(context.args[3])
    except ValueError:
        await update.message.reply_text("❌ Некорректные параметры. Множитель - число с плавающей точкой, часы - целые.")
        return
    if min_h > max_h or min_h <= 0 or max_h <= 0:
        await update.message.reply_text("❌ Неверный диапазон часов.")
        return
    diseases.append({
        "name": name,
        "iq_multiplier": multiplier,
        "min_duration": min_h,
        "max_duration": max_h
    })
    await update.message.reply_text(f"✅ Болезнь '{name}' добавлена.")


async def del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if not context.args:
        await update.message.reply_text("❌ Формат: /deldisease <номер болезни>")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ Номер должен быть числом.")
        return
    if 0 <= idx < len(diseases):
        removed = diseases.pop(idx)
        await update.message.reply_text(f"✅ Удалена болезнь: {removed['name']}")
    else:
        await update.message.reply_text("❌ Неверный номер болезни.")


async def list_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not diseases:
        await update.message.reply_text("Пока нет болезней.")
        return
    text = "Болезни:\n"
    for i, d in enumerate(diseases, 1):
        text += (f"{i}. {d['name']} — Множитель IQ: {d['iq_multiplier']}, "
                 f"Длительность: от {d['min_duration']}ч до {d['max_duration']}ч\n")
    await update.message.reply_text(text)


async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 1:
        await update.message.reply_text("❌ Формат: /d <текст команды>")
        return
    user_data = get_user_data(user_id)
    if user_data["ultra"] < 1:
        await update.message.reply_text("❌ У тебя нет ultra очков для создания команды.")
        return
    text = " ".join(context.args)
    user_commands.append({"text": text, "iq_delta": -1, "user_id": user_id})
    user_data["ultra"] -= 1
    await update.message.reply_text(f"✅ Твоя команда добавлена в список деградаций. Осталось ultra очков: {user_data['ultra']}")


async def list_user_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_commands:
        await update.message.reply_text("Нет пользовательских команд деградации.")
        return
    text = "Пользовательские команды деградации:\n"
    for i, cmd in enumerate(user_commands, 1):
        user_name = "Пользователь"
        try:
            user = await context.bot.get_chat(cmd["user_id"])
            user_name = user.first_name
        except Exception:
            pass
        text += f"{i}. {cmd['text']} (от {user_name})\n"
    await update.message.reply_text(text)


async def set_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /setiq <id> <значение>")
        return
    try:
        target_id = int(context.args[0])
        new_iq = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ ID и IQ должны быть числами.")
        return
    target_data = get_user_data(target_id)
    target_data["iq"] = new_iq
    await update.message.reply_text(f"✅ IQ пользователя {target_id} установлен в {new_iq}")


async def set_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Формат: /setultra <id> <значение>")
        return
    try:
        target_id = int(context.args[0])
        new_ultra = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ ID и ultra очки должны быть числами.")
        return
    target_data = get_user_data(target_id)
    target_data["ultra"] = new_ultra
    await update.message.reply_text(f"✅ Ultra очки пользователя {target_id} установлены в {new_ultra}")


async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    for uid in users:
        users[uid]["iq"] = 100
        users[uid]["ultra"] = 0
        users[uid]["diseases"] = []
    degrade_actions.clear()
    diseases.clear()
    user_commands.clear()
    await update.message.reply_text("✅ Все данные сброшены.")


async def reset_diseases_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    for uid in users:
        users[uid]["diseases"] = []
    await update.message.reply_text("✅ Болезни у всех сброшены.")


async def set_disease_chance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    global disease_chance
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    if not context.args:
        await update.message.reply_text(f"Текущий шанс заболеть: {disease_chance}%")
        return
    try:
        new_chance = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Значение должно быть числом.")
        return
    if not 0 <= new_chance <= 100:
        await update.message.reply_text("❌ Значение должно быть от 0 до 100.")
        return
    disease_chance = new_chance
    await update.message.reply_text(f"✅ Шанс заболевания установлен в {disease_chance}%")


async def admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return

    text = "=== Админ панель ===\n\n"

    text += "Действия деградации:\n"
    if degrade_actions:
        for i, act in enumerate(degrade_actions, 1):
            text += f"{i}. {act['text']} (IQ {act['iq_delta']})\n"
    else:
        text += "Пока нет действий.\n"

    text += "\nБолезни:\n"
    if diseases:
        for i, dis in enumerate(diseases, 1):
            text += (f"{i}. {dis['name']} — множитель IQ: {dis['iq_multiplier']}, "
                     f"длительность: от {dis['min_duration']}ч до {dis['max_duration']}ч\n")
    else:
        text += "Пока нет болезней.\n"

    text += "\nПользовательские команды деградации:\n"
    if user_commands:
        for i, cmd in enumerate(user_commands, 1):
            try:
                user = await context.bot.get_chat(cmd["user_id"])
                user_name = user.first_name
            except Exception:
                user_name = str(cmd["user_id"])
            text += f"{i}. {cmd['text']} (от {user_name})\n"
    else:
        text += "Нет пользовательских команд.\n"

    text += f"\nШанс заболевания: {disease_chance}%\n"

    await update.message.reply_text(text)


async def d_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /d <текст> — списывает 1 ultra очко, добавляет пользовательскую команду деградации
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    if not context.args:
        await update.message.reply_text("❌ Использование: /d <текст команды>")
        return

    if user_data["ultra"] < 1:
        await update.message.reply_text("❌ У тебя нет ultra очков для создания команды.")
        return

    text = " ".join(context.args)
    user_commands.append({"text": text, "iq_delta": -1, "user_id": user_id})
    user_data["ultra"] -= 1

    await update.message.reply_text(f"✅ Твоя команда добавлена в список деградаций. Осталось ultra очков: {user_data['ultra']}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("my", my))

    app.add_handler(CommandHandler("add", add_degrade))
    app.add_handler(CommandHandler("del", del_degrade))
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("deldisease", del_disease))
    app.add_handler(CommandHandler("listdiseases", list_diseases))
    app.add_handler(CommandHandler("listusercommands", list_user_commands))
    app.add_handler(CommandHandler("setiq", set_iq))
    app.add_handler(CommandHandler("setultra", set_ultra))
    app.add_handler(CommandHandler("resetall", reset_all))
    app.add_handler(CommandHandler("resetdiseases", reset_diseases_all))
    app.add_handler(CommandHandler("setdiseasechance", set_disease_chance))
    app.add_handler(CommandHandler("eair", admin_info))
    app.add_handler(CommandHandler("d", d_command))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
