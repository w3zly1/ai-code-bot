#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Code Assistant v7 ULTRA MONSTER
Telegram Bot с Gemini AI
"""

import os
import re
import io
import json
import time
import zipfile
import logging
import traceback
import hashlib
from datetime import date, datetime
from typing import Dict, List, Tuple, Optional, Any
from functools import wraps

import requests
import telebot
from telebot import types
import google.generativeai as genai


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

ADMINS = set(
    x.strip() for x in os.environ.get("ADMINS", "").split(",") if x.strip()
)
PREMIUM_USERS = set(
    x.strip() for x in os.environ.get("PREMIUM_USERS", "").split(",") if x.strip()
)

FREE_LIMIT = int(os.environ.get("FREE_LIMIT", "25"))
PREMIUM_LIMIT = int(os.environ.get("PREMIUM_LIMIT", "500"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "0000 0000 0000 0000")

VERSION = "7.0 ULTRA MONSTER"

# Модели с fallback
MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
]

# Лимиты
MAX_MESSAGE_LEN = 3900
MAX_MEMORY_TURNS = 16
MAX_CONTEXT_TURNS = 8
MAX_FILE_SIZE = 50000  # символов
MAX_PROJECTS = 5
AI_RETRIES = 3
REQUEST_TIMEOUT = 20


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("ai-code-assistant")


# =========================================================
# INIT
# =========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True, num_threads=4)
genai.configure(api_key=GEMINI_API_KEY)

http = requests.Session()
http.headers.update({"User-Agent": f"AI-Code-Assistant/{VERSION}"})


# =========================================================
# STORAGE (IN-MEMORY)
# =========================================================

users: Dict[int, dict] = {}
usage: Dict[int, Dict[date, int]] = {}
memory: Dict[int, dict] = {}
projects: Dict[int, List[dict]] = {}  # теперь список проектов
files: Dict[int, dict] = {}
user_modes: Dict[int, str] = {}  # текущий режим пользователя
user_lang: Dict[int, str] = {}  # предпочитаемый язык

stats = {
    "total": 0,
    "ok": 0,
    "err": 0,
    "users": 0,
    "projects": 0,
    "files_analyzed": 0,
    "start_time": datetime.now().isoformat(),
}


# =========================================================
# MODES
# =========================================================

MODES = {
    "auto": "🤖 Авто",
    "code": "💻 Только код",
    "debug": "🐛 Дебаг",
    "explain": "📖 Объяснение",
    "refactor": "✨ Рефакторинг",
    "architect": "🏗 Архитектура",
    "review": "🔍 Ревью",
    "learn": "📚 Обучение",
}


# =========================================================
# ROLES SYSTEM
# =========================================================

def get_role(uid: int, username: str) -> str:
    """Возвращает роль: admin, premium, user"""
    if username in ADMINS:
        return "admin"
    if username in PREMIUM_USERS:
        return "premium"
    if users.get(uid, {}).get("role") == "premium":
        return "premium"
    return "user"


def is_admin(username: str) -> bool:
    return username in ADMINS


def is_premium(uid: int, username: str) -> bool:
    return get_role(uid, username) in ("admin", "premium")


# =========================================================
# USER MANAGEMENT
# =========================================================

def get_user(uid: int, username: Optional[str] = None) -> dict:
    if uid not in users:
        users[uid] = {
            "name": username or "",
            "n": 0,
            "proj": 0,
            "files": 0,
            "role": "user",
            "lang": "python",
            "created": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
        }
        stats["users"] += 1
    else:
        users[uid]["last_active"] = datetime.now().isoformat()
        if username and not users[uid].get("name"):
            users[uid]["name"] = username
    return users[uid]


def get_limit(uid: int, username: str) -> int:
    role = get_role(uid, username)
    if role == "admin":
        return 999999
    if role == "premium":
        return PREMIUM_LIMIT
    return users.get(uid, {}).get("limit", FREE_LIMIT)


def can_use(uid: int, username: str) -> Tuple[bool, str]:
    role = get_role(uid, username)
    if role == "admin":
        return True, ""

    today = date.today()
    used = usage.get(uid, {}).get(today, 0)
    limit = get_limit(uid, username)

    if used >= limit:
        msg = f"⚠️ Лимит {limit} запросов/день исчерпан.\n\n"
        if role == "user":
            msg += "⭐ Получи Premium: /premium"
        return False, msg
    return True, ""


def add_use(uid: int):
    today = date.today()
    usage.setdefault(uid, {})
    usage[uid][today] = usage[uid].get(today, 0) + 1
    get_user(uid)["n"] += 1
    stats["total"] += 1


# =========================================================
# MESSAGE HELPERS
# =========================================================

def send_long(chat_id: int, text: str, parse_mode: Optional[str] = "Markdown", reply_markup=None):
    """Отправляет длинное сообщение частями"""
    text = (text or "").strip()
    if not text:
        text = "🤷 Пустой ответ от модели. Попробуй переформулировать вопрос."

    # Экранирование проблемных символов для Markdown
    def safe_text(t: str) -> str:
        return t

    parts = []
    while len(text) > MAX_MESSAGE_LEN:
        # Ищем хорошее место для разрыва
        cut = text.rfind("\n```", 0, MAX_MESSAGE_LEN)
        if cut == -1 or cut < MAX_MESSAGE_LEN // 2:
            cut = text.rfind("\n\n", 0, MAX_MESSAGE_LEN)
        if cut == -1 or cut < MAX_MESSAGE_LEN // 2:
            cut = text.rfind("\n", 0, MAX_MESSAGE_LEN)
        if cut == -1:
            cut = MAX_MESSAGE_LEN
        parts.append(text[:cut])
        text = text[cut:].strip()
    if text:
        parts.append(text)

    for i, part in enumerate(parts):
        try:
            rm = reply_markup if i == len(parts) - 1 else None
            bot.send_message(chat_id, safe_text(part), parse_mode=parse_mode, reply_markup=rm)
        except Exception:
            try:
                bot.send_message(chat_id, part, reply_markup=rm)
            except Exception as e:
                bot.send_message(chat_id, f"Ошибка отправки: {e}")
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

def ai_call(
    prompt: str,
    system: str = "",
    temperature: float = 0.6,
    max_output_tokens: int = 8192,
    force_code: bool = False
) -> str:
    """Вызов AI с retry и fallback между моделями"""
    
    # Усиление промпта для кода
    if force_code:
        system += "\n\nОБЯЗАТЕЛЬНО дай полный рабочий код. Без заглушек, без TODO, без пропусков."
    
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt.strip()
    last_error = None

    for model_name in MODELS:
        for attempt in range(1, AI_RETRIES + 1):
            try:
                model = genai.GenerativeModel(model_name=model_name)
                response = model.generate_content(
                    full_prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                text = getattr(response, "text", None)
                if text and text.strip():
                    result = text.strip()
                    
                    # Проверка на пустой/слабый ответ
                    if len(result) < 50 and "```" not in result:
                        raise Exception("Слишком короткий ответ")
                    
                    return result
                raise Exception("Пустой ответ модели")
            except Exception as e:
                last_error = e
                log.warning(f"AI error [{model_name}] attempt {attempt}: {e}")
                time.sleep(1.0 * attempt)

    raise Exception(f"AI временно недоступен: {last_error}")


def ai_call_with_retry(
    prompt: str,
    system: str = "",
    temperature: float = 0.6,
    max_output_tokens: int = 8192,
    min_length: int = 100,
    require_code: bool = False
) -> str:
    """AI вызов с проверкой качества ответа"""
    
    result = ai_call(prompt, system, temperature, max_output_tokens)
    
    # Проверка на качество
    is_weak = (
        len(result) < min_length or
        (require_code and "```" not in result)
    )
    
    if is_weak:
        # Повторный запрос с усилением
        enhanced_system = system + """

