#!/usr/bin/env python3
"""
AI CODE ARMY v3.0 — Финальная рабочая версия
8 ИИ-агентов | Память | Проекты | Поиск | Крипта
"""

import os
import logging
import time
import requests
import zipfile
import io
import re
import random
from datetime import datetime, date
from typing import Dict, List, Tuple
import telebot
from telebot import types
import google.generativeai as genai

# ═══════════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CARD_NUMBER = os.environ.get("CARD_NUMBER", "0000 0000 0000 0000")

ADMINS = {"MAON1K"}
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

FREE_LIMIT = 25
VERSION = "3.0"

# ═══════════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════════

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# ═══════════════════════════════════════════════════════════════════
# ХРАНИЛИЩА
# ═══════════════════════════════════════════════════════════════════

users: Dict[int, dict] = {}
usage: Dict[int, dict] = {}
memory: Dict[int, List[dict]] = {}
projects: Dict[int, dict] = {}
files: Dict[int, dict] = {}

stats = {"total": 0, "ok": 0, "err": 0, "users": 0, "projects": 0}

# ═══════════════════════════════════════════════════════════════════
# GEMINI API — АКТУАЛЬНЫЕ МОДЕЛИ МАРТ 2026
# ═══════════════════════════════════════════════════════════════════

# Из логов: Available models: ['models/gemini-2.5-flash', 'models/gemini-2.5-pro', 'models/gemini-2.0-flash']
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro", 
    "models/gemini-2.0-flash",
]

def ai(prompt: str, system: str = "") -> str:
    """Вызов Gemini AI"""
    text = f"{system}\n\n{prompt}" if system else prompt
    
    for name in MODELS:
        try:
            log.info(f"→ {name}")
            m = genai.GenerativeModel(model_name=name)
            r = m.generate_content(text, generation_config=genai.GenerationConfig(
                temperature=0.8, max_output_tokens=8000
            ))
            log.info(f"✓ {name}")
            return r.text
        except Exception as e:
            log.warning(f"✗ {name}: {str(e)[:50]}")
            continue
    
    raise Exception("AI временно недоступен. Попробуй через минуту!")

# ═══════════════════════════════════════════════════════════════════
# 8 АГЕНТОВ
# ═══════════════════════════════════════════════════════════════════

AGENTS = {
    "arch": ("🧠", "Архитектор", "Проектируй архитектуру. Выбирай технологии. Структура файлов."),
    "back": ("💻", "Backend", "Пиши серверный код. Python/Node.js. API, БД. Полный код."),
    "front": ("🎨", "Frontend", "Создавай UI. HTML/CSS/JS. Красиво и адаптивно. Полный код."),
    "bot": ("🤖", "BotDev", "Создавай Telegram ботов. Кнопки, команды. Готовый код."),
    "review": ("🔍", "Reviewer", "Анализируй код. Ищи проблемы. Оценка 1-10."),
    "sec": ("🔒", "Security", "Проверяй безопасность. SQL injection, XSS. Исправляй."),
    "ops": ("🚀", "DevOps", "Готовь деплой. Railway/Vercel. Конфиги и инструкции."),
    "pm": ("📊", "PM", "Собирай отчёт. Что готово, что дальше.")
}

def agent(name: str, task: str, ctx: str = "") -> str:
    emoji, title, role = AGENTS[name]
    system = f"Ты {title}. {role}"
    if ctx:
        system += f"\n\nКонтекст:\n{ctx[:2000]}"
    return ai(task, system)

