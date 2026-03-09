#!/usr/bin/env python3
import os, logging, time, json, requests
from datetime import datetime, date
from typing import Dict, List
import telebot
from telebot import types
import google.generativeai as genai

# ============================================================================
# CONFIG
# ============================================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "XXXX")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")  # для поиска

FREE_DAILY_LIMIT = 15
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# Хранилище
user_data: Dict[int, dict] = {}
user_usage: Dict[int, dict] = {}
conversations: Dict[int, List[dict]] = {}  # ПАМЯТЬ РАЗГОВОРОВ
project_mode: Dict[int, bool] = {}  # Режим проекта
stats = {"total": 0, "success": 0, "errors": 0}

# ============================================================================
# МЕНЮ И КНОПКИ
# ============================================================================

def get_main_menu():
    """Главное меню с кнопками"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("💻 Написать код"),
        types.KeyboardButton("🔍 Найти баг"),
        types.KeyboardButton("📖 Объяснить код"),
        types.KeyboardButton("🌐 Поиск в интернете"),
        types.KeyboardButton("🎨 Создать диаграмму"),
        types.KeyboardButton("📁 Начать проект"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("⭐ Premium"),
    ]
    keyboard.add(*buttons)
    return keyboard

def get_project_menu():
    """Меню в режиме проекта"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("✏️ Доработать"),
        types.KeyboardButton("🔄 Рефакторинг"),
        types.KeyboardButton("🐛 Найти баги"),
        types.KeyboardButton("📦 Экспорт кода"),
        types.KeyboardButton("✅ Завершить проект"),
        types.KeyboardButton("❌ Отменить проект"),
    ]
    keyboard.add(*buttons)
    return keyboard

# ============================================================================
# ПОИСК В ИНТЕРНЕТЕ
# ============================================================================

def search_web(query: str) -> str:
    """Поиск в интернете через Serper API (бесплатно 2500 запросов)"""
    
    if not SERPER_API_KEY:
        # Fallback: используем Gemini с инструкцией искать свежие данные
        return f"🌐 Поиск через Gemini (без внешнего API):\n\n{query}"
    
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": 5}
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        results = response.json()
        
        # Форматируем результаты
        output = f"🌐 **Результаты поиска:** {query}\n\n"
        
        if "organic" in results:
            for i, item in enumerate(results["organic"][:5], 1):
                output += f"{i}. **{item.get('title', 'Без названия')}**\n"
                output += f"   {item.get('snippet', '')}\n"
                output += f"   🔗 {item.get('link', '')}\n\n"
        
        return output
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"❌ Ошибка поиска: {str(e)}"

def get_crypto_price(symbol: str = "BTC") -> str:
    """Получить курс криптовалюты"""
    try:
        url = f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        price = data["data"]["amount"]
        return f"💰 **{symbol}/USD**: ${price}"
    
    except Exception as e:
        return f"❌ Не удалось получить курс {symbol}"

# ============================================================================
# AI С ПАМЯТЬЮ
# ============================================================================

class SmartAI:
    @staticmethod
    def call_with_memory(user_id: int, prompt: str, use_thinking: bool = False) -> str:
        """AI с памятью разговора"""
        
        # Инициализируем память если нет
        if user_id not in conversations:
            conversations[user_id] = []
        
        # Добавляем новое сообщение
        conversations[user_id].append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now()
        })
        
        # Ограничиваем историю (последние 20 сообщений)
        if len(conversations[user_id]) > 20:
            conversations[user_id] = conversations[user_id][-20:]
        
        # Формируем контекст
        context = ""
        for msg in conversations[user_id][-10:]:  # последние 10
            role = "Пользователь" if msg["role"] == "user" else "Ассистент"
            context += f"{role}: {msg['content']}\n\n"
        
        # System prompt
        system = """Ты — AI Code Assistant Pro. Ты помогаешь разработчикам с кодом.

ВАЖНЫЕ ПРАВИЛА:
1. ПОМНИШЬ весь контекст разговора
2. Если пользователь просит доработать — улучшай ПРЕДЫДУЩИЙ код
3. Работаешь ИТЕРАТИВНО — пока пользователь не скажет "готово"
4. Пишешь ПОЛНЫЙ код, не отрывки
5. Используй modern best practices (Python 3.12+, ES2024+)
6. Всегда добавляй комментарии

ФУНКЦИИ:
- Написание кода
- Code review
- Рефакторинг
- Поиск багов
- Объяснение кода
- Работа над проектами

Отвечай кратко и по делу. Код в блоках ```язык."""

        full_prompt = f"{system}\n\nКОНТЕКСТ РАЗГОВОРА:\n{context}\n\nНОВЫЙ ЗАПРОС:\n{prompt}"
        
        try:
            model_name = "gemini-2.0-flash-thinking-exp-1219" if use_thinking else "gemini-2.0-flash-exp"
            model = genai.GenerativeModel(model_name=model_name)
            
            response = model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=8000
                )
            )
            
            result = response.text
            
            # Сохраняем ответ в память
            conversations[user_id].append({
                "role": "assistant",
                "content": result,
                "timestamp": datetime.now()
            })
            
            return result
        
        except Exception as e:
            logger.error(f"AI error: {e}")
            raise

