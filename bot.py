#!/usr/bin/env python3
"""
🤖 AI CODE ARMY v2.0
Рой из 8 ИИ-агентов
Создаёт реальные проекты: сайты, ботов, API
С памятью, поиском, файлами, деплоем
Улучшенная визуализация и интерактивность
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
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import telebot
from telebot import types
import google.generativeai as genai

# ============================================================================
# CONFIG
# ============================================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CARD_NUMBER = os.environ.get("CARD_NUMBER", "XXXX XXXX XXXX XXXX")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

# Админы (безлимит + полный контроль)
ADMINS = {"MAON1K"}

# Premium пользователи
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

# Лимиты
FREE_DAILY_LIMIT = 25  # Увеличил!

# Версия бота
BOT_VERSION = "2.0"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# INITIALIZATION
# ============================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# ============================================================================
# ХРАНИЛИЩА
# ============================================================================

user_data: Dict[int, dict] = {}
user_usage: Dict[int, dict] = {}
conversations: Dict[int, List[dict]] = {}  # ПАМЯТЬ РАЗГОВОРОВ
project_mode: Dict[int, dict] = {}  # Активные проекты
file_cache: Dict[int, dict] = {}  # Загруженные файлы
user_settings: Dict[int, dict] = {}  # Настройки пользователей

# Статистика
stats = {
    "total_requests": 0,
    "successful": 0,
    "errors": 0,
    "users_total": 0,
    "projects_created": 0,
    "messages_today": 0,
    "started_at": datetime.now()
}

# ============================================================================
# МОТИВАЦИОННЫЕ ФРАЗЫ И ЭМОДЗИ
# ============================================================================

THINKING_PHRASES = [
    "🧠 Думаю над этим...",
    "⚡ Обрабатываю запрос...",
    "🔮 Анализирую...",
    "💭 Размышляю...",
    "🎯 Работаю над решением...",
    "✨ Генерирую магию...",
    "🚀 Запускаю нейросети...",
    "🔥 Включаю турбо-режим...",
]

SUCCESS_PHRASES = [
    "✅ Готово!",
    "🎉 Выполнено!",
    "💪 Сделано!",
    "🏆 Успех!",
    "⭐ Отлично получилось!",
    "🔥 Вот результат!",
]

WELCOME_TIPS = [
    "💡 Совет: Чем подробнее опишешь задачу — тем лучше результат!",
    "💡 Совет: Я помню весь наш разговор. Можешь писать 'доработай' или 'исправь'.",
    "💡 Совет: Отправь файл с кодом — я проанализирую его!",
    "💡 Совет: Попробуй 'Создать проект' — команда из 8 агентов сделает всё!",
    "💡 Совет: Спроси курс биткоина или поищи информацию в интернете!",
]

PROGRESS_EMOJIS = ["⬜", "🟦", "🟩", "🟨", "🟧", "🟥", "🟪", "⬛"]

# ============================================================================
# AI МОДЕЛИ (АКТУАЛЬНЫЕ!)
# ============================================================================

# Список моделей для попытки (от лучшей к базовой)
GEMINI_MODELS = [
    "gemini-1.5-pro-latest",      # Самая умная стабильная
    "gemini-1.5-flash-latest",    # Быстрая стабильная
    "gemini-1.5-pro",             # Fallback
    "gemini-1.5-flash",           # Fallback быстрая
]

def call_gemini(prompt: str, system: str = "", max_tokens: int = 8000) -> str:
    """Универсальный вызов Gemini с автофолбэком"""
    
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    last_error = None
    
    for model_name in GEMINI_MODELS:
        try:
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=max_tokens
                )
            )
            logger.info(f"✅ Model {model_name} succeeded")
            return response.text
        except Exception as e:
            last_error = e
            logger.warning(f"⚠️ Model {model_name} failed: {str(e)[:100]}")
            continue
    
    raise Exception(f"All Gemini models failed. Last error: {last_error}")

# ============================================================================
# 8 AI АГЕНТОВ
# ============================================================================

AGENTS = {
    "architect": {
        "name": "🧠 Архитектор",
        "emoji": "🧠",
        "color": "🔵",
        "role": """Ты — Lead Software Architect с 15+ годами опыта.

ТВОЯ РАБОТА:
- Анализ требований клиента
- Проектирование архитектуры (микросервисы, монолит, serverless)
- Выбор оптимальных технологий
- Создание структуры проекта
- Техническое задание для команды

ТЕХНОЛОГИИ:
- Backend: Python (Flask/FastAPI/Django), Node.js (Express/Nest), Go
- Frontend: React, Vue, Svelte, Next.js, HTML/CSS/JS
- БД: PostgreSQL, MongoDB, Redis, SQLite
- Деплой: Vercel, Railway, Netlify, Fly.io

ФОРМАТ ОТВЕТА:
📋 **ПРОЕКТ:** [название]
🎯 **ТИП:** [веб-приложение/бот/API/лендинг]

🛠 **ТЕХНОЛОГИИ:**
- Backend: [технология]
- Frontend: [технология]
- БД: [технология]
- Хостинг: [платформа]

📁 **СТРУКТУРА:**
проект/
├── backend/
│ ├── app.py
│ ├── models.py
│ └── requirements.txt
├── frontend/
│ ├── index.html
│ ├── style.css
│ └── script.js
└── README.md

📝 **ЗАДАНИЯ ДЛЯ КОМАНДЫ:**
1. Backend Dev: [задача]
2. Frontend Dev: [задача]
3. Bot Dev: [если нужен бот]
4. Security: [что проверить]
5. DevOps: [как деплоить]

