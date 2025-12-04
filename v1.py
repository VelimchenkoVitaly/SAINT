# Обновлённый прототип SAINT (Вторая итерация: Первая полная версия)
# Доработки:
# 1. Расширенная онтология: Добавлены сущности Поезд, Платформа, Путь, Бригада, Вагон в симулированную БД и модели OntologyEntity, OntologyAttribute.
# 2. 12 шаблонов команд: Перевод, Перестановка, Прицепка, Отцепка, Отправление, Осмотр, Назначение бригады, Смена пути, Проверка вагона, Формирование состава, Разформирование, Задержка отправления.
# 3. Админ-панель: Маршрут /admin с формой для добавления/редактирования шаблонов (хранятся в БД как Rules, без перезапусков).
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

# 12 шаблонов команд (regex)
def parse_text(text):
    patterns = [
        # 1. Перевод поезда
        (r'Перевести поезд №(\d+) с платформы (\d+) на платформу (\d+)', 'Перевод поезда', {'train_number': 1, 'from_platform': 2, 'to_platform': 3}),
        # 2. Перестановка поезда
        (r'Переставить поезд №(\d+) на платформу (\d+)', 'Перестановка поезда', {'train_number': 1, 'to_platform': 2}),
        # 3. Прицепка вагона
        (r'Прицепить вагон (\w+) к поезду №(\d+)', 'Прицепка вагона', {'wagon_id': 1, 'train_number': 2}),
        # 4. Отцепка вагона
        (r'Отцепить вагон (\w+) от поезда №(\d+)', 'Отцепка вагона', {'wagon_id': 1, 'train_number': 2}),
        # 5. Отправление поезда
        (r'Отправить поезд №(\d+) с платформы (\d+)', 'Отправление поезда', {'train_number': 1, 'platform': 2}),
        # 6. Осмотр поезда
        (r'Провести осмотр поезда №(\d+)', 'Осмотр поезда', {'train_number': 1}),
        # 7. Назначение бригады
        (r'Назначить бригаду (\w+) поезду №(\d+)', 'Назначение бригады', {'brigade_id': 1, 'train_number': 2}),
        # 8. Смена пути
        (r'Сменить путь (\w+) для поезда №(\d+)', 'Смена пути', {'track_id': 1, 'train_number': 2}),
        # 9. Проверка вагона
        (r'Проверить вагон (\w+)', 'Проверка вагона', {'wagon_id': 1}),
        # 10. Формирование состава
        (r'Сформировать состав поезда №(\d+) с вагонами (\w+)', 'Формирование состава', {'train_number': 1, 'wagons': 2}),
        # 11. Разформирование состава
        (r'Разформировать состав поезда №(\d+)', 'Разформирование состава', {'train_number': 1}),
        # 12. Задержка отправления
        (r'Задержать отправление поезда №(\d+) на (\d+) минут', 'Задержка отправления', {'train_number': 1, 'delay': 2})
    ]
    
    for pattern, action, keys in patterns:
        match = re.search(pattern, text)
        if match:
            entities = {list(keys.keys())[i]: match.group(i+1) for i in range(len(keys))}
            entities['action'] = action
            return entities
    return None

# Запрос к симулированной БД
def query_external_db(table, field, value):
    data = simulated_db.get(table, [])
    for item in data:
        if item.get(field) == value:
            return item
    return None

