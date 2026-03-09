#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import io
import json
import time
import zipfile
import logging
import traceback
from datetime import date, datetime
from typing import Dict, List, Tuple, Optional

import requests
import telebot
from telebot import types
import google.generativeai as genai

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

ADMINS = set(x.strip() for x in os.environ.get("ADMINS", "").split(",") if x.strip())
PREMIUM_USERS = set(x.strip() for x in os.environ.get("PREMIUM_USERS", "").split(",") if x.strip())

FREE_LIMIT = int(os.environ.get("FREE_LIMIT", "25"))
PREMIUM_LIMIT = int(os.environ.get("PREMIUM_LIMIT", "500"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "0000 0000 0000 0000")

VERSION = "7.0"

MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
]

MAX_MESSAGE_LEN = 3900
MAX_MEMORY_TURNS = 16
MAX_CONTEXT_TURNS = 8
MAX_FILE_SIZE = 50000
AI_RETRIES = 3

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

# =========================================================
# INIT
# =========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True, num_threads=4)
genai.configure(api_key=GEMINI_API_KEY)

http = requests.Session()
http.headers.update({"User-Agent": f"AI-Bot/{VERSION}"})

# =========================================================
# STORAGE
# =========================================================

users: Dict[int, dict] = {}
usage: Dict[int, Dict[date, int]] = {}
memory: Dict[int, dict] = {}
projects: Dict[int, dict] = {}
files: Dict[int, dict] = {}
user_modes: Dict[int, str] = {}

stats = {"total": 0, "ok": 0, "err": 0, "users": 0, "projects": 0}

MODES = {
    "auto": "🤖 Авто",
    "code": "💻 Код",
    "debug": "🐛 Дебаг",
    "explain": "📖 Объяснение",
    "refactor": "✨ Рефакторинг",
}

# =========================================================
# HELPERS
# =========================================================

def get_role(uid: int, username: str) -> str:
    if username in ADMINS:
        return "admin"
    if username in PREMIUM_USERS:
        return "premium"
    return "user"

def is_admin(username: str) -> bool:
    return username in ADMINS

def get_user(uid: int, username: Optional[str] = None) -> dict:
    if uid not in users:
        users[uid] = {"name": username or "", "n": 0, "proj": 0}
        stats["users"] += 1
    return users[uid]

def get_limit(uid: int, username: str) -> int:
    role = get_role(uid, username)
    if role == "admin":
        return 999999
    if role == "premium":
        return PREMIUM_LIMIT
    return FREE_LIMIT

def can_use(uid: int, username: str) -> Tuple[bool, str]:
    if get_role(uid, username) == "admin":
        return True, ""
    today = date.today()
    used = usage.get(uid, {}).get(today, 0)
    limit = get_limit(uid, username)
    if used >= limit:
        return False, f"⚠️ Лимит {limit}/день исчерпан.\n⭐ /premium"
    return True, ""

def add_use(uid: int):
    today = date.today()
    usage.setdefault(uid, {})
    usage[uid][today] = usage[uid].get(today, 0) + 1
    get_user(uid)["n"] += 1
    stats["total"] += 1

def send_long(chat_id: int, text: str, parse_mode: Optional[str] = "Markdown", reply_markup=None):
    text = (text or "").strip() or "Пустой ответ."
    parts = []
    while len(text) > MAX_MESSAGE_LEN:
        cut = text.rfind("\n", 0, MAX_MESSAGE_LEN)
        if cut == -1:
            cut = MAX_MESSAGE_LEN
        parts.append(text[:cut])
        text = text[cut:].strip()
    if text:
        parts.append(text)
    for i, part in enumerate(parts):
        rm = reply_markup if i == len(parts) - 1 else None
        try:
            bot.send_message(chat_id, part, parse_mode=parse_mode, reply_markup=rm)
        except Exception:
            bot.send_message(chat_id, part, reply_markup=rm)
        time.sleep(0.15)

def safe_edit(chat_id: int, message_id: int, text: str):
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception:
        pass

def typing_action(chat_id: int):
    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass
        # =========================================================
# AI CORE
# =========================================================

def ai_call(prompt: str, system: str = "", temperature: float = 0.6, max_tokens: int = 8192) -> str:
    full = f"{system}\n\n{prompt}".strip() if system else prompt.strip()
    for model in MODELS:
        for attempt in range(1, AI_RETRIES + 1):
            try:
                m = genai.GenerativeModel(model_name=model)
                r = m.generate_content(full, generation_config=genai.GenerationConfig(
                    temperature=temperature, max_output_tokens=max_tokens))
                txt = getattr(r, "text", None)
                if txt and txt.strip():
                    return txt.strip()
                raise Exception("Empty")
            except Exception as e:
                log.warning(f"AI err [{model}] {attempt}: {e}")
                time.sleep(1 * attempt)
    raise Exception("AI недоступен")

