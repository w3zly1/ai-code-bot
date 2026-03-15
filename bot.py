#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, io, time, asyncio, logging, traceback, zipfile
from datetime import date, datetime
from typing import Optional, List, Tuple
from dataclasses import dataclass
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import google.generativeai as genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMINS = set(os.getenv("ADMINS", "").split(","))
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "50"))
DB_PATH = "bot.db"
VERSION = "12.0"

# Много моделей для fallback
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash", 
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-8b",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")
genai.configure(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, total_requests INTEGER DEFAULT 0, total_projects INTEGER DEFAULT 0, mode TEXT DEFAULT 'quality')")
        await db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, description TEXT, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date))")
        await db.commit()
    log.info("✅ DB ready")

async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def get_user(uid: int, uname: str = "") -> dict:
    db = await get_db()
    u = await db.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    u = await u.fetchone()
    if not u:
        await db.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
        await db.commit()
        u = await db.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        u = await u.fetchone()
    await db.close()
    return dict(u)

async def add_message(uid: int, role: str, content: str):
    db = await get_db()
    await db.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (uid, role, content[:2000]))
    await db.commit()
    await db.close()

async def get_context(uid: int) -> str:
    db = await get_db()
    msgs = await db.execute("SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 6", (uid,))
    msgs = await msgs.fetchall()
    await db.close()
    if not msgs:
        return ""
    lines = []
    for m in reversed(msgs):
        role = "👤" if m["role"] == "user" else "🤖"
        lines.append(f"{role} {m['content'][:200]}")
    return "\n".join(lines)

async def inc_usage(uid: int):
    db = await get_db()
    today = date.today().isoformat()
    await db.execute("INSERT INTO daily_usage (user_id, date, count) VALUES (?, ?, 1) ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1", (uid, today))
    await db.execute("UPDATE users SET total_requests = total_requests + 1 WHERE user_id = ?", (uid,))
    await db.commit()
    await db.close()

async def can_use(uid: int, uname: str) -> Tuple[bool, str]:
    if uname in ADMINS:
        return True, ""
    db = await get_db()
    today = date.today().isoformat()
    usage = await db.execute("SELECT count FROM daily_usage WHERE user_id = ? AND date = ?", (uid, today))
    usage = await usage.fetchone()
    await db.close()
    used = usage["count"] if usage else 0
    if used >= FREE_LIMIT:
        return False, f"⚠️ Лимит {FREE_LIMIT}/день исчерпан\n\n🔄 Попробуй завтра!"
    return True, ""

async def save_project(uid: int, desc: str, result: str):
    db = await get_db()
    await db.execute("INSERT INTO projects (user_id, description, result) VALUES (?, ?, ?)", (uid, desc, result))
    await db.execute("UPDATE users SET total_projects = total_projects + 1 WHERE user_id = ?", (uid,))
    await db.commit()
    await db.close()

async def get_last_project(uid: int) -> Optional[dict]:
    db = await get_db()
    p = await db.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
    p = await p.fetchone()
    await db.close()
    return dict(p) if p else None

class RateLimiter:
    def __init__(self, max_per_min: int = 10):
        self.max = max_per_min
        self.timestamps: List[float] = []
        self.lock = asyncio.Lock()
    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 60]
            if len(self.timestamps) >= self.max:
                wait = 60 - (now - self.timestamps[0]) + 1
                log.warning(f"⏸️ Rate limit, ждём {wait:.0f}s")
                await asyncio.sleep(wait)
                self.timestamps = [t for t in self.timestamps if time.time() - t < 60]
            self.timestamps.append(time.time())

rate_limiter = RateLimiter()

async def ai_call(prompt: str, system: str = "", temp: float = 0.7, max_tokens: int = 8000) -> str:
    await rate_limiter.acquire()
    full = f"{system}\n\n{prompt}".strip() if system else prompt
    
    last_error = None
    for model_name in MODELS:
        for attempt in range(3):
            try:
                m = genai.GenerativeModel(model_name)
                r = await asyncio.to_thread(
                    m.generate_content, 
                    full, 
                    generation_config=genai.GenerationConfig(temperature=temp, max_output_tokens=max_tokens)
                )
                txt = getattr(r, "text", "")
                if txt and len(txt.strip()) > 10:
                    return txt.strip()
            except Exception as e:
                last_error = str(e)
                log.warning(f"⚠️ {model_name} attempt {attempt+1}: {e}")
                
                # Если 429 - ждём и пробуем снова
                if "429" in str(e) or "quota" in str(e).lower():
                    wait_match = re.search(r"retry in (\d+)", str(e))
                    wait_time = int(wait_match.group(1)) + 5 if wait_match else 45
                    log.info(f"⏳ Ждём {wait_time}s из-за rate limit...")
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(2)
        
        log.info(f"🔄 Пробую другую модель...")
    
    raise Exception(f"😔 AI перегружен, попробуй через минуту")