Будь конкретным и профессиональным!"""
    },
    
    "backend": {
        "name": "💻 Backend Developer",
        "emoji": "💻",
        "color": "🟢",
        "role": """Ты — Senior Backend Developer (Python/Node.js).

ТВОЯ РАБОТА:
- Разработка серверной логики
- REST/GraphQL API
- Работа с БД
- Аутентификация
- WebSockets

СТЕК:
- Python: Flask, FastAPI, Django, SQLAlchemy
- Node.js: Express, Nest.js, Prisma
- БД: PostgreSQL, MongoDB, Redis, SQLite

ТРЕБОВАНИЯ К КОДУ:
✅ Clean code с комментариями
✅ Обработка ВСЕХ ошибок
✅ Валидация входных данных
✅ Логирование
✅ ENV переменные для секретов
✅ Type hints
✅ Документация API

Пиши ПОЛНЫЙ production-ready код!"""
    },
    
    "frontend": {
        "name": "🎨 Frontend Developer",
        "emoji": "🎨",
        "color": "🟣",
        "role": """Ты — Senior Frontend Developer.

ТВОЯ РАБОТА:
- Создание современных UI
- Адаптивная вёрстка (mobile-first)
- Работа с API
- Анимации
- SEO оптимизация

СТЕК:
- HTML5, CSS3 (Flexbox, Grid)
- JavaScript ES6+ / TypeScript
- React, Vue, Svelte
- TailwindCSS, Bootstrap

ТРЕБОВАНИЯ:
✅ Кроссбраузерность
✅ Производительность (<3 сек загрузка)
✅ Семантическая вёрстка
✅ Accessibility
✅ Красивый современный дизайн
✅ Анимации и hover-эффекты

Создавай КРАСИВЫЕ и ФУНКЦИОНАЛЬНЫЕ интерфейсы!"""
    },
    
    "botdev": {
        "name": "🤖 Bot Developer",
        "emoji": "🤖",
        "color": "🔷",
        "role": """Ты — Expert Telegram Bot Developer.

ТВОЯ РАБОТА:
- Telegram боты любой сложности
- Inline кнопки, меню
- Webhook / Long Polling
- Платежи
- Интеграция с БД и API

СТЕК:
- Python: python-telegram-bot, aiogram, pyTelegramBotAPI
- Node.js: telegraf, grammy

ФУНКЦИИ:
✅ Команды (/start, /help)
✅ FSM для диалогов
✅ Inline кнопки
✅ Callback handlers
✅ Реферальная система
✅ Админ-панель

Пиши ГОТОВЫХ К ЗАПУСКУ ботов!"""
    },
    
    "reviewer": {
        "name": "🔍 Code Reviewer",
        "emoji": "🔍",
        "color": "🟡",
        "role": """Ты — Senior Code Reviewer.

ТВОЯ РАБОТА:
- Детальный анализ кода
- Проверка best practices
- Поиск багов
- Предложения по улучшению

ПРОВЕРЯЕШЬ:
- Читаемость
- DRY, SOLID принципы
- Нейминг
- Обработка ошибок
- Performance

ФОРМАТ:
📊 **ОЦЕНКА:** [1-10]/10

✅ **ПЛЮСЫ:**
- [что хорошо]

⚠️ **ПРОБЛЕМЫ:**
- [проблема + строка]

💡 **РЕКОМЕНДАЦИИ:**
- [улучшение]

🐛 **ПОТЕНЦИАЛЬНЫЕ БАГИ:**
- [баг + как исправить]

Будь конструктивным!"""
    },
    
    "security": {
        "name": "🔒 Security Expert",
        "emoji": "🔒",
        "color": "🔴",
        "role": """Ты — Cybersecurity Specialist.

ТВОЯ РАБОТА:
- Аудит кода на уязвимости
- Защита от атак
- Безопасное хранение данных
- Rate limiting

ПРОВЕРЯЕШЬ:
🔴 SQL injection
🔴 XSS
🔴 CSRF
🔴 Утечки секретов
🔴 Слабые пароли
🔴 Open redirects

ФОРМАТ:
🛡 **УРОВЕНЬ БЕЗОПАСНОСТИ:** [1-10]/10

🔴 **КРИТИЧЕСКИЕ:**
- [уязвимость]

🟡 **ПРЕДУПРЕЖДЕНИЯ:**
- [проблема]

🟢 **РЕКОМЕНДАЦИИ:**
- [улучшение]

