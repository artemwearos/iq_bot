# main.py
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"  # Вставь свой токен
ALLOWED_GROUP_ID = -1001941069892  # Работает только в этой группе
ADMIN_IDS = {6878462090}  # Множество админов (твой id)

DATA_FILE = Path("data.json")
SAVE_INTERVAL = 10  # сек (фоновая автосохранение; также сохраняем при изменениях)

DEGRADE_COOLDOWN_SEC = 3600  # 1 час
DISEASE_CHANCE_DEFAULT = 20  # %

EMOJIS = ["🎉", "👽", "🤢", "😵", "💀", "🤡", "🧠", "🔥", "❌", "⚡️"]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# -------------- STATE & LOCK --------------
lock = asyncio.Lock()


def utc_now():
    return datetime.utcnow()


def dt_to_iso(dt: datetime) -> str:
    return dt.isoformat()


def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# -------------- DATA MODEL (in memory) --------------
# data schema stored in data.json
default_data = {
    "users": {},  # user_id -> {"iq": int, "ultra": int, "last_degrade": iso str or "", "diseases": [ {name, start_iso, duration_h, multiplier} ]}
    "degrade_actions": [],  # [ {"text": str, "iq_delta": int} ]
    "diseases": [],  # [ {"name": str, "multiplier": float, "min_hours": int, "max_hours": int} ]
    "user_commands": [],  # [ {"user_id": int, "text": str} ]
    "disease_chance": DISEASE_CHANCE_DEFAULT
}

DATA: Dict[str, Any] = {}
_save_task = None
_app = None  # Application instance (set later)


# -------------- PERSISTENCE --------------
def load_data():
    global DATA
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                DATA = json.load(f)
            # Backwards compatibility: ensure keys exist
            for k in default_data:
                if k not in DATA:
                    DATA[k] = default_data[k]
        except Exception as e:
            log.exception("Failed to load data.json, starting with default. Error: %s", e)
            DATA = default_data.copy()
    else:
        DATA = default_data.copy()
    # ensure types
    if "disease_chance" not in DATA:
        DATA["disease_chance"] = DISEASE_CHANCE_DEFAULT


def save_data():
    try:
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(DATA, f, ensure_ascii=False, indent=2)
        log.info("Data saved.")
    except Exception:
        log.exception("Failed to save data.")


async def autosave_loop():
    while True:
        await asyncio.sleep(SAVE_INTERVAL)
        async with lock:
            save_data()


# -------------- HELPERS --------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def ensure_user(user_id: int):
    users = DATA.setdefault("users", {})
    s = users.get(str(user_id))
    if not s:
        users[str(user_id)] = {
            "iq": 100,
            "ultra": 0,
            "last_degrade": "",  # ISO string
            "diseases": []  # each: {name, start_iso, duration_h, multiplier}
        }
    return users[str(user_id)]


def get_last_degrade(user_rec: dict) -> datetime:
    s = user_rec.get("last_degrade", "")
    if s:
        try:
            return iso_to_dt(s)
        except Exception:
            return datetime.fromtimestamp(0)
    return datetime.fromtimestamp(0)


def set_last_degrade(user_rec: dict, dt: datetime):
    user_rec["last_degrade"] = dt_to_iso(dt)


def active_diseases(user_rec: dict) -> List[dict]:
    now = utc_now()
    out = []
    newlist = []
    for d in user_rec.get("diseases", []):
        try:
            start = iso_to_dt(d["start_iso"])
            duration_h = int(d["duration_h"])
            end = start + timedelta(hours=duration_h)
            if end > now:
                out.append(d)
                newlist.append(d)
        except Exception:
            continue
    # replace with only active
    user_rec["diseases"] = newlist
    return out


def diseases_multiplier(user_rec: dict) -> float:
    # returns additional multiplier factor sum (e.g. 0.3 means +30%)
    total = 0.0
    for d in active_diseases(user_rec):
        total += float(d.get("multiplier", 0))
    return total


