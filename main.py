# main.py
import os
import json
import random
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
# Рекомендуется хранить BOT_TOKEN в env var BOT_TOKEN (на Railway / GitHub Actions и т.д.)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7909644376:AAEJO4qo53-joyp3N6UCvZG9xPp1gj2m13g")
ALLOWED_GROUP_ID = int(os.environ.get("ALLOWED_GROUP_ID", "-1001941069892"))
ADMIN_IDS = set(int(x) for x in os.environ.get("ADMIN_IDS", "6878462090").split(","))

DATA_FILE = Path("data.json")
AUTOSAVE_INTERVAL = 10  # сек
DEGRADE_COOLDOWN_SEC = 3600  # сек (1 час)
DEFAULT_DISEASE_CHANCE = 20  # %

EMOJIS = ["🎉", "👽", "🤢", "😵", "💀", "🤡", "🧠", "🔥", "❌", "⚡️"]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# -------------- GLOBALS & LOCK --------------
lock = asyncio.Lock()
DATA: Dict[str, Any] = {}
_app = None  # will hold Application instance


# -------------- HELPERS --------------
def utc_now() -> datetime:
    return datetime.utcnow()


def dt_to_iso(dt: datetime) -> str:
    return dt.isoformat()


def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def random_emoji() -> str:
    return random.choice(EMOJIS)


# -------------- PERSISTENCE --------------
DEFAULT_DATA = {
    "users": {},  # str(user_id) -> {iq, ultra, points, last_degrade_iso, diseases: [{name,start_iso,duration_h,multiplier}]}
    "degrade_actions": [],  # [{text, iq_delta}]
    "diseases": [],  # [{name, multiplier, min_hours, max_hours}]
    "user_commands": [],  # [{user_id, text}]
    "disease_chance": DEFAULT_DISEASE_CHANCE,
}


def load_data():
    global DATA
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                DATA = json.load(f)
        except Exception:
            log.exception("Failed to load data.json — using defaults")
            DATA = DEFAULT_DATA.copy()
    else:
        DATA = DEFAULT_DATA.copy()
    # ensure keys
    for k, v in DEFAULT_DATA.items():
        if k not in DATA:
            DATA[k] = v


def save_data():
    try:
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(DATA, f, ensure_ascii=False, indent=2)
        log.info("Saved data.json")
    except Exception:
        log.exception("Failed to save data.json")


async def autosave_loop():
    while True:
        await asyncio.sleep(AUTOSAVE_INTERVAL)
        async with lock:
            save_data()


# -------------- User helpers --------------
def ensure_user_record(user_id: int) -> Dict[str, Any]:
    users = DATA.setdefault("users", {})
    key = str(user_id)
    if key not in users:
        users[key] = {
            "iq": 100,
            "ultra": 0,
            "points": 0,
            "last_degrade_iso": "",
            "diseases": [],  # [{name, start_iso, duration_h, multiplier}]
        }
    return users[key]


def get_last_degrade(rec: Dict[str, Any]) -> datetime:
    s = rec.get("last_degrade_iso", "")
    if not s:
        return datetime.fromtimestamp(0)
    try:
        return iso_to_dt(s)
    except Exception:
        return datetime.fromtimestamp(0)


def set_last_degrade(rec: Dict[str, Any], dt: datetime):
    rec["last_degrade_iso"] = dt_to_iso(dt)


def clean_expired_user_diseases(rec: Dict[str, Any]):
    now = utc_now()
    new = []
    for d in rec.get("diseases", []):
        try:
            start = iso_to_dt(d["start_iso"])
            dur = int(d["duration_h"])
            end = start + timedelta(hours=dur)
            if end > now:
                new.append(d)
        except Exception:
            continue
    rec["diseases"] = new


def compute_disease_multiplier(rec: Dict[str, Any]) -> float:
    clean_expired_user_diseases(rec)
    total = 0.0
    for d in rec.get("diseases", []):
        total += float(d.get("multiplier", 0))
    return total


