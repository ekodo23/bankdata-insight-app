import os

class Config:
    APP_NAME = "BankData Insight"
    VERSION = "1.0.0"
    SECRET_KEY = os.environ.get('SECRET_KEY', 'banque-secure-key-2024')
    DATABASE = os.environ.get('DATABASE_URL', 'banque.db')
    
    TYPES_TRANSACTION = ['DEPOT', 'RETRAIT', 'VIREMENT', 'PAIEMENT']
    DEVISES = ['XAF', 'EUR', 'USD', 'GBP']
    CANAUX = ['Guichet', 'GAB', 'Mobile Banking', 'Internet Banking', 'Agence']
    
    CATEGORIES_TRANSACTION = [
        'Salaire', 'Épargne', 'Factures', 'Alimentation',
        'Transport', 'Logement', 'Santé', 'Éducation',
        'Loisirs', 'Transfert', 'Investissement', 'Autre'
    ]
    
    TYPES_PRODUITS = {
        'COMPTE_COURANT': {'nom': 'Compte Courant', 'icone': '📊'},
        'COMPTE_EPARGNE': {'nom': 'Compte Épargne', 'icone': '💰'},
        'CREDIT_IMMOBILIER': {'nom': 'Crédit Immobilier', 'icone': '🏠'},
        'CREDIT_CONSOMMATION': {'nom': 'Crédit Conso.', 'icone': '🛒'},
        'ASSURANCE_VIE': {'nom': 'Assurance Vie', 'icone': '🛡️'},
        'CARTE_BANCAIRE': {'nom': 'Carte Bancaire', 'icone': '💳'},
        'PLACEMENT': {'nom': 'Placement Financier', 'icone': '📈'}
    }
    
    CANAUX_ENQUETE = ['Face à face', 'Téléphone', 'Email', 'SMS', 'Application Mobile']
    
    ROLES = {
        'admin': 'Administrateur',
        'agent': 'Agent',
        'conseiller': 'Conseiller',
        'analyste': 'Analyste',
        'manager': 'Manager'
    }
