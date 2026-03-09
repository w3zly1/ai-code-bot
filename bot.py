#!/usr/bin/env python3
"""
AI CODE ARMY — Рой из 7 ИИ-агентов
Создаёт реальные проекты: сайты, ботов, API
С памятью, поиском, файлами, деплоем
"""

import os, logging, time, json, requests, zipfile, io, re
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
CARD_NUMBER = os.environ.get("CARD_NUMBER", "XXXX")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

ADMINS = {"MAON1K"}
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

FREE_DAILY_LIMIT = 20

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# Хранилища
user_data: Dict[int, dict] = {}
user_usage: Dict[int, dict] = {}
conversations: Dict[int, List[dict]] = {}  # ПАМЯТЬ
project_mode: Dict[int, dict] = {}  # Активные проекты
file_cache: Dict[int, dict] = {}  # Загруженные файлы
stats = {
    "total": 0,
    "success": 0,
    "errors": 0,
    "users": 0,
    "projects": 0,
    "deployed": 0
}

# ============================================================================
# AI AGENTS — 7 СПЕЦИАЛИСТОВ
# ============================================================================

AGENTS = {
    "architect": {
        "name": "🧠 Архитектор",
        "emoji": "🧠",
        "role": """Ты — Lead Software Architect с 15+ годами опыта.

ОБЯЗАННОСТИ:
- Анализ требований клиента
- Проектирование архитектуры (микросервисы, монолит, serverless)
- Выбор технологий и фреймворков
- Создание структуры проекта
- Техническое задание для команды

ТЕХНОЛОГИИ:
- Backend: Python (Flask/FastAPI/Django), Node.js (Express/Nest), Go
- Frontend: React, Vue, Svelte, Next.js, HTML/CSS
- БД: PostgreSQL, MongoDB, Redis, SQLite
- Деплой: Vercel, Railway, Netlify, AWS, Heroku

ФОРМАТ ОТВЕТА:
**Проект:** [название]
**Тип:** [веб-приложение/бот/API/лендинг]
**Стек:**
- Backend: [технология]
- Frontend: [технология]
- БД: [технология]
- Хостинг: [платформа]

**Структура файлов:**
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

**План для команды:**
1. Backend Dev: создать API endpoints
2. Frontend Dev: сверстать UI
3. Bot Dev: интегрировать Telegram (если нужно)
4. Security: проверить уязвимости
5. DevOps: подготовить деплой

Будь конкретным и профессиональным."""
    },
    
    "backend": {
        "name": "💻 Backend Developer",
        "emoji": "💻",
        "role": """Ты — Senior Backend Developer (Python/Node.js).

ОБЯЗАННОСТИ:
- Разработка серверной логики
- REST/GraphQL API
- Работа с БД (SQL/NoSQL)
- Аутентификация и авторизация
- Обработка файлов, сессий
- WebSockets (если нужно)

СТЕК:
- Python: Flask, FastAPI, Django, SQLAlchemy
- Node.js: Express, Nest.js, Prisma
- БД: PostgreSQL, MongoDB, Redis
- ORM/ODM: SQLAlchemy, Mongoose, Prisma

ТРЕБОВАНИЯ К КОДУ:
- Clean code с комментариями
- Обработка ВСЕХ ошибок (try/except)
- Валидация входных данных
- Логирование
- ENV переменные для секретов
- Type hints (Python) / TypeScript
- Документация API

Пиши production-ready код."""
    },
    
    "frontend": {
        "name": "🎨 Frontend Developer",
        "emoji": "🎨",
        "role": """Ты — Senior Frontend Developer.

ОБЯЗАННОСТИ:
- Создание современных UI
- Адаптивная вёрстка (mobile-first)
- Работа с API (fetch/axios)
- Состояние приложения (Context/Redux)
- Анимации и transitions
- Accessibility (a11y)
- SEO оптимизация

СТЕК:
- HTML5, CSS3 (Flexbox, Grid, Custom Properties)
- JavaScript ES6+ / TypeScript
- React, Vue, Svelte
- TailwindCSS, Bootstrap, Styled Components
- Webpack, Vite, Parcel

ТРЕБОВАНИЯ:
- Кроссбраузерность (Chrome, Firefox, Safari, Edge)
- Производительность (<3 сек загрузка)
- Семантическая вёрстка
- ARIA атрибуты
- Красивый современный дизайн

Создавай готовые к продакшену интерфейсы."""
    },
    
    "botdev": {
        "name": "🤖 Bot Developer",
        "emoji": "🤖",
        "role": """Ты — Expert Telegram Bot Developer.

ОБЯЗАННОСТИ:
- Разработка Telegram ботов любой сложности
- Inline кнопки, меню, callback queries
- Webhook / Long Polling
- Обработка медиа (фото, видео, файлы)
- Платежи (Telegram Stars, Stripe)
- Админ-панели
- Интеграция с БД и API

СТЕК:
- Python: python-telegram-bot, aiogram, pyTelegramBotAPI
- Node.js: node-telegram-bot-api, telegraf, grammy
- БД: SQLite, PostgreSQL, MongoDB

ФУНКЦИИ:
- Команды (/start, /help и т.д.)
- FSM (Finite State Machine) для диалогов
- Inline режим
- Callback кнопки
- Реферальная система
- Подписки и платежи

Пиши готовых к запуску ботов с полной документацией."""
    },
    
    "security": {
        "name": "🔒 Security Expert",
        "emoji": "🔒",
        "role": """Ты — Cybersecurity Specialist.

ОБЯЗАННОСТИ:
- Аудит кода на уязвимости
- Защита от атак (SQL injection, XSS, CSRF, RCE)
- Безопасное хранение данных
- Rate limiting
- Input validation и sanitization
- Безопасность API (CORS, headers)
- Аутентификация и авторизация

ПРОВЕРЯЕШЬ:
- SQL injection в запросах
- XSS в пользовательском вводе
- CSRF токены
- Утечки секретов в коде
- Слабые пароли
- Небезопасные зависимости (npm audit, safety)
- Open redirects
- Exposed endpoints

ФОРМАТ:
**Уровень безопасности:** [1-10]/10

**🔴 Критические проблемы:**
- [проблема + место в коде]

**🟡 Предупреждения:**
- [проблема]

**🟢 Рекомендации:**
- [улучшение]

**Исправленный код:**
[безопасная версия]

Будь параноиком, но конструктивным."""
    },
    
    "devops": {
        "name": "🚀 DevOps Engineer",
        "emoji": "🚀",
        "role": """Ты — Senior DevOps Engineer.

ОБЯЗАННОСТИ:
- Деплой на production
- CI/CD пайплайны
- Docker контейнеризация
- Kubernetes (если нужно)
- Мониторинг и логирование
- Автоскейлинг

ПЛАТФОРМЫ:
- Vercel (фронтенд, Next.js, статика)
- Railway (бэкенд, боты, БД)
- Netlify (статика, JAMstack)
- Fly.io (Docker, глобальный деплой)
- GitHub Pages (статика, документация)
- Render (альтернатива)

ВЫДАЁШЬ:
1. **Конфиги:**
   - Dockerfile
   - docker-compose.yml
   - railway.json / vercel.json
   - .github/workflows/deploy.yml (CI/CD)

2. **ENV переменные** (список что нужно)

3. **Пошаговые инструкции** деплоя

4. **Команды для запуска**

Делай так чтобы работало из коробки."""
    },
    
    "pm": {
        "name": "📊 Project Manager",
        "emoji": "📊",
        "role": """Ты — Technical Project Manager.

ОБЯЗАННОСТИ:
- Координация команды
- Трекинг прогресса
- Коммуникация с клиентом
- Сбор финального результата
- Документация
- Следующие шаги

ФОРМАТ ФИНАЛЬНОГО ОТЧЁТА:

**📋 ПРОЕКТ: [название]**

**✅ СТАТУС: [X]% готов**

**ВЫПОЛНЕНО:**
✅ Архитектура спроектирована
✅ Backend API создан
✅ Frontend UI готов
✅ [Telegram бот создан] (если был)
✅ Безопасность проверена
✅ Конфиги деплоя готовы

**📦 РЕЗУЛЬТАТЫ:**

**Backend:**
- Файлы: [список]
- Endpoints: [список API]
- БД схема: [описание]

**Frontend:**
- Файлы: [список]
- Страницы: [список]
- Компоненты: [список]

**Деплой:**
- Backend: [платформа + инструкция]
- Frontend: [платформа + инструкция]

**🔗 ССЫЛКИ:**
- Демо: [URL если задеплоено]
- Репозиторий: [GitHub URL если создан]
- Документация: [README]

**📌 СЛЕДУЮЩИЕ ШАГИ:**
1. [что делать дальше]
2. [...]

**❓ НУЖНО ОТ КЛИЕНТА:**
- [вопросы если есть]

**⏱ ЗАТРАЧЕННОЕ ВРЕМЯ:** [оценка]

Будь организованным, чётким, профессиональным."""
    },
    
    "reviewer": {
        "name": "🔍 Code Reviewer",
        "emoji": "🔍",
        "role": """Ты — Senior Code Reviewer.

ОБЯЗАННОСТИ:
- Детальный анализ кода
- Проверка best practices
- Поиск багов и code smells
- Предложения по улучшению
- Проверка производительности

ПРОВЕРЯЕШЬ:
- Читаемость кода
- DRY принцип (Don't Repeat Yourself)
- SOLID принципы
- Нейминг переменных и функций
- Комментарии и документация
- Обработка ошибок
- Тесты (если есть)
- Performance bottlenecks

ФОРМАТ:
**Общая оценка:** [1-10]/10

**👍 Что сделано хорошо:**
- [пункт]

**⚠️ Проблемы:**
- [проблема + строка кода]

**💡 Рекомендации:**
- [улучшение + пример кода]

**🐛 Потенциальные баги:**
- [баг + как исправить]

**Улучшенная версия:**
[рефакторенный код]

Будь конструктивным и помогающим."""
    }
}