def format_user_diseases(rec: Dict[str, Any]) -> str:
    clean_expired_user_diseases(rec)
    if not rec.get("diseases"):
        return "— нет активных болезней"
    now = utc_now()
    out = []
    for d in rec["diseases"]:
        try:
            start = iso_to_dt(d["start_iso"])
            dur = int(d["duration_h"])
            end = start + timedelta(hours=dur)
            if end <= now:
                out.append(f"{d['name']} — истекла {end.strftime('%d.%m %H:%M')} UTC")
            else:
                rem = end - now
                h = rem.days * 24 + rem.seconds // 3600
                m = (rem.seconds % 3600) // 60
                out.append(f"{d['name']} — осталось {h}ч {m}м (до {end.strftime('%d.%m %H:%M')} UTC)")
        except Exception:
            out.append(f"{d.get('name','?')} — (ошибка данных)")
    return "\n".join(out)


# -------------- Conversation states --------------
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
    S_SET_CHANCE,
    S_CONFIRM_RESET_TIMERS,
) = range(14)


# -------------- Admin keyboard --------------
def admin_keyboard():
    kb = [
        [InlineKeyboardButton("➕ Добавить действие", callback_data="add_action")],
        [InlineKeyboardButton("🗑 Удалить действие", callback_data="del_action"),
         InlineKeyboardButton("📋 Список действий", callback_data="list_actions")],
        [InlineKeyboardButton("➕ Добавить болезнь", callback_data="add_disease")],
        [InlineKeyboardButton("🗑 Удалить болезнь", callback_data="del_disease"),
         InlineKeyboardButton("📋 Список болезней", callback_data="list_diseases")],
        [InlineKeyboardButton("👥 Пользовательские команды", callback_data="list_usercmds")],
        [InlineKeyboardButton("🧾 Управление (IQ/ultra/points)", callback_data="manage_users")],
        [InlineKeyboardButton("⏱ Сброс таймеров (всем)", callback_data="reset_timers"),
         InlineKeyboardButton("🧴 Сброс болезней (всем)", callback_data="reset_diseases")],
        [InlineKeyboardButton("♻ Сброс IQ всем", callback_data="reset_iq"),
         InlineKeyboardButton("⚙ Установить шанс болезни", callback_data="set_chance")],
        [InlineKeyboardButton("Закрыть", callback_data="close")],
    ]
    return InlineKeyboardMarkup(kb)


