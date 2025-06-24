import os
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime
import aiohttp
import asyncio

# Настройки бота
TOKEN = "8164381436:AAGfqtB4y9pjlg7rMzPAysMPsqixaUFVvZA"
ADMIN_IDS = [6790535634, 6303872304]
SITE_URL = "http://golld-stend.tilda.ws"
MIN_WITHDRAW = 250
MAX_WITHDRAW = 400
REFERRAL_BONUS = 4
TELEGRAM_CHANNEL = "https://t.me/promolllGoldfreelll"
API_URL = "https://your-site.onrender.com/api"  # Замените на ваш URL

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация и миграция БД
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT,
                      balance INTEGER DEFAULT 0,
                      referrals INTEGER DEFAULT 0,
                      banned BOOLEAN DEFAULT FALSE,
                      reg_date TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS promocodes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      code TEXT UNIQUE,
                      gold INTEGER,
                      max_activations INTEGER,
                      activations_left INTEGER,
                      is_active BOOLEAN DEFAULT TRUE)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS activations
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      promo_id INTEGER,
                      activated_at TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      amount INTEGER,
                      status TEXT,
                      avatar_id TEXT,
                      screenshot_id TEXT,
                      created_at TIMESTAMP,
                      completed_at TIMESTAMP,
                      feedback_given BOOLEAN DEFAULT FALSE)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS feedbacks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      transaction_id INTEGER,
                      text TEXT,
                      photo_id TEXT,
                      created_at TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def migrate_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'feedback_given' not in columns:
            cursor.execute("ALTER TABLE transactions ADD COLUMN feedback_given BOOLEAN DEFAULT FALSE")
        
        cursor.execute("PRAGMA table_info(feedbacks)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'transaction_id' not in columns:
            cursor.execute("ALTER TABLE feedbacks ADD COLUMN transaction_id INTEGER")
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка миграции БД: {e}")
    finally:
        conn.close()

init_db()
migrate_db()

# Состояния FSM
class WithdrawState(StatesGroup):
    AMOUNT = State()
    AVATAR = State()
    SCREENSHOT = State()

class PromoCodeState(StatesGroup):
    ENTER_CODE = State()

class AdminState(StatesGroup):
    ADD_PROMO = State()
    BAN_USER = State()
    UNBAN_USER = State()
    SEND_ANNOUNCE = State()

class FeedbackState(StatesGroup):
    TEXT = State()

# Клавиатуры
def get_main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("👤 Мой профиль", "💸 Вывести голду")
    keyboard.row("🎁 Активировать промокод", "📊 История выводов")
    keyboard.row("🌐 Наш сайт")
    return keyboard

def get_admin_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("📊 Статистика", "📢 Рассылка")
    keyboard.row("🔨 Забанить/Разбанить", "🎁 Добавить промо")
    keyboard.row("◀️ В меню")
    return keyboard

def get_back_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("◀️ Назад")
    return keyboard

def get_feedback_keyboard(transaction_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    feedback_given = True
    
    try:
        cursor.execute("SELECT feedback_given FROM transactions WHERE id = ?", (transaction_id,))
        result = cursor.fetchone()
        feedback_given = result[0] if result else True
    except Exception as e:
        logging.error(f"Ошибка проверки отзыва: {e}")
    
    conn.close()
    
    keyboard = types.InlineKeyboardMarkup()
    if not feedback_given:
        keyboard.row(
            types.InlineKeyboardButton("📝 Оставить отзыв", callback_data=f"leave_feedback_{transaction_id}"),
            types.InlineKeyboardButton("❌ Не сейчас", callback_data=f"no_feedback_{transaction_id}")
        )
    return keyboard

def get_ban_unban_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("🔨 Забанить пользователя")
    keyboard.row("🔓 Разбанить пользователя")
    keyboard.row("◀️ Назад")
    return keyboard

# Вспомогательные функции
def get_user_balance(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

async def generate_referral_link(user_id):
    bot_username = (await bot.get_me()).username
    return f"https://t.me/{bot_username}?start=ref{user_id}"

async def wake_up_server():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL.replace('/api', '')}/wakeup") as resp:
                logging.info(f"Server wakeup response: {resp.status}")
    except Exception as e:
        logging.error(f"Error waking up server: {e}")

# Обработчики команд
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await wake_up_server()  # Пробуждаем сервер при каждом старте
    
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Обработка реферальной ссылки
    ref_id = None
    if len(message.text) > 7 and 'ref' in message.text:
        try:
            ref_id = int(message.text.split('ref')[1])
        except (ValueError, IndexError):
            pass
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Проверка бана
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if user and user[0]:
        await message.answer("🚫 Вы заблокированы в системе")
        conn.close()
        return
    
    # Регистрация нового пользователя
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, reg_date) VALUES (?, ?, ?, ?)",
            (user_id, username, 0, datetime.now())
        )
        
        # Обработка реферала
        if ref_id and ref_id != user_id:
            try:
                cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (ref_id,))
                if cursor.fetchone():
                    cursor.execute("SELECT 1 FROM referrals WHERE referral_id = ?", (user_id,))
                    if not cursor.fetchone():
                        cursor.execute(
                            "INSERT INTO referrals (referrer_id, referral_id, created_at) VALUES (?, ?, ?)",
                            (ref_id, user_id, datetime.now())
                        )
                        cursor.execute(
                            "UPDATE users SET referrals = referrals + 1, balance = balance + ? WHERE user_id = ?",
                            (REFERRAL_BONUS, ref_id)
                        )
                        cursor.execute(
                            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                            (REFERRAL_BONUS, user_id)
                        )
                        
                        try:
                            await bot.send_message(
                                ref_id,
                                f"🎉 Новый реферал! @{username} присоединился по вашей ссылке!\n"
                                f"Ваш баланс пополнен на {REFERRAL_BONUS} голды"
                            )
                        except:
                            pass
                        
                        try:
                            await bot.send_message(
                                user_id,
                                f"🎉 Вы зарегистрировались по реферальной ссылке!\n"
                                f"Ваш баланс пополнен на {REFERRAL_BONUS} голды"
                            )
                        except:
                            pass
            except sqlite3.IntegrityError:
                pass
    
    conn.commit()
    conn.close()
    
    await message.answer(
        f"👋 Добро пожаловать, @{username}!\n\n"
        f"💎 Ваш баланс: {get_user_balance(user_id)} голды\n"
        f"🔗 Не знаешь где найти промокод для фарма голды? Подпишись на телеграм канал: {TELEGRAM_CHANNEL}\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=get_main_menu()
    )
    await message.answer(
        f"🌐 Для входа в личный кабинет на сайте используйте ваш Telegram ID:\n"
        f"<code>{user_id}</code>\n\n"
        f"Сайт: {SITE_URL}",
        parse_mode="HTML"
    )

# ... (все остальные обработчики из оригинального скрипта остаются без изменений)

# Новый обработчик для пробуждения сервера
@dp.message_handler(commands=['wakeup'])
async def cmd_wakeup(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await wake_up_server()
    await message.answer("Сервер пробужден")

# Запуск бота
async def on_startup(dp):
    await wake_up_server()
    asyncio.create_task(periodic_wakeup())

async def periodic_wakeup():
    while True:
        await asyncio.sleep(300)  # Каждые 5 минут
        await wake_up_server()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)