def get_context(uid: int) -> str:
    mem = memory.get(uid, {})
    turns = mem.get("turns", [])[-MAX_CONTEXT_TURNS:]
    lines = []
    for t in turns:
        role = "User" if t["role"] == "user" else "AI"
        lines.append(f"{role}: {t['text'][:800]}")
    return "\n".join(lines)

def mem_add(uid: int, role: str, text: str):
    memory.setdefault(uid, {"turns": []})
    memory[uid]["turns"].append({"role": role, "text": text[:2000]})
    if len(memory[uid]["turns"]) > MAX_MEMORY_TURNS:
        memory[uid]["turns"] = memory[uid]["turns"][-MAX_MEMORY_TURNS:]

def detect_mode(text: str) -> str:
    t = text.lower()
    if any(x in t for x in ["ошибка", "traceback", "exception", "error", "баг"]):
        return "debug"
    if any(x in t for x in ["объясни", "что делает", "поясни"]):
        return "explain"
    if any(x in t for x in ["рефактор", "улучши код"]):
        return "refactor"
    if any(x in t for x in ["напиши", "создай", "сделай", "код"]):
        return "code"
    return "auto"

BASE_SYSTEM = """
Ты AI Code Assistant. Правила:
1. Давай полный рабочий код без заглушек
2. Код в ```язык блоках
3. Кратко поясняй после кода
4. Не выдумывай несуществующие библиотеки
"""

def build_system(uid: int, mode: str) -> str:
    ctx = get_context(uid)
    mode_text = {
        "auto": "Универсальный режим",
        "code": "Режим КОД: минимум текста, полный код",
        "debug": "Режим ДЕБАГ: найди причину, дай исправление",
        "explain": "Режим ОБЪЯСНЕНИЕ: простым языком",
        "refactor": "Режим РЕФАКТОРИНГ: улучши код",
    }.get(mode, "")
    return f"{BASE_SYSTEM}\n\n{mode_text}\n\nКонтекст:\n{ctx}"

# =========================================================
# TOOLS
# =========================================================

def crypto_price(sym: str = "BTC") -> str:
    try:
        r = http.get(f"https://api.coinbase.com/v2/prices/{sym}-USD/spot", timeout=8)
        r.raise_for_status()
        amount = float(r.json()["data"]["amount"])
        return f"💰 {sym}: ${amount:,.2f}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def search_web(query: str) -> str:
    try:
        r = http.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1}, timeout=10)
        data = r.json()
        abstract = data.get("AbstractText") or ""
        if abstract:
            return f"🔍 {query}\n\n{abstract[:1000]}"
        return f"🔍 Ничего не найдено по: {query}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def make_zip(data: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in data.items():
            if isinstance(content, str):
                z.writestr(f"{name}.txt", content[:50000])
        z.writestr("README.md", f"# Project\nGenerated: {datetime.now()}")
    buf.seek(0)
    return buf.getvalue()

# =========================================================
# KEYBOARDS
# =========================================================

def main_kb(role: str = "user"):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btns = [
        types.KeyboardButton("🚀 Проект"),
        types.KeyboardButton("💻 Код"),
        types.KeyboardButton("🐛 Дебаг"),
        types.KeyboardButton("📁 Файл"),
        types.KeyboardButton("💰 Крипта"),
        types.KeyboardButton("🔍 Поиск"),
        types.KeyboardButton("📊 Статус"),
        types.KeyboardButton("🔄 Сброс"),
    ]
    if role == "admin":
        btns.append(types.KeyboardButton("👑 Админ"))
    kb.add(*btns)
    return kb

def file_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Проверить", callback_data="f_check"),
        types.InlineKeyboardButton("🐛 Баги", callback_data="f_bugs"),
        types.InlineKeyboardButton("📖 Объяснить", callback_data="f_explain"),
        types.InlineKeyboardButton("✨ Улучшить", callback_data="f_improve"),
    )
    return kb

def proj_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏️ Доработать", callback_data="p_edit"),
        types.InlineKeyboardButton("📦 ZIP", callback_data="p_zip"),
    )
    return kb
    # =========================================================
# COMMANDS
# =========================================================

@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    get_user(uid, uname)
    role = get_role(uid, uname)
    bot.send_message(m.chat.id, f"👋 Привет! Я AI Code Assistant v{VERSION}\n\nНапиши задачу или отправь код.", reply_markup=main_kb(role))

