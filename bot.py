#!/usr/bin/env python3
import os, logging, time
from datetime import datetime, date
from typing import Dict
import telebot
import google.generativeai as genai
from groq import Groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "XXXX")

FREE_DAILY_LIMIT = 15
PREMIUM_USERS = set()
if os.environ.get("PREMIUM_USERS"):
    PREMIUM_USERS = set(map(int, os.environ["PREMIUM_USERS"].split(",")))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")
genai.configure(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

user_data: Dict[int, dict] = {}
user_usage: Dict[int, dict] = {}
stats = {"total": 0, "success": 0, "errors": 0}

class AIRouter:
    @staticmethod
    def call_gemini(prompt: str, thinking: bool = False) -> str:
        try:
            model_name = "gemini-2.0-flash-thinking-exp-1219" if thinking else "gemini-2.0-flash-exp"
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(prompt, generation_config=genai.GenerationConfig(temperature=0.7, max_output_tokens=8000))
            return response.text
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise
    
    @staticmethod
    def call_groq(prompt: str, system: str = "") -> str:
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, temperature=0.7, max_tokens=4000)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq error: {e}")
            raise
    
    @staticmethod
    def smart_call(prompt: str, is_code: bool = False) -> str:
        if is_code:
            models = [("Gemini", lambda p: AIRouter.call_gemini(p, thinking=True)), ("Groq", lambda p: AIRouter.call_groq(p, system="You are an expert programmer."))]
        else:
            models = [("Gemini", lambda p: AIRouter.call_gemini(p)), ("Groq", AIRouter.call_groq)]
        
        for model_name, model_func in models:
            try:
                logger.info(f"Trying {model_name}...")
                result = model_func(prompt)
                logger.info(f"{model_name} OK")
                return result
            except Exception as e:
                if models.index((model_name, model_func)) == len(models) - 1:
                    raise Exception(f"All models failed: {e}")
                continue

def get_user(user_id: int) -> dict:
    if user_id not in user_data:
        user_data[user_id] = {"created": datetime.now(), "total_requests": 0, "referrals": 0}
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

PROMPTS = {
    "code": "Ты senior разработчик. Пиши чистый production-ready код с комментариями. Формат: ```язык\nкод\n```",
    "review": "Ты code reviewer. Формат: **Оценка:** X/10\n**Проблемы:** [список]\n**Рекомендации:** [список]",
    "explain": "Ты преподаватель. Объясняй код просто: 1) цель, 2) разбор, 3) концепции, 4) применение"
}

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if message.text.startswith('/start ref_'):
        ref_id = message.text.split('_')[1]
        try:
            referrer_id = int(ref_id)
            if referrer_id != user_id and referrer_id in user_data:
                user_data[referrer_id]["referrals"] += 1
        except:
            pass
    
    welcome = f"""🤖 **AI Code Assistant**

Привет, {message.from_user.first_name}!

Я помогу с кодом:
💻 Написать бота/скрипт/парсер
🔍 Найти баги
📖 Объяснить код
✨ Рефакторинг

**Модели:** Gemini 2.0, Llama 3.3 70B

**Тарифы:**
🆓 {FREE_DAILY_LIMIT} запросов/день
⭐ Premium: безлимит — /premium

**Примеры:**
"Напиши ТГ бота для заказов"
"Найди баг в этом коде: [код]"

Начнём? 🚀"""
    
    bot.send_message(message.chat.id, welcome)

@bot.message_handler(commands=['premium'])
def cmd_premium(message):
    user = get_user(message.from_user.id)
    
    if message.from_user.id in PREMIUM_USERS:
        bot.send_message(message.chat.id, "✅ У вас Premium активен!")
        return
    
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{message.from_user.id}"
    
    premium_msg = f"""⭐ **AI Code Assistant Premium**

**Бесплатно:**
• {FREE_DAILY_LIMIT} запросов/день
• Базовые модели

**Premium — 299₽/мес:**
✅ БЕЗЛИМИТ запросов
✅ В 3 раза быстрее
✅ Лучшие модели
✅ Без рекламы

**🎁 Первым 50: 299₽/мес навсегда!**

**Оплата:**
1. Переведи 299₽ на карту:
   `{CARD_NUMBER}`
   
2. Комментарий: `Premium @{message.from_user.username or message.from_user.id}`

3. Скинь скрин платежа сюда

4. Активация за 10 минут

**Или 10 друзей = бесплатный Premium:**
{ref_link}
Рефералов: {user['referrals']}/10
"""
    
    bot.send_message(message.chat.id, premium_msg)

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user = get_user(message.from_user.id)
    today = get_today_usage(message.from_user.id)
    status = "⭐ Premium" if message.from_user.id in PREMIUM_USERS else "🆓 Free"
    
    text = f"""📊 **Статистика**

Статус: {status}
Сегодня: {today}/{FREE_DAILY_LIMIT}
Всего: {user['total_requests']}
Рефералов: {user['referrals']}

**Бот:** {stats['total']} запросов | {stats['success']} успешно
"""
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, """📖 **Справка**

💻 **Код:** "Напиши ТГ бота для заказов"
🔍 **Ревью:** "Проверь код: ```python\\n[код]\\n```"
🐛 **Баги:** "Ошибка [текст]: ```python\\n[код]\\n```"
📖 **Объяснение:** "Объясни: ```js\\n[код]\\n```"

/start | /help | /premium | /stats""")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_request(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if len(text) < 10:
        bot.reply_to(message, "✏️ Опишите задачу подробнее")
        return
    
    can_proceed, error_msg = can_use(user_id)
    if not can_proceed:
        bot.reply_to(message, error_msg)
        return
    
    is_code = any(w in text.lower() for w in ['напиши', 'создай', 'код', 'бот', 'скрипт'])
    
    logger.info(f"User {user_id}: {text[:50]}...")
    stats["total"] += 1
    
    status_msg = bot.send_message(message.chat.id, "⚙️ Обрабатываю...\n⏱ 10-30 сек")
    
    try:
        if is_code:
            prompt = f"{PROMPTS['code']}\n\n{text}"
        elif 'проверь' in text.lower():
            prompt = f"{PROMPTS['review']}\n\n{text}"
        elif 'объясни' in text.lower():
            prompt = f"{PROMPTS['explain']}\n\n{text}"
        else:
            prompt = text
        
        response = AIRouter.smart_call(prompt, is_code=is_code)
        
        increment_usage(user_id)
        stats["success"] += 1
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
        
        send_long_message(message.chat.id, response)
        
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
        bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте переформулировать или повторить через минуту")

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
    text = f"""👑 Admin\nЮзеров: {len(user_data)} | Premium: {len(PREMIUM_USERS)}\nЗапросов: {stats['total']} | Успешно: {stats['success']}"""
    bot.send_message(message.chat.id, text)

if __name__ == "__main__":
    logger.info(f"🚀 AI Code Assistant started! Free: {FREE_DAILY_LIMIT}/day | Premium: {len(PREMIUM_USERS)}")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(15)
