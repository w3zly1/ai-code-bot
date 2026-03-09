#!/usr/bin/env python3
"""
🤖 AI CODE ARMY v2.1
Рой из 8 ИИ-агентов — ИСПРАВЛЕННАЯ ВЕРСИЯ
"""

import os
import logging
import time
import json
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

# ============================================================================
# CONFIG
# ============================================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CARD_NUMBER = os.environ.get("CARD_NUMBER", "XXXX XXXX XXXX XXXX")

ADMINS = {"MAON1K"}
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

FREE_DAILY_LIMIT = 25
BOT_VERSION = "2.1"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# INIT
# ============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# ============================================================================
# ХРАНИЛИЩА
# ============================================================================

user_data: Dict[int, dict] = {}
user_usage: Dict[int, dict] = {}
conversations: Dict[int, List[dict]] = {}
project_mode: Dict[int, dict] = {}
file_cache: Dict[int, dict] = {}

stats = {
    "total": 0,
    "success": 0,
    "errors": 0,
    "users": 0,
    "projects": 0,
    "started": datetime.now()
}

# ============================================================================
# АКТУАЛЬНЫЕ МОДЕЛИ GEMINI (март 2026)
# ============================================================================

# Пробуем разные форматы названий
GEMINI_MODELS = [
    "gemini-pro",                    # Базовая
    "gemini-1.0-pro",               # Версия 1.0
    "gemini-1.0-pro-latest",        # Последняя 1.0
    "models/gemini-pro",            # С префиксом
]

def call_gemini(prompt: str, system: str = "") -> str:
    """Вызов Gemini с автоматическим перебором моделей"""
    
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    last_error = None
    
    for model_name in GEMINI_MODELS:
        try:
            logger.info(f"🔄 Trying model: {model_name}")
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=8000
                )
            )
            logger.info(f"✅ Model {model_name} OK!")
            return response.text
            
        except Exception as e:
            last_error = e
            logger.warning(f"⚠️ Model {model_name} failed: {str(e)[:80]}")
            continue
    
    # Если все модели не сработали - пробуем получить список доступных
    try:
        logger.info("📋 Fetching available models...")
        available = list(genai.list_models())
        model_names = [m.name for m in available if 'generateContent' in str(m.supported_generation_methods)]
        logger.info(f"📋 Available models: {model_names[:5]}")
        
        if model_names:
            # Пробуем первую доступную
            model_name = model_names[0].replace("models/", "")
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(full_prompt)
            return response.text
    except Exception as e:
        logger.error(f"❌ List models failed: {e}")
    
    raise Exception(f"All models failed. Last error: {last_error}")

# ============================================================================
# ФРАЗЫ
# ============================================================================

THINKING = ["🧠 Думаю...", "⚡ Обрабатываю...", "🔮 Анализирую...", "✨ Генерирую...", "🚀 Работаю..."]
SUCCESS = ["✅ Готово!", "🎉 Выполнено!", "💪 Сделано!", "⭐ Успех!"]

# ============================================================================
# 8 АГЕНТОВ
# ============================================================================

