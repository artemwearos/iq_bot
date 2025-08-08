import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, Chat, ChatMember
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters

# Настройки
BOT_TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"
ALLOWED_GROUP_ID = -1001941069892  # твоя группа
ADMIN_ID = 6878462090

# Логи
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Данные бота (память)
users_iq = {}  # user_id: iq (int)
users_last_degrade = {}  # user_id: datetime
users_diseases = {}  # user_id: list of dicts {name, start, duration_hrs, effect_percent}
degrade_actions = []  # list of dicts {text:str, iq_delta:int}
degrade_custom_cmds = []  # list of dicts {user_id:int, text:str}
disease_list = []  # list of dicts {name:str, effect_percent:int, min_dur:int, max_dur:int}

users_points = {}  # user_id: int (очки для пользовательских команд)

# Смайлы для рандома
EMOJIS = ['🎉', '👽', '🤢', '😵', '💀', '🤡', '🧟', '🤖', '🔥', '🧠', '👻', '😈']

def get_random_emoji():
    return random.choice(EMOJIS)

def current_time():
    return datetime.utcnow()

def format_time_diff(dt: datetime):
    now = current_time()
    diff = dt - now
    if diff.total_seconds() <= 0:
        return "0 секунд"
    hours, remainder = divmod(int(diff.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    if seconds > 0:
        parts.append(f"{seconds} с")
    return " ".join(parts)

def get_user_nick(update: Update, user_id: int):
    # Пытаемся получить никнейм пользователя из чата, если нет - id
    chat = update.effective_chat
    try:
        member = chat.get_member(user_id)
        if member.user.username:
            return f"@{member.user.username}"
        else:
            name = member.user.first_name or "User"
            return f"{name}"
    except Exception:
        return str(user_id)

def calc_disease_effect(user_id):
    # Суммируем эффект всех активных болезней у пользователя
    if user_id not in users_diseases:
        return 0
    now = current_time()
    total_percent = 0
    for d in users_diseases[user_id]:
        end_time = d['start'] + timedelta(hours=d['duration_hrs'])
        if end_time > now:
            total_percent += d['effect_percent']
    return total_percent

def clean_expired_diseases():
    now = current_time()
    for uid in list(users_diseases.keys()):
        new_list = []
        for d in users_diseases[uid]:
            end_time = d['start'] + timedelta(hours=d['duration_hrs'])
            if end_time > now:
                new_list.append(d)
        users_diseases[uid] = new_list
        if not users_diseases[uid]:
            del users_diseases[uid]

async def ensure_user_initialized(user_id):
    if user_id not in users_iq:
        users_iq[user_id] = 100
    if user_id not in users_last_degrade:
        users_last_degrade[user_id] = datetime.fromtimestamp(0)
    if user_id not in users_points:
        users_points[user_id] = 0

def check_group(update: Update):
    return update.effective_chat and update.effective_chat.id == ALLOWED_GROUP_ID

# ========== Команды ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Пиши мне в личку для управления и информации.")
        return
    await update.message.reply_text("Привет! Я бот для деградации IQ. В группе используйте /degrade.")

async def degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_group(update):
        return
    user_id = update.effective_user.id
    await ensure_user_initialized(user_id)

    now = current_time()
    last = users_last_degrade[user_id]
    diff = (now - last).total_seconds()
    if diff < 3600:
        remain = format_time_diff(last + timedelta(hours=1))
        await update.message.reply_text(f"⏳ Подожди ещё {remain} до следующей деградации.")
        return

    if not degrade_actions:
        await update.message.reply_text("Пока нет действий для деградации.")
        return

    # Выбираем случайное действие с равной вероятностью
    action = random.choice(degrade_actions)
    base_iq_delta = action['iq_delta']

    # Считаем эффект болезней
    effect_percent = calc_disease_effect(user_id)
    total_iq_delta = int(base_iq_delta * (1 + effect_percent / 100))

    users_iq[user_id] += total_iq_delta
    users_last_degrade[user_id] = now

    emoji = get_random_emoji()
    msg = (f"{action['text']}, твой IQ изменился на {total_iq_delta} {emoji}\n"
           f"Сейчас твой IQ: {users_iq[user_id]}")

    # Рандомно шанс заболеть
    if disease_list:
        chance = random.randint(1, 100)
        if chance <= 10:  # 10% шанс заболеть
            disease = random.choice(disease_list)
            duration = random.randint(disease['min_dur'], disease['max_dur'])
            new_disease = {
                "name": disease['name'],
                "start": now,
                "duration_hrs": duration,
                "effect_percent": disease['effect_percent']
            }
            users_diseases.setdefault(user_id, []).append(new_disease)
            msg += f"\n{get_random_emoji()} Вы подхватили болезнь: {disease['name']}. " \
                   f"Теперь IQ падает на {disease['effect_percent']}% больше {get_random_emoji()}"
    await update.message.reply_text(msg)

async def my_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users_diseases or not users_diseases[user_id]:
        await update.message.reply_text("У тебя нет болезней.")
        return
    now = current_time()
    msgs = []
    for d in users_diseases[user_id]:
        end_time = d['start'] + timedelta(hours=d['duration_hrs'])
        if end_time > now:
            remain = format_time_diff(end_time)
            msgs.append(f"{d['name']} - осталось: {remain}")
        else:
            msgs.append(f"{d['name']} - истекла {end_time.strftime('%Y-%m-%d %H:%M:%S')} (МСК)")
    await update.message.reply_text("\n".join(msgs))

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_group(update):
        return
    if not users_iq:
        await update.message.reply_text("Пока нет данных по IQ.")
        return
    sorted_users = sorted(users_iq.items(), key=lambda x: x[1])
    msg = "Топ IQ (от самого низкого):\n"
    for i, (uid, iq) in enumerate(sorted_users[:10], 1):
        nick = get_user_nick(update, uid)
        emoji = get_random_emoji()
        msg += f"{i}. {nick} — {iq} {emoji}\n"
    await update.message.reply_text(msg)

# --- Админские команды ---

def is_admin(user_id):
    return user_id == ADMIN_ID

async def eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return

    msg = "=== Админка ===\n\n"

    msg += "Действия деградации:\n"
    if degrade_actions:
        for i, act in enumerate(degrade_actions, 1):
            msg += f"{i}. {act['text']} (IQ {act['iq_delta']})\n"
    else:
        msg += "Пока нет действий.\n"

    msg += "\nБолезни:\n"
    if disease_list:
        for i, d in enumerate(disease_list, 1):
            msg += (f"{i}. {d['name']} — эффект {d['effect_percent']}%, "
                    f"длительность {d['min_dur']}–{d['max_dur']} ч\n")
    else:
        msg += "Пока нет болезней.\n"

    msg += "\nПользовательские команды деградации:\n"
    if degrade_custom_cmds:
        for i, cmd in enumerate(degrade_custom_cmds, 1):
            msg += f"{i}. ({cmd['user_id']}) {cmd['text']}\n"
    else:
        msg += "Нет пользовательских команд.\n"

    msg += "\nТекущие пользователи IQ:\n"
    if users_iq:
        for uid, iq in users_iq.items():
            msg += f"{uid}: {iq}\n"
    else:
        msg += "Пока нет пользователей.\n"

    msg += "\nОчки пользователей:\n"
    if users_points:
        for uid, pts in users_points.items():
            msg += f"{uid}: {pts}\n"
    else:
        msg += "Нет очков.\n"

    await update.message.reply_text(msg)

async def add_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Используй: /add <текст действия> <число IQ>")
        return
    try:
        iq_delta = int(args[-1])
        text = " ".join(args[:-1])
    except:
        await update.message.reply_text("Ошибка в формате IQ. Должно быть число.")
        return
    degrade_actions.append({"text": text, "iq_delta": iq_delta})
    await update.message.reply_text(f"Добавлено действие: {text} (IQ {iq_delta})")

async def del_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Используй: /del <номер>")
        return
    try:
        idx = int(args[0]) - 1
        if idx < 0 or idx >= len(degrade_actions):
            await update.message.reply_text("Неверный номер.")
            return
        deleted = degrade_actions.pop(idx)
        await update.message.reply_text(f"Удалено действие: {deleted['text']}")
    except:
        await update.message.reply_text("Ошибка в номере.")

async def add_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) < 4:
        await update.message.reply_text("Используй: /adddisease <название> <эффект%> <мин часы> <макс часы>")
        return
    try:
        name = args[0]
        effect = int(args[1])
        minh = int(args[2])
        maxh = int(args[3])
        if minh > maxh:
            await update.message.reply_text("Мин. часы не могут быть больше макс. часов.")
            return
    except:
        await update.message.reply_text("Ошибка в аргументах.")
        return
    disease_list.append({
        "name": name,
        "effect_percent": effect,
        "min_dur": minh,
        "max_dur": maxh
    })
    await update.message.reply_text(f"Добавлена болезнь {name} с эффектом {effect}%, длительность {minh}-{maxh} ч")

async def del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Используй: /deldisease <номер>")
        return
    try:
        idx = int(args[0]) - 1
        if idx < 0 or idx >= len(disease_list):
            await update.message.reply_text("Неверный номер.")
            return
        deleted = disease_list.pop(idx)
        await update.message.reply_text(f"Удалена болезнь {deleted['name']}")
    except:
        await update.message.reply_text("Ошибка в номере.")

async def set_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используй: /setiq <user_id> <iq>")
        return
    try:
        uid = int(args[0])
        iq = int(args[1])
        users_iq[uid] = iq
        await update.message.reply_text(f"Установлен IQ {iq} для пользователя {uid}")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    users_iq.clear()
    users_last_degrade.clear()
    users_diseases.clear()
    degrade_actions.clear()
    degrade_custom_cmds.clear()
    disease_list.clear()
    users_points.clear()
    await update.message.reply_text("Все данные сброшены!")

async def reset_diseases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    users_diseases.clear()
    await update.message.reply_text("Все болезни у всех пользователей сброшены!")

async def add_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if
    async def add_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Ты не админ.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используй: /addpoints <user_id> <очки>")
        return
    try:
        uid = int(args[0])
        pts = int(args[1])
        users_points[uid] = users_points.get(uid, 0) + pts
        await update.message.reply_text(f"Добавлено {pts} очков пользователю {uid}. Текущие очки: {users_points[uid]}")
    except:
        await update.message.reply_text("Ошибка в аргументах.")

async def user_add_degrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_user_initialized(user_id)

    # Проверка баланса очков
    if users_points.get(user_id, 0) < 1:
        await update.message.reply_text("У тебя недостаточно очков для добавления команды деградации (нужно 1 очко).")
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Используй: /d <текст команды>")
        return

    degrade_custom_cmds.append({
        "user_id": user_id,
        "text": text
    })

    # Снимаем 1 очко
    users_points[user_id] -= 1
    await update.message.reply_text(f"Команда добавлена. У тебя осталось {users_points[user_id]} очков.")

    # Уведомление админу
    try:
        await context.bot.send_message(ADMIN_ID, f"Пользователь {user_id} добавил команду деградации:\n{text}")
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

async def list_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_group(update):
        return

    msg = "Доступные команды:\n"
    msg += "/degrade — выполнить деградацию IQ (раз в час)\n"
    msg += "/my — посмотреть свои болезни и их статус\n"
    msg += "/top — топ пользователей по IQ\n"
    if update.effective_user.id == ADMIN_ID:
        msg += "\nАдмин команды:\n"
        msg += "/eair — показать админ панель\n"
        msg += "/add <текст действия> <IQ> — добавить действие деградации\n"
        msg += "/del <номер> — удалить действие деградации\n"
        msg += "/adddisease <название> <эффект%> <мин часы> <макс часы> — добавить болезнь\n"
        msg += "/deldisease <номер> — удалить болезнь\n"
        msg += "/setiq <user_id> <iq> — установить IQ пользователю\n"
        msg += "/addpoints <user_id> <очки> — добавить очки пользователю\n"
        msg += "/reset — сбросить все данные\n"
        msg += "/resetdiseases — сбросить все болезни\n"
    msg += "\nПользовательские команды деградации:\n"
    if degrade_custom_cmds:
        for i, cmd in enumerate(degrade_custom_cmds, 1):
            msg += f"{i}. ({cmd['user_id']}) {cmd['text']}\n"
    else:
        msg += "Пока нет пользовательских команд.\n"
    await update.message.reply_text(msg)

# Обработка пользовательской кастомной команды деградации (рандомно срабатывает в degrade)
def get_random_custom_degrade():
    if degrade_custom_cmds:
        return random.choice(degrade_custom_cmds)['text']
    return None

async def degrade_with_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Для замены команды /degrade - можно не использовать, т.к. основной degrade уже есть.
    # Но можно добавить вывод кастомной команды с IQ эффектом 0 или -1 для эффекта.
    pass

# Регистрация обработчиков

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("degrade", degrade))
    app.add_handler(CommandHandler("my", my_diseases))
    app.add_handler(CommandHandler("top", top))

    app.add_handler(CommandHandler("eair", eair))
    app.add_handler(CommandHandler("add", add_degrade))
    app.add_handler(CommandHandler("del", del_degrade))
    app.add_handler(CommandHandler("adddisease", add_disease))
    app.add_handler(CommandHandler("deldisease", del_disease))
    app.add_handler(CommandHandler("setiq", set_iq))
    app.add_handler(CommandHandler("reset", reset_all))
    app.add_handler(CommandHandler("resetdiseases", reset_diseases))
    app.add_handler(CommandHandler("addpoints", add_points))
    app.add_handler(CommandHandler("d", user_add_degrade_cmd))
    app.add_handler(CommandHandler("list", list_commands))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