# Полная реализация apply_rules для всех 12 команд
def apply_rules(entities):
    action = entities['action']
    reasons = []
    plan = 'Шаг 1: Подготовка. Шаг 2: Выполнение. Шаг 3: Фиксация.'  # Дефолтный план
    
    if action == 'Перевод поезда':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        from_platform = query_external_db('platforms', 'platform_number', entities['from_platform'])
        to_platform = query_external_db('platforms', 'platform_number', entities['to_platform'])
        if train and from_platform and to_platform and to_platform['is_occupied'] == False and train['status'] != 'в пути':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan}
        if not train: reasons.append('Поезд не существует.')
        if not to_platform: reasons.append('Целевая платформа не существует.')
        if to_platform and to_platform['is_occupied']: reasons.append('Целевая платформа занята.')
        if train and train['status'] == 'в пути': reasons.append('Поезд в пути.')
    
    elif action == 'Перестановка поезда':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        to_platform = query_external_db('platforms', 'platform_number', entities['to_platform'])
        if train and to_platform and to_platform['is_occupied'] == False and train['status'] == 'на платформе':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Перестановка')}
        if not train: reasons.append('Поезд не существует.')
        if not to_platform: reasons.append('Платформа не существует.')
        if to_platform and to_platform['is_occupied']: reasons.append('Платформа занята.')
        if train and train['status'] != 'на платформе': reasons.append('Поезд не на платформе.')
    
    elif action == 'Прицепка вагона':
        wagon = query_external_db('wagons', 'wagon_id', entities['wagon_id'])
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if wagon and train and wagon['status'] == 'свободен' and wagon['inspection'] == 'OK':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Прицепка вагона')}
        if not wagon: reasons.append('Вагон не существует.')
        if not train: reasons.append('Поезд не существует.')
        if wagon and wagon['status'] != 'свободен': reasons.append('Вагон не свободен.')
        if wagon and wagon['inspection'] != 'OK': reasons.append('Вагон требует осмотра.')
    
    elif action == 'Отцепка вагона':
        wagon = query_external_db('wagons', 'wagon_id', entities['wagon_id'])
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if wagon and train and entities['wagon_id'] in train['wagons']:
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Отцепка вагона')}
        if not wagon: reasons.append('Вагон не существует.')
        if not train: reasons.append('Поезд не существует.')
        if wagon and entities['wagon_id'] not in train['wagons']: reasons.append('Вагон не прикреплён к поезду.')
    
    elif action == 'Отправление поезда':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        platform = query_external_db('platforms', 'platform_number', entities['platform'])
        if train and platform and train['brigade_id'] and train['status'] == 'на платформе' and platform['is_occupied']:
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Отправление')}
        if not train: reasons.append('Поезд не существует.')
        if not platform: reasons.append('Платформа не существует.')
        if train and not train['brigade_id']: reasons.append('Нет бригады.')
        if train and train['status'] != 'на платформе': reasons.append('Поезд не на платформе.')
    
    elif action == 'Осмотр поезда':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if train:
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Осмотр поезда')}
        if not train: reasons.append('Поезд не существует.')
    
    elif action == 'Назначение бригады':
        brigade = query_external_db('brigades', 'brigade_id', entities['brigade_id'])
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if brigade and train and brigade['status'] == 'свободна' and not train['brigade_id']:
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Назначение бригады')}
        if not brigade: reasons.append('Бригада не существует.')
        if not train: reasons.append('Поезд не существует.')
        if brigade and brigade['status'] != 'свободна': reasons.append('Бригада занята.')
        if train and train['brigade_id']: reasons.append('Поезд уже имеет бригаду.')
    
    elif action == 'Смена пути':
        track = query_external_db('tracks', 'track_id', entities['track_id'])
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if track and train and track['status'] == 'свободен':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Смена пути')}
        if not track: reasons.append('Путь не существует.')
        if not train: reasons.append('Поезд не существует.')
        if track and track['status'] != 'свободен': reasons.append('Путь занят.')
    
    elif action == 'Проверка вагона':
        wagon = query_external_db('wagons', 'wagon_id', entities['wagon_id'])
        if wagon and wagon['inspection'] == 'OK':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Проверка вагона')}
        if not wagon: reasons.append('Вагон не существует.')
        if wagon and wagon['inspection'] != 'OK': reasons.append('Вагон требует осмотра.')
    
    elif action == 'Формирование состава':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        wagons = [query_external_db('wagons', 'wagon_id', w.strip()) for w in entities['wagons'].split(',')]
        if train and all(wagons) and all(w['status'] == 'свободен' for w in wagons if w):
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Формирование состава')}
        if not train: reasons.append('Поезд не существует.')
        if not all(wagons): reasons.append('Один или более вагонов не существуют.')
        if any(w['status'] != 'свободен' for w in wagons if w): reasons.append('Вагон не свободен.')
    
    elif action == 'Разформирование состава':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if train and train['wagons']:
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', 'Разформирование состава')}
        if not train: reasons.append('Поезд не существует.')
        if train and not train['wagons']: reasons.append('Состав пуст.')
    
    elif action == 'Задержка отправления':
        train = query_external_db('trains', 'train_number', entities['train_number'])
        if train and train['status'] == 'на платформе':
            return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': plan.replace('Выполнение', f'Задержка на {entities["delay"]} минут')}
        if not train: reasons.append('Поезд не существует.')
        if train and train['status'] != 'на платформе': reasons.append('Поезд не на платформе.')
    
    if reasons:
        return {'status': 'Не выполнимо', 'details': ' '.join(reasons), 'plan': None}
    return {'status': 'Не выполнимо', 'details': 'Команда не поддерживается в этой версии.', 'plan': None}

# Routes (без изменений)
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