# ============================================================================
# AI ARMY — КОМАНДА АГЕНТОВ
# ============================================================================

class AIArmy:
    """Рой из 7 ИИ-агентов с памятью"""
    
    @staticmethod
    def call_agent(agent_name: str, task: str, context: str = "", 
                   memory: List[dict] = None) -> str:
        """Вызов одного агента с учётом памяти"""
        
        if agent_name not in AGENTS:
            raise ValueError(f"Unknown agent: {agent_name}")
        
        agent = AGENTS[agent_name]
        
        # Формируем промпт
        system = f"{agent['role']}\n\n"
        
        # Добавляем контекст проекта
        if context:
            system += f"КОНТЕКСТ ПРОЕКТА:\n{context}\n\n"
        
        # Добавляем память (последние 5 сообщений)
        if memory:
            memory_text = "\n".join([
                f"{m['agent']}: {m['content'][:200]}..."
                for m in memory[-5:]
            ])
            system += f"ИСТОРИЯ РАБОТЫ КОМАНДЫ:\n{memory_text}\n\n"
        
        full_prompt = f"{system}ТВОЯ ЗАДАЧА:\n{task}"
        
        try:
            # Используем thinking mode для сложных задач
            use_thinking = agent_name in ["architect", "backend", "security"]
            
            model_name = "gemini-2.0-flash-thinking-exp-1219" if use_thinking else "gemini-2.0-flash-exp"
            model = genai.GenerativeModel(model_name=model_name)
            
            response = model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=8000
                )
            )
            
            return response.text
        
        except Exception as e:
            logger.error(f"Agent {agent_name} error: {e}")
            raise
    
    @staticmethod
    def build_project(user_id: int, description: str, callback) -> dict:
        """Полный цикл создания проекта командой"""
        
        project_memory = []  # Память команды
        results = {}
        
        # Определяем какие агенты нужны
        needs_bot = any(w in description.lower() for w in ['бот', 'telegram', 'тг'])
        
        def add_to_memory(agent_name: str, content: str):
            project_memory.append({
                "agent": AGENTS[agent_name]["name"],
                "content": content,
                "time": datetime.now()
            })
        
        # ШАГ 1: Архитектор
        callback(f"{AGENTS['architect']['emoji']} Архитектор проектирует систему...")
        arch_result = AIArmy.call_agent("architect", description)
        results["architect"] = arch_result
        add_to_memory("architect", arch_result)
        time.sleep(2)
        
        # ШАГ 2: Backend
        callback(f"{AGENTS['backend']['emoji']} Backend Developer пишет серверную логику...")
        backend_task = "Создай полный backend код согласно архитектуре. Готовый к запуску."
        backend_result = AIArmy.call_agent("backend", backend_task, 
                                          context=arch_result, memory=project_memory)
        results["backend"] = backend_result
        add_to_memory("backend", backend_result)
        time.sleep(2)
        
        # ШАГ 3: Frontend
        callback(f"{AGENTS['frontend']['emoji']} Frontend Developer создаёт интерфейс...")
        frontend_task = "Создай полный frontend код с дизайном. Адаптивный, современный."
        context_for_frontend = f"Архитектура:\n{arch_result}\n\nBackend API:\n{backend_result}"
        frontend_result = AIArmy.call_agent("frontend", frontend_task,
                                           context=context_for_frontend, memory=project_memory)
        results["frontend"] = frontend_result
        add_to_memory("frontend", frontend_result)
        time.sleep(2)
        
        # ШАГ 4: Bot (если нужен)
        if needs_bot:
            callback(f"{AGENTS['botdev']['emoji']} Bot Developer создаёт Telegram бота...")
            bot_task = "Создай полный код Telegram бота. Готовый к запуску на Railway."
            full_context = f"Архитектура:\n{arch_result}\n\nBackend:\n{backend_result}"
            bot_result = AIArmy.call_agent("botdev", bot_task,
                                          context=full_context, memory=project_memory)
            results["bot"] = bot_result
            add_to_memory("botdev", bot_result)
            time.sleep(2)
        
        # ШАГ 5: Code Review
        callback(f"{AGENTS['reviewer']['emoji']} Code Reviewer проверяет качество...")
        review_task = "Проверь весь код. Найди проблемы, предложи улучшения."
        all_code = f"Backend:\n{backend_result}\n\nFrontend:\n{frontend_result}"
        if needs_bot and "bot" in results:
            all_code += f"\n\nBot:\n{results['bot']}"
        review_result = AIArmy.call_agent("reviewer", review_task,
                                         context=all_code, memory=project_memory)
        results["review"] = review_result
        add_to_memory("reviewer", review_result)
        time.sleep(2)
        
        # ШАГ 6: Security
        callback(f"{AGENTS['security']['emoji']} Security Expert проверяет безопасность...")
        security_task = "Проверь код на уязвимости. Дай исправленные версии."
        security_result = AIArmy.call_agent("security", security_task,
                                           context=all_code, memory=project_memory)
        results["security"] = security_result
        add_to_memory("security", security_result)
        time.sleep(2)
        
        # ШАГ 7: DevOps
        callback(f"{AGENTS['devops']['emoji']} DevOps готовит деплой конфиги...")
        devops_task = "Создай все конфиги для деплоя (Railway, Vercel). Инструкции."
        devops_result = AIArmy.call_agent("devops", devops_task,
                                         context=all_code, memory=project_memory)
        results["devops"] = devops_result
        add_to_memory("devops", devops_result)
        time.sleep(2)
        
        # ШАГ 8: Project Manager собирает
        callback(f"{AGENTS['pm']['emoji']} Project Manager готовит финальный отчёт...")
        pm_task = "Собери финальный отчёт для клиента. Что готово, ссылки, следующие шаги."
        pm_context = "\n\n".join([f"{k.upper()}:\n{v}" for k, v in results.items()])
        pm_result = AIArmy.call_agent("pm", pm_task,
                                     context=pm_context, memory=project_memory)
        results["pm"] = pm_result
        
        return results

