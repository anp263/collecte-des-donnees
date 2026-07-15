# utils.py – Version corrigée (position des notes export)
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
import os
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
import copy
import io
from PIL import Image

# Décorateur inactif (évite les boucles de re-rendu)
def timed(func):
    return func

from datetime import datetime, time
from difflib import SequenceMatcher


# ============================================================
# Constantes (chemins de fichiers, etc.)
# ============================================================
STATE_FILE = "planning_state.json"
MAG_POS_FILE = "magasin_positions.json"
K_OVERRIDE_FILE = "k_overrides.json"
BRAND_MAP_FILE = "brand_mapping.json"
COMMUNE_NIVEAU_FILE = "commune_niveau.json"
PEAK_CONFIG_FILE = "peak_hours_config.json"
DB_PATH = "consolidated.db"

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

# ============================================================
# Fonctions
# ============================================================

# ──────────────────────────────────────────────
# Formatage
# ──────────────────────────────────────────────

def make_hashable(df):
    """Convertit toutes les colonnes contenant des listes/dicts/ndarray en chaînes JSON."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            first_valid = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
            if first_valid is not None and isinstance(first_valid, (list, dict, np.ndarray)):
                df[col] = df[col].apply(
                    lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict, np.ndarray)) else x
                )
            else:
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
                devise = st.session_state.get("devise_globale", "FC")
    if devise == "FC":
        return f"{int(round(float(val))):,}".replace(",", " ") + " FC"
    else:
        return f"{float(val):,.2f}".replace(",", " ") + " $"


def convertir_prix(prix_fc, devise, taux):
    if pd.isna(prix_fc):
        return prix_fc
    if devise == 'USD':
        return round(prix_fc / taux, 2)
    return round(prix_fc, 0)


def tranche_age(age_str):
    if not isinstance(age_str, str):
        return None
    age_str = age_str.strip()
    if '25' not in age_str and '50' not in age_str and '35' not in age_str and 'ans' in age_str:
        if age_str.startswith(('-', '0', '1', '2', '3', '4')):
            return 'Moins de 25 ans'
        return '50 ans et plus'
    if '25' in age_str:
        return 'Moins de 25 ans'
    if '35' in age_str:
        return '25-34 ans'
    if '50' in age_str:
        return '35-49 ans'
    return '50 ans et plus'


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


def get_official_brands(df_prices_ext=None):
    """Retourne les marques officielles."""
    if df_prices_ext is None or (hasattr(df_prices_ext, 'empty') and df_prices_ext.empty):
        return set()
    base = set(normalize_brand(b) for b in df_prices_ext['marque'].unique())
    mapping = load_brand_mapping()
    targets = set(v for v in mapping.values() if v)
    return base | targets


def apply_brand_mapping_strict(series, df_prices_ext=None):
    """
    Applique le mapping et ne conserve que les marques officielles.
    """
    official = get_official_brands(df_prices_ext) if df_prices_ext is not None else get_official_brands()
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


# ============================================================
# Fonctions ajoutées pour les pages
# ============================================================

def force_black_axes(fig, title_size=18, tick_size=15, caption=None, export_width=None, export_height=None):
    """
    Applique une police noire et des tailles explicites à tous les axes,
    aux légendes, annotations et titres d'une figure Plotly.
    Peut aussi ajouter un caption intégré dans la figure (exportable).
    Cette fonction est conservée pour compatibilité mais n'est plus utilisée.
    """
    # Récupérer les dimensions depuis la session si non fournies
    if export_width is None:
        export_width = st.session_state.get("export_width", 1000)
    if export_height is None:
        export_height = st.session_state.get("export_height", 600)
    # Facteurs d'échelle
    scale_h = max(0.5, min(2.0, export_height / 600))
    scale_w = max(0.5, min(2.0, export_width / 1000))
    scale = min(scale_h, scale_w)
    # Titre général
    if fig.layout.title:
        fig.layout.title.font.color = "black"
        fig.layout.title.font.size = 22
        fig.layout.title.font.family = "Gilroy, sans-serif"
    # Légende
    if fig.layout.legend:
        fig.layout.legend.font.color = "black"
        fig.layout.legend.font.size = 13
    # Axes principaux et secondaires
    for axis_name in fig.layout:
        if axis_name.startswith('xaxis') or axis_name.startswith('yaxis'):
            axis = fig.layout[axis_name]
            if axis.title and axis.title.font:
                axis.title.font.color = "black"
                axis.title.font.size = title_size
            if axis.tickfont:
                axis.tickfont.color = "black"
                axis.tickfont.size = tick_size
    # Annotations
    if fig.layout.annotations:
        for ann in fig.layout.annotations:
            ann.font.color = "black"
    # Ajout du caption intégré dans la figure (exportable)
    if caption:
        # Largeur disponible pour le texte du caption
        avail_width_px = export_width * 0.9
        chars_per_line = max(20, int(avail_width_px / 6.5))
        # Retours à la ligne automatiques
        if len(caption) > chars_per_line:
            wrapped_text = ""
            for word in caption.split(' '):
                line_so_far = wrapped_text.split('<br>')[-1] if '<br>' in wrapped_text else wrapped_text
                if len(line_so_far) + len(word) + 1 > chars_per_line:
                    wrapped_text += '<br>' + word
                else:
                    prefix = ' ' if wrapped_text and not wrapped_text.endswith('<br>') else ''
                    wrapped_text += prefix + word
            caption = wrapped_text
        # Marge basée adaptative
        nb_lines = caption.count('<br>') + 1
        margin_b = max(40, min(120, int(80 * scale + 15 * nb_lines)))
        pos_y = max(-0.30, min(-0.10, -0.17 * scale))
        fig.add_annotation(
            text=caption,
            xref="paper", yref="paper",

            x=0.02, y=pos_y,
            xanchor="left",
            showarrow=False,
            font=dict(size=11, color="black", family="Gilroy, sans-serif")
        )

        fig.update_layout(margin=dict(b=margin_b))
    # Activer automargin sur tous les axes
    for axis_name in fig.layout:
        if axis_name.startswith('xaxis') or axis_name.startswith('yaxis'):
            axis = fig.layout[axis_name]
            if hasattr(axis, 'automargin'):
                axis.automargin = True
    return fig


def parse_criteres_smart(val):
    if isinstance(val, list):
        return val
    if not isinstance(val, str):
        return []
    result = []
    current = ''
    depth = 0
    for char in val:
        if char == '(':
            depth += 1
            current += char
        elif char == ')':
            depth -= 1
            current += char
        elif char == ',' and depth == 0:
            result.append(current.strip())
            current = ''
        else:
            current += char
    if current:
        result.append(current.strip())
    return result


def plot_with_caption(fig, caption_text=None, **kwargs):
    """
    Affiche un graphique Plotly avec une caption intégrée dans la figure (exportable en PNG).
    Cette fonction est conservée pour compatibilité mais n'est plus utilisée.
    """
    if caption_text:
        import copy
        fig = copy.deepcopy(fig)
        fig.add_annotation(
            text=caption_text,
            xref="paper", yref="paper",
            x=0.5, y=-0.17,
            showarrow=False,
            font=dict(size=11, color="gray", family="Gilroy, sans-serif")
        )
        fig.update_layout(margin=dict(b=80))
    st.plotly_chart(fig, **kwargs)


def get_top8_brands_from_acheteurs(df_acheteurs):
    """
    Retourne la liste des 8 marques les plus achetées (par nombre d'acheteurs)
    à partir d'un DataFrame d'acheteurs (avec colonne 'marque_clean').
    """
    if df_acheteurs.empty or 'marque_clean' not in df_acheteurs.columns:
        return []
    counts = df_acheteurs['marque_clean'].value_counts()
    return counts.head(8).index.tolist()


# ============================================================
# Fonctions ajoutées depuis dashboard.py
# ============================================================

def get_sm_hash():
    if not os.path.exists("supermarches.csv"):
        return ""
    with open("supermarches.csv", "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def build_unified_questionnaire_df(df_q_f):
    """Retourne un DataFrame avec toutes les réponses des questionnaires, unifié pour les trois types."""
    rows = []
    for _, row in df_q_f.iterrows():
        data = row['data_dict'] if isinstance(row['data_dict'], dict) else json.loads(row['data_dict'])
        qtype = row['type']
        if qtype == 'menage':
            sexe_age = data.get('Q10_SexeAgeClasse')
            nb_pers = data.get('Q1_NbPersonnes')
            achat_huile = str(data.get('Q2_Achat', '')).strip()
            freq = data.get('Q3_Frequence')
            marque = data.get('Q7_MarquePreferee')
            qte_nb = data.get('Q4_Quantite_Nombre')
            contenant = data.get('Q4_Quantite_Contenant')
            vol_unit = data.get('Q4_Quantite_VolumeUnitaire')
            prix = data.get('Q5_PrixHabituel')
            pourcent = data.get('Q6_Pourcentages')
            pret_plus = data.get('Q8_PretPayerPlus')
            prix_max = data.get('Q9_PrixMax')
            qualite = data.get('Q_Qualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = None
            supermarche_origine = None
            commune = data.get('Commune', '')
        elif qtype == 'supermarche_menage':
            sexe_age = data.get('Q11_SexeAgeClasse')
            nb_pers = data.get('Q2_NbPersonnes')
            achat_huile = str(data.get('Q3_Achat', '')).strip()
            freq = data.get('Q4_Frequence')
            marque = data.get('Q8_MarquePreferee')
            qte_nb = data.get('Q5_Quantite_Nombre')
            contenant = data.get('Q5_Quantite_Contenant')
            vol_unit = data.get('Q5_Quantite_VolumeUnitaire')
            prix = data.get('Q6_PrixHabituel')
            pourcent = data.get('Q7_Pourcentages')
            pret_plus = data.get('Q9_PretPayerPlus')
            prix_max = data.get('Q10_PrixMax')
            qualite = data.get('Q_Qualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = None
            supermarche_origine = data.get("Supermarché d'origine", '')
            commune = data.get('Commune', '')
        else:  # supermarche (acheteur)
            sexe_age = data.get('Q12_SexeAge')
            nb_pers = data.get('Q7_NbPersonnes')
            achat_huile = 'Oui'
            freq = data.get('Q6_Fréquence')
            marque = data.get('Q2_Marque')
            qte_nb = None
            contenant = None
            vol_unit = None
            vol_texte = data.get('Q4_Quantité')
            vol_total_sm = extraire_litres(vol_texte) if vol_texte else None
            prix = data.get('Q5_PrixPayé')
            pourcent = data.get('Q8_LieuxAchat')
            pret_plus = data.get('Q9_PretPayerPlus')
            prix_max = data.get('Q10_PrixMax')
            qualite = data.get('Q11_ReconnaitreQualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = data.get('Q3_Raison')
            supermarche_origine = data.get('Supermarché', '')
            commune = data.get('Commune', '')
        # Appliquer le mapping des marques (identique à celui de df_supermarche / df_menage)
        marque_clean = apply_brand_mapping_strict(pd.Series([marque])).iloc[0] if marque else None
        unified = {
            'uuid': row['uuid'],
            'date': row['date'],
            'enqueteur': row.get('enqueteur', row.get('Enquêteur', '')),
            'type': qtype,
            'statut': row.get('statut', ''),
            'magasin_officiel': row.get('magasin_officiel', ''),
            'lieu': row.get('lieu', ''),
            'sexe_age': sexe_age,
            'nb_personnes': nb_pers,
            'achat_huile': achat_huile,
            'frequence': freq,
            'marque_preferee': marque,
            'marque_clean': marque_clean,
            'quantite_nombre': qte_nb,
            'contenant': contenant,
            'volume_unitaire_l': vol_unit,
            'prix_paye': prix,
            'pourcentages_achat': pourcent,
            'pret_payer_plus': pret_plus,
            'prix_max': prix_max,
            'qualite': qualite,
            'rc_connaissance': rc_conn,
            'rc_qualites': rc_qual,
            'raison_choix': raison,
            'commune': commune,
            'supermarche_origine': supermarche_origine,
            'volume_total_l_supermarche': vol_total_sm if qtype == 'supermarche' else None,
        }
        rows.append(unified)
    return pd.DataFrame(rows)


# ============================================================
# Fonctions supplémentaires depuis dashboard.py
# ============================================================

def load_planning_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('equipes', []), data.get('selected_magasins', [])
    return [], []

def save_planning_state(equipes, selected_magasins):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'equipes': equipes, 'selected_magasins': selected_magasins}, f, indent=2)

def load_manual_positions():
    if os.path.exists(MAG_POS_FILE):
        with open(MAG_POS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_manual_positions(pos_dict):
    with open(MAG_POS_FILE, 'w', encoding='utf-8') as f:
        json.dump(pos_dict, f, indent=2)

def parse_time(t_str):
    try:
        return datetime.strptime(t_str.strip(), '%H:%M').time()
    except:
        return None

def load_peak_config():
    if os.path.exists(PEAK_CONFIG_FILE):
        with open(PEAK_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"groups": {}}

def save_peak_config(config):
    with open(PEAK_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def is_peak(dt, secteur, config):
    for groupe_name, groupe_data in config["groups"].items():
        if secteur in groupe_data["secteurs"]:
            day_type = 'semaine' if dt.weekday() < 5 else 'weekend'
            creneaux = groupe_data.get(day_type, [])
            t = dt.time()
            for debut_str, fin_str in creneaux:
                d = parse_time(debut_str)
                f = parse_time(fin_str)
                if d and f and d <= t <= f:
                    return True
            return False
    return False


# ============================================================
# Fonctions de validation et gestion des anomalies
# ============================================================

def get_settings_hash(settings):
    """Calcule un hash des paramètres actuels."""
    s = json.dumps(settings, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()

def init_anomalies_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS anomalies_dashboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT,
            type TEXT,
            date TEXT,
            enqueteur TEXT,
            anomaly_text TEXT,
            settings_hash TEXT,
            created_at TEXT
        )
    """)
    conn.commit()

