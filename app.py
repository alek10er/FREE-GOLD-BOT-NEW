from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import os
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key-123')
app.config['API_KEY'] = os.getenv('API_KEY', 'secure_api_key_123')

# Инициализация LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, balance, referrals):
        self.id = id
        self.username = username
        self.balance = balance
        self.referrals = referrals

def get_db_connection():
    conn = sqlite3.connect('bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get('X-API-KEY') != app.config['API_KEY']:
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user = conn.execute(
        'SELECT user_id, username, balance, referrals FROM users WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if user:
        return User(user['user_id'], user['username'], user['balance'], user['referrals'])
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/wake-up')
def wake_up():
    return jsonify({"status": "awake"}), 200

@app.route('/login')
def login():
    token = request.args.get('token')
    user_id = request.args.get('user_id')
    
    if not token or not user_id:
        flash('Неверная ссылка для входа', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    db_token = conn.execute(
        'SELECT auth_token FROM users WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if not db_token or token != db_token['auth_token']:
        flash('Неверный токен авторизации', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    user_data = conn.execute(
        'SELECT user_id, username, balance, referrals FROM users WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if user_data:
        user = User(user_data['user_id'], user_data['username'], user_data['balance'], user_data['referrals'])
        login_user(user)
        return redirect(url_for('dashboard'))
    
    flash('Пользователь не найден', 'error')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    
    # Получаем последние 5 транзакций
    transactions = conn.execute(
        '''SELECT id, amount, status, created_at 
           FROM transactions 
           WHERE user_id = ? 
           ORDER BY created_at DESC 
           LIMIT 5''',
        (current_user.id,)
    ).fetchall()
    
    # Получаем реферальную статистику
    referrals_count = conn.execute(
        'SELECT COUNT(*) FROM referrals WHERE referrer_id = ?',
        (current_user.id,)
    ).fetchone()[0]
    
    conn.close()
    
    return render_template(
        'dashboard.html',
        user=current_user,
        transactions=transactions,
        referrals_count=referrals_count,
        referral_bonus=4
    )

@app.route('/transactions')
@login_required
def transactions():
    conn = get_db_connection()
    transactions = conn.execute(
        '''SELECT id, amount, status, created_at, completed_at 
           FROM transactions 
           WHERE user_id = ? 
           ORDER BY created_at DESC''',
        (current_user.id,)
    ).fetchall()
    conn.close()
    
    return render_template('transactions.html', transactions=transactions)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# API Endpoints
@app.route('/api/login', methods=['POST'])
@api_key_required
def api_login():
    data = request.get_json()
    user_id = data.get('user_id')
    
    conn = get_db_connection()
    user_exists = conn.execute(
        'SELECT 1 FROM users WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if not user_exists:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({"status": "success"}), 200

@app.route('/api/users/<int:user_id>', methods=['PATCH'])
@api_key_required
def update_user(user_id):
    data = request.get_json()
    balance = data.get('balance')
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET balance = ? WHERE user_id = ?',
        (balance, user_id)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success"}), 200

@app.route('/api/transactions', methods=['POST'])
@api_key_required
def create_transaction():
    data = request.get_json()
    
    conn = get_db_connection()
    conn.execute(
        '''INSERT INTO transactions 
           (user_id, amount, status, created_at) 
           VALUES (?, ?, ?, ?)''',
        (data['user_id'], data['amount'], data['status'], data['created_at'])
    )
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success"}), 201

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', error="Страница не найдена"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', error="Доступ запрещен"), 403

@app.errorhandler(500)
def internal_error(e):
    return render_template('error.html', error="Внутренняя ошибка сервера"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)