# ============================================================================
# ПРОСТОЙ AI С ПАМЯТЬЮ (для обычных вопросов)
# ============================================================================

class SmartAI:
    @staticmethod
    def call_with_memory(user_id: int, prompt: str, use_thinking: bool = False) -> str:
        """AI с памятью разговора для простых вопросов"""
        
        if user_id not in conversations:
            conversations[user_id] = []
        
        # Добавляем в память
        conversations[user_id].append({
            "role": "user",
            "content": prompt,
            "time": datetime.now()
        })
        
        # Ограничиваем (последние 30 сообщений)
        if len(conversations[user_id]) > 30:
            conversations[user_id] = conversations[user_id][-30:]
        
        # Формируем контекст
        context = "\n".join([
            f"{'Пользователь' if m['role']=='user' else 'Ассистент'}: {m['content']}"
            for m in conversations[user_id][-10:]
        ])
        
        system = f"""Ты — AI Code Assistant Pro.

ПРАВИЛА:
- ПОМНИШЬ весь контекст разговора
- Работаешь итеративно (доработки, улучшения)
- Пишешь ПОЛНЫЙ код, не фрагменты
- Всегда комментарии
- Python 3.12+, modern JS/TS

МОЖЕШЬ:
- Писать код
- Находить баги
- Объяснять
- Рефакторинг
- Поиск информации

КОНТЕКСТ РАЗГОВОРА:
{context}

Отвечай кратко. Код в блоках ```."""

        try:
            model_name = "gemini-2.0-flash-thinking-exp-1219" if use_thinking else "gemini-2.0-flash-exp"
            model = genai.GenerativeModel(model_name=model_name)
            
            response = model.generate_content(
                f"{system}\n\nНОВЫЙ ЗАПРОС:\n{prompt}",
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=8000
                )
            )
            
            result = response.text
            
            # Сохраняем ответ
            conversations[user_id].append({
                "role": "assistant",
                "content": result,
                "time": datetime.now()
            })
            
            return result
        
        except Exception as e:
            logger.error(f"AI error: {e}")
            raise