@dataclass
class AgentResult:
    name: str
    output: str
    success: bool
    error: Optional[str] = None

class BaseAgent:
    def __init__(self, name: str, emoji: str, system: str):
        self.name = name
        self.emoji = emoji
        self.system = system
    async def run(self, task: str, ctx: dict, mode: str = "quality") -> AgentResult:
        try:
            context = ctx.get("history", "") + "\n\n" + ctx.get("previous", "")
            prompt = f"{task}\n\n{context if context.strip() else ''}"
            temp_map = {"fast": 0.5, "quality": 0.7, "creative": 0.9}
            output = await ai_call(prompt, self.system, temp=temp_map.get(mode, 0.7))
            return AgentResult(name=self.name, output=output, success=True)
        except Exception as e:
            return AgentResult(name=self.name, output="", success=False, error=str(e))

# ═══════════════════════════════════════════════════════════
# УЛУЧШЕННЫЕ ПРОМПТЫ С ЭМОДЗИ
# ═══════════════════════════════════════════════════════════

class AnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__("Analyst", "🔍", """Ты аналитик задач. Разбираешь запрос пользователя.

📋 **ФОРМАТ ОТВЕТА:**

🎯 **Задача**
[Что нужно сделать — 1-2 предложения]

📝 **Требования**
• Требование 1
• Требование 2
• Требование 3

⚠️ **Важно учесть**
• Ограничение 1
• Ограничение 2

Максимум 150 слов. Без воды.""")

class CoderAgent(BaseAgent):
    def __init__(self):
        super().__init__("Coder", "💻", """Ты elite-программист. Пишешь идеальный код.

📋 **ПРАВИЛА:**
✅ Код ПОЛНЫЙ — без TODO, без "добавьте здесь"
✅ Type hints и обработка ошибок
✅ Сразу к делу — без "Конечно, я помогу"
✅ Код в ```блоках с указанием языка

📋 **ФОРМАТ ДЛЯ TELEGRAM:**

Абзацы по 2-3 строки
Пустая строка между блоками

📄 **main.py**
```python
# код здесь
```

🚀 **Запуск**
```bash
python main.py
```

💡 **Примечание**
Краткий комментарий если нужно

📋 **ЭМОДЗИ:**
📄 — файл
🚀 — запуск
💡 — совет
⚠️ — важно
✅ — готово
🔧 — настройка
📦 — установка

Если есть ТЗ от аналитика — следуй ему.
Если замечания ревьюера — исправь.""")

class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__("Reviewer", "🐛", """Ты senior code reviewer.

📋 **ПРОВЕРЯЕШЬ:**
• Баги и ошибки
• Безопасность
• Производительность
• Читаемость

📋 **ФОРМАТ ОТВЕТА:**

🔴 **Критично**
• Проблема 1

🟡 **Желательно**
• Улучшение 1

🟢 **Мелочи**
• Замечание 1

📊 **Оценка: X/10**

📄 **Исправленный код** (если оценка < 7)
```python
# исправленный код
```

Будь конкретным. Без воды.""")

class DocumenterAgent(BaseAgent):
    def __init__(self):
        super().__init__("Documenter", "📝", """Ты техписатель. Создаёшь документацию.

📋 **ФОРМАТ README:**

# 🚀 Название проекта

📝 Краткое описание (1 строка)

## ✨ Возможности
• Функция 1
• Функция 2

## 📦 Установка
```bash
pip install -r requirements.txt
```

## 🚀 Запуск
```bash
python main.py
```

## ⚙️ Настройка
Переменные окружения если нужны

## 📁 Структура
```
project/
├── main.py
└── requirements.txt
```

Кратко и по делу.""")

analyst = AnalystAgent()
coder = CoderAgent()
reviewer = ReviewerAgent()
documenter = DocumenterAgent()