Исправленный код в блоках ```"""
    },
    
    "devops": {
        "name": "🚀 DevOps Engineer",
        "emoji": "🚀",
        "color": "🟠",
        "role": """Ты — Senior DevOps Engineer.

ТВОЯ РАБОТА:
- Деплой на production
- Docker
- CI/CD
- Мониторинг

ПЛАТФОРМЫ:
- Vercel (фронтенд)
- Railway (бэкенд, боты)
- Netlify (статика)
- Fly.io

ВЫДАЁШЬ:
1️⃣ **КОНФИГИ:**
- Dockerfile
- docker-compose.yml
- railway.json / vercel.json

2️⃣ **ENV ПЕРЕМЕННЫЕ** (список)

3️⃣ **ИНСТРУКЦИИ** деплоя по шагам

4️⃣ **КОМАНДЫ** для запуска

Делай так чтобы работало ИЗ КОРОБКИ!"""
    },
    
    "pm": {
        "name": "📊 Project Manager",
        "emoji": "📊",
        "color": "⚪",
        "role": """Ты — Technical Project Manager.

ТВОЯ РАБОТА:
- Координация команды
- Финальный отчёт
- Документация
- Следующие шаги

ФОРМАТ ОТЧЁТА:

📋 **ПРОЕКТ:** [название]
✅ **СТАТУС:** ГОТОВ

━━━━━━━━━━━━━━━━━━━━━

📦 **РЕЗУЛЬТАТЫ:**

**Backend:**
- Файлы: [список]
- API endpoints: [список]

**Frontend:**
- Страницы: [список]
- Компоненты: [список]

**Деплой:**
- Backend → [платформа]
- Frontend → [платформа]

━━━━━━━━━━━━━━━━━━━━━

📌 **СЛЕДУЮЩИЕ ШАГИ:**
1. [действие]
2. [действие]

💡 **СОВЕТЫ:**
- [совет]

Будь организованным и чётким!"""
    }
}

# ============================================================================
# AI ARMY — КОМАНДА АГЕНТОВ
# ============================================================================

class AIArmy:
    """Рой из 8 ИИ-агентов с памятью"""
    
    @staticmethod
    def call_agent(agent_name: str, task: str, context: str = "", 
                   memory: List[dict] = None) -> str:
        """Вызов одного агента"""
        
        if agent_name not in AGENTS:
            raise ValueError(f"Unknown agent: {agent_name}")
        
        agent = AGENTS[agent_name]
        
        # Формируем промпт
        system = f"{agent['role']}\n\n"
        
        if context:
            system += f"📋 КОНТЕКСТ ПРОЕКТА:\n{context}\n\n"
        
        if memory:
            memory_text = "\n".join([
                f"{m['agent']}: {m['content'][:150]}..."
                for m in memory[-5:]
            ])
            system += f"💬 РАБОТА КОМАНДЫ:\n{memory_text}\n\n"
        
        full_prompt = f"ТВОЯ ЗАДАЧА:\n{task}"
        
        return call_gemini(full_prompt, system=system)
    
    @staticmethod
    def build_project(user_id: int, description: str, callback) -> dict:
        """Полный цикл создания проекта командой"""
        
        project_memory = []
        results = {}
        
        needs_bot = any(w in description.lower() for w in ['бот', 'telegram', 'тг'])
        
        def add_memory(agent_name: str, content: str):
            project_memory.append({
                "agent": AGENTS[agent_name]["name"],
                "content": content,
                "time": datetime.now()
            })
        
        def progress(step: int, total: int, text: str):
            bar = "".join(["🟩" if i < step else "⬜" for i in range(total)])
            callback(f"{bar} {step}/{total}\n\n{text}")
        
        total_steps = 7 if needs_bot else 6
        step = 0
        
        # 1. Архитектор
        step += 1
        progress(step, total_steps, f"{AGENTS['architect']['emoji']} Архитектор проектирует систему...")
        arch = AIArmy.call_agent("architect", description)
        results["architect"] = arch
        add_memory("architect", arch)
        time.sleep(1)
        
        # 2. Backend
        step += 1
        progress(step, total_steps, f"{AGENTS['backend']['emoji']} Backend Developer пишет сервер...")
        backend = AIArmy.call_agent("backend", 
            "Создай полный backend код. Production-ready.", 
            context=arch, memory=project_memory)
        results["backend"] = backend
        add_memory("backend", backend)
        time.sleep(1)
        
        # 3. Frontend
        step += 1
        progress(step, total_steps, f"{AGENTS['frontend']['emoji']} Frontend Developer создаёт UI...")
        ctx = f"Архитектура:\n{arch}\n\nBackend:\n{backend[:500]}"
        frontend = AIArmy.call_agent("frontend",
            "Создай полный frontend. Красивый современный дизайн.",
            context=ctx, memory=project_memory)
        results["frontend"] = frontend
        add_memory("frontend", frontend)
        time.sleep(1)
        
        # 4. Bot (если нужен)
        if needs_bot:
            step += 1
            progress(step, total_steps, f"{AGENTS['botdev']['emoji']} Bot Developer создаёт бота...")
            bot_code = AIArmy.call_agent("botdev",
                "Создай полный Telegram бот. Готовый к запуску.",
                context=ctx, memory=project_memory)
            results["bot"] = bot_code
            add_memory("botdev", bot_code)
            time.sleep(1)
        
        # 5. Code Review
        step += 1
        progress(step, total_steps, f"{AGENTS['reviewer']['emoji']} Code Reviewer проверяет код...")
        all_code = f"Backend:\n{backend[:1000]}\n\nFrontend:\n{frontend[:1000]}"
        review = AIArmy.call_agent("reviewer",
            "Проверь код. Найди проблемы.",
            context=all_code, memory=project_memory)
        results["review"] = review
        add_memory("reviewer", review)
        time.sleep(1)
        
        # 6. Security
        step += 1
        progress(step, total_steps, f"{AGENTS['security']['emoji']} Security Expert проверяет безопасность...")
        security = AIArmy.call_agent("security",
            "Проверь на уязвимости.",
            context=all_code, memory=project_memory)
        results["security"] = security
        add_memory("security", security)
        time.sleep(1)
        
        # 7. DevOps
        step += 1
        progress(step, total_steps, f"{AGENTS['devops']['emoji']} DevOps готовит деплой...")
        devops = AIArmy.call_agent("devops",
            "Создай конфиги для деплоя. Railway, Vercel.",
            context=all_code, memory=project_memory)
        results["devops"] = devops
        add_memory("devops", devops)
        time.sleep(1)
        
        # 8. PM собирает
        progress(total_steps, total_steps, f"{AGENTS['pm']['emoji']} Project Manager готовит отчёт...")
        pm_ctx = "\n\n".join([f"{k.upper()}:\n{v[:300]}" for k, v in results.items()])
        pm = AIArmy.call_agent("pm",
            "Собери финальный отчёт для клиента.",
            context=pm_ctx, memory=project_memory)
        results["pm"] = pm
        
        return results

# ============================================================================
# SMART AI — С ПАМЯТЬЮ
# ============================================================================

class SmartAI:
    """AI с памятью разговора"""
    
    @staticmethod
    def chat(user_id: int, prompt: str) -> str:
        """Ответ с учётом контекста разговора"""
        
        # Инициализация памяти
        if user_id not in conversations:
            conversations[user_id] = []
        
        # Добавляем сообщение
        conversations[user_id].append({
            "role": "user",
            "content": prompt,
            "time": datetime.now()
        })
        
        # Ограничиваем память (последние 30)
        if len(conversations[user_id]) > 30:
            conversations[user_id] = conversations[user_id][-30:]
        
        # Формируем контекст
        context = "\n".join([
            f"{'👤 Ты' if m['role']=='user' else '🤖 Я'}: {m['content']}"
            for m in conversations[user_id][-10:]
        ])
        
        system = f"""Ты — AI Code Assistant Pro v{BOT_VERSION}. 
Умный, дружелюбный, профессиональный помощник программиста.

🧠 ТВОИ СПОСОБНОСТИ:
- Писать код любой сложности
- Находить и исправлять баги
- Объяснять сложные концепции просто
- Рефакторинг и оптимизация
- Code review
- Работа над проектами итеративно

📝 ПРАВИЛА:
1. ПОМНИШЬ весь контекст разговора
2. Если просят "доработай" — улучшаешь ПРЕДЫДУЩИЙ код
3. Пишешь ПОЛНЫЙ код, не фрагменты
4. Добавляешь комментарии
5. Используешь современные практики
6. Отвечаешь по делу, но дружелюбно
7. Используй эмодзи для наглядности

💬 ИСТОРИЯ РАЗГОВОРА:
{context}

Отвечай полезно и по существу. Код в блоках ```язык"""

        # Вызов AI
        result = call_gemini(prompt, system=system)
        
        # Сохраняем ответ
        conversations[user_id].append({
            "role": "assistant",
            "content": result,
            "time": datetime.now()
        })
        
        return result

# ============================================================================
# ПОИСК И УТИЛИТЫ
# ============================================================================

def get_crypto_price(symbol: str = "BTC") -> str:
    """Получить курс криптовалюты"""
    try:
        url = f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        price = float(r.json()["data"]["amount"])
        
        # Красивое форматирование
        emoji = "📈" if symbol == "BTC" else "💎" if symbol == "ETH" else "💰"
        return f"{emoji} **{symbol}/USD:** ${price:,.2f}"
    except Exception as e:
        logger.error(f"Crypto error: {e}")
        return f"❌ Не удалось получить курс {symbol}"

def search_web(query: str) -> str:
    """Поиск в интернете"""
    try:
        url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        result = f"🔍 **Поиск:** {query}\n\n"
        
        if data.get("Abstract"):
            result += f"📌 {data['Abstract']}\n"
            if data.get("AbstractURL"):
                result += f"🔗 {data['AbstractURL']}\n"
        
        if data.get("RelatedTopics"):
            result += "\n**Связанное:**\n"
            for topic in data["RelatedTopics"][:3]:
                if isinstance(topic, dict) and "Text" in topic:
                    result += f"• {topic['Text'][:100]}...\n"
        
        return result if len(result) > 40 else "🔍 Ничего не найдено. Попробуй переформулировать!"
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "❌ Ошибка поиска"

def create_project_zip(results: dict, name: str) -> bytes:
    """Создание ZIP архива проекта"""
    buffer = io.BytesIO()
    
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for agent, content in results.items():
            # Извлекаем код
            blocks = re.findall(r'```(\w+)?\n(.*?)```', content, re.DOTALL)
            
            for i, (lang, code) in enumerate(blocks):
                lang = lang or 'txt'
                
                if agent == "backend":
                    path = f"backend/main.{lang}"
                elif agent == "frontend":
                    path = f"frontend/index.{lang}"
                elif agent == "bot":
                    path = f"bot/bot.{lang}"
                elif agent == "devops":
                    path = lang
                else:
                    path = f"{agent}_{i}.{lang}"
                
                zf.writestr(path, code.strip())
        
        # README
        zf.writestr("README.md", f"# {name}\n\nСоздано AI CODE ARMY 🤖\n")
    
    return buffer.getvalue()

def extract_code_from_file(content: bytes, filename: str) -> str:
    """Извлечь код из файла"""
    try:
        text = content.decode('utf-8')
    except:
        text = content.decode('latin-1', errors='ignore')
    
    ext = filename.split('.')[-1].lower()
    lang_map = {'py': 'python', 'js': 'javascript', 'ts': 'typescript', 
                'html': 'html', 'css': 'css', 'json': 'json'}
    lang = lang_map.get(ext, ext)
    
    return f"```{lang}\n{text}\n```"

# ============================================================================
# USER MANAGEMENT
# ============================================================================

def get_user(user_id: int, username: str = None) -> dict:
    """Получить/создать пользователя"""
    if user_id not in user_data:
        user_data[user_id] = {
            "username": username,
            "created": datetime.now(),
            "total_requests": 0,
            "projects": 0,
            "referrals": 0,
            "last_active": datetime.now()
        }
        stats["users_total"] += 1
    else:
        user_data[user_id]["last_active"] = datetime.now()
        if username:
            user_data[user_id]["username"] = username
    return user_data[user_id]

def is_admin(username: str) -> bool:
    return username in ADMINS if username else False

def is_premium(user_id: int, username: str) -> bool:
    return is_admin(username) or user_id in PREMIUM_USERS

def get_today_usage(user_id: int) -> int:
    today = date.today()
    if user_id not in user_usage:
        user_usage[user_id] = {}
    return user_usage[user_id].get(today, 0)

def increment_usage(user_id: int):
    today = date.today()
    if user_id not in user_usage:
        user_usage[user_id] = {}
    user_usage[user_id][today] = user_usage[user_id].get(today, 0) + 1
    get_user(user_id)["total_requests"] += 1
    stats["total_requests"] += 1
    stats["messages_today"] += 1

def can_use(user_id: int, username: str) -> Tuple[bool, str]:
    """Проверка лимитов"""
    if is_admin(username):
        return True, ""
    
    if user_id in PREMIUM_USERS:
        return True, ""
    
    today = get_today_usage(user_id)
    if today >= FREE_DAILY_LIMIT:
        return False, f"""⚠️ **Дневной лимит исчерпан!**

