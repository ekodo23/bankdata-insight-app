import sqlite3
import threading

class Database:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.db_path = 'banque.db'
        self._local = threading.local()
    
    def get_connection(self):
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    def execute_query(self, query, params=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params or [])
        conn.commit()
        return cursor
    
    def fetch_all(self, query, params=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params or [])
        return [dict(row) for row in cursor.fetchall()]
    
    def fetch_one(self, query, params=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params or [])
        row = cursor.fetchone()
        return dict(row) if row else None

    def create_tables(self):
        self.execute_query("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, agence TEXT, email TEXT)")
        self.execute_query("CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, prenom TEXT NOT NULL, age INTEGER, telephone TEXT, email TEXT, agence TEXT)")
        self.execute_query("CREATE TABLE IF NOT EXISTS agences (id INTEGER PRIMARY KEY AUTOINCREMENT, agence TEXT UNIQUE NOT NULL, ville TEXT, region TEXT)")
        self.execute_query("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, client_nom TEXT NOT NULL, type TEXT NOT NULL, montant REAL NOT NULL, devise TEXT DEFAULT 'XAF', date_transaction DATE NOT NULL, heure_transaction TIME NOT NULL, agence TEXT, canal TEXT, categorie TEXT, description TEXT, agent_id INTEGER)")
        self.execute_query("CREATE TABLE IF NOT EXISTS enquetes_satisfaction (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, agence TEXT, date_enquete DATE NOT NULL, score_global INTEGER NOT NULL, score_accueil INTEGER, score_temps_attente INTEGER, score_conseil INTEGER, score_digital INTEGER, commentaire TEXT, recommandation BOOLEAN DEFAULT 0, canal_enquete TEXT, agent_id INTEGER)")
        self.execute_query("CREATE TABLE IF NOT EXISTS produits_souscrits (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, type_produit TEXT NOT NULL, nom_produit TEXT NOT NULL, date_souscription DATE NOT NULL, montant_souscription REAL DEFAULT 0, taux_interet REAL DEFAULT 0, duree_mois INTEGER, agence TEXT, canal_souscription TEXT, statut TEXT DEFAULT 'ACTIF', agent_id INTEGER)")
        
        existing = self.fetch_one("SELECT id FROM users WHERE username = 'admin'")
        if not existing:
            self.execute_query("INSERT INTO users (username, password, role, agence, email) VALUES ('admin','admin123','admin','Siege','admin@banque.cm')")
        
        clients_default = [
            ('DUPONT', 'Jean', 35, '670000001'),
            ('MARTIN', 'Marie', 28, '670000002'),
            ('KAMGA', 'Paul', 45, '670000003'),
            ('NJOYA', 'Alice', 32, '670000004'),
            ('FOTSO', 'Pierre', 50, '670000005'),
        ]
        for nom, prenom, age, tel in clients_default:
            self.execute_query(
                "INSERT OR IGNORE INTO clients (nom, prenom, age, telephone, agence) VALUES (?, ?, ?, ?, ?)",
                [nom, prenom, age, tel, 'Centre-Ville']
            )
        
        for ag in ['Siege','Centre-Ville','Marche Central','Port','Zone Industrielle']:
            self.execute_query("INSERT OR IGNORE INTO agences (agence, ville) VALUES (?,?)", [ag, 'Douala'])

db = Database()