class TaskRouter:
    @staticmethod
    def detect(text: str) -> str:
        t = text.lower()
        if any(x in t for x in ["создай проект", "сделай проект", "полный проект", "с нуля", "целый проект"]):
            return "project"
        if any(x in t for x in ["ошибка", "error", "traceback", "не работает", "баг", "bug", "исправь", "падает"]):
            return "debug"
        if any(x in t for x in ["объясни", "как работает", "почему", "напиши код", "реализуй", "функцию", "скрипт"]) or len(text) > 150:
            return "question"
        return "simple"

task_router = TaskRouter()

class Pipeline:
    @staticmethod
    async def update(msg: Message, text: str):
        try:
            await msg.edit_text(text)
        except:
            pass

    @staticmethod
    async def process(user_input: str, route: str, ctx: dict, mode: str, progress: Message) -> str:
        context = {"history": ctx.get("history", ""), "previous": ""}
        
        if route == "simple":
            await Pipeline.update(progress, "🧠 Думаю...\n\n💻 Пишу ответ... ⏳")
            r = await coder.run(user_input, context, mode)
            return r.output if r.success else f"❌ {r.error}"
        
        if route == "question":
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Анализирую задачу... ⏳\n💻 Ожидает...")
            analysis = await analyst.run(user_input, context, mode)
            if not analysis.success:
                # Fallback на coder напрямую
                await Pipeline.update(progress, "🧠 Работаю...\n\n💻 Пишу ответ... ⏳")
                r = await coder.run(user_input, context, mode)
                return r.output if r.success else f"❌ {r.error}"
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Анализ готов ✅\n💻 Пишу ответ... ⏳")
            context["previous"] = analysis.output
            code = await coder.run(user_input, context, mode)
            return code.output if code.success else f"❌ {code.error}"
        
        if route == "debug":
            await Pipeline.update(progress, "🐛 Дебажу...\n\n🔍 Анализирую ошибку... ⏳\n🐛 Ожидает...\n💻 Ожидает...")
            analysis = await analyst.run(user_input, context, mode)
            await Pipeline.update(progress, "🐛 Дебажу...\n\n🔍 Анализ готов ✅\n🐛 Ищу проблему... ⏳\n💻 Ожидает...")
            context["previous"] = analysis.output if analysis.success else ""
            review = await reviewer.run(user_input, context, mode)
            await Pipeline.update(progress, "🐛 Дебажу...\n\n🔍 Готово ✅\n🐛 Готово ✅\n💻 Исправляю... ⏳")
            context["previous"] = f"{analysis.output if analysis.success else ''}\n\n{review.output if review.success else ''}"
            code = await coder.run(user_input, context, mode)
            return code.output if code.success else f"❌ {code.error}"
        
        if route == "project":
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Пишу ТЗ... ⏳\n💻 Ожидает...\n🐛 Ожидает...\n📝 Ожидает...")
            analysis = await analyst.run(user_input, context, mode)
            if not analysis.success:
                return f"❌ {analysis.error}"
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 ТЗ готово ✅\n💻 Пишу код... ⏳\n🐛 Ожидает...\n📝 Ожидает...")
            context["previous"] = analysis.output
            code = await coder.run(user_input, context, mode)
            if not code.success:
                return f"❌ {code.error}"
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Готово ✅\n💻 Готово ✅\n🐛 Проверяю... ⏳\n📝 Ожидает...")
            context["previous"] = code.output
            review = await reviewer.run("Пров��рь этот код", context, mode)
            final_code = code.output
            if review.success and mode != "fast":
                score = re.search(r"(\d+)/10", review.output)
                if score and int(score.group(1)) < 7:
                    await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Готово ✅\n💻 Улучшаю код... ⏳\n🐛 Готово ✅\n📝 Ожидает...")
                    context["previous"] = f"{code.output}\n\n⚠️ ЗАМЕЧАНИЯ:\n{review.output}"
                    improved = await coder.run("Исправь замечания ревьюера", context, mode)
                    if improved.success:
                        final_code = improved.output
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Готово ✅\n💻 Готово ✅\n🐛 Готово ✅\n📝 Пишу README... ⏳")
            context["previous"] = final_code
            docs = await documenter.run("Создай README для этого проекта", context, mode)
            return f"{docs.output if docs.success else '📝 README не удалось создать'}\n\n---\n\n## 💻 Код\n\n{final_code}"
        
        return "❌ Неизвестный маршрут"