ВАЖНО: Предыдущий ответ был слишком коротким или неполным.
Дай ПОЛНЫЙ, ДЕТАЛЬНЫЙ ответ.
Если нужен код - ОБЯЗАТЕЛЬНО дай полный рабочий код в блоке ```язык
Не пиши "и так далее", "...", "TODO" - дай готовое решение.
"""
        try:
            result2 = ai_call(prompt, enhanced_system, temperature * 0.8, max_output_tokens)
            if len(result2) > len(result):
                return result2
        except Exception:
            pass
    
    return result


# =========================================================
# MEMORY & CONTEXT
# =========================================================

def get_memory(uid: int) -> dict:
    return memory.setdefault(uid, {"turns": [], "summary": "", "facts": []})


def mem_add(uid: int, role: str, text: str):
    mem = get_memory(uid)
    mem["turns"].append({
        "role": role,
        "text": (text or "").strip()[:2000],
        "time": datetime.now().isoformat()
    })
    
    # Ограничение размера
    if len(mem["turns"]) > MAX_MEMORY_TURNS:
        mem["turns"] = mem["turns"][-MAX_MEMORY_TURNS:]
    
    # Автоматическое сжатие
    if len(mem["turns"]) >= 10 and len(mem["turns"]) % 5 == 0:
        summarize_memory(uid)


def summarize_memory(uid: int):
    """Сжимает историю в краткое резюме"""
    mem = get_memory(uid)
    if len(mem.get("turns", [])) < 6:
        return

    turns = mem["turns"][-12:]
    raw = "\n".join(f"{x['role']}: {x['text'][:500]}" for x in turns)

    system = """
Сожми диалог в краткое резюме (макс 300 слов).
Сохрани ТОЛЬКО:
- Цели пользователя
- Выбранные технологии
- Ключевые решения
- Текущие проблемы
- Важные ограничения
Формат: краткие пункты.
"""

    try:
        summary = ai_call(raw, system=system, temperature=0.2, max_output_tokens=500)
        mem["summary"] = summary
        mem["turns"] = mem["turns"][-4:]  # Оставляем только последние
    except Exception as e:
        log.warning(f"Summary failed: {e}")


def extract_facts(uid: int, text: str):
    """Извлекает важные факты из сообщения"""
    mem = get_memory(uid)
    
    # Простое извлечение технологий/языков
    tech_patterns = [
        r'\b(python|javascript|typescript|go|rust|java|c\+\+|c#|php|ruby|swift|kotlin)\b',
        r'\b(react|vue|angular|django|flask|fastapi|express|next\.?js|nest\.?js)\b',
        r'\b(postgresql|mysql|mongodb|redis|sqlite|elasticsearch)\b',
        r'\b(docker|kubernetes|aws|gcp|azure|railway|heroku|vercel)\b',
    ]
    
    text_lower = text.lower()
    for pattern in tech_patterns:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            fact = f"tech:{match.lower()}"
            if fact not in mem.get("facts", []):
                mem.setdefault("facts", []).append(fact)


def get_context(uid: int) -> str:
    """Собирает контекст для AI"""
    mem = get_memory(uid)
    
    parts = []
    
    # Резюме
    if mem.get("summary"):
        parts.append(f"📋 Резюме диалога:\n{mem['summary']}")
    
    # Факты
    facts = mem.get("facts", [])
    if facts:
        parts.append(f"🔧 Технологии: {', '.join(f.replace('tech:', '') for f in facts[:10])}")
    
    # Последние сообщения
    turns = mem.get("turns", [])[-MAX_CONTEXT_TURNS:]
    if turns:
        parts.append("\n📝 Последние сообщения:")
        for t in turns:
            role = "👤" if t["role"] == "user" else "🤖"
            parts.append(f"{role}: {t['text'][:800]}")
    
    return "\n\n".join(parts)


def clear_memory(uid: int):
    """Полностью очищает память пользователя"""
    memory.pop(uid, None)
    user_modes.pop(uid, None)
    files.pop(uid, None)


# =========================================================
# MODE DETECTION
# =========================================================

def detect_mode(text: str, uid: int) -> str:
    """Определяет режим работы по тексту"""
    
    # Если режим установлен вручную
    manual_mode = user_modes.get(uid)
    if manual_mode and manual_mode != "auto":
        return manual_mode
    
    t = text.lower()
    
    # Debug mode
    if any(x in t for x in [
        "ошибка", "traceback", "exception", "error", "stack trace",
        "не работает", "bug", "баг", "падает", "crash", "failed",
        "typeerror", "valueerror", "keyerror", "attributeerror",
        "syntaxerror", "importerror", "modulenotfounderror"
    ]):
        return "debug"
    
    # Explain mode
    if any(x in t for x in [
        "объясни", "что делает", "поясни", "разбери", "как работает",
        "explain", "what does", "расскажи про", "что такое"
    ]):
        return "explain"
    
    # Refactor mode
    if any(x in t for x in [
        "рефактор", "улучши код", "оптимизируй", "сделай лучше",
        "refactor", "improve", "optimize", "clean up"
    ]):
        return "refactor"
    
    # Review mode
    if any(x in t for x in [
        "проверь код", "review", "ревью", "найди проблемы",
        "code review", "что не так"
    ]):
        return "review"
    
    # Architecture mode
    if any(x in t for x in [
        "архитектура", "структура проекта", "как организовать",
        "architecture", "project structure", "design pattern"
    ]):
        return "architect"
    
    # Code mode (просят написать код)
    if any(x in t for x in [
        "напиши", "создай", "сделай", "реализуй", "код для",
        "write", "create", "implement", "make", "build",
        "функци", "класс", "скрипт", "бот", "api", "парсер"
    ]):
        return "code"
    
    # Learn mode
    if any(x in t for x in [
        "научи", "tutorial", "пример", "как сделать",
        "покажи как", "обучение", "курс"
    ]):
        return "learn"
    
    return "auto"


def detect_language(text: str, uid: int) -> str:
    """Определяет язык программирования"""
    t = text.lower()
    
    lang_patterns = {
        "python": ["python", "питон", "py", "django", "flask", "fastapi", "pandas", "numpy"],
        "javascript": ["javascript", "js", "node", "react", "vue", "express", "npm"],
        "typescript": ["typescript", "ts", "angular", "nest"],
        "go": ["golang", " go ", "gin", "fiber"],
        "rust": ["rust", "cargo", "tokio"],
        "java": ["java", "spring", "maven", "gradle"],
        "csharp": ["c#", "csharp", ".net", "asp.net"],
        "php": ["php", "laravel", "symfony"],
        "sql": ["sql", "postgresql", "mysql", "sqlite", "запрос к базе"],
        "bash": ["bash", "shell", "sh", "terminal", "командная строка"],
    }
    
    for lang, patterns in lang_patterns.items():
        if any(p in t for p in patterns):
            user_lang[uid] = lang
            return lang
    
    # Возвращаем сохраненный или дефолтный
    return user_lang.get(uid, "python")


# =========================================================
# SYSTEM PROMPTS
# =========================================================

BASE_SYSTEM = """
Ты AI Code Assistant уровня Staff/Principal Engineer.
Твоя задача - давать МАКСИМАЛЬНО ПОЛЕЗНЫЕ ответы.

ЖЕЛЕЗНЫЕ ПРАВИЛА:
1. Если просят код - даёшь ПОЛНЫЙ РАБОЧИЙ код без заглушек и TODO
2. Код оформляешь в ```язык блоки
3. Каждый ответ должен быть ПРАКТИЧЕСКИ ПРИМЕНИМ
4. Не выдумываешь несуществующие библиотеки и API
5. Учитываешь обработку ошибок и edge cases
6. Даёшь краткие пояснения после кода
7. Если не хватает данных - задаёшь 1-2 уточняющих вопроса
8. Отвечаешь на русском, код на английском