# -------------- Admin handlers --------------
async def cmd_eair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await (update.effective_message or update.message).reply_text("🚫 Доступ только для админов.")
        return ConversationHandler.END
    txt = (
        "🛠 *Админ-панель*\n\n"
        "Кнопки ниже управляют ботом. Нажмите нужную кнопку."
    )
    await (update.effective_message or update.message).reply_text(txt, reply_markup=admin_keyboard(), parse_mode="Markdown")
    return S_MENU


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This handler is registered both globally and inside ConversationHandler to be robust.
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        try:
            await query.message.edit_text("🚫 Доступ только для админов.")
        except Exception:
            pass
        return ConversationHandler.END

    data = query.data

    # ADD ACTION
    if data == "add_action":
        await query.message.reply_text("Введите текст действия (пример: Купил айфон в кредит):")
        return S_ADD_ACTION_TEXT

    if data == "del_action":
        arr = DATA.get("degrade_actions", [])
        if not arr:
            await query.message.reply_text("Пока нет действий.")
            return S_MENU
        text = "Список действий (введите номер для удаления):\n"
        for i, a in enumerate(arr, 1):
            text += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
        await query.message.reply_text(text)
        return S_DEL_ACTION

    if data == "list_actions":
        arr = DATA.get("degrade_actions", [])
        if not arr:
            await query.message.reply_text("Пока нет действий.")
            return S_MENU
        text = "Действия деградации:\n"
        for i, a in enumerate(arr, 1):
            text += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
        await query.message.reply_text(text)
        return S_MENU

    # DISEASES
    if data == "add_disease":
        await query.message.reply_text("Введите название болезни:")
        return S_ADD_DISEASE_NAME

    if data == "del_disease":
        arr = DATA.get("diseases", [])
        if not arr:
            await query.message.reply_text("Пока нет болезней.")
            return S_MENU
        text = "Список болезней (введите номер для удаления):\n"
        for i, d in enumerate(arr, 1):
            text += f"{i}. {d['name']} (x{d['multiplier']}, {d['min_hours']}-{d['max_hours']}ч)\n"
        await query.message.reply_text(text)
        return S_DEL_DISEASE

    if data == "list_diseases":
        arr = DATA.get("diseases", [])
        if not arr:
            await query.message.reply_text("Пока нет болезней.")
            return S_MENU
        text = "Болезни:\n"
        for i, d in enumerate(arr, 1):
            text += f"{i}. {d['name']} — множитель {d['multiplier']}, длительность {d['min_hours']}-{d['max_hours']} ч\n"
        await query.message.reply_text(text)
        return S_MENU

    if data == "list_usercmds":
        arr = DATA.get("user_commands", [])
        if not arr:
            await query.message.reply_text("Нет пользовательских команд.")
            return S_MENU
        text = "Пользовательские команды:\n"
        for i, c in enumerate(arr, 1):
            text += f"{i}. (от {c['user_id']}) {c['text']}\n"
        await query.message.reply_text(text)
        return S_MENU

    if data == "manage_users":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Установить IQ", callback_data="set_iq")],
            [InlineKeyboardButton("Установить ultra", callback_data="set_ultra")],
            [InlineKeyboardButton("Выдать points", callback_data="set_points")],
            [InlineKeyboardButton("Назад", callback_data="back")],
        ])
        await query.message.reply_text("Выберите действие:", reply_markup=kb)
        return S_MENU

    if data == "set_iq":
        await query.message.reply_text("Введи: <user_id> <iq>")
        return S_SET_IQ

    if data == "set_ultra":
        await query.message.reply_text("Введи: <user_id> <ultra>")
        return S_SET_ULTRA

    if data == "set_points":
        await query.message.reply_text("Введи: <user_id> <points>")
        return S_SET_POINTS

    if data == "reset_timers":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Подтвердить", callback_data="confirm_reset_timers")],
            [InlineKeyboardButton("Отмена", callback_data="back")],
        ])
        await query.message.reply_text("Подтвердите: сброс таймеров (last_degrade) для всех пользователей.", reply_markup=kb)
        return S_CONFIRM_RESET_TIMERS

    if data == "confirm_reset_timers":
        async with lock:
            for uid, rec in DATA.get("users", {}).items():
                rec["last_degrade_iso"] = ""
            save_data()
        try:
            await query.message.edit_text("✅ Таймеры у всех сброшены.")
        except Exception:
            pass
        return ConversationHandler.END

    if data == "reset_diseases":
        async with lock:
            for uid, rec in DATA.get("users", {}).items():
                rec["diseases"] = []
            save_data()
        await query.message.reply_text("✅ Болезни у всех сброшены.")
        return S_MENU

    if data == "reset_iq":
        async with lock:
            for uid, rec in DATA.get("users", {}).items():
                rec["iq"] = 100
            save_data()
        await query.message.reply_text("✅ IQ всех пользователей сброшен до 100.")
        return S_MENU

    if data == "set_chance":
        await query.message.reply_text(f"Текущий шанс заболевания: {DATA.get('disease_chance', DEFAULT_DISEASE_CHANCE)}%.\nВведите новое значение 0-100:")
        return S_SET_CHANCE

    if data == "close":
        try:
            await query.message.edit_text("Закрыто.")
        except Exception:
            pass
        return ConversationHandler.END

    if data == "back":
        await query.message.reply_text("Возврат в меню.", reply_markup=admin_keyboard())
        return S_MENU

    await query.message.reply_text("Неизвестная опция.")
    return S_MENU


# -------------- Admin Conversation receivers --------------
async def receive_add_action_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message or update.message).text.strip()
    if not text:
        await (update.effective_message or update.message).reply_text("Текст не должен быть пустым. Введите снова:")
        return S_ADD_ACTION_TEXT
    context.user_data["new_action_text"] = text
    await (update.effective_message or update.message).reply_text("Теперь введите IQ delta (например -3 или 2). Отрицательное — уменьшает IQ.")
    return S_ADD_ACTION_IQ


