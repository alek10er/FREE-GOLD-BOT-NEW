import os
import logging
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime
from aiohttp import ClientSession
import secrets

# Настройки бота
TOKEN = os.getenv("8164381436:AAGfqtB4y9pjlg7rMzPAysMPsqixaUFVvZA")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "6790535634,6303872304").split(",")))
SITE_URL = os.getenv("SITE_URL", "https://free-gold-bot-new.onrender.com")
MIN_WITHDRAW = 250
MAX_WITHDRAW = 400
REFERRAL_BONUS = 4
TELEGRAM_CHANNEL = "https://t.me/promolllGoldfreelll"
API_KEY = os.getenv("API_KEY", "secure_api_key_123")

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def wake_up_server():
    """Функция для пробуждения сервера на Render"""
    try:
        async with ClientSession() as session:
            async with session.get(f"{SITE_URL}/wake-up") as response:
                if response.status == 200:
                    logger.info("Сервер успешно пробужден")
                else:
                    logger.warning("Не удалось пробудить сервер")
    except Exception as e:
        logger.error(f"Ошибка при пробуждении сервера: {e}")

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT,
                      balance INTEGER DEFAULT 0,
                      referrals INTEGER DEFAULT 0,
                      banned BOOLEAN DEFAULT FALSE,
                      reg_date TIMESTAMP,
                      auth_token TEXT)''')
    
    # Таблица промокодов
    cursor.execute('''CREATE TABLE IF NOT EXISTS promocodes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      code TEXT UNIQUE,
                      gold INTEGER,
                      max_activations INTEGER,
                      activations_left INTEGER,
                      is_active BOOLEAN DEFAULT TRUE)''')
    
    # Таблица активаций промокодов
    cursor.execute('''CREATE TABLE IF NOT EXISTS activations
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      promo_id INTEGER,
                      activated_at TIMESTAMP)''')
    
    # Таблица транзакций
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
    
    # Таблица отзывов
    cursor.execute('''CREATE TABLE IF NOT EXISTS feedbacks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      transaction_id INTEGER,
                      text TEXT,
                      photo_id TEXT,
                      created_at TIMESTAMP)''')
    
    # Таблица рефералов
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      referrer_id INTEGER,
                      referral_id INTEGER UNIQUE,
                      created_at TIMESTAMP)''')
    
    conn.commit()
    conn.close()

init_db()

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
    keyboard.row("🌐 Личный кабинет")
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
    keyboard = types.InlineKeyboardMarkup()
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
async def generate_auth_token(user_id):
    """Генерация токена для авторизации на сайте"""
    token = secrets.token_hex(16)
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET auth_token = ? WHERE user_id = ?", (token, user_id))
    conn.commit()
    conn.close()
    return token

async def get_user_balance(user_id):
    """Получение баланса пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

async def generate_referral_link(user_id):
    """Генерация реферальной ссылки"""
    bot_username = (await bot.get_me()).username
    return f"https://t.me/{bot_username}?start=ref{user_id}"

async def sync_with_website(user_id, action, data=None):
    """Синхронизация с веб-сайтом"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT auth_token FROM users WHERE user_id = ?", (user_id,))
        token = cursor.fetchone()[0]
        
        headers = {
            "Authorization": f"Bearer {token}",
            "X-API-KEY": API_KEY
        }
        
        async with ClientSession() as session:
            if action == "login":
                await session.post(
                    f"{SITE_URL}/api/login", 
                    json={"user_id": user_id}, 
                    headers=headers
                )
            elif action == "withdraw":
                await session.post(
                    f"{SITE_URL}/api/transactions", 
                    json=data, 
                    headers=headers
                )
            elif action == "update_balance":
                await session.patch(
                    f"{SITE_URL}/api/users/{user_id}", 
                    json=data, 
                    headers=headers
                )
    except Exception as e:
        logger.error(f"Ошибка синхронизации с сайтом: {e}")