# ============================================================================
# ПОИСК И КРИПТА
# ============================================================================

def get_crypto_price(symbol: str = "BTC") -> str:
    try:
        url = f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        price = data["data"]["amount"]
        return f"💰 **{symbol}/USD**: ${float(price):,.2f}"
    except:
        return f"❌ Ошибка получения курса {symbol}"

def search_web(query: str) -> str:
    """Поиск через DuckDuckGo"""
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
        
        return result if len(result) > 40 else "🔍 Ничего не найдено"
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "❌ Ошибка поиска"

# ============================================================================
# ФАЙЛЫ
# ============================================================================

def extract_code_from_file(file_content: bytes, filename: str) -> str:
    """Извлекает код из файла"""
    try:
        # Определяем кодировку
        text = file_content.decode('utf-8')
        return f"```{get_file_extension(filename)}\n{text}\n```"
    except:
        try:
            text = file_content.decode('latin-1')
            return f"```{get_file_extension(filename)}\n{text}\n```"
        except:
            return "❌ Не удалось прочитать файл"

def get_file_extension(filename: str) -> str:
    ext = filename.split('.')[-1].lower()
    lang_map = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'html': 'html',
        'css': 'css',
        'json': 'json',
        'md': 'markdown'
    }
    return lang_map.get(ext, ext)