AGENTS = {
    "architect": {
        "name": "🧠 Архитектор",
        "emoji": "🧠",
        "role": """Ты Lead Software Architect. Проектируешь архитектуру приложений.
Выбираешь технологии, создаёшь структуру проекта, пишешь ТЗ для команды.
Отвечай структурированно с эмодзи."""
    },
    "backend": {
        "name": "💻 Backend Dev",
        "emoji": "💻",
        "role": """Ты Senior Backend Developer. Пишешь серверный код на Python/Node.js.
REST API, работа с БД, аутентификация. Пиши ПОЛНЫЙ production-ready код."""
    },
    "frontend": {
        "name": "🎨 Frontend Dev",
        "emoji": "🎨",
        "role": """Ты Senior Frontend Developer. Создаёшь современные UI.
HTML/CSS/JS, React, адаптивная вёрстка. Пиши ПОЛНЫЙ красивый код."""
    },
    "botdev": {
        "name": "🤖 Bot Dev",
        "emoji": "🤖",
        "role": """Ты Expert Telegram Bot Developer. Создаёшь ботов на Python.
Кнопки, команды, FSM, платежи. Пиши ГОТОВЫЙ к запуску код."""
    },
    "reviewer": {
        "name": "🔍 Reviewer",
        "emoji": "🔍",
        "role": """Ты Senior Code Reviewer. Анализируешь код, находишь проблемы.
Даёшь оценку 1-10, список проблем и рекомендаций."""
    },
    "security": {
        "name": "🔒 Security",
        "emoji": "🔒",
        "role": """Ты Cybersecurity Specialist. Проверяешь код на уязвимости.
SQL injection, XSS, CSRF. Даёшь исправленный безопасный код."""
    },
    "devops": {
        "name": "🚀 DevOps",
        "emoji": "🚀",
        "role": """Ты DevOps Engineer. Готовишь деплой на Railway/Vercel.
Dockerfile, конфиги, инструкции. Чтобы работало из коробки."""
    },
    "pm": {
        "name": "📊 PM",
        "emoji": "📊",
        "role": """Ты Project Manager. Собираешь финальный отчёт для клиента.
Что готово, что нужно, следующие шаги. Красиво и структурированно."""
    }
}

# ============================================================================
# AI ARMY
# ============================================================================

class AIArmy:
    @staticmethod
    def call_agent(name: str, task: str, context: str = "") -> str:
        agent = AGENTS[name]
        system = f"{agent['role']}\n\nКонтекст:\n{context}" if context else agent['role']
        return call_gemini(task, system=system)
    
    @staticmethod
    def build_project(user_id: int, description: str, callback) -> dict:
        results = {}
        needs_bot = "бот" in description.lower() or "telegram" in description.lower()
        steps = 7 if needs_bot else 6
        
        def progress(step, text):
            bar = "🟩" * step + "⬜" * (steps - step)
            callback(f"{bar} {step}/{steps}\n\n{text}")
        
        # 1. Архитектор
        progress(1, "🧠 Архитектор проектирует...")
        results["architect"] = AIArmy.call_agent("architect", description)
        time.sleep(1)
        
        # 2. Backend
        progress(2, "💻 Backend Developer пишет код...")
        results["backend"] = AIArmy.call_agent("backend", 
            "Создай backend код", context=results["architect"])
        time.sleep(1)
        
        # 3. Frontend
        progress(3, "🎨 Frontend Developer создаёт UI...")
        results["frontend"] = AIArmy.call_agent("frontend",
            "Создай frontend код", context=results["architect"])
        time.sleep(1)
        
        # 4. Bot (если нужен)
        if needs_bot:
            progress(4, "🤖 Bot Developer создаёт бота...")
            results["bot"] = AIArmy.call_agent("botdev",
                "Создай Telegram бота", context=results["architect"])
            time.sleep(1)
        
        # Security
        step = 5 if needs_bot else 4
        progress(step, "🔒 Security проверяет...")
        all_code = f"{results['backend']}\n{results['frontend']}"
        results["security"] = AIArmy.call_agent("security",
            "Проверь на уязвимости", context=all_code)
        time.sleep(1)
        
        # DevOps
        step += 1
        progress(step, "🚀 DevOps готовит деплой...")
        results["devops"] = AIArmy.call_agent("devops",
            "Создай конфиги деплоя", context=all_code)
        time.sleep(1)
        
        # PM
        progress(steps, "📊 PM собирает отчёт...")
        summary = "\n".join([f"{k}: {v[:200]}" for k, v in results.items()])
        results["pm"] = AIArmy.call_agent("pm",
            "Собери финальный отчёт", context=summary)
        
        return results

# ============================================================================
# SMART AI С ПАМЯТЬЮ
# ============================================================================