КАЧЕСТВО КОДА:
- Type hints где возможно
- Docstrings для функций
- Обработка ошибок
- Логирование
- Понятные имена переменных
"""

MODE_PROMPTS = {
    "auto": """
Режим: Универсальный ассистент.
Анализируй запрос и давай оптимальный ответ.
Если нужен код - пиши код. Если нужно объяснение - объясняй.
""",
    
    "code": """
Режим: ТОЛЬКО КОД.
- Минимум текста, максимум кода
- Полный рабочий код без пропусков
- Код должен запускаться сразу
- После кода - краткая инструкция запуска (2-3 строки)
""",
    
    "debug": """
Режим: ДЕБАГ И ИСПРАВЛЕНИЕ ОШИБОК.
Порядок работы:
1. Определи тип и причину ошибки
2. Найди корневую проблему
3. Дай ИСПРАВЛЕННЫЙ код целиком
4. Объясни что было не так (кратко)
5. Дай совет как избежать такого в будущем
""",
    
    "explain": """
Режим: ОБЪЯСНЕНИЕ.
- Объясняй простым языком
- Разбивай на шаги
- Используй аналогии
- Показывай примеры
- Отвечай на "почему", а не только "как"
""",
    
    "refactor": """
Режим: РЕФАКТОРИНГ.
1. Сначала покажи что именно улучшишь
2. Дай ПОЛНЫЙ улучшенный код
3. Не меняй функциональность без просьбы
4. Добавь type hints, docstrings, обработку ошибок
5. Сделай код более читаемым и maintainable
""",
    
    "review": """