async def receive_add_action_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        iq = int(s)
    except ValueError:
        await (update.effective_message or update.message).reply_text("IQ должен быть целым числом. Попробуйте снова:")
        return S_ADD_ACTION_IQ
    text = context.user_data.pop("new_action_text", None)
    if not text:
        await (update.effective_message or update.message).reply_text("Ошибка — начните заново.")
        return ConversationHandler.END
    async with lock:
        DATA.setdefault("degrade_actions", []).append({"text": text, "iq_delta": iq})
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Добавлено действие: {text} ({iq} IQ)")
    return ConversationHandler.END


async def receive_del_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        idx = int(s) - 1
    except ValueError:
        await (update.effective_message or update.message).reply_text("Нужен номер (целое число).")
        return S_DEL_ACTION
    async with lock:
        arr = DATA.get("degrade_actions", [])
        if not (0 <= idx < len(arr)):
            await (update.effective_message or update.message).reply_text("Неверный номер.")
            return ConversationHandler.END
        removed = arr.pop(idx)
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Удалено: {removed['text']}")
    return ConversationHandler.END


async def receive_add_disease_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.effective_message or update.message).text.strip()
    if not name:
        await (update.effective_message or update.message).reply_text("Название не должно быть пустым.")
        return S_ADD_DISEASE_NAME
    context.user_data["disease_name"] = name
    await (update.effective_message or update.message).reply_text("Введи минимальное время (часы, целое):")
    return S_ADD_DISEASE_MIN


async def receive_add_disease_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        v = int(s)
        if v <= 0:
            raise ValueError()
    except ValueError:
        await (update.effective_message or update.message).reply_text("Нужен положительный целый час.")
        return S_ADD_DISEASE_MIN
    context.user_data["disease_min"] = v
    await (update.effective_message or update.message).reply_text("Введи максимальное время (часы, целое, >= минимального):")
    return S_ADD_DISEASE_MAX


async def receive_add_disease_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        v = int(s)
        if v <= 0:
            raise ValueError()
    except ValueError:
        await (update.effective_message or update.message).reply_text("Нужен положительный целый час.")
        return S_ADD_DISEASE_MAX
    if v < context.user_data.get("disease_min", 0):
        await (update.effective_message or update.message).reply_text("Максимум не может быть меньше минимума.")
        return S_ADD_DISEASE_MAX
    context.user_data["disease_max"] = v
    await (update.effective_message or update.message).reply_text("Введи множитель (float), например 1.3 (1.0 = без эффекта):")
    return S_ADD_DISEASE_MULT


async def receive_add_disease_mult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip().replace(",", ".")
    try:
        mult = float(s)
    except ValueError:
        await (update.effective_message or update.message).reply_text("Неверный формат множителя. Пример: 1.3")
        return S_ADD_DISEASE_MULT
    if mult < 1.0:
        await (update.effective_message or update.message).reply_text("Множитель должен быть >= 1.0")
        return S_ADD_DISEASE_MULT
    name = context.user_data.pop("disease_name", None)
    hmin = context.user_data.pop("disease_min", None)
    hmax = context.user_data.pop("disease_max", None)
    if not name:
        await (update.effective_message or update.message).reply_text("Ошибка данных. Начните заново.")
        return ConversationHandler.END
    async with lock:
        DATA.setdefault("diseases", []).append({
            "name": name,
            "multiplier": mult,
            "min_hours": int(hmin),
            "max_hours": int(hmax),
        })
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Болезнь '{name}' добавлена: {hmin}-{hmax} ч, x{mult}")
    return ConversationHandler.END


