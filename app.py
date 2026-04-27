from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_file
from functools import wraps
from datetime import datetime
from config import Config
from database import db
from validators import BankDataValidator
import io
import csv
import os

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
db.create_tables()
validator = BankDataValidator()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('Acces non autorise', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = db.fetch_one("SELECT * FROM users WHERE username = ? AND password = ?", [username, password])
        if user_data:
            session['user_id'] = user_data['id']
            session['username'] = user_data['username']
            session['role'] = user_data['role']
            session['agence'] = user_data.get('agence', 'Siege')
            flash(f'Bienvenue {username} !', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Identifiants invalides', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Deconnexion reussie', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        nb = db.fetch_one("SELECT COUNT(*) as c FROM transactions")['c']
    except:
        nb = 0
    try:
        depots = db.fetch_one("SELECT COALESCE(SUM(montant),0) as c FROM transactions WHERE type='DEPOT'")['c']
    except:
        depots = 0
    try:
        retraits = db.fetch_one("SELECT COALESCE(SUM(montant),0) as c FROM transactions WHERE type='RETRAIT'")['c']
    except:
        retraits = 0
    try:
        enquetes = db.fetch_one("SELECT COUNT(*) as c FROM enquetes_satisfaction")['c']
    except:
        enquetes = 0
    try:
        score = db.fetch_one("SELECT COALESCE(AVG(score_global),0) as c FROM enquetes_satisfaction")['c']
    except:
        score = 0
    try:
        produits = db.fetch_one("SELECT COUNT(*) as c FROM produits_souscrits")['c']
    except:
        produits = 0
    try:
        clients = db.fetch_one("SELECT COUNT(DISTINCT client_id) as c FROM transactions")['c']
    except:
        clients = 0

    stats = {'nb': nb, 'depots': depots, 'retraits': retraits, 'enquetes': enquetes, 'score': score, 'produits': produits, 'clients': clients}
    return render_template('dashboard.html', stats=stats, transactions_mois=[], satisfaction_agence=[], produits_pop=[])

@app.route('/collecte/transactions', methods=['GET', 'POST'])
@login_required
def collecte_transactions():
    if request.method == 'POST':
        data = request.get_json()
        v = validator.validate_transaction(data)
        if not v.is_valid:
            return jsonify({'success': False, 'errors': v.errors}), 422
        s = v.sanitized_data
        db.execute_query("INSERT INTO transactions (client_id, client_nom, type, montant, devise, date_transaction, heure_transaction, agence, canal, categorie, description, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['client_nom'],s['type'],s['montant'],s.get('devise','XAF'),s['date_transaction'],s['heure_transaction'],s['agence'],s['canal'],s.get('categorie'),s.get('description'),session['user_id']])
        return jsonify({'success': True, 'message': 'Transaction enregistree'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    return render_template('collecte/transactions.html', clients=clients, agences=agences, categories=Config.CATEGORIES_TRANSACTION)

@app.route('/collecte/satisfaction', methods=['GET', 'POST'])
@login_required
def collecte_satisfaction():
    if request.method == 'POST':
        data = request.get_json()
        v = validator.validate_satisfaction(data)
        if not v.is_valid:
            return jsonify({'success': False, 'errors': v.errors}), 422
        s = v.sanitized_data
        db.execute_query("INSERT INTO enquetes_satisfaction (client_id, agence, date_enquete, score_global, score_accueil, score_temps_attente, score_conseil, score_digital, commentaire, recommandation, canal_enquete, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['agence'],s['date_enquete'],s['score_global'],s.get('score_accueil'),s.get('score_temps_attente'),s.get('score_conseil'),s.get('score_digital'),s.get('commentaire'),s.get('recommandation',False),s['canal_enquete'],session['user_id']])
        return jsonify({'success': True, 'message': 'Enquete enregistree'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    return render_template('collecte/satisfaction.html', clients=clients, agences=agences)

@app.route('/collecte/produits', methods=['GET', 'POST'])
@login_required
def collecte_produits():
    if request.method == 'POST':
        data = request.get_json()
        v = validator.validate_produit(data)
        if not v.is_valid:
            return jsonify({'success': False, 'errors': v.errors}), 422
        s = v.sanitized_data
        db.execute_query("INSERT INTO produits_souscrits (client_id, type_produit, nom_produit, date_souscription, montant_souscription, taux_interet, duree_mois, agence, canal_souscription, statut, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['type_produit'],s['nom_produit'],s['date_souscription'],s.get('montant_souscription',0),s.get('taux_interet',0),s.get('duree_mois'),s['agence'],s['canal_souscription'],s.get('statut','ACTIF'),session['user_id']])
        return jsonify({'success': True, 'message': 'Produit enregistre'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    return render_template('collecte/produits.html', clients=clients, agences=agences, types_produits=Config.TYPES_PRODUITS)

@app.route('/analyses/transactions')
@login_required
def analyse_transactions():
    return render_template('analyses/transactions.html', analyse_mensuelle=[], analyse_agences=[], analyse_canaux=[], stats_descriptives={'nb_total':0,'montant_total':0,'moyenne':0,'minimum':0,'maximum':0})

@app.route('/analyses/satisfaction')
@login_required
def analyse_satisfaction():
    return render_template('analyses/satisfaction.html', scores_dimensions={'score_global_moyen':0,'nb_enquetes':0}, distribution_scores=[], tendance_mensuelle=[], par_agence=[], taux_recommandation={'taux_reco':0})

@app.route('/analyses/produits')
@login_required
def analyse_produits():
    return render_template('analyses/produits.html', volume_produits=[], evolution_mensuelle=[], performance_agences=[], conversion_canal=[])

@app.route('/rapports')
@login_required
def rapports():
    return render_template('rapports.html')

@app.route('/utilisateurs')
@login_required
@role_required(['admin'])
def utilisateurs():
    users = db.fetch_all("SELECT * FROM users ORDER BY username")
    return render_template('utilisateurs.html', users=users, audit_logs=[], roles=Config.ROLES)

@app.route('/clients')
@login_required
def clients():
    clients_list = db.fetch_all("SELECT * FROM clients ORDER BY nom")
    return render_template('clients.html', clients=clients_list)

@app.route('/api/clients/ajouter', methods=['POST'])
@login_required
def ajouter_client():
    data = request.get_json()
    
    if not data.get('nom') or not data.get('prenom') or not data.get('agence'):
        return jsonify({'success': False, 'message': 'Nom, prénom et agence requis'}), 400
    
    db.execute_query(
        "INSERT INTO clients (nom, prenom, age, telephone, email, agence) VALUES (?, ?, ?, ?, ?, ?)",
        [data['nom'].strip().upper(), data['prenom'].strip().title(), 
         data.get('age'), data.get('telephone'), data.get('email'), data['agence']]
    )
    
    return jsonify({'success': True, 'message': 'Client ajouté'}), 201

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