Режим: CODE REVIEW.
Проверь код на:
- Баги и логические ошибки
- Проблемы безопасности
- Проблемы производительности
- Code style и best practices
- Потенциальные edge cases

Формат: список проблем с приоритетом (🔴 критично, 🟡 важно, 🟢 улучшение)
""",
    
    "architect": """
Режим: АРХИТЕКТУРА.
- Структура проекта (дерево файлов)
- Компоненты и их взаимодействие
- Выбор технологий с обоснованием
- API design (если применимо)
- База данных (если применимо)
- Деплой
""",
    
    "learn": """
Режим: ОБУЧЕНИЕ.
- Объясняй концепции с нуля
- Давай пошаговые примеры
- От простого к сложному
- Показывай best practices сразу
- Давай задания для практики
""",
}


def build_system_prompt(uid: int, mode: str, lang: str) -> str:
    """Собирает системный промпт"""
    context = get_context(uid)
    mode_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["auto"])
    
    return f"""
{BASE_SYSTEM}

{mode_prompt}

Предпочитаемый язык: {lang}

Контекст диалога:
{context}
""".strip()


# =========================================================
# CODE EXTRACTION & ZIP
# =========================================================

def extract_code_blocks(text: str) -> List[Tuple[str, str, str]]:
    """Извлекает блоки кода: (язык, код, имя_файла)"""
    pattern = r"```(\w+)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    
    blocks = []
    file_counter = {}
    
    for lang, code in matches:
        lang = (lang or "txt").strip().lower()
        code = code.strip()
        
        if not code:
            continue
        
        # Определение имени файла из кода
        filename = None
        
        # Python
        if lang in ("python", "py"):
            if "if __name__" in code:
                filename = "main.py"
            elif "class " in code:
                match = re.search(r"class\s+(\w+)", code)
                if match:
                    filename = f"{match.group(1).lower()}.py"
            elif "def " in code:
                match = re.search(r"def\s+(\w+)", code)
                if match:
                    filename = f"{match.group(1)}.py"
        
        # JavaScript/TypeScript
        elif lang in ("javascript", "js", "typescript", "ts"):
            ext = "ts" if lang in ("typescript", "ts") else "js"
            if "export default" in code or "module.exports" in code:
                filename = f"index.{ext}"
            elif "express()" in code or "fastify" in code:
                filename = f"server.{ext}"
        
        # Конфиги
        elif lang == "json":
            if '"scripts"' in code:
                filename = "package.json"
            elif '"name"' in code and '"version"' in code:
                filename = "config.json"
        
        # Docker
        elif lang in ("dockerfile", "docker"):
            filename = "Dockerfile"
            lang = "dockerfile"
        
        # По умолчанию
        if not filename:
            ext = lang_to_ext(lang)
            file_counter[ext] = file_counter.get(ext, 0) + 1
            filename = f"file_{file_counter[ext]}.{ext}"
        
        blocks.append((lang, code, filename))
    
    return blocks


def lang_to_ext(lang: str) -> str:
    mapping = {
        "python": "py", "py": "py",
        "javascript": "js", "js": "js",
        "typescript": "ts", "ts": "ts",
        "json": "json",
        "html": "html",
        "css": "css",
        "bash": "sh", "sh": "sh", "shell": "sh",
        "sql": "sql",
        "yaml": "yml", "yml": "yml",
        "toml": "toml",
        "markdown": "md", "md": "md",
        "dockerfile": "Dockerfile",
        "go": "go",
        "rust": "rs",
        "java": "java",
        "csharp": "cs", "c#": "cs",
        "php": "php",
        "ruby": "rb",
        "swift": "swift",
        "kotlin": "kt",
        "txt": "txt", "text": "txt",
    }
    return mapping.get(lang.lower(), "txt")


def make_project_zip(project_data: dict) -> bytes:
    """Создаёт ZIP архив проекта"""
    buf = io.BytesIO()
    
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        all_files = {}
        
        for section_name, content in project_data.items():
            if not isinstance(content, str):
                continue
            
            blocks = extract_code_blocks(content)
            
            if blocks:
                for lang, code, filename in blocks:
                    # Избегаем дубликатов
                    if filename in all_files:
                        base, ext = os.path.splitext(filename)
                        i = 2
                        while f"{base}_{i}{ext}" in all_files:
                            i += 1
                        filename = f"{base}_{i}{ext}"
                    
                    all_files[filename] = code
        
        # Записываем файлы
        for filename, code in all_files.items():
            z.writestr(filename, code)
        
        # README
        readme = f"""# AI Code Assistant Generated Project

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Files: {len(all_files)}

