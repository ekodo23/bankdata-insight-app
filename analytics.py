import statistics
from typing import Dict, Any, List
from config import Config

class BankingAnalytics:
    
    def __init__(self, db):
        self.db = db
    
    def get_transaction_stats(self) -> Dict:
        stats = self.db.fetch_one("""
            SELECT 
                COUNT(*) as nb_total,
                COALESCE(SUM(montant), 0) as montant_total,
                ROUND(AVG(montant), 2) as moyenne,
                MIN(montant) as minimum,
                MAX(montant) as maximum
            FROM transactions
        """)
        return stats
    
    def get_monthly_volume(self) -> List:
        return self.db.fetch_all("""
            SELECT strftime('%Y-%m', date_transaction) as periode,
                   COUNT(*) as volume,
                   SUM(montant) as montant_total
            FROM transactions
            WHERE date_transaction >= date('now', '-12 months')
            GROUP BY periode ORDER BY periode
        """)
    
    def get_agency_performance(self) -> List:
        return self.db.fetch_all("""
            SELECT agence, COUNT(*) as volume,
                   SUM(montant) as montant_total,
                   ROUND(AVG(montant), 2) as montant_moyen
            FROM transactions
            GROUP BY agence ORDER BY volume DESC
        """)
    
    def get_satisfaction_stats(self) -> Dict:
        return self.db.fetch_one("""
            SELECT 
                ROUND(AVG(score_global), 2) as score_moyen,
                COUNT(*) as nb_enquetes,
                ROUND(AVG(CASE WHEN recommandation = 1 THEN 100 ELSE 0 END), 2) as taux_reco
            FROM enquetes_satisfaction
        """)
    
    def get_product_distribution(self) -> List:
        return self.db.fetch_all("""
            SELECT type_produit, COUNT(*) as nb,
                   SUM(montant_souscription) as montant_total
            FROM produits_souscrits
            GROUP BY type_produit ORDER BY nb DESC
        """)
