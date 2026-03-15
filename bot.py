#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 Мультиагентный AI Telegram Bot v10.0
Railway: добавь переменные TELEGRAM_TOKEN, GEMINI_API_KEY, ADMINS (опционально)
Procfile: worker: python bot.py
"""

import os, re, io, time, asyncio, logging, traceback, zipfile, sqlite3
from datetime import date, datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from contextlib import asynccontextmanager

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import google.generativeai as genai

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMINS = set(os.getenv("ADMINS", "").split(","))
FREE_LIMIT = int(os.getenv("FREE_LIMIT", "50"))
DB_PATH = "bot.db"
VERSION = "10.0"

MODELS = {
    "fast": "models/gemini-2.0-flash",
    "quality": "models/gemini-2.5-flash",
    "creative": "models/gemini-2.5-flash"
}

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("bot")

# ═══════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════

genai.configure(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════

async def init_db():
    """Инициализация SQLite базы"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_requests INTEGER DEFAULT 0,
                total_projects INTEGER DEFAULT 0,
                mode TEXT DEFAULT 'quality'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                description TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER,
                date TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        """)
        await db.commit()
    log.info("✅ База данных инициализирована")

@asynccontextmanager
async def get_db():
    """Context manager для работы с БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def get_user(user_id: int, username: str = "") -> dict:
    """Получить или создать пользователя"""
    async with get_db() as db:
        user = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await user.fetchone()
        if not user:
            await db.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            await db.commit()
            user = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = await user.fetchone()
        return dict(user)

async def add_message(user_id: int, role: str, content: str):
    """Добавить сообщение в историю"""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content[:2000])
        )
        await db.commit()
        # Суммаризация если > 10 сообщений
        count = await db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE user_id = ?",
            (user_id,)
        )
        count = (await count.fetchone())["cnt"]
        if count > 10:
            await summarize_old_messages(user_id)

async def summarize_old_messages(user_id: int):
    """Сжатие старых сообщений для экономии контекста"""
    async with get_db() as db:
        old_msgs = await db.execute(
            "SELECT content FROM messages WHERE user_id = ? ORDER BY id ASC LIMIT 5",
            (user_id,)
        )
        old_msgs = await old_msgs.fetchall()
        if not old_msgs:
            return
        combined = "\n".join([m["content"][:300] for m in old_msgs])
        try:
            summary = await ai_call(
                f"Кратко сожми эту историю диалога в 2-3 предложения:\n\n{combined}",
                "Ты суммаризатор. Выдели только ключевые факты.",
                temp=0.3,
                max_tokens=200
            )
            await db.execute(
                "UPDATE messages SET summary = ? WHERE user_id = ? AND id IN (SELECT id FROM messages WHERE user_id = ? ORDER BY id ASC LIMIT 5)",
                (summary, user_id, user_id)
            )
            await db.commit()
        except:
            pass

async def get_context(user_id: int) -> str:
    """Получить контекст последних сообщений"""
    async with get_db() as db:
        msgs = await db.execute(
            "SELECT role, content, summary FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 6",
            (user_id,)
        )
        msgs = await msgs.fetchall()
        if not msgs:
            return "Новый диалог"
        lines = []
        for m in reversed(msgs):
            role = "👤" if m["role"] == "user" else "🤖"
            text = m["summary"] if m["summary"] else m["content"][:300]
            lines.append(f"{role} {text}")
        return "\n".join(lines)

async def inc_usage(user_id: int):
    """Увеличить счётчик запросов"""
    today = date.today().isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO daily_usage (user_id, date, count) VALUES (?, ?, 1) ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1",
            (user_id, today)
        )
        await db.execute(
            "UPDATE users SET total_requests = total_requests + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()

async def can_use(user_id: int, username: str) -> Tuple[bool, str]:
    """Проверка лимита"""
    if username in ADMINS:
        return True, ""
    today = date.today().isoformat()
    async with get_db() as db:
        usage = await db.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND date = ?",
            (user_id, today)
        )
        usage = await usage.fetchone()
        used = usage["count"] if usage else 0
        if used >= FREE_LIMIT:
            return False, f"⚠️ Лимит {FREE_LIMIT}/день исчерпан"
        return True, ""