def extract_files(text: str) -> List[Tuple[str, str]]:
    pattern = r"```(\S+)\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    files = []
    counters = {}
    for marker, code in matches:
        code = code.strip()
        if not code or len(code) < 10:
            continue
        if "." in marker and "/" not in marker:
            filename = marker
        elif "/" in marker:
            filename = marker.split("/")[-1]
        else:
            ext_map = {"python": "py", "py": "py", "javascript": "js", "js": "js", "html": "html", "css": "css", "bash": "sh", "dockerfile": "Dockerfile", "json": "json", "yaml": "yml", "sql": "sql"}
            ext = ext_map.get(marker.lower(), "txt")
            filename = f"main.{ext}" if ext == "py" else f"index.{ext}" if ext == "html" else f"app.{ext}"
        if filename in counters:
            base, ext = os.path.splitext(filename)
            counters[filename] += 1
            filename = f"{base}_{counters[filename]}{ext}"
        else:
            counters[filename] = 1
        files.append((filename, code))
    return files

def create_zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files = extract_files(text)
        for fn, code in files:
            z.writestr(fn, code)
        z.writestr("INFO.md", f"# 🚀 AI Project\n\n📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n📁 Файлов: {len(files)}\n\n## 📋 Содержимое\n" + "\n".join(f"• {f}" for f, _ in files))
    buf.seek(0)
    return buf.getvalue()

async def send_long(cid: int, text: str, markup=None):
    text = (text or "").strip() or "🤷 Пустой ответ"
    parts = []
    while len(text) > 3800:
        cut = text.rfind("\n\n", 0, 3800)
        if cut < 1000:
            cut = text.rfind("\n", 0, 3800)
        if cut < 1000:
            cut = 3800
        parts.append(text[:cut])
        text = text[cut:].strip()
    if text:
        parts.append(text)
    for i, part in enumerate(parts):
        rm = markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(cid, part, parse_mode="Markdown", reply_markup=rm)
        except:
            await bot.send_message(cid, part, reply_markup=rm)
        await asyncio.sleep(0.2)

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💬 Вопрос"), KeyboardButton(text="🚀 Проект")],
        [KeyboardButton(text="⚙️ Режим"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🔄 Сброс"), KeyboardButton(text="❓ Помощь")]
    ], resize_keyboard=True)

def mode_kb(current: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅' if current=='fast' else '⚡'} Быстрый", callback_data="mode_fast"), 
         InlineKeyboardButton(text=f"{'✅' if current=='quality' else '🎯'} Качество", callback_data="mode_quality")],
        [InlineKeyboardButton(text=f"{'✅' if current=='creative' else '🎨'} Креатив", callback_data="mode_creative")]
    ])

def project_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Скачать ZIP", callback_data="get_zip"), 
         InlineKeyboardButton(text="✏️ Доработать", callback_data="edit_project")]
    ])

def file_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить", callback_data="file_check"), 
         InlineKeyboardButton(text="🐛 Баги", callback_data="file_bugs")],
        [InlineKeyboardButton(text="📖 Объяснить", callback_data="file_explain"), 
         InlineKeyboardButton(text="✨ Улучшить", callback_data="file_improve")]
    ])

@router.message(Command("start"))
async def cmd_start(msg: Message):
    await get_user(msg.from_user.id, msg.from_user.username or "")
    await msg.answer(f"""🧠 **AI Assistant v{VERSION}**

Мультиагентная система с 4 специализированными AI.

⚡ **Режимы:**
• Быстрый — 1 агент, ~10 сек
• Качество — до 4 агентов, ~30 сек
• Креатив — максимальная свобода

✨ **Что умею:**
• 💬 Отвечать на любые вопросы
• 💻 Писать код на любом языке
• 🚀 Создавать полные проекты
• 🐛 Находить и исправлять баги
• 📖 Объяснять сложные вещи

👇 **Просто напиши что нужно!**""", parse_mode="Markdown", reply_markup=main_kb())