## Files

{chr(10).join(f'- {f}' for f in sorted(all_files.keys()))}

## Generated by AI Code Assistant v{VERSION}
"""
        z.writestr("README.md", readme)
        
        # requirements.txt если есть Python файлы
        if any(f.endswith('.py') for f in all_files):
            # Попытка извлечь импорты
            imports = set()
            for code in all_files.values():
                for match in re.findall(r'^(?:from|import)\s+(\w+)', code, re.MULTILINE):
                    if match not in ('os', 'sys', 're', 'json', 'time', 'datetime', 'typing', 'collections', 'functools', 'itertools', 'pathlib'):
                        imports.add(match)
            
            if imports:
                z.writestr("requirements.txt", "\n".join(sorted(imports)))
    
    buf.seek(0)
    return buf.getvalue()


# =========================================================
# TOOLS
# =========================================================

def search_web(query: str) -> str:
    """Поиск через DuckDuckGo"""
    try:
        r = http.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

        result_parts = []
        
        # Abstract
        abstract = data.get("AbstractText") or data.get("Abstract")
        if abstract:
            result_parts.append(abstract[:1000])
        
        # Related topics
        related = data.get("RelatedTopics", [])
        for item in related[:5]:
            if isinstance(item, dict) and item.get("Text"):
                result_parts.append(f"• {item['Text'][:200]}")
        
        if result_parts:
            return f"🔍 **{query}**\n\n" + "\n\n".join(result_parts)
        
        return f"🔍 По запросу «{query}» ничего конкретного не найдено. Попробуй уточнить."
    except Exception as e:
        return f"❌ Ошибка поиска: {e}"


def get_crypto_prices() -> str:
    """Получает курсы криптовалют"""
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP"]
    results = []
    
    for sym in symbols:
        try:
            r = http.get(f"https://api.coinbase.com/v2/prices/{sym}-USD/spot", timeout=5)
            r.raise_for_status()
            amount = float(r.json()["data"]["amount"])
            results.append(f"• **{sym}**: ${amount:,.2f}")
        except Exception:
            results.append(f"• **{sym}**: недоступно")
    
    return "💰 **Курсы криптовалют**\n\n" + "\n".join(results)


def crypto_price(sym: str = "BTC") -> str:
    try:
        r = http.get(f"https://api.coinbase.com/v2/prices/{sym.upper()}-USD/spot", timeout=8)
        r.raise_for_status()
        amount = float(r.json()["data"]["amount"])
        return f"💰 **{sym.upper()}**: ${amount:,.2f}"
    except Exception as e:
        return f"❌ Ошибка получения курса {sym}: {e}"


# =========================================================
# AI AGENTS SYSTEM
# =========================================================

AGENTS = [
    {
        "emoji": "🎯",
        "name": "Аналитик",
        "role": """Проанализируй задачу:
1. Чётко сформулируй что нужно сделать
2. Определи основные компоненты
3. Выбери технологии с обоснованием
4. Опиши структуру проекта
5. Укажи потенциальные сложности"""
    },
    {
        "emoji": "💻",
        "name": "Разработчик",
        "role": """Напиши ПОЛНЫЙ рабочий код:
1. Весь необходимый код без пропусков
2. Правильная структура файлов
3. Type hints и docstrings
4. Обработка ошибок
5. Конфиги и зависимости"""
    },
    {
        "emoji": "🔍",
        "name": "Ревьюер",
        "role": """Проверь код разработчика:
1. Найди баги и логические ошибки
2. Проверь edge cases
3. Оцени код на чистоту
4. Предложи конкретные улучшения
5. Проверь корректность работы"""
    },
    {
        "emoji": "🔒",
        "name": "Безопасник",
        "role": """Проверь безопасность:
1. SQL injection, XSS, CSRF
2. Хардкод секретов
3. Валидация входных данных
4. Права доступа
5. Дай исправления если нужно"""
    },
    {
        "emoji": "🚀",
        "name": "DevOps",
        "role": """Опиши деплой:
1. Dockerfile если нужен
2. Переменные окружения
3. Команды запуска
4. Деплой на Railway/Heroku/VPS
5. Мониторинг и логи"""
    },
]


def run_agents(description: str, update_status) -> dict:
    """Запускает команду AI агентов"""
    results = {}
    history = []
    
    for i, agent in enumerate(AGENTS, 1):
        progress = "🟩" * i + "⬜" * (len(AGENTS) - i)
        update_status(f"{progress} {i}/{len(AGENTS)}\n{agent['emoji']} **{agent['name']}** работает...")
        
        context = "\n\n---\n\n".join(history[-2:]) if history else ""
        
        system = f"""
Ты {agent['name']} в команде разработки.

{agent['role']}

{'Предыдущий контекст:' + chr(10) + context if context else ''}

