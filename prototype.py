# Прототип первой версии системы SAINT
# Требования: Python 3, Flask, SQLAlchemy, NLTK (для парсинга)
# Установка: pip install flask sqlalchemy nltk
# Запуск: python app.py
# Доступ: http://127.0.0.1:5000/
# Для простоты: Внутренняя БД - SQLite, внешняя БД - симулирована в памяти.
# Первая версия: Загрузка .txt, парсинг простых команд "Перевести поезд X с платформы A на платформу B",
# Проверка в симулированной БД, отчет о выполнимости.

import os
import re
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import nltk
from nltk.tokenize import word_tokenize

# NLTK setup
nltk.download('punkt', quiet=True)

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saint.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Модели БД (на основе ER-модели, упрощено)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, nullable=False)  # 1: Operator, 2: Admin
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    raw_text = db.Column(db.Text, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class AnalysisResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'Выполнимо' or 'Не выполнимо'
    details = db.Column(db.Text)
    execution_plan = db.Column(db.Text)  # JSON-like string
    analyzed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Симулированная внешняя БД (для теста, в реальности - подключение к SQL)
simulated_db = {
    'trains': [
        {'train_number': '123', 'status': 'на платформе 1'},
        {'train_number': '456', 'status': 'в пути'}
    ],
    'platforms': [
        {'platform_number': '1', 'is_occupied': True},
        {'platform_number': '5', 'is_occupied': False}
    ]
}

# Простая онтология и правила (хардкод для первой версии)
ontology = {
    'Поезд': {'db_table': 'trains', 'attributes': {'Номер': 'train_number'}},
    'Платформа': {'db_table': 'platforms', 'attributes': {'Номер': 'platform_number', 'Занятость': 'is_occupied'}}
}

rules = [
    {
        'name': 'Проверка перевода поезда',
        'conditions': [
            {'entity': 'Поезд', 'check': 'exists'},
            {'entity': 'Платформа', 'attribute': 'Занятость', 'value': False}
        ],
        'conclusion': {'status': 'Выполнимо', 'plan': ['Шаг 1: Освободить текущую платформу.', 'Шаг 2: Перевести поезд.', 'Шаг 3: Зафиксировать на новой платформе.']}
    }
]

# Функции backend
def parse_text(text):
    # Простой парсинг: Ищем шаблон "Перевести поезд №X с платформы A на платформу B"
    match = re.search(r'Перевести поезд №(\d+) с платформы (\d+) на платформу (\d+)', text)
    if match:
        return {
            'action': 'Перевести',
            'train_number': match.group(1),
            'from_platform': match.group(2),
            'to_platform': match.group(3)
        }
    return None

def query_external_db(table, field, value):
    # Симуляция запроса
    data = simulated_db.get(table, [])
    for item in data:
        if item.get(field) == value:
            return item
    return None

def apply_rules(entities):
    # Простой логический вывод
    train = query_external_db('trains', 'train_number', entities['train_number'])
    platform = query_external_db('platforms', 'platform_number', entities['to_platform'])
    
    if train and platform and not platform['is_occupied']:
        return {'status': 'Выполнимо', 'details': 'Все условия соблюдены.', 'plan': '\n'.join(rules[0]['conclusion']['plan'])}
    else:
        reason = []
        if not train: reason.append('Поезд не существует.')
        if not platform: reason.append('Платформа не существует.')
        if platform and platform['is_occupied']: reason.append('Платформа занята.')
        return {'status': 'Не выполнимо', 'details': ' '.join(reason), 'plan': None}

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']  # В реальности - хэш
        user = User.query.filter_by(username=username, password_hash=password).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role_id
            return redirect(url_for('dashboard'))
        flash('Неверные данные')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session['role'] == 1:  # Operator
        return render_template('operator.html')
    elif session['role'] == 2:  # Admin
        return render_template('admin.html')
    return 'Роль не определена'

@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session or session['role'] != 1:
        return redirect(url_for('login'))
    
    file = request.files['file']
    if file and file.filename.endswith(('.txt', '.docx')):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Чтение текста (для .docx нужно docx2txt, но для простоты assume .txt)
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        doc = Document(user_id=session['user_id'], file_name=filename, raw_text=text)
        db.session.add(doc)
        db.session.commit()
        
        entities = parse_text(text)
        if entities:
            result = apply_rules(entities)
            analysis = AnalysisResult(document_id=doc.id, status=result['status'], details=result['details'], execution_plan=result['plan'])
            db.session.add(analysis)
            db.session.commit()
            return render_template('result.html', result=result)
        else:
            flash('Команда не распознана')
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Инициализация БД и тестовые данные
with app.app_context():
    db.create_all()
    if not User.query.first():
        # Тестовые пользователи
        operator = User(username='operator', password_hash='pass', role_id=1)
        admin = User(username='admin', password_hash='pass', role_id=2)
        db.session.add(operator)
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)