@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("""❓ **Помощь**

📋 **Команды:**
• /start — Начало
• /help — Эта помощь
• /new — Новый диалог
• /mode — Выбрать режим
• /stats — Статистика

💡 **Примеры запросов:**
• _Объясни что такое рекурсия_
• _Напиши функцию сортировки на Python_
• _Создай проект: сайт для кофейни_
• _Исправь ошибку: [вставь код]_

📁 **Файлы:**
Просто отправь файл с кодом — я проанализирую!""", parse_mode="Markdown")

@router.message(Command("new"))
async def cmd_new(msg: Message):
    db = await get_db()
    await db.execute("DELETE FROM messages WHERE user_id = ?", (msg.from_user.id,))
    await db.commit()
    await db.close()
    await msg.answer("🔄 Диалог сброшен!\n\n✨ Начинаем с чистого листа")

@router.message(Command("mode"))
async def cmd_mode(msg: Message):
    u = await get_user(msg.from_user.id)
    current = u.get('mode', 'quality')
    await msg.answer(f"""⚙️ **Текущий режим:** {current}

⚡ **Быстрый**
1 агент, ~10 секунд
Для простых вопросов

🎯 **Качество** 
До 4 агентов, ~30 секунд
Для кода и проектов

🎨 **Креатив**
Максимальная температура
Для творческих задач""", parse_mode="Markdown", reply_markup=mode_kb(current))

@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    u = await get_user(msg.from_user.id)
    db = await get_db()
    today = date.today().isoformat()
    usage = await db.execute("SELECT count FROM daily_usage WHERE user_id = ? AND date = ?", (msg.from_user.id, today))
    usage = await usage.fetchone()
    await db.close()
    used = usage["count"] if usage else 0
    await msg.answer(f"""📊 **Твоя статистика**

📨 Всего запросов: {u['total_requests']}
🚀 Проектов создано: {u['total_projects']}
📅 Сегодня: {used}/{FREE_LIMIT}
⚙️ Режим: {u.get('mode', 'quality')}""", parse_mode="Markdown")

@router.message(F.text == "💬 Вопрос")
async def btn_question(msg: Message):
    await msg.answer("💬 Задай любой вопрос!\n\n_Я понимаю код, ошибки, концепции — всё что угодно_", parse_mode="Markdown")

@router.message(F.text == "🚀 Проект")
async def btn_project(msg: Message, state: FSMContext):
    await msg.answer("""🚀 **Создание проекта**

Опиши что нужно создать:

💡 **Примеры:**
• _Сайт для пиццерии с каталогом и корзиной_
• _Telegram бот для записи к врачу_
• _REST API для списка задач_
• _Парсер товаров с сайта_

👇 **Жду описание:**""", parse_mode="Markdown")
    await state.set_state("project_desc")

@router.message(F.text == "⚙️ Режим")
async def btn_mode(msg: Message):
    await cmd_mode(msg)

@router.message(F.text == "📊 Статистика")
async def btn_stats(msg: Message):
    await cmd_stats(msg)

@router.message(F.text == "🔄 Сброс")
async def btn_reset(msg: Message):
    await cmd_new(msg)

@router.message(F.text == "❓ Помощь")
async def btn_help(msg: Message):
    await cmd_help(msg)

@router.callback_query(F.data.startswith("mode_"))
async def cb_mode(call: CallbackQuery):
    mode = call.data.split("_")[1]
    db = await get_db()
    await db.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode, call.from_user.id))
    await db.commit()
    await db.close()
    names = {"fast": "⚡ Быстрый", "quality": "🎯 Качество", "creative": "🎨 Креатив"}
    await call.answer(f"✅ Выбран: {names[mode]}")
    await call.message.edit_text(f"✅ Режим изменён: **{names[mode]}**", parse_mode="Markdown")

@router.callback_query(F.data == "get_zip")
async def cb_zip(call: CallbackQuery):
    p = await get_last_project(call.from_user.id)
    if not p:
        await call.answer("❌ Сначала создай проект")
        return
    await call.answer("📦 Создаю архив...")
    try:
        data = create_zip(p["result"])
        await bot.send_document(call.message.chat.id, BufferedInputFile(data, filename=f"project_{int(time.time())}.zip"), caption="📦 **Твой проект готов!**\n\n✅ Распакуй и запускай по README", parse_mode="Markdown")
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "edit_project")
async def cb_edit(call: CallbackQuery, state: FSMContext):
    p = await get_last_project(call.from_user.id)
    if not p:
        await call.answer("❌ Нет проекта")
        return
    await call.answer()
    await call.message.answer("✏️ **Что изменить или добавить?**\n\n_Опиши изменения:_", parse_mode="Markdown")
    await state.set_state("edit_project")

