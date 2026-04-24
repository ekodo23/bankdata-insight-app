import re
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from config import Config

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    sanitized_data: Optional[Dict[str, Any]] = None

class BankDataValidator:
    
    def validate_transaction(self, data: Dict[str, Any]) -> ValidationResult:
        errors = []
        sanitized = {}
        
        if not data.get('client_id'):
            errors.append("Client requis")
        else:
            sanitized['client_id'] = str(data['client_id'])
        
        if not data.get('client_nom', '').strip():
            errors.append("Nom client requis")
        else:
            sanitized['client_nom'] = data['client_nom'].strip().upper()
        
        if data.get('type') not in Config.TYPES_TRANSACTION:
            errors.append("Type de transaction invalide")
        else:
            sanitized['type'] = data['type']
        
        try:
            montant = float(data.get('montant', 0))
            if montant <= 0 or montant > 100000000:
                errors.append("Montant invalide")
            else:
                sanitized['montant'] = round(montant, 2)
        except (ValueError, TypeError):
            errors.append("Montant invalide")
        
        try:
            date_t = datetime.strptime(data.get('date_transaction', ''), '%Y-%m-%d').date()
            if date_t > date.today():
                errors.append("Date future non autorisée")
            else:
                sanitized['date_transaction'] = str(date_t)
        except (ValueError, TypeError):
            errors.append("Date invalide")
        
        try:
            heure = data.get('heure_transaction', '')
            datetime.strptime(heure, '%H:%M')
            sanitized['heure_transaction'] = heure
        except (ValueError, TypeError):
            errors.append("Heure invalide")
        
        if not data.get('agence', '').strip():
            errors.append("Agence requise")
        else:
            sanitized['agence'] = data['agence'].strip()
        
        if data.get('canal') not in Config.CANAUX:
            errors.append("Canal invalide")
        else:
            sanitized['canal'] = data['canal']
        
        sanitized['devise'] = data.get('devise', 'XAF') if data.get('devise') in Config.DEVISES else 'XAF'
        sanitized['categorie'] = data.get('categorie', '')
        sanitized['description'] = data.get('description', '')[:200] if data.get('description') else None
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized if not errors else None
        )
    
    def validate_satisfaction(self, data: Dict[str, Any]) -> ValidationResult:
        errors = []
        sanitized = {}
        
        if not data.get('client_id'):
            errors.append("Client requis")
        else:
            sanitized['client_id'] = str(data['client_id'])
        
        for field in ['score_global', 'score_accueil', 'score_temps_attente', 'score_conseil', 'score_digital']:
            try:
                score = int(data.get(field, 0))
                if score < 1 or score > 10:
                    errors.append(f"{field} doit être entre 1 et 10")
                else:
                    sanitized[field] = score
            except (ValueError, TypeError):
                if field == 'score_global':
                    errors.append("Score global requis")
        
        try:
            date_e = datetime.strptime(data.get('date_enquete', ''), '%Y-%m-%d').date()
            sanitized['date_enquete'] = str(date_e)
        except (ValueError, TypeError):
            errors.append("Date invalide")
        
        if not data.get('agence', '').strip():
            errors.append("Agence requise")
        else:
            sanitized['agence'] = data['agence'].strip()
        
        sanitized['canal_enquete'] = data.get('canal_enquete', 'Face à face')
        sanitized['commentaire'] = data.get('commentaire', '')[:300] if data.get('commentaire') else None
        sanitized['recommandation'] = data.get('recommandation') == '1'
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized if not errors else None
        )
    
    def validate_produit(self, data: Dict[str, Any]) -> ValidationResult:
        errors = []
        sanitized = {}
        
        if not data.get('client_id'):
            errors.append("Client requis")
        else:
            sanitized['client_id'] = str(data['client_id'])
        
        if data.get('type_produit') not in Config.TYPES_PRODUITS:
            errors.append("Type de produit invalide")
        else:
            sanitized['type_produit'] = data['type_produit']
        
        if not data.get('nom_produit', '').strip():
            errors.append("Nom du produit requis")
        else:
            sanitized['nom_produit'] = data['nom_produit'].strip()
        
        try:
            date_s = datetime.strptime(data.get('date_souscription', ''), '%Y-%m-%d').date()
            sanitized['date_souscription'] = str(date_s)
        except (ValueError, TypeError):
            errors.append("Date invalide")
        
        if not data.get('agence', '').strip():
            errors.append("Agence requise")
        else:
            sanitized['agence'] = data['agence'].strip()
        
        sanitized['montant_souscription'] = float(data.get('montant_souscription', 0))
        sanitized['taux_interet'] = float(data.get('taux_interet', 0))
        sanitized['duree_mois'] = int(data.get('duree_mois', 0)) if data.get('duree_mois') else None
        sanitized['canal_souscription'] = data.get('canal_souscription', 'Agence')
        sanitized['statut'] = data.get('statut', 'ACTIF')
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized if not errors else None
        )