# Обработчики команд
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await wake_up_server()
    
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
        auth_token = await generate_auth_token(user_id)
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, reg_date, auth_token) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, 0, datetime.now(), auth_token)
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
                        except Exception as e:
                            logger.error(f"Не удалось отправить сообщение рефереру: {e}")
                        
                        try:
                            await bot.send_message(
                                user_id,
                                f"🎉 Вы зарегистрировались по реферальной ссылке!\n"
                                f"Ваш баланс пополнен на {REFERRAL_BONUS} голды"
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить сообщение рефералу: {e}")
            except sqlite3.IntegrityError:
                pass
    
    conn.commit()
    conn.close()
    
    # Синхронизация с сайтом
    await sync_with_website(user_id, "login")
    
    await message.answer(
        f"👋 Добро пожаловать, @{username}!\n\n"
        f"💎 Ваш баланс: {await get_user_balance(user_id)} голды\n"
        f"🔗 Не знаешь где найти промокод для фарма голды? Подпишись на телеграм канал: {TELEGRAM_CHANNEL}\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=get_main_menu()
    )

@dp.message_handler(text="◀️ В меню")
async def back_to_menu(message: types.Message):
    """Возврат в главное меню"""
    await message.answer("Главное меню:", reply_markup=get_main_menu())

# Профиль пользователя
@dp.message_handler(text="👤 Мой профиль")
async def my_profile(message: types.Message):
    """Отображение профиля пользователя"""
    user_id = message.from_user.id
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT balance, referrals FROM users WHERE user_id = ?", 
        (user_id,)
    )
    user_data = cursor.fetchone()
    
    if not user_data:
        await message.answer("❌ Профиль не найден")
        conn.close()
        return
    
    balance, referrals = user_data
    
    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND status = 'completed'",
        (user_id,)
    )
    withdrawals = cursor.fetchone()[0]
    
    conn.close()
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("🔗 Реферальная ссылка", callback_data="ref_link"),
        types.InlineKeyboardButton("📤 Мои выводы", callback_data="my_withdrawals")
    )
    
    await message.answer(
        f"👤 Ваш профиль:\n\n"
        f"💰 Баланс: {balance} голды\n"
        f"👥 Рефералов: {referrals} (+{referrals * REFERRAL_BONUS} голды)\n"
        f"📤 Выводов: {withdrawals}",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == "ref_link")
async def show_ref_link(callback_query: types.CallbackQuery):
    """Показ реферальной ссылки"""
    user_id = callback_query.from_user.id
    link = await generate_referral_link(user_id)
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=f"👥 Реферальная программа:\n\n"
             f"🔗 Ваша ссылка: {link}\n\n"
             f"💎 За каждого приглашенного друга вы получаете {REFERRAL_BONUS} голды!\n"
             f"💰 Ваш другу тоже получает бонус при регистрации!",
        reply_markup=None
    )

@dp.callback_query_handler(lambda c: c.data == "my_withdrawals")
async def show_my_withdrawals(callback_query: types.CallbackQuery):
    """Показ истории выводов"""
    user_id = callback_query.from_user.id
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, amount, status, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    )
    transactions = cursor.fetchall()
    conn.close()
    
    if not transactions:
        await bot.answer_callback_query(callback_query.id, "📊 У вас еще нет выводов")
        return
    
    response = "📤 Ваши последние выводы:\n\n"
    for trans in transactions:
        trans_id, amount, status, created_at = trans
        status_icon = "✅" if status == "completed" else "🕒" if status == "pending" else "❌"
        response += f"{status_icon} #{trans_id}: {amount} голды ({status}) - {created_at}\n"
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=response,
        reply_markup=None
    )