Будь конкретным. Давай готовые решения, не обещания.
Код оформляй в ```язык блоки.
"""
        
        try:
            response = ai_call(
                description,
                system=system,
                temperature=0.5,
                max_output_tokens=8192
            )
            results[agent['name']] = response
            history.append(f"**{agent['name']}**:\n{response[:3000]}")
        except Exception as e:
            results[agent['name']] = f"❌ Ошибка: {e}"
        
        time.sleep(0.5)
    
    return results


def finalize_project(bundle: dict, description: str) -> str:
    """Финальная сборка проекта"""
    
    combined = "\n\n---\n\n".join([
        f"## {name}\n{content}" 
        for name, content in bundle.items()
    ])
    
    system = """
Ты финальный архитектор-сборщик.
Объедини результаты всех агентов в один качественный ответ.

ФОРМАТ ОТВЕТА:
## 📋 Что делает проект
(краткое описание)

## 🏗 Структура
(дерево файлов)

## 💻 Код
(весь код по файлам, каждый файл в своём ```язык блоке)

## 🚀 Запуск
(команды для запуска)

## ☁️ Деплой
(инструкция деплоя)

## 📝 Примечания
(важное)

ВАЖНО: Дай ПОЛНЫЙ РАБОЧИЙ код. Не "и так далее", не "добавьте здесь".
"""
    
    prompt = f"""
Задача: {description}

Результаты агентов:
{combined}

Собери финальный ответ с полным рабочим кодом.
"""
    
    return ai_call_with_retry(
        prompt,
        system=system,
        temperature=0.4,
        max_output_tokens=16000,
        min_length=500,
        require_code=True
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(role: str = "user"):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("🚀 Проект"),
        types.KeyboardButton("💻 Код"),
        types.KeyboardButton("🐛 Дебаг"),
        types.KeyboardButton("📖 Объясни"),
        types.KeyboardButton("📁 Файл"),
        types.KeyboardButton("🧠 Режим"),
        types.KeyboardButton("💰 Крипта"),
        types.KeyboardButton("🔍 Поиск"),
        types.KeyboardButton("📊 Статус"),
        types.KeyboardButton("🔄 Сброс"),
    ]
    if role in ("admin", "premium"):
        buttons.append(types.KeyboardButton("👑 Админ"))
    kb.add(*buttons)
    return kb


def mode_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(f"{v}", callback_data=f"mode_{k}")
        for k, v in MODES.items()
    ]
    kb.add(*buttons)
    return kb


def project_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏️ Доработать", callback_data="proj_edit"),
        types.InlineKeyboardButton("📦 ZIP", callback_data="proj_zip"),
        types.InlineKeyboardButton("📋 Список", callback_data="proj_list"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data="proj_delete"),
    )
    return kb


def file_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Проверить", callback_data="file_check"),
        types.InlineKeyboardButton("🐛 Баги", callback_data="file_bugs"),
        types.InlineKeyboardButton("📖 Объяснить", callback_data="file_explain"),
        types.InlineKeyboardButton("✨ Улучшить", callback_data="file_improve"),
        types.InlineKeyboardButton("🔒 Безопасность", callback_data="file_security"),
        types.InlineKeyboardButton("📝 Документация", callback_data="file_docs"),
    )
    return kb


# =========================================================
# COMMANDS
# =========================================================

@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid = m.from_user.id
    username = m.from_user.username or ""
    role = get_role(uid, username)
    get_user(uid, username)
    
    bot.send_message(
        m.chat.id,
        f"""
👋 Привет, **{m.from_user.first_name}**!

Я **AI Code Assistant** v{VERSION}

🔥 Что я умею:
• Писать полный рабочий код
• Исправлять ошибки и дебажить
• Объяснять код простым языком
• Рефакторить и улучшать
• Анализировать файлы
• Создавать проекты командой AI-агентов
• Генерировать ZIP с проектом

⚡ Быстрый старт:
Просто напиши задачу или отправь код

📚 Команды: /help
""".strip(),
        parse_mode="Markdown",
        reply_markup=main_keyboard(role),
    )


@bot.message_handler(commands=["help"])
def cmd_help(m):
    bot.send_message(
        m.chat.id,
        """
📚 **Команды**

**Основные:**
/start - Начало
/help - Помощь
/mode - Выбор режима
/new - Новый диалог
/limit - Лимит запросов

**Создание:**
/project - Создать проект
/code - Режим "только код"
/debug - Режим дебага

**Файлы:**
Просто отправь файл документом

**Premium:**
/premium - Информация

**Админ:**
/stats - Статистика
/setlimit - Установить лимит
/setpremium - Дать premium
/broadcast - Рассылка