def load_anomalies_from_db(conn, settings_hash):
    cur = conn.cursor()
    cur.execute("SELECT uuid, type, date, enqueteur, anomaly_text FROM anomalies_dashboard WHERE settings_hash = ?", (settings_hash,))
    rows = cur.fetchall()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]

def save_anomalies_to_db(conn, anomalies, settings_hash):
    cur = conn.cursor()
    cur.execute("DELETE FROM anomalies_dashboard WHERE settings_hash = ?", (settings_hash,))
    now = datetime.now().isoformat()
    for (uuid, typ, date, enqueteur, text) in anomalies:
        cur.execute(
            "INSERT INTO anomalies_dashboard (uuid, type, date, enqueteur, anomaly_text, settings_hash, created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid, typ, date, enqueteur, text, settings_hash, now)
        )
    conn.commit()

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

def load_anomaly_settings():
    if os.path.exists("anomaly_settings.json"):
        with open("anomaly_settings.json", "r") as f:
            return json.load(f)
    return DEFAULT_ANOMALY_SETTINGS.copy()

def save_anomaly_settings(settings):
    with open("anomaly_settings.json", "w") as f:
        json.dump(settings, f, indent=2)

def validate_questionnaire_dynamic(record, qtype, settings):
    """Validation intrinsèque paramétrable (UUID, prix/L, volume)"""
    anomalies = []
    if qtype == "supermarche":
        quantite_str = record.get('Q4_Quantité', '')
        prix_str = record.get('Q5_PrixPayé', '')
        if quantite_str and prix_str:
            vol = extraire_litres(quantite_str)
            try:
                prix = float(prix_str.replace(',', '.'))
                if vol and vol > 0:
                    prix_litre = prix / vol
                    if prix_litre < settings['prix_litre_min_fc'] or prix_litre > settings['prix_litre_max_fc']:
                        anomalies.append(f'Prix/litre hors normes ({prix_litre:.0f} FC/L)')
            except:
                pass
    elif qtype in ("menage", "supermarche_menage"):
        nb = record.get('Q4_Quantite_Nombre', '')
        cont = record.get('Q4_Quantite_Contenant', '')
        vol_unit_str = record.get('Q4_Quantite_VolumeUnitaire', '')
        prix_hab_str = record.get('Q5_PrixHabituel', '')
        if nb and cont and vol_unit_str:
            try:
                nb_int = int(nb)
                vol_unit = float(vol_unit_str.replace(',', '.'))
                vol_total = nb_int * vol_unit
                if vol_total > settings['volume_max_litres']:
                    anomalies.append(f'Volume acheté supérieur à {settings["volume_max_litres"]} L ({vol_total} L)')
                if prix_hab_str:
                    prix = float(prix_hab_str.replace(',', '.'))
                    if vol_total > 0:
                        prix_litre = prix / vol_total
                        if prix_litre < settings['prix_litre_min_fc'] or prix_litre > settings['prix_litre_max_fc']:
                            anomalies.append(f'Prix/litre hors normes ({prix_litre:.0f} FC/L)')
            except:
                pass
    return anomalies

