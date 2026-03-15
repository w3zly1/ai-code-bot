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
VERSION = "11.0"
MODELS = {"fast": "models/gemini-2.0-flash", "quality": "models/gemini-2.5-flash", "creative": "models/gemini-2.5-flash"}

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
    log.info("DB ready")

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
        role = "User" if m["role"] == "user" else "AI"
        lines.append(f"{role}: {m['content'][:200]}")
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
        return False, f"⚠️ Лимит {FREE_LIMIT}/день"
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
    def __init__(self, max_per_min: int = 14):
        self.max = max_per_min
        self.timestamps: List[float] = []
        self.lock = asyncio.Lock()
    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 60]
            if len(self.timestamps) >= self.max:
                wait = 60 - (now - self.timestamps[0]) + 0.5
                await asyncio.sleep(wait)
                self.timestamps = [t for t in self.timestamps if time.time() - t < 60]
            self.timestamps.append(time.time())

rate_limiter = RateLimiter()

async def ai_call(prompt: str, system: str = "", temp: float = 0.7, max_tokens: int = 8000, model: str = "quality") -> str:
    await rate_limiter.acquire()
    full = f"{system}\n\n{prompt}".strip() if system else prompt
    model_name = MODELS.get(model, MODELS["quality"])
    for attempt in range(2):
        try:
            m = genai.GenerativeModel(model_name)
            r = await asyncio.to_thread(m.generate_content, full, generation_config=genai.GenerationConfig(temperature=temp, max_output_tokens=max_tokens))
            txt = getattr(r, "text", "")
            if txt and len(txt.strip()) > 10:
                return txt.strip()
        except Exception as e:
            log.warning(f"AI error {attempt+1}: {e}")
            if attempt == 0:
                model_name = MODELS["fast"]
                await asyncio.sleep(1)
            else:
                raise Exception(f"AI недоступен: {e}")
    raise Exception("Пустой ответ")

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
            output = await ai_call(prompt, self.system, temp=temp_map.get(mode, 0.7), model=mode)
            return AgentResult(name=self.name, output=output, success=True)
        except Exception as e:
            return AgentResult(name=self.name, output="", success=False, error=str(e))

class AnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__("Analyst", "🔍", "Ты аналитик. Разбираешь запрос, создаёшь ТЗ.\n\nФормат:\nЗАДАЧА: [что делать]\nТРЕБОВАНИЯ: [список]\n\nМаксимум 200 слов.")

class CoderAgent(BaseAgent):
    def __init__(self):
        super().__init__("Coder", "💻", "Ты elite-программист.\n\nПравила:\n- Код ПОЛНЫЙ, без TODO\n- Type hints, обработка ошибок\n- Код в ```блоках\n- Сразу к делу, без воды\n- Формат для Telegram: абзацы 2-3 строки, эмодзи\n\nЕсли есть ТЗ — следуй ему. Если замечания — исправь.")

class ReviewerAgent(BaseAgent):
    def __init__(self):
        super().__init__("Reviewer", "🐛", "Ты code reviewer.\n\nПроверяешь: баги, безопасность, производительность.\n\nФормат:\nПРОБЛЕМЫ: [список]\nИСПРАВЛЕНИЯ: [код]\nОЦЕНКА: [1-10]\n\nЕсли < 7 — дай исправленный код.")

class DocumenterAgent(BaseAgent):
    def __init__(self):
        super().__init__("Documenter", "📝", "Ты техписатель. Создай README:\n# Название\n## Что умеет\n## Установка\n## Запуск\n\nКратко.")

analyst = AnalystAgent()
coder = CoderAgent()
reviewer = ReviewerAgent()
documenter = DocumenterAgent()

