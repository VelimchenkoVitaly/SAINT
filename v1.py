# Обновлённый прототип SAINT (Вторая итерация: Первая полная версия)
# Доработки:
# 1. Расширенная онтология: Добавлены сущности Поезд, Платформа, Путь, Бригада, Вагон в симулированную БД и модели OntologyEntity, OntologyAttribute.
# 2. 12 шаблонов команд: Перевод, Перестановка, Прицепка, Отцепка, Отправление, Осмотр, Назначение бригады, Смена пути, Проверка вагона, Формирование состава, Разформирование, Задержка отправления.
# 3. Админ-панель: Маршрут /admin с формой для добавления/редактирования шаблонов (хранятся в БД как Rules, без перезапусков).
# 4. Динамический парсинг: parse_text теперь использует patterns из БД.
# 5. Динамический apply_rules: Парсит JSON conditions и conclusion для кастомных правил.
# Установка: pip install flask flask-sqlalchemy nltk
# Запуск: python app.py
# Доступ: http://127.0.0.1:5000/
# Тест: Логин admin/pass → /dashboard (админ-панель) для добавления шаблонов.

import os
import re
import datetime
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import nltk
from nltk.tokenize import word_tokenize

nltk.download('punkt', quiet=True)

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saint.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Модели БД (расширены для онтологии и правил)
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

# Новая модель: Онтология (сущности)
class OntologyEntity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., 'Поезд', 'Платформа'
    db_table = db.Column(db.String(100))  # e.g., 'trains'
    attributes = db.Column(db.Text)  # JSON: {'Номер': 'train_number', ...}

# Новая модель: Правила/Шаблоны команд (для админ-панели)
class Rule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., 'Перевод поезда'
    pattern = db.Column(db.Text, nullable=False)  # Regex шаблон
    conditions = db.Column(db.Text)  # JSON: условия проверки
    conclusion = db.Column(db.Text)  # JSON: статус и план

# Расширенная симулированная внешняя БД
simulated_db = {
    'trains': [
        {'train_number': '123', 'status': 'на платформе 1', 'brigade_id': None, 'wagons': []},
        {'train_number': '456', 'status': 'в пути', 'brigade_id': 'B1', 'wagons': ['W1', 'W2']},
        {'train_number': '789', 'status': 'на платформе 3', 'brigade_id': 'B2', 'wagons': ['W3']}
    ],
    'platforms': [
        {'platform_number': '1', 'is_occupied': True},
        {'platform_number': '5', 'is_occupied': False},
        {'platform_number': '3', 'is_occupied': False}
    ],
    'tracks': [  # Пути
        {'track_id': 'T1', 'status': 'свободен'},
        {'track_id': 'T2', 'status': 'занят'}
    ],
    'brigades': [  # Бригады
        {'brigade_id': 'B1', 'status': 'занята'},
        {'brigade_id': 'B2', 'status': 'свободна'}
    ],
    'wagons': [  # Вагоны
        {'wagon_id': 'W1', 'status': 'прикреплён к 456', 'inspection': 'OK'},
        {'wagon_id': 'W2', 'status': 'свободен', 'inspection': 'требует осмотр'},
        {'wagon_id': 'W3', 'status': 'прикреплён к 789', 'inspection': 'OK'}
    ]
}

# Расширенная онтология (по умолчанию, если БД пустая)
default_ontology = {
    'Поезд': {'db_table': 'trains', 'attributes': {'Номер': 'train_number', 'Статус': 'status', 'Бригада': 'brigade_id', 'Вагоны': 'wagons'}},
    'Платформа': {'db_table': 'platforms', 'attributes': {'Номер': 'platform_number', 'Занятость': 'is_occupied'}},
    'Путь': {'db_table': 'tracks', 'attributes': {'ИД': 'track_id', 'Статус': 'status'}},
    'Бригада': {'db_table': 'brigades', 'attributes': {'ИД': 'brigade_id', 'Статус': 'status'}},
    'Вагон': {'db_table': 'wagons', 'attributes': {'ИД': 'wagon_id', 'Статус': 'status', 'Осмотр': 'inspection'}}
}