# ============================================================================
# СОЗДАНИЕ ZIP
# ============================================================================

def create_project_zip(results: dict, project_name: str) -> bytes:
    """Создаёт ZIP архив проекта"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Извлекаем код из результатов
        for agent_name, content in results.items():
            # Ищем блоки кода
            code_blocks = re.findall(r'```(\w+)?\n(.*?)```', content, re.DOTALL)
            
            for i, (lang, code) in enumerate(code_blocks):
                if not lang:
                    lang = 'txt'
                
                # Определяем путь файла
                if agent_name == "backend":
                    filepath = f"backend/main.{lang}"
                elif agent_name == "frontend":
                    filepath = f"frontend/index.{lang}"
                elif agent_name == "bot":
                    filepath = f"bot/bot.{lang}"
                elif agent_name == "devops":
                    filepath = f"{lang}"
                else:
                    filepath = f"{agent_name}/{i}.{lang}"
                
                zf.writestr(filepath, code.strip())
        
        # README
        readme = f"""# {project_name}

Проект создан AI CODE ARMY

## Структура

- `backend/` — серверная логика
- `frontend/` — интерфейс
- `bot/` — Telegram бот (если есть)

## Запуск

См. инструкции в результатах от DevOps Engineer.

---

Создано с помощью AI CODE ARMY 🤖
"""
        zf.writestr("README.md", readme)
    
    return zip_buffer.getvalue()

# ============================================================================
# USER MANAGEMENT
# ============================================================================

def get_user(user_id: int, username: str = None) -> dict:
    if user_id not in user_data:
        user_data[user_id] = {
            "username": username,
            "created": datetime.now(),
            "total": 0,
            "referrals": 0,
            "projects": 0
        }
        stats["users"] += 1
    return user_data[user_id]

def is_admin(username: str) -> bool:
    return username in ADMINS

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
    get_user(user_id)["total"] += 1

def can_use(user_id: int, username: str) -> Tuple[bool, str]:
    if is_admin(username):
        return True, ""
    if user_id in PREMIUM_USERS:
        return True, ""
    today = get_today_usage(user_id)
    if today >= FREE_DAILY_LIMIT:
        return False, f"⚠️ Лимит ({FREE_DAILY_LIMIT}/день)\n\n⭐ /premium"
    return True, ""

def clear_memory(user_id: int):
    if user_id in conversations:
        conversations[user_id] = []

# ============================================================================
# МЕНЮ
# ============================================================================

def get_menu(is_admin=False):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("🏗️ Создать проект"),
        types.KeyboardButton("💬 Простой вопрос"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("🧹 Очистить память"),
        types.KeyboardButton("⭐ Premium"),
    ]
    if is_admin:
        buttons.insert(3, types.KeyboardButton("👑 Админ"))
    keyboard.add(*buttons)
    return keyboard

# ============================================================================
# КОМАНДЫ
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    user = get_user(user_id, username)
    
    # Реферальная система
    if message.text.startswith('/start ref_'):
        try:
            ref_id = int(message.text.split('_')[1])
            if ref_id != user_id and ref_id in user_data:
                user_data[ref_id]["referrals"] += 1
                bot.send_message(ref_id, "🎉 По вашей ссылке зарегистрировался пользователь!\n+3 бесплатных запроса")
        except:
            pass
    
    is_adm = is_admin(username)
    
    welcome = f"""🤖 **AI CODE ARMY**
