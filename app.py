import os
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
import secrets
import string
from threading import Thread

# Настройки бота
TOKEN = "8164381436:AAGfqtB4y9pjlg7rMzPAysMPsqixaUFVvZA"
ADMIN_IDS = [6790535634, 6303872304]  # Замените на ваш ID
SITE_URL = "http://your-site.com"
MIN_WITHDRAW = 250
MAX_WITHDRAW = 400
REFERRAL_BONUS = 4
TELEGRAM_CHANNEL = "https://t.me/@lllGoldso2freelll_bot"
WEBHOOK_URL = "https://free-gold-bot-new.onrender.com"
PORT = int(os.environ.get('PORT', 5000))

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация Flask
app = Flask(__name__)
app.secret_key = 'your-secret-key-123'

# Генерация кода подтверждения
def generate_confirmation_code(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))

# Инициализация БД
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT,
                      first_name TEXT,
                      last_name TEXT,
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
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      referrer_id INTEGER,
                      referral_id INTEGER UNIQUE,
                      created_at TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS web_sessions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      session_id TEXT,
                      confirmation_code TEXT,
                      created_at TIMESTAMP,
                      expires_at TIMESTAMP)''')
    
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
    keyboard.row("🌐 Наш сайт", "📱 Мини-приложение")
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

# Обработчики команд
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name or ""
    
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
            "INSERT INTO users (user_id, username, first_name, last_name, balance, reg_date) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, 0, datetime.now())
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
                            await bot.send_message(
                                user_id,
                                f"🎉 Вы зарегистрировались по реферальной ссылке!\n"
                                f"Ваш баланс пополнен на {REFERRAL_BONUS} голды"
                            )
                        except Exception as e:
                            logging.error(f"Ошибка отправки уведомления: {e}")
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

@dp.message_handler(text="◀️ В меню")
async def back_to_menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_menu())

# Мини-приложение
@dp.message_handler(text="📱 Мини-приложение")
async def mini_app(message: types.Message):
    user_id = message.from_user.id
    web_app = types.WebAppInfo(url=f"{WEBHOOK_URL}/web_app?user_id={user_id}")
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Открыть мини-приложение", web_app=web_app))
    
    await message.answer(
        "Нажмите кнопку ниже, чтобы открыть мини-приложение:",
        reply_markup=keyboard
    )

# Обработчики профиля
@dp.message_handler(text="👤 Мой профиль")
async def my_profile(message: types.Message):
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

# Активация промокода
@dp.message_handler(text="🎁 Активировать промокод")
async def activate_promo_start(message: types.Message):
    await PromoCodeState.ENTER_CODE.set()
    await message.answer("🔑 Введите промокод:", reply_markup=get_back_menu())

@dp.message_handler(state=PromoCodeState.ENTER_CODE)
async def process_promo_code(message: types.Message, state: FSMContext):
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
        await message.answer(
            f"🎉 Промокод активирован! +{gold} голды\n"
            f"Ваш баланс: {get_user_balance(user_id)} голды",
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
    user_id = message.from_user.id
    balance = get_user_balance(user_id)
    
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
    balance = get_user_balance(user_id)
    
    if balance < amount:
        await message.answer("❌ Недостаточно средств на балансе")
        await state.finish()
        return
    
    await state.update_data(amount=amount)
    await WithdrawState.AVATAR.set()
    await message.answer("📸 Пришлите фото вашего профиля (аватар):")

@dp.message_handler(content_types=['photo'], state=WithdrawState.AVATAR)
async def process_avatar(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(avatar_id=photo_id)
    await WithdrawState.SCREENSHOT.set()
    await message.answer("📊 Теперь пришлите скриншот с торговой площадки:")

@dp.message_handler(content_types=['photo'], state=WithdrawState.SCREENSHOT)
async def process_screenshot(message: types.Message, state: FSMContext):
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
                logging.error(f"Error notifying admin {admin_id}: {e}")
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
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("👮‍♂️ Панель администратора", reply_markup=get_admin_menu())

@dp.message_handler(text="📊 Статистика")
async def admin_stats(message: types.Message):
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
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("Выберите действие:", reply_markup=get_ban_unban_menu())

@dp.message_handler(text="🔨 Забанить пользователя")
async def ban_user_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.BAN_USER.set()
    await message.answer(
        "Введите ID пользователя для блокировки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(text="🔓 Разбанить пользователя")
async def unban_user_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.UNBAN_USER.set()
    await message.answer(
        "Введите ID пользователя для разблокировки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(lambda message: message.text == "◀️ Назад", state=[AdminState.BAN_USER, AdminState.UNBAN_USER])
async def cancel_ban_unban(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено", reply_markup=get_admin_menu())

@dp.message_handler(state=AdminState.BAN_USER)
async def process_ban_user(message: types.Message, state: FSMContext):
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
            logging.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
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
            logging.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
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
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await AdminState.SEND_ANNOUNCE.set()
    await message.answer(
        "Введите сообщение для рассылки:",
        reply_markup=get_back_menu()
    )

@dp.message_handler(state=AdminState.SEND_ANNOUNCE)
async def process_announce(message: types.Message, state: FSMContext):
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
            logging.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
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
        
        try:
            # Отправляем уведомление пользователю
            await bot.send_message(
                user_id,
                f"❌ Ваш вывод #{trans_id} на сумму {amount} голды отклонен.\n"
                f"Средства возвращены на баланс."
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
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
    trans_id = int(callback_query.data.split('_')[2])
    
    # Проверяем, не оставлял ли уже пользователь отзыв на этот вывод
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT feedback_given FROM transactions WHERE id = ?", (trans_id,))
        result = cursor.fetchone()
        feedback_given = result[0] if result else True
    except Exception as e:
        logging.error(f"Ошибка проверки отзыва: {e}")
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
    await bot.send_message(
        callback_query.from_user.id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=FeedbackState.TEXT, content_types=['text', 'photo'])
async def process_feedback(message: types.Message, state: FSMContext):
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
        
        # Сохраняем отзыв с указанием transaction_id
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
                logging.error(f"Error sending feedback to admin {admin_id}: {e}")
        
        await message.answer(
            "✅ Спасибо за ваш отзыв!",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении отзыва: {str(e)}")
    finally:
        conn.close()
        await state.finish()

# Flask роуты для мини-приложения
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/web_app')
def web_app():
    user_id = request.args.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return redirect(url_for('login'))
    
    # Создаем сессию для пользователя
    session_id = secrets.token_hex(16)
    confirmation_code = generate_confirmation_code()
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO web_sessions (user_id, session_id, confirmation_code, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, session_id, confirmation_code, datetime.now(), datetime.now().timestamp() + 3600)
    )
    conn.commit()
    conn.close()
    
    # Отправляем код подтверждения пользователю
    try:
        bot.send_message(
            user_id,
            f"🔑 Ваш код подтверждения для входа в мини-приложение: {confirmation_code}\n\n"
            "Введите этот код на сайте для продолжения."
        )
    except Exception as e:
        logging.error(f"Не удалось отправить код подтверждения: {e}")
    
    return render_template('confirm.html', user={
        'user_id': user[0],
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3]
    }, session_id=session_id)

@app.route('/confirm', methods=['POST'])
def confirm():
    user_id = request.form.get('user_id')
    session_id = request.form.get('session_id')
    code = request.form.get('code')
    
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM web_sessions WHERE user_id = ? AND session_id = ? AND confirmation_code = ? AND expires_at > ?",
        (user_id, session_id, code, datetime.now().timestamp())
    )
    session_data = cursor.fetchone()
    conn.close()
    
    if not session_data:
        flash("Неверный код подтверждения или срок действия истек", "error")
        return redirect(url_for('web_app', user_id=user_id))
    
    # Удаляем использованный код
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM web_sessions WHERE id = ?", (session_data[0],))
    conn.commit()
    conn.close()
    
    # Создаем новую сессию для пользователя
    session['user_id'] = user_id
    session['logged_in'] = True
    
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Получаем данные пользователя
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        session.clear()
        return redirect(url_for('login'))
    
    _, username, first_name, last_name, balance, referrals, banned, reg_date = user
    
    # Получаем историю выводов
    cursor.execute(
        "SELECT id, amount, status, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    )
    transactions = cursor.fetchall()
    
    # Получаем количество выводов
    cursor.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND status = 'completed'",
        (user_id,)
    )
    withdrawals_count = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template(
        'dashboard.html',
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=balance,
        referrals=referrals,
        withdrawals_count=withdrawals_count,
        transactions=transactions,
        is_admin=user_id in ADMIN_IDS
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Запуск Flask в отдельном потоке
def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Запуск бота
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print("Бот и мини-приложение запущены! Для остановки нажмите Ctrl+C")
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)