# История выводов
@dp.message_handler(text="📊 История выводов")
async def show_history(message: types.Message):
    """Отображение истории выводов"""
    user_id = message.from_user.id
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, amount, status, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    )
    transactions = cursor.fetchall()
    
    if not transactions:
        await message.answer("📊 У вас еще нет выводов")
        return
    
    response = "📊 Последние выводы:\n\n"
    for trans in transactions:
        trans_id, amount, status, created_at = trans
        status_icon = "✅" if status == "completed" else "🕒" if status == "pending" else "❌"
        response += f"{status_icon} #{trans_id}: {amount} голды ({status}) - {created_at}\n"
    
    await message.answer(response)

# Личный кабинет
@dp.message_handler(text="🌐 Личный кабинет")
async def personal_account(message: types.Message):
    """Отправка ссылки на личный кабинет"""
    user_id = message.from_user.id
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT auth_token FROM users WHERE user_id = ?", (user_id,))
    token = cursor.fetchone()[0]
    conn.close()
    
    login_url = f"{SITE_URL}/login?token={token}&user_id={user_id}"
    
    await message.answer(
        f"🔐 Ваш личный кабинет:\n\n"
        f"Перейдите по ссылке для входа:\n"
        f"{login_url}\n\n"
        f"В личном кабинете вы можете:\n"
        f"- Просматривать историю транзакций\n"
        f"- Управлять настройками аккаунта\n"
        f"- Получать статистику",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("📲 Открыть кабинет", url=login_url)
        )
    )

# Активация промокода
@dp.message_handler(text="🎁 Активировать промокод")
async def activate_promo_start(message: types.Message):
    """Начало процесса активации промокода"""
    await PromoCodeState.ENTER_CODE.set()
    await message.answer("🔑 Введите промокод:", reply_markup=get_back_menu())

@dp.message_handler(state=PromoCodeState.ENTER_CODE)
async def process_promo_code(message: types.Message, state: FSMContext):
    """Обработка введенного промокода"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Главное меню:", reply_markup=get_main_menu())
        return
        
    promo_code = message.text.upper()
    user_id = message.from_user.id
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM promocodes WHERE code = ?", (promo_code,))
        promo = cursor.fetchone()
        
        if not promo:
            await message.answer("❌ Промокод не найден")
            return
        
        promo_id, code, gold, max_activations, activations_left, is_active = promo
        
        if not is_active:
            await message.answer("❌ Промокод деактивирован")
            return
            
        if activations_left <= 0:
            await message.answer("❌ Лимит активаций исчерпан")
            return
            
        cursor.execute("SELECT * FROM activations WHERE user_id = ? AND promo_id = ?", (user_id, promo_id))
        if cursor.fetchone():
            await message.answer("❌ Вы уже активировали этот промокод")
            return
            
        cursor.execute(
            "UPDATE promocodes SET activations_left = activations_left - 1 WHERE id = ?",
            (promo_id,)
        )
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (gold, user_id)
        )
        cursor.execute(
            "INSERT INTO activations (user_id, promo_id, activated_at) VALUES (?, ?, ?)",
            (user_id, promo_id, datetime.now())
        )
        
        conn.commit()
        
        # Синхронизация с сайтом
        await sync_with_website(user_id, "update_balance", {"balance": await get_user_balance(user_id)})
        
        await message.answer(
            f"🎉 Промокод активирован! +{gold} голды\n"
            f"Ваш баланс: {await get_user_balance(user_id)} голды",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()
        await state.finish()

# Вывод голды
@dp.message_handler(text="💸 Вывести голду")
async def withdraw_start(message: types.Message):
    """Начало процесса вывода"""
    user_id = message.from_user.id
    balance = await get_user_balance(user_id)
    
    if balance < MIN_WITHDRAW:
        await message.answer(
            f"❌ Минимальная сумма вывода: {MIN_WITHDRAW} голды\n"
            f"💰 Ваш баланс: {balance} голды"
        )
        return
    
    await WithdrawState.AMOUNT.set()
    await message.answer(
        f"💰 Ваш баланс: {balance} голды\n"
        f"Введите сумму для вывода ({MIN_WITHDRAW}-{MAX_WITHDRAW}):",
        reply_markup=get_back_menu()
    )

@dp.message_handler(state=WithdrawState.AMOUNT)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    """Обработка суммы вывода"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Главное меню:", reply_markup=get_main_menu())
        return
    
    try:
        amount = int(message.text)
        if amount < MIN_WITHDRAW or amount > MAX_WITHDRAW:
            raise ValueError
    except ValueError:
        await message.answer(
            f"❌ Неверная сумма. Введите число от {MIN_WITHDRAW} до {MAX_WITHDRAW}"
        )
        return
    
    user_id = message.from_user.id
    balance = await get_user_balance(user_id)
    
    if balance < amount:
        await message.answer("❌ Недостаточно средств на балансе")
        await state.finish()
        return
    
    await state.update_data(amount=amount)
    await WithdrawState.AVATAR.set()
    await message.answer("📸 Пришлите фото вашего профиля (аватар):")