Рой из 7 ИИ-агентов

Привет, {message.from_user.first_name}!

**МЫ СОЗДАЁМ:**
🌐 Сайты (Vercel/Netlify)
🤖 Telegram ботов (Railway)
⚙️ Backend API (Flask/FastAPI)
🎨 Современные UI (React/Vue)
📦 Готовые проекты (ZIP)

**КОМАНДА:**
{AGENTS['architect']['emoji']} Архитектор
{AGENTS['backend']['emoji']} Backend Dev
{AGENTS['frontend']['emoji']} Frontend Dev
{AGENTS['botdev']['emoji']} Bot Developer
{AGENTS['reviewer']['emoji']} Code Reviewer
{AGENTS['security']['emoji']} Security Expert
{AGENTS['devops']['emoji']} DevOps Engineer
{AGENTS['pm']['emoji']} Project Manager

**ОСОБЕННОСТИ:**
✅ Память разговора
✅ Итеративная работа
✅ Поиск в интернете
✅ Работа с файлами
✅ Курсы криптовалют

**ТАРИФЫ:**
🆓 {FREE_DAILY_LIMIT} запросов/день
⭐ Premium: безлимит

{"👑 **ВЫ АДМИН** — безлимит!" if is_adm else ""}

Используй кнопки ниже! 👇"""
    
    bot.send_message(message.chat.id, welcome, reply_markup=get_menu(is_adm), parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = """📖 **Справка**

**Создание проекта:**
🏗️ Нажми кнопку "Создать проект"
Опиши что нужно → команда из 7 агентов создаст за 3-5 минут

**Простые вопросы:**
💬 Помощь с кодом, объяснения, дебаг

**Память:**
Бот помнит весь разговор. Можешь писать "доработай", "исправь" и он поймёт контекст

**Файлы:**
Отправь файл с кодом → бот проанализирует

**Поиск:**
"Найди курс биткоина"
"Поищи информацию о React 19"