class SmartAI:
    @staticmethod
    def chat(user_id: int, prompt: str) -> str:
        if user_id not in conversations:
            conversations[user_id] = []
        
        conversations[user_id].append({"role": "user", "content": prompt})
        
        if len(conversations[user_id]) > 20:
            conversations[user_id] = conversations[user_id][-20:]
        
        context = "\n".join([
            f"{'User' if m['role']=='user' else 'AI'}: {m['content']}"
            for m in conversations[user_id][-8:]
        ])
        
        system = f"""Ты AI Code Assistant Pro v{BOT_VERSION}.
Умный помощник программиста с памятью.

Умеешь:
- Писать код
- Находить баги
- Объяснять
- Улучшать

История:
{context}

Отвечай полезно. Код в блоках ```"""

        result = call_gemini(prompt, system=system)
        
        conversations[user_id].append({"role": "assistant", "content": result})
        
        return result

# ============================================================================
# УТИЛИТЫ
# ============================================================================

def get_crypto(symbol: str = "BTC") -> str:
    try:
        r = requests.get(f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", timeout=5)
        price = float(r.json()["data"]["amount"])
        return f"💰 **{symbol}/USD:** ${price:,.2f}"
    except:
        return f"❌ Ошибка получения {symbol}"

def search_web(query: str) -> str:
    try:
        r = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json", timeout=10)
        data = r.json()
        result = f"🔍 **{query}**\n\n"
        if data.get("Abstract"):
            result += data["Abstract"]
        return result if len(result) > 30 else "Ничего не найдено"
    except:
        return "❌ Ошибка поиска"

def create_zip(results: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in results.items():
            blocks = re.findall(r'```(\w+)?\n(.*?)```', content, re.DOTALL)
            for i, (lang, code) in enumerate(blocks):
                ext = lang or 'txt'
                zf.writestr(f"{name}_{i}.{ext}", code.strip())
        zf.writestr("README.md", "# Project\nCreated by AI CODE ARMY")
    return buf.getvalue()

# ============================================================================
# USER MANAGEMENT
# ============================================================================

def get_user(uid: int, username: str = None) -> dict:
    if uid not in user_data:
        user_data[uid] = {"username": username, "total": 0, "projects": 0, "referrals": 0}
        stats["users"] += 1
    return user_data[uid]

def is_admin(username: str) -> bool:
    return username in ADMINS if username else False

def is_premium(uid: int, username: str) -> bool:
    return is_admin(username) or uid in PREMIUM_USERS

def get_usage(uid: int) -> int:
    today = date.today()
    if uid not in user_usage:
        user_usage[uid] = {}
    return user_usage[uid].get(today, 0)

def add_usage(uid: int):
    today = date.today()
    if uid not in user_usage:
        user_usage[uid] = {}
    user_usage[uid][today] = user_usage[uid].get(today, 0) + 1
    get_user(uid)["total"] += 1
    stats["total"] += 1

def can_use(uid: int, username: str) -> Tuple[bool, str]:
    if is_admin(username) or uid in PREMIUM_USERS:
        return True, ""
    if get_usage(uid) >= FREE_DAILY_LIMIT:
        return False, f"⚠️ Лимит исчерпан ({FREE_DAILY_LIMIT}/день)\n\n⭐ /premium"
    return True, ""

# ============================================================================
# МЕНЮ
# ============================================================================

def main_menu(is_adm=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btns = [
        types.KeyboardButton("🏗️ Создать проект"),
        types.KeyboardButton("💬 Вопрос"),
        types.KeyboardButton("📊 Стата"),
        types.KeyboardButton("🧹 Очистить"),
        types.KeyboardButton("💰 Крипта"),
        types.KeyboardButton("⭐ Premium"),
    ]
    if is_adm:
        btns.append(types.KeyboardButton("👑 Админ"))
    kb.add(*btns)
    return kb

# ============================================================================
# КОМАНДЫ
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    get_user(uid, username)
    
    is_adm = is_admin(username)
    
    text = f"""🤖 **AI CODE ARMY v{BOT_VERSION}**

Привет, **{message.from_user.first_name}**! 👋

Я команда из **8 ИИ-агентов**:
🧠💻🎨🤖🔍🔒🚀📊

**Умею:**
• Создавать проекты (сайты, боты, API)
• Писать и улучшать код
• Находить баги
• Помнить наш разговор

**Тариф:** {'👑 АДМИН' if is_adm else f'🆓 {FREE_DAILY_LIMIT}/день'}

Используй кнопки! 👇"""
    
    bot.send_message(message.chat.id, text, reply_markup=main_menu(is_adm), parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, """📖 **Справка**

🏗️ **Проект** — команда создаёт за 3-5 мин
💬 **Вопрос** — просто напиши
📊 **Стата** — твоя статистика
🧹 **Очистить** — сброс памяти
💰 **Крипта** — курсы BTC/ETH
⭐ **Premium** — безлимит

Примеры:
• "Напиши бота для заказов"
• "Найди баг в коде"
• "Курс биткоина"
""", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    user = get_user(uid)
    
    status = "👑 Админ" if is_admin(username) else ("⭐ Premium" if uid in PREMIUM_USERS else "🆓 Free")
    
    bot.send_message(message.chat.id, f"""📊 **Статистика**

👤 Статус: {status}
📅 Сегодня: {get_usage(uid)}/{FREE_DAILY_LIMIT}
📈 Всего: {user['total']}
🏗️ Проектов: {user['projects']}
💾 Память: {len(conversations.get(uid, []))} сообщений
""", parse_mode="Markdown")

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    if message.from_user.id in conversations:
        conversations[message.from_user.id] = []
    bot.reply_to(message, "🧹 Память очищена!")

@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    
    if is_admin(username):
        bot.send_message(message.chat.id, "👑 Вы админ — безлимит!")
        return
    
    bot.send_message(message.chat.id, f"""⭐ **Premium — 499₽/мес**

✅ Безлимит запросов
✅ Приоритет
✅ Расширенная память

**Оплата:**
Карта: `{CARD_NUMBER}`
Комментарий: `Premium {uid}`

Скинь скрин → активация 10 мин
""", parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if not is_admin(message.from_user.username):
        return
    
    uptime = datetime.now() - stats["started"]
    
    bot.send_message(message.chat.id, f"""👑 **Админ-панель**

⏱ Аптайм: {uptime}
👥 Юзеров: {stats['users']}
📨 Запросов: {stats['total']}
✅ Успешно: {stats['success']}
❌ Ошибок: {stats['errors']}
🏗️ Проектов: {stats['projects']}
""", parse_mode="Markdown")

# ============================================================================
# КНОПКИ
# ============================================================================

@bot.message_handler(func=lambda m: m.text == "🏗️ Создать проект")
def btn_project(message):
    msg = bot.send_message(message.chat.id, 
        "🏗️ **Создание проекта**\n\nОпиши что нужно:\n\n• Сайт-визитка\n• Telegram бот\n• REST API\n• и т.д.",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_project)

def process_project(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    desc = message.text.strip()
    
    if len(desc) < 10:
        bot.reply_to(message, "❌ Опиши подробнее")
        return
    
    can, err = can_use(uid, username)
    if not can:
        bot.reply_to(message, err, parse_mode="Markdown")
        return
    
    logger.info(f"🏗️ PROJECT: @{username} — {desc[:50]}")
    
    status = bot.send_message(message.chat.id, f"🚀 **Запускаю команду...**\n\n{random.choice(THINKING)}", parse_mode="Markdown")
    
    def update(text):
        try:
            bot.edit_message_text(f"🚀 **Работаем...**\n\n{text}", 
                chat_id=message.chat.id, message_id=status.message_id, parse_mode="Markdown")
        except:
            pass
    
    try:
        results = AIArmy.build_project(uid, desc, update)
        
        add_usage(uid)
        get_user(uid)["projects"] += 1
        stats["success"] += 1
        stats["projects"] += 1
        
        project_mode[uid] = {"results": results}
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        bot.send_message(message.chat.id, f"🎉 **ГОТОВО!**", parse_mode="Markdown")
        
        if "pm" in results:
            send_long(message.chat.id, results["pm"])
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🧠 Архитектура", callback_data="v_architect"),
            types.InlineKeyboardButton("💻 Backend", callback_data="v_backend"),
            types.InlineKeyboardButton("🎨 Frontend", callback_data="v_frontend"),
            types.InlineKeyboardButton("🔒 Security", callback_data="v_security"),
            types.InlineKeyboardButton("🚀 DevOps", callback_data="v_devops"),
            types.InlineKeyboardButton("📦 ZIP", callback_data="download"),
        )
        if "bot" in results:
            kb.add(types.InlineKeyboardButton("🤖 Bot", callback_data="v_bot"))
        
        bot.send_message(message.chat.id, "📂 **Детали:**", reply_markup=kb, parse_mode="Markdown")
        
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Project error: {e}", exc_info=True)
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)[:200]}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("v_"))
def cb_view(call):
    uid = call.from_user.id
    if uid not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    part = call.data[2:]
    results = project_mode[uid]["results"]
    
    if part in results:
        bot.answer_callback_query(call.id)
        send_long(call.message.chat.id, f"**{part.upper()}:**\n\n{results[part]}")
    else:
        bot.answer_callback_query(call.id, "❌ Не найдено")

@bot.callback_query_handler(func=lambda c: c.data == "download")
def cb_download(call):
    uid = call.from_user.id
    if uid not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    bot.answer_callback_query(call.id, "📦 Создаю...")
    
    try:
        data = create_zip(project_mode[uid]["results"])
        bot.send_document(call.message.chat.id, document=data, 
            visible_file_name=f"project_{uid}.zip", caption="📦 Архив проекта")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda m: m.text == "💬 Вопрос")
def btn_question(message):
    bot.send_message(message.chat.id, "💬 Напиши свой вопрос!\n\nЯ помню наш разговор.")

@bot.message_handler(func=lambda m: m.text == "📊 Стата")
def btn_stats(message):
    cmd_stats(message)

@bot.message_handler(func=lambda m: m.text == "🧹 Очистить")
def btn_clear(message):
    cmd_clear(message)

@bot.message_handler(func=lambda m: m.text == "💰 Крипта")
def btn_crypto(message):
    btc = get_crypto("BTC")
    eth = get_crypto("ETH")
    bot.send_message(message.chat.id, f"💰 **Курсы:**\n\n{btc}\n{eth}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "⭐ Premium")
def btn_premium(message):
    cmd_premium(message)

@bot.message_handler(func=lambda m: m.text == "👑 Админ")
def btn_admin(message):
    cmd_admin(message)

# ============================================================================
# ФАЙЛЫ
# ============================================================================

@bot.message_handler(content_types=['document'])
def handle_file(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    
    can, err = can_use(uid, username)
    if not can:
        bot.reply_to(message, err)
        return
    
    try:
        f = bot.get_file(message.document.file_id)
        content = bot.download_file(f.file_path)
        
        try:
            text = content.decode('utf-8')
        except:
            text = content.decode('latin-1')
        
        file_cache[uid] = {"name": message.document.file_name, "code": text}
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔍 Проверить", callback_data="f_review"),
            types.InlineKeyboardButton("🐛 Баги", callback_data="f_debug"),
            types.InlineKeyboardButton("📖 Объяснить", callback_data="f_explain"),
            types.InlineKeyboardButton("✨ Улучшить", callback_data="f_improve"),
        )
        
        bot.reply_to(message, f"📁 Файл `{message.document.file_name}` получен!\n\nЧто сделать?",
            reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("f_"))
def cb_file(call):
    uid = call.from_user.id
    if uid not in file_cache:
        bot.answer_callback_query(call.id, "❌ Файл не найден")
        return
    
    action = call.data[2:]
    code = file_cache[uid]["code"]
    
    prompts = {
        "review": f"Сделай code review:\n```\n{code}\n```",
        "debug": f"Найди баги:\n```\n{code}\n```",
        "explain": f"Объясни код:\n```\n{code}\n```",
        "improve": f"Улучши код:\n```\n{code}\n```"
    }
    
    bot.answer_callback_query(call.id, random.choice(THINKING))
    
    try:
        result = SmartAI.chat(uid, prompts[action])
        add_usage(uid)
        stats["success"] += 1
        send_long(call.message.chat.id, result)
    except Exception as e:
        stats["errors"] += 1
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {str(e)[:200]}")

# ============================================================================
# ГЛАВНЫЙ ОБРАБОТЧИК
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    uid = message.from_user.id
    username = message.from_user.username or ""
    text = message.text.strip()
    
    if len(text) < 2:
        return
    
    can, err = can_use(uid, username)
    if not can:
        bot.reply_to(message, err, parse_mode="Markdown")
        return
    
    get_user(uid, username)
    
    # Крипта
    if any(w in text.lower() for w in ['курс', 'btc', 'eth', 'биткоин']):
        symbol = "ETH" if "eth" in text.lower() else "BTC"
        bot.reply_to(message, get_crypto(symbol), parse_mode="Markdown")
        return
    
    # Поиск
    if any(w in text.lower() for w in ['найди', 'поищи', 'search']):
        query = re.sub(r'найди|поищи|search|в интернете', '', text, flags=re.I).strip()
        bot.reply_to(message, search_web(query), parse_mode="Markdown")
        return
    
    logger.info(f"💬 @{username}: {text[:50]}")
    bot.send_chat_action(message.chat.id, 'typing')
    
    status = bot.send_message(message.chat.id, random.choice(THINKING))
    
    try:
        # Если есть файл в кеше и говорят про него
        if uid in file_cache and any(w in text.lower() for w in ['файл', 'код', 'этот', 'его', 'проверь']):
            text = f"{text}\n\nКод:\n```\n{file_cache[uid]['code']}\n```"
        
        result = SmartAI.chat(uid, text)
        
        add_usage(uid)
        stats["success"] += 1
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        send_long(message.chat.id, result)
        
        # Напоминание
        if not is_premium(uid, username):
            left = FREE_DAILY_LIMIT - get_usage(uid)
            if 0 < left <= 5:
                bot.send_message(message.chat.id, f"ℹ️ Осталось: {left}")
    
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)[:200]}\n\nПопробуй ещё раз!")

def send_long(chat_id, text: str):
    MAX = 4000
    if len(text) <= MAX:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, text)
        return
    
    parts = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) > MAX:
            parts.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    if current:
        parts.append(current)
    
    for part in parts:
        try:
            bot.send_message(chat_id, part, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, part)
        time.sleep(0.3)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    logger.info(f"🚀 AI CODE ARMY v{BOT_VERSION}")
    logger.info(f"👑 Admins: {ADMINS}")
    logger.info(f"🤖 Agents: {len(AGENTS)}")
    
    # ВАЖНО: Сброс webhook перед стартом
    try:
        bot.remove_webhook()
        logger.info("✅ Webhook removed")
    except Exception as e:
        logger.warning(f"Webhook remove error: {e}")
    
    # Дополнительный сброс через API напрямую
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        logger.info("✅ Webhook deleted via API")
    except:
        pass
    
    time.sleep(2)  # Пауза перед стартом
    
    # Запуск
    while True:
        try:
            logger.info("📡 Starting polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            time.sleep(15)