async def save_project(user_id: int, description: str, result: str):
    """Сохранить проект"""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO projects (user_id, description, result) VALUES (?, ?, ?)",
            (user_id, description, result)
        )
        await db.execute(
            "UPDATE users SET total_projects = total_projects + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()

async def get_last_project(user_id: int) -> Optional[dict]:
    """Получить последний проект"""
    async with get_db() as db:
        proj = await db.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        proj = await proj.fetchone()
        return dict(proj) if proj else None

# ═══════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════

class GeminiRateLimiter:
    """Rate limiter для Gemini API (14 req/min)"""
    def __init__(self, max_per_minute: int = 14):
        self.max = max_per_minute
        self.timestamps: List[float] = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Ждать если лимит достигнут"""
        async with self.lock:
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 60]
            if len(self.timestamps) >= self.max:
                wait = 60 - (now - self.timestamps[0]) + 0.5
                log.warning(f"⏸️ Rate limit, ожидание {wait:.1f}s")
                await asyncio.sleep(wait)
                self.timestamps = [t for t in self.timestamps if time.time() - t < 60]
            self.timestamps.append(time.time())

rate_limiter = GeminiRateLimiter()

# ═══════════════════════════════════════════════════════════
# AI CORE
# ═══════════════════════════════════════════════════════════

async def ai_call(
    prompt: str,
    system: str = "",
    temp: float = 0.7,
    max_tokens: int = 8000,
    model: str = "quality"
) -> str:
    """Вызов Gemini API с rate limiting"""
    await rate_limiter.acquire()
    
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
    model_name = MODELS.get(model, MODELS["quality"])
    
    for attempt in range(2):
        try:
            m = genai.GenerativeModel(model_name)
            response = await asyncio.to_thread(
                m.generate_content,
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=temp,
                    max_output_tokens=max_tokens
                )
            )
            text = getattr(response, "text", "")
            if text and len(text.strip()) > 10:
                return text.strip()
        except Exception as e:
            log.warning(f"AI call error (attempt {attempt+1}): {e}")
            if attempt == 0:
                model_name = MODELS["fast"]
                await asyncio.sleep(1)
            else:
                raise Exception(f"AI недоступен: {e}")
    
    raise Exception("Пустой ответ от AI")

# ═══════════════════════════════════════════════════════════
# AGENTS
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentResult:
    """Результат работы агента"""
    agent_name: str
    output: str
    success: bool
    error: Optional[str] = None

class BaseAgent:
    """Базовый класс агента"""
    def __init__(self, name: str, emoji: str, system_prompt: str):
        self.name = name
        self.emoji = emoji
        self.system_prompt = system_prompt
    
    async def run(self, task: str, context: dict, mode: str = "quality") -> AgentResult:
        """Выполнить задачу агента"""
        try:
            full_context = context.get("history", "") + "\n\n" + context.get("previous_output", "")
            prompt = f"{task}\n\n{'Контекст:' if full_context.strip() else ''}\n{full_context}"
            
            temp_map = {"fast": 0.5, "quality": 0.7, "creative": 0.9}
            temp = temp_map.get(mode, 0.7)
            
            output = await ai_call(
                prompt,
                self.system_prompt,
                temp=temp,
                model=mode
            )
            
            return AgentResult(
                agent_name=self.name,
                output=output,
                success=True
            )
        except Exception as e:
            log.error(f"{self.emoji} {self.name} error: {e}")
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=str(e)
            )

class AnalystAgent(BaseAgent):
    """🔍 Агент-аналитик"""
    def __init__(self):
        super().__init__(
            "Analyst",
            "🔍",
            """Ты аналитик задач. Разбираешь запрос пользователя и создаёшь чёткое ТЗ.

Формат вывода:
ЗАДАЧА: [что нужно сделать]
ТРЕБОВАНИЯ: [список требований]
ОГРАНИЧЕНИЯ: [что учесть]
EDGE CASES: [крайние случаи]

Будь кратким, максимум 250 слов."""
        )

class CoderAgent(BaseAgent):
    """💻 Агент-программист (главный)"""
    def __init__(self):
        super().__init__(
            "Coder",
            "💻",
            """Ты elite-программист. Пишешь идеальный production-ready код.

Правила:
✅ Код ПОЛНЫЙ, без TODO и заглушек
✅ Type hints, docstrings, обработка ошибок
✅ Современные best practices
✅ Если задача простая — отвечай кратко
✅ Если нужен код — давай ВЕСЬ код в ```блоках
✅ Каждый файл в своём блоке: ```filename.ext
✅ Отвечай на языке пользователя

Если получил ТЗ от аналитика — следуй ему точно.
Если получил замечания от ревьюера — исправь ВСЁ."""
        )

class ReviewerAgent(BaseAgent):
    """🐛 Агент-ревьюер"""
    def __init__(self):
        super().__init__(
            "Reviewer",
            "🐛",
            """Ты senior code reviewer с 20+ годами опыта.

Проверяешь код на:
- Баги и логические ошибки
- Уязвимости безопасности
- Проблемы производительности
- Соответствие ТЗ

Формат:
ПРОБЛЕМЫ: [список с приоритетами 🔴🟡🟢]
ИСПРАВЛЕНИЯ: [конкретные рекомендации]
ОЦЕНКА: [1-10]

Если оценка < 7 — дай код с исправлениями.
Будь строгим но конструктивным."""
        )

class DocumenterAgent(BaseAgent):
    """📝 Агент-документатор"""
    def __init__(self):
        super().__init__(
            "Documenter",
            "📝",
            """Ты технический писатель. Создаёшь документацию.

Формат:
# [Название проекта]

## Описание
[1-2 предложения]

## Функции
- функция 1
- функция 2

## Установка
```bash
команды
```

## Запуск
```bash
команды
```

## API (если есть)
Endpoints с примерами

Markdown, кратко, с примерами команд."""
        )

# Инициализация агентов
analyst = AnalystAgent()
coder = CoderAgent()
reviewer = ReviewerAgent()
documenter = DocumenterAgent()

# ═══════════════════════════════════════════════════════════
# ROUTER (определение маршрута)
# ═══════════════════════════════════════════════════════════

class Router:
    """Определяет какие агенты нужны для запроса (БЕЗ вызова AI)"""
    
    @staticmethod
    def detect(text: str) -> str:
        """
        Возвращает:
        - simple: простой вопрос/чат
        - question: вопрос требующий анализа
        - debug: отладка кода
        - project: создание проекта
        """
        t = text.lower()
        
        # Проект
        if any(x in t for x in [
            "создай проект", "сделай проект", "полный проект",
            "приложение с нуля", "сайт с нуля", "бот с нуля",
            "целый проект", "новый проект"
        ]):
            return "project"
        
        # Дебаг
        if any(x in t for x in [
            "ошибка", "error", "traceback", "exception",
            "не работает", "баг", "bug", "failed", "crash",
            "почему падает", "исправь код"
        ]):
            return "debug"
        
        # Сложный вопрос
        if any(x in t for x in [
            "объясни", "как работает", "почему", "в чём разница",
            "что лучше", "сравни", "разбери", "проанализируй",
            "напиши код", "реализуй", "функцию для"
        ]) or len(text) > 200:
            return "question"
        
        # Простое общение
        return "simple"

router_agent = Router()

# ═══════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════

class AgentPipeline:
    """Управляет цепочкой агентов"""
    
    @staticmethod
    async def update_progress(msg: Message, text: str):
        """Обновить прогресс-бар"""
        try:
            await msg.edit_text(text)
        except:
            pass
    
    @staticmethod
    async def process(
        user_input: str,
        route: str,
        context: dict,
        mode: str,
        progress_msg: Message
    ) -> str:
        """
        Запустить pipeline агентов
        
        simple:   Coder → ответ
        question: Analyst → Coder → ответ
        debug:    Analyst → Reviewer → Coder → ответ
        project:  Analyst → Coder → Reviewer → [retry if <7] → Documenter → ответ
        """
        
        ctx = {"history": context.get("history", ""), "previous_output": ""}
        
        # ═══ SIMPLE ═══
        if route == "simple":
            await AgentPipeline.update_progress(progress_msg, "🧠 Думаю...\n\n💻 Coder: Работаю... ⏳")
            result = await coder.run(user_input, ctx, mode)
            if not result.success:
                return f"❌ Ошибка: {result.error}"
            return result.output
        
        # ═══ QUESTION ═══
        if route == "question":
            await AgentPipeline.update_progress(
                progress_msg,
                "🧠 Думаю...\n\n🔍 Analyst: Анализирую... ⏳\n💻 Coder: Ожидание..."
            )
            
            analysis = await analyst.run(user_input, ctx, mode)
            if not analysis.success:
                return f"❌ Ошибка аналитика: {analysis.error}"
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🧠 Думаю...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Пишу ответ... ⏳"
            )
            
            ctx["previous_output"] = analysis.output
            code = await coder.run(user_input, ctx, mode)
            if not code.success:
                return f"❌ Ошибка программиста: {code.error}"
            
            return code.output
        
        # ═══ DEBUG ═══
        if route == "debug":
            await AgentPipeline.update_progress(
                progress_msg,
                "🧠 Работаю...\n\n🔍 Analyst: Анализирую... ⏳\n🐛 Reviewer: Ожидание...\n💻 Coder: Ожидание..."
            )
            
            analysis = await analyst.run(user_input, ctx, mode)
            if not analysis.success:
                analysis.output = "Анализ пропущен из-за ошибки"
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🧠 Работаю...\n\n🔍 Analyst: Готово ✅\n🐛 Reviewer: Проверяю... ⏳\n💻 Coder: Ожидание..."
            )
            
            ctx["previous_output"] = analysis.output
            review = await reviewer.run(user_input, ctx, mode)
            if not review.success:
                review.output = "Ревью пропущено из-за ошибки"
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🧠 Работаю...\n\n🔍 Analyst: Готово ✅\n🐛 Reviewer: Готово ✅\n💻 Coder: Исправляю... ⏳"
            )
            
            ctx["previous_output"] = f"{analysis.output}\n\n{review.output}"
            code = await coder.run(user_input, ctx, mode)
            if not code.success:
                return f"❌ Ошибка: {code.error}"
            
            return code.output
        
        # ═══ PROJECT ═══
        if route == "project":
            await AgentPipeline.update_progress(
                progress_msg,
                "🚀 Создаю проект...\n\n🔍 Analyst: Анализирую ТЗ... ⏳\n💻 Coder: Ожидание...\n🐛 Reviewer: Ожидание...\n📝 Documenter: Ожидание..."
            )
            
            # Шаг 1: Анализ
            analysis = await analyst.run(user_input, ctx, mode)
            if not analysis.success:
                return f"❌ Ошибка анализа: {analysis.error}"
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Пишу код... ⏳\n🐛 Reviewer: Ожидание...\n📝 Documenter: Ожидание..."
            )
            
            # Шаг 2: Код
            ctx["previous_output"] = analysis.output
            code = await coder.run(user_input, ctx, mode)
            if not code.success:
                return f"❌ Ошибка кодирования: {code.error}"
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Готово ✅\n🐛 Reviewer: Проверяю... ⏳\n📝 Documenter: Ожидание..."
            )
            
            # Шаг 3: Ревью
            ctx["previous_output"] = code.output
            review = await reviewer.run("Проверь этот код", ctx, mode)
            
            final_code = code.output
            
            # Шаг 4: Retry если оценка < 7 (только в quality/creative)
            if review.success and mode != "fast":
                score_match = re.search(r"ОЦЕНКА:\s*(\d+)", review.output)
                if score_match and int(score_match.group(1)) < 7:
                    await AgentPipeline.update_progress(
                        progress_msg,
                        "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Улучшаю код... ⏳\n🐛 Reviewer: Готово ✅\n📝 Documenter: Ожидание..."
                    )
                    
                    ctx["previous_output"] = f"{code.output}\n\nЗАМЕЧАНИЯ РЕВЬЮЕРА:\n{review.output}"
                    improved = await coder.run("Исправь замечания ревьюера", ctx, mode)
                    if improved.success:
                        final_code = improved.output
            
            await AgentPipeline.update_progress(
                progress_msg,
                "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Готово ✅\n🐛 Reviewer: Готово ✅\n📝 Documenter: Пишу README... ⏳"
            )
            
            # Шаг 5: Документация
            ctx["previous_output"] = final_code
            docs = await documenter.run("Создай документацию для этого проекта", ctx, mode)
            
            # Собираем финальный результат
            result_parts = [
                "# 🚀 Проект готов!\n",
                docs.output if docs.success else "## Документация\n(Автогенерация не удалась)\n",
                "\n---\n\n## 💻 Код\n",
                final_code
            ]
            
            return "\n".join(result_parts)
        
        return "❌ Неизвестный маршрут"

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def extract_code_files(text: str) -> List[Tuple[str, str]]:
    """Извлечь файлы из markdown блоков"""
    pattern = r"```(\S+)\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    
    files = []
    counters = {}
    
    for marker, code in matches:
        code = code.strip()
        if not code or len(code) < 10:
            continue
        
        # Определение имени файла
        if "." in marker and "/" not in marker:
            filename = marker
        elif "/" in marker:
            filename = marker.split("/")[-1]
        else:
            ext_map = {
                "python": "py", "py": "py",
                "javascript": "js", "js": "js",
                "html": "html", "css": "css",
                "dockerfile": "Dockerfile",
                "bash": "sh", "sql": "sql"
            }
            ext = ext_map.get(marker.lower(), "txt")
            base = "main" if ext == "py" else "index" if ext == "html" else "app"
            filename = f"{base}.{ext}"
        
        # Защита от дубликатов
        if filename in counters:
            base, ext = os.path.splitext(filename)
            counters[filename] += 1
            filename = f"{base}_{counters[filename]}{ext}"
        else:
            counters[filename] = 1
        
        files.append((filename, code))
    
    return files

def create_zip(text: str) -> bytes:
    """Создать ZIP архив из кода"""
    buf = io.BytesIO()
    
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files = extract_code_files(text)
        
        for filename, code in files:
            z.writestr(filename, code)
        
        readme = f"""# AI Generated Project

Дата: {datetime.now().strftime("%Y-%m-%d %H:%M")}
Файлов: {len(files)}

## Содержимое

{chr(10).join(f"- {f}" for f, _ in files)}

Создано AI Assistant v{VERSION}
"""
        z.writestr("_INFO.md", readme)
    
    buf.seek(0)
    return buf.getvalue()

async def send_long_message(chat_id: int, text: str, reply_markup=None):
    """Отправить длинное сообщение частями"""
    text = (text or "").strip() or "Пустой ответ"
    
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
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(chat_id, part, parse_mode="Markdown", reply_markup=markup)
        except:
            await bot.send_message(chat_id, part, reply_markup=markup)
        await asyncio.sleep(0.2)

# ═══════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Вопрос"), KeyboardButton(text="🚀 Проект")],
            [KeyboardButton(text="⚙️ Режим"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="🔄 Новый диалог"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )

def mode_kb(current: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅' if current=='fast' else '⚡'} Быстрый",
                    callback_data="mode_fast"
                ),
                InlineKeyboardButton(
                    text=f"{'✅' if current=='quality' else '🎯'} Качество",
                    callback_data="mode_quality"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅' if current=='creative' else '🎨'} Креатив",
                    callback_data="mode_creative"
                )
            ]
        ]
    )

def project_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 ZIP", callback_data="get_zip"),
                InlineKeyboardButton(text="✏️ Доработать", callback_data="edit_project")
            ]
        ]
    )

def file_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 Проверить", callback_data="file_check"),
                InlineKeyboardButton(text="🐛 Баги", callback_data="file_bugs")
            ],
            [
                InlineKeyboardButton(text="📖 Объяснить", callback_data="file_explain"),
                InlineKeyboardButton(text="✨ Улучшить", callback_data="file_improve")
            ]
        ]
    )

# ═══════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════

@router.message(Command("start"))
async def cmd_start(msg: Message):
    await get_user(msg.from_user.id, msg.from_user.username or "")
    await msg.answer(
        f"""🧠 **AI Assistant v{VERSION}**

Мультиагентная система с 5 специализированными AI.

**Режимы:**
⚡ Быстрый — 1 агент, мгновенно
🎯 Качество — до 4 агентов, детально
🎨 Креатив — повышенная температура

**Что умею:**
• Отвечать на любые вопросы
• Писать код любой сложности
• Создавать полные проекты
• Находить и исправлять баги
• Объяснять сложное просто

Просто напиши что нужно! 🚀""",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        """❓ **Помощь**

**Команды:**
/start — Начало
/help — Помощь
/new — Новый диалог
/mode — Выбор режима
/stats — Статистика
/agents — Список агентов

**Примеры:**
• _Объясни рекурсию простыми словами_
• _Напиши функцию сортировки на Python_
• _Создай проект: сайт для кофейни_
• _Вот ошибка: [код], исправь_

Файлы отправляй документом.""",
        parse_mode="Markdown"
    )

@router.message(Command("new"))
async def cmd_new(msg: Message):
    async with get_db() as db:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (msg.from_user.id,))
        await db.commit()
    await msg.answer("🔄 Диалог сброшен. Начинаем с чистого листа!")

@router.message(Command("mode"))
async def cmd_mode(msg: Message):
    user = await get_user(msg.from_user.id)
    current = user.get("mode", "quality")
    await msg.answer(
        f"⚙️ **Режим работы**\n\nТекущий: {current}\n\n"
        "⚡ **Быстрый** — 1 агент, ~5-10 сек\n"
        "🎯 **Качество** — 2-4 агента, ~20-40 сек\n"
        "🎨 **Креатив** — больше свободы\n\n"
        "Выбери режим:",
        parse_mode="Markdown",
        reply_markup=mode_kb(current)
    )

@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    user = await get_user(msg.from_user.id, msg.from_user.username or "")
    today = date.today().isoformat()
    async with get_db() as db:
        usage = await db.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND date = ?",
            (msg.from_user.id, today)
        )
        usage = await usage.fetchone()
        used = usage["count"] if usage else 0
    
    await msg.answer(
        f"""📊 **Статистика**

Всего запросов: {user['total_requests']}
Проектов создано: {user['total_projects']}
Сегодня: {used}/{FREE_LIMIT}
Режим: {user.get('mode', 'quality')}""",
        parse_mode="Markdown"
    )

@router.message(Command("agents"))
async def cmd_agents(msg: Message):
    await msg.answer(
        """🤖 **Агенты системы**

🔍 **Analyst** — анализирует задачу, создаёт ТЗ
💻 **Coder** — пишет код (главный агент)
🐛 **Reviewer** — проверяет на баги и качество
📝 **Documenter** — создаёт документацию

**Маршруты:**
• Простой вопрос → Coder (1 API)
• Сложный вопрос → Analyst + Coder (2 API)
• Дебаг → Analyst + Reviewer + Coder (3 API)
• Проект → Analyst + Coder + Reviewer + Documenter (4-5 API)""",
        parse_mode="Markdown"
    )

@router.message(F.text == "💬 Вопрос")
async def btn_question(msg: Message):
    await msg.answer("💬 Задай любой вопрос, я отвечу!")

@router.message(F.text == "🚀 Проект")
async def btn_project(msg: Message, state: FSMContext):
    await msg.answer(
        "🚀 **Создание проекта**\n\n"
        "Опиши что нужно:\n\n"
        "_Пример: Сделай сайт для пиццерии с каталогом, корзиной и формой заказа_",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_project_desc")

@router.message(F.text == "⚙️ Режим")
async def btn_mode(msg: Message):
    await cmd_mode(msg)

@router.message(F.text == "📊 Статистика")
async def btn_stats(msg: Message):
    await cmd_stats(msg)

@router.message(F.text == "🔄 Новый диалог")
async def btn_new(msg: Message):
    await cmd_new(msg)

@router.message(F.text == "❓ Помощь")
async def btn_help(msg: Message):
    await cmd_help(msg)

@router.callback_query(F.data.startswith("mode_"))
async def cb_mode(call: CallbackQuery):
    mode = call.data.split("_")[1]
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET mode = ? WHERE user_id = ?",
            (mode, call.from_user.id)
        )
        await db.commit()
    
    mode_names = {"fast": "⚡ Быстрый", "quality": "🎯 Качество", "creative": "🎨 Креатив"}
    await call.answer(f"Выбран режим: {mode_names[mode]}")
    await call.message.edit_text(
        f"✅ Режим изменён на **{mode_names[mode]}**",
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "get_zip")
async def cb_zip(call: CallbackQuery):
    project = await get_last_project(call.from_user.id)
    if not project:
        await call.answer("❌ Нет проекта")
        return
    
    await call.answer("📦 Создаю архив...")
    
    try:
        zip_data = create_zip(project["result"])
        filename = f"project_{int(time.time())}.zip"
        
        # Сохраняем временно
        with open(filename, "wb") as f:
            f.write(zip_data)
        
        await bot.send_document(
            call.message.chat.id,
            FSInputFile(filename),
            caption="📦 Твой проект!\n\nРаспакуй и запускай по README"
        )
        
        os.remove(filename)
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "edit_project")
async def cb_edit(call: CallbackQuery, state: FSMContext):
    project = await get_last_project(call.from_user.id)
    if not project:
        await call.answer("❌ Нет проекта")
        return
    
    await call.answer()
    await call.message.answer("✏️ Что изменить/добавить в проект?")
    await state.set_state("editing_project")

@router.callback_query(F.data.startswith("file_"))
async def cb_file(call: CallbackQuery, state: FSMContext):
    action = call.data.split("_")[1]
    
    data = await state.get_data()
    file_content = data.get("file_content")
    
    if not file_content:
        await call.answer("❌ Файл не найден, отправь заново")
        return
    
    ok, err = await can_use(call.from_user.id, call.from_user.username or "")
    if not ok:
        await call.answer(err)
        return
    
    await call.answer("⏳ Анализирую...")
    
    user = await get_user(call.from_user.id)
    mode = user.get("mode", "quality")
    
    prompts = {
        "check": "Проверь этот код. Найди проблемы и дай рекомендации.",
        "bugs": "Найди ВСЕ баги в этом коде. Дай исправленный код.",
        "explain": "Объясни простым языком что делает этот код. Разбери по частям.",
        "improve": "Улучши этот код. Сделай чище, быстрее, безопаснее. Дай полный улучшенный код."
    }
    
    task = f"{prompts[action]}\n\n```\n{file_content[:20000]}\n```"
    
    progress = await call.message.answer("🔄 Анализирую файл...")
    
    try:
        route = "debug" if action == "bugs" else "question"
        context = {"history": await get_context(call.from_user.id)}
        
        result = await AgentPipeline.process(task, route, context, mode, progress)
        
        await progress.delete()
        await inc_usage(call.from_user.id)
        await send_long_message(call.message.chat.id, result)
    except Exception as e:
        await progress.delete()
        await call.message.answer(f"❌ Ошибка: {e}")

@router.message(F.document)
async def on_document(msg: Message, state: FSMContext):
    try:
        file = await bot.get_file(msg.document.file_id)
        file_data = await bot.download_file(file.file_path)
        
        try:
            content = file_data.read().decode("utf-8")
        except:
            content = file_data.read().decode("latin-1", errors="ignore")
        
        if len(content) > 50000:
            content = content[:50000] + "\n\n... (обрезано)"
        
        await state.update_data(file_content=content)
        
        await msg.answer(
            f"📁 Файл `{msg.document.file_name}` получен!\n\nЧто сделать?",
            parse_mode="Markdown",
            reply_markup=file_kb()
        )
    except Exception as e:
        await msg.answer(f"❌ Не удалось прочитать: {e}")

@router.message(F.text)
async def on_text(msg: Message, state: FSMContext):
    user_state = await state.get_state()
    
    # Обработка состояний
    if user_state == "waiting_project_desc":
        await state.clear()
        user_input = msg.text
        route = "project"
    elif user_state == "editing_project":
        await state.clear()
        project = await get_last_project(msg.from_user.id)
        if not project:
            await msg.answer("❌ Нет проекта для редактирования")
            return
        user_input = f"Текущий проект:\n{project['result'][:10000]}\n\n---\n\nИзменения:\n{msg.text}"
        route = "project"
    else:
        user_input = msg.text
        route = router_agent.detect(user_input)
    
    # Проверка лимита
    ok, err = await can_use(msg.from_user.id, msg.from_user.username or "")
    if not ok:
        await msg.answer(err)
        return
    
    # Получаем режим пользователя
    user = await get_user(msg.from_user.id, msg.from_user.username or "")
    mode = user.get("mode", "quality")
    
    # Прогресс-бар
    route_emoji = {
        "simple": "💬",
        "question": "🤔",
        "debug": "🐛",
        "project": "🚀"
    }
    
    progress = await msg.answer(f"{route_emoji.get(route, '🧠')} Думаю...")
    
    try:
        # Контекст
        context = {"history": await get_context(msg.from_user.id)}
        
        # Запуск pipeline
        result = await AgentPipeline.process(user_input, route, context, mode, progress)
        
        # Сохранение
        await add_message(msg.from_user.id, "user", msg.text)
        await add_message(msg.from_user.id, "assistant", result[:2000])
        await inc_usage(msg.from_user.id)
        
        # Сохранение проекта
        if route == "project":
            await save_project(msg.from_user.id, user_input, result)
        
        # Удаляем прогресс
        await progress.delete()
        
        # Отправка результата
        markup = project_kb() if route == "project" else None
        await send_long_message(msg.chat.id, result, markup)
        
    except Exception as e:
        log.error(f"Error: {traceback.format_exc()}")
        await progress.delete()
        await msg.answer(f"❌ Ошибка: {e}\n\nПопробуй /mode fast для быстрого режима")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    log.info(f"🚀 AI Assistant v{VERSION}")
    
    # Инициализация БД
    await init_db()
    
    # Регистрация router
    dp.include_router(router)
    
    # Запуск
    log.info("✅ Бот запущен")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