**Команды:**
/start — начало
/help — справка
/stats — статистика
/clear — очистить память
/premium — Premium подписка
"""
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🏗️ Создать проект")
def btn_create_project(message):
    msg = bot.send_message(
        message.chat.id,
        "🏗️ **Создание проекта**\n\n"
        "Опишите что создать:\n\n"
        "**Примеры:**\n"
        "• Сайт-визитку для кофейни\n"
        "• Telegram бота для приёма заказов\n"
        "• Landing page для IT курсов\n"
        "• Интернет-магазин на React\n"
        "• API для мобильного приложения\n\n"
        "Команда создаст за 3-5 минут!",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_project)

def process_project(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    description = message.text.strip()
    
    if len(description) < 10:
        bot.reply_to(message, "❌ Опишите подробнее (мин. 10 символов)")
        return
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err)
        return
    
    get_user(user_id, username)
    logger.info(f"PROJECT: @{username} — {description[:50]}...")
    
    status_msg = bot.send_message(
        message.chat.id,
        "⚙️ **AI CODE ARMY запущена!**\n\n"
        "Команда начала работу...\n"
        "⏱ 3-5 минут",
        parse_mode="Markdown"
    )
    
    def update_status(text):
        try:
            bot.edit_message_text(
                f"⚙️ **Работаем...**\n\n{text}",
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
        except:
            pass
    
    try:
        # Запуск команды
        results = AIArmy.build_project(user_id, description, update_status)
        
        increment_usage(user_id)
        get_user(user_id)["projects"] += 1
        stats["success"] += 1
        stats["projects"] += 1
        
        # Сохраняем проект
        project_mode[user_id] = {
            "description": description,
            "results": results,
            "created": datetime.now()
        }
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        # Отправляем результаты
        bot.send_message(message.chat.id, "✅ **ПРОЕКТ ГОТОВ!**", parse_mode="Markdown")
        
        # PM отчёт (главное)
        if "pm" in results:
            send_long(message.chat.id, f"📊 **ОТЧЁТ**\n\n{results['pm']}")
        
        # Остальное по кнопкам
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("📋 Архитектура", callback_data="show_architect"),
            types.InlineKeyboardButton("💻 Backend", callback_data="show_backend"),
            types.InlineKeyboardButton("🎨 Frontend", callback_data="show_frontend"),
            types.InlineKeyboardButton("🔒 Security", callback_data="show_security"),
            types.InlineKeyboardButton("🚀 DevOps", callback_data="show_devops"),
            types.InlineKeyboardButton("📦 Скачать ZIP", callback_data="download_zip"),
        )
        
        if "bot" in results:
            keyboard.add(types.InlineKeyboardButton("🤖 Bot код", callback_data="show_bot"))
        
        bot.send_message(
            message.chat.id,
            "💡 **Действия:**",
            reply_markup=keyboard
        )
        
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Project error: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)[:200]}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_"))
def handle_show_callbacks(call):
    user_id = call.from_user.id
    
    if user_id not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    results = project_mode[user_id]["results"]
    
    part = call.data.replace("show_", "")
    
    titles = {
        "architect": "🧠 АРХИТЕКТУРА",
        "backend": "💻 BACKEND КОД",
        "frontend": "🎨 FRONTEND КОД",
        "bot": "🤖 BOT КОД",
        "security": "🔒 БЕЗОПАСНОСТЬ",
        "devops": "🚀 ДЕПЛОЙ"
    }
    
    if part in results:
        bot.answer_callback_query(call.id)
        send_long(call.message.chat.id, f"**{titles.get(part, part.upper())}**\n\n{results[part]}")
    else:
        bot.answer_callback_query(call.id, "❌ Раздел не найден")

@bot.callback_query_handler(func=lambda call: call.data == "download_zip")
def handle_download_zip(call):
    user_id = call.from_user.id
    
    if user_id not in project_mode:
        bot.answer_callback_query(call.id, "❌ Проект не найден")
        return
    
    bot.answer_callback_query(call.id, "📦 Создаю ZIP...")
    
    try:
        project = project_mode[user_id]
        project_name = f"project_{user_id}"
        
        zip_data = create_project_zip(project["results"], project_name)
        
        bot.send_document(
            call.message.chat.id,
            document=zip_data,
            visible_file_name=f"{project_name}.zip",
            caption="📦 Весь проект в одном архиве"
        )
    except Exception as e:
        logger.error(f"ZIP error: {e}")
        bot.send_message(call.message.chat.id, f"❌ Ошибка создания ZIP: {str(e)}")

@bot.message_handler(func=lambda m: m.text == "💬 Простой вопрос")
def btn_simple(message):
    bot.send_message(
        message.chat.id,
        "💬 Задайте вопрос:\n\n"
        "• Помощь с кодом\n"
        "• Объяснение\n"
        "• Дебаг\n"
        "• Поиск информации"
    )

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def btn_stats(message):
    cmd_stats(message)

@bot.message_handler(func=lambda m: m.text == "🧹 Очистить память")
def btn_clear(message):
    cmd_clear(message)

@bot.message_handler(func=lambda m: m.text == "⭐ Premium")
def btn_premium(message):
    cmd_premium(message)

@bot.message_handler(func=lambda m: m.text == "👑 Админ")
def btn_admin(message):
    cmd_admin(message)

@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    if is_admin(username):
        bot.send_message(message.chat.id, "👑 Админ — безлимит!")
        return
    
    if user_id in PREMIUM_USERS:
        bot.send_message(message.chat.id, "✅ Premium активен!")
        return
    
    user = get_user(user_id)
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{user_id}"
    
    msg = f"""⭐ **AI CODE ARMY Premium**

**Premium — 499₽/мес:**
✅ БЕЗЛИМИТ проектов
✅ Приоритет
✅ Расширенная команда
✅ Автодеплой GitHub
✅ Поддержка 24/7

**Оплата:**
`{CARD_NUMBER}`
Комментарий: `Premium {user_id}`

Скрин → активация 10 мин

**Или 15 друзей:**
{ref_link}
Рефералов: {user['referrals']}/15"""
    
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    user = get_user(user_id)
    today = get_today_usage(user_id)
    
    status = "👑 Админ" if is_admin(username) else ("⭐ Premium" if user_id in PREMIUM_USERS else "🆓 Free")
    memory = len(conversations.get(user_id, []))
    
    text = f"""📊 **Статистика**

Статус: {status}
Сегодня: {today}/{FREE_DAILY_LIMIT if not is_admin(username) else '∞'}
Всего: {user['total']}
Проектов: {user['projects']}
Память: {memory} сообщений
Рефералов: {user['referrals']}

