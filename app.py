from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_file
from functools import wraps
from datetime import datetime, timedelta
from config import Config
from database import db
from validators import BankDataValidator
from analytics import BankingAnalytics
import io
import csv
import json

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Initialisation
analytics_engine = BankingAnalytics(db)
validator = BankDataValidator()

# ============================================
# MODÈLE UTILISATEUR SIMPLIFIÉ
# ============================================
class User(UserMixin):
    def __init__(self, id, username, role, agence):
        self.id = id
        self.username = username
        self.role = role
        self.agence = agence

@login_manager.user_loader
def load_user(user_id):
    user_data = db.fetch_one("SELECT * FROM users WHERE id = ?", [user_id])
    if user_data:
        return User(user_data['id'], user_data['username'], user_data['role'], user_data['agence'])
    return None

# ============================================
# DÉCORATEUR RÔLES
# ============================================
def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('Accès non autorisé', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============================================
# INTERFACE 1 : AUTHENTIFICATION
# ============================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Interface de connexion sécurisée"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db.fetch_one(
            "SELECT * FROM users WHERE username = ? AND password = ?", 
            [username, password]  # En production: hashage bcrypt
        )
        
        if user_data:
            user = User(user_data['id'], user_data['username'], user_data['role'], user_data['agence'])
            login_user(user)
            
            # Log de connexion
            db.execute_query(
                "INSERT INTO audit_log (user_id, action, ip_address) VALUES (?, ?, ?)",
                [user.id, 'CONNEXION', request.remote_addr]
            )
            
            flash(f'Bienvenue {user.username} !', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Identifiants invalides', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    db.execute_query(
        "INSERT INTO audit_log (user_id, action, ip_address) VALUES (?, ?, ?)",
        [current_user.id, 'DECONNEXION', request.remote_addr]
    )
    logout_user()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('login'))

# ============================================
# INTERFACE 2 : TABLEAU DE BORD PRINCIPAL
# ============================================
@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard principal avec KPIs"""
    # Statistiques globales
    stats_globales = db.fetch_one("""
        SELECT 
            (SELECT COUNT(*) FROM transactions) as nb_transactions,
            (SELECT COALESCE(SUM(montant), 0) FROM transactions WHERE type = 'DEPOT') as total_depots,
            (SELECT COALESCE(SUM(montant), 0) FROM transactions WHERE type = 'RETRAIT') as total_retraits,
            (SELECT COUNT(*) FROM enquetes_satisfaction) as nb_enquetes,
            (SELECT COALESCE(AVG(score), 0) FROM enquetes_satisfaction) as score_moyen,
            (SELECT COUNT(*) FROM produits_souscrits) as nb_produits,
            (SELECT COUNT(DISTINCT client_id) FROM transactions) as clients_actifs
    """)
    
    # Données pour graphiques
    transactions_par_mois = db.fetch_all("""
        SELECT strftime('%Y-%m', date_transaction) as mois, 
               COUNT(*) as nb, 
               SUM(CASE WHEN type='DEPOT' THEN montant ELSE 0 END) as depots,
               SUM(CASE WHEN type='RETRAIT' THEN montant ELSE 0 END) as retraits
        FROM transactions 
        WHERE date_transaction >= date('now', '-6 months')
        GROUP BY mois
        ORDER BY mois
    """)
    
    satisfaction_par_agence = db.fetch_all("""
        SELECT agence, AVG(score) as score_moyen, COUNT(*) as nb_reponses
        FROM enquetes_satisfaction
        GROUP BY agence
        ORDER BY score_moyen DESC
    """)
    
    produits_populaires = db.fetch_all("""
        SELECT type_produit, COUNT(*) as nb_souscriptions
        FROM produits_souscrits
        GROUP BY type_produit
        ORDER BY nb_souscriptions DESC
        LIMIT 5
    """)
    
    return render_template('dashboard.html',
        stats=stats_globales,
        transactions_mois=transactions_par_mois,
        satisfaction_agence=satisfaction_par_agence,
        produits_pop=produits_populaires
    )

# ============================================
# INTERFACE 3.1 : COLLECTE TRANSACTIONS
# ============================================
@app.route('/collecte/transactions', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'agent', 'guichetier'])
def collecte_transactions():
    """Interface de collecte des transactions bancaires"""
    if request.method == 'POST':
        data = request.get_json()
        
        # Validation des données bancaires
        validation = validator.validate_transaction(data)
        
        if not validation.is_valid:
            return jsonify({
                'success': False,
                'errors': validation.errors
            }), 422
        
        # Insertion dans la base
        sanitized = validation.sanitized_data
        db.execute_query("""
            INSERT INTO transactions 
            (client_id, client_nom, type, montant, devise, date_transaction, 
             heure_transaction, agence, canal, categorie, description, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            sanitized['client_id'],
            sanitized['client_nom'],
            sanitized['type'],
            sanitized['montant'],
            sanitized.get('devise', 'XAF'),
            sanitized['date_transaction'],
            sanitized['heure_transaction'],
            sanitized['agence'],
            sanitized['canal'],
            sanitized.get('categorie'),
            sanitized.get('description'),
            current_user.id
        ])
        
        # Log
        db.execute_query(
            "INSERT INTO audit_log (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
            [current_user.id, 'AJOUT_TRANSACTION', 
             f"Transaction {sanitized['type']} de {sanitized['montant']} {sanitized.get('devise', 'XAF')}",
             request.remote_addr]
        )
        
        return jsonify({
            'success': True,
            'message': 'Transaction enregistrée avec succès'
        }), 201
    
    # GET: Affichage du formulaire
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    categories = Config.CATEGORIES_TRANSACTION
    
    return render_template('collecte/transactions.html',
        clients=clients,
        agences=agences,
        categories=categories
    )