@dp.message_handler(content_types=['photo'], state=WithdrawState.AVATAR)
async def process_avatar(message: types.Message, state: FSMContext):
    """Обработка аватара для вывода"""
    photo_id = message.photo[-1].file_id
    await state.update_data(avatar_id=photo_id)
    await WithdrawState.SCREENSHOT.set()
    await message.answer("📊 Теперь пришлите скриншот с торговой площадки:")

@dp.message_handler(content_types=['photo'], state=WithdrawState.SCREENSHOT)
async def process_screenshot(message: types.Message, state: FSMContext):
    """Обработка скриншота и завершение вывода"""
    user_id = message.from_user.id
    username = message.from_user.username
    screenshot_id = message.photo[-1].file_id
    data = await state.get_data()
    amount = data['amount']
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO transactions (user_id, amount, status, avatar_id, screenshot_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, amount, 'pending', data['avatar_id'], screenshot_id, datetime.now())
        )
        trans_id = cursor.lastrowid
        
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (amount, user_id)
        )
        
        conn.commit()
        
        # Синхронизация с сайтом
        await sync_with_website(user_id, "withdraw", {
            "transaction_id": trans_id,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        })
        
        await sync_with_website(user_id, "update_balance", {"balance": await get_user_balance(user_id)})
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                admin_msg = (
                    f"🆕 Новый запрос на вывод #ID{trans_id}\n\n"
                    f"👤 Пользователь: @{username} (ID: {user_id})\n"
                    f"💰 Сумма: {amount} голды\n"
                    f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                )
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(
                    types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{trans_id}"),
                    types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{trans_id}")
                )
                
                await bot.send_message(admin_id, admin_msg, reply_markup=keyboard)
                await bot.send_photo(admin_id, data['avatar_id'])
                await bot.send_photo(admin_id, screenshot_id)
            except Exception as e:
                logger.error(f"Error notifying admin {admin_id}: {e}")
                continue
        
        await message.answer(
            "✅ Ваш запрос на вывод отправлен администратору.\n"
            "Ожидайте подтверждения!",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()
        await state.finish()

# Админ-панель
@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    """Отображение админ-панели"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("👮‍♂️ Панель администратора", reply_markup=get_admin_menu())

@dp.message_handler(text="📊 Статистика")
async def admin_stats(message: types.Message):
    """Отображение статистики для админа"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(balance) FROM users")
    total_gold = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM referrals")
    total_refs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'completed'")
    completed_withdrawals = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE status = 'completed'")
    total_withdrawn = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
    pending_withdrawals = cursor.fetchone()[0]
    
    conn.close()
    
    await message.answer(
        f"📊 Статистика системы:\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🚫 Заблокировано: {banned_users}\n"
        f"💰 Всего голды: {total_gold}\n"
        f"👥 Рефералов: {total_refs}\n\n"
        f"💸 Выводов:\n"
        f"✅ Завершено: {completed_withdrawals} (Σ{total_withdrawn} голды)\n"
        f"🕒 Ожидает: {pending_withdrawals}",
        reply_markup=get_admin_menu()
    )