@router.callback_query(F.data.startswith("file_"))
async def cb_file(call: CallbackQuery, state: FSMContext):
    action = call.data.split("_")[1]
    data = await state.get_data()
    content = data.get("file_content")
    if not content:
        await call.answer("❌ Файл не найден, отправь заново")
        return
    ok, err = await can_use(call.from_user.id, call.from_user.username or "")
    if not ok:
        await call.answer("❌ Лимит исчерпан")
        return
    await call.answer("⏳ Анализирую...")
    u = await get_user(call.from_user.id)
    mode = u.get("mode", "quality")
    prompts = {
        "check": "🔍 Проверь этот код. Найди проблемы и дай рекомендации.", 
        "bugs": "🐛 Найди ВСЕ баги в этом коде. Дай исправленный код.", 
        "explain": "📖 Объясни простым языком что делает этот код.", 
        "improve": "✨ Улучши этот код. Дай полный улучшенный вариант."
    }
    task = f"{prompts[action]}\n\n```\n{content[:20000]}\n```"
    progress = await call.message.answer("🔄 Анализирую файл...")
    try:
        route = "debug" if action == "bugs" else "question"
        ctx = {"history": await get_context(call.from_user.id)}
        result = await Pipeline.process(task, route, ctx, mode, progress)
        await progress.delete()
        await inc_usage(call.from_user.id)
        await send_long(call.message.chat.id, result)
    except Exception as e:
        await progress.delete()
        await call.message.answer(f"❌ {e}")

@router.message(F.document)
async def on_doc(msg: Message, state: FSMContext):
    try:
        file = await bot.get_file(msg.document.file_id)
        data = await bot.download_file(file.file_path)
        try:
            content = data.read().decode("utf-8")
        except:
            content = data.read().decode("latin-1", errors="ignore")
        if len(content) > 50000:
            content = content[:50000]
        await state.update_data(file_content=content)
        await msg.answer(f"📁 **Файл получен:** `{msg.document.file_name}`\n\n👇 **Что сделать с файлом?**", parse_mode="Markdown", reply_markup=file_kb())
    except Exception as e:
        await msg.answer(f"❌ Не удалось прочитать: {e}")

@router.message(F.text)
async def on_text(msg: Message, state: FSMContext):
    st = await state.get_state()
    if st == "project_desc":
        await state.clear()
        user_input = msg.text
        route = "project"
    elif st == "edit_project":
        await state.clear()
        p = await get_last_project(msg.from_user.id)
        if not p:
            await msg.answer("❌ Нет проекта для редактирования")
            return
        user_input = f"📝 Текущий проект:\n{p['result'][:10000]}\n\n✏️ Изменения:\n{msg.text}"
        route = "project"
    else:
        user_input = msg.text
        route = task_router.detect(user_input)
    
    ok, err = await can_use(msg.from_user.id, msg.from_user.username or "")
    if not ok:
        await msg.answer(err)
        return
    
    u = await get_user(msg.from_user.id, msg.from_user.username or "")
    mode = u.get("mode", "quality")
    emojis = {"simple": "💬", "question": "🤔", "debug": "🐛", "project": "🚀"}
    progress = await msg.answer(f"{emojis.get(route, '🧠')} Думаю...")
    
    try:
        ctx = {"history": await get_context(msg.from_user.id)}
        result = await Pipeline.process(user_input, route, ctx, mode, progress)
        await add_message(msg.from_user.id, "user", msg.text)
        await add_message(msg.from_user.id, "assistant", result[:2000])
        await inc_usage(msg.from_user.id)
        if route == "project":
            await save_project(msg.from_user.id, user_input, result)
        await progress.delete()
        markup = project_kb() if route == "project" else None
        await send_long(msg.chat.id, result, markup)
    except Exception as e:
        log.error(traceback.format_exc())
        await progress.delete()
        await msg.answer(f"❌ {e}\n\n💡 Попробуй /mode fast для быстрого режима")

async def main():
    log.info(f"🚀 AI Assistant v{VERSION}")
    await init_db()
    dp.include_router(router)
    log.info("✅ Бот запущен")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