# ============================================
# INTERFACE 3.2 : COLLECTE SATISFACTION CLIENT
# ============================================
@app.route('/collecte/satisfaction', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'agent', 'conseiller'])
def collecte_satisfaction():
    """Interface de collecte des enquêtes de satisfaction"""
    if request.method == 'POST':
        data = request.get_json()
        
        validation = validator.validate_satisfaction(data)
        
        if not validation.is_valid:
            return jsonify({
                'success': False,
                'errors': validation.errors
            }), 422
        
        sanitized = validation.sanitized_data
        db.execute_query("""
            INSERT INTO enquetes_satisfaction 
            (client_id, agence, date_enquete, score_global, score_accueil, 
             score_temps_attente, score_conseil, score_digital, commentaire, 
             recommandation, canal_enquete, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            sanitized['client_id'],
            sanitized['agence'],
            sanitized['date_enquete'],
            sanitized['score_global'],
            sanitized.get('score_accueil'),
            sanitized.get('score_temps_attente'),
            sanitized.get('score_conseil'),
            sanitized.get('score_digital'),
            sanitized.get('commentaire'),
            sanitized.get('recommandation', False),
            sanitized['canal_enquete'],
            current_user.id
        ])
        
        db.execute_query(
            "INSERT INTO audit_log (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
            [current_user.id, 'AJOUT_ENQUETE', 
             f"Enquête satisfaction client {sanitized['client_id']} - Score: {sanitized['score_global']}/10",
             request.remote_addr]
        )
        
        return jsonify({
            'success': True,
            'message': 'Enquête enregistrée avec succès'
        }), 201
    
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    
    return render_template('collecte/satisfaction.html',
        clients=clients,
        agences=agences
    )

# ============================================
# INTERFACE 3.3 : COLLECTE PRODUITS BANCAIRES
# ============================================
@app.route('/collecte/produits', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'agent', 'conseiller'])
def collecte_produits():
    """Interface de collecte des souscriptions produits"""
    if request.method == 'POST':
        data = request.get_json()
        
        validation = validator.validate_produit(data)
        
        if not validation.is_valid:
            return jsonify({
                'success': False,
                'errors': validation.errors
            }), 422
        
        sanitized = validation.sanitized_data
        db.execute_query("""
            INSERT INTO produits_souscrits 
            (client_id, type_produit, nom_produit, date_souscription, montant_souscription,
             taux_interet, duree_mois, agence, canal_souscription, statut, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            sanitized['client_id'],
            sanitized['type_produit'],
            sanitized['nom_produit'],
            sanitized['date_souscription'],
            sanitized.get('montant_souscription', 0),
            sanitized.get('taux_interet', 0),
            sanitized.get('duree_mois'),
            sanitized['agence'],
            sanitized['canal_souscription'],
            sanitized.get('statut', 'ACTIF'),
            current_user.id
        ])
        
        db.execute_query(
            "INSERT INTO audit_log (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
            [current_user.id, 'AJOUT_PRODUIT', 
             f"Souscription {sanitized['type_produit']} - {sanitized['nom_produit']}",
             request.remote_addr]
        )
        
        return jsonify({
            'success': True,
            'message': 'Produit enregistré avec succès'
        }), 201
    
    clients = db.fetch_all("SELECT id, nom, prenom FROM clients ORDER BY nom")
    agences = db.fetch_all("SELECT DISTINCT agence FROM agences")
    types_produits = Config.TYPES_PRODUITS
    
    return render_template('collecte/produits.html',
        clients=clients,
        agences=agences,
        types_produits=types_produits
    )