async def receive_del_disease(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        idx = int(s) - 1
    except ValueError:
        await (update.effective_message or update.message).reply_text("Нужен номер (целое число).")
        return S_DEL_DISEASE
    async with lock:
        arr = DATA.get("diseases", [])
        if not (0 <= idx < len(arr)):
            await (update.effective_message or update.message).reply_text("Неверный номер.")
            return ConversationHandler.END
        removed = arr.pop(idx)
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Удалена болезнь: {removed['name']}")
    return ConversationHandler.END


async def receive_set_iq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip().split()
    if len(s) != 2:
        await (update.effective_message or update.message).reply_text("Формат: <user_id> <iq>")
        return S_SET_IQ
    try:
        uid = int(s[0]); iq = int(s[1])
    except ValueError:
        await (update.effective_message or update.message).reply_text("ID и IQ должны быть целыми числами.")
        return S_SET_IQ
    async with lock:
        rec = ensure_user_record(uid)
        rec["iq"] = iq
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ IQ пользователя {uid} установлен в {iq}")
    return ConversationHandler.END


async def receive_set_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip().split()
    if len(s) != 2:
        await (update.effective_message or update.message).reply_text("Формат: <user_id> <ultra>")
        return S_SET_ULTRA
    try:
        uid = int(s[0]); ultra = int(s[1])
    except ValueError:
        await (update.effective_message or update.message).reply_text("ID и ultra должны быть целыми.")
        return S_SET_ULTRA
    async with lock:
        rec = ensure_user_record(uid)
        rec["ultra"] = ultra
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Ultra пользователя {uid} установлен в {ultra}")
    return ConversationHandler.END


async def receive_set_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip().split()
    if len(s) != 2:
        await (update.effective_message or update.message).reply_text("Формат: <user_id> <points>")
        return S_SET_POINTS
    try:
        uid = int(s[0]); pts = int(s[1])
    except ValueError:
        await (update.effective_message or update.message).reply_text("ID и points должны быть целыми.")
        return S_SET_POINTS
    async with lock:
        rec = ensure_user_record(uid)
        rec["points"] = rec.get("points", 0) + pts
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Пользователю {uid} выданы {pts} points (теперь {rec.get('points')}).")
    return ConversationHandler.END


async def receive_set_chance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.effective_message or update.message).text.strip()
    try:
        v = int(s)
    except ValueError:
        await (update.effective_message or update.message).reply_text("Введите целое 0-100.")
        return S_SET_CHANCE
    if not (0 <= v <= 100):
        await (update.effective_message or update.message).reply_text("Значение должно быть 0-100.")
        return S_SET_CHANCE
    async with lock:
        DATA["disease_chance"] = v
        save_data()
    await (update.effective_message or update.message).reply_text(f"✅ Шанс заболевания установлен: {v}%")
    return ConversationHandler.END


# -------------- User commands --------------
async def cmd_degrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat is None or chat.id != ALLOWED_GROUP_ID:
        return
    uid = update.effective_user.id
    async with lock:
        rec = ensure_user_record(uid)
        last = get_last_degrade(rec)
        now = utc_now()
        elapsed = (now - last).total_seconds()
        if elapsed < DEGRADE_COOLDOWN_SEC:
            rem = int(DEGRADE_COOLDOWN_SEC - elapsed)
            mm = rem // 60; ss = rem % 60
            await update.message.reply_text(f"⏳ Подожди {mm} мин {ss} сек до следующей деградации.")
            return
        actions = list(DATA.get("degrade_actions", []))
        for uc in DATA.get("user_commands", []):
            actions.append({"text": uc["text"], "iq_delta": -1})
        if not actions:
            await update.message.reply_text("⚠️ Админ пока не добавил действий деградации.")
            return
        action = random.choice(actions)
        base = abs(int(action.get("iq_delta", -1)))
        mult = compute_disease_multiplier(rec)
        iq_loss = int(base * (1 + mult))
        rec["iq"] = rec.get("iq", 100) - iq_loss
        set_last_degrade(rec, now)
        disease_msg = ""
        chance = DATA.get("disease_chance", DEFAULT_DISEASE_CHANCE)
        if DATA.get("diseases") and random.randint(1, 100) <= chance:
            d = random.choice(DATA["diseases"])
            dur = random.randint(int(d["min_hours"]), int(d["max_hours"]))
            rec.setdefault("diseases", []).append({
                "name": d["name"],
                "start_iso": dt_to_iso(now),
                "duration_h": dur,
                "multiplier": d["multiplier"]
            })
            disease_msg = f"\n{random_emoji()} Подхватил болезнь: {d['name']} (дл. {dur} ч, +{int(d['multiplier']*100)}%)."
        save_data()
    await update.message.reply_text(f"{action['text']}\nТвой IQ упал на {iq_loss} {random_emoji()}\nСейчас IQ: {rec['iq']}{disease_msg}")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat is None or chat.id != ALLOWED_GROUP_ID:
        return
    async with lock:
        users_map = DATA.get("users", {})
        arr = []
        for k, v in users_map.items():
            try:
                uid = int(k)
            except Exception:
                continue
            arr.append((uid, v.get("iq", 100)))
        arr.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 Топ по IQ:\n"
    for i, (uid, iq) in enumerate(arr[:10], 1):
        try:
            chat_user = await _app.bot.get_chat(uid)
            name = chat_user.username or chat_user.first_name or str(uid)
        except Exception:
            name = str(uid)
        text += f"{i}. {name} — {iq} {random_emoji()}\n"
    await update.message.reply_text(text)