class TaskRouter:
    @staticmethod
    def detect(text: str) -> str:
        t = text.lower()
        if any(x in t for x in ["создай проект", "сделай проект", "полный проект", "с нуля"]):
            return "project"
        if any(x in t for x in ["ошибка", "error", "traceback", "не работает", "баг", "bug", "исправь"]):
            return "debug"
        if any(x in t for x in ["объясни", "как работает", "почему", "напиши код", "реализуй", "функцию"]) or len(text) > 200:
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
            await Pipeline.update(progress, "🧠 Думаю...\n\n💻 Coder: Работаю... ⏳")
            r = await coder.run(user_input, context, mode)
            return r.output if r.success else f"❌ {r.error}"
        if route == "question":
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Analyst: Анализирую... ⏳\n💻 Coder: Ожидает")
            analysis = await analyst.run(user_input, context, mode)
            if not analysis.success:
                return f"❌ {analysis.error}"
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Пишу... ⏳")
            context["previous"] = analysis.output
            code = await coder.run(user_input, context, mode)
            return code.output if code.success else f"❌ {code.error}"
        if route == "debug":
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Analyst: Анализирую... ⏳\n🐛 Reviewer: Ожидает\n💻 Coder: Ожидает")
            analysis = await analyst.run(user_input, context, mode)
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Analyst: Готово ✅\n🐛 Reviewer: Проверяю... ⏳\n💻 Coder: Ожидает")
            context["previous"] = analysis.output if analysis.success else ""
            review = await reviewer.run(user_input, context, mode)
            await Pipeline.update(progress, "🧠 Работаю...\n\n🔍 Analyst: Готово ✅\n🐛 Reviewer: Готово ✅\n💻 Coder: Исправляю... ⏳")
            context["previous"] = f"{analysis.output if analysis.success else ''}\n\n{review.output if review.success else ''}"
            code = await coder.run(user_input, context, mode)
            return code.output if code.success else f"❌ {code.error}"
        if route == "project":
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Analyst: ТЗ... ⏳\n💻 Coder: Ожидает\n🐛 Reviewer: Ожидает\n📝 Docs: Ожидает")
            analysis = await analyst.run(user_input, context, mode)
            if not analysis.success:
                return f"❌ {analysis.error}"
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Пишу... ⏳\n🐛 Reviewer: Ожидает\n📝 Docs: Ожидает")
            context["previous"] = analysis.output
            code = await coder.run(user_input, context, mode)
            if not code.success:
                return f"❌ {code.error}"
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Готово ✅\n🐛 Reviewer: Проверяю... ⏳\n📝 Docs: Ожидает")
            context["previous"] = code.output
            review = await reviewer.run("Проверь код", context, mode)
            final_code = code.output
            if review.success and mode != "fast":
                score = re.search(r"ОЦЕНКА:\s*(\d+)", review.output)
                if score and int(score.group(1)) < 7:
                    await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Улучшаю... ⏳\n🐛 Reviewer: Готово ✅\n📝 Docs: Ожидает")
                    context["previous"] = f"{code.output}\n\nЗАМЕЧАНИЯ:\n{review.output}"
                    improved = await coder.run("Исправь замечания", context, mode)
                    if improved.success:
                        final_code = improved.output
            await Pipeline.update(progress, "🚀 Создаю проект...\n\n🔍 Analyst: Готово ✅\n💻 Coder: Готово ✅\n🐛 Reviewer: Готово ✅\n📝 Docs: README... ⏳")
            context["previous"] = final_code
            docs = await documenter.run("Создай README", context, mode)
            return f"{docs.output if docs.success else ''}\n\n---\n\n{final_code}"
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
            ext_map = {"python": "py", "py": "py", "javascript": "js", "js": "js", "html": "html", "css": "css", "bash": "sh", "dockerfile": "Dockerfile"}
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
        z.writestr("INFO.md", f"# AI Project\nДата: {datetime.now()}\nФайлов: {len(files)}")
    buf.seek(0)
    return buf.getvalue()

async def send_long(cid: int, text: str, markup=None):
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
        rm = markup if i == len(parts) - 1 else None
        try:
            await bot.send_message(cid, part, parse_mode="Markdown", reply_markup=rm)
        except:
            await bot.send_message(cid, part, reply_markup=rm)
        await asyncio.sleep(0.2)

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="💬 Вопрос"), KeyboardButton(text="🚀 Проект")], [KeyboardButton(text="⚙️ Режим"), KeyboardButton(text="📊 Статистика")], [KeyboardButton(text="🔄 Сброс"), KeyboardButton(text="❓ Помощь")]], resize_keyboard=True)

def mode_kb(current: str):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{'✅' if current=='fast' else '⚡'} Быстрый", callback_data="mode_fast"), InlineKeyboardButton(text=f"{'✅' if current=='quality' else '🎯'} Качество", callback_data="mode_quality")], [InlineKeyboardButton(text=f"{'✅' if current=='creative' else '🎨'} Креатив", callback_data="mode_creative")]])

def project_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 ZIP", callback_data="get_zip"), InlineKeyboardButton(text="✏️ Доработать", callback_data="edit_project")]])

def file_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Проверить", callback_data="file_check"), InlineKeyboardButton(text="🐛 Баги", callback_data="file_bugs")], [InlineKeyboardButton(text="📖 Объяснить", callback_data="file_explain"), InlineKeyboardButton(text="✨ Улучшить", callback_data="file_improve")]])

@router.message(Command("start"))
async def cmd_start(msg: Message):
    await get_user(msg.from_user.id, msg.from_user.username or "")
    await msg.answer(f"🧠 **AI Assistant v{VERSION}**\n\nМультиагентная система.\n\n**Режимы:**\n⚡ Быстрый — 1 агент\n🎯 Качество — до 4 агентов\n🎨 Креатив — max температура\n\n**Что умею:**\n• Отвечать на вопросы\n• Писать код\n• Создавать проекты\n• Находить баги\n\nПросто напиши 🚀", parse_mode="Markdown", reply_markup=main_kb())