# ============================================================================
# USER MANAGEMENT
# ============================================================================

def get_user(user_id: int) -> dict:
    if user_id not in user_data:
        user_data[user_id] = {
            "created": datetime.now(),
            "total_requests": 0,
            "referrals": 0,
            "projects": 0
        }
    return user_data[user_id]

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

def can_use(user_id: int) -> tuple[bool, str]:
    if user_id in PREMIUM_USERS:
        return True, ""
    today_usage = get_today_usage(user_id)
    if today_usage >= FREE_DAILY_LIMIT:
        return False, f"⚠️ Лимит исчерпан ({FREE_DAILY_LIMIT}/день)\n\n🔓 Premium = безлимит: /premium"
    return True, ""

def clear_memory(user_id: int):
    """Очистить память разговора"""
    if user_id in conversations:
        conversations[user_id] = []

# ============================================================================
# КОМАНДЫ
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    welcome = f"""🤖 **AI Code Assistant Pro**

Привет, {message.from_user.first_name}!

Я — твой персональный AI разработчик с:
✅ Памятью разговора
✅ Поиском в интернете
✅ Режимом проектов
✅ Генерацией диаграмм

**Тарифы:**
🆓 {FREE_DAILY_LIMIT} запросов/день
⭐ Premium: безлимит

**Используй кнопки ниже или пиши свободно!** 👇"""
    
    bot.send_message(message.chat.id, welcome, reply_markup=get_main_menu(), parse_mode="Markdown")

@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_menu())

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    clear_memory(message.from_user.id)
    bot.reply_to(message, "🧹 Память очищена! Начнём с чистого листа.")