Использовано: {today}/{FREE_DAILY_LIMIT}

🔓 **Получить больше:**
• Premium подписка → /premium
• Пригласить друзей → бонусные запросы

Лимит обновится завтра в 00:00 ⏰"""
    
    return True, ""

def clear_memory(user_id: int):
    if user_id in conversations:
        conversations[user_id] = []

# ============================================================================
# МЕНЮ И КНОПКИ
# ============================================================================

def get_main_menu(is_adm: bool = False) -> types.ReplyKeyboardMarkup:
    """Главное меню"""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("🏗️ Создать проект"),
        types.KeyboardButton("💬 Задать вопрос"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("🧹 Очистить память"),
        types.KeyboardButton("💰 Крипта"),
        types.KeyboardButton("⭐ Premium"),
    ]
    if is_adm:
        buttons.append(types.KeyboardButton("👑 Админ-панель"))
    kb.add(*buttons)
    return kb

def get_inline_actions() -> types.InlineKeyboardMarkup:
    """Inline кнопки быстрых действий"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💻 Написать код", callback_data="action_code"),
        types.InlineKeyboardButton("🔍 Найти баг", callback_data="action_debug"),
        types.InlineKeyboardButton("📖 Объяснить", callback_data="action_explain"),
        types.InlineKeyboardButton("✨ Улучшить", callback_data="action_improve"),
    )
    return kb

