import json
import random
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio

# === НАСТРОЙКИ ===
TOKEN = "7909644376:AAHD8zFEV-hjsVSfZ4AdtceBi5u9-ywRHOQ"  # твой токен
GROUP_ID = -1001941069892
ADMIN_ID = 6878462090  # твой Telegram ID
EMOJIS = ["😂", "💩", "🤡", "🔥", "😎", "🐒", "👽", "💀", "🥴", "🍌", "🤯", "🎉", "🧠", "🍺"]

# === ФАЙЛЫ ===
USERS_FILE = "users.json"
MESSAGES_FILE = "messages.json"

# === ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ ===
def load_data(file, default):
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_data(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_data(USERS_FILE, {})
messages_list = load_data(MESSAGES_FILE, [
    {"text": "ты купил айфон в кредит", "delta": 3},
    {"text": "ты спорил с ботом в интернете", "delta": 2}
])

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === /degrade ===
@dp.message(Command("degrade"))
async def degrade(msg: Message):
    if msg.chat.id != GROUP_ID:
        return
    
    user_id = str(msg.from_user.id)
    now = time.time()

    if user_id not in users:
        users[user_id] = {"iq": 100, "last_time": 0}

    elapsed = now - users[user_id]["last_time"]
    wait_time = 3600  # 1 час в секундах

    if elapsed < wait_time:
        remain = wait_time - elapsed
        mins = int(remain // 60)
        secs = int(remain % 60)
        await msg.reply(f"⏳ Деградировать можно раз в час.\nПодожди ещё {mins} мин {secs} сек.")
        return

    action = random.choice(messages_list)
    emoji = random.choice(EMOJIS)
    users[user_id]["iq"] -= action["delta"]
    users[user_id]["last_time"] = now
    save_data(USERS_FILE, users)

    await msg.reply(
        f"{action['text']}, твой IQ упал на {action['delta']} {emoji}\n"
        f"сейчас твой IQ {users[user_id]['iq']} {random.choice(EMOJIS)}"
    )

# === /top ===
@dp.message(Command("top"))
async def top(msg: Message):
    if msg.chat.id != GROUP_ID:
        return
    
    sorted_users = sorted(users.items(), key=lambda x: x[1]["iq"])
    text = "🏆 Топ деградантов:\n"
    for i, (uid, data) in enumerate(sorted_users[:10], start=1):
        try:
            user = await bot.get_chat_member(GROUP_ID, int(uid))
            name = user.user.full_name
        except:
            name = f"User {uid}"
        text += f"{i}. {name} — {data['iq']} 🧠\n"

    await msg.reply(text)

# === /eair (админка) ===
@dp.message(Command("eair"))
async def eair(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    
    if msg.chat.type != "private":
        await msg.reply("Пиши в личку.")
        return

    await msg.reply("Админка:\n/add <текст> <число> — добавить событие\n/del <номер> — удалить событие")

@dp.message(Command("add"))
async def add_message(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        parts = msg.text.split()
        delta = int(parts[-1])
        text = " ".join(parts[1:-1])
        messages_list.append({"text": text, "delta": delta})
        save_data(MESSAGES_FILE, messages_list)
        await msg.reply("✅ Сообщение добавлено.")
    except:
        await msg.reply("❌ Формат: /add текст число")

@dp.message(Command("del"))
async def del_message(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        idx = int(msg.text.split()[1]) - 1
        messages_list.pop(idx)
        save_data(MESSAGES_FILE, messages_list)
        await msg.reply("✅ Удалено.")
    except:
        await msg.reply("❌ Ошибка.")

# === ЗАПУСК ===
async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
