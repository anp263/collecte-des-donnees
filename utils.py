"""
utils.py – Fonctions utilitaires pour le dashboard
"""
import re
import json
import hashlib
import unicodedata
import numpy as np
import pandas as pd
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, time
from difflib import SequenceMatcher

# ──────────────────────────────────────────────
# Formatage
# ──────────────────────────────────────────────

def make_hashable(df):
    """Convertit toutes les colonnes contenant des listes/dicts/ndarray en chaînes JSON.
    Vérifie TOUTES les valeurs (pas seulement un échantillon).
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            # Vérification rapide : essai de hasher la première valeur non-nulle
            first_valid = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
            if first_valid is not None and isinstance(first_valid, (list, dict, np.ndarray)):
                df[col] = df[col].apply(
                    lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict, np.ndarray)) else x
                )
            else:
                # Vérification exhaustive pour détecter des valeurs non-hashables
                non_hashable_types = {list, dict, np.ndarray}
                detected_types = set()
                for val in df[col].dropna():
                    if isinstance(val, (list, dict, np.ndarray)):
                        detected_types.add(type(val))
                        if len(detected_types) >= 3:
                            break
                if detected_types:
                    df[col] = df[col].apply(
                        lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict, np.ndarray)) else x
                    )
    return df


def deserialize_obj_cols(df):
    """Convertit les chaînes JSON en dict/list pour restaurer les types originaux."""
    df = df.copy()
    for col in df.columns:
        if df[col].apply(
            lambda x: isinstance(x, str) and (x.startswith('{') or x.startswith('['))
        ).any():
            df[col] = df[col].apply(
                lambda x: json.loads(x) if isinstance(x, str) and (x.startswith('{') or x.startswith('[')) else x
            )
    return df


def fmt_volume(val, decimals=0):
    if pd.isna(val) or val is None or not np.isfinite(val):
        return ""
    if decimals == 0:
        return f"{int(round(float(val))):,}".replace(",", " ")
    else:
        return f"{float(val):,.{decimals}f}".replace(",", " ")


def fmt_prix(val, devise=None):
    if pd.isna(val) or val is None or not np.isfinite(val):
        return ""
    if devise is None:
        import streamlit as st
        devise = st.session_state.get("devise_globale", "FC")
    if devise == "FC":
        return f"{int(round(float(val))):,}".replace(",", " ") + " FC"
    else:
        return f"{float(val):,.2f}".replace(",", " ") + " $"


def fmt_nombre(val, decimals=0):
    """Formate un nombre générique avec séparateur d'espaces et décimale optionnelle."""
    if pd.isna(val) or val is None:
        return ""
    if decimals == 0:
        return f"{int(round(float(val))):,}".replace(",", " ")
    else:
        return f"{float(val):,.{decimals}f}".replace(",", " ")


# ──────────────────────────────────────────────
# Normalisation
# ──────────────────────────────────────────────

def normalize_name(name):
    return name.strip().lower() if name else ""


def normalize_brand(name):
    if not isinstance(name, str):
        return ""
    name = name.lower().strip()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = re.sub(r'[^a-z0-9\s%]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similar(a, b, threshold=0.85):
    return SequenceMatcher(None, a, b).ratio() >= threshold


# ──────────────────────────────────────────────
# GPS & Distance
# ──────────────────────────────────────────────

def parse_gps(gps_str):
    """Retourne (lat, lon) ou (None, None)"""
    if not gps_str or ',' not in gps_str:
        return None, None
    parts = gps_str.split(',')
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
        return lat, lon
    except:
        return None, None


def haversine(lat1, lon1, lat2, lon2):
    """Distance en km entre deux points GPS (formule de Haversine)"""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


# ──────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────

def extraire_litres(texte):
    if not texte:
        return None
    match = re.search(r'(\d+(?:[.,]\d+)?)', texte)
    if match:
        return float(match.group(1).replace(',', '.'))
    return None


def parse_time(t_str):
    try:
        return datetime.strptime(t_str.strip(), '%H:%M').time()
    except:
        return None


# ──────────────────────────────────────────────
# Brand mapping
# ──────────────────────────────────────────────

def load_brand_mapping():
    from config import BRAND_MAP_FILE
    import os
    if os.path.exists(BRAND_MAP_FILE):
        with open(BRAND_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_brand_mapping(mapping):
    from config import BRAND_MAP_FILE
    with open(BRAND_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


def get_official_brands(df_prices_ext):
    """Retourne l'ensemble des marques officielles : supermarchés.csv + cibles du mapping."""
    base = set()
    if not df_prices_ext.empty:
        base = set(normalize_brand(b) for b in df_prices_ext['marque'].unique())
    mapping = load_brand_mapping()
    targets = set(v for v in mapping.values() if v)
    return base | targets


def apply_brand_mapping_strict(series, df_prices_ext):
    """
    Applique le mapping et ne conserve que les marques officielles.
    """
    official = get_official_brands(df_prices_ext)
    mapping = load_brand_mapping()
    def mapper(b):
        if not isinstance(b, str) or b.strip() == '':
            return None
        b_norm = normalize_brand(b.replace('Autre:', ''))
        if b_norm in official:
            return b_norm
        if b_norm in mapping:
            target = mapping[b_norm]
            if target in official:
                return target
        return None
    return series.apply(mapper)


def apply_brand_mapping_soft(series):
    """
    Remplace les marques qui sont dans le mapping.
    Les autres sont normalisées mais conservées telles quelles.
    """
    mapping = load_brand_mapping()
    def mapper(b):
        if not isinstance(b, str) or b.strip() == '':
            return 'Inconnue'
        b_norm = normalize_brand(b.replace('Autre:', ''))
        if b_norm in mapping:
            return mapping[b_norm]
        return b_norm
    return series.apply(mapper)


# ──────────────────────────────────────────────
# Commune niveau
# ──────────────────────────────────────────────

def load_commune_niveau():
    from config import COMMUNE_NIVEAU_FILE
    import os
    if os.path.exists(COMMUNE_NIVEAU_FILE):
        with open(COMMUNE_NIVEAU_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    default = {
        "gombe": "Aisé", "ngaliema": "Aisé", "limete": "Aisé",
        "lingwala": "Moyen", "kalamu": "Moyen", "barumbu": "Moyen",
        "kinshasa": "Moyen", "bandalungwa": "Moyen", "ngiri-ngiri": "Moyen",
        "kasa-vubu": "Moyen", "lemba": "Moyen",
        "matete": "Populaire", "ndjili": "Populaire", "masina": "Populaire",
        "kimbanseke": "Populaire", "mont-ngafula": "Populaire",
        "selembao": "Populaire", "maluku": "Populaire", "nsele": "Populaire"
    }
    return default


def save_commune_niveau(mapping):
    from config import COMMUNE_NIVEAU_FILE
    with open(COMMUNE_NIVEAU_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────
# Hash & Timing
# ──────────────────────────────────────────────

def get_settings_hash(settings):
    """Calcule un hash des paramètres actuels."""
    s = json.dumps(settings, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()


def to_float(val):
    """Convertit une valeur en float, gère les chaînes avec virgules."""
    if pd.isna(val) or val == '':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '.').replace(' ', ''))
    except:
        return 0.0


def get_sm_hash():
    from config import SUPERMARCHES_CSV
    import os
    if not os.path.exists(SUPERMARCHES_CSV):
        return ""
    with open(SUPERMARCHES_CSV, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()