@dp.message_handler(text="🎁 Добавить промо")
async def add_promo_start(message: types.Message):
    """Добавление нового промокода"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.ADD_PROMO.set()
    await message.answer(
        "Введите данные промокода в формате:\n"
        "<code>НАЗВАНИЕ КОЛИЧЕСТВО_ГОЛДЫ КОЛИЧЕСТВО_АКТИВАЦИЙ</code>\n\n"
        "Пример: <code>SUMMER2023 100 50</code>",
        reply_markup=get_back_menu(),
        parse_mode="HTML"
    )

@dp.message_handler(state=AdminState.ADD_PROMO)
async def process_add_promo(message: types.Message, state: FSMContext):
    """Обработка добавления промокода"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Админ-меню:", reply_markup=get_admin_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            raise ValueError("Неверный формат")
        
        code = parts[0].upper()
        gold = int(parts[1])
        activations = int(parts[2])
        
        conn = None
        try:
            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            
            cursor.execute(
                "INSERT INTO promocodes (code, gold, max_activations, activations_left) VALUES (?, ?, ?, ?)",
                (code, gold, activations, activations)
            )
            
            conn.commit()
            await message.answer(
                f"✅ Промокод добавлен:\n"
                f"🔑 Код: {code}\n"
                f"💰 Голда: {gold}\n"
                f"🔄 Активаций: {activations}",
                reply_markup=get_admin_menu()
            )
        except sqlite3.IntegrityError:
            await message.answer("❌ Такой промокод уже существует")
        except Exception as e:
            await message.answer(f"❌ Ошибка базы данных: {str(e)}")
        finally:
            if conn:
                conn.close()
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте: НАЗВАНИЕ ГОЛДА АКТИВАЦИИ")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        await state.finish()