def validate_counting_dynamic(record, settings):
    """Validation des comptages paramétrable"""
    anomalies = []
    debut = record.get('Heure début', '')
    fin = record.get('Heure fin', '')
    total_str = record.get('Total', '0')
    try:
        total = int(total_str)
        if debut and fin:
            fmt = '%H:%M:%S'
            t1 = datetime.strptime(debut, fmt)
            t2 = datetime.strptime(fin, fmt)
            duree = (t2 - t1).total_seconds() / 3600.0
            if duree > settings['duree_max_heures']:
                anomalies.append(f'Durée > {settings["duree_max_heures"]} h ({duree:.1f} h)')
            if duree > 0.5 and total == 0:
                anomalies.append('Durée > 30 min avec 0 sorties')
            if duree > 0 and total > 0 and (total / duree) > settings['taux_sortie_max_par_heure']:
                anomalies.append(f'Taux de sortie > {settings["taux_sortie_max_par_heure"]}/h ({total/duree:.0f}/h)')
    except:
        pass
    return anomalies

def validate_price_dynamic(record, settings):
    """Validation des prix paramétrable"""
    anomalies = []
    prix_str = record.get('Prix', '')
    try:
        prix = float(prix_str.replace(',', '.'))
        if prix < settings['prix_min_fc'] or prix > settings['prix_max_fc']:
            anomalies.append(f'Prix hors plage raisonnable ({prix} FC)')
    except:
        pass
    return anomalies