def format_remaining(start_iso: str, duration_h: int) -> str:
    try:
        start = iso_to_dt(start_iso)
    except Exception:
        return "unknown"
    end = start + timedelta(hours=duration_h)
    now = utc_now()
    if end <= now:
        return f"истекла {end.strftime('%d.%m %H:%M')} (UTC)"
    rem = end - now
    h = rem.seconds // 3600 + rem.days * 24
    m = (rem.seconds % 3600) // 60
    return f"осталось {h}ч {m}м (до {end.strftime('%d.%m %H:%M')} UTC)"


def random_emoji() -> str:
    return random.choice(EMOJIS)


# -------------- ADMIN MENU STATES --------------
# Conversation states
(
    S_MENU,
    S_ADD_ACTION_TEXT,
    S_ADD_ACTION_IQ,
    S_DEL_ACTION,
    S_ADD_DISEASE_NAME,
    S_ADD_DISEASE_MIN,
    S_ADD_DISEASE_MAX,
    S_ADD_DISEASE_MULT,
    S_DEL_DISEASE,
    S_SET_IQ,
    S_SET_ULTRA,
    S_SET_POINTS,
    S_RESET_TIMERS_CONFIRM,
    S_SET_DISEASE_CHANCE,
) = range(14)


# -------------- ADMIN INLINE MENU & HANDLERS --------------
def admin_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("Добавить действие", callback_data="menu_add_action")],
        [InlineKeyboardButton("Удалить действие", callback_data="menu_del_action")],
        [InlineKeyboardButton("Список действий", callback_data="menu_list_actions")],
        [InlineKeyboardButton("Добавить болезнь", callback_data="menu_add_disease")],
        [InlineKeyboardButton("Удалить болезнь", callback_data="menu_del_disease")],
        [InlineKeyboardButton("Список болезней", callback_data="menu_list_diseases")],
        [InlineKeyboardButton("Пользовательские команды", callback_data="menu_list_usercmds")],
        [InlineKeyboardButton("Выдать ultra / points / IQ", callback_data="menu_manage_users")],
        [InlineKeyboardButton("Сброс таймеров всем", callback_data="menu_reset_timers")],
        [InlineKeyboardButton("Установить шанс болезни", callback_data="menu_set_chance")],
        [InlineKeyboardButton("Выйти", callback_data="menu_exit")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def cmd_eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start admin menu (Conversation entry)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Доступ только для админов.")
        return ConversationHandler.END

    text = (
        "🛠️ *Админ панель*\n\n"
        "Здесь вы можете добавить/удалить действия и болезни, выдать ultra/iq/очки, "
        "сбросить таймеры и т.д.\n\n"
        "Нажмите кнопку ниже для выбора действия."
    )
    await update.message.reply_text(text, reply_markup=admin_main_keyboard(), parse_mode="Markdown")
    return S_MENU


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline menu callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.message.edit_text("🚫 Доступ только для админов.")
        return ConversationHandler.END

    # ROUTING
    if data == "menu_add_action":
        await query.message.reply_text("Введите текст действия (пример: 'Купил айфон в кредит'):")
        return S_ADD_ACTION_TEXT

    if data == "menu_add_disease":
        await query.message.reply_text("Введите название болезни (без пробелов рекомендуется):")
        return S_ADD_DISEASE_NAME

    if data == "menu_del_action":
        # show list
        items = DATA.get("degrade_actions", [])
        if not items:
            await query.message.reply_text("Пока нет действий для удаления.")
            return S_MENU
        text = "Список действий (введите номер для удаления):\n"
        for i, a in enumerate(items, 1):
            text += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
        await query.message.reply_text(text)
        return S_DEL_ACTION

    if data == "menu_list_actions":
        items = DATA.get("degrade_actions", [])
        text = "Действия деградации:\n" if items else "Пока нет действий.\n"
        for i, a in enumerate(items, 1):
            text += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
        await query.message.reply_text(text)
        return S_MENU

    if data == "menu_del_disease":
        items = DATA.get("diseases", [])
        if not items:
            await query.message.reply_text("Пока нет болезней.")
            return S_MENU
        text = "Список болезней (введите номер для удаления):\n"
        for i, d in enumerate(items, 1):
            text += f"{i}. {d['name']} (x{d['multiplier']}, {d['min_hours']}-{d['max_hours']}ч)\n"
        await query.message.reply_text(text)
        return S_DEL_DISEASE

    if data == "menu_list_diseases":
        items = DATA.get("diseases", [])
        if not items:
            await query.message.reply_text("Пока нет болезней.")
            return S_MENU
        text = "Болезни:\n"
        for i, d in enumerate(items, 1):
            text += f"{i}. {d['name']} — множитель: {d['multiplier']}, длительность: {d['min_hours']}-{d['max_hours']} ч\n"
        await query.message.reply_text(text)
        return S_MENU

    if data == "menu_list_usercmds":
        items = DATA.get("user_commands", [])
        if not items:
            await query.message.reply_text("Нет пользовательских команд.")
            return S_MENU
        text = "Пользовательские команды:\n"
        for i, c in enumerate(items, 1):
            text += f"{i}. ({c['user_id']}) {c['text']}\n"
        await query.message.reply_text(text)
        return S_MENU

    if data == "menu_manage_users":
        # present sub buttons
        kb = [
            [InlineKeyboardButton("Установить IQ", callback_data="menu_set_iq")],
            [InlineKeyboardButton("Установить ultra", callback_data="menu_set_ultra")],
            [InlineKeyboardButton("Выдать очки (points)", callback_data="menu_set_points")],
            [InlineKeyboardButton("Назад", callback_data="menu_back")],
        ]
        await query.message.reply_text("Выберите действие для управления пользователями:", reply_markup=InlineKeyboardMarkup(kb))
        return S_MENU

    if data == "menu_set_iq":
        await query.message.reply_text("Введи: <user_id> <iq>")
        return S_SET_IQ

    if data == "menu_set_ultra":
        await query.message.reply_text("Введи: <user_id> <ultra>")
        return S_SET_ULTRA

    if data == "menu_set_points":
        await query.message.reply_text("Введи: <user_id> <points>")
        return S_SET_POINTS

    if data == "menu_reset_timers":
        # confirm
        kb = [
            [InlineKeyboardButton("Подтвердить сброс таймеров", callback_data="confirm_reset_timers")],
            [InlineKeyboardButton("Отмена", callback_data="menu_exit")],
        ]
        await query.message.reply_text("Вы уверены? Сбросит таймеры деградации у всех пользователей.", reply_markup=InlineKeyboardMarkup(kb))
        return S_RESET_TIMERS_CONFIRM

    if data == "confirm_reset_timers":
        # reset last_degrade for all users
        async with lock:
            for uid, rec in DATA.get("users", {}).items():
                rec["last_degrade"] = ""
            save_data()
        await query.message.edit_text("✅ Таймеры всем сброшены.")
        return ConversationHandler.END

    if data == "menu_set_chance":
        await query.message.reply_text(f"Текущий шанс заболевания: {DATA.get('disease_chance', DISEASE_CHANCE_DEFAULT)}%.\nВведи число 0-100 для установки:")
        return S_SET_DISEASE_CHANCE

    if data == "menu_exit" or data == "menu_back":
        await query.message.edit_text("Выход из админки.")
        return ConversationHandler.END

    # Fallback
    await query.message.reply_text("Неизвестная опция.")
    return S_MENU


# -------------- ADMIN: Conversation text handlers --------------
async def receive_add_action_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Текст не должен быть пустым. Повторите ввод:")
        return S_ADD_ACTION_TEXT
    context.user_data["new_action_text"] = text
    await update.message.reply_text("Теперь введите число IQ (отрицательное для уменьшения, например -3):")
    return S_ADD_ACTION_IQ


async def receive_add_action_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        iq = int(s)
    except ValueError:
        await update.message.reply_text("IQ должен быть целым числом. Попробуйте снова:")
        return S_ADD_ACTION_IQ
    text = context.user_data.pop("new_action_text", None)
    if not text:
        await update.message.reply_text("Что-то пошло не так — начните заново.")
        return ConversationHandler.END
    async with lock:
        DATA.setdefault("degrade_actions", []).append({"text": text, "iq_delta": iq})
        save_data()
    await update.message.reply_text(f"✅ Действие добавлено: {text} ({iq} IQ)")
    return ConversationHandler.END


async def receive_del_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        idx = int(s) - 1
    except ValueError:
        await update.message.reply_text("Нужен номер (число). Попробуйте снова:")
        return S_DEL_ACTION
    async with lock:
        actions = DATA.get("degrade_actions", [])
        if not (0 <= idx < len(actions)):
            await update.message.reply_text("Неверный номер. Операция отменена.")
            return ConversationHandler.END
        removed = actions.pop(idx)
        save_data()
    await update.message.reply_text(f"✅ Удалено: {removed['text']}")
    return ConversationHandler.END


async def receive_add_disease_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не должно быть пустым. Введите название:")
        return S_ADD_DISEASE_NAME
    context.user_data["disease_name"] = name
    await update.message.reply_text("Введи минимальное время в часах (целое):")
    return S_ADD_DISEASE_MIN


async def receive_add_disease_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        hmin = int(s)
        if hmin <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Нужен положительный целый час. Введите минимальное время снова:")
        return S_ADD_DISEASE_MIN
    context.user_data["disease_min"] = hmin
    await update.message.reply_text("Введи максимальное время в часах (целое, >= минимального):")
    return S_ADD_DISEASE_MAX


async def receive_add_disease_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        hmax = int(s)
        if hmax <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Нужен положительный целый час. Введите максимальное время снова:")
        return S_ADD_DISEASE_MAX
    if hmax < context.user_data.get("disease_min", 0):
        await update.message.reply_text("Максимум не может быть меньше минимума. Введите снова:")
        return S_ADD_DISEASE_MAX
    context.user_data["disease_max"] = hmax
    await update.message.reply_text("Введи множитель (float), например 1.3 (где 1.0 — без эффекта, 1.3 — +30%):")
    return S_ADD_DISEASE_MULT


async def receive_add_disease_mult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip().replace(",", ".")
    try:
        mult = float(s)
        if mult < 1.0:
            await update.message.reply_text("Множитель должен быть >= 1.0. Введите снова:")
            return S_ADD_DISEASE_MULT
    except ValueError:
        await update.message.reply_text("Неверный формат множителя. Пример: 1.3")
        return S_ADD_DISEASE_MULT
    name = context.user_data.pop("disease_name", None)
    hmin = context.user_data.pop("disease_min", None)
    hmax = context.user_data.pop("disease_max", None)
    if not (name and hmin and hmax):
        await update.message.reply_text("Ошибка данных, начните заново.")
        return ConversationHandler.END
    async with lock:
        DATA.setdefault("diseases", []).append({
            "name": name,
            "multiplier": mult,
            "min_hours": int(hmin),
            "max_hours": int(hmax)
        })
        save_data()
    await update.message.reply_text(f"✅ Болезнь '{name}' добавлена: {hmin}-{hmax} ч, x{mult}")
    return ConversationHandler.END


async def receive_del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        idx = int(s) - 1
    except ValueError:
        await update.message.reply_text("Нужен номер (число). Отмена.")
        return ConversationHandler.END
    async with lock:
        arr = DATA.get("diseases", [])
        if not (0 <= idx < len(arr)):
            await update.message.reply_text("Неверный номер.")
            return ConversationHandler.END
        removed = arr.pop(idx)
        save_data()
    await update.message.reply_text(f"✅ Удалена болезнь: {removed['name']}")
    return ConversationHandler.END


async def receive_set_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip().split()
    if len(s) != 2:
        await update.message.reply_text("Нужно 2 аргумента: <user_id> <iq>")
        return S_SET_IQ
    try:
        uid = int(s[0])
        iq = int(s[1])
    except ValueError:
        await update.message.reply_text("ID и IQ должны быть числами.")
        return S_SET_IQ
    async with lock:
        rec = ensure_user(uid)
        rec["iq"] = iq
        save_data()
    await update.message.reply_text(f"✅ IQ пользователя {uid} установлен: {iq}")
    return ConversationHandler.END


async def receive_set_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip().split()
    if len(s) != 2:
        await update.message.reply_text("Нужно 2 аргумента: <user_id> <ultra>")
        return S_SET_ULTRA
    try:
        uid = int(s[0])
        ultra = int(s[1])
    except ValueError:
        await update.message.reply_text("ID и ultra должны быть числами.")
        return S_SET_ULTRA
    async with lock:
        rec = ensure_user(uid)
        rec["ultra"] = ultra
        save_data()
    await update.message.reply_text(f"✅ Ultra пользователя {uid} установлен: {ultra}")
    return ConversationHandler.END


async def receive_set_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip().split()
    if len(s) != 2:
        await update.message.reply_text("Нужно 2 аргумента: <user_id> <points>")
        return S_SET_POINTS
    try:
        uid = int(s[0])
        pts = int(s[1])
    except ValueError:
        await update.message.reply_text("ID и points должны быть числами.")
        return S_SET_POINTS
    async with lock:
        rec = ensure_user(uid)
        # for backward compatibility we store points as 'points' in user record
        rec["points"] = rec.get("points", 0) + pts
        save_data()
    await update.message.reply_text(f"✅ Пользователю {uid} выдано {pts} points (теперь {rec.get('points')}).")
    return ConversationHandler.END


async def receive_set_disease_chance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = update.message.text.strip()
    try:
        val = int(s)
    except ValueError:
        await update.message.reply_text("Введите целое число 0-100.")
        return S_SET_DISEASE_CHANCE
    if not (0 <= val <= 100):
        await update.message.reply_text("Значение должно быть от 0 до 100.")
        return S_SET_DISEASE_CHANCE
    async with lock:
        DATA["disease_chance"] = val
        save_data()
    await update.message.reply_text(f"✅ Шанс заболевания установлен: {val}%")
    return ConversationHandler.END


# -------------- USER COMMANDS --------------
async def cmd_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_GROUP_ID:
        return
    uid = update.effective_user.id
    async with lock:
        rec = ensure_user(uid)
        last = get_last_degrade(rec)
        now = utc_now()
        elapsed = (now - last).total_seconds()
        if elapsed < DEGRADE_COOLDOWN_SEC:
            remain = int(DEGRADE_COOLDOWN_SEC - elapsed)
            mm = remain // 60
            ss = remain % 60
            await update.message.reply_text(f"⏳ Подожди {mm} мин {ss} сек до следующей деградации.")
            return
        # build combined actions list
        actions = list(DATA.get("degrade_actions", []))
        # include user-defined commands (user_commands)
        for uc in DATA.get("user_commands", []):
            actions.append({"text": uc["text"], "iq_delta": -1})
        if not actions:
            await update.message.reply_text("⚠️ Админ пока не добавил действия для деградации.")
            return
        action = random.choice(actions)
        base = abs(int(action.get("iq_delta", -1)))
        # calc multiplier from diseases
        mult = diseases_multiplier(rec)
        iq_loss = int(base * (1 + mult))
        rec["iq"] = rec.get("iq", 100) - iq_loss
        set_last_degrade(rec, now)
        # chance to catch disease
        chance = DATA.get("disease_chance", DISEASE_CHANCE_DEFAULT)
        disease_msg = ""
        if DATA.get("diseases") and random.randint(1, 100) <= chance:
            dis = random.choice(DATA["diseases"])
            dur = random.randint(int(dis["min_hours"]), int(dis["max_hours"]))
            rec.setdefault("diseases", []).append({
                "name": dis["name"],
                "start_iso": dt_to_iso(now),
                "duration_h": dur,
                "multiplier": dis["multiplier"]
            })
            disease_msg = f"\n{random_emoji()} Подхватил болезнь: {dis['name']} (дл. {dur} ч, +{int(dis['multiplier']*100)}%)."
        save_data()
    await update.message.reply_text(f"{action['text']}\nТвой IQ упал на {iq_loss} {random_emoji()}\nСейчас IQ: {rec['iq']}{disease_msg}")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_GROUP_ID:
        return
    async with lock:
        users_map = DATA.get("users", {})
        if not users_map:
            await update.message.reply_text("Пока нет пользователей.")
            return
        arr = []
        for k, v in users_map.items():
            try:
                uid = int(k)
            except:
                continue
            arr.append((uid, v.get("iq", 100)))
        arr.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 Топ по IQ:\n"
    for i, (uid, iq) in enumerate(arr[:10], 1):
        try:
            chat = await context.bot.get_chat(uid)
            name = chat.username or chat.first_name or str(uid)
        except Exception:
            name = str(uid)
        text += f"{i}. {name} — {iq} {random_emoji()}\n"
    await update.message.reply_text(text)


async def cmd_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with lock:
        rec = ensure_user(uid)
        active = active_diseases(rec)  # also cleans expired
        iq = rec.get("iq", 100)
        ultra = rec.get("ultra", 0)
        last = get_last_degrade(rec)
        now = utc_now()
        cd = max(0, DEGRADE_COOLDOWN_SEC - (now - last).total_seconds())
        mm = int(cd // 60)
        ss = int(cd % 60)
    text = f"Твой IQ: {iq}\nUltra: {ultra}\nДеградация через: {mm} мин {ss} сек\n\nБолезни:\n"
    if not active:
        text += "— нет активных болезней\n"
    else:
        for d in active:
            text += f"{d['name']} — {format_remaining(d['start_iso'], int(d['duration_h']))}\n"
    await update.message.reply_text(text)


async def cmd_d_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /d <text> — add user command; cost 1 ultra
    uid = update.effective_user.id
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Использование: /d <текст команды>")
        return
    async with lock:
        rec = ensure_user(uid)
        if rec.get("ultra", 0) < 1:
            await update.message.reply_text("У тебя недостаточно ultra очков (нужно 1).")
            return
        rec["ultra"] -= 1
        DATA.setdefault("user_commands", []).append({"user_id": uid, "text": text})
        save_data()
    await update.message.reply_text(f"✅ Команда добавлена. Осталось ultra: {rec['ultra']}")


# -------------- Admin commands not via conversation --------------
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # simple list for group or admin
    async with lock:
        acts = DATA.get("degrade_actions", [])
    if not acts:
        await update.message.reply_text("Пока нет действий.")
        return
    txt = "Действия деградации:\n"
    for i, a in enumerate(acts, 1):
        txt += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
    await update.message.reply_text(txt)


# -------------- Conversation fallbacks --------------
async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена.")
    return ConversationHandler.END


# -------------- Startup and registration --------------
def build_application():
    global _app
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    _app = app

    # Conversation handler for admin menu
    conv = ConversationHandler(
        entry_points=[CommandHandler("eair", cmd_eair)],
        states={
            S_MENU: [CallbackQueryHandler(admin_menu_callback)],
            S_ADD_ACTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_action_text)],
            S_ADD_ACTION_IQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_action_iq)],
            S_DEL_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_del_action)],
            S_ADD_DISEASE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_disease_name)],
            S_ADD_DISEASE_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_disease_min)],
            S_ADD_DISEASE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_disease_max)],
            S_ADD_DISEASE_MULT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_disease_mult)],
            S_DEL_DISEASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_del_disease)],
            S_SET_IQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_set_iq)],
            S_SET_ULTRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_set_ultra)],
            S_SET_POINTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_set_points)],
            S_RESET_TIMERS_CONFIRM: [CallbackQueryHandler(admin_menu_callback)],
            S_SET_DISEASE_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_set_disease_chance)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        allow_reentry=True,
    )

    # User commands
    app.add_handler(conv)

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Бот запущен. Используй /degrade в группе.")))
    app.add_handler(CommandHandler("degrade", cmd_degrade))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("d", cmd_d_add))
    app.add_handler(CommandHandler("list", cmd_list))

    return app


# -------------- Main --------------
def main():
    load_data()
    app = build_application()

    # run autosave background task
    loop = asyncio.get_event_loop()
    loop.create_task(autosave_loop())

    log.info("Starting bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