def build_project(desc: str, update) -> dict:
    """Создание проекта командой агентов"""
    r = {}
    has_bot = "бот" in desc.lower() or "telegram" in desc.lower()
    total = 7 if has_bot else 6
    
    def step(n, txt):
        bar = "█" * n + "░" * (total - n)
        update(f"[{bar}] {n}/{total}\n{txt}")
    
    step(1, "🧠 Архитектор проектирует...")
    r["arch"] = agent("arch", desc)
    time.sleep(1)
    
    step(2, "💻 Backend пишет код...")
    r["back"] = agent("back", "Напиши backend", r["arch"])
    time.sleep(1)
    
    step(3, "🎨 Frontend создаёт UI...")
    r["front"] = agent("front", "Напиши frontend", r["arch"])
    time.sleep(1)
    
    if has_bot:
        step(4, "🤖 BotDev делает бота...")
        r["bot"] = agent("bot", "Напиши Telegram бота", r["arch"])
        time.sleep(1)
    
    n = 5 if has_bot else 4
    step(n, "🔒 Security проверяет...")
    code = f"{r['back']}\n{r['front']}"
    r["sec"] = agent("sec", "Проверь безопасность", code)
    time.sleep(1)
    
    step(n+1, "🚀 DevOps готовит деплой...")
    r["ops"] = agent("ops", "Подготовь деплой", code)
    time.sleep(1)
    
    step(total, "📊 PM собирает отчёт...")
    summary = "\n".join([f"{k}: готово" for k in r.keys()])
    r["pm"] = agent("pm", "Итоговый отчёт", summary)
    
    return r

# ═══════════════════════════════════════════════════════════════════
# AI С ПАМЯТЬЮ
# ═══════════════════════════════════════════════════════════════════

def chat(uid: int, msg: str) -> str:
    """Чат с памятью"""
    if uid not in memory:
        memory[uid] = []
    
    memory[uid].append({"role": "user", "text": msg})
    if len(memory[uid]) > 20:
        memory[uid] = memory[uid][-20:]
    
    hist = "\n".join([f"{'→' if m['role']=='user' else '←'} {m['text']}" for m in memory[uid][-6:]])
    
    system = f"""Ты AI Code Assistant v{VERSION}.

Умеешь: код, баги, объяснения, улучшения.
Помнишь разговор. Отвечай кратко и полезно.

История:
{hist}"""
    
    result = ai(msg, system)
    memory[uid].append({"role": "ai", "text": result})
    return result

# ═══════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════

def crypto(sym: str = "BTC") -> str:
    try:
        r = requests.get(f"https://api.coinbase.com/v2/prices/{sym}-USD/spot", timeout=5)
        p = float(r.json()["data"]["amount"])
        return f"💰 {sym}: ${p:,.2f}"
    except:
        return f"❌ Ошибка {sym}"

def search(q: str) -> str:
    try:
        r = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json", timeout=8)
        d = r.json()
        if d.get("Abstract"):
            return f"🔍 {d['Abstract'][:500]}"
        return "🔍 Ничего не найдено"
    except:
        return "❌ Ошибка поиска"