def compute_context_anomalies_questionnaire_dynamic(conn, uuid, record, qtype, settings):
    """Validation contextuelle paramétrable (intervalles, GPS)"""
    anomalies = []
    anom_counter = 1
    c = conn.cursor()
    date_str = record.get('Date', '')
    heure_str = record.get('Heure', '')
    if not date_str or not heure_str:
        return anomalies
    try:
        dt_new = datetime.strptime(f"{date_str} {heure_str}", '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return anomalies
    enqueteur = record.get('Enquêteur', '')
    c.execute("""
        SELECT uuid, type, date, heure, statut, data FROM questionnaires
        WHERE enqueteur = ? AND (type = 'supermarche' OR type = 'supermarche_menage')
          AND uuid != ?
        ORDER BY date, heure
    """, (enqueteur, uuid))
    existing_rows = c.fetchall()
    seq = []
    for row in existing_rows:
        r_uuid, r_type, r_date, r_heure, r_statut, r_data_json = row
        data = json.loads(r_data_json) if r_data_json else {}
        achat = data.get('Q3_Achat', '').strip().lower() if r_type == 'supermarche_menage' else None
        seq.append({
            'uuid': r_uuid, 'type': r_type, 'date': r_date, 'heure': r_heure,
            'statut': r_statut, 'achat': achat
        })
    new_achat = None
    if qtype == 'supermarche_menage':
        new_achat = record.get('Q3_Achat', '').strip().lower()
    seq.append({
        'uuid': uuid, 'type': qtype, 'date': date_str, 'heure': heure_str,
        'statut': record.get('Statut', ''), 'achat': new_achat
    })
    seq.sort(key=lambda x: (x['date'], x['heure']))
    for i in range(len(seq)-1):
        prev = seq[i]
        curr = seq[i+1]
        if prev['uuid'] != uuid and curr['uuid'] != uuid:
            continue
        try:
            dt_prev = datetime.strptime(f"{prev['date']} {prev['heure']}", '%Y-%m-%d %H:%M:%S')
            dt_curr = datetime.strptime(f"{curr['date']} {curr['heure']}", '%Y-%m-%d %H:%M:%S')
            delta = (dt_curr - dt_prev).total_seconds()
        except:
            continue
        # Règle Refus
        if prev['statut'] == 'Refus':
            if delta < settings['refus_min_secondes']:
                anomalies.append(
                    f"[{anom_counter}] Refus trop rapproché ({delta:.0f} s) "
                    f"- {curr['type']} après {prev['type']} (min {settings['refus_min_secondes']} s)"
                )
                anom_counter += 1
            continue
        # Exceptions
        if curr['type'] == 'supermarche_menage' and prev['type'] == 'supermarche':
            continue
        if prev['type'] == 'supermarche_menage' and prev['achat'] == 'non':
            continue
        if delta < settings['intervalle_min_secondes']:
            anomalies.append(
                f"[{anom_counter}] Intervalle trop court entre {curr['type']} et {prev['type']} "
                f"({delta:.0f} s) – minimum {settings['intervalle_min_secondes']}s (précédent UUID: {prev['uuid']})"
            )
            anom_counter += 1
    # Vérification GPS
    gps_str = record.get('GPS', '')
    lat_new, lon_new = parse_gps(gps_str)
    if lat_new is None or lon_new is None:
        return anomalies
    if qtype in ('supermarche', 'supermarche_menage'):
        if qtype == 'supermarche':
            lieu = record.get('Supermarché', '')
        else:
            lieu = record.get("Supermarché d'origine", '')
        if lieu:
            c.execute("""
                SELECT uuid, type, data FROM questionnaires
                WHERE (type = 'supermarche' OR type = 'supermarche_menage')
                  AND lieu = ? AND uuid != ?
            """, (lieu, uuid))
            coords = []
            for row in c.fetchall():
                _, _, other_data_json = row
                try:
                    other_rec = json.loads(other_data_json)
                    olat, olon = parse_gps(other_rec.get('GPS', ''))
                    if olat is not None and olon is not None:
                        coords.append((olat, olon))
                except:
                    pass
            if coords:
                lats = [c[0] for c in coords]
                lons = [c[1] for c in coords]
                lat_med = np.median(lats)
                lon_med = np.median(lons)
                dist = haversine(lat_new, lon_new, lat_med, lon_med)
                seuil_km = settings['distance_gps_questionnaire_m'] / 1000.0
                if dist > seuil_km:
                    anomalies.append(
                        f"[{anom_counter}] Distance GPS > {settings['distance_gps_questionnaire_m']} m "
                        f"par rapport à la médiane de '{lieu}' ({dist*1000:.0f} m)"
                    )
                    anom_counter += 1
    elif qtype == 'menage':
        lat_str = f"{lat_new:.5f}"
        lon_str = f"{lon_new:.5f}"
        c.execute("SELECT uuid, data FROM questionnaires WHERE type = 'menage' AND uuid != ?", (uuid,))
        for row in c.fetchall():
            other_uuid, other_data_json = row
            try:
                other_rec = json.loads(other_data_json)
                olat, olon = parse_gps(other_rec.get('GPS', ''))
                if olat is not None and olon is not None:
                    if f"{olat:.5f}" == lat_str and f"{olon:.5f}" == lon_str:
                        anomalies.append(
                            f"[{anom_counter}] Coordonnées GPS identiques à un autre ménage ({lat_str}, {lon_str})"
                        )
                        anom_counter += 1
                        break
            except:
                pass
    return anomalies

def compute_context_anomalies_counting_dynamic(conn, uuid, record, settings):
    """Validation contextuelle des comptages (GPS)"""
    anomalies = []
    anom_counter = 1
    gps_str = record.get('GPS', '')
    lat_new, lon_new = parse_gps(gps_str)
    if lat_new is None or lon_new is None:
        return anomalies
    lieu = record.get('Supermarché', '')
    if not lieu:
        return anomalies
    c = conn.cursor()
    c.execute("SELECT uuid, data FROM countings WHERE lieu = ? AND uuid != ?", (lieu, uuid))
    coords = []
    for row in c.fetchall():
        other_uuid, other_data = row
        try:
            other_rec = json.loads(other_data)
            olat, olon = parse_gps(other_rec.get('GPS', ''))
            if olat is not None and olon is not None:
                coords.append((olat, olon))
        except:
            pass
    if coords:
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        lat_med = np.median(lats)
        lon_med = np.median(lons)
        dist = haversine(lat_new, lon_new, lat_med, lon_med)
        seuil_km = settings['distance_gps_comptage_m'] / 1000.0
        if dist > seuil_km:
            anomalies.append(
                f"[{anom_counter}] Distance GPS > {settings['distance_gps_comptage_m']} m "
                f"par rapport à la médiane des comptages du même supermarché '{lieu}' ({dist*1000:.0f} m)"
            )
    return anomalies

def load_brand_mapping():
    if os.path.exists(BRAND_MAP_FILE):
        with open(BRAND_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_brand_mapping(mapping):
    with open(BRAND_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

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

def get_sm_hash():
    if not os.path.exists("supermarches.csv"):
        return ""
    with open("supermarches.csv", "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def load_planning_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('equipes', []), data.get('selected_magasins', [])
    return [], []

def save_planning_state(equipes, selected_magasins):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'equipes': equipes, 'selected_magasins': selected_magasins}, f, indent=2)

def extraire_litres(texte):
    if not texte:
        return None
    match = re.search(r'(\d+(?:[.,]\d+)?)', texte)
    if match:
        return float(match.group(1).replace(',', '.'))
    return None

def load_manual_positions():
    if os.path.exists(MAG_POS_FILE):
        with open(MAG_POS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_manual_positions(pos_dict):
    with open(MAG_POS_FILE, 'w', encoding='utf-8') as f:
        json.dump(pos_dict, f, indent=2)

def normalize_name(name):
    return name.strip().lower() if name else ""

def parse_time(t_str):
    try:
        return datetime.strptime(t_str.strip(), '%H:%M').time()
    except:
        return None

def load_peak_config():
    if os.path.exists(PEAK_CONFIG_FILE):
        with open(PEAK_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"groups": {}}

def save_peak_config(config):
    with open(PEAK_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def is_peak(dt, secteur, config):
    for groupe_name, groupe_data in config["groups"].items():
        if secteur in groupe_data["secteurs"]:
            day_type = 'semaine' if dt.weekday() < 5 else 'weekend'
            creneaux = groupe_data.get(day_type, [])
            t = dt.time()
            for debut_str, fin_str in creneaux:
                d = parse_time(debut_str)
                f = parse_time(fin_str)
                if d and f and d <= t <= f:
                    return True
            return False
    return False


def prepare_figure_for_export(fig, config=None, caption=None, export_width=None, export_height=None, dpi=96):
    """
    Prépare une figure Plotly pour un export propre.
    config : dict avec les clés suivantes (valeurs par défaut si absentes) :
        ...
        - title_text          (str)  : ''     → si non vide, remplace le titre principal
        - xaxis_title_text    (str)  : ''     → si non vide, remplace le titre de l'axe X
        - yaxis_title_text    (str)  : ''     → si non vide, remplace le titre de l'axe Y
        ...
    """
    if config is None:
        config = {}

    def get(key, default):
        return config.get(key, default)

    MAIN_TITLE_PT = get('main_title_pt', 11)
    LEGEND_PT = get('legend_pt', 9)
    LEGEND_TITLE_PT = get('legend_title_pt', 9)
    AXIS_TITLE_PT = get('axis_title_pt', 10)
    AXIS_TICK_PT = get('axis_tick_pt', 9)
    BAR_TEXT_PT = get('bar_text_pt', 10)
    PIE_PCT_PT = get('pie_pct_pt', 10)
    CAPTION_PT = get('caption_pt', 7)
    TITLE_Y = get('title_y', 0.98)
    PIE_DOMAIN_Y = get('pie_domain_y', [0.2, 0.8])
    PIE_DOMAIN_X = get('pie_domain_x', [0.1, 0.9])
    X_TICK_ANGLE = get('x_tick_angle', -15)
    CAPTION_X = get('caption_x', 0.02)
    CAPTION_Y = get('caption_y', -0.22)
    MARGIN_T = get('margin_t', 80)
    MARGIN_B = get('margin_b', 80)
    MARGIN_L = get('margin_l', 80)
    MARGIN_R = get('margin_r', 80)
    XAXIS_TITLE_STANDOFF = get('xaxis_title_standoff', 20)
    YAXIS_TITLE_STANDOFF = get('yaxis_title_standoff', 25)
    SHOW_LEGEND = get('show_legend', True)
    LEGEND_X = get('legend_x', 1.0)
    LEGEND_Y = get('legend_y', 0.5)
    SHOW_BAR_TEXT = get('show_bar_text', True)
    SHOW_CAPTION = get('show_caption', True)
    # --- nouveaux paramètres pour les titres personnalisés ---
    TITLE_TEXT = get('title_text', '')
    XAXIS_TITLE_TEXT = get('xaxis_title_text', '')
    YAXIS_TITLE_TEXT = get('yaxis_title_text', '')
    # ---
    WRAP_TITLE_FACTOR = get('wrap_title_max_chars_factor', 0.85)
    WRAP_AXIS_FACTOR = get('wrap_axis_label_max_chars_factor', 0.4)
    WRAP_LEGEND_FACTOR = get('wrap_legend_max_chars_factor', 0.30)
    WRAP_CAPTION_FACTOR = get('wrap_caption_max_chars_factor', 0.9)

    if export_width is None:
        export_width = st.session_state.get("export_width", 1000)
    if export_height is None:
        export_height = st.session_state.get("export_height", 600)

    # tailles en pixels
    main_title_px = MAIN_TITLE_PT * dpi / 72
    legend_px = LEGEND_PT * dpi / 72
    legend_title_px = LEGEND_TITLE_PT * dpi / 72
    title_px = AXIS_TITLE_PT * dpi / 72
    tick_px = AXIS_TICK_PT * dpi / 72
    bar_text_px = BAR_TEXT_PT * dpi / 72
    pie_pct_px = PIE_PCT_PT * dpi / 72
    caption_px = CAPTION_PT * dpi / 72

    def wrap_text(text, max_chars):
        if max_chars >= 200 or not isinstance(text, str):
            return text
        if len(text) <= max_chars:
            return text
        words = text.split(' ')
        lines = []
        current = ''
        for w in words:
            if len(current) + len(w) + 1 > max_chars and current:
                lines.append(current)
                current = w
            else:
                current = (current + ' ' + w) if current else w
        if current:
            lines.append(current)
        return '<br>'.join(lines)

    def max_chars_for_font(font_size_pt, width_factor, total_width_px):
        char_width_px = 0.5 * font_size_pt * dpi / 72
        if char_width_px <= 0:
            return 20
        return max(10, int(total_width_px * width_factor / char_width_px))

    title_max = max_chars_for_font(MAIN_TITLE_PT, WRAP_TITLE_FACTOR, export_width)
    axis_label_max = max_chars_for_font(AXIS_TICK_PT, WRAP_AXIS_FACTOR, export_width)
    legend_max = max_chars_for_font(LEGEND_PT, WRAP_LEGEND_FACTOR, export_width)
    is_pie = any(trace.type == 'pie' for trace in fig.data)

    # --- Traces ---
    for trace in fig.data:
        if hasattr(trace, 'name') and trace.name:
            trace.name = wrap_text(trace.name, legend_max)
        if hasattr(trace, 'labels') and trace.labels is not None and len(trace.labels) > 0:
            trace.labels = [wrap_text(l, legend_max if not is_pie else axis_label_max) for l in trace.labels]
        if hasattr(trace, 'text') and trace.text is not None and len(trace.text) > 0:
            trace.text = [wrap_text(t, axis_label_max) for t in trace.text]

        if trace.type == 'pie':
            trace.textinfo = 'percent+label'
            trace.textfont.size = pie_pct_px
            trace.showlegend = False
        elif trace.type == 'bar':
            if hasattr(trace, 'textfont'):
                trace.textfont.size = bar_text_px
            if not SHOW_BAR_TEXT:
                if hasattr(trace, 'textposition') and trace.textposition != 'none':
                    trace.textposition = 'none'
                    trace.text = None

    # --- Domaine camemberts ---
    if is_pie:
        for trace in fig.data:
            if trace.type == 'pie':
                trace.domain = dict(x=PIE_DOMAIN_X, y=PIE_DOMAIN_Y)

    # --- Titre principal ---
    if TITLE_TEXT and TITLE_TEXT.strip():
        fig.layout.title.text = TITLE_TEXT.strip()    # remplacement
    if fig.layout.title and fig.layout.title.text:
        fig.layout.title.font.color = "black"
        fig.layout.title.font.size = main_title_px
        fig.layout.title.font.family = "Gilroy, sans-serif"
        fig.layout.title.font.weight = "bold"
        fig.layout.title.y = TITLE_Y
        fig.layout.title.text = wrap_text(fig.layout.title.text, title_max)

    # --- Légende ---
    for trace in fig.data:
        if trace.type != 'pie':
            trace.showlegend = SHOW_LEGEND
    fig.update_layout(
        showlegend=SHOW_LEGEND,
        legend=dict(
            x=LEGEND_X,
            y=LEGEND_Y,
            xanchor='left',
            yanchor='middle',
            font=dict(size=legend_px, color="black", family="Gilroy, sans-serif"),
            title=dict(font=dict(size=legend_title_px, color="black"))
        )
    )

    # --- Axes ---
    for ax in fig.layout:
        if ax.startswith('xaxis') or ax.startswith('yaxis'):
            axis = fig.layout[ax]
            # Titre de l'axe personnalisé
            if ax.startswith('xaxis') and XAXIS_TITLE_TEXT and XAXIS_TITLE_TEXT.strip():
                if axis.title:
                    axis.title.text = XAXIS_TITLE_TEXT.strip()
                else:
                    axis.title = dict(text=XAXIS_TITLE_TEXT.strip())
            elif ax.startswith('yaxis') and YAXIS_TITLE_TEXT and YAXIS_TITLE_TEXT.strip():
                if axis.title:
                    axis.title.text = YAXIS_TITLE_TEXT.strip()
                else:
                    axis.title = dict(text=YAXIS_TITLE_TEXT.strip())

            if axis.title and axis.title.text:
                axis.title.font.color = "black"
                axis.title.font.size = title_px
                axis.title.text = wrap_text(axis.title.text, axis_label_max)
                if ax.startswith('xaxis'):
                    axis.title.standoff = XAXIS_TITLE_STANDOFF
                else:
                    axis.title.standoff = YAXIS_TITLE_STANDOFF
            if axis.tickfont:
                axis.tickfont.color = "black"
                axis.tickfont.size = tick_px

            if ax.startswith('xaxis'):
                axis.tickangle = X_TICK_ANGLE
                labels = []
                if hasattr(axis, 'ticktext') and axis.ticktext is not None:
                    labels = axis.ticktext
                elif hasattr(axis, 'categoryarray') and axis.categoryarray is not None:
                    labels = axis.categoryarray
                if labels:
                    max_len = max((len(str(l)) for l in labels), default=0)
                    if max_len > 8:
                        axis.tickfont.size = max(tick_px - 2, 6)

    # --- Annotations existantes ---
    if fig.layout.annotations:
        for ann in fig.layout.annotations:
            ann.font.color = "black"

    # --- Note (caption) ---
    if caption and SHOW_CAPTION:
        cap_wrapped = wrap_text(caption, max_chars_for_font(CAPTION_PT, WRAP_CAPTION_FACTOR, export_width))
        fig.add_annotation(
            text=cap_wrapped,
            xref="paper", yref="paper",
            x=CAPTION_X, y=CAPTION_Y,
            xanchor="left", yanchor="top",
            showarrow=False,
            font=dict(size=caption_px, color="black", family="Gilroy, sans-serif")
        )

    fig.update_layout(
        margin=dict(t=MARGIN_T, b=MARGIN_B, l=MARGIN_L, r=MARGIN_R),
        autosize=True,
        width=export_width,
        height=export_height,
        paper_bgcolor='white',
        plot_bgcolor='white'
    )

    for ax in fig.layout:
        if ax.startswith('xaxis') or ax.startswith('yaxis'):
            if hasattr(fig.layout[ax], 'automargin'):
                fig.layout[ax].automargin = True

    return fig


def plotly_chart_with_local_export(fig, caption=None, key="plot"):
    """
    Affiche un graphique Plotly avec export PNG et réglages avancés.
    """
    default_config = {
        'main_title_pt': 11,
        'legend_pt': 9,
        'legend_title_pt': 9,
        'axis_title_pt': 10,
        'axis_tick_pt': 9,
        'bar_text_pt': 10,
        'pie_pct_pt': 10,
        'caption_pt': 7,
        'title_y': 0.98,
        'pie_domain_y': [0.2, 0.8],
        'pie_domain_x': [0.1, 0.9],
        'x_tick_angle': -15,
        'caption_x': 0.02,
        'caption_y': -0.22,
        'margin_t': 80,
        'margin_b': 80,
        'margin_l': 80,
        'margin_r': 80,
        'xaxis_title_standoff': 20,
        'yaxis_title_standoff': 25,
        'show_legend': True,
        'legend_x': 1.0,
        'legend_y': 0.5,
        'show_bar_text': True,
        'show_caption': True,
        'title_text': '',          # nouveau
        'xaxis_title_text': '',    # nouveau
        'yaxis_title_text': '',    # nouveau
        'wrap_title_max_chars_factor': 0.85,
        'wrap_axis_label_max_chars_factor': 0.4,
        'wrap_legend_max_chars_factor': 0.30,
        'wrap_caption_max_chars_factor': 0.9,
        'export_width_cm': 16.0,
        'export_height_cm': 9.0,
    }

    config_key = f"{key}_config"
    if config_key not in st.session_state:
        st.session_state[config_key] = default_config.copy()
        # Initialiser les titres avec ceux de la figure originale (une seule fois)
        cfg = st.session_state[config_key]
        if fig.layout.title and fig.layout.title.text:
            cfg['title_text'] = fig.layout.title.text
        # Pour les axes, il faut chercher le premier xaxis/yaxis
        xaxis = None
        yaxis = None
        for ax in fig.layout:
            if ax.startswith('xaxis') and xaxis is None:
                xaxis = fig.layout[ax]
            if ax.startswith('yaxis') and yaxis is None:
                yaxis = fig.layout[ax]
        if xaxis and xaxis.title and xaxis.title.text:
            cfg['xaxis_title_text'] = xaxis.title.text
        if yaxis and yaxis.title and yaxis.title.text:
            cfg['yaxis_title_text'] = yaxis.title.text

    config = st.session_state[config_key]

    # --- Graphique principal ---
    fig_display = copy.deepcopy(fig)
    fig_display = prepare_figure_for_export(
        fig_display,
        config=config,
        caption=caption if config.get('show_caption', True) else None,
        export_width=1000,
        export_height=600,
        dpi=96
    )
    st.plotly_chart(fig_display, use_container_width=True, key=f"{key}_chart")

    # --- Panneau de réglages ---
    with st.expander("📥 Exporter ce graphique (PNG) + réglages avancés", expanded=False):
        st.markdown("#### Dimensions d'export")
        col1, col2 = st.columns(2)
        with col1:
            config['export_width_cm'] = st.number_input(
                "Largeur (cm)", min_value=2.0, max_value=50.0,
                value=config.get('export_width_cm', 16.0), step=0.5,
                key=f"{key}_export_width_cm"
            )
        with col2:
            config['export_height_cm'] = st.number_input(
                "Hauteur (cm)", min_value=2.0, max_value=50.0,
                value=config.get('export_height_cm', 9.0), step=0.5,
                key=f"{key}_export_height_cm"
            )

        st.markdown("#### Polices")
        col3, col4, col5 = st.columns(3)
        with col3:
            config['main_title_pt'] = st.slider("Titre principal (pt)", 6, 20, config['main_title_pt'], key=f"{key}_main_title_pt")
            config['axis_title_pt'] = st.slider("Titres axes (pt)", 6, 18, config['axis_title_pt'], key=f"{key}_axis_title_pt")
            config['legend_pt'] = st.slider("Légende (pt)", 6, 16, config['legend_pt'], key=f"{key}_legend_pt")
        with col4:
            config['axis_tick_pt'] = st.slider("Étiquettes axes (pt)", 6, 16, config['axis_tick_pt'], key=f"{key}_axis_tick_pt")
            config['pie_pct_pt'] = st.slider("Étiquettes camembert (pt)", 6, 16, config['pie_pct_pt'], key=f"{key}_pie_pct_pt")
            config['caption_pt'] = st.slider("Note (pt)", 5, 14, config['caption_pt'], key=f"{key}_caption_pt")
        with col5:
            config['legend_title_pt'] = st.slider("Titre légende (pt)", 6, 16, config['legend_title_pt'], key=f"{key}_legend_title_pt")
            config['bar_text_pt'] = st.slider("Texte barres (pt)", 6, 16, config['bar_text_pt'], key=f"{key}_bar_text_pt")

        st.markdown("#### Disposition")
        col6, col7 = st.columns(2)
        with col6:
            config['title_y'] = st.slider("Position titre (y)", 0.0, 1.0, config['title_y'], step=0.01, key=f"{key}_title_y")
            config['pie_domain_y'] = [
                st.slider("Domaine pie min", 0.0, 0.5, config['pie_domain_y'][0], step=0.01, key=f"{key}_pie_domain_y_min"),
                st.slider("Domaine pie max", 0.5, 1.0, config['pie_domain_y'][1], step=0.01, key=f"{key}_pie_domain_y_max")
            ]
            config['pie_domain_x'] = [
                st.slider("Domaine pie xmin", 0.0, 0.5, config['pie_domain_x'][0], step=0.01, key=f"{key}_pie_domain_x_min"),
                st.slider("Domaine pie xmax", 0.5, 1.0, config['pie_domain_x'][1], step=0.01, key=f"{key}_pie_domain_x_max")
            ]
        with col7:
            st.markdown("**Marges manuelles (pixels)**")
            config['margin_t'] = st.number_input("Marge haute", 20, 500, config.get('margin_t', 80), step=5, key=f"{key}_margin_top")
            config['margin_b'] = st.number_input("Marge basse", 20, 500, config.get('margin_b', 80), step=5, key=f"{key}_margin_bottom")
            config['margin_l'] = st.number_input("Marge gauche", 20, 500, config.get('margin_l', 80), step=5, key=f"{key}_margin_left")
            config['margin_r'] = st.number_input("Marge droite", 20, 500, config.get('margin_r', 80), step=5, key=f"{key}_margin_right")

        st.markdown("#### Titres des axes (décalage)")
        col_ax1, col_ax2 = st.columns(2)
        with col_ax1:
            config['xaxis_title_standoff'] = st.number_input("Décalage titre X (px)", 0, 100, config.get('xaxis_title_standoff', 20), step=5, key=f"{key}_xaxis_title_standoff")
        with col_ax2:
            config['yaxis_title_standoff'] = st.number_input("Décalage titre Y (px)", 0, 100, config.get('yaxis_title_standoff', 25), step=5, key=f"{key}_yaxis_title_standoff")

        st.markdown("#### Personnalisation des titres")
        config['title_text'] = st.text_input("Titre principal", value=config.get('title_text', ''), key=f"{key}_title_text")
        config['xaxis_title_text'] = st.text_input("Titre axe X", value=config.get('xaxis_title_text', ''), key=f"{key}_xaxis_title_text")
        config['yaxis_title_text'] = st.text_input("Titre axe Y", value=config.get('yaxis_title_text', ''), key=f"{key}_yaxis_title_text")
        if config['title_text'] or config['xaxis_title_text'] or config['yaxis_title_text']:
            st.caption("Laissez un champ vide pour conserver le titre d'origine.")

        st.markdown("#### Note (caption)")
        config['show_caption'] = st.checkbox("Afficher la note", value=config['show_caption'], key=f"{key}_show_caption")
        if config['show_caption']:
            st.caption(f"*Note : {caption}*")
            col_cap1, col_cap2 = st.columns(2)
            with col_cap1:
                config['caption_x'] = st.slider("Position horizontale (0–1)", 0.0, 1.0, config.get('caption_x', 0.02), step=0.01, key=f"{key}_caption_x")
            with col_cap2:
                config['caption_y'] = st.slider("Position verticale (sous le graphique)", -0.5, 0.0, config.get('caption_y', -0.22), step=0.01, key=f"{key}_caption_y")

        st.markdown("#### Axe X – Angle des étiquettes")
        config['x_tick_angle'] = st.slider(
            "Angle des étiquettes (°)",
            -90, 90, config.get('x_tick_angle', -15),
            step=5, key=f"{key}_x_tick_angle"
        )

        st.markdown("#### Légende et étiquettes des barres")
        col_leg1, col_leg2 = st.columns(2)
        with col_leg1:
            config['show_legend'] = st.checkbox("Afficher la légende", value=config.get('show_legend', True), key=f"{key}_show_legend")
            if config['show_legend']:
                config['legend_x'] = st.slider("Position légende X", 0.0, 1.0, config.get('legend_x', 1.0), step=0.01, key=f"{key}_legend_x")
                config['legend_y'] = st.slider("Position légende Y", 0.0, 1.0, config.get('legend_y', 0.5), step=0.01, key=f"{key}_legend_y")
        with col_leg2:
            config['show_bar_text'] = st.checkbox("Afficher les étiquettes sur les barres", value=config.get('show_bar_text', True), key=f"{key}_show_bar_text")

        st.markdown("#### Retour à la ligne (facteurs)")
        col8, col9, col10 = st.columns(3)
        with col8:
            config['wrap_title_max_chars_factor'] = st.slider("Titre", 0.2, 1.0, config['wrap_title_max_chars_factor'], key=f"{key}_wrap_title")
        with col9:
            config['wrap_axis_label_max_chars_factor'] = st.slider("Étiquettes axes", 0.1, 0.8, config['wrap_axis_label_max_chars_factor'], key=f"{key}_wrap_axis")
        with col10:
            config['wrap_legend_max_chars_factor'] = st.slider("Légende", 0.1, 0.8, config['wrap_legend_max_chars_factor'], key=f"{key}_wrap_legend")

        # Bouton de génération PNG
        if st.button("📥 Générer le PNG avec ces réglages", key=f"{key}_generate"):
            DPI = 300
            export_width_px = int(round(config['export_width_cm'] / 2.54 * DPI))
            export_height_px = int(round(config['export_height_cm'] / 2.54 * DPI))

            fig_export = copy.deepcopy(fig)
            fig_export = prepare_figure_for_export(
                fig_export,
                config=config,
                caption=caption if config['show_caption'] else None,
                export_width=export_width_px,
                export_height=export_height_px,
                dpi=DPI
            )
            img_bytes = fig_export.to_image(format="png", width=export_width_px, height=export_height_px, scale=1)

            img = Image.open(io.BytesIO(img_bytes))
            buf = io.BytesIO()
            img.save(buf, format='PNG', dpi=(DPI, DPI))
            buf.seek(0)

            st.download_button(
                label="📥 Télécharger le PNG",
                data=buf,
                file_name=f"graph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                mime="image/png",
                key=f"{key}_download"
            )

def normalize_reason(reason):
    """
    Normalise une raison de choix de marque en regroupant les variantes.
    - 'emballage' et 'conditionnement' -> 'Emballage'
    """
    if not isinstance(reason, str):
        return reason
    r = reason.strip().lower()
    # Fusionner emballage et conditionnement
    if r in ['emballage', 'conditionnement', 'conditionnement/emballage']:
        return 'Emballage'
    return reason.strip()