💡 **Примеры запросов:**
• Напиши Telegram-бота для заявок
• Исправь ошибку: [код с ошибкой]
• Объясни что делает этот код
• Сделай REST API на FastAPI
""".strip(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["new"])
def cmd_new(m):
    uid = m.from_user.id
    clear_memory(uid)
    bot.reply_to(m, "✅ Начинаем новый диалог. Память очищена.")


@bot.message_handler(commands=["reset"])
def cmd_reset(m):
    uid = m.from_user.id
    clear_memory(uid)
    bot.reply_to(m, "✅ Память, файлы и режим сброшены.")


@bot.message_handler(commands=["mode"])
def cmd_mode(m):
    bot.send_message(
        m.chat.id,
        "🧠 **Выбери режим работы:**",
        parse_mode="Markdown",
        reply_markup=mode_keyboard()
    )


@bot.message_handler(commands=["code"])
def cmd_code_mode(m):
    uid = m.from_user.id
    user_modes[uid] = "code"
    msg = bot.send_message(m.chat.id, "💻 Режим «Только код» активирован.\nОпиши что нужно написать:")
    bot.register_next_step_handler(msg, handle_code_request)


@bot.message_handler(commands=["debug"])
def cmd_debug_mode(m):
    uid = m.from_user.id
    user_modes[uid] = "debug"
    msg = bot.send_message(m.chat.id, "🐛 Режим дебага активирован.\nОтправь код с ошибкой или traceback:")
    bot.register_next_step_handler(msg, handle_debug_request)


@bot.message_handler(commands=["limit"])
def cmd_limit(m):
    uid = m.from_user.id
    username = m.from_user.username or ""
    role = get_role(uid, username)
    today = date.today()
    used = usage.get(uid, {}).get(today, 0)
    limit = get_limit(uid, username)
    
    bot.reply_to(
        m,
        f"""
📊 **Твой лимит**

Роль: {role}
Сегодня: {used}/{limit}
Осталось: {max(0, limit - used)}
""".strip(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["premium"])
def cmd_premium(m):
    bot.reply_to(
        m,
        f"""
⭐ **Premium подписка**

Преимущества:
• {PREMIUM_LIMIT} запросов в день (вместо {FREE_LIMIT})
• Приоритетная обработка
• Расширенные лимиты файлов

Для получения напиши админу.
Реквизиты: `{CARD_NUMBER}`
""".strip(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["project"])
def cmd_project(m):
    msg = bot.send_message(
        m.chat.id,
        """
🚀 **Создание проекта**

Опиши проект подробно:
• Что должен делать
• Какие функции нужны
• Какой стек (или "на твой выбор")
• Особые требования

Примеры:
• Telegram-бот для записи на услуги
• REST API для todo-листа на FastAPI
• Парсер товаров с сайта
• Discord бот с командами
""".strip(),
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_project)


@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    if not is_admin(m.from_user.username or ""):
        return bot.reply_to(m, "⛔ Нет доступа")
    
    uptime = datetime.now() - datetime.fromisoformat(stats["start_time"])
    
    bot.reply_to(
        m,
        f"""
👑 **Статистика бота**

👥 Пользователей: {stats['users']}
📨 Всего запросов: {stats['total']}
✅ Успешных: {stats['ok']}
❌ Ошибок: {stats['err']}
🚀 Проектов: {stats['projects']}
📁 Файлов: {stats['files_analyzed']}

⏱ Uptime: {uptime}
🔧 Версия: {VERSION}
""".strip(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["setlimit"])
def cmd_setlimit(m):
    if not is_admin(m.from_user.username or ""):
        return bot.reply_to(m, "⛔ Нет доступа")
    
    parts = (m.text or "").split()
    if len(parts) != 3:
        return bot.reply_to(m, "Использование: /setlimit <user_id> <limit>")
    
    try:
        uid = int(parts[1])
        limit = int(parts[2])
        get_user(uid)["limit"] = limit
        bot.reply_to(m, f"✅ Лимит для {uid}: {limit}")
    except Exception as e:
        bot.reply_to(m, f"❌ Ошибка: {e}")


@bot.message_handler(commands=["setpremium"])
def cmd_setpremium(m):
    if not is_admin(m.from_user.username or ""):
        return bot.reply_to(m, "⛔ Нет доступа")
    
    parts = (m.text or "").split()
    if len(parts) != 2:
        return bot.reply_to(m, "Использование: /setpremium <user_id>")
    
    try:
        uid = int(parts[1])
        get_user(uid)["role"] = "premium"
        bot.reply_to(m, f"✅ Premium для {uid} активирован")
    except Exception as e:
        bot.reply_to(m, f"❌ Ошибка: {e}")


@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(m):
    if not is_admin(m.from_user.username or ""):
        return bot.reply_to(m, "⛔ Нет доступа")
    
    text = (m.text or "").replace("/broadcast", "", 1).strip()
    if not text:
        return bot.reply_to(m, "Использование: /broadcast <текст>")
    
    sent = 0
    for uid in list(users.keys()):
        try:
            bot.send_message(uid, f"📢 **Объявление**\n\n{text}", parse_mode="Markdown")
            sent += 1
            time.sleep(0.05)
        except Exception:
            pass
    
    bot.reply_to(m, f"✅ Отправлено: {sent}")


# =========================================================
# BUTTON HANDLERS
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🚀 Проект")
def btn_project(m):
    cmd_project(m)


@bot.message_handler(func=lambda m: m.text == "💻 Код")
def btn_code(m):
    cmd_code_mode(m)


@bot.message_handler(func=lambda m: m.text == "🐛 Дебаг")
def btn_debug(m):
    cmd_debug_mode(m)


@bot.message_handler(func=lambda m: m.text == "📖 Объясни")
def btn_explain(m):
    uid = m.from_user.id
    user_modes[uid] = "explain"
    msg = bot.send_message(m.chat.id, "📖 Отправь код или концепцию для объяснения:")
    bot.register_next_step_handler(msg, handle_explain_request)


@bot.message_handler(func=lambda m: m.text == "📁 Файл")
def btn_file(m):
    bot.send_message(m.chat.id, "📁 Отправь файл с кодом документом (не фото).")


@bot.message_handler(func=lambda m: m.text == "🧠 Режим")
def btn_mode(m):
    cmd_mode(m)


@bot.message_handler(func=lambda m: m.text == "💰 Крипта")
def btn_crypto(m):
    typing_action(m.chat.id)
    bot.send_message(m.chat.id, get_crypto_prices(), parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == "🔍 Поиск")
def btn_search(m):
    msg = bot.send_message(m.chat.id, "🔍 Что найти?")
    bot.register_next_step_handler(msg, handle_search)


@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def btn_status(m):
    uid = m.from_user.id
    username = m.from_user.username or ""
    u = get_user(uid, username)
    role = get_role(uid, username)
    today = date.today()
    used = usage.get(uid, {}).get(today, 0)
    limit = get_limit(uid, username)
    mode = user_modes.get(uid, "auto")
    
    bot.send_message(
        m.chat.id,
        f"""