# ============================================================================
# КОМАНДЫ
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    user = get_user(user_id, username)
    
    # Реферальная система
    if ' ' in message.text:
        try:
            ref_id = int(message.text.split()[1].replace('ref_', ''))
            if ref_id != user_id and ref_id in user_data:
                user_data[ref_id]["referrals"] += 1
                bot.send_message(ref_id, 
                    "🎉 По вашей ссылке пришёл новый пользователь!\n+3 бонусных запроса!")
        except:
            pass
    
    is_adm = is_admin(username)
    tip = random.choice(WELCOME_TIPS)
    
    welcome = f"""🤖 **AI CODE ARMY v{BOT_VERSION}**
━━━━━━━━━━━━━━━━━━━━━

Привет, **{message.from_user.first_name}**! 👋

Я — команда из **8 ИИ-агентов**:

{AGENTS['architect']['emoji']} Архитектор
{AGENTS['backend']['emoji']} Backend Developer
{AGENTS['frontend']['emoji']} Frontend Developer
{AGENTS['botdev']['emoji']} Bot Developer
{AGENTS['reviewer']['emoji']} Code Reviewer
{AGENTS['security']['emoji']} Security Expert
{AGENTS['devops']['emoji']} DevOps Engineer
{AGENTS['pm']['emoji']} Project Manager

━━━━━━━━━━━━━━━━━━━━━

🎯 **ЧТО МОГУ:**
• Создавать полные проекты (сайты, боты, API)
• Писать и улучшать код
• Находить и исправлять баги
• Объяснять сложные вещи просто
• Помнить наш разговор

📊 **ТВОЙ ТАРИФ:**
{'👑 АДМИН — безлимит!' if is_adm else f'🆓 Free — {FREE_DAILY_LIMIT} запросов/день'}

{tip}

**Используй кнопки ниже или пиши свободно!** 👇"""
    
    bot.send_message(
        message.chat.id, 
        welcome, 
        reply_markup=get_main_menu(is_adm),
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = """📖 **СПРАВКА**
━━━━━━━━━━━━━━━━━━━━━

**🏗️ Создание проекта:**
Нажми кнопку → опиши что нужно → команда из 8 агентов создаст за 3-5 минут!

**💬 Простые вопросы:**
Просто пиши! Я помню весь разговор.

**🔄 Итеративная работа:**
"Доработай код" / "Исправь" / "Добавь функцию"
Я понимаю контекст!

**📁 Работа с файлами:**
Отправь файл с кодом → попроси проверить/улучшить

**🔍 Поиск:**
"Найди информацию о React 19"
"Курс биткоина"

━━━━━━━━━━━━━━━━━━━━━

**КОМАНДЫ:**
/start — Начало
/help — Эта справка
/stats — Статистика
/clear — Очистить память
/premium — Подписка
/project — Создать проект

━━━━━━━━━━━━━━━━━━━━━

**ПРИМЕРЫ ЗАПРОСОВ:**
• "Напиши Telegram бота для заказов"
• "Найди баг в этом коде: [код]"
• "Объясни что такое Docker"
• "Создай лендинг для кофейни"
"""
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    user = get_user(user_id)
    today = get_today_usage(user_id)
    
    status = "👑 Админ" if is_admin(username) else ("⭐ Premium" if user_id in PREMIUM_USERS else "🆓 Free")
    limit = "∞" if is_premium(user_id, username) else str(FREE_DAILY_LIMIT)
    memory = len(conversations.get(user_id, []))
    
    text = f"""📊 **ТВОЯ СТАТИСТИКА**
━━━━━━━━━━━━━━━━━━━━━

👤 **Статус:** {status}
📅 **Сегодня:** {today}/{limit}
📈 **Всего запросов:** {user['total_requests']}
🏗️ **Проектов:** {user['projects']}
💾 **Память:** {memory} сообщений
👥 **Рефералов:** {user['referrals']}

━━━━━━━━━━━━━━━━━━━━━

🌍 **ГЛОБАЛЬНО:**
👥 Пользователей: {stats['users_total']}
📨 Запросов всего: {stats['total_requests']}
✅ Успешных: {stats['successful']}
🏗️ Проектов: {stats['projects_created']}
"""
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    clear_memory(message.from_user.id)
    bot.reply_to(message, "🧹 Память очищена!\n\nНачинаем с чистого листа. Чем могу помочь?")

@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    if is_admin(username):
        bot.send_message(message.chat.id, "👑 Вы **АДМИН** — у вас уже безлимит!", parse_mode="Markdown")
        return
    
    if user_id in PREMIUM_USERS:
        bot.send_message(message.chat.id, "⭐ У вас уже активен **Premium**!", parse_mode="Markdown")
        return
    
    user = get_user(user_id)
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{user_id}"
    
    text = f"""⭐ **AI CODE ARMY PREMIUM**
━━━━━━━━━━━━━━━━━━━━━

**🆓 FREE (сейчас):**
• {FREE_DAILY_LIMIT} запросов/день
• Все функции
• Память разговора

**⭐ PREMIUM — 499₽/мес:**
✅ БЕЗЛИМИТ запросов
✅ Приоритетная обработка
✅ Расширенная память (100 сообщений)
✅ Ранний доступ к новым функциям
✅ Поддержка 24/7

━━━━━━━━━━━━━━━━━━━━━

**💳 КАК ОПЛАТИТЬ:**

1️⃣ Переведи **499₽** на карту:
`{CARD_NUMBER}`

2️⃣ Комментарий: `Premium {user_id}`

3️⃣ Скинь скрин оплаты сюда

4️⃣ Активация за **10 минут**!

━━━━━━━━━━━━━━━━━━━━━

**🎁 ИЛИ БЕСПЛАТНО:**
Пригласи **15 друзей** = вечный Premium!

Твоя ссылка:
`{ref_link}`

Приглашено: **{user['referrals']}/15**
"""
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    username = message.from_user.username or ""
    
    if not is_admin(username):
        return
    
    uptime = datetime.now() - stats["started_at"]
    hours = int(uptime.total_seconds() // 3600)
    mins = int((uptime.total_seconds() % 3600) // 60)
    
    active = sum(1 for uid, usage in user_usage.items() if date.today() in usage)
    
    text = f"""👑 **АДМИН-ПАНЕЛЬ**
━━━━━━━━━━━━━━━━━━━━━

**📊 СТАТИСТИКА:**
⏱ Аптайм: {hours}ч {mins}мин
👥 Всего юзеров: {stats['users_total']}
⭐ Premium: {len(PREMIUM_USERS)}
🟢 Активных сегодня: {active}

**📨 ЗАПРОСЫ:**
Всего: {stats['total_requests']}
✅ Успешно: {stats['successful']}
❌ Ошибок: {stats['errors']}
📅 Сегодня: {stats['messages_today']}

**🏗️ ПРОЕКТЫ:**
Создано: {stats['projects_created']}

━━━━━━━━━━━━━━━━━━━━━

**🏆 ТОП-5 ПОЛЬЗОВАТЕЛЕЙ:**
"""
    
    top = sorted(user_data.items(), key=lambda x: x[1]['total_requests'], reverse=True)[:5]
    for i, (uid, data) in enumerate(top, 1):
        text += f"{i}. @{data.get('username', '?')} — {data['total_requests']} запросов\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ============================================================================
# КНОПКИ МЕНЮ
# ============================================================================

@bot.message_handler(func=lambda m: m.text == "🏗️ Создать проект")
def btn_project(message):
    text = """🏗️ **СОЗДАНИЕ ПРОЕКТА**
━━━━━━━━━━━━━━━━━━━━━

Опиши что нужно создать, и команда из **8 агентов** сделает это!

**ПРИМЕРЫ:**
• "Сайт-визитку для фотографа"
• "Telegram бота для приёма заказов"
• "Landing page для IT-курсов"
• "REST API для мобильного приложения"
• "Интернет-магазин на React"

━━━━━━━━━━━━━━━━━━━━━

✏️ **Опиши свой проект:**"""
    
    msg = bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_project)

def process_project(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    description = message.text.strip()
    
    if len(description) < 10:
        bot.reply_to(message, "❌ Опиши подробнее (минимум 10 символов)")
        return
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err, parse_mode="Markdown")
        return
    
    get_user(user_id, username)
    logger.info(f"🏗️ PROJECT: @{username} — {description[:50]}...")
    
    status_msg = bot.send_message(
        message.chat.id,
        f"🚀 **AI CODE ARMY запущена!**\n\n{random.choice(THINKING_PHRASES)}\n\n⏱ 3-5 минут",
        parse_mode="Markdown"
    )
    
    def update_status(text):
        try:
            bot.edit_message_text(
                f"🚀 **Работаем...**\n\n{text}",
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
        except:
            pass
    
    try:
        results = AIArmy.build_project(user_id, description, update_status)
        
        increment_usage(user_id)
        get_user(user_id)["projects"] += 1
        stats["successful"] += 1
        stats["projects_created"] += 1
        
        project_mode[user_id] = {
            "description": description,
            "results": results,
            "created": datetime.now()
        }
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        # Отправляем результат
        bot.send_message(message.chat.id, f"🎉 **ПРОЕКТ ГОТОВ!**\n\n{random.choice(SUCCESS_PHRASES)}", parse_mode="Markdown")
        
        # PM отчёт
        if "pm" in results:
            send_long(message.chat.id, results["pm"])
        
        # Кнопки для детального просмотра
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🧠 Архитектура", callback_data="view_architect"),
            types.InlineKeyboardButton("💻 Backend", callback_data="view_backend"),
            types.InlineKeyboardButton("🎨 Frontend", callback_data="view_frontend"),
            types.InlineKeyboardButton("🔒 Security", callback_data="view_security"),
            types.InlineKeyboardButton("🚀 DevOps", callback_data="view_devops"),
            types.InlineKeyboardButton("📦 Скачать ZIP", callback_data="download_zip"),
        )
        
        if "bot" in results:
            kb.add(types.InlineKeyboardButton("🤖 Bot код", callback_data="view_bot"))
        
        bot.send_message(
            message.chat.id,
            "📂 **Детали проекта:**",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Project error: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        bot.send_message(
            message.chat.id,
            f"❌ **Ошибка:** {str(e)[:200]}\n\nПопробуй переформулировать или повторить позже.",
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_"))
def handle_view(call):
    user_id = call.from_user.id
    
    if user_id not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    results = project_mode[user_id]["results"]
    part = call.data.replace("view_", "")
    
    names = {
        "architect": "🧠 АРХИТЕКТУРА",
        "backend": "💻 BACKEND",
        "frontend": "🎨 FRONTEND",
        "bot": "🤖 BOT",
        "security": "🔒 БЕЗОПАСНОСТЬ",
        "devops": "🚀 DEVOPS",
        "review": "🔍 CODE REVIEW"
    }
    
    if part in results:
        bot.answer_callback_query(call.id)
        send_long(call.message.chat.id, f"**{names.get(part, part.upper())}**\n\n{results[part]}")
    else:
        bot.answer_callback_query(call.id, "❌ Раздел не найден")

@bot.callback_query_handler(func=lambda c: c.data == "download_zip")
def handle_zip(call):
    user_id = call.from_user.id
    
    if user_id not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    bot.answer_callback_query(call.id, "📦 Создаю архив...")
    
    try:
        project = project_mode[user_id]
        zip_data = create_project_zip(project["results"], f"project_{user_id}")
        
        bot.send_document(
            call.message.chat.id,
            document=zip_data,
            visible_file_name=f"project_{user_id}.zip",
            caption="📦 **Весь проект в одном архиве!**"
        )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {str(e)}")

@bot.message_handler(func=lambda m: m.text == "💬 Задать вопрос")
def btn_question(message):
    bot.send_message(
        message.chat.id,
        "💬 **Задай свой вопрос!**\n\nЯ помню наш разговор и могу:\n\n• Писать код\n• Находить баги\n• Объяснять\n• Улучшать\n\nПросто напиши что нужно! 👇",
        reply_markup=get_inline_actions(),
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def btn_stats(message):
    cmd_stats(message)

@bot.message_handler(func=lambda m: m.text == "🧹 Очистить память")
def btn_clear(message):
    cmd_clear(message)

@bot.message_handler(func=lambda m: m.text == "💰 Крипта")
def btn_crypto(message):
    btc = get_crypto_price("BTC")
    eth = get_crypto_price("ETH")
    
    text = f"""💰 **КУРСЫ КРИПТОВАЛЮТ**
━━━━━━━━━━━━━━━━━━━━━

{btc}
{eth}

━━━━━━━━━━━━━━━━━━━━━
🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}

Напиши "курс SOL" или "курс BTC" для других монет!
"""
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "⭐ Premium")
def btn_premium(message):
    cmd_premium(message)

@bot.message_handler(func=lambda m: m.text == "👑 Админ-панель")
def btn_admin(message):
    cmd_admin(message)

# ============================================================================
# INLINE CALLBACKS
# ============================================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("action_"))
def handle_action(call):
    action = call.data.replace("action_", "")
    
    prompts = {
        "code": "Напиши код. Опиши что нужно:",
        "debug": "Отправь код с ошибкой — найду баг:",
        "explain": "Отправь код — объясню как работает:",
        "improve": "Отправь код — улучшу его:"
    }
    
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"✏️ {prompts.get(action, 'Напиши запрос:')}")

# ============================================================================
# ФАЙЛЫ
# ============================================================================

@bot.message_handler(content_types=['document'])
def handle_file(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err, parse_mode="Markdown")
        return
    
    try:
        file = bot.get_file(message.document.file_id)
        content = bot.download_file(file.file_path)
        filename = message.document.file_name
        
        code = extract_code_from_file(content, filename)
        
        file_cache[user_id] = {
            "filename": filename,
            "code": code,
            "time": datetime.now()
        }
        
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔍 Проверить", callback_data="file_review"),
            types.InlineKeyboardButton("🐛 Найти баги", callback_data="file_debug"),
            types.InlineKeyboardButton("📖 Объяснить", callback_data="file_explain"),
            types.InlineKeyboardButton("✨ Улучшить", callback_data="file_improve"),
        )
        
        bot.reply_to(
            message,
            f"📁 **Файл получен:** `{filename}`\n\nЧто сделать с кодом?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"File error: {e}")
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("file_"))
def handle_file_action(call):
    user_id = call.from_user.id
    
    if user_id not in file_cache:
        bot.answer_callback_query(call.id, "❌ Файл не найден")
        return
    
    action = call.data.replace("file_", "")
    file_data = file_cache[user_id]
    
    prompts = {
        "review": f"Сделай code review этого кода:\n{file_data['code']}",
        "debug": f"Найди все баги и ошибки:\n{file_data['code']}",
        "explain": f"Объясни подробно как работает этот код:\n{file_data['code']}",
        "improve": f"Улучши этот код (производительность, читаемость, best practices):\n{file_data['code']}"
    }
    
    bot.answer_callback_query(call.id, random.choice(THINKING_PHRASES))
    
    try:
        result = SmartAI.chat(user_id, prompts[action])
        increment_usage(user_id)
        stats["successful"] += 1
        send_long(call.message.chat.id, result)
    except Exception as e:
        stats["errors"] += 1
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {str(e)[:200]}")

# ============================================================================
# ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    text = message.text.strip()
    
    if len(text) < 2:
        return
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err, parse_mode="Markdown")
        return
    
    get_user(user_id, username)
    
    # Определяем тип запроса
    text_lower = text.lower()
    is_crypto = any(w in text_lower for w in ['курс', 'цена', 'btc', 'eth', 'bitcoin', 'биткоин'])
    is_search = any(w in text_lower for w in ['найди', 'поищи', 'загугли', 'search'])
    
    logger.info(f"💬 @{username}: {text[:50]}...")
    
    # Показываем что печатаем
    bot.send_chat_action(message.chat.id, 'typing')
    
    status = bot.send_message(message.chat.id, random.choice(THINKING_PHRASES))
    
    try:
        result = ""
        
        # Крипта
        if is_crypto:
            symbol = "BTC"
            if "eth" in text_lower or "эфир" in text_lower:
                symbol = "ETH"
            elif "sol" in text_lower:
                symbol = "SOL"
            result = get_crypto_price(symbol) + "\n\n"
        
        # Поиск
        if is_search:
            query = text_lower
            for word in ['найди', 'поищи', 'загугли', 'в интернете', 'search']:
                query = query.replace(word, '')
            result += search_web(query.strip()) + "\n\n"
        
        # Проверяем есть ли загруженный файл
        if user_id in file_cache:
            file_data = file_cache[user_id]
            if any(w in text_lower for w in ['файл', 'код', 'проверь', 'этот', 'его']):
                text = f"{text}\n\nКод из файла {file_data['filename']}:\n{file_data['code']}"
        
        # AI ответ
        ai_result = SmartAI.chat(user_id, text)
        result += ai_result
        
        increment_usage(user_id)
        stats["successful"] += 1
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        send_long(message.chat.id, result)
        
        # Напоминание о лимите
        if not is_premium(user_id, username):
            left = FREE_DAILY_LIMIT - get_today_usage(user_id)
            if left <= 5 and left > 0:
                bot.send_message(
                    message.chat.id,
                    f"ℹ️ Осталось запросов сегодня: **{left}**",
                    parse_mode="Markdown"
                )
    
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        bot.send_message(
            message.chat.id,
            f"❌ **Ошибка:** {str(e)[:200]}\n\nПопробуй переформулировать!",
            parse_mode="Markdown"
        )

def send_long(chat_id, text: str):
    """Отправка длинных сообщений"""
    MAX = 4000
    
    if len(text) <= MAX:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, text, parse_mode=None)
        return
    
    parts = []
    current = ""
    
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > MAX:
            parts.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    
    if current:
        parts.append(current)
    
    for i, part in enumerate(parts):
        try:
            bot.send_message(chat_id, part, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, part, parse_mode=None)
        
        if i < len(parts) - 1:
            time.sleep(0.5)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    logger.info(f"🚀 AI CODE ARMY v{BOT_VERSION} started!")
    logger.info(f"👑 Admins: {ADMINS}")
    logger.info(f"🤖 Agents: {len(AGENTS)}")
    logger.info(f"💰 Free limit: {FREE_DAILY_LIMIT}/day")
    logger.info(f"🧠 Models: {GEMINI_MODELS}")
    
    # Удаляем webhook
    try:
        bot.remove_webhook()
    except:
        pass
    
    time.sleep(1)
    
    # Запуск с автоперезапуском
    while True:
        try:
            logger.info("📡 Starting polling...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                allowed_updates=["message", "callback_query"]
            )
        except Exception as e:
            logger.error(f"❌ Polling error: {e}")
            time.sleep(15)