**Глобально:**
Проектов: {stats['projects']}"""
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    clear_memory(message.from_user.id)
    bot.reply_to(message, "🧹 Память очищена!")

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    username = message.from_user.username or ""
    
    if not is_admin(username):
        return
    
    total_users = len(user_data)
    premium = len(PREMIUM_USERS)
    active = len([u for u, usage in user_usage.items() if date.today() in usage])
    
    text = f"""👑 **АДМИН-ПАНЕЛЬ**

**Пользователи:**
Всего: {total_users}
Premium: {premium}
Активных: {active}

**Запросы:**
Всего: {stats['total']}
Успешно: {stats['success']}
Ошибок: {stats['errors']}

**Проекты:**
Создано: {stats['projects']}

**Топ:**"""
    
    top = sorted(user_data.items(), key=lambda x: x[1]['total'], reverse=True)[:5]
    for i, (uid, data) in enumerate(top, 1):
        text += f"\n{i}. @{data.get('username', '?')} — {data['total']} ({data.get('projects', 0)} проектов)"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ============================================================================
# ОБРАБОТКА ФАЙЛОВ
# ============================================================================

@bot.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err)
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        filename = message.document.file_name
        code = extract_code_from_file(downloaded_file, filename)
        
        # Сохраняем в кеш
        file_cache[user_id] = {
            "filename": filename,
            "code": code,
            "time": datetime.now()
        }
        
        bot.reply_to(
            message,
            f"📁 Файл `{filename}` получен!\n\n"
            "Что сделать?\n"
            "• 'Проверь этот код'\n"
            "• 'Найди баги'\n"
            "• 'Объясни что делает'\n"
            "• 'Улучши код'",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"File error: {e}")
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

# ============================================================================
# ОБРАБОТКА ТЕКСТА
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    text = message.text.strip()
    
    if len(text) < 3:
        return
    
    can, err = can_use(user_id, username)
    if not can:
        bot.reply_to(message, err)
        return
    
    get_user(user_id, username)
    
    # Определяем тип
    is_code = any(w in text.lower() for w in ['напиши', 'создай', 'код', 'функци', 'класс', 'скрипт'])
    is_crypto = any(w in text.lower() for w in ['курс', 'цена', 'bitcoin', 'btc', 'eth', 'крипто'])
    is_search = 'найди' in text.lower() or 'поищи' in text.lower()
    has_file = user_id in file_cache
    
    logger.info(f"@{username}: {text[:50]}...")
    stats["total"] += 1
    
    status = bot.send_message(message.chat.id, "⚙️ Обрабатываю...")
    
    try:
        result = ""
        
        # Крипта
        if is_crypto:
            symbol = "BTC"
            if "eth" in text.lower():
                symbol = "ETH"
            elif "sol" in text.lower():
                symbol = "SOL"
            result = get_crypto_price(symbol) + "\n\n"
        
        # Поиск
        if is_search:
            query = text.replace("найди", "").replace("поищи", "").replace("в интернете", "").strip()
            result += search_web(query) + "\n\n"
        
        # Если есть загруженный файл и запрос про него
        if has_file and any(w in text.lower() for w in ['файл', 'код', 'проверь', 'найди', 'объясни', 'улучши']):
            file_data = file_cache[user_id]
            text = f"{text}\n\nКод из файла {file_data['filename']}:\n{file_data['code']}"
        
        # AI ответ с памятью
        ai_result = SmartAI.call_with_memory(user_id, text, use_thinking=is_code)
        result += ai_result
        
        increment_usage(user_id)
        stats["success"] += 1
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        send_long(message.chat.id, result)
        
        # Reminder
        if not is_admin(username) and user_id not in PREMIUM_USERS:
            left = FREE_DAILY_LIMIT - get_today_usage(user_id)
            if left <= 3:
                bot.send_message(message.chat.id, f"ℹ️ Осталось: {left}")
        
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, status.message_id)
        except:
            pass
        
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)[:200]}")

def send_long(chat_id, text):
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
            bot.send_message(chat_id, part, parse_mode=None)
        time.sleep(0.3)

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    logger.info("🚀 AI CODE ARMY started!")
    logger.info(f"👑 Admins: {ADMINS}")
    logger.info(f"🤖 Agents: {len(AGENTS)}")
    logger.info(f"💰 Free limit: {FREE_DAILY_LIMIT}/day")
    
    # Удаляем webhook
    bot.remove_webhook()
    time.sleep(1)
    
    # Запуск
    while True:
        try:
            logger.info("Starting polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(15)