async def cmd_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with lock:
        rec = ensure_user_record(uid)
        clean_expired_user_diseases(rec)
        iq = rec.get("iq", 100)
        ultra = rec.get("ultra", 0)
        last = get_last_degrade(rec)
        now = utc_now()
        cd = max(0, DEGRADE_COOLDOWN_SEC - (now - last).total_seconds())
        mm = int(cd // 60); ss = int(cd % 60)
    text = f"Твой IQ: {iq}\nUltra: {ultra}\nДеградация через: {mm} мин {ss} сек\n\nБолезни:\n{format_user_diseases(rec)}"
    await update.message.reply_text(text)


async def cmd_d_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Использование: /d <текст команды>")
        return
    async with lock:
        rec = ensure_user_record(uid)
        if rec.get("ultra", 0) < 1:
            await update.message.reply_text("У тебя нет ultra очков (нужно 1).")
            return
        rec["ultra"] -= 1
        DATA.setdefault("user_commands", []).append({"user_id": uid, "text": text})
        save_data()
    await update.message.reply_text(f"✅ Команда добавлена. Осталось ultra: {rec['ultra']}")


# -------------- misc --------------
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with lock:
        actions = DATA.get("degrade_actions", [])
    if not actions:
        await update.message.reply_text("Пока нет действий.")
        return
    txt = "Действия деградации:\n"
    for i, a in enumerate(actions, 1):
        txt += f"{i}. {a['text']} ({a['iq_delta']} IQ)\n"
    await update.message.reply_text(txt)


# -------------- Error handler --------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Exception while handling an update:", exc_info=context.error)
    # optionally notify admin(s)
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin, text=f"Ошибка в боте: {context.error}")
        except Exception:
            pass


# -------------- Build app --------------
def build_app():
    global _app
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    _app = app

    # Global callback query handler (catches button presses even if Conversation state lost)
    app.add_handler(CallbackQueryHandler(admin_callback))

    # Conversation handler for admin flows
    conv = ConversationHandler(
        entry_points=[CommandHandler("eair", cmd_eair)],
        states={
            S_MENU: [CallbackQueryHandler(admin_callback)],
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
            S_SET_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_set_chance)],
            S_CONFIRM_RESET_TIMERS: [CallbackQueryHandler(admin_callback)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Отмена."))],
        allow_reentry=True,
    )

    app.add_handler(conv)

    # user commands
    app.add_handler(CommandHandler("start", lambda u, c: c.bot.send_message(chat_id=u.effective_chat.id, text="Привет! Пиши /my или используй /degrade в группе.")))
    app.add_handler(CommandHandler("degrade", cmd_degrade))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("my", cmd_my))
    app.add_handler(CommandHandler("d", cmd_d_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_error_handler(error_handler)

    return app


# -------------- Main --------------
def main():
    load_data()
    app = build_app()
    loop = asyncio.get_event_loop()
    loop.create_task(autosave_loop())
    log.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