@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("❓ **Помощь**\n\n/start\n/help\n/new — новый диалог\n/mode — режим\n/stats — статистика\n\n**Примеры:**\n• _Объясни рекурсию_\n• _Напиши сортировку_\n• _Создай проект: сайт кофейни_", parse_mode="Markdown")

@router.message(Command("new"))
async def cmd_new(msg: Message):
    db = await get_db()
    await db.execute("DELETE FROM messages WHERE user_id = ?", (msg.from_user.id,))
    await db.commit()
    await db.close()
    await msg.answer("🔄 Диалог сброшен")

@router.message(Command("mode"))
async def cmd_mode(msg: Message):
    u = await get_user(msg.from_user.id)
    await msg.answer(f"⚙️ **Режим:** {u.get('mode', 'quality')}\n\n⚡ Быстрый — 1 агент\n🎯 Качество — 2-4 агента\n🎨 Креатив — max свобода", parse_mode="Markdown", reply_markup=mode_kb(u.get("mode", "quality")))

@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    u = await get_user(msg.from_user.id)
    db = await get_db()
    today = date.today().isoformat()
    usage = await db.execute("SELECT count FROM daily_usage WHERE user_id = ? AND date = ?", (msg.from_user.id, today))
    usage = await usage.fetchone()
    await db.close()
    used = usage["count"] if usage else 0
    await msg.answer(f"📊 **Статистика**\n\nВсего: {u['total_requests']}\nПроектов: {u['total_projects']}\nСегодня: {used}/{FREE_LIMIT}", parse_mode="Markdown")

@router.message(F.text == "💬 Вопрос")
async def btn_question(msg: Message):
    await msg.answer("💬 Задай вопрос")

@router.message(F.text == "🚀 Проект")
async def btn_project(msg: Message, state: FSMContext):
    await msg.answer("🚀 **Создание проекта**\n\nОпиши что нужно:\n\n_Пример: Сайт для пиццерии с каталогом_", parse_mode="Markdown")
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
    await call.answer(f"Выбран: {names[mode]}")
    await call.message.edit_text(f"✅ Режим: **{names[mode]}**", parse_mode="Markdown")

@router.callback_query(F.data == "get_zip")
async def cb_zip(call: CallbackQuery):
    p = await get_last_project(call.from_user.id)
    if not p:
        await call.answer("❌ Нет проекта")
        return
    await call.answer("📦 Создаю...")
    try:
        data = create_zip(p["result"])
        await bot.send_document(call.message.chat.id, BufferedInputFile(data, filename=f"project_{int(time.time())}.zip"), caption="📦 Твой проект")
    except Exception as e:
        await call.message.answer(f"❌ {e}")

@router.callback_query(F.data == "edit_project")
async def cb_edit(call: CallbackQuery, state: FSMContext):
    p = await get_last_project(call.from_user.id)
    if not p:
        await call.answer("❌ Нет проекта")
        return
    await call.answer()
    await call.message.answer("✏️ Что изменить?")
    await state.set_state("edit_project")

@router.callback_query(F.data.startswith("file_"))
async def cb_file(call: CallbackQuery, state: FSMContext):
    action = call.data.split("_")[1]
    data = await state.get_data()
    content = data.get("file_content")
    if not content:
        await call.answer("❌ Файл не найден")
        return
    ok, err = await can_use(call.from_user.id, call.from_user.username or "")
    if not ok:
        await call.answer(err)
        return
    await call.answer("⏳ Анализирую...")
    u = await get_user(call.from_user.id)
    mode = u.get("mode", "quality")
    prompts = {"check": "Проверь код", "bugs": "Найди баги, дай исправленный код", "explain": "Объясни код", "improve": "Улучши код"}
    task = f"{prompts[action]}\n\n```\n{content[:20000]}\n```"
    progress = await call.message.answer("🔄 Анализирую...")
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
        await msg.answer(f"📁 Файл `{msg.document.file_name}` получен\n\nЧто сделать?", parse_mode="Markdown", reply_markup=file_kb())
    except Exception as e:
        await msg.answer(f"❌ {e}")

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
            await msg.answer("❌ Нет проекта")
            return
        user_input = f"Текущий:\n{p['result'][:10000]}\n\nИзменения:\n{msg.text}"
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
        await msg.answer(f"❌ {e}")

async def main():
    log.info(f"🚀 v{VERSION}")
    await init_db()
    dp.include_router(router)
    log.info("✅ Started")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