@bot.message_handler(commands=["help"])
def cmd_help(m):
    bot.send_message(m.chat.id, "📚 Команды:\n/start\n/help\n/project\n/reset\n/limit\n/premium\n\nПросто напиши задачу!")

@bot.message_handler(commands=["reset", "new"])
def cmd_reset(m):
    uid = m.from_user.id
    memory.pop(uid, None)
    files.pop(uid, None)
    user_modes.pop(uid, None)
    bot.reply_to(m, "✅ Память сброшена.")

@bot.message_handler(commands=["limit"])
def cmd_limit(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    today = date.today()
    used = usage.get(uid, {}).get(today, 0)
    limit = get_limit(uid, uname)
    bot.reply_to(m, f"📊 Сегодня: {used}/{limit}")

@bot.message_handler(commands=["premium"])
def cmd_prem(m):
    bot.reply_to(m, f"⭐ Premium: напиши админу.\nРеквизиты: {CARD_NUMBER}")

@bot.message_handler(commands=["project"])
def cmd_proj(m):
    msg = bot.send_message(m.chat.id, "🚀 Опиши проект подробно:")
    bot.register_next_step_handler(msg, do_project)

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    if not is_admin(m.from_user.username or ""):
        return bot.reply_to(m, "⛔ Нет доступа")
    bot.reply_to(m, f"👑 Статистика\n\nUsers: {stats['users']}\nRequests: {stats['total']}\nOK: {stats['ok']}\nErr: {stats['err']}")

# =========================================================
# BUTTONS
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🚀 Проект")
def btn_proj(m):
    cmd_proj(m)

@bot.message_handler(func=lambda m: m.text == "💻 Код")
def btn_code(m):
    user_modes[m.from_user.id] = "code"
    msg = bot.send_message(m.chat.id, "💻 Опиши что написать:")
    bot.register_next_step_handler(msg, handle_text)

@bot.message_handler(func=lambda m: m.text == "🐛 Дебаг")
def btn_debug(m):
    user_modes[m.from_user.id] = "debug"
    msg = bot.send_message(m.chat.id, "🐛 Отправь код с ошибкой:")
    bot.register_next_step_handler(msg, handle_text)

@bot.message_handler(func=lambda m: m.text == "📁 Файл")
def btn_file(m):
    bot.send_message(m.chat.id, "📁 Отправь файл документом.")

@bot.message_handler(func=lambda m: m.text == "💰 Крипта")
def btn_crypto(m):
    bot.send_message(m.chat.id, f"{crypto_price('BTC')}\n{crypto_price('ETH')}\n{crypto_price('SOL')}")

@bot.message_handler(func=lambda m: m.text == "🔍 Поиск")
def btn_search(m):
    msg = bot.send_message(m.chat.id, "🔍 Что найти?")
    bot.register_next_step_handler(msg, lambda x: bot.reply_to(x, search_web(x.text or "")))

@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def btn_status(m):
    cmd_limit(m)

@bot.message_handler(func=lambda m: m.text == "🔄 Сброс")
def btn_reset(m):
    cmd_reset(m)

@bot.message_handler(func=lambda m: m.text == "👑 Админ")
def btn_admin(m):
    cmd_stats(m)

# =========================================================
# PROJECT
# =========================================================

def do_project(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    desc = (m.text or "").strip()
    ok, err = can_use(uid, uname)
    if not ok:
        return bot.reply_to(m, err)
    if not desc:
        return bot.reply_to(m, "❌ Пустое описание")
    
    status = bot.send_message(m.chat.id, "⏳ Генерирую проект...")
    typing_action(m.chat.id)
    
    system = "Ты senior developer. Создай полный проект по описанию. Дай: структуру файлов, полный код, запуск, деплой."
    
    try:
        result = ai_call(desc, system=system, temperature=0.5, max_tokens=12000)
        projects[uid] = {"desc": desc, "result": result}
        add_use(uid)
        get_user(uid)["proj"] += 1
        stats["ok"] += 1
        stats["projects"] += 1
        bot.delete_message(m.chat.id, status.message_id)
        send_long(m.chat.id, result, reply_markup=proj_kb())
    except Exception as e:
        stats["err"] += 1
        safe_edit(m.chat.id, status.message_id, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda c: c.data == "p_zip")
def cb_zip(c):
    uid = c.from_user.id
    if uid not in projects:
        return bot.answer_callback_query(c.id, "❌ Нет проекта")
    bot.answer_callback_query(c.id, "📦 Создаю...")
    try:
        data = make_zip(projects[uid])
        bot.send_document(c.message.chat.id, data, visible_file_name=f"project_{uid}.zip")
    except Exception as e:
        bot.send_message(c.message.chat.id, f"❌ {e}")

@bot.callback_query_handler(func=lambda c: c.data == "p_edit")
def cb_edit(c):
    bot.answer_callback_query(c.id)
    msg = bot.send_message(c.message.chat.id, "✏️ Что изменить?")
    bot.register_next_step_handler(msg, handle_edit)

def handle_edit(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    ok, err = can_use(uid, uname)
    if not ok:
        return bot.reply_to(m, err)
    if uid not in projects:
        return bot.reply_to(m, "❌ Нет проекта")
    
    typing_action(m.chat.id)
    prev = projects[uid].get("result", "")[:10000]
    system = "Доработай проект по запросу пользователя."
    prompt = f"Проект:\n{prev}\n\nЗапрос:\n{m.text}"
    
    try:
        result = ai_call(prompt, system=system)
        projects[uid]["result"] = result
        add_use(uid)
        stats["ok"] += 1
        send_long(m.chat.id, result, reply_markup=proj_kb())
    except Exception as e:
        stats["err"] += 1
        bot.reply_to(m, f"❌ {e}")

# =========================================================
# FILE HANDLER
# =========================================================

@bot.message_handler(content_types=["document"])
def on_file(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    ok, err = can_use(uid, uname)
    if not ok:
        return bot.reply_to(m, err)
    try:
        info = bot.get_file(m.document.file_id)
        data = bot.download_file(info.file_path)
        text = data.decode("utf-8", errors="ignore")[:MAX_FILE_SIZE]
        files[uid] = {"name": m.document.file_name, "code": text}
        bot.reply_to(m, f"📁 Файл `{m.document.file_name}` получен.\nЧто сделать?", parse_mode="Markdown", reply_markup=file_kb())
    except Exception as e:
        bot.reply_to(m, f"❌ {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("f_"))
def cb_file(c):
    uid, uname = c.from_user.id, c.from_user.username or ""
    ok, err = can_use(uid, uname)
    if not ok:
        bot.answer_callback_query(c.id)
        return bot.send_message(c.message.chat.id, err)
    if uid not in files:
        return bot.answer_callback_query(c.id, "❌ Файл не найден")
    
    act = c.data[2:]
    code = files[uid]["code"]
    name = files[uid]["name"]
    
    prompts = {
        "check": f"Проверь код {name}. Найди проблемы.",
        "bugs": f"Найди баги в {name}. Дай исправления.",
        "explain": f"Объясни что делает {name}.",
        "improve": f"Улучши код {name}.",
    }
    
    bot.answer_callback_query(c.id, "⏳...")
    typing_action(c.message.chat.id)
    
    try:
        result = ai_call(f"{prompts.get(act, 'Анализ')}\n\nКод:\n```\n{code}\n```", temperature=0.4)
        add_use(uid)
        stats["ok"] += 1
        send_long(c.message.chat.id, result)
    except Exception as e:
        stats["err"] += 1
        bot.send_message(c.message.chat.id, f"❌ {e}")

# =========================================================
# MAIN TEXT
# =========================================================

def handle_text(m):
    on_text(m)

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(m):
    uid, uname = m.from_user.id, m.from_user.username or ""
    text = (m.text or "").strip()
    get_user(uid, uname)
    
    # Quick tools
    t = text.lower()
    if any(x in t for x in ["btc", "eth", "sol", "курс"]):
        sym = "ETH" if "eth" in t else "SOL" if "sol" in t else "BTC"
        return bot.reply_to(m, crypto_price(sym))
    
    if any(x in t for x in ["найди", "поищи", "загугли"]):
        q = re.sub(r"(найди|поищи|загугли)", "", text, flags=re.IGNORECASE).strip()
        if q:
            return bot.reply_to(m, search_web(q))
    
    ok, err = can_use(uid, uname)
    if not ok:
        return bot.reply_to(m, err)
    
    typing_action(m.chat.id)
    
    mode = user_modes.get(uid) or detect_mode(text)
    mem_add(uid, "user", text)
    system = build_system(uid, mode)
    
    try:
        result = ai_call(text, system=system)
        mem_add(uid, "assistant", result[:2000])
        add_use(uid)
        stats["ok"] += 1
        send_long(m.chat.id, result)
    except Exception as e:
        stats["err"] += 1
        bot.reply_to(m, f"❌ {e}")

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    print(f"🚀 AI Bot v{VERSION}")
    for _ in range(3):
        try:
            bot.remove_webhook()
        except Exception:
            pass
        time.sleep(0.5)
    print("✅ Polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(5)