# ============================================
# INTERFACE 4.1 : ANALYSE DES TRANSACTIONS
# ============================================
@app.route('/analyses/transactions')
@login_required
@role_required(['admin', 'analyste', 'manager'])
def analyse_transactions():
    """Interface d'analyse descriptive des transactions"""
    
    # Analyse temporelle
    analyse_mensuelle = db.fetch_all("""
        SELECT 
            strftime('%Y-%m', date_transaction) as periode,
            COUNT(*) as volume,
            SUM(montant) as montant_total,
            AVG(montant) as montant_moyen,
            SUM(CASE WHEN type='DEPOT' THEN 1 ELSE 0 END) as nb_depots,
            SUM(CASE WHEN type='RETRAIT' THEN 1 ELSE 0 END) as nb_retraits,
            SUM(CASE WHEN type='VIREMENT' THEN 1 ELSE 0 END) as nb_virements
        FROM transactions
        WHERE date_transaction >= date('now', '-12 months')
        GROUP BY periode
        ORDER BY periode DESC
    """)
    
    # Analyse par agence
    analyse_agences = db.fetch_all("""
        SELECT 
            agence,
            COUNT(*) as volume,
            SUM(montant) as montant_total,
            AVG(montant) as montant_moyen,
            COUNT(DISTINCT client_id) as clients_uniques
        FROM transactions
        GROUP BY agence
        ORDER BY volume DESC
    """)
    
    # Analyse par canal
    analyse_canaux = db.fetch_all("""
        SELECT 
            canal,
            COUNT(*) as volume,
            SUM(montant) as montant_total,
            ROUND(AVG(montant), 2) as montant_moyen
        FROM transactions
        GROUP BY canal
        ORDER BY volume DESC
    """)
    
    # Analyse par catégorie
    analyse_categories = db.fetch_all("""
        SELECT 
            COALESCE(categorie, 'Non catégorisé') as categorie,
            COUNT(*) as volume,
            SUM(montant) as montant_total,
            ROUND(AVG(montant), 2) as montant_moyen
        FROM transactions
        GROUP BY categorie
        ORDER BY volume DESC
    """)
    
    # Heures de pointe
    heures_pointe = db.fetch_all("""
        SELECT 
            strftime('%H', heure_transaction) as heure,
            COUNT(*) as volume,
            SUM(montant) as montant_total
        FROM transactions
        GROUP BY heure
        ORDER BY volume DESC
        LIMIT 10
    """)
    
    # Statistiques descriptives
    stats_descriptives = db.fetch_one("""
        SELECT 
            COUNT(*) as nb_total,
            SUM(montant) as montant_total,
            ROUND(AVG(montant), 2) as moyenne,
            ROUND(MIN(montant), 2) as minimum,
            ROUND(MAX(montant), 2) as maximum,
            ROUND(AVG(CASE WHEN type='DEPOT' THEN montant END), 2) as depot_moyen,
            ROUND(AVG(CASE WHEN type='RETRAIT' THEN montant END), 2) as retrait_moyen
        FROM transactions
    """)
    
    return render_template('analyses/transactions.html',
        analyse_mensuelle=analyse_mensuelle,
        analyse_agences=analyse_agences,
        analyse_canaux=analyse_canaux,
        analyse_categories=analyse_categories,
        heures_pointe=heures_pointe,
        stats_descriptives=stats_descriptives
    )

