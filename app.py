cat > app.py << 'ENDCODE'
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_file
from functools import wraps
from datetime import datetime, timedelta
from config import Config
from database import db
from validators import BankDataValidator
from analytics import BankingAnalytics
import io
import csv
import os

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

analytics_engine = BankingAnalytics(db)
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
                flash('Accès non autorisé', 'danger')
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
            session['agence'] = user_data.get('agence', 'Siège')
            flash(f'Bienvenue {username} !', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Identifiants invalides', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    stats_globales = db.fetch_one("SELECT (SELECT COUNT(*) FROM transactions) as nb_transactions, (SELECT COALESCE(SUM(montant),0) FROM transactions WHERE type='DEPOT') as total_depots, (SELECT COALESCE(SUM(montant),0) FROM transactions WHERE type='RETRAIT') as total_retraits, (SELECT COUNT(*) FROM enquetes_satisfaction) as nb_enquetes, (SELECT COALESCE(AVG(score_global),0) FROM enquetes_satisfaction) as score_moyen, (SELECT COUNT(*) FROM produits_souscrits) as nb_produits, (SELECT COUNT(DISTINCT client_id) FROM transactions) as clients_actifs")
    transactions_mois = db.fetch_all("SELECT strftime('%Y-%m', date_transaction) as mois, COUNT(*) as nb FROM transactions WHERE date_transaction >= date('now','-6 months') GROUP BY mois ORDER BY mois")
    satisfaction_agence = db.fetch_all("SELECT agence, ROUND(AVG(score_global),2) as score_moyen, COUNT(*) as nb_reponses FROM enquetes_satisfaction GROUP BY agence ORDER BY score_moyen DESC")
    produits_pop = db.fetch_all("SELECT type_produit, COUNT(*) as nb_souscriptions FROM produits_souscrits GROUP BY type_produit ORDER BY nb_souscriptions DESC LIMIT 5")
    return render_template('dashboard.html', stats=stats_globales, transactions_mois=transactions_mois, satisfaction_agence=satisfaction_agence, produits_pop=produits_pop)

@app.route('/collecte/transactions', methods=['GET', 'POST'])
@login_required
def collecte_transactions():
    if request.method == 'POST':
        data = request.get_json()
        validation = validator.validate_transaction(data)
        if not validation.is_valid:
            return jsonify({'success': False, 'errors': validation.errors}), 422
        s = validation.sanitized_data
        db.execute_query("INSERT INTO transactions (client_id, client_nom, type, montant, devise, date_transaction, heure_transaction, agence, canal, categorie, description, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['client_nom'],s['type'],s['montant'],s.get('devise','XAF'),s['date_transaction'],s['heure_transaction'],s['agence'],s['canal'],s.get('categorie'),s.get('description'),session['user_id']])
        return jsonify({'success': True, 'message': 'Transaction enregistrée'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences ORDER BY agence")
    return render_template('collecte/transactions.html', clients=clients, agences=agences, categories=Config.CATEGORIES_TRANSACTION)

@app.route('/collecte/satisfaction', methods=['GET', 'POST'])
@login_required
def collecte_satisfaction():
    if request.method == 'POST':
        data = request.get_json()
        validation = validator.validate_satisfaction(data)
        if not validation.is_valid:
            return jsonify({'success': False, 'errors': validation.errors}), 422
        s = validation.sanitized_data
        db.execute_query("INSERT INTO enquetes_satisfaction (client_id, agence, date_enquete, score_global, score_accueil, score_temps_attente, score_conseil, score_digital, commentaire, recommandation, canal_enquete, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['agence'],s['date_enquete'],s['score_global'],s.get('score_accueil'),s.get('score_temps_attente'),s.get('score_conseil'),s.get('score_digital'),s.get('commentaire'),s.get('recommandation',False),s['canal_enquete'],session['user_id']])
        return jsonify({'success': True, 'message': 'Enquête enregistrée'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences ORDER BY agence")
    return render_template('collecte/satisfaction.html', clients=clients, agences=agences)

@app.route('/collecte/produits', methods=['GET', 'POST'])
@login_required
def collecte_produits():
    if request.method == 'POST':
        data = request.get_json()
        validation = validator.validate_produit(data)
        if not validation.is_valid:
            return jsonify({'success': False, 'errors': validation.errors}), 422
        s = validation.sanitized_data
        db.execute_query("INSERT INTO produits_souscrits (client_id, type_produit, nom_produit, date_souscription, montant_souscription, taux_interet, duree_mois, agence, canal_souscription, statut, agent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [s['client_id'],s['type_produit'],s['nom_produit'],s['date_souscription'],s.get('montant_souscription',0),s.get('taux_interet',0),s.get('duree_mois'),s['agence'],s['canal_souscription'],s.get('statut','ACTIF'),session['user_id']])
        return jsonify({'success': True, 'message': 'Produit enregistré'}), 201
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences ORDER BY agence")
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

@app.route('/api/export/<string:type_export>')
@login_required
def export_data(type_export):
    if type_export == 'transactions':
        data = db.fetch_all("SELECT * FROM transactions")
        fn = f"transactions_{datetime.now().strftime('%Y%m%d')}.csv"
    elif type_export == 'satisfaction':
        data = db.fetch_all("SELECT * FROM enquetes_satisfaction")
        fn = f"satisfaction_{datetime.now().strftime('%Y%m%d')}.csv"
    elif type_export == 'produits':
        data = db.fetch_all("SELECT * FROM produits_souscrits")
        fn = f"produits_{datetime.now().strftime('%Y%m%d')}.csv"
    else:
        return jsonify({'error': 'Type invalide'}), 400
    output = io.StringIO()
    if data:
        w = csv.DictWriter(output, fieldnames=data[0].keys())
        w.writeheader()
        w.writerows(data)
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=fn)

@app.route('/utilisateurs')
@login_required
@role_required(['admin'])
def utilisateurs():
    users = db.fetch_all("SELECT * FROM users ORDER BY username")
    return render_template('utilisateurs.html', users=users, audit_logs=[], roles=Config.ROLES)

def init_database():
    db.execute_query("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, agence TEXT, email TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute_query("CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, prenom TEXT NOT NULL, age INTEGER, telephone TEXT, email TEXT, agence TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute_query("CREATE TABLE IF NOT EXISTS agences (id INTEGER PRIMARY KEY AUTOINCREMENT, agence TEXT UNIQUE NOT NULL, ville TEXT, region TEXT)")
    db.execute_query("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, client_nom TEXT NOT NULL, type TEXT NOT NULL, montant REAL NOT NULL, devise TEXT DEFAULT 'XAF', date_transaction DATE NOT NULL, heure_transaction TIME NOT NULL, agence TEXT, canal TEXT, categorie TEXT, description TEXT, agent_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute_query("CREATE TABLE IF NOT EXISTS enquetes_satisfaction (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, agence TEXT, date_enquete DATE NOT NULL, score_global INTEGER NOT NULL, score_accueil INTEGER, score_temps_attente INTEGER, score_conseil INTEGER, score_digital INTEGER, commentaire TEXT, recommandation BOOLEAN DEFAULT 0, canal_enquete TEXT, agent_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute_query("CREATE TABLE IF NOT EXISTS produits_souscrits (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, type_produit TEXT NOT NULL, nom_produit TEXT NOT NULL, date_souscription DATE NOT NULL, montant_souscription REAL DEFAULT 0, taux_interet REAL DEFAULT 0, duree_mois INTEGER, agence TEXT, canal_souscription TEXT, statut TEXT DEFAULT 'ACTIF', agent_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute_query("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, details TEXT, ip_address TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    if not db.fetch_one("SELECT id FROM users WHERE username = 'admin'"):
        db.execute_query("INSERT INTO users (username, password, role, agence, email) VALUES ('admin','admin123','admin','Siège','admin@banque.cm')")
    for ag in ['Siège','Centre-Ville','Marché Central','Port','Zone Industrielle']:
        db.execute_query("INSERT OR IGNORE INTO agences (agence, ville) VALUES (?,?)", [ag, 'Douala'])

if __name__ == '__main__':
    init_database()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
ENDCODE