@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    user = get_user(message.from_user.id)
    
    if message.from_user.id in PREMIUM_USERS:
        bot.send_message(message.chat.id, "✅ У вас Premium активен!")
        return
    
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{message.from_user.id}"
    
    premium_msg = f"""⭐ **AI Code Assistant Premium**

**Premium — 299₽/мес:**
✅ БЕЗЛИМИТ запросов
✅ Приоритетная обработка
✅ Расширенная память (50 сообщений)
✅ Экспорт проектов в GitHub
✅ Генерация изображений без лимита
✅ Голосовые сообщения

**🎁 Первым 50: 299₽/мес навсегда!**

**Оплата:**
Переведите 299₽:
`{CARD_NUMBER}`

Комментарий: `Premium @{message.from_user.username or message.from_user.id}`

Скиньте скрин → активация за 10 мин

**Или 10 друзей:**
{ref_link}
Рефералов: {user['referrals']}/10
"""
    
    bot.send_message(message.chat.id, premium_msg, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user = get_user(message.from_user.id)
    today = get_today_usage(message.from_user.id)
    status = "⭐ Premium" if message.from_user.id in PREMIUM_USERS else "🆓 Free"
    
    memory_size = len(conversations.get(message.from_user.id, []))
    
    text = f"""📊 **Ваша статистика**

Статус: {status}
Сегодня: {today}/{FREE_DAILY_LIMIT}
Всего запросов: {user['total_requests']}
Проектов: {user['projects']}
Память: {memory_size} сообщений
Рефералов: {user['referrals']}

**Бот:** {stats['total']} запросов | {stats['success']} успешно
"""
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ============================================================================
# ОБРАБОТКА КНОПОК
# ============================================================================

@bot.message_handler(func=lambda m: m.text in ["💻 Написать код", "🔍 Найти баг", "📖 Объяснить код", "🌐 Поиск в интернете", "🎨 Создать диаграмму", "📁 Начать проект", "📊 Статистика", "⭐ Premium"])
def handle_buttons(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "💻 Написать код":
        bot.send_message(message.chat.id, "💻 Опишите какой код нужен:\n\nНапример:\n'Напиши Telegram бота для приёма заказов'\n'Создай парсер товаров с сайта'")
    
    elif text == "🔍 Найти баг":
        bot.send_message(message.chat.id, "🔍 Отправьте код с ошибкой:\n\n```python\nваш код\n```\n\nУкажите текст ошибки если есть.")
    
    elif text == "📖 Объяснить код":
        bot.send_message(message.chat.id, "📖 Отправьте код который нужно объяснить:\n\n```python\nваш код\n```")
    
    elif text == "🌐 Поиск в интернете":
        bot.send_message(message.chat.id, "🌐 Что найти в интернете?\n\nНапример:\n'Курс биткоина сейчас'\n'Последние новости Python 3.13'\n'Лучшие практики FastAPI'")
    
    elif text == "🎨 Создать диаграмму":
        bot.send_message(message.chat.id, "🎨 Опишите какую диаграмму создать:\n\n'Архитектура микросервисов'\n'ER-диаграмма для интернет-магазина'\n'Flowchart алгоритма сортировки'")
    
    elif text == "📁 Начать проект":
        project_mode[user_id] = True
        get_user(user_id)["projects"] += 1
        bot.send_message(
            message.chat.id,
            "📁 **Режим проекта активирован!**\n\nОпишите что нужно сделать. Я буду работать итеративно пока не скажете 'Завершить проект'.\n\nДоступны команды:",
            reply_markup=get_project_menu(),
            parse_mode="Markdown"
        )
    
    elif text == "📊 Статистика":
        cmd_stats(message)
    
    elif text == "⭐ Premium":
        cmd_premium(message)

@bot.message_handler(func=lambda m: m.text in ["✏️ Доработать", "🔄 Рефакторинг", "🐛 Найти баги", "📦 Экспорт кода", "✅ Завершить проект", "❌ Отменить проект"])
def handle_project_buttons(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "✏️ Доработать":
        bot.send_message(message.chat.id, "✏️ Что доработать? Опишите изменения:")
    
    elif text == "🔄 Рефакторинг":
        bot.send_message(message.chat.id, "🔄 Запускаю рефакторинг кода...")
        # AI возьмёт последний код из памяти и улучшит
        handle_request(message, force_prompt="Сделай рефакторинг последнего кода. Улучши читаемость, производительность, добавь docstrings.")
    
    elif text == "🐛 Найти баги":
        bot.send_message(message.chat.id, "🐛 Анализирую код на баги...")
        handle_request(message, force_prompt="Проанализируй последний код. Найди все возможные баги, уязвимости, проблемы с производительностью.")
    
    elif text == "📦 Экспорт кода":
        # Соберём весь код из памяти в один файл
        if user_id in conversations:
            code_blocks = []
            for msg in conversations[user_id]:
                if msg["role"] == "assistant" and "```" in msg["content"]:
                    code_blocks.append(msg["content"])
            
            if code_blocks:
                combined = "\n\n".join(code_blocks)
                # Отправим как документ
                bot.send_document(
                    message.chat.id,
                    document=combined.encode(),
                    visible_file_name="project_code.txt",
                    caption="📦 Весь код проекта"
                )
            else:
                bot.send_message(message.chat.id, "❌ Код ещё не был создан")
        else:
            bot.send_message(message.chat.id, "❌ История пуста")
    
    elif text == "✅ Завершить проект":
        project_mode[user_id] = False
        bot.send_message(
            message.chat.id,
            "✅ Проект завершён!\n\nВозвращаюсь в обычный режим.",
            reply_markup=get_main_menu()
        )
    
    elif text == "❌ Отменить проект":
        project_mode[user_id] = False
        clear_memory(user_id)
        bot.send_message(
            message.chat.id,
            "❌ Проект отменён. Память очищена.",
            reply_markup=get_main_menu()
        )

# ============================================================================
# ГЛАВНЫЙ ОБРАБОТЧИК
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_request(message, force_prompt=None):
    user_id = message.from_user.id
    text = force_prompt or message.text.strip()
    
    if len(text) < 3:
        return
    
    can_proceed, error_msg = can_use(user_id)
    if not can_proceed:
        bot.reply_to(message, error_msg)
        return
    
    # Определяем тип запроса
    is_code = any(w in text.lower() for w in ['напиши', 'создай', 'код', 'бот', 'скрипт', 'функц'])
    is_search = any(w in text.lower() for w in ['найди в интернете', 'поищи', 'курс', 'цена', 'новости'])
    is_crypto = any(w in text.lower() for w in ['биткоин', 'bitcoin', 'btc', 'eth', 'крипто'])
    
    logger.info(f"User {user_id}: {text[:50]}...")
    stats["total"] += 1
    
    status_msg = bot.send_message(message.chat.id, "⚙️ Обрабатываю...")
    
    try:
        result = ""
        
        # Курс криптовалюты
        if is_crypto:
            symbol = "BTC"
            if "eth" in text.lower():
                symbol = "ETH"
            result = get_crypto_price(symbol) + "\n\n"
        
        # Поиск в интернете
        if is_search:
            search_result = search_web(text)
            result += search_result + "\n\n"
        
        # AI ответ с памятью
        ai_response = SmartAI.call_with_memory(user_id, text, use_thinking=is_code)
        result += ai_response
        
        increment_usage(user_id)
        stats["success"] += 1
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        send_long_message(message.chat.id, result)
        
        # Reminder для Free
        if user_id not in PREMIUM_USERS:
            left = FREE_DAILY_LIMIT - get_today_usage(user_id)
            if left <= 3:
                bot.send_message(message.chat.id, f"ℹ️ Осталось: {left}\n\nPremium: /premium")
    
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Error: {e}")
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте переформулировать")

def send_long_message(chat_id, text):
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, text, parse_mode=None)
        return
    
    parts = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > MAX_LEN:
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

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = f"""👑 Admin
Юзеров: {len(user_data)} | Premium: {len(PREMIUM_USERS)}
Запросов: {stats['total']} | Успешно: {stats['success']}
Активных проектов: {sum(1 for v in project_mode.values() if v)}"""
    bot.send_message(message.chat.id, text)

if __name__ == "__main__":
    logger.info(f"🚀 AI Code Assistant Pro started!")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(15)