# ============================================
# INTERFACE 4.2 : ANALYSE SATISFACTION
# ============================================
@app.route('/analyses/satisfaction')
@login_required
@role_required(['admin', 'analyste', 'manager'])
def analyse_satisfaction():
    """Interface d'analyse descriptive de la satisfaction"""
    
    # Scores moyens par dimension
    scores_dimensions = db.fetch_one("""
        SELECT 
            ROUND(AVG(score_global), 2) as score_global_moyen,
            ROUND(AVG(score_accueil), 2) as score_accueil_moyen,
            ROUND(AVG(score_temps_attente), 2) as score_attente_moyen,
            ROUND(AVG(score_conseil), 2) as score_conseil_moyen,
            ROUND(AVG(score_digital), 2) as score_digital_moyen,
            COUNT(*) as nb_enquetes
        FROM enquetes_satisfaction
    """)
    
    # Distribution des scores
    distribution_scores = db.fetch_all("""
        SELECT 
            CASE 
                WHEN score_global <= 4 THEN 'Très insatisfait (0-4)'
                WHEN score_global <= 6 THEN 'Insatisfait (5-6)'
                WHEN score_global <= 7 THEN 'Neutre (7)'
                WHEN score_global <= 8 THEN 'Satisfait (8)'
                ELSE 'Très satisfait (9-10)'
            END as categorie,
            COUNT(*) as nb_clients,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM enquetes_satisfaction), 2) as pourcentage
        FROM enquetes_satisfaction
        GROUP BY categorie
        ORDER BY MIN(score_global)
    """)
    
    # Tendance mensuelle
    tendance_mensuelle = db.fetch_all("""
        SELECT 
            strftime('%Y-%m', date_enquete) as mois,
            ROUND(AVG(score_global), 2) as score_moyen,
            COUNT(*) as nb_reponses
        FROM enquetes_satisfaction
        WHERE date_enquete >= date('now', '-6 months')
        GROUP BY mois
        ORDER BY mois
    """)
    
    # Par agence
    par_agence = db.fetch_all("""
        SELECT 
            agence,
            ROUND(AVG(score_global), 2) as score_moyen,
            COUNT(*) as nb_reponses,
            ROUND(AVG(score_accueil), 2) as accueil,
            ROUND(AVG(score_temps_attente), 2) as attente,
            ROUND(AVG(score_conseil), 2) as conseil
        FROM enquetes_satisfaction
        GROUP BY agence
        ORDER BY score_moyen DESC
    """)
    
    # Taux de recommandation
    taux_recommandation = db.fetch_one("""
        SELECT 
            ROUND(AVG(CASE WHEN recommandation = 1 THEN 100 ELSE 0 END), 2) as taux_reco,
            SUM(CASE WHEN recommandation = 1 THEN 1 ELSE 0 END) as nb_recommandent,
            COUNT(*) as total
        FROM enquetes_satisfaction
    """)
    
    return render_template('analyses/satisfaction.html',
        scores_dimensions=scores_dimensions,
        distribution_scores=distribution_scores,
        tendance_mensuelle=tendance_mensuelle,
        par_agence=par_agence,
        taux_recommandation=taux_recommandation
    )