📊 **Твой статус**

👤 Роль: {role}
🧠 Режим: {MODES.get(mode, mode)}
📨 Запросов всего: {u['n']}
🚀 Проектов: {u['proj']}
📁 Файлов: {u['files']}
📅 Сегодня: {used}/{limit}
""".strip(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "🔄 Сброс")
def btn_reset(m):
    uid = m.from_user.id
    clear_memory(uid)
    bot.reply_to(m, "✅ Память диалога очищена.")


@bot.message_handler(func=lambda m: m.text == "👑 Админ")
def btn_admin(m):
    if not is_admin(m.from_user.username or ""):
        return
    cmd_stats(m)


# =========================================================
# CALLBACK HANDLERS
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("mode_"))
def cb_mode(c):
    uid = c.from_user.id
    mode = c.data[5:]
    user_modes[uid] = mode
    
    bot.answer_callback_query(c.id, f"Режим: {MODES.get(mode, mode)}")
    bot.edit_message_text(
        f"✅ Режим **{MODES.get(mode, mode)}** активирован",
        c.message.chat.id,
        c.message.message_id,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("proj_"))
def cb_project(c):
    uid = c.from_user.id
    action = c.data[5:]
    
    if action == "zip":
        if uid not in projects or not projects[uid]:
            return bot.answer_callback_query(c.id, "❌ Нет проектов")
        
        bot.answer_callback_query(c.id, "📦 Создаю архив...")
        try:
            project = projects[uid][-1]  # Последний проект
            data = make_project_zip(project)
            bot.send_document(
                c.message.chat.id,
                data,
                visible_file_name=f"project_{uid}_{int(time.time())}.zip"
            )
        except Exception as e:
            bot.send_message(c.message.chat.id, f"❌ Ошибка: {e}")
    
    elif action == "edit":
        bot.answer_callback_query(c.id)
        msg = bot.send_message(c.message.chat.id, "✏️ Что изменить/добавить?")
        bot.register_next_step_handler(msg, handle_project_edit)
    
    elif action == "list":
        bot.answer_callback_query(c.id)
        user_projects = projects.get(uid, [])
        if not user_projects:
            return bot.send_message(c.message.chat.id, "📋 Нет сохранённых проектов")
        
        text = "📋 **Твои проекты:**\n\n"
        for i, p in enumerate(user_projects, 1):
            desc = p.get("description", "Без описания")[:50]
            text += f"{i}. {desc}...\n"
        
        bot.send_message(c.message.chat.id, text, parse_mode="Markdown")
    
    elif action == "delete":
        if uid in projects and projects[uid]:
            projects[uid].pop()
            bot.answer_callback_query(c.id, "🗑 Последний проект удалён")
        else:
            bot.answer_callback_query(c.id, "❌ Нет проектов")


@bot.callback_query_handler(func=lambda c: c.data.startswith("file_"))
def cb_file(c):
    uid = c.from_user.id
    username = c.from_user.username or ""
    action = c.data[5:]
    
    ok, err = can_use(uid, username)
    if not ok:
        bot.answer_callback_query(c.id)
        return bot.send_message(c.message.chat.id, err)
    
    if uid not in files:
        return bot.answer_callback_query(c.id, "❌ Файл не найден. Отправь заново.")
    
    file_data = files[uid]
    code = file_data["code"][:MAX_FILE_SIZE]
    name = file_data["name"]
    
    prompts = {
        "check": f"Проведи code review файла {name}. Найди проблемы: архитектурные, логические, стилистические.",
        "bugs": f"Найди ВСЕ баги и потенциальные ошибки в файле {name}. Дай исправленный код.",
        "explain": f"Объясни простым языком что делает файл {name}. Разбери по частям.",
        "improve": f"Улучши код файла {name}: рефакторинг, оптимизация, читаемость. Дай полный улучшенный код.",
        "security": f"Проверь безопасность файла {name}: уязвимости, утечки данных, инъекции.",
        "docs": f"Напиши документацию для файла {name}: docstrings, README секция, примеры использования.",
    }
    
    if action not in prompts:
        return bot.answer_callback_query(c.id, "❌ Неизвестное действие")
    
    bot.answer_callback_query(c.id, "⏳ Анализирую...")
    typing_action(c.message.chat.id)
    
    system = """
Ты senior developer и code reviewer.
Анализируй код тщательно.
Давай конкретные рекомендации.
Если даёшь исправления - показывай полный исправленный код.
"""
    
    prompt = f"""
{prompts[action]}