def make_zip(data: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for k, v in data.items():
            for i, (_, code) in enumerate(re.findall(r'```(\w+)?\n(.*?)```', v, re.DOTALL)):
                z.writestr(f"{k}_{i}.txt", code.strip())
        z.writestr("README.md", "# Project\nAI CODE ARMY")
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛИ
# ═══════════════════════════════════════════════════════════════════

def user(uid: int, name: str = "") -> dict:
    if uid not in users:
        users[uid] = {"name": name, "n": 0, "proj": 0, "ref": 0}
        stats["users"] += 1
    return users[uid]

def is_admin(name: str) -> bool:
    return name in ADMINS if name else False

def is_vip(uid: int, name: str) -> bool:
    return is_admin(name) or uid in PREMIUM_USERS

def today_use(uid: int) -> int:
    d = date.today()
    return usage.get(uid, {}).get(d, 0)

def add_use(uid: int):
    d = date.today()
    if uid not in usage:
        usage[uid] = {}
    usage[uid][d] = usage[uid].get(d, 0) + 1
    user(uid)["n"] += 1
    stats["total"] += 1

def can(uid: int, name: str) -> Tuple[bool, str]:
    if is_vip(uid, name):
        return True, ""
    if today_use(uid) >= FREE_LIMIT:
        return False, f"⚠️ Лимит {FREE_LIMIT}/день исчерпан\n\n⭐ /premium — безлимит"
    return True, ""

# ═══════════════════════════════════════════════════════════════════
# МЕНЮ
# ═══════════════════════════════════════════════════════════════════

def menu(adm=False):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    b = [
        types.KeyboardButton("🚀 Проект"),
        types.KeyboardButton("💬 Чат"),
        types.KeyboardButton("📊 Стата"),
        types.KeyboardButton("🧹 Сброс"),
        types.KeyboardButton("💰 Курсы"),
        types.KeyboardButton("⭐ VIP"),
    ]
    if adm:
        b.append(types.KeyboardButton("👑 Админ"))
    k.add(*b)
    return k

# ═══════════════════════════════════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    user(uid, name)
    adm = is_admin(name)
    
    txt = f"""🤖 *AI CODE ARMY v{VERSION}*

Привет, *{m.from_user.first_name}*!

*Что умею:*
🚀 Создавать проекты (8 агентов)
💬 Писать и улучшать код
🔍 Находить баги
📖 Объяснять
💾 Помнить разговор

*Тариф:* {'👑 VIP' if adm else f'🆓 {FREE_LIMIT}/день'}

_Выбери действие ниже_ 👇"""
    
    bot.send_message(m.chat.id, txt, reply_markup=menu(adm), parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(m):
    bot.send_message(m.chat.id, """📖 *Справка*

🚀 *Проект* — 8 агентов создают за 3-5 мин
💬 *Чат* — помощь с кодом (помню контекст!)
💰 *Курсы* — BTC, ETH
🧹 *Сброс* — очистить память

*Примеры:*
• "Напиши бота для заказов"
• "Найди баг: [код]"
• "Объясни: [код]"
• "Улучши этот код"
""", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    u = user(uid)
    
    st = "👑 VIP" if is_vip(uid, name) else "🆓 Free"
    lim = "∞" if is_vip(uid, name) else str(FREE_LIMIT)
    mem = len(memory.get(uid, []))
    
    bot.send_message(m.chat.id, f"""📊 *Твоя статистика*

Статус: {st}
Сегодня: {today_use(uid)}/{lim}
Всего: {u['n']}
Проектов: {u['proj']}
Память: {mem} сообщений
""", parse_mode="Markdown")

@bot.message_handler(commands=['clear'])
def cmd_clear(m):
    if m.from_user.id in memory:
        memory[m.from_user.id] = []
    bot.reply_to(m, "🧹 Память очищена!")

@bot.message_handler(commands=['premium'])
def cmd_premium(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    
    if is_admin(name):
        return bot.send_message(m.chat.id, "👑 Ты VIP!")
    
    bot.send_message(m.chat.id, f"""⭐ *Premium — 499₽/мес*

✅ Безлимит запросов
✅ Приоритет
✅ Расширенная память

*Оплата:*
`{CARD_NUMBER}`
Комментарий: `VIP {uid}`

Скинь скрин — активация за 10 мин!
""", parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def cmd_admin(m):
    if not is_admin(m.from_user.username):
        return
    
    bot.send_message(m.chat.id, f"""👑 *Админка*

👥 Юзеров: {stats['users']}
📨 Запросов: {stats['total']}
✅ Успешно: {stats['ok']}
❌ Ошибок: {stats['err']}
🚀 Проектов: {stats['projects']}
""", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════════
# КНОПКИ МЕНЮ
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text == "🚀 Проект")
def btn_project(m):
    msg = bot.send_message(m.chat.id, """🚀 *Создание проекта*

Опиши что нужно сделать:

• Сайт-визитка
• Telegram бот
• REST API
• Landing page

_Команда из 8 агентов создаст за 3-5 минут!_
""", parse_mode="Markdown")
    bot.register_next_step_handler(msg, do_project)

def do_project(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    desc = m.text.strip()
    
    if len(desc) < 10:
        return bot.reply_to(m, "❌ Опиши подробнее (мин. 10 символов)")
    
    ok, err = can(uid, name)
    if not ok:
        return bot.reply_to(m, err, parse_mode="Markdown")
    
    log.info(f"🚀 PROJECT @{name}: {desc[:40]}")
    
    status = bot.send_message(m.chat.id, "🚀 Запускаю команду...")
    
    def upd(txt):
        try:
            bot.edit_message_text(f"🚀 *Работаю...*\n\n{txt}", 
                m.chat.id, status.message_id, parse_mode="Markdown")
        except:
            pass
    
    try:
        result = build_project(desc, upd)
        
        add_use(uid)
        user(uid)["proj"] += 1
        stats["ok"] += 1
        stats["projects"] += 1
        
        projects[uid] = result
        
        try:
            bot.delete_message(m.chat.id, status.message_id)
        except:
            pass
        
        bot.send_message(m.chat.id, "✅ *Готово!*", parse_mode="Markdown")
        
        if "pm" in result:
            send(m.chat.id, result["pm"])
        
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("🧠", callback_data="p_arch"),
            types.InlineKeyboardButton("💻", callback_data="p_back"),
            types.InlineKeyboardButton("🎨", callback_data="p_front"),
            types.InlineKeyboardButton("🔒", callback_data="p_sec"),
            types.InlineKeyboardButton("🚀", callback_data="p_ops"),
            types.InlineKeyboardButton("📦 ZIP", callback_data="p_zip"),
        )
        if "bot" in result:
            kb.add(types.InlineKeyboardButton("🤖 Bot", callback_data="p_bot"))
        
        bot.send_message(m.chat.id, "📂 Детали:", reply_markup=kb)
        
    except Exception as e:
        stats["err"] += 1
        log.error(f"Project error: {e}")
        try:
            bot.delete_message(m.chat.id, status.message_id)
        except:
            pass
        bot.send_message(m.chat.id, f"❌ {str(e)[:150]}\n\nПопробуй ещё раз!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("p_"))
def cb_project(c):
    uid = c.from_user.id
    if uid not in projects:
        return bot.answer_callback_query(c.id, "❌ Проект не найден")
    
    key = c.data[2:]
    
    if key == "zip":
        bot.answer_callback_query(c.id, "📦 Создаю...")
        try:
            data = make_zip(projects[uid])
            bot.send_document(c.message.chat.id, data, 
                visible_file_name=f"project_{uid}.zip")
        except Exception as e:
            bot.send_message(c.message.chat.id, f"❌ {e}")
        return
    
    if key in projects[uid]:
        bot.answer_callback_query(c.id)
        send(c.message.chat.id, projects[uid][key])
    else:
        bot.answer_callback_query(c.id, "❌ Нет данных")

@bot.message_handler(func=lambda m: m.text == "💬 Чат")
def btn_chat(m):
    bot.send_message(m.chat.id, "💬 Напиши свой вопрос!\n\n_Я помню наш разговор_", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📊 Стата")
def btn_stats(m):
    cmd_stats(m)

@bot.message_handler(func=lambda m: m.text == "🧹 Сброс")
def btn_clear(m):
    cmd_clear(m)

@bot.message_handler(func=lambda m: m.text == "💰 Курсы")
def btn_crypto(m):
    btc = crypto("BTC")
    eth = crypto("ETH")
    bot.send_message(m.chat.id, f"💰 *Курсы криптовалют*\n\n{btc}\n{eth}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "⭐ VIP")
def btn_vip(m):
    cmd_premium(m)

@bot.message_handler(func=lambda m: m.text == "👑 Админ")
def btn_admin(m):
    cmd_admin(m)

# ═══════════════════════════════════════════════════════════════════
# ФАЙЛЫ
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(content_types=['document'])
def on_file(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    
    ok, err = can(uid, name)
    if not ok:
        return bot.reply_to(m, err)
    
    try:
        f = bot.get_file(m.document.file_id)
        data = bot.download_file(f.file_path)
        text = data.decode('utf-8', errors='ignore')
        
        files[uid] = {"name": m.document.file_name, "code": text}
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔍 Проверить", callback_data="f_review"),
            types.InlineKeyboardButton("🐛 Баги", callback_data="f_bugs"),
            types.InlineKeyboardButton("📖 Объяснить", callback_data="f_explain"),
            types.InlineKeyboardButton("✨ Улучшить", callback_data="f_improve"),
        )
        
        bot.reply_to(m, f"📁 *{m.document.file_name}*\n\nЧто сделать?", 
            reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, f"❌ {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("f_"))
def cb_file(c):
    uid = c.from_user.id
    if uid not in files:
        return bot.answer_callback_query(c.id, "❌ Файл не найден")
    
    act = c.data[2:]
    code = files[uid]["code"]
    
    prompts = {
        "review": f"Сделай code review:\n```\n{code[:3000]}\n```",
        "bugs": f"Найди все баги:\n```\n{code[:3000]}\n```",
        "explain": f"Объясни код:\n```\n{code[:3000]}\n```",
        "improve": f"Улучши код:\n```\n{code[:3000]}\n```"
    }
    
    bot.answer_callback_query(c.id, "⏳ Работаю...")
    
    try:
        result = chat(uid, prompts[act])
        add_use(uid)
        stats["ok"] += 1
        send(c.message.chat.id, result)
    except Exception as e:
        stats["err"] += 1
        bot.send_message(c.message.chat.id, f"❌ {str(e)[:150]}")

# ═══════════════════════════════════════════════════════════════════
# ТЕКСТ
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: True, content_types=['text'])
def on_text(m):
    uid = m.from_user.id
    name = m.from_user.username or ""
    text = m.text.strip()
    
    if len(text) < 2:
        return
    
    ok, err = can(uid, name)
    if not ok:
        return bot.reply_to(m, err, parse_mode="Markdown")
    
    user(uid, name)
    low = text.lower()
    
    # Крипта
    if any(w in low for w in ['курс', 'btc', 'eth', 'биткоин']):
        sym = "ETH" if "eth" in low else "BTC"
        return bot.reply_to(m, crypto(sym))
    
    # Поиск
    if any(w in low for w in ['найди', 'поищи', 'search']):
        q = re.sub(r'найди|поищи|search|в интернете', '', low).strip()
        return bot.reply_to(m, search(q))
    
    log.info(f"💬 @{name}: {text[:30]}")
    bot.send_chat_action(m.chat.id, 'typing')
    
    # Если есть файл
    if uid in files and any(w in low for w in ['файл', 'этот', 'код', 'проверь']):
        text += f"\n\nФайл:\n```\n{files[uid]['code'][:2000]}\n```"
    
    try:
        result = chat(uid, text)
        add_use(uid)
        stats["ok"] += 1
        send(m.chat.id, result)
        
        if not is_vip(uid, name):
            left = FREE_LIMIT - today_use(uid)
            if 0 < left <= 5:
                bot.send_message(m.chat.id, f"ℹ️ Осталось: {left}")
    
    except Exception as e:
        stats["err"] += 1
        log.error(f"Error: {e}")
        bot.send_message(m.chat.id, f"❌ {str(e)[:150]}\n\nПопробуй ещё раз!")

def send(cid, txt: str):
    """Отправка с разбивкой"""
    if len(txt) <= 4000:
        try:
            bot.send_message(cid, txt, parse_mode="Markdown")
        except:
            bot.send_message(cid, txt)
        return
    
    for i in range(0, len(txt), 4000):
        part = txt[i:i+4000]
        try:
            bot.send_message(cid, part, parse_mode="Markdown")
        except:
            bot.send_message(cid, part)
        time.sleep(0.3)

# ═══════════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info(f"🚀 AI CODE ARMY v{VERSION}")
    log.info(f"👑 Admins: {ADMINS}")
    log.info(f"🤖 Models: {MODELS}")
    
    # Агрессивная очистка webhook
    for _ in range(3):
        try:
            bot.remove_webhook()
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset=-1", timeout=5)
        except:
            pass
        time.sleep(1)
    
    log.info("✅ Webhook cleared")
    time.sleep(3)
    
    # Запуск
    while True:
        try:
            log.info("📡 Polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            log.error(f"❌ {e}")
            time.sleep(10)