# ============================================
# INTERFACE 4.3 : ANALYSE PRODUITS
# ============================================
@app.route('/analyses/produits')
@login_required
@role_required(['admin', 'analyste', 'manager'])
def analyse_produits():
    """Interface d'analyse descriptive des produits"""
    
    # Volume par type de produit
    volume_produits = db.fetch_all("""
        SELECT 
            type_produit,
            COUNT(*) as nb_souscriptions,
            SUM(montant_souscription) as montant_total,
            ROUND(AVG(montant_souscription), 2) as montant_moyen,
            ROUND(AVG(taux_interet), 2) as taux_moyen
        FROM produits_souscrits
        GROUP BY type_produit
        ORDER BY nb_souscriptions DESC
    """)
    
    # Évolution mensuelle
    evolution_mensuelle = db.fetch_all("""
        SELECT 
            strftime('%Y-%m', date_souscription) as mois,
            COUNT(*) as nb_souscriptions,
            SUM(montant_souscription) as montant_total,
            COUNT(DISTINCT client_id) as nouveaux_clients
        FROM produits_souscrits
        WHERE date_souscription >= date('now', '-12 months')
        GROUP BY mois
        ORDER BY mois
    """)
    
    # Performance par agence
    performance_agences = db.fetch_all("""
        SELECT 
            agence,
            COUNT(*) as nb_produits,
            SUM(montant_souscription) as montant_total,
            COUNT(DISTINCT client_id) as clients_uniques,
            COUNT(DISTINCT type_produit) as diversite_produits
        FROM produits_souscrits
        GROUP BY agence
        ORDER BY montant_total DESC
    """)
    
    # Taux de conversion par canal
    conversion_canal = db.fetch_all("""
        SELECT 
            canal_souscription,
            COUNT(*) as nb_souscriptions,
            SUM(montant_souscription) as montant_total,
            ROUND(AVG(montant_souscription), 2) as panier_moyen
        FROM produits_souscrits
        GROUP BY canal_souscription
        ORDER BY nb_souscriptions DESC
    """)
    
    # Analyse démographique
    analyse_age = db.fetch_all("""
        SELECT 
            CASE 
                WHEN c.age < 25 THEN '18-24 ans'
                WHEN c.age < 35 THEN '25-34 ans'
                WHEN c.age < 50 THEN '35-49 ans'
                WHEN c.age < 65 THEN '50-64 ans'
                ELSE '65+ ans'
            END as tranche_age,
            COUNT(*) as nb_produits,
            COUNT(DISTINCT p.client_id) as clients,
            ROUND(AVG(p.montant_souscription), 2) as montant_moyen
        FROM produits_souscrits p
        JOIN clients c ON p.client_id = c.id
        GROUP BY tranche_age
        ORDER BY MIN(c.age)
    """)
    
    return render_template('analyses/produits.html',
        volume_produits=volume_produits,
        evolution_mensuelle=evolution_mensuelle,
        performance_agences=performance_agences,
        conversion_canal=conversion_canal,
        analyse_age=analyse_age
    )

# ============================================
# INTERFACE 5 : RAPPORTS & EXPORT
# ============================================
@app.route('/rapports')
@login_required
@role_required(['admin', 'analyste', 'manager'])
def rapports():
    """Interface de génération de rapports"""
    return render_template('rapports.html')