@dp.message_handler(text="🔨 Забанить/Разбанить")
async def ban_unban_menu(message: types.Message):
    """Меню бана/разбана"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("Выберите действие:", reply_markup=get_ban_unban_menu())

@dp.message_handler(text="🔨 Забанить пользователя")
async def ban_user_start(message: types.Message):
    """Начало процесса бана"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.BAN_USER.set()
    await message.answer(
        "Введите ID пользователя для блокировки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(text="🔓 Разбанить пользователя")
async def unban_user_start(message: types.Message):
    """Начало процесса разбана"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.UNBAN_USER.set()
    await message.answer(
        "Введите ID пользователя для разблокировки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(state=AdminState.BAN_USER)
async def process_ban_user(message: types.Message, state: FSMContext):
    """Обработка бана пользователя"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Админ-меню:", reply_markup=get_admin_menu())
        return
    
    try:
        user_id = int(message.text)
        
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        cursor.execute(
            "UPDATE users SET banned = TRUE WHERE user_id = ?",
            (user_id,)
        )
        
        conn.commit()
        
        try:
            await bot.send_message(
                user_id,
                "🚫 Вы были заблокированы в системе. Обратитесь к администратору."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        await message.answer(
            f"✅ Пользователь @{user[0]} (ID: {user_id}) заблокирован",
            reply_markup=get_admin_menu()
        )
    except ValueError:
        await message.answer("❌ Введите числовой ID пользователя")
    finally:
        conn.close()
        await state.finish()

@dp.message_handler(state=AdminState.UNBAN_USER)
async def process_unban_user(message: types.Message, state: FSMContext):
    """Обработка разбана пользователя"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Админ-меню:", reply_markup=get_admin_menu())
        return
    
    try:
        user_id = int(message.text)
        
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        cursor.execute(
            "UPDATE users SET banned = FALSE WHERE user_id = ?",
            (user_id,)
        )
        
        conn.commit()
        
        try:
            await bot.send_message(
                user_id,
                "✅ Вы были разблокированы в системе. Теперь вы можете снова пользоваться ботом."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        await message.answer(
            f"✅ Пользователь @{user[0]} (ID: {user_id}) разблокирован",
            reply_markup=get_admin_menu()
        )
    except ValueError:
        await message.answer("❌ Введите числовой ID пользователя")
    finally:
        conn.close()
        await state.finish()

@dp.message_handler(text="📢 Рассылка")
async def announce_start(message: types.Message):
    """Начало рассылки"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.SEND_ANNOUNCE.set()
    await message.answer(
        "Введите сообщение для рассылки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(state=AdminState.SEND_ANNOUNCE)
async def process_announce(message: types.Message, state: FSMContext):
    """Обработка рассылки"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Админ-меню:", reply_markup=get_admin_menu())
        return
    
    conn = None
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM users WHERE banned = FALSE")
        users = cursor.fetchall()
        
        success = 0
        fails = 0
        
        for user in users:
            try:
                await bot.send_message(user[0], message.text)
                success += 1
            except:
                fails += 1
        
        await message.answer(
            f"📢 Рассылка завершена:\n"
            f"✅ Успешно: {success}\n"
            f"❌ Не удалось: {fails}",
            reply_markup=get_admin_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        if conn:
            conn.close()
        await state.finish()

# Обработка выводов админом
@dp.callback_query_handler(lambda c: c.data.startswith('confirm_'))
async def confirm_withdrawal(callback_query: types.CallbackQuery):
    """Подтверждение вывода администратором"""
    if callback_query.from_user.id not in ADMIN_IDS:
        return
    
    trans_id = int(callback_query.data.split('_')[1])
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT user_id, amount FROM transactions WHERE id = ? AND status = 'pending'",
            (trans_id,)
        )
        trans = cursor.fetchone()
        
        if not trans:
            await bot.answer_callback_query(
                callback_query.id,
                "Транзакция уже обработана или не найдена",
                show_alert=True
            )
            return
        
        user_id, amount = trans
        
        cursor.execute(
            "UPDATE transactions SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.now(), trans_id)
        )
        
        conn.commit()
        
        try:
            # Отправляем уведомление пользователю
            await bot.send_message(
                user_id,
                f"✅ Ваш вывод #{trans_id} на сумму {amount} голды подтвержден!",
                reply_markup=get_feedback_keyboard(trans_id)
            )
            
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"✅ Вывод #{trans_id} подтвержден",
            reply_markup=None
        )
        
        await bot.answer_callback_query(callback_query.id)
    except Exception as e:
        await bot.answer_callback_query(
            callback_query.id,
            f"Ошибка: {str(e)}",
            show_alert=True
        )
    finally:
        conn.close()

@dp.callback_query_handler(lambda c: c.data.startswith('reject_'))
async def reject_withdrawal(callback_query: types.CallbackQuery):
    """Отклонение вывода администратором"""
    if callback_query.from_user.id not in ADMIN_IDS:
        return
    
    trans_id = int(callback_query.data.split('_')[1])
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT user_id, amount FROM transactions WHERE id = ? AND status = 'pending'",
            (trans_id,)
        )
        trans = cursor.fetchone()
        
        if not trans:
            await bot.answer_callback_query(
                callback_query.id,
                "Транзакция уже обработана или не найдена",
                show_alert=True
            )
            return
        
        user_id, amount = trans
        
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id)
        )
        
        cursor.execute(
            "UPDATE transactions SET status = 'rejected' WHERE id = ?",
            (trans_id,)
        )
        
        conn.commit()
        
        # Синхронизация с сайтом
        await sync_with_website(user_id, "update_balance", {"balance": await get_user_balance(user_id)})
        
        try:
            # Отправляем уведомление пользователю
            await bot.send_message(
                user_id,
                f"❌ Ваш вывод #{trans_id} на сумму {amount} голды отклонен.\n"
                f"Средства возвращены на баланс."
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"❌ Вывод #{trans_id} отклонен",
            reply_markup=None
        )
        
        await bot.answer_callback_query(callback_query.id)
    except Exception as e:
        await bot.answer_callback_query(
            callback_query.id,
            f"Ошибка: {str(e)}",
            show_alert=True
        )
    finally:
        conn.close()

# Система отзывов
@dp.callback_query_handler(lambda c: c.data.startswith('leave_feedback_'))
async def start_feedback(callback_query: types.CallbackQuery, state: FSMContext):
    """Начало процесса оставления отзыва"""
    trans_id = int(callback_query.data.split('_')[2])
    
    # Проверяем, не оставлял ли уже пользователь отзыв на этот вывод
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT feedback_given FROM transactions WHERE id = ?", (trans_id,))
        result = cursor.fetchone()
        feedback_given = result[0] if result else True
    except Exception as e:
        logger.error(f"Ошибка проверки отзыва: {e}")
        feedback_given = True
    
    conn.close()
    
    if feedback_given:
        await bot.answer_callback_query(
            callback_query.id,
            "Вы уже оставили отзыв на этот вывод",
            show_alert=True
        )
        return
    
    await FeedbackState.TEXT.set()
    await state.update_data(transaction_id=trans_id)
    await bot.send_message(
        callback_query.from_user.id,
        "📝 Напишите ваш отзыв о работе бота:",
        reply_markup=get_back_menu()
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith('no_feedback_'))
async def skip_feedback(callback_query: types.CallbackQuery):
    """Пропуск оставления отзыва"""
    await bot.send_message(
        callback_query.from_user.id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=FeedbackState.TEXT, content_types=['text', 'photo'])
async def process_feedback(message: types.Message, state: FSMContext):
    """Обработка отзыва"""
    if message.text == "◀️ Назад":
        await state.finish()
        await message.answer("Главное меню:", reply_markup=get_main_menu())
        return
        
    user_id = message.from_user.id
    data = await state.get_data()
    transaction_id = data['transaction_id']
    text = message.text or message.caption
    photo_id = None
    
    if message.photo:
        photo_id = message.photo[-1].file_id
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем, не оставлял ли уже пользователь отзыв на этот вывод
        cursor.execute("SELECT feedback_given FROM transactions WHERE id = ?", (transaction_id,))
        result = cursor.fetchone()
        feedback_given = result[0] if result else True
        
        if feedback_given:
            await message.answer("❌ Вы уже оставили отзыв на этот вывод", reply_markup=get_main_menu())
            return
        
        # Сохраняем отзыв
        cursor.execute(
            "INSERT INTO feedbacks (user_id, transaction_id, text, photo_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, transaction_id, text, photo_id, datetime.now())
        )
        
        # Помечаем вывод как имеющий отзыв
        cursor.execute(
            "UPDATE transactions SET feedback_given = TRUE WHERE id = ?",
            (transaction_id,)
        )
        
        conn.commit()
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                msg = f"📝 Новый отзыв от @{message.from_user.username} (ID: {user_id}) на вывод #{transaction_id}:\n\n{text}"
                if photo_id:
                    await bot.send_photo(admin_id, photo_id, caption=msg)
                else:
                    await bot.send_message(admin_id, msg)
            except Exception as e:
                logger.error(f"Error sending feedback to admin {admin_id}: {e}")
        
        await message.answer(
            "✅ Спасибо за ваш отзыв!",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении отзыва: {str(e)}")
    finally:
        conn.close()
        await state.finish()

# Обработка всех сообщений для пробуждения сервера
@dp.message_handler()
async def wake_up_on_message(message: types.Message):
    """Обработка всех сообщений для пробуждения сервера"""
    await wake_up_server()
    await message.answer("Используйте кнопки меню для навигации", reply_markup=get_main_menu())

# Запуск бота
if __name__ == '__main__':
    from aiogram import executor
    logger.info("Бот запущен! Для остановки нажмите Ctrl+C")
    executor.start_polling(dp, skip_updates=True)