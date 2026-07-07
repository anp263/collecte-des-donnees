"""
config.py – Configuration et constantes du dashboard
"""
import os

# Chemins des fichiers
DB_PATH = "consolidated.db"
PEAK_CONFIG_FILE = "peak_hours_config.json"
STATE_FILE = "planning_state.json"
MAG_POS_FILE = "magasin_positions.json"
K_OVERRIDE_FILE = "k_overrides.json"
BRAND_MAP_FILE = "brand_mapping.json"
COMMUNE_NIVEAU_FILE = "commune_niveau.json"
SUPERMARCHES_CSV = "supermarches.csv"
FREQUENTATION_CSV = "fréquentation.csv"
STORE_MAPPING_CORRECTIONS = "store_mapping_corrections.json"
ANOMALY_SETTINGS_FILE = "anomaly_settings.json"

# Paramètres par défaut des anomalies
DEFAULT_ANOMALY_SETTINGS = {
    "intervalle_min_secondes": 90,
    "refus_min_secondes": 5,
    "distance_gps_questionnaire_m": 150,
    "distance_gps_comptage_m": 100,
    "prix_litre_min_fc": 1000,
    "prix_litre_max_fc": 10000,
    "volume_max_litres": 25,
    "taux_sortie_max_par_heure": 300,
    "duree_max_heures": 12,
    "prix_min_fc": 100,
    "prix_max_fc": 50000,
    "duree_min_comptage_minutes": 10,
    "total_min_comptage": 10
}

# Paramètres de cache
CACHE_TTL_DATA = 3600       # 1h pour les données lourdes
CACHE_TTL_LIGHT = 7200      # 2h pour les données légères
CACHE_TTL_DEFAULT = 300     # fallback