@app.route('/api/export/<string:type_export>')
@login_required
def export_data(type_export):
    """Export des données en CSV/Excel"""
    
    if type_export == 'transactions':
        data = db.fetch_all("""
            SELECT t.*, c.nom, c.prenom 
            FROM transactions t 
            LEFT JOIN clients c ON t.client_id = c.id
            ORDER BY t.date_transaction DESC
        """)
        filename = f"transactions_{datetime.now().strftime('%Y%m%d')}.csv"
        
    elif type_export == 'satisfaction':
        data = db.fetch_all("""
            SELECT e.*, c.nom, c.prenom
            FROM enquetes_satisfaction e
            LEFT JOIN clients c ON e.client_id = c.id
            ORDER BY e.date_enquete DESC
        """)
        filename = f"satisfaction_{datetime.now().strftime('%Y%m%d')}.csv"
        
    elif type_export == 'produits':
        data = db.fetch_all("""
            SELECT p.*, c.nom, c.prenom
            FROM produits_souscrits p
            LEFT JOIN clients c ON p.client_id = c.id
            ORDER BY p.date_souscription DESC
        """)
        filename = f"produits_{datetime.now().strftime('%Y%m%d')}.csv"
    
    else:
        return jsonify({'error': 'Type d\'export invalide'}), 400
    
    # Génération CSV
    output = io.StringIO()
    if data:
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    
    # Envoi du fichier
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    output.close()
    
    db.execute_query(
        "INSERT INTO audit_log (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
        [current_user.id, 'EXPORT_DONNEES', f"Export {type_export}", request.remote_addr]
    )
    
    return send_file(
        mem,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

# ============================================
# INTERFACE 6 : GESTION UTILISATEURS
# ============================================
@app.route('/utilisateurs')
@login_required
@role_required(['admin'])
def utilisateurs():
    """Interface de gestion des utilisateurs"""
    users = db.fetch_all("""
        SELECT u.*, 
               (SELECT COUNT(*) FROM audit_log WHERE user_id = u.id) as actions,
               (SELECT MAX(timestamp) FROM audit_log WHERE user_id = u.id) as derniere_action
        FROM users u
        ORDER BY u.username
    """)
    
    audit_logs = db.fetch_all("""
        SELECT a.*, u.username
        FROM audit_log a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.timestamp DESC
        LIMIT 100
    """)
    
    return render_template('utilisateurs.html', 
        users=users,
        audit_logs=audit_logs
    )

@app.route('/api/users', methods=['POST'])
@login_required
@role_required(['admin'])
def create_user():
    """Création d'un utilisateur"""
    data = request.get_json()
    
    # Validation
    if not data.get('username') or not data.get('password') or not data.get('role'):
        return jsonify({'success': False, 'message': 'Champs obligatoires manquants'}), 400
    
    # Vérification unicité
    existing = db.fetch_one("SELECT id FROM users WHERE username = ?", [data['username']])
    if existing:
        return jsonify({'success': False, 'message': 'Utilisateur existant'}), 409
    
    db.execute_query("""
        INSERT INTO users (username, password, role, agence, email)
        VALUES (?, ?, ?, ?, ?)
    """, [
        data['username'],
        data['password'],  # En production: hashage
        data['role'],
        data.get('agence', 'Siège'),
        data.get('email')
    ])
    
    return jsonify({'success': True, 'message': 'Utilisateur créé'}), 201

# ============================================
# API POUR LES GRAPHIQUES DYNAMIQUES
# ============================================
@app.route('/api/charts/transactions-volume')
@login_required
def chart_transactions_volume():
    """Données pour graphique volume transactions"""
    data = db.fetch_all("""
        SELECT date_transaction as date, COUNT(*) as volume, SUM(montant) as montant
        FROM transactions
        WHERE date_transaction >= date('now', '-30 days')
        GROUP BY date_transaction
        ORDER BY date_transaction
    """)
    return jsonify(data)

@app.route('/api/charts/satisfaction-radar')
@login_required
def chart_satisfaction_radar():
    """Données pour graphique radar satisfaction"""
    data = db.fetch_one("""
        SELECT 
            ROUND(AVG(score_accueil), 2) as accueil,
            ROUND(AVG(score_temps_attente), 2) as temps_attente,
            ROUND(AVG(score_conseil), 2) as conseil,
            ROUND(AVG(score_digital), 2) as digital,
            ROUND(AVG(score_global), 2) as global
        FROM enquetes_satisfaction
    """)
    return jsonify(data)

@app.route('/api/charts/produits-distribution')
@login_required
def chart_produits_distribution():
    """Données pour graphique distribution produits"""
    data = db.fetch_all("""
        SELECT type_produit, COUNT(*) as valeur
        FROM produits_souscrits
        GROUP BY type_produit
    """)
    return jsonify(data)

# ============================================
# GESTION DES ERREURS
# ============================================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500

# ============================================
# INITIALISATION ET LANCEMENT
# ============================================
def init_database():
    """Initialisation de la base de données"""
    db.execute_query("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'agent', 'guichetier', 'conseiller', 'analyste', 'manager')),
            agence TEXT,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Création utilisateur admin par défaut
    admin_exists = db.fetch_one("SELECT id FROM users WHERE username = 'admin'")
    if not admin_exists:
        db.execute_query("""
            INSERT INTO users (username, password, role, agence, email)
            VALUES ('admin', 'admin123', 'admin', 'Siège', 'admin@banque.cm')
        """)
    
    db.execute_query("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

if __name__ == '__main__':
    import os
    init_database()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
