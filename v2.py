# Прототип SAINT v2.0 (Вторая итерация: Интеллектуальный движок)
# Доработки:
# 1. Замена хардкод-правил на Prolog (через PySWIP): Логический вывод для сложных правил.
# 2. Поддержка правил вроде "Если поезд пассажирский и время > 22:00 → нужен техосмотр".
# 3. Автообнаружение конфликтов: Prolog проверяет на конфликты между приказами (e.g., платформа занята другим поездом).
# Установка: pip install flask flask-sqlalchemy nltk pyswip
# Prolog файл: Создай rules.pl с правилами ниже.
# Запуск: python app.py
# Тест: Добавь правила в админ, загрузи файл — Prolog вернёт вывод.

import os
import re
import datetime
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import nltk
from nltk.tokenize import word_tokenize
from pyswip import Prolog

nltk.download('punkt', quiet=True)

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saint.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Модели БД (без изменений)
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
    status = db.Column(db.String(20), nullable=False)
    details = db.Column(db.Text)
    execution_plan = db.Column(db.Text)
    analyzed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class OntologyEntity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    db_table = db.Column(db.String(100))
    attributes = db.Column(db.Text)

class Rule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    pattern = db.Column(db.Text, nullable=False)
    conditions = db.Column(db.Text)  # Prolog rules as string
    conclusion = db.Column(db.Text)  # Prolog query

# Prolog интеграция
prolog = Prolog()
prolog.consult('rules.pl')  # Создай файл rules.pl с правилами ниже

# Пример rules.pl (сохрани в той же папке)
# train(123, passenger, 'на платформе 1').
# platform(5, free).
# conflict(Command1, Command2) :- Command1 \= Command2, share_resource(Command1, Command2).
# requires_inspection(Train) :- train(Train, passenger), current_time(T), T > 22.
# feasible(Command) :- not(requires_inspection(_)), not(conflict(Command, _)).

# Расширенная симулированная БД (без изменений)
simulated_db = {
    'trains': [
        {'train_number': '123', 'type': 'passenger', 'status': 'на платформе 1', 'brigade_id': None, 'wagons': []},
        {'train_number': '456', 'type': 'freight', 'status': 'в пути', 'brigade_id': 'B1', 'wagons': ['W1', 'W2']}
    ],
    'platforms': [
        {'platform_number': '1', 'is_occupied': True},
        {'platform_number': '5', 'is_occupied': False}
    ]
    # ... остальное
}

# Динамический парсинг (без изменений)
def parse_text(text):
    rules = Rule.query.all()
    for rule in rules:
        match = re.search(rule.pattern, text)
        if match:
            entities = {'action': rule.name}
            for i in range(1, len(match.groups()) + 1):
                entities[f'group{i}'] = match.group(i)
            entities['rule_id'] = rule.id
            return entities
    return None

# Логический вывод через Prolog
def apply_rules(entities):
    if 'rule_id' in entities:
        rule = Rule.query.get(entities['rule_id'])
        if rule:
            # Загружаем данные в Prolog динамически
            for train in simulated_db['trains']:
                prolog.assertz(f"train({train['train_number']}, {train['type']}, '{train['status']}')")
            for platform in simulated_db['platforms']:
                prolog.assertz(f"platform({platform['platform_number']}, {'free' if not platform['is_occupied'] else 'occupied'})")
            # Добавьте для других сущностей
            
            # Текущее время для правил
            current_hour = datetime.datetime.now().hour
            prolog.assertz(f"current_time({current_hour})")
            
            # Выполняем query из rule.conclusion (e.g., "feasible(translate(123,5))")
            query = json.loads(rule.conclusion).get('query', f"feasible({entities['action'].lower()}({entities.get('group1')}))")
            result = list(prolog.query(query))
            
            if result:
                # Проверка конфликтов
                conflict_query = f"conflict({entities['action'].lower()}({entities.get('group1')}), X)"
                conflicts = list(prolog.query(conflict_query))
                if conflicts:
                    return {'status': 'Не выполнимо', 'details': f'Конфликт с {conflicts[0]["X"]}', 'plan': None}
                return {'status': 'Выполнимо', 'details': 'Условия соблюдены.', 'plan': 'Шаг 1: Выполнить. Шаг 2: Зафиксировать.'}
            else:
                inspection_query = f"requires_inspection({entities.get('group1')})"
                if list(prolog.query(inspection_query)):
                    return {'status': 'Не выполнимо', 'details': 'Нужен техосмотр (время > 22:00 для пассажирского поезда)', 'plan': None}
                return {'status': 'Не выполнимо', 'details': 'Не выполнимо по правилам.', 'plan': None}
    
    return {'status': 'Не выполнимо', 'details': 'Команда не поддерживается.', 'plan': None}

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

# Инициализация (добавьте Prolog факты)
with app.app_context():
    db.create_all()
    # ... остальное
    # Добавьте дефолтные Prolog правила в rules.pl

if __name__ == '__main__':
    app.run(debug=True)