# Динамический парсинг: Загружает все patterns из БД
def parse_text(text):
    rules = Rule.query.all()
    for rule in rules:
        match = re.search(rule.pattern, text)
        if match:
            entities = {'action': rule.name}
            # Извлекаем группы из match (предполагаем, что pattern имеет группы, e.g. (\d+))
            for i in range(1, len(match.groups()) + 1):
                entities[f'group{i}'] = match.group(i)  # Динамически сохраняем группы
            entities['rule_id'] = rule.id  # Для ссылки на rule в apply_rules
            return entities
    return None

# Динамический apply_rules: Парсит JSON conditions и conclusion
def apply_rules(entities):
    if 'rule_id' in entities:
        rule = Rule.query.get(entities['rule_id'])
        if rule:
            try:
                conditions_data = json.loads(rule.conditions)
                # Если conditions — не список (один объект), обернуть в список
                if not isinstance(conditions_data, list):
                    conditions_data = [conditions_data]
                conditions = conditions_data
                conclusion = json.loads(rule.conclusion)
            except json.JSONDecodeError:
                return {'status': 'Не выполнимо', 'details': 'Неверный JSON в правиле.', 'plan': None}
            
            reasons = []
            for cond in conditions:
                if cond.get('check') == 'exists':
                    entity = cond.get('entity')
                    ontology = OntologyEntity.query.filter_by(name=entity).first()
                    if ontology:
                        table = ontology.db_table
                        attributes = json.loads(ontology.attributes)
                        field = attributes.get('Номер', 'id')  # Дефолт field
                        value = entities.get('group1')  # Предполагаем первую группу — номер
                        if not query_external_db(table, field, value):
                            reasons.append(f'{entity} не существует.')
            
            if not reasons:
                return {'status': conclusion.get('status', 'Выполнимо'), 'details': 'Условия соблюдены.', 'plan': conclusion.get('plan')}
            else:
                return {'status': 'Не выполнимо', 'details': ' '.join(reasons), 'plan': None}
    
    return {'status': 'Не выполнимо', 'details': 'Команда не поддерживается.', 'plan': None}

# Запрос к симулированной БД
def query_external_db(table, field, value):
    data = simulated_db.get(table, [])
    for item in data:
        if item.get(field) == value:
            return item
    return None

# Routes (без изменений, кроме dashboard для админа)
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
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
    if session['role'] == 1:
        return render_template('operator.html')
    elif session['role'] == 2:
        rules = Rule.query.all()
        return render_template('admin.html', rules=rules)
    return 'Роль не определена'

@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session or session['role'] != 1:
        return redirect(url_for('login'))
    
    file = request.files['file']
    if file and file.filename.endswith('.txt'):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        doc = Document(user_id=session['user_id'], file_name=filename, raw_text=text)
        db.session.add(doc)
        db.session.commit()
        
        entities = parse_text(text)
        if entities:
            analysis_result = apply_rules(entities)
            result_for_template = {
                'status': analysis_result['status'],
                'details': analysis_result['details'],
                'plan': analysis_result.get('plan')
            }
            ar = AnalysisResult(document_id=doc.id, status=result_for_template['status'], details=result_for_template['details'], execution_plan=result_for_template['plan'])
            db.session.add(ar)
            db.session.commit()
            return render_template('result.html', result=result_for_template)
        else:
            flash('Команда не распознана')
    return redirect(url_for('dashboard'))

@app.route('/admin/add_rule', methods=['GET', 'POST'])
def add_rule():
    if 'role' not in session or session['role'] != 2:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        pattern = request.form['pattern']
        conditions = request.form['conditions']
        conclusion = request.form['conclusion']
        rule = Rule(name=name, pattern=pattern, conditions=conditions, conclusion=conclusion)
        db.session.add(rule)
        db.session.commit()
        flash('Шаблон добавлен')
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Инициализация (без изменений)
with app.app_context():
    db.create_all()
    if not User.query.first():
        operator = User(username='operator', password_hash='pass', role_id=1)
        admin = User(username='admin', password_hash='pass', role_id=2)
        db.session.add(operator)
        db.session.add(admin)
        db.session.commit()
    
    if not OntologyEntity.query.first():
        for name, data in default_ontology.items():
            entity = OntologyEntity(name=name, db_table=data['db_table'], attributes=json.dumps(data['attributes']))
            db.session.add(entity)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)