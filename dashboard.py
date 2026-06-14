# dashboard.py – Tableau de bord complet enrichi
import os
import sys
import streamlit as st
import pandas as pd
import sqlite3
import matplotlib.font_manager as fm
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

# --- Template personnalisé pour les exports (police Gilroy, tailles lisibles) ---
pio.templates["gilroy_export"] = go.layout.Template(
    layout=dict(
        font=dict(family="Gilroy, sans-serif", size=14, color="black"),
        title=dict(font=dict(family="Gilroy, sans-serif", size=22, color="black")),
        legend=dict(font=dict(family="Gilroy, sans-serif", size=13, color="black")),
        xaxis=dict(
            title=dict(font=dict(family="Gilroy, sans-serif", size=18, color="black")),
            tickfont=dict(family="Gilroy, sans-serif", size=15, color="black"),
            gridcolor="lightgrey",
            zerolinecolor="black"
        ),
        yaxis=dict(
            title=dict(font=dict(family="Gilroy, sans-serif", size=18, color="black")),
            tickfont=dict(family="Gilroy, sans-serif", size=15, color="black"),
            gridcolor="lightgrey",
            zerolinecolor="black"
        ),
        annotationdefaults=dict(font=dict(color="black")),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
)
pio.templates.default = "gilroy_export"

def force_black_axes(fig, title_size=18, tick_size=15):
    """
    Applique une police noire et des tailles explicites à tous les axes,
    aux légendes, annotations et titres d'une figure Plotly.
    """
    # Titre général
    if fig.layout.title:
        fig.layout.title.font.color = "black"
        fig.layout.title.font.size = 22
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
    return fig

import json
import re
from datetime import datetime, time, timedelta, date
import subprocess
import uuid
import hashlib
import numpy as np
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium, folium_static
from difflib import SequenceMatcher
import unicodedata
from math import radians, cos, sin, asin, sqrt
from plotly.subplots import make_subplots
import branca

st.set_page_config(page_title="Dashboard Huile de Palme", layout="wide")
st.title("📊 Étude de marché – Huile de palme rouge à Kinshasa")

# ============================================================
# Constantes et chemins
# ============================================================
DB_PATH = "consolidated.db"
PEAK_CONFIG_FILE = "peak_hours_config.json"
STATE_FILE = "planning_state.json"
MAG_POS_FILE = "magasin_positions.json"
K_OVERRIDE_FILE = "k_overrides.json"
BRAND_MAP_FILE = "brand_mapping.json"
COMMUNE_NIVEAU_FILE = "commune_niveau.json"

# ============================================================
# Validation dynamique des anomalies (paramétrable)
# ============================================================

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
# Fonctions utilitaires
# ============================================================

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

def fmt_nombre(val, decimals=0):
    """Formate un nombre générique avec séparateur d'espaces et décimale optionnelle."""
    if pd.isna(val) or val is None:
        return ""
    if decimals == 0:
        return f"{int(round(float(val))):,}".replace(",", " ")
    else:
        return f"{float(val):,.{decimals}f}".replace(",", " ")


def get_official_brands():
    """Retourne l'ensemble des marques officielles : supermarchés.csv + cibles du mapping."""
    base = set()
    if not df_prices_ext.empty:
        base = set(normalize_brand(b) for b in df_prices_ext['marque'].unique())
    mapping = load_brand_mapping()
    targets = set(v for v in mapping.values() if v)
    return base | targets

def apply_brand_mapping_strict(series):
    """
    Applique le mapping et ne conserve que les marques officielles.
    Retourne une Series avec la marque officielle ou None si inconnue.
    """
    official = get_official_brands()
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
    Les autres sont normalisées mais conservées telles quelles (pas de 'Autre').
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

def load_commune_niveau():
    if os.path.exists(COMMUNE_NIVEAU_FILE):
        with open(COMMUNE_NIVEAU_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    default = {
        "gombe": "Aisé",
        "ngaliema": "Aisé",
        "limete": "Aisé",
        "lingwala": "Moyen",
        "kalamu": "Moyen",
        "barumbu": "Moyen",
        "kinshasa": "Moyen",
        "bandalungwa": "Moyen",
        "ngiri-ngiri": "Moyen",
        "kasa-vubu": "Moyen",
        "lemba": "Moyen",
        "matete": "Populaire",
        "ndjili": "Populaire",
        "masina": "Populaire",
        "kimbanseke": "Populaire",
        "mont-ngafula": "Populaire",
        "selembao": "Populaire",
        "maluku": "Populaire",
        "nsele": "Populaire"
    }
    return default

def save_commune_niveau(mapping):
    with open(COMMUNE_NIVEAU_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

commune_niveau = load_commune_niveau()

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

# ============================================================
# Chargement des données de collecte
# ============================================================
@st.cache_data(ttl=300)
def load_db_internal():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "Fichier 'consolidated.db' introuvable. Exécutez d'abord process_daily.py."
    try:
        conn = sqlite3.connect(DB_PATH)
        df_q = pd.read_sql("SELECT * FROM questionnaires", conn)
        df_c = pd.read_sql("SELECT * FROM countings", conn)
        df_p = pd.read_sql("SELECT * FROM prices", conn)
        conn.close()
    except sqlite3.Error as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), f"Erreur de lecture de la base : {e}"
    for df in [df_q, df_c, df_p]:
        if 'data' in df.columns:
            df['data_dict'] = df['data'].apply(lambda x: json.loads(x) if isinstance(x, str) else {})
        if 'anomalies' in df.columns:
            df['anomalies_list'] = df['anomalies'].apply(lambda x: json.loads(x) if isinstance(x, str) else [])
    if 'statut' not in df_q.columns:
        df_q['statut'] = 'Accepté'
    return df_q, df_c, df_p, None

def load_db():
    df_q, df_c, df_p, err = load_db_internal()
    if err:
        st.error(err)
    return df_q, df_c, df_p

# ============================================================
# Chargement des supermarchés
# ============================================================
@st.cache_data
def load_supermarches_internal():
    encodings = ['utf-8-sig', 'latin1', 'cp1252']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv("supermarches.csv", encoding=enc, skip_blank_lines=False)
            break
        except Exception:
            continue
    if df is None:
        return pd.DataFrame(), pd.DataFrame(), "Fichier supermarches.csv illisible."

    def clean_column_name(name):
        if not isinstance(name, str):
            name = str(name)
        name = name.replace('�%', '%').replace('�', '%')
        name = name.replace('\xa0', ' ')
        name = name.strip()
        if ' - ' in name:
            parts = name.split(' - ')
            name = parts[0].strip() + ' - ' + parts[1].strip()
        return name

    df.columns = [clean_column_name(c) for c in df.columns]

    nom_col = None
    if 'Nom du supermarché' in df.columns:
        nom_col = 'Nom du supermarché'
    else:
        for c in df.columns:
            if 'nom' in c.lower() and 'supermarche' in c.lower():
                nom_col = c
                break
    if not nom_col:
        return pd.DataFrame(), pd.DataFrame(), "Colonne 'Nom du supermarché' introuvable."

    socio_col = next((c for c in df.columns if 'socio' in c.lower() or 'niveau' in c.lower()), None)
    price_cols = [c for c in df.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]

    def to_float(val):
        if pd.isna(val) or val == '':
            return 0.0
        s = str(val)
        s = s.replace('\xa0', '').replace(' ', '').replace(',', '.')
        match = re.search(r'(\d+(?:\.\d+)?)', s)
        if match:
            try:
                return float(match.group(1))
            except:
                return 0.0
        return 0.0

    data_id = {
        'Nom': df[nom_col].astype(str).str.strip(),
        'Chaine': df['Chaine'].astype(str).str.strip() if 'Chaine' in df.columns else '',
        'Secteur': df['Secteur'].astype(str).str.strip() if 'Secteur' in df.columns else '',
        'Niveau_socio': df[socio_col].astype(str).str.strip() if socio_col else '',
        'Taille': df['Taille'].astype(str).str.strip() if 'Taille' in df.columns else '',
        'ouv_sem': df['Horaire d’ouverture semaine'].astype(str).str.strip() if 'Horaire d’ouverture semaine' in df.columns else '',
        'ferm_sem': df['Horaire de fermeture semaine'].astype(str).str.strip() if 'Horaire de fermeture semaine' in df.columns else '',
        'ouv_we': df['Horaire d’ouverture weekend'].astype(str).str.strip() if 'Horaire d’ouverture weekend' in df.columns else '',
        'ferm_we': df['Horaire de fermeture weekend'].astype(str).str.strip() if 'Horaire de fermeture weekend' in df.columns else '',
    }
    df_id = pd.DataFrame(data_id)

    df_prices = df[price_cols].copy()
    for c in price_cols:
        df_prices[c] = df_prices[c].apply(to_float)

    out = pd.concat([df_id, df_prices], axis=1)
    out = out[out['Nom'].notna() & (out['Nom'] != '')]

    rows_prices = []
    for _, row in out.iterrows():
        supermarche = row['Nom']
        for c in price_cols:
            prix = row[c]
            if prix > 0:
                parts = c.split(' - ')
                if len(parts) >= 2:
                    marque = parts[0].strip()
                    conditionnement = parts[1].strip()
                    rows_prices.append({
                        'supermarche': supermarche,
                        'marque': marque,
                        'conditionnement': conditionnement,
                        'prix': prix
                    })
    df_prices_ext = pd.DataFrame(rows_prices)
    return out, df_prices_ext, f"{len(out)} supermarchés chargés, {len(df_prices_ext)} prix externes trouvés."

def load_supermarches():
    out, df_prices_ext, msg = load_supermarches_internal()
    if "illisible" in msg or "introuvable" in msg:
        st.error(msg)
    elif msg:
        st.success(msg)
    return out, df_prices_ext

# ============================================================
# Chargement des données d'affluence
# ============================================================
@st.cache_data(ttl=3600)
def load_frequentation_data():
    if not os.path.exists("fréquentation.csv"):
        st.warning("Fichier 'fréquentation.csv' introuvable.")
        return pd.DataFrame(), pd.DataFrame()

    encodings = ['utf-8', 'latin1', 'cp1252']
    df_raw = None
    for enc in encodings:
        try:
            df_raw = pd.read_csv("fréquentation.csv", encoding=enc)
            break
        except:
            continue
    if df_raw is None:
        st.error("Impossible de lire 'fréquentation.csv'")
        return pd.DataFrame(), pd.DataFrame()

    if 'title' in df_raw.columns:
        mag_col = 'title'
    else:
        possible = [c for c in df_raw.columns if 'title' in c.lower() or 'nom' in c.lower()]
        mag_col = possible[0] if possible else df_raw.columns[0]

    occ_cols = [c for c in df_raw.columns if c.endswith('occupancyPercent')]
    hour_cols = [c for c in df_raw.columns if c.endswith('/hour')]

    if not occ_cols or not hour_cols:
        st.error("Colonnes occupancyPercent/hour manquantes.")
        return pd.DataFrame(), pd.DataFrame()

    occ_to_hour = {}
    for occ in occ_cols:
        hour_candidate = occ.replace('occupancyPercent', 'hour')
        if hour_candidate in hour_cols:
            occ_to_hour[occ] = hour_candidate

    records = []
    for idx, row in df_raw.iterrows():
        magasin = row[mag_col]
        for occ_col, hour_col in occ_to_hour.items():
            heure_val = row.get(hour_col)
            occ_val = row.get(occ_col)
            if pd.notna(heure_val) and pd.notna(occ_val):
                try:
                    heure = int(float(heure_val))
                    occ = float(occ_val)
                    parts = occ_col.split('/')
                    if len(parts) >= 3:
                        jour = parts[1]
                        records.append({
                            'magasin': magasin,
                            'jour': jour,
                            'heure': heure,
                            'occupancy': occ
                        })
                except:
                    pass
    if not records:
        return pd.DataFrame(), pd.DataFrame()

    df_long = pd.DataFrame(records)
    df_long['key'] = df_long['jour'] + '_' + df_long['heure'].astype(str)
    pivot = df_long.pivot_table(index='magasin', columns='key', values='occupancy', fill_value=0)
    pivot = pivot.reset_index()

    jours = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
    for jour in jours:
        for h in range(24):
            col_name = f"{jour}_{h}"
            if col_name not in pivot.columns:
                pivot[col_name] = 0

    other_cols = [c for c in pivot.columns if c != 'magasin']
    other_cols.sort()
    pivot = pivot[['magasin'] + other_cols]
    return pivot, df_long

# ============================================================
# Fonctions pour la méthode A
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def cached_compute_k_factors(magasin, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping):
    """
    Version cachable du calcul des facteurs k pour un magasin.
    """
    comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
    if comptages.empty:
        return None, None, []
    
    k_sem_list, k_we_list, details = [], [], []
    jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}
    
    def get_effective_profile_local(mag, jour_code):
        nom_google = magasin_mapping.get(mag)
        if nom_google and nom_google in df_profils_pivot['magasin'].values:
            row = df_profils_pivot[df_profils_pivot['magasin'] == nom_google].iloc[0]
            profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            if max(profil) > 0:
                return profil, "Google"
        secteur = df_sm[df_sm['Nom'] == mag]['Secteur'].values
        if len(secteur) > 0 and secteur_profiles is not None:
            secteur = secteur[0]
            if secteur in secteur_profiles['secteur'].values:
                row_sect = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
                return profil, f"Secteur {secteur}"
        return [1.0]*24, "Uniforme"
    
    for _, row in comptages.iterrows():
        date_obj = row['date_dt']
        jour_code = date_obj.strftime('%a')
        jour_google = jour_map.get(jour_code, jour_code)
        profil, source = get_effective_profile_local(magasin, jour_google)
        debut, fin = row['debut_dt'], row['fin_dt']
        duree = (fin - debut).total_seconds() / 3600.0
        if duree <= 0:
            continue
        start_min = debut.hour * 60 + debut.minute
        end_min = fin.hour * 60 + fin.minute
        current = start_min
        G_moy = 0.0
        while current < end_min:
            h = current // 60
            nxt = min((h+1)*60, end_min)
            frac = (nxt - current) / 60.0
            G_moy += profil[h] * frac
            current = nxt
        G_moy = G_moy / duree if duree > 0 else 0
        if G_moy <= 0:
            continue
        flux_reel = row['total'] / duree
        k = flux_reel / G_moy
        is_we = date_obj.weekday() >= 5
        (k_we_list if is_we else k_sem_list).append(k)
        details.append({
            'date': date_obj.strftime('%Y-%m-%d'),
            'type': 'weekend' if is_we else 'semaine',
            'k': k,
            'source': source,
            'debut': debut.strftime('%H:%M'),
            'fin': fin.strftime('%H:%M'),
            'duree_h': duree,
            'total': row['total'],
            'flux_reel': flux_reel,
            'G_moy': G_moy,
            'debut_dt': debut,
            'fin_dt': fin
        })
    k_sem = np.median(k_sem_list) if k_sem_list else None
    k_we  = np.median(k_we_list) if k_we_list else None
    if k_sem is None and k_we is not None:
        k_sem = k_we
    if k_we is None and k_sem is not None:
        k_we = k_sem
    return k_sem, k_we, details

def load_k_overrides():
    if os.path.exists(K_OVERRIDE_FILE):
        with open(K_OVERRIDE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_k_overrides(overrides):
    with open(K_OVERRIDE_FILE, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2)

def get_opening_hours(row_sm, jour_type):
    """Retourne une liste de booléens indiquant si le magasin est ouvert pour chaque heure (0‑23)."""
    if jour_type == 'semaine':
        ouverture = str(row_sm.get('ouv_sem', '08:00')).strip()
        fermeture = str(row_sm.get('ferm_sem', '18:00')).strip()
    else:
        ouverture = str(row_sm.get('ouv_we', '08:00')).strip()
        fermeture = str(row_sm.get('ferm_we', '18:00')).strip()

    def parse_horaire(h_str):
        """Accepte '08:00', '8:00', '07H', '7H', '23H', etc. Retourne (h, m)."""
        h_str = h_str.upper().replace('H', ':00').replace(' ', '')
        try:
            t = datetime.strptime(h_str, '%H:%M')
            return t.hour, t.minute
        except:
            return 8, 0

    h_ouv, m_ouv = parse_horaire(ouverture)
    h_ferm, m_ferm = parse_horaire(fermeture)

    ouvert = [False] * 24
    for h in range(24):
        if h > h_ouv and h < h_ferm:
            ouvert[h] = True
        elif h == h_ouv and m_ouv == 0:
            ouvert[h] = True
        elif h == h_ferm and m_ferm == 0:
            ouvert[h] = False
        elif h == h_ouv and m_ouv > 0:
            ouvert[h] = True
        elif h == h_ferm and m_ferm > 0:
            ouvert[h] = True
    return ouvert

def get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles):
    if not df_profils_pivot.empty and magasin in df_profils_pivot['magasin'].values:
        row = df_profils_pivot[df_profils_pivot['magasin'] == magasin].iloc[0]
        profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
        if max(profil) > 0:
            return profil, "Google direct"
    if magasin in df_sm['Nom'].values:
        secteur = df_sm[df_sm['Nom'] == magasin]['Secteur'].values[0]
        if df_secteur_profiles is not None and secteur in df_secteur_profiles['secteur'].values:
            row_sect = df_secteur_profiles[df_secteur_profiles['secteur'] == secteur].iloc[0]
            profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            return profil, f"Secteur {secteur} (médian)"
    return [1.0]*24, "Aucun profil"

def compute_k_factors(magasin, df_c_f, df_sm, df_profils_pivot, df_secteur_profiles):
    comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
    if comptages.empty:
        return None, None, {}

    k_sem_list = []
    k_we_list = []
    details = []
    for idx, row in comptages.iterrows():
        date_obj = row['date_dt']
        is_weekend = date_obj.weekday() >= 5
        jour_type = 'weekend' if is_weekend else 'semaine'
        jour_code = date_obj.strftime('%a')
        profil, source = get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles)

        debut = row['debut_dt']
        fin = row['fin_dt']
        duree = (fin - debut).total_seconds() / 3600.0
        if duree <= 0:
            continue

        start_min = debut.hour * 60 + debut.minute
        end_min = fin.hour * 60 + fin.minute
        current = start_min
        G_moy = 0.0
        while current < end_min:
            h = current // 60
            next_min = min((h+1)*60, end_min)
            frac = (next_min - current) / 60.0
            G_moy += profil[h] * frac
            current = next_min
        G_moy = G_moy / duree if duree > 0 else 0

        if G_moy <= 0:
            continue

        flux_reel = row['total'] / duree
        k = flux_reel / G_moy

        if jour_type == 'semaine':
            k_sem_list.append(k)
        else:
            k_we_list.append(k)
        details.append({'date': date_obj.strftime('%Y-%m-%d'), 'type': jour_type, 'k': k, 'source': source})

    k_sem = np.median(k_sem_list) if k_sem_list else None
    k_we = np.median(k_we_list) if k_we_list else None
    if k_sem is None and k_we is not None:
        k_sem = k_we
    if k_we is None and k_sem is not None:
        k_we = k_sem

    cv_sem = np.std(k_sem_list)/np.mean(k_sem_list) if len(k_sem_list)>1 else 0
    cv_we = np.std(k_we_list)/np.mean(k_we_list) if len(k_we_list)>1 else 0
    anomalies = {'k_sem_list': k_sem_list, 'k_we_list': k_we_list, 'cv_sem': cv_sem, 'cv_we': cv_we, 'details': details}
    return k_sem, k_we, anomalies

def estimate_daily_flow(magasin, jour_code, k_sem, k_we, df_sm, df_profils_pivot, df_secteur_profiles):
    is_weekend = jour_code in ['Sa', 'Su']
    k = k_we if is_weekend else k_sem
    if k is None:
        return [0]*24, 0, "k non disponible"

    profil, source = get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles)

    sm_row = df_sm[df_sm['Nom'] == magasin]
    if sm_row.empty:
        ouvert = [True]*24
    else:
        ouvert = get_opening_hours(sm_row.iloc[0], 'semaine' if not is_weekend else 'weekend')

    clients_par_heure = []
    for h in range(24):
        if ouvert[h]:
            clients = int(round(k * profil[h]))
        else:
            clients = 0
        clients_par_heure.append(clients)
    total = sum(clients_par_heure)
    return clients_par_heure, total, source

# ============================================================
# Chargement effectif des données
# ============================================================
df_q, df_c, df_p = load_db()
df_sm, df_prices_ext = load_supermarches()

# Normalisation supermarchés
if not df_sm.empty:
    df_sm = df_sm.copy()
    df_sm['nom_norm'] = df_sm['Nom'].apply(normalize_name)

# Normalisation lieux questionnaires
if not df_q.empty:
    df_q['lieu_norm'] = df_q['lieu'].apply(normalize_name)
    if not df_sm.empty:
        mapping_lieu = dict(zip(df_sm['nom_norm'], df_sm['Nom']))
        df_q['magasin_officiel'] = df_q['lieu_norm'].map(mapping_lieu).fillna(df_q['lieu'])
    else:
        df_q['magasin_officiel'] = df_q['lieu']
else:
    df_q = pd.DataFrame(columns=['type', 'lieu', 'magasin_officiel', 'date', 'enqueteur'])

# Sauvegarde du DataFrame AVANT filtrage par magasin
df_q_avant_filtrage = df_q.copy()

# ============================================================
# Normalisation des lieux de comptage (création systématique de lieu_officiel)
# ============================================================
if not df_c.empty:
    df_c['lieu_norm'] = df_c['lieu'].apply(normalize_name)
    if not df_sm.empty:
        sm_norm = dict(zip(df_sm['nom_norm'], df_sm['Nom']))
        df_c['lieu_officiel'] = df_c['lieu_norm'].map(sm_norm).fillna(df_c['lieu'])
    else:
        df_c['lieu_officiel'] = df_c['lieu']

# Filtrage magasins sélectionnés (corrigé)
selected_mags = st.session_state.get('selected_magasins', [])
df_q_raw = df_q.copy() if not df_q.empty else df_q

if selected_mags:
    # Fonction de nettoyage : supprime " → commune"
    def clean_mag_name(name):
        if isinstance(name, str) and ' → ' in name:
            return name.split(' → ')[0].strip()
        return name

    selected_norm = {normalize_name(m): m for m in selected_mags}
    if not df_q.empty and 'magasin_officiel' in df_q.columns:
        corrections_file = "store_mapping_corrections.json"
        manual_corrections = {}
        if os.path.exists(corrections_file):
            with open(corrections_file, 'r', encoding='utf-8') as f:
                manual_corrections = json.load(f)

        magasin_mapping = {}
        all_officiel = df_q['magasin_officiel'].dropna().unique()
        for officiel in all_officiel:
            cleaned_officiel = clean_mag_name(officiel)
            if cleaned_officiel in selected_mags:
                magasin_mapping[officiel] = cleaned_officiel
            elif officiel in manual_corrections:
                corrected = manual_corrections[officiel]
                if corrected is not None and corrected in selected_mags:
                    magasin_mapping[officiel] = corrected
            else:
                norm_off = normalize_name(cleaned_officiel)
                if norm_off in selected_norm:
                    magasin_mapping[officiel] = selected_norm[norm_off]
                else:
                    magasin_mapping[officiel] = None
        mask_sm = df_q['type'].isin(['supermarche', 'supermarche_menage'])
        keep_sm = df_q['magasin_officiel'].isin(set(magasin_mapping.keys()))
        df_q = df_q[~mask_sm | keep_sm]

    # Filtrage des comptages (inchangé, mais on peut appliquer le même nettoyage si besoin)
    if not df_c.empty and 'lieu' in df_c.columns:
        df_c['lieu_norm'] = df_c['lieu'].apply(normalize_name)
        if not df_sm.empty:
            sm_norm = dict(zip(df_sm['nom_norm'], df_sm['Nom']))
            df_c['lieu_officiel'] = df_c['lieu_norm'].map(sm_norm).fillna(df_c['lieu'])
        else:
            df_c['lieu_officiel'] = df_c['lieu']
        df_c = df_c[df_c['lieu_officiel'].isin(selected_mags)]

    if not df_p.empty and 'supermarche' in df_p.columns:
        prix_mapping = {}
        all_sm = df_p['supermarche'].dropna().unique()
        for sm in all_sm:
            if sm in selected_mags:
                prix_mapping[sm] = sm
            else:
                norm_sm = normalize_name(sm)
                best_score = 0
                best_match = None
                for norm_sel, sel_orig in selected_norm.items():
                    score = SequenceMatcher(None, norm_sm, norm_sel).ratio()
                    if score > best_score and score >= 0.8:
                        best_score = score
                        best_match = sel_orig
                if best_match:
                    prix_mapping[sm] = best_match
        df_p = df_p[df_p['supermarche'].isin(set(prix_mapping.keys()))]

# ============================================================
# Construction du datetime complet (date + heure) pour df_q et df_q_raw
# ============================================================
if not df_q.empty:
    heure_col = next((c for c in df_q.columns if c.lower() == 'heure'), None)
    if heure_col:
        df_q['date_dt'] = pd.to_datetime(
            df_q['date'].astype(str) + ' ' + df_q[heure_col].astype(str),
            errors='coerce'
        )
    else:
        df_q['date_dt'] = pd.to_datetime(df_q['date'])
else:
    pass

if not df_q_raw.empty:
    heure_col_raw = next((c for c in df_q_raw.columns if c.lower() == 'heure'), None)
    if heure_col_raw:
        df_q_raw['date_dt'] = pd.to_datetime(
            df_q_raw['date'].astype(str) + ' ' + df_q_raw[heure_col_raw].astype(str),
            errors='coerce'
        )

# ============================================================
# Barre latérale : filtres temporels et enquêteur
# ============================================================
st.sidebar.header("🔎 Filtres")

# Calcul de la période couverte avant le widget
dates_all = []
if not df_q.empty and 'date_dt' in df_q.columns:
    dates_all.extend(df_q['date_dt'].dropna().tolist())
if not df_c.empty and 'date_dt' in df_c.columns:
    dates_all.extend(df_c['date_dt'].dropna().tolist())
if not df_p.empty and 'date_dt' in df_p.columns:
    dates_all.extend(df_p['date_dt'].dropna().tolist())

if dates_all:
    min_date = pd.Timestamp(min(dates_all)).date()
    max_date = pd.Timestamp(max(dates_all)).date()
else:
    min_date = datetime.today().date()
    max_date = datetime.today().date()

date_range = st.sidebar.date_input(
    "Période", (min_date, max_date),
    min_value=min_date, max_value=max_date,
    key="sidebar_date_range"
)
enqueteurs = sorted(df_q['enqueteur'].unique()) if not df_q.empty else []
selected_enqueteur = st.sidebar.selectbox(
    "Enquêteur", ["Tous"] + enqueteurs,
    key="sidebar_enqueteur"
)

# Application filtres date + enquêteur sur df_q filtré
if not df_q.empty:
    mask_q = (df_q['date_dt'].dt.date >= date_range[0]) & (df_q['date_dt'].dt.date <= date_range[1])
    if selected_enqueteur != "Tous":
        mask_q &= (df_q['enqueteur'] == selected_enqueteur)
    df_q_f = df_q[mask_q].copy()
else:
    df_q_f = pd.DataFrame()

# DataFrame brut non filtré par magasin (pour affichage questionnaires non traités)
if not df_q_raw.empty:
    df_q_raw['date_dt'] = pd.to_datetime(df_q_raw['date'])
    mask_raw = (df_q_raw['date_dt'].dt.date >= date_range[0]) & (df_q_raw['date_dt'].dt.date <= date_range[1])
    if selected_enqueteur != "Tous":
        mask_raw &= (df_q_raw['enqueteur'] == selected_enqueteur)
    df_q_f_raw = df_q_raw[mask_raw].copy()
else:
    df_q_f_raw = pd.DataFrame()

# Comptages avec dates filtrées
if not df_c.empty:
    df_c['date_dt'] = pd.to_datetime(df_c['date'])
    mask_c = (df_c['date_dt'].dt.date >= date_range[0]) & (df_c['date_dt'].dt.date <= date_range[1])
    df_c_f = df_c[mask_c].copy()
    df_c_f['debut'] = df_c_f['debut'].astype(str).str.strip()
    df_c_f['fin'] = df_c_f['fin'].astype(str).str.strip()
    df_c_f = df_c_f[(df_c_f['debut'] != '') & (df_c_f['fin'] != '') &
                    (df_c_f['debut'] != 'nan') & (df_c_f['fin'] != 'nan')]
    if not df_c_f.empty:
        df_c_f['debut_dt'] = pd.to_datetime(df_c_f['date_dt'].astype(str) + ' ' + df_c_f['debut'],
                                            format='%Y-%m-%d %H:%M:%S', errors='coerce')
        df_c_f['fin_dt'] = pd.to_datetime(df_c_f['date_dt'].astype(str) + ' ' + df_c_f['fin'],
                                          format='%Y-%m-%d %H:%M:%S', errors='coerce')
        df_c_f = df_c_f.dropna(subset=['debut_dt', 'fin_dt'])
        if not df_c_f.empty:
            df_c_f['duree_h'] = (df_c_f['fin_dt'] - df_c_f['debut_dt']).dt.total_seconds() / 3600.0
else:
    df_c_f = pd.DataFrame()

# Prix filtrés par date
if not df_p.empty:
    df_p['date_dt'] = pd.to_datetime(df_p['date'])
    mask_p = (df_p['date_dt'].dt.date >= date_range[0]) & (df_p['date_dt'].dt.date <= date_range[1])
    df_p_f = df_p[mask_p].copy()
else:
    df_p_f = pd.DataFrame()

# ============================================================
# Construction du DataFrame unifié pour l'export des questionnaires
# ============================================================
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

# Création du DataFrame unifié (utilisé uniquement pour l'export)
if not df_q_f.empty:
    df_q_export = build_unified_questionnaire_df(df_q_f)
else:
    df_q_export = pd.DataFrame()


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

if not df_q_f.empty:
    df_supermarche = df_q_f[df_q_f['type'] == 'supermarche'].copy()
    df_menage = df_q_f[df_q_f['type'].isin(['menage', 'supermarche_menage'])].copy()

    if not df_supermarche.empty:
        def extract_supermarche_fields(row):
            d = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
            vol_texte = d.get('Q4_Quantité', '')
            vol_litres = extraire_litres(vol_texte) if vol_texte else None
            prix_num = pd.to_numeric(d.get('Q5_PrixPayé', '').replace(',', '.'), errors='coerce')
            return {
                'Q1': d.get('Q1_Achat'),
                'Q2': d.get('Q2_Marque'),
                'Q3': d.get('Q3_Raison'),
                'Q4': d.get('Q4_Quantité'),
                'Q5': d.get('Q5_PrixPayé'),
                'Q6': d.get('Q6_Fréquence'),
                'Q7': d.get('Q7_NbPersonnes'),
                'Q8': d.get('Q8_LieuxAchat'),
                'Q9': d.get('Q9_PretPayerPlus'),
                'Q10': d.get('Q10_PrixMax'),
                'Q11': d.get('Q11_ReconnaitreQualite'),
                'RC_Conn': d.get('Q_RC_Connaissance'),
                'RC_Qual': d.get('Q_RC_Qualités'),
                'SexeAge': d.get('Q12_SexeAge'),
                'vol_litres': vol_litres,
                'prix_num': prix_num,
                'prix_litre': prix_num / vol_litres if vol_litres and vol_litres > 0 else None,
                'prix_max_num': pd.to_numeric(d.get('Q10_PrixMax', '').replace(',', '.'), errors='coerce'),
                'criteres_consentement': parse_criteres_smart(d.get('Q9_PretPayerPlus', ''))
            }
        
        df_supermarche['_fields'] = df_supermarche.apply(extract_supermarche_fields, axis=1)
        for col in ['Q1','Q2','Q3','Q4','Q5','Q6','Q7','Q8','Q9','Q10','Q11','RC_Conn','RC_Qual','SexeAge',
                    'vol_litres','prix_num','prix_litre','prix_max_num','criteres_consentement']:
            df_supermarche[col] = df_supermarche['_fields'].apply(lambda x: x[col])
        df_supermarche.drop(columns=['_fields'], inplace=True)

        # --- Ajouter la colonne marque_clean ---
        df_supermarche['marque_clean'] = apply_brand_mapping_strict(df_supermarche['Q2'])

        # Sauvegarde de la version complète (sans filtre marque)
        df_supermarche_full = df_supermarche.copy()

        # Suppression des lignes dont la marque n'est pas officielle (pour les graphiques de marques)
        df_supermarche = df_supermarche[df_supermarche['marque_clean'].notna()]

    if not df_menage.empty:
        def extract_menage_fields(row):
            d = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
            nb = d.get('Q4_Quantite_Nombre')
            vol_unit_str = d.get('Q4_Quantite_VolumeUnitaire')
            vol_unit = pd.to_numeric(vol_unit_str.replace(',', '.'), errors='coerce') if vol_unit_str else None
            nb_int = pd.to_numeric(nb, errors='coerce') if nb else None
            if nb_int and vol_unit and nb_int > 0:
                vol_total = nb_int * vol_unit
            else:
                vol_total = None
            prix_num = pd.to_numeric(d.get('Q5_PrixHabituel', '').replace(',', '.'), errors='coerce')
            prix_litre = prix_num / vol_total if vol_total and vol_total > 0 else None
            return {
                'Q1_nb': d.get('Q1_NbPersonnes'),
                'Q2': d.get('Q2_Achat'),
                'Q3': d.get('Q3_Frequence'),
                'Q4_nb': nb,
                'Q4_cont': d.get('Q4_Quantite_Contenant'),
                'Q4_vol_unit': vol_unit_str,
                'Q5': d.get('Q5_PrixHabituel'),
                'Q6': d.get('Q6_Pourcentages'),
                'Q7': d.get('Q7_MarquePreferee'),
                'Q8': d.get('Q8_PretPayerPlus'),
                'Q9': d.get('Q9_PrixMax'),
                'RC_Conn': d.get('Q_RC_Connaissance'),
                'RC_Qual': d.get('Q_RC_Qualités'),
                'SexeAgeClasse': d.get('Q10_SexeAgeClasse'),
                'qualite': d.get('Q_Qualite'),
                'volume_total': vol_total,
                'prix_num': prix_num,
                'prix_litre': prix_litre,
                'prix_max_num': pd.to_numeric(d.get('Q9_PrixMax', '').replace(',', '.'), errors='coerce'),
                'criteres': parse_criteres_smart(d.get('Q8_PretPayerPlus', ''))
            }
        
        df_menage['_fields'] = df_menage.apply(extract_menage_fields, axis=1)
        for col in ['Q1_nb','Q2','Q3','Q4_nb','Q4_cont','Q4_vol_unit','Q5','Q6','Q7','Q8','Q9',
                    'RC_Conn','RC_Qual','SexeAgeClasse','qualite','volume_total','prix_num','prix_litre',
                    'prix_max_num','criteres']:
            df_menage[col] = df_menage['_fields'].apply(lambda x: x[col])
        df_menage.drop(columns=['_fields'], inplace=True)

        # --- Nouvelle gestion des marques (stricte) ---
        if 'marques_brutes_menage' not in st.session_state:
            st.session_state.marques_brutes_menage = set()
        st.session_state.marques_brutes_menage.update(
            df_menage['Q7'].apply(lambda x: normalize_brand(x.replace('Autre:', '')) if isinstance(x, str) else None).dropna()
        )
        df_menage['marque_clean'] = apply_brand_mapping_strict(df_menage['Q7'])
        df_menage = df_menage[df_menage['marque_clean'].notna()]

        df_menage['criteres'] = df_menage['Q8'].apply(parse_criteres_smart)

        def extract_pct_supermarche(pourcent_str):
            if not isinstance(pourcent_str, str):
                return 0.0
            match = re.search(r'Supermarché.*?(\d+(?:\.\d+)?)\s*%', pourcent_str, re.IGNORECASE)
            if match:
                return float(match.group(1))
            return 0.0
        df_menage['pct_supermarche'] = df_menage['Q6'].apply(extract_pct_supermarche)

        freq_map = {
            'Plusieurs fois par semaine': 4,
            'Une fois par semaine': 4,
            'Deux à trois fois par mois': 2.5,
            'Une fois par mois': 1,
            'Moins souvent': 0.5
        }
        df_menage['freq_num'] = df_menage['Q3'].map(freq_map).fillna(0)
        df_menage['achats_mois'] = df_menage['freq_num']
        df_menage['conso_menage_an'] = df_menage['volume_total'] * df_menage['achats_mois'] * 12
        df_menage['taille_menage'] = pd.to_numeric(df_menage['Q1_nb'], errors='coerce').fillna(1)
        df_menage['conso_indiv_an'] = df_menage['conso_menage_an'] / df_menage['taille_menage']
else:
    df_supermarche = pd.DataFrame()
    df_supermarche_full = pd.DataFrame()
    df_menage = pd.DataFrame()

# DataFrame brut des supermarchés non filtrés par magasin (pour affichage questionnaires exclus)
if not df_q_f_raw.empty:
    df_supermarche_raw = df_q_f_raw[df_q_f_raw['type'] == 'supermarche'].copy()
    if not df_supermarche_raw.empty:
        df_supermarche_raw['magasin_officiel_raw'] = df_supermarche_raw['magasin_officiel']
        df_supermarche_raw['date_raw'] = df_supermarche_raw['date']
        df_supermarche_raw['enqueteur_raw'] = df_supermarche_raw['enqueteur']
else:
    df_supermarche_raw = pd.DataFrame()

# Chargement données affluence
df_profils_pivot, df_profils_long = load_frequentation_data()
secteur_profiles = None
if not df_profils_pivot.empty and not df_sm.empty:
    df_profils_pivot['magasin_norm'] = df_profils_pivot['magasin'].apply(normalize_name)
    df_sm['nom_norm'] = df_sm['Nom'].apply(normalize_name)
    merged = df_profils_pivot.merge(df_sm[['nom_norm', 'Secteur']], left_on='magasin_norm', right_on='nom_norm', how='left')
    secteur_profiles_list = []
    for secteur in merged['Secteur'].dropna().unique():
        sub = merged[merged['Secteur'] == secteur]
        cols = [c for c in sub.columns if c not in ['magasin', 'magasin_norm', 'Secteur', 'nom_norm']]
        median_row = {'secteur': secteur}
        for c in cols:
            median_row[c] = sub[c].median()
        secteur_profiles_list.append(median_row)
    if secteur_profiles_list:
        secteur_profiles = pd.DataFrame(secteur_profiles_list)

# ============================================================
# Barre latérale : suppression, traitement, heures de pointe
# ============================================================
st.sidebar.markdown("---")
st.sidebar.header("🗑️ Effacement des données de collecte")
if st.sidebar.button("Effacer les données de collecte"):
    st.session_state['confirm_delete'] = True
if st.session_state.get('confirm_delete', False):
    st.sidebar.warning("⚠️ Êtes-vous sûr ?")
    col1, col2 = st.sidebar.columns(2)
    if col1.button("Oui"):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM questionnaires")
            conn.execute("DELETE FROM countings")
            conn.execute("DELETE FROM prices")
            conn.commit()
            conn.close()
            load_db_internal.clear()
            st.sidebar.success("Données effacées. Rechargez la page.")
            st.session_state['confirm_delete'] = False
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Erreur : {e}")
    if col2.button("Non"):
        st.session_state['confirm_delete'] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Traitement des données")
if st.sidebar.button("🔄 Traiter les fichiers CSV"):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_daily.py")
    try:
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            st.sidebar.success("Traitement terminé. Rechargez la page.")
            load_db_internal.clear()
            st.rerun()
        else:
            st.sidebar.error(f"Erreur : {result.stderr}")
    except Exception as e:
        st.sidebar.error(f"Impossible d'exécuter le script : {e}")

# ============================================================
# Paramètres globaux : devise et taux de change
# ============================================================
st.sidebar.markdown("---")
st.sidebar.header("💱 Devise et taux de change")
devise_globale = st.sidebar.radio("Devise d'affichage", ['FC', 'USD'], index=0, key="devise_globale")
taux_change = st.sidebar.number_input("Taux de change (FC pour 1 USD)", value=2800, step=100, key="taux_change")

def convertir_prix(montant_fc, devise=None, taux=None):
    """Convertit un montant en FC vers la devise souhaitée (par défaut, utilise les paramètres globaux)."""
    if devise is None:
        devise = st.session_state.get("devise_globale", "FC")
    if taux is None:
        taux = st.session_state.get("taux_change", 2800)
    if devise == "FC":
        return montant_fc
    else:
        return montant_fc / taux

def prix_formatte(montant_fc, devise=None, taux=None):
    """Retourne une chaîne formatée avec la devise."""
    val = convertir_prix(montant_fc, devise, taux)
    if devise is None:
        devise = st.session_state.get("devise_globale", "FC")
    symbol = "FC" if devise == "FC" else "$"
    return f"{val:,.2f} {symbol}"


# ============================================================
# Onglets
# ============================================================
tabs = st.tabs([
    "📋 Accueil & Avancement",
    "👤 Enquêteur",
    "🛒 Supermarché",
    "🏠 Ménages",
    "🚶 Comptages & Flux",
    "📊 Estimation du marché",
    "🏷️ Prix & Concurrence",
    "🏪 Profil supermarchés",
    "⚠️ Anomalies",
    "🗺️ Carte des données",
    "📊 Affluence",
    "📤 Exportation"
])

# ------------------------------------------------------------
# ONGLET 0 : ACCUEIL (corrigé – test figure supprimé, tout en noir)
# ------------------------------------------------------------
with tabs[0]:
    current_hash = get_sm_hash()
    if 'sm_hash' not in st.session_state:
        st.session_state.sm_hash = current_hash
        saved_equipes, saved_selected = load_planning_state()
        st.session_state.selected_magasins = saved_selected
    elif st.session_state.sm_hash != current_hash:
        st.warning("⚠️ Le fichier supermarches.csv a été modifié.")
        existing_mags = set(df_sm['Nom'].unique())
        st.session_state.selected_magasins = [m for m in st.session_state.selected_magasins if m in existing_mags]
        st.session_state.sm_hash = current_hash
        save_planning_state([], st.session_state.selected_magasins)
        st.rerun()

    if 'selected_magasins' not in st.session_state:
        st.session_state.selected_magasins = []
    selected_mags = st.session_state.selected_magasins

    def merge_intervals(intervals):
        if not intervals:
            return [], 0
        intervals.sort(key=lambda x: x[0])
        merged = []
        current_start, current_end = intervals[0]
        for start, end in intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end
        merged.append((current_start, current_end))
        total_duration = sum(end - start for start, end in merged)
        return merged, total_duration

    def compute_coverage_stats(df_c_f, magasin):
        if df_c_f.empty:
            return "Aucun comptage", "Aucun comptage", 0.0, 0.0
        comps = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
        if comps.empty:
            return "Aucun comptage", "Aucun comptage", 0.0, 0.0
        comps['weekday'] = comps['date_dt'].dt.weekday
        comps['est_weekend'] = comps['weekday'] >= 5
        def process_group(mask):
            sub = comps[mask]
            if sub.empty:
                return "Aucun comptage", 0.0
            intervals = []
            for _, row in sub.iterrows():
                debut = row['debut_dt']
                fin = row['fin_dt']
                debut_min = debut.hour * 60 + debut.minute
                fin_min = fin.hour * 60 + fin.minute
                if fin_min < debut_min:
                    fin_min += 24 * 60
                intervals.append((debut_min, fin_min))
            merged, duree_couverte_min = merge_intervals(intervals)
            if not merged:
                return "Aucun intervalle", 0.0
            t_min = min(i[0] for i in merged)
            t_max = max(i[1] for i in merged)
            intervalle_total_min = t_max - t_min
            if intervalle_total_min <= 0:
                return "Intervalle nul", 0.0
            pct = (duree_couverte_min / intervalle_total_min) * 100
            debut_heure = f"{t_min // 60:02d}:{t_min % 60:02d}"
            fin_heure = f"{t_max // 60:02d}:{t_max % 60:02d}"
            texte = f"{debut_heure} – {fin_heure} ({pct:.1f}%)"
            heures = duree_couverte_min / 60.0
            return texte, heures
        texte_sem, heures_sem = process_group(~comps['est_weekend'])
        texte_we, heures_we = process_group(comps['est_weekend'])
        return texte_sem, texte_we, heures_sem, heures_we

    # ================================================================
    # Progression globale – Nouvelle version
    # ================================================================
    st.header("📈 Progression globale")

    if not selected_mags:
        st.info("ℹ️ Aucun magasin sélectionné.")
        heures_sem = heures_we = 0.0
        q_sm_sem = q_sm_we = 0
        q_men_total = 0
        objectif_heures_sem = objectif_heures_we = 0
        objectif_q_sm_sem = objectif_q_sm_we = 0
        objectif_men = 500
        heures_mag = {}
        q_faits = {}
    else:
        # --- Heures de comptage (semaine / week‑end) ---
        if not df_c_f.empty:
            heures_sem = df_c_f[df_c_f['date_dt'].dt.weekday < 5]['duree_h'].sum()
            heures_we  = df_c_f[df_c_f['date_dt'].dt.weekday >= 5]['duree_h'].sum()
        else:
            heures_sem = 0.0
            heures_we  = 0.0
        objectif_heures_sem = (len(selected_mags) * 8) / 2
        objectif_heures_we  = (len(selected_mags) * 8) / 2

        # --- Questionnaires supermarché (tous les 'supermarche', statut != Refus) ---
        q_sm_sem = q_sm_we = 0
        if not df_supermarche_full.empty:
            valides = df_supermarche_full[df_supermarche_full['statut'] != 'Refus']
            q_sm_sem = len(valides[valides['date_dt'].dt.weekday < 5])
            q_sm_we  = len(valides[valides['date_dt'].dt.weekday >= 5])
        objectif_q_sm_sem = (len(selected_mags) * 100) / 2
        objectif_q_sm_we  = (len(selected_mags) * 100) / 2

        # --- Questionnaires ménages purs (type 'menage') ---
        q_men_total = 0
        if not df_q_f.empty:
            df_men_purs = df_q_f[df_q_f['type'] == 'menage']
            if not df_men_purs.empty:
                if 'statut' in df_men_purs.columns:
                    q_men_total = len(df_men_purs[df_men_purs['statut'] != 'Refus'])
                else:
                    q_men_total = len(df_men_purs)
        objectif_men = 500

        # --- Heures totales par magasin pour le tableau de détail (somme simple) ---
        heures_mag = {}
        for mag in selected_mags:
            sessions_mag = df_c_f[df_c_f['lieu_officiel'] == mag] if not df_c_f.empty else pd.DataFrame()
            if not sessions_mag.empty:
                h_sem = sessions_mag[sessions_mag['date_dt'].dt.weekday < 5]['duree_h'].sum()
                h_we  = sessions_mag[sessions_mag['date_dt'].dt.weekday >= 5]['duree_h'].sum()
            else:
                h_sem = 0.0
                h_we  = 0.0
            heures_mag[mag] = (h_sem, h_we)

        # --- Questionnaires supermarché par magasin (pour le tableau de détail) ---
        q_faits = {}
        for mag in selected_mags:
            if not df_supermarche_full.empty:
                df_mag = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
                valides = df_mag[df_mag['statut'] != 'Refus'] if 'statut' in df_mag.columns else df_mag
                q_faits[mag] = len(valides)
            else:
                q_faits[mag] = 0

    # ================================================================
    # Affichage des métriques de progression
    # ================================================================
    st.subheader("Progression en semaine")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        ratio_hsem = min(1.0, heures_sem / objectif_heures_sem) if objectif_heures_sem > 0 else 0
        st.metric("Heures comptage semaine", f"{heures_sem:.1f} / {objectif_heures_sem:.0f}")
        st.progress(ratio_hsem)
    with col_s2:
        ratio_sm_sem = min(1.0, q_sm_sem / objectif_q_sm_sem) if objectif_q_sm_sem > 0 else 0
        st.metric("Questionnaires supermarché semaine", f"{q_sm_sem} / {objectif_q_sm_sem:.0f}")
        st.progress(ratio_sm_sem)

    st.subheader("Progression le week‑end")
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        ratio_hwe = min(1.0, heures_we / objectif_heures_we) if objectif_heures_we > 0 else 0
        st.metric("Heures comptage week‑end", f"{heures_we:.1f} / {objectif_heures_we:.0f}")
        st.progress(ratio_hwe)
    with col_w2:
        ratio_sm_we = min(1.0, q_sm_we / objectif_q_sm_we) if objectif_q_sm_we > 0 else 0
        st.metric("Questionnaires supermarché week‑end", f"{q_sm_we} / {objectif_q_sm_we:.0f}")
        st.progress(ratio_sm_we)

    st.subheader("Progression ménages")
    col_m1, col_m2, col_m3 = st.columns([1, 1, 1])
    with col_m1:
        ratio_men = min(1.0, q_men_total / objectif_men) if objectif_men > 0 else 0
        st.metric("Questionnaires ménages (purs)", f"{q_men_total} / {objectif_men}")
        st.progress(ratio_men)

    # ================================================================
    # Tableau de détail par magasin
    # ================================================================
    if selected_mags:
        rows_avancement = []
        for mag in selected_mags:
            h_sem, h_we = heures_mag.get(mag, (0.0, 0.0))
            q = q_faits.get(mag, 0)
            pct_heures = ((h_sem + h_we) / 8) * 100 if (h_sem + h_we) > 0 else 0
            pct_q = (q / 100) * 100 if q > 0 else 0
            mag_info = df_sm[df_sm['Nom'] == mag]
            if not mag_info.empty:
                secteur = mag_info.iloc[0]['Secteur']
                taille  = mag_info.iloc[0].get('Taille', '')
                niveau  = mag_info.iloc[0].get('Niveau_socio', '')
            else:
                secteur, taille, niveau = '', '', ''
            rows_avancement.append({
                'Magasin': mag,
                'Secteur': secteur,
                'Taille': taille,
                'Niveau socio-économique': niveau,
                'Heures semaine': f"{h_sem:.1f}",
                'Heures week‑end': f"{h_we:.1f}",
                'Questionnaires': f"{q} / 100",
                'Progression comptage (%)': f"{pct_heures:.1f}%",
                'Progression questionnaire (%)': f"{pct_q:.1f}%"
            })
        df_avancement = pd.DataFrame(rows_avancement)
        st.subheader("📋 Détail par magasin")
        st.dataframe(df_avancement, use_container_width=True)
    else:
        st.info("ℹ️ Aucun magasin sélectionné.")

    st.divider()
    st.header("🛒 Sélection des magasins (avec huile)")
    if df_sm.empty:
        st.warning("Aucun supermarché chargé.")
        st.stop()
    price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
    df_avec_huile = df_sm[(df_sm[price_cols] > 0).any(axis=1) if price_cols else False].copy()
    if df_avec_huile.empty:
        st.warning("Aucun supermarché ne vend d'huile.")
        st.stop()
    df_avec_huile['Taille'] = df_avec_huile['Taille'].fillna("Non renseigné")
    df_avec_huile['Niveau_socio'] = df_avec_huile['Niveau_socio'].fillna("Non renseigné")
    df_avec_huile['Strate'] = df_avec_huile['Taille'] + ' / ' + df_avec_huile['Niveau_socio']
    strates = sorted(df_avec_huile['Strate'].unique())
    total_magasins = len(df_avec_huile)
    nb_selected = len(selected_mags)
    pct_selected = (nb_selected / total_magasins * 100) if total_magasins > 0 else 0
    col_a1, col_a2, col_a3 = st.columns(3)
    col_a1.metric("Total supermarchés (huile)", total_magasins)
    col_a2.metric("Sélectionnés", nb_selected)
    col_a3.metric("Pourcentage", f"{pct_selected:.1f}%")
    new_selection = []
    for strate in strates:
        mags_strate = df_avec_huile[df_avec_huile['Strate'] == strate]
        options = sorted(mags_strate['Nom'].tolist())
        default_vals = [m for m in selected_mags if m in options]
        selected = st.multiselect(f"{strate} ({len(options)} magasins)", options=options, default=default_vals, key=f"sel_{strate}")
        new_selection.extend(selected)
    if set(new_selection) != set(selected_mags):
        st.session_state.selected_magasins = new_selection
        save_planning_state([], st.session_state.selected_magasins)
        st.rerun()

# ------------------------------------------------------------
# ONGLET 1 : ENQUÊTEUR
# ------------------------------------------------------------
with tabs[1]:
    st.header("👤 Statistiques par enquêteur")

    # ------------------------------------------------------------
    # Préparation des données filtrées (date, enquêteur, etc.)
    # ------------------------------------------------------------
    if not df_q.empty:
        mask_date_q = (pd.to_datetime(df_q['date_dt']).dt.date >= date_range[0]) & (pd.to_datetime(df_q['date_dt']).dt.date <= date_range[1])
        df_q_ni = df_q[mask_date_q].copy()
    else:
        df_q_ni = pd.DataFrame()

    if not df_c.empty:
        mask_date_c = (df_c['date_dt'].dt.date >= date_range[0]) & (df_c['date_dt'].dt.date <= date_range[1])
        df_c_ni = df_c[mask_date_c].copy()
        df_c_ni['debut'] = df_c_ni['debut'].astype(str).str.strip()
        df_c_ni['fin'] = df_c_ni['fin'].astype(str).str.strip()
        df_c_ni = df_c_ni[(df_c_ni['debut'] != '') & (df_c_ni['fin'] != '') &
                          (df_c_ni['debut'] != 'nan') & (df_c_ni['fin'] != 'nan')]
        if not df_c_ni.empty:
            df_c_ni['debut_dt'] = pd.to_datetime(df_c_ni['date_dt'].astype(str) + ' ' + df_c_ni['debut'],
                                                 format='%Y-%m-%d %H:%M:%S', errors='coerce')
            df_c_ni['fin_dt'] = pd.to_datetime(df_c_ni['date_dt'].astype(str) + ' ' + df_c_ni['fin'],
                                               format='%Y-%m-%d %H:%M:%S', errors='coerce')
            df_c_ni = df_c_ni.dropna(subset=['debut_dt', 'fin_dt'])
            df_c_ni['duree_h'] = (df_c_ni['fin_dt'] - df_c_ni['debut_dt']).dt.total_seconds() / 3600.0
        else:
            df_c_ni = pd.DataFrame()
    else:
        df_c_ni = pd.DataFrame()

    if not df_p.empty:
        mask_date_p = (df_p['date_dt'].dt.date >= date_range[0]) & (df_p['date_dt'].dt.date <= date_range[1])
        df_p_ni = df_p[mask_date_p].copy()
    else:
        df_p_ni = pd.DataFrame()

    # ------------------------------------------------------------
    # Normalisation des noms d'enquêteurs
    # ------------------------------------------------------------
    noms = set()
    if not df_q_ni.empty:
        noms.update(df_q_ni['enqueteur'].dropna().unique())
    if not df_c_ni.empty:
        noms.update(df_c_ni['enqueteur'].dropna().unique())
    if not df_p_ni.empty:
        noms.update(df_p_ni['enqueteur'].dropna().unique())
    noms_list = list(noms)

    def group_similar_names(names, threshold=0.85):
        if not names:
            return {}
        def clean(s):
            s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
            return re.sub(r'\s+', ' ', s.strip().lower())
        cleaned = [clean(n) for n in names]
        sorted_names = sorted(cleaned)
        clusters = []
        for name in sorted_names:
            found = False
            for cluster in clusters:
                if any(name in existing or existing in name for existing in cluster):
                    cluster.append(name)
                    found = True
                    break
                if any(SequenceMatcher(None, name, existing).ratio() >= threshold for existing in cluster):
                    cluster.append(name)
                    found = True
                    break
            if not found:
                clusters.append([name])
        original_to_clean = dict(zip(names, cleaned))
        mapping = {}
        for cluster in clusters:
            orig_names = [n for n, c in original_to_clean.items() if c in cluster]
            canonical = max(orig_names, key=len)
            for name in orig_names:
                mapping[name] = canonical
        return mapping

    name_mapping = group_similar_names(noms_list)

    if not df_q_ni.empty:
        df_q_ni['enqueteur_canon'] = df_q_ni['enqueteur'].map(name_mapping)
    if not df_c_ni.empty:
        df_c_ni['enqueteur_canon'] = df_c_ni['enqueteur'].map(name_mapping)
    if not df_p_ni.empty:
        df_p_ni['enqueteur_canon'] = df_p_ni['enqueteur'].map(name_mapping)

    tous_canoniques = sorted(set(name_mapping.values()))

    # ------------------------------------------------------------
    # Fonction de calcul des statistiques par enquêteur
    # ------------------------------------------------------------
    def compute_stats(enq_canon):
        q_sm_all = df_q_ni[(df_q_ni['enqueteur_canon'] == enq_canon) &
                           (df_q_ni['type'].isin(['supermarche', 'supermarche_menage']))].copy()
        q_sm_pure = df_q_ni[(df_q_ni['enqueteur_canon'] == enq_canon) &
                            (df_q_ni['type'] == 'supermarche')].copy()
        if not q_sm_pure.empty:
            q_sm_pure['statut_norm'] = q_sm_pure['statut'].apply(
                lambda x: unicodedata.normalize('NFKD', str(x))
                            .encode('ASCII', 'ignore')
                            .decode('utf-8')
                            .strip()
                            .lower()
            )
            refus = q_sm_pure['statut_norm'].isin(['refus', 'refuse']).sum()
            total_sm = len(q_sm_pure)
            q_sm_accept = q_sm_pure[~q_sm_pure['statut_norm'].isin(['refus', 'refuse'])]
        else:
            refus = 0
            total_sm = 0
            q_sm_accept = pd.DataFrame()
        c_grp = df_c_ni[(df_c_ni['enqueteur_canon'] == enq_canon) & (df_c_ni['duree_h'] > 5/60)]
        heures_comptage = c_grp['duree_h'].sum() if not c_grp.empty else 0.0
        nb_q_sans_refus = len(q_sm_accept)
        q1_oui = 0
        if nb_q_sans_refus > 0:
            q1_oui = q_sm_accept['data_dict'].apply(
                lambda d: d.get('Q1_Achat', '') == 'Oui' if isinstance(d, dict) else False
            ).sum()
        pct_acheteur = (q1_oui / nb_q_sans_refus * 100) if nb_q_sans_refus > 0 else 0.0
        pct_refus = (refus / total_sm * 100) if total_sm > 0 else 0.0
        timestamps = []
        if not q_sm_all.empty:
            timestamps.extend(q_sm_all['date_dt'].tolist())
        q_menage = df_q_ni[(df_q_ni['enqueteur_canon'] == enq_canon) & (df_q_ni['type'] == 'menage')]
        if not q_menage.empty:
            timestamps.extend(q_menage['date_dt'].tolist())
        c_all = df_c_ni[df_c_ni['enqueteur_canon'] == enq_canon]
        if not c_all.empty:
            timestamps.extend(c_all['debut_dt'].tolist())
            timestamps.extend(c_all['fin_dt'].tolist())
        timestamps = [ts for ts in timestamps if pd.notna(ts)]
        travail = 0.0
        if timestamps:
            df_times = pd.DataFrame({'ts': timestamps})
            df_times['jour'] = df_times['ts'].dt.date
            for jour, grp in df_times.groupby('jour'):
                span = (grp['ts'].max() - grp['ts'].min()).total_seconds() / 3600.0
                travail += span
        nb_accept = len(q_sm_accept)
        temps_quest = (nb_accept * 2 + refus * 0.5) / 60.0
        temps_estime_total = heures_comptage + temps_quest
        return {
            'nb_q_total': total_sm,
            'nb_q_sans_refus': nb_q_sans_refus,
            'nb_q1_oui': q1_oui,
            'pct_acheteur': pct_acheteur,
            'heures_comptage': heures_comptage,
            'pct_refus': pct_refus,
            'travail': travail,
            'temps_estime_total': temps_estime_total
        }

    # ------------------------------------------------------------
    # Paramètres de détection des anomalies
    # ------------------------------------------------------------
    st.subheader("⚙️ Paramètres de détection des anomalies")
    settings = load_anomaly_settings()
    col1, col2 = st.columns(2)
    with col1:
        new_intervalle = st.number_input("Intervalle min entre questionnaires (secondes)", min_value=0, value=settings['intervalle_min_secondes'], step=5)
        new_refus = st.number_input("Intervalle min après Refus (secondes)", min_value=0, value=settings['refus_min_secondes'], step=1)
        new_dist_q = st.number_input("Distance GPS max pour supermarché (mètres)", min_value=0, value=settings['distance_gps_questionnaire_m'], step=10)
        new_dist_c = st.number_input("Distance GPS max pour comptage (mètres)", min_value=0, value=settings['distance_gps_comptage_m'], step=10)
        new_prix_min_l = st.number_input("Prix/L min (FC/L)", min_value=0, value=settings['prix_litre_min_fc'], step=100)
        new_prix_max_l = st.number_input("Prix/L max (FC/L)", min_value=0, value=settings['prix_litre_max_fc'], step=500)
    with col2:
        new_vol_max = st.number_input("Volume max par achat (litres)", min_value=0, value=settings['volume_max_litres'], step=1)
        new_taux = st.number_input("Taux de sortie max (/h)", min_value=0, value=settings['taux_sortie_max_par_heure'], step=10)
        new_duree_max = st.number_input("Durée max comptage (heures)", min_value=0, value=settings['duree_max_heures'], step=1)
        new_prix_min = st.number_input("Prix min absolu (FC)", min_value=0, value=settings['prix_min_fc'], step=10)
        new_prix_max = st.number_input("Prix max absolu (FC)", min_value=0, value=settings['prix_max_fc'], step=1000)
        new_duree_min_c = st.number_input("Durée minimale comptage (minutes)", min_value=0, value=settings['duree_min_comptage_minutes'], step=5)
        new_total_min = st.number_input("Total minimal comptage", min_value=0, value=settings['total_min_comptage'], step=1)

    if st.button("💾 Appliquer les paramètres et recalculer les anomalies"):
        new_settings = {
            "intervalle_min_secondes": new_intervalle,
            "refus_min_secondes": new_refus,
            "distance_gps_questionnaire_m": new_dist_q,
            "distance_gps_comptage_m": new_dist_c,
            "prix_litre_min_fc": new_prix_min_l,
            "prix_litre_max_fc": new_prix_max_l,
            "volume_max_litres": new_vol_max,
            "taux_sortie_max_par_heure": new_taux,
            "duree_max_heures": new_duree_max,
            "prix_min_fc": new_prix_min,
            "prix_max_fc": new_prix_max,
            "duree_min_comptage_minutes": new_duree_min_c,
            "total_min_comptage": new_total_min
        }
        save_anomaly_settings(new_settings)
        
        st.rerun()

    # ------------------------------------------------------------
    # Calcul des anomalies (mise en cache)
    # ------------------------------------------------------------
    @st.cache_data(ttl=3600, show_spinner="Calcul des anomalies en cours...")
    def compute_all_anomalies(df_q_full, df_c_full, df_p_full, settings, df_prices_ext, brand_map):
        all_anomalies = []
        # --- Questionnaires ---
        if not df_q_full.empty:
            q = df_q_full.copy()
            q['datetime'] = pd.to_datetime(q['date'] + ' ' + q['heure'], errors='coerce')
            q = q.dropna(subset=['datetime'])
            # 1) Validations intrinsèques
            for _, row in q.iterrows():
                rec = row['data_dict']
                qtype = row['type']
                msgs = validate_questionnaire_dynamic(rec, qtype, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'questionnaire', row['date'], row['enqueteur'], m))
            # 2) Intervalles temporels par enquêteur
            for enqueteur, grp in q.groupby('enqueteur'):
                grp_sorted = grp.sort_values('datetime')
                for i in range(len(grp_sorted) - 1):
                    prev = grp_sorted.iloc[i]
                    curr = grp_sorted.iloc[i + 1]
                    delta = (curr['datetime'] - prev['datetime']).total_seconds()
                    if delta <= 0:
                        continue
                    # Refus
                    if prev.get('statut') == 'Refus':
                        if delta < settings['refus_min_secondes']:
                            all_anomalies.append((
                                curr['uuid'], 'questionnaire', curr['date'], enqueteur,
                                f"Refus trop rapproché ({delta:.0f} s) - {curr['type']} après {prev['type']} "
                                f"(min {settings['refus_min_secondes']} s)"
                            ))
                        continue
                    curr_type = curr['type']
                    prev_type = prev['type']
                    # Exceptions
                    if curr_type == 'supermarche_menage' and prev_type == 'supermarche':
                        continue
                    if prev_type == 'supermarche_menage':
                        data_prev = prev['data_dict']
                        if data_prev.get('Q3_Achat', '').strip().lower() == 'non':
                            continue
                    if delta < settings['intervalle_min_secondes']:
                        all_anomalies.append((
                            curr['uuid'], 'questionnaire', curr['date'], enqueteur,
                            f"Intervalle trop court entre {curr_type} et {prev_type} "
                            f"({delta:.0f} s) – minimum {settings['intervalle_min_secondes']}s (UUID précédent: {prev['uuid']})"
                        ))
            # 3) GPS supermarché / supermarche_menage
            sm_q = q[q['type'].isin(['supermarche', 'supermarche_menage'])].copy()
            if not sm_q.empty:
                sm_q['lat'] = sm_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
                )
                sm_q['lon'] = sm_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
                )
                sm_q_valid = sm_q.dropna(subset=['lat', 'lon'])
                for lieu, grp_lieu in sm_q_valid.groupby('lieu'):
                    if len(grp_lieu) < 2:
                        continue
                    lat_med = grp_lieu['lat'].median()
                    lon_med = grp_lieu['lon'].median()
                    for idx, row in grp_lieu.iterrows():
                        dist_km = haversine(row['lat'], row['lon'], lat_med, lon_med)
                        seuil_km = settings['distance_gps_questionnaire_m'] / 1000.0
                        if dist_km > seuil_km:
                            all_anomalies.append((
                                row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                                f"Distance GPS > {settings['distance_gps_questionnaire_m']} m "
                                f"par rapport à la médiane de '{lieu}' ({dist_km*1000:.0f} m)"
                            ))
            # 4) GPS ménages (doublons)
            menage_q = q[q['type'] == 'menage'].copy()
            if not menage_q.empty:
                menage_q['lat'] = menage_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
                )
                menage_q['lon'] = menage_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
                )
                menage_valid = menage_q.dropna(subset=['lat', 'lon'])
                menage_valid['lat_round'] = menage_valid['lat'].round(5)
                menage_valid['lon_round'] = menage_valid['lon'].round(5)
                duplicate_groups = menage_valid.groupby(['lat_round', 'lon_round']).filter(lambda x: len(x) > 1)
                for _, row in duplicate_groups.iterrows():
                    all_anomalies.append((
                        row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                        f"Coordonnées GPS identiques à un autre ménage ({row['lat_round']}, {row['lon_round']})"
                    ))
            # 5) Marques non référencées (questionnaires vs supermarchés.csv)
            if not df_prices_ext.empty:
                mag_marques = {}
                for _, row in df_prices_ext.iterrows():
                    mag = normalize_name(row['supermarche'])
                    marque = normalize_brand(row['marque'])
                    marque = brand_map.get(marque, marque)
                    mag_marques.setdefault(mag, set()).add(marque)
                acheteurs_sm = q[(q['type'] == 'supermarche') & 
                                 (q['data_dict'].apply(lambda d: d.get('Q1_Achat', '') == 'Oui' if isinstance(d, dict) else False))]
                for _, row in acheteurs_sm.iterrows():
                    lieu = row['lieu']
                    norm_lieu = normalize_name(lieu)
                    if norm_lieu not in mag_marques:
                        continue
                    marque_brute = row['data_dict'].get('Q2_Marque', '')
                    if not marque_brute:
                        continue
                    marque_clean = normalize_brand(marque_brute.replace('Autre:', ''))
                    marque_clean = brand_map.get(marque_clean, marque_clean)
                    if marque_clean and marque_clean not in mag_marques[norm_lieu]:
                        all_anomalies.append((
                            row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                            f"Marque achetée « {marque_clean} » non référencée dans le supermarché « {lieu} »"
                        ))
        # --- Comptages ---
        if not df_c_full.empty:
            for _, row in df_c_full.iterrows():
                rec = row['data_dict']
                msgs = validate_counting_dynamic(rec, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'comptage', row['date'], row['enqueteur'], m))
            c = df_c_full.copy()
            c['lat'] = c['data_dict'].apply(
                lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
            )
            c['lon'] = c['data_dict'].apply(
                lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
            )
            c_valid = c.dropna(subset=['lat', 'lon'])
            for lieu, grp in c_valid.groupby('lieu'):
                if len(grp) < 2:
                    continue
                lat_med = grp['lat'].median()
                lon_med = grp['lon'].median()
                for _, row in grp.iterrows():
                    dist_km = haversine(row['lat'], row['lon'], lat_med, lon_med)
                    seuil_km = settings['distance_gps_comptage_m'] / 1000.0
                    if dist_km > seuil_km:
                        all_anomalies.append((
                            row['uuid'], 'comptage', row['date'], row['enqueteur'],
                            f"Distance GPS > {settings['distance_gps_comptage_m']} m "
                            f"par rapport à la médiane de '{lieu}' ({dist_km*1000:.0f} m)"
                        ))
        # --- Prix ---
        if not df_p_full.empty:
            for _, row in df_p_full.iterrows():
                rec = row['data_dict']
                msgs = validate_price_dynamic(rec, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'prix', row['date'], row['enqueteur'], m))
        return all_anomalies

    # Filtrage préalable sur la période et l'enquêteur sélectionnés
    df_q_filtre_anom = df_q if 'df_q' in dir() else pd.DataFrame()
    df_c_filtre_anom = df_c if 'df_c' in dir() else pd.DataFrame()
    df_p_filtre_anom = df_p if 'df_p' in dir() else pd.DataFrame()

    if not df_q_filtre_anom.empty and 'date_dt' in df_q_filtre_anom.columns:
        mask_q_anom = (df_q_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_q_filtre_anom['date_dt'].dt.date <= date_range[1])
        df_q_filtre_anom = df_q_filtre_anom[mask_q_anom]
        if selected_enqueteur != "Tous":
            df_q_filtre_anom = df_q_filtre_anom[df_q_filtre_anom['enqueteur'] == selected_enqueteur]

    if not df_c_filtre_anom.empty and 'date_dt' in df_c_filtre_anom.columns:
        mask_c_anom = (df_c_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_c_filtre_anom['date_dt'].dt.date <= date_range[1])
        df_c_filtre_anom = df_c_filtre_anom[mask_c_anom]

    if not df_p_filtre_anom.empty and 'date_dt' in df_p_filtre_anom.columns:
        mask_p_anom = (df_p_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_p_filtre_anom['date_dt'].dt.date <= date_range[1])
        df_p_filtre_anom = df_p_filtre_anom[mask_p_anom]

    brand_map = load_brand_mapping()
    prices_ext = df_prices_ext if 'df_prices_ext' in dir() else pd.DataFrame()

    with st.spinner("Calcul des anomalies (cette opération est mise en cache)..."):
        anomaly_records = compute_all_anomalies(df_q_filtre_anom, df_c_filtre_anom, df_p_filtre_anom, settings, prices_ext, brand_map)

    # ------------------------------------------------------------
    # Comptage des anomalies par enquêteur et par jour
    # ------------------------------------------------------------
    if anomaly_records:
        df_anom = pd.DataFrame(anomaly_records, columns=['uuid', 'type', 'date_str', 'enqueteur', 'message'])
        df_anom['message'] = df_anom['message'].str.replace('FCFA', 'FC')
        df_anom['date'] = pd.to_datetime(df_anom['date_str'].str[:10], format='%Y-%m-%d', errors='coerce').dt.date
        df_anom = df_anom.dropna(subset=['date']).reset_index(drop=True)
        # Filtrage par la période de la barre latérale
        mask_date_anom = (df_anom['date'] >= date_range[0]) & (df_anom['date'] <= date_range[1])
        df_anom_f = df_anom[mask_date_anom]
        if selected_enqueteur != "Tous":
            df_anom_f = df_anom_f[df_anom_f['enqueteur'] == selected_enqueteur]
        anom_count_enq = df_anom_f.groupby('enqueteur').size().to_dict()
    else:
        df_anom_f = pd.DataFrame()
        anom_count_enq = {}

    # ------------------------------------------------------------
    # Tableau de synthèse par enquêteur (avec anomalies intégrées)
    # ------------------------------------------------------------
    st.subheader("📊 Synthèse par enquêteur")
    lignes_global = []
    for canon in tous_canoniques:
        stats = compute_stats(canon)
        lignes_global.append({
            'Enquêteur': canon,
            'Nb questionnaires SM (total)': stats['nb_q_total'],
            'Nb Q1=Oui': stats['nb_q1_oui'],
            '% Acheteur SM': f"{stats['pct_acheteur']:.1f}%",
            'Heures comptage': f"{stats['heures_comptage']:.1f}",
            '% Refus SM': f"{stats['pct_refus']:.1f}%",
            'Anomalies': anom_count_enq.get(canon, 0),
            'Heures travail effectif': f"{stats['travail']:.1f}",
            'Temps de travail effectif (h)': f"{stats['temps_estime_total']:.1f}"
        })
    df_global = pd.DataFrame(lignes_global)
    st.dataframe(df_global, use_container_width=True)

    # ------------------------------------------------------------
    # Détail journalier pour un enquêteur sélectionné
    # ------------------------------------------------------------
    st.subheader("📅 Détail journalier")
    choix_enqueteur = st.selectbox("Choisir un enquêteur", tous_canoniques)
    if choix_enqueteur:
        q_sel = df_q_ni[df_q_ni['enqueteur_canon'] == choix_enqueteur] if not df_q_ni.empty else pd.DataFrame()
        c_sel = df_c_ni[df_c_ni['enqueteur_canon'] == choix_enqueteur] if not df_c_ni.empty else pd.DataFrame()
        dates = set()
        if not q_sel.empty:
            dates.update(q_sel['date_dt'].dt.date)
        if not c_sel.empty:
            dates.update(c_sel['date_dt'].dt.date)
        dates = sorted(dates)

        anom_count_jour = df_anom_f[df_anom_f['enqueteur'] == choix_enqueteur].groupby('date').size().to_dict() if not df_anom_f.empty else {}

        lignes_jour = []
        for jour in dates:
            q_jour = q_sel[(q_sel['type'] == 'supermarche') & (q_sel['date_dt'].dt.date == jour)].copy()
            total_sm = len(q_jour)
            if total_sm > 0:
                q_jour['statut_norm'] = q_jour['statut'].apply(
                    lambda x: unicodedata.normalize('NFKD', str(x))
                                .encode('ASCII', 'ignore')
                                .decode('utf-8')
                                .strip()
                                .lower()
                )
                refus = q_jour['statut_norm'].isin(['refus', 'refuse']).sum()
                accept = q_jour[~q_jour['statut_norm'].isin(['refus', 'refuse'])]
            else:
                refus = 0
                accept = pd.DataFrame()
            nb_accept = len(accept)
            q1_oui = accept['data_dict'].apply(
                lambda d: d.get('Q1_Achat', '') == 'Oui' if isinstance(d, dict) else False
            ).sum() if nb_accept > 0 else 0
            pct_acheteur = (q1_oui / nb_accept * 100) if nb_accept > 0 else 0.0
            pct_refus = (refus / total_sm * 100) if total_sm > 0 else 0.0
            c_all_jour = c_sel[c_sel['date_dt'].dt.date == jour]
            heures_comptage = c_all_jour[c_all_jour['duree_h'] > 5/60]['duree_h'].sum() if not c_all_jour.empty else 0.0
            timestamps = []
            q_all_jour = q_sel[q_sel['date_dt'].dt.date == jour]
            if not q_all_jour.empty:
                timestamps.extend(q_all_jour['date_dt'].tolist())
            if not c_all_jour.empty:
                timestamps.extend(c_all_jour['debut_dt'].tolist())
                timestamps.extend(c_all_jour['fin_dt'].tolist())
            timestamps = [ts for ts in timestamps if pd.notna(ts)]
            travail_jour = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0 if timestamps else 0.0
            lignes_jour.append({
                'Date': jour.strftime('%Y-%m-%d'),
                'Nb questionnaires SM (total)': total_sm,
                'Nb Q1=Oui': q1_oui,
                '% Acheteur SM': f"{pct_acheteur:.1f}%",
                'Heures comptage': f"{heures_comptage:.1f}",
                '% Refus SM': f"{pct_refus:.1f}%",
                'Anomalies': anom_count_jour.get(jour, 0),
                'Temps de présence sur le terrain (h)': f"{travail_jour:.1f}"
            })
        df_jour = pd.DataFrame(lignes_jour)
        st.dataframe(df_jour, use_container_width=True)

    # ------------------------------------------------------------
    # Interface de gestion des anomalies (suppression, exploration)
    # ------------------------------------------------------------
    st.header("⚠️ Gestion des anomalies")

    if not anomaly_records:
        st.success("✅ Aucune anomalie détectée avec les paramètres actuels.")
    else:
        st.subheader("📊 Synthèse des anomalies par jour et enquêteur")
        synth = df_anom_f.groupby(['date', 'enqueteur']).size().reset_index(name='nb_anomalies')
        synth['date'] = synth['date'].astype(str)

        event = st.dataframe(
            synth,
            on_select="rerun",
            selection_mode="multi-row",
            use_container_width=True,
            key="synth_anomalies"
        )

        if event.selection.rows:
            selected_indices = event.selection.rows
            valid_indices = [i for i in selected_indices if i < len(synth)]
            if not valid_indices:
                st.warning("Les lignes sélectionnées ne sont plus disponibles. Veuillez resélectionner.")
            else:
                pairs = [(synth.iloc[i]['date'], synth.iloc[i]['enqueteur']) for i in valid_indices]
                mask_detail = pd.Series(False, index=df_anom_f.index)
                for date_s, enq_s in pairs:
                    mask_detail |= ((df_anom_f['date'].astype(str) == date_s) & (df_anom_f['enqueteur'] == enq_s))
            df_detail = df_anom_f[mask_detail].reset_index(drop=True)

            st.subheader(f"🔍 Anomalies sélectionnées ({len(df_detail)} enregistrement(s))")

            if not df_detail.empty:
                detail_event = st.dataframe(
                    df_detail[['type', 'uuid', 'message']],
                    on_select="rerun",
                    selection_mode="multi-row",
                    use_container_width=True,
                    key=f"detail_multi_{hash(str(pairs))}"
                )

                if detail_event.selection.rows:
                    detail_indices = detail_event.selection.rows
                    st.write(f"**{len(detail_indices)} anomalie(s) cochée(s) pour suppression.**")

                    if st.button("🗑️ Supprimer les anomalies cochées", key=f"del_multi_{hash(str(pairs))}"):
                        try:
                            db_conn = sqlite3.connect(DB_PATH)
                            cur = db_conn.cursor()
                            for _, row_sel in df_detail.iloc[detail_indices].iterrows():
                                table = "questionnaires" if row_sel['type'] == 'questionnaire' else ("countings" if row_sel['type'] == 'comptage' else "prices")
                                cur.execute(f"DELETE FROM {table} WHERE uuid = ?", (row_sel['uuid'],))
                            db_conn.commit()
                            db_conn.close()
                            load_db_internal.clear()
                            compute_all_anomalies.clear()
                            cached_compute_k_factors.clear()
                            st.success(f"{len(detail_indices)} enregistrement(s) supprimé(s).")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur : {e}")
                else:
                    st.info("Cochez une ou plusieurs anomalies dans le tableau ci-dessus pour les supprimer.")
            else:
                st.info("Aucune anomalie trouvée pour la sélection.")
        else:
            st.info("Sélectionnez une ou plusieurs lignes dans le tableau de synthèse pour afficher le détail.")

# ------------------------------------------------------------
# ONGLET 2 : SUPERMARCHÉ
# ------------------------------------------------------------
with tabs[2]:
    st.header("Questionnaires Supermarché")

    if df_supermarche_full.empty:
        st.info("Aucun questionnaire supermarché trouvé pour les magasins sélectionnés.")
    else:
        # Sélecteur de magasin (basé sur la version complète)
        magasins_disponibles = sorted(df_supermarche_full['magasin_officiel'].unique())
        mag_sel = st.selectbox("Magasin", ["Tous"] + magasins_disponibles, key="mag_sm")

        # Version complète (sans filtre marque) pour les compteurs globaux
        df_show_full = df_supermarche_full.copy()
        if mag_sel != "Tous":
            df_show_full = df_show_full[df_show_full['magasin_officiel'] == mag_sel]

        # Version filtrée (marques reconnues) pour les graphiques de marques
        df_show = df_supermarche.copy() if not df_supermarche.empty else pd.DataFrame()
        if mag_sel != "Tous" and not df_show.empty:
            df_show = df_show[df_show['magasin_officiel'] == mag_sel]

        if df_show_full.empty:
            st.info("Aucune donnée pour ce magasin.")
        else:
            # Extraction démographique (appliquée à df_show_full)
            def get_sexe(x):
                if not isinstance(x, str): return None
                if 'Sexe:' in x:
                    m = re.search(r'Sexe:\s*([FH])', x)
                    return m.group(1) if m else None
                if 'F' in x.upper() and 'H' not in x.upper(): return 'F'
                if 'H' in x.upper(): return 'H'
                return None

            def get_age(x):
                if not isinstance(x, str): return None
                m = re.search(r'Âge:\s*(\d+[-+]*\d*)', x)
                if m: return m.group(1)
                m2 = re.search(r'(\d{2})', x)
                return m2.group(1) if m2 else None

            df_show_full['Sexe'] = df_show_full['SexeAge'].apply(get_sexe)
            df_show_full['Âge'] = df_show_full['SexeAge'].apply(get_age)

            def tranche_age(age_str):
                if not age_str: return 'Inconnu'
                try:
                    age = int(re.search(r'\d+', age_str).group())
                    if age < 25: return 'Moins de 25 ans'
                    elif age < 35: return '25-34 ans'
                    elif age < 50: return '35-49 ans'
                    else: return '50 ans et plus'
                except: return 'Inconnu'

            df_show_full['Tranche_age'] = df_show_full['Âge'].apply(tranche_age)

            # Filtre par sexe/âge (pour les acheteurs)
            def filter_df(data, key_suffix):
                col1, col2 = st.columns(2)
                with col1:
                    sexe_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key=f"sexe_{key_suffix}")
                with col2:
                    age_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"],
                                           key=f"age_{key_suffix}")
                filtered = data.copy()
                if sexe_sel != "Tous": filtered = filtered[filtered['Sexe'] == sexe_sel]
                if age_sel != "Tous": filtered = filtered[filtered['Tranche_age'] == age_sel]
                return filtered, sexe_sel, age_sel

            # Acheteurs globaux (sur la version complète)
            acheteurs_global_full = df_show_full[df_show_full['Q1'] == 'Oui'].copy()

            # Consentement (inchangé)
            def is_willing_to_pay_more(crit_list):
                if not crit_list: return False
                for crit in crit_list:
                    crit_lower = crit.strip().lower()
                    if any(phrase in crit_lower for phrase in ['non', 'pas prêt', 'ne suis pas prêt', 'aucun']):
                        return False
                return True

            acheteurs_global_full['criteres_consentement'] = acheteurs_global_full['criteres_consentement'].apply(
                lambda x: x if isinstance(x, list) else [])
            acheteurs_global_full['pret_plus'] = acheteurs_global_full['criteres_consentement'].apply(is_willing_to_pay_more)

            # ----- 1. SYNTHÈSE GÉNÉRALE -----
            col1, col2, col3, col4 = st.columns(4)

            # Exclure les refus pour le calcul du taux d'achat (et pour toutes les métriques qui suivent)
            if 'statut' in df_show_full.columns:
                df_show_valides = df_show_full[df_show_full['statut'] != 'Refus']
            else:
                df_show_valides = df_show_full

            acheteurs_global_full = df_show_valides[df_show_valides['Q1'] == 'Oui'].copy()
            taux_achat = len(acheteurs_global_full) / len(df_show_valides) * 100 if len(df_show_valides) > 0 else 0
            col1.metric("Taux d'achat", f"{taux_achat:.1f}%")
            vol_moy = acheteurs_global_full['vol_litres'].mean() if not acheteurs_global_full.empty else 0
            col2.metric("Vol. moyen (L)", f"{fmt_volume(vol_moy,2)} L")
            prix_moy = acheteurs_global_full['prix_litre'].mean() if not acheteurs_global_full.empty else 0
            col3.metric("Prix/L", fmt_prix(prix_moy, st.session_state.get("devise_globale", "FC")))
            col4.metric("Acheteurs", len(acheteurs_global_full))

            # ----- 2. TABLEAU PAR SEGMENT -----
            st.subheader("📊 Synthèse par segment de magasin (taille × niveau socio-économique)")
            if not df_sm.empty and not df_supermarche_full.empty:
                df_sm_seg = df_sm[['Nom', 'Taille', 'Niveau_socio']].copy()
                df_sm_seg['nom_norm'] = df_sm_seg['Nom'].apply(normalize_name)
                df_q_seg = df_supermarche_full.copy()
                df_q_seg['magasin_norm'] = df_q_seg['magasin_officiel'].apply(normalize_name)
                df_q_seg = df_q_seg.merge(df_sm_seg[['nom_norm', 'Taille', 'Niveau_socio']],
                                          left_on='magasin_norm', right_on='nom_norm', how='left')

                tailles = sorted(df_q_seg['Taille'].dropna().unique())
                niveaux = sorted(df_q_seg['Niveau_socio'].dropna().unique())

                rows_seg = []
                for taille in tailles:
                    for niveau in niveaux:
                        mask = (df_q_seg['Taille'] == taille) & (df_q_seg['Niveau_socio'] == niveau)
                        sub = df_q_seg[mask]
                        if sub.empty:
                            # Sauter les combinaisons sans données
                            continue
                        # Exclure les refus pour ce segment
                        if 'statut' in sub.columns:
                            sub_valides = sub[sub['statut'] != 'Refus']
                        else:
                            sub_valides = sub
                        total_q = len(sub_valides)
                        acheteurs = sub_valides[sub_valides['Q1'] == 'Oui']
                        nb_acheteurs = len(acheteurs)
                        taux_achat = (nb_acheteurs / total_q * 100) if total_q > 0 else 0
                        # Les volumes moyens et prix moyens peuvent rester basés sur acheteurs (pas de refus)
                        vol_moy = acheteurs['vol_litres'].mean() if nb_acheteurs > 0 else 0
                        prix_moy = acheteurs['prix_litre'].mean() if nb_acheteurs > 0 else 0
                        rows_seg.append({
                            'Taille': taille,
                            'Niveau socio-économique': niveau,
                            'Nb questionnaires': total_q,
                            'Taux d\'achat (%)': round(taux_achat, 1),
                            'Volume moyen (L)': fmt_volume(vol_moy, 2) + " L",
                            'Prix moyen (FC/L)': fmt_prix(prix_moy, "FC") + "/L"
                        })
                if rows_seg:
                    df_seg_sm = pd.DataFrame(rows_seg)
                    st.dataframe(df_seg_sm, use_container_width=True)

                    fig_seg_sm = px.bar(df_seg_sm[df_seg_sm['Nb questionnaires'] > 0],
                                        x='Taille', y="Taux d'achat (%)", color='Niveau socio-économique',
                                        barmode='group', title="Taux d'achat par segment")
                    fig_seg_sm.update_layout(template="gilroy_export")
                    fig_seg_sm = force_black_axes(fig_seg_sm)
                    st.plotly_chart(fig_seg_sm, use_container_width=True)
            else:
                st.info("Données insuffisantes pour la segmentation.")

            # ----- 3. MARQUES ET RAISONS D'ACHAT (basé sur df_show filtré) -----
            st.subheader("🏷️ Marques et raisons d'achat")
            # Pour les marques, on part des acheteurs complets puis on filtre sur marque connue
            acheteurs_global = df_show[df_show['Q1'] == 'Oui'].copy() if not df_show.empty else pd.DataFrame()
            acheteurs_filt, _, _ = filter_df(acheteurs_global, "marques")
            col_marq, col_rais = st.columns(2)
            with col_marq:
                if not acheteurs_filt.empty and 'marque_clean' in acheteurs_filt.columns:
                    marques = acheteurs_filt['marque_clean'].value_counts().reset_index()
                    marques.columns = ['Marque', 'Nombre']
                    fig_marq = px.pie(marques, values='Nombre', names='Marque', title="Marques achetées")
                    fig_marq.update_layout(template="gilroy_export")
                    fig_marq = force_black_axes(fig_marq)
                    st.plotly_chart(fig_marq, use_container_width=True)
                else:
                    st.info("Aucun acheteur avec marque reconnue.")
            with col_rais:
                if not acheteurs_filt.empty:
                    raisons_series = acheteurs_filt['Q3'].dropna().str.split(',').explode().str.strip()
                    raisons_counts = raisons_series.value_counts().reset_index()
                    raisons_counts.columns = ['Raison', 'Nombre']
                    if not raisons_counts.empty:
                        fig_rais = px.bar(raisons_counts, x='Raison', y='Nombre', title="Raisons de choix de la marque")
                        fig_rais.update_layout(template="gilroy_export")
                        fig_rais = force_black_axes(fig_rais)
                        st.plotly_chart(fig_rais, use_container_width=True)
                    else:
                        st.info("Aucune raison.")
                else:
                    st.info("Aucun acheteur.")

            # Croisement marque × raison
            if not acheteurs_filt.empty and 'Q3' in acheteurs_filt.columns:
                exploded = acheteurs_filt[['marque_clean', 'Q3']].dropna()
                exploded = exploded.assign(Raison=exploded['Q3'].str.split(',')).explode('Raison')
                exploded['Raison'] = exploded['Raison'].str.strip()
                exploded = exploded[exploded['Raison'] != '']
                exploded = exploded.reset_index(drop=True)
                cross = pd.crosstab(exploded['marque_clean'], exploded['Raison'])
                if not cross.empty:
                    st.subheader("🔗 Raisons par marque")
                    fig_cross = px.imshow(cross, text_auto=True, aspect="auto", title="Effectifs marque × raison")
                    fig_cross.update_layout(template="gilroy_export")
                    fig_cross = force_black_axes(fig_cross)
                    st.plotly_chart(fig_cross, use_container_width=True)

            # ----- 4. VOLUMES ACHETÉS -----
            st.subheader("📦 Volumes achetés")
            acheteurs_vol, _, _ = filter_df(acheteurs_global, "volumes")
            col_vol1, col_vol2 = st.columns(2)
            with col_vol1:
                if not acheteurs_vol.empty:
                    fig_vol_hist = px.histogram(acheteurs_vol, x='vol_litres', nbins=20,
                                                title="Distribution des volumes (litres)")
                    fig_vol_hist.update_xaxes(tickformat=",.0f")
                    fig_vol_hist.update_layout(template="gilroy_export")
                    fig_vol_hist = force_black_axes(fig_vol_hist)
                    st.plotly_chart(fig_vol_hist, use_container_width=True)
                else:
                    st.info("Aucun acheteur.")
            with col_vol2:
                if not acheteurs_vol.empty and 'marque_clean' in acheteurs_vol.columns:
                    vol_par_marque = acheteurs_vol.groupby('marque_clean')['vol_litres'].mean().reset_index()
                    vol_par_marque.columns = ['Marque', 'Volume moyen (L)']
                    fig_vol_marq = px.bar(vol_par_marque, x='Marque', y='Volume moyen (L)',
                                          title="Volume moyen par marque")
                    fig_vol_marq.update_yaxes(tickformat=",.0f")
                    fig_vol_marq.update_layout(template="gilroy_export")
                    fig_vol_marq = force_black_axes(fig_vol_marq)
                    st.plotly_chart(fig_vol_marq, use_container_width=True)
                else:
                    st.info("Aucun acheteur.")

            # ----- 5. FRÉQUENCE D'ACHAT -----
            st.subheader("📅 Fréquence d'achat")
            acheteurs_freq, _, _ = filter_df(acheteurs_global, "freq")
            if not acheteurs_freq.empty:
                def clean_q6(val):
                    if isinstance(val, str) and val.strip() != '' and val.strip().lower() not in ['nan', 'none']:
                        return val
                    return pd.NA
                acheteurs_freq['Q6_clean'] = acheteurs_freq['Q6'].apply(clean_q6)
                freq_counts = acheteurs_freq['Q6_clean'].dropna().value_counts().reset_index()
                freq_counts.columns = ['Fréquence', 'Nombre']
                if not freq_counts.empty:
                    fig_freq = px.bar(freq_counts, x='Fréquence', y='Nombre', title="Fréquence d'achat (acheteurs)")
                    fig_freq.update_layout(template="gilroy_export")
                    fig_freq = force_black_axes(fig_freq)
                    st.plotly_chart(fig_freq, use_container_width=True)
                else:
                    st.info("Aucune réponse.")
            else:
                st.info("Aucun acheteur.")

            # ----- 6. CONSENTEMENT À PAYER PLUS -----
            st.subheader("💵 Consentement à payer plus cher")

            # S'assurer que les colonnes de consentement sont présentes (même après filtrage)
            if 'pret_plus' not in acheteurs_global_full.columns:
                acheteurs_global_full['criteres_consentement'] = acheteurs_global_full['criteres_consentement'].apply(
                    lambda x: x if isinstance(x, list) else [])
                acheteurs_global_full['pret_plus'] = acheteurs_global_full['criteres_consentement'].apply(is_willing_to_pay_more)

            acheteurs_cons, _, _ = filter_df(acheteurs_global_full, "consent")
            if not acheteurs_cons.empty:
                nb_pret = acheteurs_cons['pret_plus'].sum()
                tx_pret = (nb_pret / len(acheteurs_cons) * 100) if len(acheteurs_cons) else 0
                st.metric("Prêts à payer plus", f"{tx_pret:.1f}% ({nb_pret}/{len(acheteurs_cons)} acheteurs)")

                with st.expander("🔍 Détail des réponses brutes (Q9)"):
                    reponses_brutes = acheteurs_cons['Q9'].value_counts().reset_index()
                    reponses_brutes.columns = ['Réponse originale', 'Nombre']
                    st.dataframe(reponses_brutes, use_container_width=True)

                pret_df = acheteurs_cons[acheteurs_cons['pret_plus'] == True]
                if not pret_df.empty:
                    all_criteria = pret_df['criteres_consentement'].explode()
                    all_criteria = all_criteria[~all_criteria.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    crit_counts = all_criteria.value_counts().reset_index()
                    crit_counts.columns = ['Critère', 'Nombre']
                    if not crit_counts.empty:
                        st.subheader("📋 Critères invoqués pour accepter de payer plus")
                        fig_crit = px.bar(crit_counts, x='Critère', y='Nombre')
                        fig_crit.update_layout(template="gilroy_export")
                        fig_crit = force_black_axes(fig_crit)
                        st.plotly_chart(fig_crit, use_container_width=True)
                    else:
                        st.info("Aucun critère positif.")
                else:
                    st.info("Aucun acheteur prêt à payer plus.")
            else:
                st.info("Aucun acheteur.")

            # ----- 7. ÉCART DE PRIX PAR CRITÈRE -----
            st.subheader("💰 Consentement à payer plus par critère (% d'écart de prix)")
            acheteurs_ecart, _, _ = filter_df(acheteurs_global_full, "ecart")
            if not acheteurs_ecart.empty:
                acheteurs_ecart = acheteurs_ecart.dropna(subset=['prix_num', 'prix_max_num']).copy()
                if not acheteurs_ecart.empty:
                    acheteurs_ecart['ecart_rel'] = (acheteurs_ecart['prix_max_num'] / acheteurs_ecart['prix_num'] - 1) * 100
                    pret_ecart = acheteurs_ecart[acheteurs_ecart['pret_plus'] == True]
                    if not pret_ecart.empty:
                        pret_ecart['criteres_consentement'] = pret_ecart['criteres_consentement'].apply(
                            lambda x: x if isinstance(x, list) else [])
                        exploded = pret_ecart.explode('criteres_consentement')
                        exploded = exploded[~exploded['criteres_consentement'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        ecart_par_crit = exploded.groupby('criteres_consentement')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_par_crit.columns = ['Critère', 'Écart moyen (%)', "Nombre d'acheteurs"]
                        ecart_par_crit['Écart moyen (%)'] = ecart_par_crit['Écart moyen (%)'].round(1)
                        fig_ecart_crit = px.bar(ecart_par_crit, x='Critère', y='Écart moyen (%)',
                                                text="Nombre d'acheteurs",
                                                title="Pourcentage moyen que les acheteurs sont prêts à payer en plus, par critère")
                        fig_ecart_crit.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_ecart_crit.update_layout(template="gilroy_export")
                        fig_ecart_crit = force_black_axes(fig_ecart_crit)
                        st.plotly_chart(fig_ecart_crit, use_container_width=True)

                        with st.expander("📊 Boxplot des écarts par critère"):
                            fig_box = px.box(exploded, x='criteres_consentement', y='ecart_rel',
                                             title="Distribution de l'écart de prix par critère")
                            fig_box.update_layout(template="gilroy_export")
                            fig_box = force_black_axes(fig_box)
                            st.plotly_chart(fig_box, use_container_width=True)
                    else:
                        st.info("Aucun acheteur prêt à payer plus avec données de prix valides.")
                else:
                    st.info("Pas assez de données de prix valides.")
            else:
                st.info("Aucun acheteur.")

            # ----- 8. SEGMENTATION DÉMOGRAPHIQUE -----
            st.subheader("👥 Segmentation des acheteurs")
            acheteurs_seg = acheteurs_global_full.copy()
            if not acheteurs_seg.empty:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Acheteurs par sexe**")
                    sexe_counts = acheteurs_seg['Sexe'].value_counts().reset_index()
                    sexe_counts.columns = ['Sexe', 'Nombre']
                    fig_sexe = px.bar(sexe_counts, x='Sexe', y='Nombre', color='Sexe')
                    fig_sexe.update_layout(template="gilroy_export")
                    fig_sexe = force_black_axes(fig_sexe)
                    st.plotly_chart(fig_sexe, use_container_width=True)
                with col2:
                    st.markdown("**Acheteurs par âge**")
                    age_counts = acheteurs_seg['Tranche_age'].value_counts().reset_index()
                    age_counts.columns = ["Tranche d'âge", 'Nombre']
                    fig_age = px.bar(age_counts, x="Tranche d'âge", y='Nombre', color="Tranche d'âge")
                    fig_age.update_layout(template="gilroy_export")
                    fig_age = force_black_axes(fig_age)
                    st.plotly_chart(fig_age, use_container_width=True)

                st.markdown("**Heatmap des acheteurs (Âge × Sexe)**")
                heat_data = pd.crosstab(acheteurs_seg['Tranche_age'], acheteurs_seg['Sexe'])
                if not heat_data.empty:
                    fig_heat = px.imshow(heat_data, text_auto=True, aspect="auto",
                                        title="Nombre d'acheteurs par âge et sexe")
                    fig_heat.update_layout(template="gilroy_export")
                    fig_heat = force_black_axes(fig_heat)
                    st.plotly_chart(fig_heat, use_container_width=True)

                st.markdown("**Volume acheté par âge et sexe**")
                vol_data = acheteurs_seg[['Sexe', 'Tranche_age', 'vol_litres']].dropna()
                if not vol_data.empty:
                    fig_box_age = px.box(vol_data, x='Tranche_age', y='vol_litres', color='Sexe',
                                        title="Distribution du volume acheté (L)")
                    fig_box_age.update_yaxes(tickformat=",.0f")
                    fig_box_age.update_layout(template="gilroy_export")
                    fig_box_age = force_black_axes(fig_box_age)
                    st.plotly_chart(fig_box_age, use_container_width=True)
                else:
                    st.info("Données de volume insuffisantes.")
            else:
                st.info("Aucun acheteur.")

            # ----- 9. PERCEPTION DE LA QUALITÉ & NOTORIÉTÉ -----
            st.subheader("🔍 Perception de la qualité & Notoriété de RougeCongo des clients des supermarchés")
            # Acheteurs supermarché (Q1=Oui) hors refus
            if 'statut' in df_supermarche_full.columns:
                acheteurs_sm = df_supermarche_full[(df_supermarche_full['Q1'] == 'Oui') & (df_supermarche_full['statut'] != 'Refus')].copy()
            else:
                acheteurs_sm = df_supermarche_full[df_supermarche_full['Q1'] == 'Oui'].copy()

            # Non-acheteurs réinterrogés (supermarche_menage) hors refus
            sm_menage = df_q_f[df_q_f['type'] == 'supermarche_menage'].copy()
            if 'statut' in sm_menage.columns:
                sm_menage = sm_menage[sm_menage['statut'] != 'Refus']

            if not sm_menage.empty:
                sm_menage['Q_Qualite'] = sm_menage['data_dict'].apply(lambda d: d.get('Q_Qualite') if isinstance(d, dict) else None)
                sm_menage['RC_Conn']   = sm_menage['data_dict'].apply(lambda d: d.get('Q_RC_Connaissance') if isinstance(d, dict) else None)
                sm_menage['RC_Qual']   = sm_menage['data_dict'].apply(lambda d: d.get('Q_RC_Qualités') if isinstance(d, dict) else None)
                sm_menage['SexeAgeClasse'] = sm_menage['data_dict'].apply(lambda d: d.get('Q10_SexeAgeClasse') if isinstance(d, dict) else None)

                def get_sexe_from_qsm_menage(x):
                    if not isinstance(x, str): return None
                    parts = x.split('-')
                    if len(parts) >= 1:
                        sexe = parts[0].strip().upper()
                        if sexe in ['F', 'H']: return sexe
                    return None
                def get_age_from_qsm_menage(x):
                    if not isinstance(x, str): return None
                    match = re.search(r'(\d+[-+]*\d*\s*ans?)', x)
                    if match: return match.group(1)
                    return None
                sm_menage['Sexe'] = sm_menage['SexeAgeClasse'].apply(get_sexe_from_qsm_menage)
                sm_menage['Âge'] = sm_menage['SexeAgeClasse'].apply(get_age_from_qsm_menage)
            else:
                sm_menage = pd.DataFrame(columns=['Q_Qualite', 'RC_Conn', 'RC_Qual', 'Sexe', 'Âge'])

            acheteurs_sm = acheteurs_sm.rename(columns={'Q11': 'Q_Qualite'})
            cols_to_keep = ['Q_Qualite', 'RC_Conn', 'RC_Qual', 'Sexe', 'Âge']
            for col in cols_to_keep:
                if col not in acheteurs_sm.columns: acheteurs_sm[col] = None
                if col not in sm_menage.columns: sm_menage[col] = None
            df_combined = pd.concat([acheteurs_sm[cols_to_keep], sm_menage[cols_to_keep]], ignore_index=True)

            if df_combined.empty:
                st.info("Aucune donnée disponible pour l'analyse de la perception et de la notoriété.")
            else:
                df_combined['Tranche_age'] = df_combined['Âge'].apply(tranche_age)
                col1, col2 = st.columns(2)
                with col1:
                    sexe_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key="qual_sexe")
                with col2:
                    age_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"], key="qual_age")
                df_combined_filt = df_combined.copy()
                if sexe_sel != "Tous": df_combined_filt = df_combined_filt[df_combined_filt['Sexe'] == sexe_sel]
                if age_sel != "Tous": df_combined_filt = df_combined_filt[df_combined_filt['Tranche_age'] == age_sel]

                st.caption(f"Population combinée : {len(df_combined)} répondants (acheteurs + non-acheteurs réinterrogés)")

                st.subheader("🧪 Perception de la qualité")
                if not df_combined_filt.empty and df_combined_filt['Q_Qualite'].notna().any():
                    qual_series = df_combined_filt['Q_Qualite'].dropna().astype(str).str.split(',').explode().str.strip()
                    qual_series = qual_series[qual_series != '']
                    qual_series = qual_series.apply(lambda x: x.split(':', 1)[1].strip() if x.lower().startswith('autre:') else x)
                    qual_counts = qual_series.value_counts().reset_index()
                    qual_counts.columns = ['Critère', 'Nombre']
                    fig_qual = px.bar(qual_counts, x='Critère', y='Nombre', title="Comment reconnaît-on la qualité de l'huile ?")
                    fig_qual.update_layout(template="gilroy_export")
                    fig_qual = force_black_axes(fig_qual)
                    st.plotly_chart(fig_qual, use_container_width=True)
                else:
                    st.info("Aucune réponse sur la reconnaissance de la qualité.")

                st.subheader("📣 Notoriété de RougeCongo")
                col_conn, col_qual_rc = st.columns(2)
                with col_conn:
                    if not df_combined_filt.empty and df_combined_filt['RC_Conn'].notna().any():
                        conn_counts = df_combined_filt['RC_Conn'].dropna().value_counts().reset_index()
                        conn_counts.columns = ['Réponse', 'Nombre']
                        conn_counts = conn_counts[conn_counts['Réponse'] != '']
                        fig_conn = px.bar(conn_counts, x='Réponse', y='Nombre', title="Avez-vous déjà entendu parler de RougeCongo ?")
                        fig_conn.update_layout(template="gilroy_export")
                        fig_conn = force_black_axes(fig_conn)
                        st.plotly_chart(fig_conn, use_container_width=True)
                    else:
                        st.info("Aucune donnée sur la connaissance.")
                with col_qual_rc:
                    if not df_combined_filt.empty and df_combined_filt['RC_Qual'].notna().any():
                        qual_rc_series = df_combined_filt['RC_Qual'].dropna().astype(str).str.split(',').explode().str.strip()
                        qual_rc_series = qual_rc_series[qual_rc_series != '']
                        qual_rc_series = qual_rc_series.apply(lambda x: x.split(':', 1)[1].strip() if x.lower().startswith('autre:') else x)
                        qual_rc_counts = qual_rc_series.value_counts().reset_index()
                        qual_rc_counts.columns = ['Qualité', 'Nombre']
                        fig_rc_qual = px.bar(qual_rc_counts, x='Qualité', y='Nombre', title="Quelles qualités associez-vous à RougeCongo ?")
                        fig_rc_qual.update_layout(template="gilroy_export")
                        fig_rc_qual = force_black_axes(fig_rc_qual)
                        st.plotly_chart(fig_rc_qual, use_container_width=True)
                    else:
                        st.info("Aucune réponse sur les qualités.")

            # ================================================================
            # QUESTIONNAIRES NON TRAITÉS
            # ================================================================
            st.divider()
            st.subheader("📋 Questionnaires supermarché non traités (magasins non reconnus ou exclus)")

            if not df_supermarche_raw.empty:
                uuids_inclus = set(df_supermarche_full['uuid'].values)
                df_exclus = df_supermarche_raw[~df_supermarche_raw['uuid'].isin(uuids_inclus)]
                if not df_exclus.empty:
                    st.warning(f"{len(df_exclus)} questionnaire(s) exclus car le magasin n'a pas été rapproché d'un magasin sélectionné.")
                    df_exclus_display = df_exclus[['magasin_officiel', 'date', 'enqueteur', 'uuid']].copy()
                    df_exclus_display.columns = ['Magasin relevé', 'Date', 'Enquêteur', 'UUID']
                    st.dataframe(df_exclus_display, use_container_width=True)
                else:
                    st.success("✅ Tous les questionnaires supermarché (dans la période et pour l'enquêteur sélectionné) sont inclus dans l'analyse.")
            else:
                st.info("Aucune donnée brute disponible pour comparaison.")

            # ----- 10. TÉLÉCHARGEMENT -----
            st.download_button("📥 Données brutes (CSV)", df_show_full.to_csv(index=False), "supermarche_data.csv")

# ------------------------------------------------------------
# ONGLET 3 : MÉNAGES
# ------------------------------------------------------------
with tabs[3]:
    st.header("Questionnaires Ménage")

    # ═══════════════════════════════════════════════════════
    # Construction du DataFrame unifié (sans filtre magasin)
    # ═══════════════════════════════════════════════════════
    if 'df_q_f_raw' in dir() and not df_q_f_raw.empty:
        df_source = df_q_f_raw.copy()
        df_source = df_source[df_source['type'].isin(['menage', 'supermarche', 'supermarche_menage'])]

        rows_unified = []
        for _, row in df_source.iterrows():
            qtype = row['type']
            data = row['data_dict'] if isinstance(row['data_dict'], dict) else {}

            if qtype == 'supermarche':
                achat = str(data.get('Q1_Achat', '')).strip().lower()
                if achat != 'oui':
                    continue
                cat = 'Acheteur supermarché'
            elif qtype == 'supermarche_menage':
                cat = 'Non-acheteur supermarché'
            else:
                cat = 'Ménage pur'

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
                commune = data.get('Commune')
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
                supermarche_origine = data.get("Supermarché d'origine")
                commune = data.get('Commune')
            else:  # supermarche
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
                supermarche_origine = data.get('Supermarché')
                commune = data.get('Commune')

            unified = {
                'uuid': row['uuid'],
                'date': row['date'],
                'enqueteur': row['enqueteur'],
                'categorie': cat,
                'type_original': qtype,
                'sexe_age': sexe_age,
                'nb_personnes': nb_pers,
                'achat_huile': achat_huile,
                'frequence': freq,
                'marque_preferee': marque,
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
            rows_unified.append(unified)

        df_menage_unifie = pd.DataFrame(rows_unified)

        if not df_menage_unifie.empty:
            # --- Conversion des quantités et volumes unitaires (gestion 0 -> 1, décimales) ---
            # Quantité nombre : remplacer 0 par 1
            df_menage_unifie['quantite_nombre'] = pd.to_numeric(
                df_menage_unifie['quantite_nombre'].astype(str).str.replace(',', '.'), errors='coerce')
            df_menage_unifie['quantite_nombre'] = df_menage_unifie['quantite_nombre'].replace(0, 1)

            # Volume unitaire : conversion virgule->point puis numérique, détection ml
            df_menage_unifie['volume_unitaire_l'] = pd.to_numeric(
                df_menage_unifie['volume_unitaire_l'].astype(str).str.replace(',', '.'), errors='coerce')
            seuil_ml = 50
            mask_ml = df_menage_unifie['volume_unitaire_l'] > seuil_ml
            if mask_ml.any():
                st.warning(f"🔧 {mask_ml.sum()} volumes unitaires > {seuil_ml} détectés – conversion automatique en litres (÷1000).")
                df_menage_unifie.loc[mask_ml, 'volume_unitaire_l'] = df_menage_unifie.loc[mask_ml, 'volume_unitaire_l'] / 1000

            # Volume total pour ménages purs et supermarche_menage
            mask_pur_sm = df_menage_unifie['type_original'].isin(['menage', 'supermarche_menage'])
            df_menage_unifie['volume_total_l'] = np.nan
            if mask_pur_sm.any():
                nb = df_menage_unifie.loc[mask_pur_sm, 'quantite_nombre']
                vol_unit = df_menage_unifie.loc[mask_pur_sm, 'volume_unitaire_l']
                df_menage_unifie.loc[mask_pur_sm, 'volume_total_l'] = nb * vol_unit

            # Volume pour supermarché (déjà extrait)
            mask_s = df_menage_unifie['type_original'] == 'supermarche'
            if mask_s.any():
                df_menage_unifie.loc[mask_s, 'volume_total_l'] = df_menage_unifie.loc[mask_s, 'volume_total_l_supermarche']

            # Prix numérique
            df_menage_unifie['prix_num'] = pd.to_numeric(
                df_menage_unifie['prix_paye'].astype(str).str.replace(',', '.'), errors='coerce')
            df_menage_unifie['prix_litre'] = np.where(
                (df_menage_unifie['volume_total_l'].notna()) & (df_menage_unifie['volume_total_l'] > 0) & (df_menage_unifie['prix_num'].notna()),
                df_menage_unifie['prix_num'] / df_menage_unifie['volume_total_l'],
                np.nan
            )
            df_menage_unifie['prix_litre'].replace([np.inf, -np.inf], np.nan, inplace=True)

            # Taille du ménage (sécurisée)
            df_menage_unifie['taille_menage'] = pd.to_numeric(df_menage_unifie['nb_personnes'], errors='coerce')

            # Marque nettoyée (mapping strict)
            df_menage_unifie['marque_clean'] = apply_brand_mapping_strict(df_menage_unifie['marque_preferee'])
            # Correction spécifique : supermarche_menage "mbila" → "En vrac"
            mask_sm_menage = df_menage_unifie['type_original'] == 'supermarche_menage'
            df_menage_unifie.loc[mask_sm_menage & (df_menage_unifie['marque_clean'] == 'mbila'), 'marque_clean'] = 'En vrac'

            # Consentement à payer plus
            def pret_plus_val(texte):
                if not isinstance(texte, str):
                    return False
                crit_list = parse_criteres_smart(texte)
                for c in crit_list:
                    if any(mot in c.lower() for mot in ['non', 'pas prêt', 'ne suis pas prêt', 'aucun']):
                        return False
                return len(crit_list) > 0

            df_menage_unifie['pret_plus'] = df_menage_unifie['pret_payer_plus'].apply(pret_plus_val)
            df_menage_unifie['criteres'] = df_menage_unifie['pret_payer_plus'].apply(parse_criteres_smart)

            # Fréquence numérique et nettoyage des labels
            freq_map = {
                'Plusieurs fois par semaine': 8,
                'Une fois par semaine': 4,
                'Deux à trois fois par mois': 2.5,
                'Une fois par mois': 1,
                'Une fois par trimestre': 0.33,
                'Moins souvent': 0.166
            }
            # Nettoyage : transformer en chaîne, enlever les espaces superflus
            df_menage_unifie['frequence'] = df_menage_unifie['frequence'].astype(str).str.strip()
            # Si la valeur est un nombre pur (ex. '5'), on la remplace par NaN pour ne pas fausser le graphique
            df_menage_unifie.loc[df_menage_unifie['frequence'].str.match(r'^\d+(\.\d+)?$'), 'frequence'] = np.nan
            df_menage_unifie['freq_num'] = df_menage_unifie['frequence'].map(freq_map)

            # Zone socioéconomique
            if not df_sm.empty:
                sm_niveau = dict(zip(df_sm['Nom'].apply(normalize_name), df_sm['Niveau_socio']))
            else:
                sm_niveau = {}

            def zone_via_magasin(origine):
                if not isinstance(origine, str) or origine.strip() == '':
                    return None
                key = normalize_name(origine)
                if key in sm_niveau and sm_niveau[key] and sm_niveau[key] != 'Non renseigné':
                    return sm_niveau[key]
                best_score, best_val = 0, None
                for k, v in sm_niveau.items():
                    score = SequenceMatcher(None, key, k).ratio()
                    if score > best_score and score >= 0.8:
                        best_score, best_val = score, v
                return best_val

            mask_s_sm = df_menage_unifie['type_original'].isin(['supermarche', 'supermarche_menage'])
            df_menage_unifie['zone_socioeco'] = ''
            if mask_s_sm.any():
                df_menage_unifie.loc[mask_s_sm, 'zone_socioeco'] = df_menage_unifie.loc[mask_s_sm, 'supermarche_origine'].apply(zone_via_magasin)

            mask_m = df_menage_unifie['type_original'] == 'menage'
            if mask_m.any():
                commune_niveau = load_commune_niveau()
                commune_niveau_norm = {normalize_name(k): v for k, v in commune_niveau.items()}
                def zone_from_commune(commune):
                    if not isinstance(commune, str) or commune.strip() == '':
                        return 'Inconnu'
                    return commune_niveau_norm.get(normalize_name(commune), 'Non classé')
                df_menage_unifie.loc[mask_m, 'zone_socioeco'] = df_menage_unifie.loc[mask_m, 'commune'].apply(zone_from_commune)

            df_menage_unifie['zone_socioeco'] = df_menage_unifie['zone_socioeco'].replace('', 'Inconnu').fillna('Inconnu')
            # Exclure les questionnaires avec statut 'Refus' (si la colonne existe)
            if 'statut' in df_menage_unifie.columns:
                df_menage_unifie = df_menage_unifie[df_menage_unifie['statut'] != 'Refus'].copy()
    else:
        df_menage_unifie = pd.DataFrame()

    if df_menage_unifie.empty:
        st.info("Aucune donnée ménage disponible pour la période et l'enquêteur sélectionnés.")
    else:
        cat_options = {
            "Tous": "Tous",
            "1. Acheteurs supermarché": "Acheteur supermarché",
            "2. Non-acheteurs supermarché": "Non-acheteur supermarché",
            "3. Ménages purs": "Ménage pur"
        }
        cat_label = st.selectbox("Catégorie de questionnaire", list(cat_options.keys()), index=0)
        cat_value = cat_options[cat_label]

        df_m = df_menage_unifie.copy()
        if cat_value != "Tous":
            df_m = df_m[df_m['categorie'] == cat_value]

        def get_sexe_menage(x):
            if not isinstance(x, str): return None
            parts = x.split('-')
            if len(parts) >= 1:
                sexe = parts[0].strip().upper()
                if sexe in ['F', 'H']: return sexe
            return None

        def get_age_menage(x):
            if not isinstance(x, str): return None
            match = re.search(r'(\d+[-+]*\d*\s*ans?)', x)
            return match.group(1) if match else None

        def tranche_age(age_str):
            if not age_str: return 'Inconnu'
            try:
                age = int(re.search(r'\d+', age_str).group())
                if age < 25: return 'Moins de 25 ans'
                elif age < 35: return '25-34 ans'
                elif age < 50: return '35-49 ans'
                else: return '50 ans et plus'
            except: return 'Inconnu'

        df_m['Sexe'] = df_m['sexe_age'].apply(get_sexe_menage)
        df_m['Âge'] = df_m['sexe_age'].apply(get_age_menage)
        df_m['Tranche_age'] = df_m['Âge'].apply(tranche_age)

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            communes_disponibles = sorted(df_m['commune'].dropna().unique())
            commune_sel = st.selectbox("Commune", ["Tous"] + communes_disponibles, key="menage_commune")
        with col_f2:
            sexe_menage_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key="menage_sexe")
        with col_f3:
            age_menage_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"], key="menage_age")

        if commune_sel != "Tous":
            df_m = df_m[df_m['commune'] == commune_sel]
        if sexe_menage_sel != "Tous":
            df_m = df_m[df_m['Sexe'] == sexe_menage_sel]
        if age_menage_sel != "Tous":
            df_m = df_m[df_m['Tranche_age'] == age_menage_sel]

        if df_m.empty:
            st.info("Aucune donnée après filtrage.")
        else:
            nb_total = len(df_m)
            acheteurs_mask = (df_m['achat_huile'].str.lower() == 'oui')

            seuil_taille = 20
            seuil_volume = 50

            taille_valide = df_m['taille_menage'].notna() & (df_m['taille_menage'] > 0) & (df_m['taille_menage'] <= seuil_taille)
            volume_valide = df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= seuil_volume)
            acheteurs_vol_valide = acheteurs_mask & volume_valide

            nb_taille = taille_valide.sum()
            nb_taille_exclus = df_m['taille_menage'].notna().sum() - nb_taille

            nb_volume = volume_valide.sum()
            nb_prix_l = df_m['prix_litre'].notna().sum()
            nb_freq = df_m.loc[acheteurs_mask, 'frequence'].notna().sum()
            nb_marque = df_m['marque_clean'].notna().sum()
            nb_qual = df_m['qualite'].notna().sum()
            nb_rc_conn = df_m['rc_connaissance'].notna().sum()
            nb_rc_qual = df_m['rc_qualites'].notna().sum()
            nb_consent = df_m['pret_payer_plus'].notna().sum()
            nb_pourcent = df_m['pourcentages_achat'].notna().sum()

            with st.expander("📋 Récapitulatif des effectifs par section", expanded=True):
                recap = pd.DataFrame({
                    "Section": [
                        "Total questionnaires affichés",
                        "Distribution taille ménage (≤20 pers.)",
                        "Volume acheté / Prix au litre",
                        "Fréquence d'achat (acheteurs)",
                        "Marque (préférée ou achetée)",
                        "Perception qualité",
                        "Notoriété RougeCongo (connaissance)",
                        "Qualités RougeCongo",
                        "Consentement à payer plus",
                        "Lieux d'achat / Pourcentages"
                    ],
                    "Nombre de réponses": [
                        nb_total, nb_taille, nb_volume, nb_freq, nb_marque,
                        nb_qual, nb_rc_conn, nb_rc_qual, nb_consent, nb_pourcent
                    ]
                })
                st.dataframe(recap, use_container_width=True, hide_index=True)
                if nb_taille_exclus > 0:
                    st.caption(f"⚠️ {nb_taille_exclus} ménages exclus de la distribution de taille (taille ≤ 0 ou > {seuil_taille} pers.).")
                st.write("**Répartition par catégorie :**")
                st.write(df_m['categorie'].value_counts().to_dict())

            st.divider()

            # ── SYNTHÈSE ──
            st.subheader("📊 Synthèse")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Questionnaires", nb_total)
            taille_moy = df_m.loc[taille_valide, 'taille_menage'].mean()
            c2.metric("Taille moyenne du ménage", f"{taille_moy:.1f} pers.",
                      help=f"Calculée sur {nb_taille} ménages valides")
            vol_moy = df_m.loc[acheteurs_vol_valide, 'volume_total_l'].mean()
            c3.metric("Volume moyen acheté", f"{fmt_volume(vol_moy,2)} L",
                      help=f"Moyenne sur {acheteurs_vol_valide.sum()} acheteurs avec volume ≤ {seuil_volume} L")
            prix_moy = df_m.loc[df_m['prix_litre'].notna(), 'prix_litre'].mean()
            devise_aff = st.session_state.get("devise_globale", "FC")
            if pd.isna(prix_moy):
                c4.metric("Prix moyen au litre", "N/A")
            else:
                c4.metric("Prix moyen au litre", fmt_prix(prix_moy, devise_aff))
            nb_acheteurs = acheteurs_mask.sum()
            pct_acheteurs = (nb_acheteurs / nb_total * 100) if nb_total > 0 else 0
            c5.metric("% Acheteurs d'huile", f"{pct_acheteurs:.1f}%")
            freq_mode = df_m.loc[acheteurs_mask, 'frequence'].mode()
            freq_mode_str = freq_mode.iloc[0] if not freq_mode.empty else "N/A"
            st.caption(f"Fréquence la plus citée (acheteurs) : {freq_mode_str}")

            # ── PROFIL DES MÉNAGES ──
            st.subheader("👥 Profil des ménages")
            col_a, col_b = st.columns(2)
            with col_a:
                data_taille = df_m.loc[taille_valide, 'taille_menage']
                fig_taille = px.histogram(data_taille, x='taille_menage', nbins=20,
                                          title="Distribution de la taille des ménages",
                                          labels={'taille_menage': 'Nombre de personnes'})
                fig_taille.update_layout(template="gilroy_export")
                fig_taille = force_black_axes(fig_taille)
                st.plotly_chart(fig_taille, use_container_width=True)
                st.caption(f"Basé sur {nb_taille} réponses (exclusion de {nb_taille_exclus} ménages non valides).")
            with col_b:
                zone_counts = df_m['zone_socioeco'].value_counts().reset_index()
                zone_counts.columns = ['Zone socioéconomique', 'Nombre de ménages']
                zone_counts = zone_counts[zone_counts['Zone socioéconomique'] != 'Inconnu']
                nb_inconnus_zone = len(df_m[df_m['zone_socioeco'] == 'Inconnu'])
                ordre = ['Aisé', 'Moyen', 'Populaire', 'Non classé']
                zone_counts['ordre'] = zone_counts['Zone socioéconomique'].apply(
                    lambda x: ordre.index(x) if x in ordre else 99)
                zone_counts = zone_counts.sort_values('ordre')
                fig_zone = px.bar(zone_counts, x='Zone socioéconomique', y='Nombre de ménages',
                                  title="Ménages interrogés par zone socioéconomique",
                                  color='Zone socioéconomique', color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_zone.update_layout(showlegend=False, template="gilroy_export")
                fig_zone = force_black_axes(fig_zone)
                st.plotly_chart(fig_zone, use_container_width=True)
                st.caption(f"{nb_inconnus_zone} ménages avec zone 'Inconnu' exclus du graphique.")

            st.subheader("📏 Taille moyenne du ménage par zone socioéconomique")
            df_tz = df_m[taille_valide & (df_m['zone_socioeco'] != 'Inconnu')]
            taille_zone = df_tz.groupby('zone_socioeco')['taille_menage'].mean().reset_index()
            taille_zone.columns = ['Zone socioéconomique', 'Taille moyenne']
            taille_zone['ordre'] = taille_zone['Zone socioéconomique'].apply(
                lambda x: ordre.index(x) if x in ordre else 99)
            taille_zone = taille_zone.sort_values('ordre')
            fig_tz = px.bar(taille_zone, x='Zone socioéconomique', y='Taille moyenne',
                            text='Taille moyenne', color='Zone socioéconomique',
                            color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_tz.update_traces(texttemplate='%{text:.1f} pers.', textposition='outside')
            fig_tz.update_layout(showlegend=False, yaxis_title="Personnes", template="gilroy_export")
            fig_tz = force_black_axes(fig_tz)
            st.plotly_chart(fig_tz, use_container_width=True)

            # ── VOLUME ET FRÉQUENCE ──
            st.subheader("🛒 Volume et fréquence d'achat")
            col1, col2 = st.columns(2)
            with col1:
                # Camembert par tranches de volume
                df_vol = df_m[df_m['volume_total_l'].notna() & (df_m['volume_total_l'] <= seuil_volume) & (df_m['volume_total_l'] > 0)].copy()
                if not df_vol.empty:
                    def tranche_vol(x):
                        if x < 0.5:
                            return '<0,5 L'
                        elif x <= 1:
                            return '0,5-1 L'
                        elif x <= 2:
                            return '1-2 L'
                        elif x <= 3:
                            return '2-3 L'
                        elif x <= 4:
                            return '3-4 L'
                        elif x <= 5:
                            return '4-5 L'
                        else:
                            return '>5 L'
                    df_vol['tranche_vol'] = df_vol['volume_total_l'].apply(tranche_vol)
                    vol_counts = df_vol['tranche_vol'].value_counts().reset_index()
                    vol_counts.columns = ['Tranche de volume', 'Nombre']
                    fig_vol_pie = px.pie(vol_counts, values='Nombre', names='Tranche de volume',
                                         title="Volume acheté (% des répondants)",
                                         category_orders={'Tranche de volume': ['<1 L', '1-4 L', '5 L', '>5 L']})
                    fig_vol_pie.update_layout(template="gilroy_export")
                    fig_vol_pie = force_black_axes(fig_vol_pie)
                    st.plotly_chart(fig_vol_pie, use_container_width=True)
                    st.caption(f"Basé sur {len(df_vol)} répondants avec un volume valide.")
                else:
                    st.info("Aucun volume valide.")
            with col2:
                freq_df = df_m[acheteurs_mask].dropna(subset=['frequence'])
                if not freq_df.empty:
                    freq_counts = freq_df['frequence'].value_counts().reset_index()
                    freq_counts.columns = ['Fréquence', 'Nombre']
                    fig_freq = px.pie(freq_counts, values='Nombre', names='Fréquence',
                                      title="Fréquence d'achat (acheteurs)")
                    fig_freq.update_layout(template="gilroy_export")
                    fig_freq = force_black_axes(fig_freq)
                    st.plotly_chart(fig_freq, use_container_width=True)
                    st.caption(f"Basé sur {len(freq_df)} acheteurs.")
                else:
                    st.info("Aucune fréquence renseignée pour les acheteurs.")

            # ── MARQUE ──
            st.subheader("🏷️ Marque (préférée ou achetée)")
            marque_counts = df_m['marque_clean'].dropna().value_counts().reset_index()
            marque_counts.columns = ['Marque', 'Nombre']
            if not marque_counts.empty:
                fig_marque = px.pie(marque_counts, values='Nombre', names='Marque',
                                    title="Répartition des marques")
                fig_marque.update_layout(template="gilroy_export")
                fig_marque = force_black_axes(fig_marque)
                st.plotly_chart(fig_marque, use_container_width=True)
                st.caption(f"Basé sur {nb_marque} réponses avec marque reconnue.")

                with st.expander("🔍 Inspecter les marques brutes pour une marque sélectionnée"):
                    marque_choisie = st.selectbox("Choisir une marque (clean)", marque_counts['Marque'].tolist(), key="inspect_marque")
                    if marque_choisie:
                        sub_inspect = df_m[df_m['marque_clean'] == marque_choisie][['uuid', 'type_original', 'marque_preferee', 'marque_clean']]
                        st.dataframe(sub_inspect, use_container_width=True)
                        st.caption(f"{len(sub_inspect)} questionnaires pour la marque '{marque_choisie}'")
            else:
                st.info("Aucune marque.")

            # ── PRIX AU LITRE ──
            st.subheader("💲 Prix au litre")
            seuil_prix_affichage = 10000  # FC/L
            prix_plot = df_m[(df_m['prix_litre'].notna()) & (df_m['prix_litre'] <= seuil_prix_affichage)]
            nb_exclus_prix = df_m['prix_litre'].notna().sum() - len(prix_plot)
            if not prix_plot.empty:
                fig_prix = px.box(prix_plot, y='prix_litre', title="Distribution du prix au litre")
                if devise_aff == "FC":
                    fig_prix.update_yaxes(tickformat=",.0f", ticksuffix=" FC")
                else:
                    fig_prix.update_yaxes(tickformat=",.2f", tickprefix="$ ")
                fig_prix.update_layout(template="gilroy_export")
                fig_prix = force_black_axes(fig_prix)
                st.plotly_chart(fig_prix, use_container_width=True)
                st.caption(f"Basé sur {len(prix_plot)} réponses (≤ {fmt_nombre(seuil_prix_affichage,0)} FC/L). {nb_exclus_prix} valeurs extrêmes exclues.")
            else:
                st.info("Aucune valeur de prix au litre disponible.")

            # ── CONSENTEMENT À PAYER PLUS CHER ──
            st.subheader("💵 Consentement à payer plus cher")
            if nb_consent > 0:
                pret_oui = df_m['pret_plus'].sum()
                tx = pret_oui / nb_consent * 100 if nb_consent else 0
                st.metric("Prêts à payer plus", f"{tx:.1f}% ({int(pret_oui)}/{nb_consent})")
                if pret_oui > 0:
                    crits = df_m[df_m['pret_plus']]['criteres'].explode().dropna()
                    crits = crits[~crits.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    crit_counts = crits.value_counts().reset_index()
                    crit_counts.columns = ['Critère', 'Nombre']
                    fig_crit = px.bar(crit_counts, x='Critère', y='Nombre',
                                      title="Critères pour payer plus cher")
                    fig_crit.update_layout(template="gilroy_export")
                    fig_crit = force_black_axes(fig_crit)
                    st.plotly_chart(fig_crit, use_container_width=True)

                    df_pret = df_m[df_m['pret_plus']].dropna(subset=['prix_num', 'prix_max']).copy()
                    if not df_pret.empty:
                        df_pret['ecart_rel'] = (pd.to_numeric(df_pret['prix_max'], errors='coerce') /
                                                pd.to_numeric(df_pret['prix_num'], errors='coerce') - 1) * 100
                        df_pret = df_pret[df_pret['ecart_rel'].notna() & (df_pret['ecart_rel'].abs() < 1000)]
                        exploded = df_pret.explode('criteres')
                        exploded = exploded[~exploded['criteres'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        ecart_crit = exploded.groupby('criteres')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_crit.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                        ecart_crit['Écart moyen (%)'] = ecart_crit['Écart moyen (%)'].round(1)
                        fig_ecart = px.bar(ecart_crit, x='Critère', y='Écart moyen (%)',
                                           text='Nb répondants',
                                           title="% moyen que les acheteurs sont prêts à payer en plus, par critère")
                        fig_ecart.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_ecart.update_layout(template="gilroy_export")
                        fig_ecart = force_black_axes(fig_ecart)
                        st.plotly_chart(fig_ecart, use_container_width=True)
                    else:
                        st.info("Données insuffisantes pour le calcul de l'écart.")
                else:
                    st.info("Aucun répondant prêt à payer plus.")
            else:
                st.info("Données non disponibles.")

            # ── PERCEPTION QUALITÉ ──
            st.subheader("🧪 Perception de la qualité")
            if nb_qual > 0:
                qual_ser = df_m['qualite'].dropna().astype(str).str.split(',').explode().str.strip()
                qual_ser = qual_ser[qual_ser != '']
                qual_ser = qual_ser.apply(lambda x: x.split(':',1)[1].strip() if x.lower().startswith('autre:') else x)
                qual_counts = qual_ser.value_counts().reset_index()
                qual_counts.columns = ['Critère', 'Nombre']
                fig_qual = px.bar(qual_counts, x='Critère', y='Nombre',
                                  title="Comment reconnaissez-vous la qualité ?")
                fig_qual.update_layout(template="gilroy_export")
                fig_qual = force_black_axes(fig_qual)
                st.plotly_chart(fig_qual, use_container_width=True)
            else:
                st.info("Aucune réponse.")

            # ── NOTORIÉTÉ RougeCongo ──
            st.subheader("📣 Notoriété de RougeCongo")
            col_c, col_q = st.columns(2)
            with col_c:
                if nb_rc_conn > 0:
                    conn = df_m['rc_connaissance'].dropna().loc[lambda x: x != ''].value_counts().reset_index()
                    conn.columns = ['Réponse', 'Nombre']
                    if not conn.empty:
                        fig_conn = px.bar(conn, x='Réponse', y='Nombre',
                                          title="Connaissance de RougeCongo")
                        fig_conn.update_layout(template="gilroy_export")
                        fig_conn = force_black_axes(fig_conn)
                        st.plotly_chart(fig_conn, use_container_width=True)
                    else:
                        st.info("Aucune réponse valide.")
                else:
                    st.info("Aucune donnée.")
            with col_q:
                if nb_rc_qual > 0:
                    qual_rc = df_m['rc_qualites'].dropna().astype(str).str.split(',').explode().str.strip()
                    qual_rc = qual_rc[qual_rc != '']
                    qual_rc = qual_rc.apply(lambda x: x.split(':',1)[1].strip() if x.lower().startswith('autre:') else x)
                    qc = qual_rc.value_counts().reset_index()
                    qc.columns = ['Qualité', 'Nombre']
                    if not qc.empty:
                        fig_rc_qual = px.bar(qc, x='Qualité', y='Nombre',
                                             title="Qualités attribuées à RougeCongo")
                        fig_rc_qual.update_layout(template="gilroy_export")
                        fig_rc_qual = force_black_axes(fig_rc_qual)
                        st.plotly_chart(fig_rc_qual, use_container_width=True)
                    else:
                        st.info("Aucune réponse.")
                else:
                    st.info("Aucune réponse.")

            # ── LIEUX D'ACHAT ──
            st.subheader("📍 Lieux d'achat / Répartition des dépenses")
            if nb_pourcent > 0:
                mask_pct = df_m['type_original'].isin(['menage', 'supermarche_menage'])
                df_pct = df_m[mask_pct].dropna(subset=['pourcentages_achat'])
                if not df_pct.empty:
                    records = []
                    for _, row in df_pct.iterrows():
                        texte = row['pourcentages_achat']
                        if not isinstance(texte, str): continue
                        for part in texte.split(','):
                            part = part.strip()
                            if ':' not in part: continue
                            cat, pct_str = part.split(':', 1)
                            pct = pd.to_numeric(pct_str.strip().replace('%', ''), errors='coerce')
                            if pd.notna(pct):
                                records.append({'Catégorie': cat.strip(), 'Pourcentage': pct})
                    if records:
                        df_lieux = pd.DataFrame(records)
                        df_moy = df_lieux.groupby('Catégorie')['Pourcentage'].mean().reset_index()
                        df_moy.columns = ['Catégorie', 'Pourcentage moyen']
                        fig_lieux = px.bar(df_moy, x='Catégorie', y='Pourcentage moyen',
                                           title="Part moyenne des dépenses par canal")
                        fig_lieux.update_layout(template="gilroy_export")
                        fig_lieux = force_black_axes(fig_lieux)
                        st.plotly_chart(fig_lieux, use_container_width=True)
                        st.caption(f"Basé sur {len(df_pct)} questionnaires.")
                    else:
                        st.info("Aucune répartition exploitable.")
                else:
                    st.info("Aucune donnée de pourcentages.")
                if (df_m['type_original'] == 'supermarche').any():
                    st.info("Les acheteurs supermarché ne sont pas inclus (question différente).")
            else:
                st.info("Aucune donnée.")

            st.download_button("📥 Télécharger les données (CSV)", df_m.to_csv(index=False), "menages.csv")

# ------------------------------------------------------------
# ONGLET 4 : COMPTAGES & FLUX (refonte complète avec formatage)
# ------------------------------------------------------------
with tabs[4]:
    st.header("🚶 Comptages & Flux – Affluence estimée par magasin")

    if df_c_f.empty:
        st.info("Aucune donnée de comptage disponible pour la période sélectionnée.")
        st.stop()

    if not selected_mags:
        st.warning("⚠️ Aucun magasin sélectionné. Veuillez d'abord choisir des magasins dans l'onglet 'Accueil'.")
        st.stop()

    # --------------------------------------------------------
    # Chargement des données annexes
    # --------------------------------------------------------
    df_profils_pivot, _ = load_frequentation_data()

    secteur_profiles = None
    if not df_profils_pivot.empty and not df_sm.empty:
        df_profils_pivot['magasin_norm'] = df_profils_pivot['magasin'].apply(normalize_name)
        df_sm['nom_norm'] = df_sm['Nom'].apply(normalize_name)
        merged = df_profils_pivot.merge(df_sm[['nom_norm', 'Secteur']],
                                        left_on='magasin_norm', right_on='nom_norm', how='left')
        secteur_profiles_list = []
        for secteur in merged['Secteur'].dropna().unique():
            sub = merged[merged['Secteur'] == secteur]
            cols = [c for c in sub.columns if c not in ['magasin', 'magasin_norm', 'Secteur', 'nom_norm']]
            median_row = {'secteur': secteur}
            for c in cols:
                median_row[c] = sub[c].median()
            secteur_profiles_list.append(median_row)
        if secteur_profiles_list:
            secteur_profiles = pd.DataFrame(secteur_profiles_list)

    mapping_file = "magasin_mapping.json"
    magasin_mapping = {}
    if os.path.exists(mapping_file):
        with open(mapping_file, 'r', encoding='utf-8') as f:
            magasin_mapping = json.load(f)

    k_overrides = load_k_overrides()

    # --------------------------------------------------------
    # Fonctions internes à l'onglet
    # --------------------------------------------------------
    def get_effective_profile(magasin, jour_code):
        nom_google = magasin_mapping.get(magasin)
        if nom_google and nom_google in df_profils_pivot['magasin'].values:
            row = df_profils_pivot[df_profils_pivot['magasin'] == nom_google].iloc[0]
            profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            if max(profil) > 0:
                return profil, "Google", nom_google
        secteur = df_sm[df_sm['Nom'] == magasin]['Secteur'].values
        if len(secteur) > 0 and secteur_profiles is not None:
            secteur = secteur[0]
            if secteur in secteur_profiles['secteur'].values:
                row_sect = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
                return profil, f"Secteur {secteur}", "Profil secteur"
        return [1.0]*24, "Uniforme", "Aucun"

    def get_opening_hours(row_sm, jour_type):
        if jour_type == 'semaine':
            ouverture = str(row_sm.get('ouv_sem', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_sem', '18:00')).strip()
        else:
            ouverture = str(row_sm.get('ouv_we', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_we', '18:00')).strip()
        def parse_horaire(h_str):
            h_str = h_str.upper().replace('H', ':00').replace(' ', '')
            try:
                t = datetime.strptime(h_str, '%H:%M')
                return t.hour, t.minute
            except:
                return 8, 0
        h_ouv, m_ouv = parse_horaire(ouverture)
        h_ferm, m_ferm = parse_horaire(fermeture)
        ouvert = [False]*24
        for h in range(24):
            if h > h_ouv and h < h_ferm:
                ouvert[h] = True
            elif h == h_ouv and m_ouv == 0:
                ouvert[h] = True
            elif h == h_ferm and m_ferm == 0:
                ouvert[h] = False
            elif h == h_ouv and m_ouv > 0:
                ouvert[h] = True
            elif h == h_ferm and m_ferm > 0:
                ouvert[h] = True
        return ouvert

    def compute_k_factors_onglet(magasin):
        comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
        if comptages.empty:
            return None, None, []
        k_sem_list, k_we_list, details = [], [], []
        jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}
        for _, row in comptages.iterrows():
            date_obj = row['date_dt']
            jour_code = date_obj.strftime('%a')
            jour_code_google = jour_map.get(jour_code, jour_code)
            profil, source, _ = get_effective_profile(magasin, jour_code_google)
            debut, fin = row['debut_dt'], row['fin_dt']
            duree = (fin - debut).total_seconds() / 3600.0
            if duree <= 0:
                continue
            start_min = debut.hour * 60 + debut.minute
            end_min = fin.hour * 60 + fin.minute
            current = start_min
            G_moy = 0.0
            while current < end_min:
                h = current // 60
                next_min = min((h+1)*60, end_min)
                frac = (next_min - current) / 60.0
                G_moy += profil[h] * frac
                current = next_min
            G_moy = G_moy / duree if duree > 0 else 0
            if G_moy <= 0:
                continue
            flux_reel = row['total'] / duree
            k = flux_reel / G_moy
            is_we = date_obj.weekday() >= 5
            jour_type = 'weekend' if is_we else 'semaine'
            if jour_type == 'semaine':
                k_sem_list.append(k)
            else:
                k_we_list.append(k)
            details.append({
                'date': date_obj.strftime('%Y-%m-%d'),
                'type': jour_type,
                'k': k,
                'source': source,
                'debut': debut.strftime('%H:%M'),
                'fin': fin.strftime('%H:%M'),
                'duree_h': duree,
                'total': row['total'],
                'flux_reel': flux_reel,
                'G_moy': G_moy,
                'debut_dt': debut,
                'fin_dt': fin
            })
        k_sem = np.median(k_sem_list) if k_sem_list else None
        k_we  = np.median(k_we_list) if k_we_list else None
        if k_sem is None and k_we is not None: k_sem = k_we
        if k_we is None and k_sem is not None: k_we = k_sem
        return k_sem, k_we, details

    def estimate_daily_flow_onglet(magasin, jour_code, k_sem, k_we, profil):
        is_we = jour_code in ['Sa', 'Su']
        k = k_we if is_we else k_sem
        if k is None:
            return [0]*24, 0
        sm_row = df_sm[df_sm['Nom'] == magasin]
        if sm_row.empty:
            ouvert = [True]*24
        else:
            ouvert = get_opening_hours(sm_row.iloc[0], 'semaine' if not is_we else 'weekend')
        clients = []
        for h in range(24):
            if ouvert[h]:
                clients.append(int(round(k * profil[h])))
            else:
                clients.append(0)
        return clients, sum(clients)

    # --------------------------------------------------------
    # 2.1 – Tableau de correspondance magasin ↔ profil Google
    # --------------------------------------------------------
    st.subheader("🔗 Correspondance magasin – profil Google (mapping)")
    st.markdown("Pour chaque magasin sélectionné, choisissez un profil Google direct ou un profil médian de secteur. "
                "La valeur par défaut est le profil médian du secteur du magasin (s'il n'y a pas de mapping Google existant).")

    with st.expander("✏️ Éditer la correspondance"):
        magasins_dispos_google = sorted(df_profils_pivot['magasin'].unique()) if not df_profils_pivot.empty else []
        secteurs_dispos = sorted(secteur_profiles['secteur'].unique()) if secteur_profiles is not None else []
        secteur_options = [f"Profil médian secteur {s}" for s in secteurs_dispos]
        options = secteur_options + magasins_dispos_google

        mapping_corrige = magasin_mapping.copy()
        for mag in selected_mags:
            current_val = mapping_corrige.get(mag, "")
            secteur_mag = df_sm[df_sm['Nom'] == mag]['Secteur'].values[0] if not df_sm[df_sm['Nom'] == mag].empty else None
            default_secteur_str = f"Profil médian secteur {secteur_mag}" if secteur_mag and f"Profil médian secteur {secteur_mag}" in options else ""
            if not current_val or current_val not in options:
                current_val = default_secteur_str if default_secteur_str else options[0]
            idx = options.index(current_val) if current_val in options else 0
            new_val = st.selectbox(f"**{mag}**", options, index=idx, key=f"mapping_{mag}")
            if new_val.startswith("Profil médian secteur "):
                mapping_corrige[mag] = ""
            else:
                mapping_corrige[mag] = new_val

        if st.button("💾 Enregistrer les modifications", key="save_mapping_flux"):
            clean_mapping = {k: v for k, v in mapping_corrige.items() if v}
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(clean_mapping, f, indent=2, ensure_ascii=False)
            st.success("Correspondance sauvegardée. Les calculs vont être mis à jour.")
            st.rerun()

    # --------------------------------------------------------
    # Calcul des k pour tous les magasins sélectionnés
    # --------------------------------------------------------
    all_k_data = {}
    for mag in selected_mags:
        k_sem, k_we, details = cached_compute_k_factors(mag, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping)
        over = k_overrides.get(mag, {})
        if 'k_sem' in over: k_sem = over['k_sem']
        if 'k_we' in over: k_we = over['k_we']
        all_k_data[mag] = {'k_sem': k_sem, 'k_we': k_we, 'details': details}

    # --------------------------------------------------------
    # 2.3 – Tableau synthétique des k
    # --------------------------------------------------------
    st.subheader("📊 Synthèse des facteurs k")
    rows_synthese = []
    for mag in selected_mags:
        data = all_k_data[mag]
        k_sem = data['k_sem']
        k_we  = data['k_we']
        details = data['details']
        sem_vals = [d['k'] for d in details if d['type'] == 'semaine']
        we_vals = [d['k'] for d in details if d['type'] == 'weekend']
        cv_sem = np.std(sem_vals)/np.mean(sem_vals) if len(sem_vals)>1 else 0
        cv_we  = np.std(we_vals)/np.mean(we_vals) if len(we_vals)>1 else 0
        _, source, _ = get_effective_profile(mag, 'Mo')
        rows_synthese.append({
            'Magasin': mag,
            'k_sem_num': k_sem,
            'k_we_num': k_we,
            'cv_sem_num': cv_sem,
            'cv_we_num': cv_we,
            'Nb comptages': len(details),
            'Source profil': source
        })

    df_synthese = pd.DataFrame(rows_synthese)

    seuil_cv = st.slider("Seuil d'alerte CV", 0.0, 1.0, 0.3, 0.05, key="cv_slider")
    alertes = df_synthese[(df_synthese['cv_sem_num'] > seuil_cv) | (df_synthese['cv_we_num'] > seuil_cv)]

    # Formatage pour affichage
    df_synthese_disp = df_synthese.copy()
    df_synthese_disp['k semaine'] = df_synthese_disp['k_sem_num'].apply(lambda x: fmt_nombre(x, 2) if pd.notna(x) else "")
    df_synthese_disp['k week‑end'] = df_synthese_disp['k_we_num'].apply(lambda x: fmt_nombre(x, 2) if pd.notna(x) else "")
    df_synthese_disp['CV semaine'] = df_synthese_disp['cv_sem_num'].apply(lambda x: fmt_nombre(x, 2))
    df_synthese_disp['CV week‑end'] = df_synthese_disp['cv_we_num'].apply(lambda x: fmt_nombre(x, 2))
    st.dataframe(df_synthese_disp[['Magasin', 'k semaine', 'k week‑end', 'CV semaine', 'CV week‑end', 'Nb comptages', 'Source profil']],
                 use_container_width=True)

    if not alertes.empty:
        st.warning(f"{len(alertes)} magasin(s) avec une dispersion élevée (CV > {seuil_cv}) :")
        st.dataframe(alertes[['Magasin', 'cv_sem_num', 'cv_we_num']].rename(columns={'cv_sem_num': 'CV semaine', 'cv_we_num': 'CV week‑end'}),
                     use_container_width=True)

    with st.expander("🔧 Forcer manuellement les facteurs k"):
        mag_force = st.selectbox("Choisir un magasin", [""] + selected_mags, key="mag_force")
        if mag_force:
            current_over = k_overrides.get(mag_force, {})
            current_sem = current_over.get('k_sem', all_k_data[mag_force]['k_sem'])
            current_we  = current_over.get('k_we', all_k_data[mag_force]['k_we'])
            new_sem = st.number_input(f"k_sem pour {mag_force}", value=float(current_sem) if current_sem is not None else 0.0, step=10.0)
            new_we  = st.number_input(f"k_we pour {mag_force}", value=float(current_we) if current_we is not None else 0.0, step=10.0)
            if st.button("Appliquer le forçage", key="force_k"):
                overrides = load_k_overrides()
                overrides[mag_force] = {'k_sem': new_sem, 'k_we': new_we}
                save_k_overrides(overrides)
                st.success("Facteurs k forcés. Rechargez la page pour les prendre en compte.")
                st.rerun()

    # --------------------------------------------------------
    # 2.2 – Graphiques intégrés par magasin
    # --------------------------------------------------------
    st.subheader("📈 Profil, plages de comptage et évolution des k")
    mag_choisi = st.selectbox("Magasin à visualiser", selected_mags, key="mag_vizu")
    if mag_choisi:
        data = all_k_data[mag_choisi]
        k_sem = data['k_sem']
        k_we  = data['k_we']
        details = data['details']

        jours_sem = ['Mo', 'Tu', 'We', 'Th', 'Fr']
        jours_we  = ['Sa', 'Su']
        profils_sem, profils_we = [], []
        for jour in jours_sem:
            profil, _, _ = get_effective_profile(mag_choisi, jour)
            clients, _ = estimate_daily_flow_onglet(mag_choisi, jour, k_sem, k_we, profil)
            profils_sem.append(clients)
        for jour in jours_we:
            profil, _, _ = get_effective_profile(mag_choisi, jour)
            clients, _ = estimate_daily_flow_onglet(mag_choisi, jour, k_sem, k_we, profil)
            profils_we.append(clients)
        median_sem = np.median(profils_sem, axis=0) if profils_sem else [0]*24
        median_we  = np.median(profils_we, axis=0) if profils_we else [0]*24

        heures = list(range(24))
        k_par_heure_sem = {h: [] for h in heures}
        k_par_heure_we  = {h: [] for h in heures}
        for d in details:
            debut_h = d['debut_dt'].hour + d['debut_dt'].minute/60
            fin_h   = d['fin_dt'].hour + d['fin_dt'].minute/60
            for h in range(int(debut_h), min(int(fin_h)+1, 24)):
                if d['type'] == 'semaine':
                    k_par_heure_sem[h].append(d['k'])
                else:
                    k_par_heure_we[h].append(d['k'])

        def pct_couverture_par_heure(details_list, type_jour):
            from collections import defaultdict
            jours = defaultdict(list)
            for d in details_list:
                if d['type'] != type_jour: continue
                date = d['date']
                jours[date].append((d['debut_dt'].hour*60 + d['debut_dt'].minute,
                                    d['fin_dt'].hour*60 + d['fin_dt'].minute))
            pct = [0.0]*24
            for h in range(24):
                total_couvert = 0
                for date, intervals in jours.items():
                    parts = []
                    for debut, fin in intervals:
                        if debut < (h+1)*60 and fin > h*60:
                            start_in_h = max(debut, h*60)
                            end_in_h   = min(fin, (h+1)*60)
                            if end_in_h > start_in_h:
                                parts.append((start_in_h - h*60, end_in_h - h*60))
                    if parts:
                        parts.sort()
                        merged = []
                        cur_s, cur_e = parts[0]
                        for s, e in parts[1:]:
                            if s <= cur_e: cur_e = max(cur_e, e)
                            else:
                                merged.append((cur_s, cur_e))
                                cur_s, cur_e = s, e
                        merged.append((cur_s, cur_e))
                        duree = sum(e - s for s, e in merged)
                        total_couvert += duree
                nb_jours = len(jours)
                if nb_jours > 0: pct[h] = (total_couvert / (60 * nb_jours)) * 100
            return pct

        pct_sem = pct_couverture_par_heure(details, 'semaine')
        pct_we  = pct_couverture_par_heure(details, 'weekend')

        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Profil clients estimés et boxplots k", "Couverture des comptages et k par heure"),
            vertical_spacing=0.25,
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
        )

        # Sous-graphique 1
        fig.add_trace(go.Scatter(x=heures, y=median_sem, mode='lines', name='Clients semaine',
                                 line=dict(color='blue', width=3)), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=heures, y=median_we, mode='lines', name='Clients week‑end',
                                 line=dict(color='orange', width=3)), row=1, col=1, secondary_y=False)

        for h in heures:
            if k_par_heure_sem[h]:
                fig.add_trace(go.Box(y=k_par_heure_sem[h], x=[h-0.2]*len(k_par_heure_sem[h]),
                                     name='k semaine', legendgroup='k semaine',
                                     showlegend=(h==0), marker=dict(color='blue'),
                                     boxpoints='all', jitter=0.3, pointpos=0, width=0.3, offsetgroup='sem'),
                              row=1, col=1, secondary_y=True)
            if k_par_heure_we[h]:
                fig.add_trace(go.Box(y=k_par_heure_we[h], x=[h+0.2]*len(k_par_heure_we[h]),
                                     name='k week‑end', legendgroup='k week‑end',
                                     showlegend=(h==0), marker=dict(color='orange'),
                                     boxpoints='all', jitter=0.3, pointpos=0, width=0.3, offsetgroup='we'),
                              row=1, col=1, secondary_y=True)

        fig.update_xaxes(title_text="Heure", tickvals=heures[::2],
                         ticktext=[f"{h}h" for h in heures[::2]], row=1, col=1)
        fig.update_yaxes(title_text="Clients estimés / heure", tickformat=",.0f", row=1, col=1, secondary_y=False)
        fig.update_yaxes(title_text="k", row=1, col=1, secondary_y=True)

        # Sous-graphique 2
        fig.add_trace(go.Bar(x=heures, y=pct_sem, name='% couverture semaine',
                             marker=dict(color='blue', opacity=0.6)), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Bar(x=heures, y=pct_we, name='% couverture week‑end',
                             marker=dict(color='orange', opacity=0.6)), row=2, col=1, secondary_y=False)

        for h in heures:
            if k_par_heure_sem[h]:
                fig.add_trace(go.Box(y=k_par_heure_sem[h], x=[h-0.2]*len(k_par_heure_sem[h]),
                                     name='k semaine', legendgroup='k semaine2',
                                     showlegend=False, marker=dict(color='blue'),
                                     boxpoints='all', jitter=0.3, pointpos=0, width=0.3, offsetgroup='sem2'),
                              row=2, col=1, secondary_y=True)
            if k_par_heure_we[h]:
                fig.add_trace(go.Box(y=k_par_heure_we[h], x=[h+0.2]*len(k_par_heure_we[h]),
                                     name='k week‑end', legendgroup='k week‑end2',
                                     showlegend=False, marker=dict(color='orange'),
                                     boxpoints='all', jitter=0.3, pointpos=0, width=0.3, offsetgroup='we2'),
                              row=2, col=1, secondary_y=True)

        fig.update_xaxes(title_text="Heure", tickvals=heures[::2],
                         ticktext=[f"{h}h" for h in heures[::2]], row=2, col=1)
        fig.update_yaxes(title_text="% couverture", row=2, col=1, secondary_y=False)
        fig.update_yaxes(title_text="k", row=2, col=1, secondary_y=True)

        fig.update_layout(height=800, title_text=f"Analyse intégrée – {mag_choisi}", template="gilroy_export")
        fig = force_black_axes(fig)
        st.plotly_chart(fig, use_container_width=True, key="analyse_integree")

    # --------------------------------------------------------
    # 2.4 – Périodes d’affluence par secteur (Google)
    # --------------------------------------------------------
    st.subheader("⏰ Périodes d’affluence par secteur")

    if secteur_profiles is None or secteur_profiles.empty:
        st.info("Aucun profil secteur disponible.")
    else:
        secteurs_selection = df_sm[df_sm['Nom'].isin(selected_mags)]['Secteur'].unique()
        secteurs_a_afficher = [s for s in secteurs_selection if s in secteur_profiles['secteur'].values]
        if not secteurs_a_afficher:
            st.info("Aucun secteur trouvé pour les magasins sélectionnés.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Semaine (lun‑ven)**")
                sem_data = []
                for secteur in secteurs_a_afficher:
                    row = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                    vals = [np.mean([row.get(f"{j}_{h}", 0.0) for j in ['Mo','Tu','We','Th','Fr']]) for h in range(24)]
                    sem_data.append(vals)
                df_sem_heat = pd.DataFrame(sem_data, index=secteurs_a_afficher, columns=[f"{h}h" for h in range(24)])
                fig_heat_sem = px.imshow(df_sem_heat, labels=dict(x="Heure", y="Secteur", color="Occupancy %"),
                                         title="Affluence semaine")
                fig_heat_sem.update_xaxes(tickvals=list(range(0,24,2)))
                fig_heat_sem.update_layout(template="gilroy_export")
                fig_heat_sem = force_black_axes(fig_heat_sem)
                st.plotly_chart(fig_heat_sem, use_container_width=True, key="heat_sem")
            with col2:
                st.markdown("**Week‑end (sam‑dim)**")
                we_data = []
                for secteur in secteurs_a_afficher:
                    row = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                    vals = [np.mean([row.get(f"{j}_{h}", 0.0) for j in ['Sa','Su']]) for h in range(24)]
                    we_data.append(vals)
                df_we_heat = pd.DataFrame(we_data, index=secteurs_a_afficher, columns=[f"{h}h" for h in range(24)])
                fig_heat_we = px.imshow(df_we_heat, labels=dict(x="Heure", y="Secteur", color="Occupancy %"),
                                        title="Affluence week‑end")
                fig_heat_we.update_xaxes(tickvals=list(range(0,24,2)))
                fig_heat_we.update_layout(template="gilroy_export")
                fig_heat_we = force_black_axes(fig_heat_we)
                st.plotly_chart(fig_heat_we, use_container_width=True, key="heat_we")

            secteur_sel = st.selectbox("Détail pour un secteur", secteurs_a_afficher, key="sect_detail")
            row_sec = secteur_profiles[secteur_profiles['secteur'] == secteur_sel].iloc[0]
            median_sem_occ = [np.mean([row_sec.get(f"{j}_{h}", 0.0) for j in jours_sem]) for h in range(24)]
            median_we_occ  = [np.mean([row_sec.get(f"{j}_{h}", 0.0) for j in jours_we]) for h in range(24)]

            fig_pointe = go.Figure()
            fig_pointe.add_trace(go.Scatter(x=heures, y=median_sem_occ, mode='lines', name='Semaine', line=dict(color='blue')))
            fig_pointe.add_trace(go.Scatter(x=heures, y=median_we_occ, mode='lines', name='Week‑end', line=dict(color='orange')))

            top_sem = sorted(enumerate(median_sem_occ), key=lambda x: x[1], reverse=True)[:3]
            for h, val in top_sem:
                fig_pointe.add_shape(type="rect", x0=h-0.4, x1=h+0.4, y0=0, y1=val, fillcolor="blue", opacity=0.2, line_width=0)
            top_we = sorted(enumerate(median_we_occ), key=lambda x: x[1], reverse=True)[:3]
            for h, val in top_we:
                fig_pointe.add_shape(type="rect", x0=h-0.4, x1=h+0.4, y0=0, y1=val, fillcolor="orange", opacity=0.2, line_width=0)

            fig_pointe.update_xaxes(title_text="Heure", tickvals=heures[::2], ticktext=[f"{h}h" for h in heures[::2]])
            fig_pointe.update_yaxes(title_text="Occupation %")
            fig_pointe.update_layout(title=f"Profil d’affluence – secteur {secteur_sel} (avec top 3 heures)", template="gilroy_export")
            fig_pointe = force_black_axes(fig_pointe)
            st.plotly_chart(fig_pointe, use_container_width=True, key="pointe_secteur")

            top_data = []
            for secteur in secteurs_a_afficher:
                row = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                sem_vals = [np.mean([row.get(f"{j}_{h}", 0.0) for j in jours_sem]) for h in range(24)]
                we_vals  = [np.mean([row.get(f"{j}_{h}", 0.0) for j in jours_we]) for h in range(24)]
                top_sem_h = sorted(enumerate(sem_vals), key=lambda x: x[1], reverse=True)[:3]
                top_we_h  = sorted(enumerate(we_vals), key=lambda x: x[1], reverse=True)[:3]
                top_data.append({
                    'Secteur': secteur,
                    'Semaine #1': f"{top_sem_h[0][0]}h ({top_sem_h[0][1]:.1f}%)",
                    'Semaine #2': f"{top_sem_h[1][0]}h ({top_sem_h[1][1]:.1f}%)",
                    'Semaine #3': f"{top_sem_h[2][0]}h ({top_sem_h[2][1]:.1f}%)",
                    'Week‑end #1': f"{top_we_h[0][0]}h ({top_we_h[0][1]:.1f}%)",
                    'Week‑end #2': f"{top_we_h[1][0]}h ({top_we_h[1][1]:.1f}%)",
                    'Week‑end #3': f"{top_we_h[2][0]}h ({top_we_h[2][1]:.1f}%)"
                })
            df_top = pd.DataFrame(top_data)
            st.subheader("Top 3 heures les plus chargées")
            st.dataframe(df_top, use_container_width=True)

    # --------------------------------------------------------
    # 2.5 – Couverture des plages horaires (semaine vs week‑end)
    # --------------------------------------------------------
    st.subheader("🕒 Couverture des plages horaires par type de jour")
    mag_gantt = st.selectbox("Magasin (couverture)", selected_mags, key="mag_gantt_3")
    if mag_gantt:
        sessions = df_c_f[df_c_f['lieu_officiel'] == mag_gantt].copy()
        if sessions.empty:
            st.info("Aucun comptage pour ce magasin.")
        else:
            def merge_intervals_minutes(intervals):
                if not intervals: return []
                intervals.sort()
                merged = []
                cur_s, cur_e = intervals[0]
                for s, e in intervals[1:]:
                    if s <= cur_e: cur_e = max(cur_e, e)
                    else:
                        merged.append((cur_s, cur_e))
                        cur_s, cur_e = s, e
                merged.append((cur_s, cur_e))
                return merged

            intervals_sem, intervals_we = [], []
            for _, row in sessions.iterrows():
                debut_min = row['debut_dt'].hour * 60 + row['debut_dt'].minute
                fin_min   = row['fin_dt'].hour * 60 + row['fin_dt'].minute
                if fin_min < debut_min: fin_min += 24*60
                if row['date_dt'].weekday() < 5:
                    intervals_sem.append((debut_min, fin_min))
                else:
                    intervals_we.append((debut_min, fin_min))

            merged_sem = merge_intervals_minutes(intervals_sem)
            merged_we  = merge_intervals_minutes(intervals_we)

            fig_cov = go.Figure()
            for start, end in merged_sem:
                fig_cov.add_shape(type="rect", x0=start/60, x1=end/60, y0=0.6, y1=1.0, yref="paper",
                                  fillcolor="DodgerBlue", opacity=0.7, line_width=0)
            for start, end in merged_we:
                fig_cov.add_shape(type="rect", x0=start/60, x1=end/60, y0=0.0, y1=0.4, yref="paper",
                                  fillcolor="orange", opacity=0.7, line_width=0)

            mag_row = df_sm[df_sm['Nom'] == mag_gantt]
            if not mag_row.empty:
                row_sm = mag_row.iloc[0]
                ouv_sem = get_opening_hours(row_sm, 'semaine')
                debut_sem = next((h for h, o in enumerate(ouv_sem) if o), 8)
                fin_sem   = next((h for h in range(23,-1,-1) if ouv_sem[h]), 18) + 1
                fig_cov.add_shape(type="rect", x0=debut_sem, x1=fin_sem, y0=0.6, y1=1.0, yref="paper",
                                  fillcolor="black", opacity=0.15, line_width=0, layer="below")
                ouv_we = get_opening_hours(row_sm, 'weekend')
                debut_we = next((h for h, o in enumerate(ouv_we) if o), 8)
                fin_we   = next((h for h in range(23,-1,-1) if ouv_we[h]), 18) + 1
                fig_cov.add_shape(type="rect", x0=debut_we, x1=fin_we, y0=0.0, y1=0.4, yref="paper",
                                  fillcolor="black", opacity=0.15, line_width=0, layer="below")

            fig_cov.add_trace(go.Scatter(x=[None], y=[None], mode='markers', marker=dict(color='DodgerBlue', size=10), name='Semaine'))
            fig_cov.add_trace(go.Scatter(x=[None], y=[None], mode='markers', marker=dict(color='orange', size=10), name='Week‑end'))

            fig_cov.update_layout(title=f"Plages horaires couvertes – {mag_gantt}",
                                  xaxis=dict(title="Heure de la journée", tickvals=list(range(0,24,2)),
                                             ticktext=[f"{h}h" for h in range(0,24,2)], range=[0,24]),
                                  yaxis=dict(visible=False), height=300, showlegend=True,
                                  template="gilroy_export")
            fig_cov = force_black_axes(fig_cov)
            st.plotly_chart(fig_cov, use_container_width=True, key="cov_hours")

            def compute_cov_hours(intervals):
                merged = merge_intervals_minutes(intervals)
                total_min = sum(e - s for s, e in merged)
                return total_min / 60.0

            h_sem = compute_cov_hours(intervals_sem)
            h_we  = compute_cov_hours(intervals_we)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Heures couvertes en semaine", f"{fmt_volume(h_sem)} h")
            with col2:
                st.metric("Heures couvertes le week‑end", f"{fmt_volume(h_we)} h")

    # --------------------------------------------------------
    # 2.6 – Contrôle de cohérence flux estimé vs réel
    # --------------------------------------------------------
    st.subheader("🔍 Contrôle de cohérence : flux estimé vs flux réel")
    mag_c = st.selectbox("Magasin pour cohérence", selected_mags, key="mag_coherence")
    if mag_c:
        data = all_k_data[mag_c]
        k_sem = data['k_sem']
        k_we  = data['k_we']
        details = data['details']
        if not details:
            st.info("Aucun comptage pour ce magasin.")
        else:
            points = []
            for d in details:
                date_obj = datetime.strptime(d['date'], '%Y-%m-%d')
                is_we = date_obj.weekday() >= 5
                k_util = k_we if is_we else k_sem
                if k_util is None: continue
                flux_pred = k_util * d['G_moy']
                points.append({'flux_réel': d['flux_reel'], 'flux_prédit': flux_pred, 'k': d['k'],
                               'date': d['date'], 'source': d['source']})
            if points:
                df_points = pd.DataFrame(points)
                fig_coher = px.scatter(df_points, x='flux_prédit', y='flux_réel',
                                       hover_data=['date', 'k', 'source'],
                                       title=f"Flux réel vs Flux prédit – {mag_c}")
                max_val = max(df_points['flux_prédit'].max(), df_points['flux_réel'].max())
                fig_coher.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], mode='lines',
                                               name='y=x', line=dict(dash='dash', color='black')))
                fig_coher.update_xaxes(title_text="Flux prédit (clients/h)", tickformat=",.0f")
                fig_coher.update_yaxes(title_text="Flux réel (clients/h)", tickformat=",.0f")
                fig_coher.update_layout(template="gilroy_export")
                fig_coher = force_black_axes(fig_coher)
                st.plotly_chart(fig_coher, use_container_width=True, key="coherence")
            else:
                st.info("Impossible de calculer les flux prédits (k manquant).")

    # --------------------------------------------------------
    # 2.6 bis – Détection des comptages aberrants
    # --------------------------------------------------------
    st.subheader("⚠️ Comptages aberrants (k extrêmes)")
    seuil_iqr = st.slider("Seuil (écarts interquartiles)", 1.5, 5.0, 3.0, 0.5, key="iqr_thresh")
    aberrants_list = []
    for mag in selected_mags:
        details = all_k_data[mag]['details']
        if len(details) < 3: continue
        k_vals = [d['k'] for d in details]
        Q1 = np.percentile(k_vals, 25)
        Q3 = np.percentile(k_vals, 75)
        IQR = Q3 - Q1
        for d in details:
            if d['k'] < Q1 - seuil_iqr * IQR or d['k'] > Q3 + seuil_iqr * IQR:
                aberrants_list.append({
                    'Magasin': mag, 'Date': d['date'], 'Type': d['type'],
                    'k': round(d['k'], 2), 'Flux réel': round(d['flux_reel'], 1),
                    'G_moy': round(d['G_moy'], 2), 'Source profil': d['source']
                })
    if aberrants_list:
        df_aberr = pd.DataFrame(aberrants_list)
        st.warning(f"{len(df_aberr)} comptage(s) aberrant(s) détecté(s).")
        st.dataframe(df_aberr, use_container_width=True)
    else:
        st.success("Aucun comptage aberrant détecté.")

    # --------------------------------------------------------
    # 2.7 – Estimation de la fréquentation totale par magasin et par segment
    # --------------------------------------------------------
    st.subheader("📊 Estimation de la fréquentation totale par magasin")

    mags_avec_k = [m for m in selected_mags if all_k_data[m]['k_sem'] is not None or all_k_data[m]['k_we'] is not None]
    if not mags_avec_k:
        st.info("Aucun magasin avec facteur k calculable (pas assez de comptages).")
    else:
        rows_estimation = []
        for mag in mags_avec_k:
            data = all_k_data[mag]
            k_sem = data['k_sem']
            k_we  = data['k_we']
            details = data['details']

            sem_k_vals = [d['k'] for d in details if d['type'] == 'semaine']
            we_k_vals  = [d['k'] for d in details if d['type'] == 'weekend']

            k_sem_med = np.median(sem_k_vals) if sem_k_vals else k_sem
            k_we_med  = np.median(we_k_vals) if we_k_vals else k_we
            k_sem_q1 = np.percentile(sem_k_vals, 25) if sem_k_vals else k_sem_med
            k_sem_q3 = np.percentile(sem_k_vals, 75) if sem_k_vals else k_sem_med
            k_we_q1  = np.percentile(we_k_vals, 25) if we_k_vals else k_we_med
            k_we_q3  = np.percentile(we_k_vals, 75) if we_k_vals else k_we_med

            profil_sem, _, _ = get_effective_profile(mag, 'Mo')
            profil_we, _, _  = get_effective_profile(mag, 'Sa')

            def clients_jour(k_s, k_w, profil):
                clients, _ = estimate_daily_flow_onglet(mag, 'Mo', k_s, k_w, profil)
                return sum(clients) if clients else 0

            sem_med = clients_jour(k_sem_med, k_we_med, profil_sem)
            sem_q1  = clients_jour(k_sem_q1, k_we_q1, profil_sem)
            sem_q3  = clients_jour(k_sem_q3, k_we_q3, profil_sem)
            delta_sem = round((sem_q3 - sem_q1) / 2)

            we_med = clients_jour(k_sem_med, k_we_med, profil_we)
            we_q1  = clients_jour(k_sem_q1, k_we_q1, profil_we)
            we_q3  = clients_jour(k_sem_q3, k_we_q3, profil_we)
            delta_we = round((we_q3 - we_q1) / 2)

            total_med = 5 * sem_med + 2 * we_med
            total_q1  = 5 * sem_q1 + 2 * we_q1
            total_q3  = 5 * sem_q3 + 2 * we_q3
            delta_total = round((total_q3 - total_q1) / 2)

            rows_estimation.append({
                'Magasin': mag,
                'Jour semaine': f"{fmt_volume(sem_med)} ± {fmt_volume(delta_sem)}",
                'Jour WE': f"{fmt_volume(we_med)} ± {fmt_volume(delta_we)}",
                'Total hebdo': f"{fmt_volume(total_med)} ± {fmt_volume(delta_total)}",
                'sem_med': sem_med,
                'we_med': we_med,
                'total_med': total_med
            })

        df_estim = pd.DataFrame(rows_estimation)
        st.dataframe(df_estim[['Magasin', 'Jour semaine', 'Jour WE', 'Total hebdo']], use_container_width=True)

        # --------------------------------------------------------
        # Agrégation par segment
        # --------------------------------------------------------
        st.subheader("📦 Fréquentation par segment (taille × niveau socio-économique)")

        df_sm_info = df_sm[['Nom', 'Taille', 'Niveau_socio']].copy()
        df_estim = df_estim.merge(df_sm_info, left_on='Magasin', right_on='Nom', how='left')
        df_estim['Segment'] = df_estim['Taille'].fillna('Inconnue') + ' / ' + df_estim['Niveau_socio'].fillna('Inconnu')

        segments = df_estim['Segment'].value_counts()
        segments_a_afficher = segments[segments > 0].index.tolist()

        if not segments_a_afficher:
            st.info("Aucune information de segment disponible.")
        else:
            agg_median = df_estim.groupby('Segment').agg(
                nb_magasins=('Magasin', 'count'),
                médiane_jour_sem=('sem_med', 'median'),
                iqr_jour_sem=('sem_med', lambda x: (np.percentile(x,75)-np.percentile(x,25))/2),
                médiane_jour_we=('we_med', 'median'),
                iqr_jour_we=('we_med', lambda x: (np.percentile(x,75)-np.percentile(x,25))/2),
                médiane_total=('total_med', 'median'),
                iqr_total=('total_med', lambda x: (np.percentile(x,75)-np.percentile(x,25))/2)
            ).reset_index()
            agg_median['Jour semaine'] = agg_median.apply(lambda r: f"{fmt_volume(r['médiane_jour_sem'])} ± {fmt_volume(r['iqr_jour_sem'])}", axis=1)
            agg_median['Jour WE'] = agg_median.apply(lambda r: f"{fmt_volume(r['médiane_jour_we'])} ± {fmt_volume(r['iqr_jour_we'])}", axis=1)
            agg_median['Total hebdo'] = agg_median.apply(lambda r: f"{fmt_volume(r['médiane_total'])} ± {fmt_volume(r['iqr_total'])}", axis=1)
            st.dataframe(agg_median[['Segment', 'nb_magasins', 'Jour semaine', 'Jour WE', 'Total hebdo']], use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                fig_box_sem = px.box(df_estim, x='Segment', y='sem_med',
                                     title="Clients estimés par jour de semaine", points="all")
                fig_box_sem.update_xaxes(tickangle=45)
                fig_box_sem.update_yaxes(tickformat=",.0f")
                fig_box_sem.update_layout(template="gilroy_export")
                fig_box_sem = force_black_axes(fig_box_sem)
                st.plotly_chart(fig_box_sem, use_container_width=True, key="box_sem")
            with col2:
                fig_box_we = px.box(df_estim, x='Segment', y='we_med',
                                    title="Clients estimés par jour de week-end", points="all")
                fig_box_we.update_xaxes(tickangle=45)
                fig_box_we.update_yaxes(tickformat=",.0f")
                fig_box_we.update_layout(template="gilroy_export")
                fig_box_we = force_black_axes(fig_box_we)
                st.plotly_chart(fig_box_we, use_container_width=True, key="box_we")

            fig_box_total = px.box(df_estim, x='Segment', y='total_med',
                                   title="Total hebdomadaire estimé par magasin", points="all")
            fig_box_total.update_xaxes(tickangle=45)
            fig_box_total.update_yaxes(tickformat=",.0f")
            fig_box_total.update_layout(template="gilroy_export")
            fig_box_total = force_black_axes(fig_box_total)
            st.plotly_chart(fig_box_total, use_container_width=True, key="box_total")

        # --- Stockage sécurisé pour l'export ---
        if 'df_estim' in locals():
            st.session_state['freq_magasin'] = df_estim[['Magasin', 'Jour semaine', 'Jour WE', 'Total hebdo']].copy()
        else:
            st.session_state['freq_magasin'] = None

        if 'agg_median' in locals():
            st.session_state['freq_segment'] = agg_median[['Segment', 'nb_magasins', 'Jour semaine', 'Jour WE', 'Total hebdo']].copy()
        else:
            st.session_state['freq_segment'] = None

    # --------------------------------------------------------
    # Diagramme en barres : fréquentation hebdomadaire par magasin (semaine / week‑end)
    # --------------------------------------------------------
    st.subheader("📊 Fréquentation hebdomadaire par magasin (tri décroissant)")

    # Préparation des données : tri par total hebdomadaire décroissant
    df_estim_sorted = df_estim.sort_values('total_med', ascending=False).copy()
    df_estim_sorted['Magasin_court'] = df_estim_sorted['Magasin'].apply(
        lambda x: x[:25] + '...' if len(x) > 25 else x
    )

    # Graphique en barres groupées : semaine et week‑end
    fig_freq_bars = go.Figure()
    fig_freq_bars.add_trace(go.Bar(
        x=df_estim_sorted['Magasin_court'],
        y=df_estim_sorted['sem_med'] * 5,   # 5 jours de semaine
        name='Clients semaine',
        marker_color='steelblue'
    ))
    fig_freq_bars.add_trace(go.Bar(
        x=df_estim_sorted['Magasin_court'],
        y=df_estim_sorted['we_med'] * 2,    # 2 jours de week‑end
        name='Clients week‑end',
        marker_color='darkorange'
    ))

    fig_freq_bars.update_layout(
        barmode='stack',                     # ou 'group' si vous préférez côte à côte
        xaxis_title='Magasin',
        yaxis_title='Clients estimés par semaine',
        title='Fréquentation hebdomadaire estimée par magasin (semaine + week‑end)',
        legend=dict(x=0.01, y=0.99),
        xaxis_tickangle=-45,
        height=500,
        template="gilroy_export"
    )
    fig_freq_bars = force_black_axes(fig_freq_bars)
    st.plotly_chart(fig_freq_bars, width='stretch')

# ------------------------------------------------------------
# ONGLET 5 : ESTIMATION DU MARCHÉ (version finale complète et corrigée)
# ------------------------------------------------------------
with tabs[5]:
    st.header("📊 Estimation du marché de l'huile de palme rouge à Kinshasa")

    # État de session pour ne calculer qu'à la demande
    if 'market_calculated' not in st.session_state:
        st.session_state.market_calculated = False

    if not st.session_state.market_calculated:
        st.info("ℹ️ Cliquez sur le bouton ci-dessous pour lancer l'estimation du marché (cela peut prendre 10 à 30 secondes).")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🚀 Lancer les calculs", key="run_market"):
                st.session_state.market_calculated = True
                st.rerun()
        with col2:
            if st.button("🔄 Recalculer (forcer)"):
                st.cache_data.clear()
                st.session_state.market_calculated = False
                st.rerun()
        st.stop()

    if df_sm.empty:
        st.error("Fichier supermarches.csv manquant.")
        st.stop()
    if not selected_mags:
        st.warning("Aucun magasin sélectionné dans l'onglet Accueil.")
        st.stop()

    # Initialisation des variables de synthèse (évite les NameError)
    total_med = None
    total_demi_iqr = None
    total_A_med = 0
    demi_iqr_total_A = 0
    vol_annuel_med_C = None
    demi_iqr_annuel_C = None

    # ─── Fonctions internes (profil, horaires, k, flux) ───────
    df_profils_pivot, _ = load_frequentation_data()
    secteur_profiles = None
    if not df_profils_pivot.empty:
        df_profils_pivot['magasin_norm'] = df_profils_pivot['magasin'].apply(normalize_name)
        df_sm_local = df_sm.copy()
        df_sm_local['nom_norm'] = df_sm_local['Nom'].apply(normalize_name)
        merged = df_profils_pivot.merge(df_sm_local[['nom_norm', 'Secteur']],
                                        left_on='magasin_norm', right_on='nom_norm', how='left')
        secteur_profiles_list = []
        for secteur in merged['Secteur'].dropna().unique():
            sub = merged[merged['Secteur'] == secteur]
            cols = [c for c in sub.columns if c not in ['magasin', 'magasin_norm', 'Secteur', 'nom_norm']]
            median_row = {'secteur': secteur}
            for c in cols:
                median_row[c] = sub[c].median()
            secteur_profiles_list.append(median_row)
        if secteur_profiles_list:
            secteur_profiles = pd.DataFrame(secteur_profiles_list)

    magasin_mapping = {}
    if os.path.exists("magasin_mapping.json"):
        with open("magasin_mapping.json", 'r') as f:
            magasin_mapping = json.load(f)

    def get_effective_profile(magasin, jour_code):
        nom_google = magasin_mapping.get(magasin)
        if nom_google and nom_google in df_profils_pivot['magasin'].values:
            row = df_profils_pivot[df_profils_pivot['magasin'] == nom_google].iloc[0]
            profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            if max(profil) > 0:
                return profil, "Google", nom_google
        secteur = df_sm[df_sm['Nom'] == magasin]['Secteur'].values
        if len(secteur) > 0 and secteur_profiles is not None:
            secteur = secteur[0]
            if secteur in secteur_profiles['secteur'].values:
                row_sect = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
                return profil, f"Secteur {secteur}", "Profil secteur"
        return [1.0]*24, "Uniforme", "Aucun"

    def get_opening_hours(row_sm, jour_type):
        if jour_type == 'semaine':
            ouverture = str(row_sm.get('ouv_sem', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_sem', '18:00')).strip()
        else:
            ouverture = str(row_sm.get('ouv_we', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_we', '18:00')).strip()
        def parse_horaire(h_str):
            h_str = h_str.upper().replace('H', ':00').replace(' ', '')
            try:
                t = datetime.strptime(h_str, '%H:%M')
                return t.hour, t.minute
            except:
                return 8, 0
        h_ouv, m_ouv = parse_horaire(ouverture)
        h_ferm, m_ferm = parse_horaire(fermeture)
        ouvert = [False]*24
        for h in range(24):
            if h > h_ouv and h < h_ferm:
                ouvert[h] = True
            elif h == h_ouv and m_ouv == 0:
                ouvert[h] = True
            elif h == h_ferm and m_ferm == 0:
                ouvert[h] = False
            elif h == h_ouv and m_ouv > 0:
                ouvert[h] = True
            elif h == h_ferm and m_ferm > 0:
                ouvert[h] = True
        return ouvert

    def compute_k_factors_marche(magasin):
        comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
        if comptages.empty:
            return None, None, []
        k_sem_list, k_we_list, details = [], [], []
        jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}
        for _, row in comptages.iterrows():
            date_obj = row['date_dt']
            jour_code = date_obj.strftime('%a')
            jour_code_google = jour_map.get(jour_code, jour_code)
            profil, source, _ = get_effective_profile(magasin, jour_code_google)
            debut, fin = row['debut_dt'], row['fin_dt']
            duree = (fin - debut).total_seconds() / 3600.0
            if duree <= 0: continue
            start_min = debut.hour * 60 + debut.minute
            end_min = fin.hour * 60 + fin.minute
            current = start_min
            G_moy = 0.0
            while current < end_min:
                h = current // 60
                next_min = min((h+1)*60, end_min)
                frac = (next_min - current) / 60.0
                G_moy += profil[h] * frac
                current = next_min
            G_moy = G_moy / duree if duree > 0 else 0
            if G_moy <= 0: continue
            flux_reel = row['total'] / duree
            k = flux_reel / G_moy
            is_we = date_obj.weekday() >= 5
            (k_we_list if is_we else k_sem_list).append(k)
            details.append({'k': k, 'type': 'weekend' if is_we else 'semaine'})
        k_sem = np.median(k_sem_list) if k_sem_list else None
        k_we  = np.median(k_we_list) if k_we_list else None
        if k_sem is None and k_we is not None: k_sem = k_we
        if k_we is None and k_sem is not None: k_we = k_sem
        return k_sem, k_we, details

    def estimate_daily_flow_marche(magasin, jour_code, k_sem, k_we, profil):
        is_we = jour_code in ['Sa', 'Su']
        k = k_we if is_we else k_sem
        if k is None: return [0]*24, 0
        sm_row = df_sm[df_sm['Nom'] == magasin]
        ouvert = [True]*24 if sm_row.empty else get_opening_hours(sm_row.iloc[0], 'semaine' if not is_we else 'weekend')
        clients = [int(round(k * profil[h])) if ouvert[h] else 0 for h in range(24)]
        return clients, sum(clients)

    def weekly_volume_from_k(magasin, k_sem, k_we):
        profil_sem, _, _ = get_effective_profile(magasin, 'Mo')
        profil_we, _, _  = get_effective_profile(magasin, 'Sa')
        clients_sem, _ = estimate_daily_flow_marche(magasin, 'Mo', k_sem, k_we, profil_sem)
        clients_we, _  = estimate_daily_flow_marche(magasin, 'Sa', k_sem, k_we, profil_we)
        return 5 * sum(clients_sem) + 2 * sum(clients_we)

    def bootstrap_magasin_weekly(magasin, n_boot=200):
        k_sem_list, k_we_list, details = compute_k_factors_marche(magasin)
        if not details:
            return None, None, None
        sem_vals = [d['k'] for d in details if d['type'] == 'semaine']
        we_vals  = [d['k'] for d in details if d['type'] == 'weekend']
        if not sem_vals and not we_vals:
            return None, None, None
        boot_volumes = []
        for _ in range(n_boot):
            ks = np.median(np.random.choice(sem_vals, size=len(sem_vals))) if sem_vals else None
            kw = np.median(np.random.choice(we_vals, size=len(we_vals))) if we_vals else None
            if ks is None and kw is not None: ks = kw
            if kw is None and ks is not None: kw = ks
            if ks is None or kw is None:
                continue
            vol = weekly_volume_from_k(magasin, ks, kw)
            boot_volumes.append(vol)
        if not boot_volumes:
            return None, None, None
        boot_volumes = np.array(boot_volumes)
        med = np.median(boot_volumes)
        q1 = np.percentile(boot_volumes, 25)
        q3 = np.percentile(boot_volumes, 75)
        return med, q1, q3

    # ─── 1. Calcul des métriques par magasin sélectionné ─────
    mag_data = {}
    for mag in selected_mags:
        k_sem, k_we, _ = compute_k_factors_marche(mag)
        has_k = k_sem is not None or k_we is not None
        total_hebdo_clients = None
        if has_k:
            total_hebdo_clients = weekly_volume_from_k(mag, k_sem, k_we)

        df_sm_q = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
        nb_total_q = len(df_sm_q[df_sm_q['statut'] != 'Refus']) if 'statut' in df_sm_q.columns else len(df_sm_q)
        acheteurs = df_sm_q[(df_sm_q['Q1'] == 'Oui') & (df_sm_q['statut'] != 'Refus')] if 'statut' in df_sm_q.columns else df_sm_q[df_sm_q['Q1'] == 'Oui']
        nb_acheteurs = len(acheteurs)
        has_q = nb_total_q > 0

        ti = nb_acheteurs / nb_total_q if has_q and nb_total_q > 0 else 0.0
        qi = acheteurs['vol_litres'].mean() if nb_acheteurs > 0 else 0.0
        Vh_huile_hebdo = total_hebdo_clients * ti * qi if (total_hebdo_clients is not None and ti is not None and qi is not None) else None

        # Bootstrap pour le volume clients hebdo (pour intervalle)
        vol_clients_med, vol_clients_q1, vol_clients_q3 = bootstrap_magasin_weekly(mag) if has_k else (None, None, None)
        vol_annuel_med = vol_clients_med * 52 * ti * qi if (vol_clients_med is not None and ti is not None and qi is not None) else None
        vol_annuel_q1 = vol_clients_q1 * 52 * ti * qi if (vol_clients_q1 is not None and ti is not None and qi is not None) else None
        vol_annuel_q3 = vol_clients_q3 * 52 * ti * qi if (vol_clients_q3 is not None and ti is not None and qi is not None) else None

        match = df_sm[df_sm['Nom'] == mag]
        taille = match.iloc[0]['Taille'] if not match.empty else '?'
        niveau = match.iloc[0]['Niveau_socio'] if not match.empty else '?'
        chaine = match.iloc[0].get('Chaine', '') if not match.empty else ''

        mag_data[mag] = {
            'has_k': has_k, 'nb_total_q': nb_total_q,
            'nb_acheteurs': nb_acheteurs, 'ti': ti, 'qi': qi,
            'Vh_huile_hebdo': Vh_huile_hebdo,
            'vol_clients_med': vol_clients_med,
            'vol_clients_q1': vol_clients_q1,
            'vol_clients_q3': vol_clients_q3,
            'vol_annuel_med': vol_annuel_med,
            'vol_annuel_q1': vol_annuel_q1,
            'vol_annuel_q3': vol_annuel_q3,
            'taille': taille, 'niveau': niveau, 'chaine': chaine
        }

    # ─── Diagnostic ──────────────────────────────────────────
    with st.expander("🔍 Critères de magasin enquêté (diagnostic)", expanded=True):
        diag_rows = []
        for mag in selected_mags:
            data = mag_data.get(mag, {})
            has_k = data.get('has_k', False)
            has_q = data.get('nb_total_q', 0) > 0
            can_estimate = data.get('Vh_huile_hebdo') is not None
            diag_rows.append({
                'Magasin': mag,
                'Comptages': 'Oui' if has_k else 'Non',
                'Questionnaires SM': 'Oui' if has_q else 'Non',
                'Volume huile estimable': 'Oui' if can_estimate else 'Non'
            })
        df_diag = pd.DataFrame(diag_rows)
        st.dataframe(df_diag, use_container_width=True)
        nb_est = df_diag[df_diag['Volume huile estimable'] == 'Oui'].shape[0]
        nb_q = df_diag[df_diag['Questionnaires SM'] == 'Oui'].shape[0]
        st.caption(
            f"{nb_q} magasin(s) avec questionnaires SM, "
            f"{nb_est} magasin(s) avec volume huile estimable (y compris volume nul)."
        )

    # ─── 2. Méthode A – Strates ─────────────────────────────
    st.subheader("1. Méthode A – Strates (taille × niveau socio-économique)")

    df_strates = df_sm.groupby(['Taille', 'Niveau_socio']).agg(
        N_s=('Nom', 'count'),
        magasins_liste=('Nom', lambda x: list(x))
    ).reset_index()
    df_strates['Strate'] = df_strates['Taille'] + ' / ' + df_strates['Niveau_socio']

    strate_enquete = {}
    for mag, data in mag_data.items():
        if data['Vh_huile_hebdo'] is not None:   # inclut Vh = 0
            key = (data['taille'], data['niveau'])
            strate_enquete.setdefault(key, []).append(data['Vh_huile_hebdo'])

    rows_strates = []
    total_A_med = 0
    total_A_borne_inf = 0
    total_A_borne_sup = 0
    for _, row in df_strates.iterrows():
        taille = row['Taille']
        niveau = row['Niveau_socio']
        strate_name = row['Strate']
        N_s = row['N_s']
        key = (taille, niveau)
        Vh_list = strate_enquete.get(key, [])
        n_s = len(Vh_list)
        if n_s > 0:
            med = np.median(Vh_list)
            q1 = np.percentile(Vh_list, 25)
            q3 = np.percentile(Vh_list, 75)
            vol_annuel_med = med * N_s * 52
            vol_annuel_q1  = q1 * N_s * 52
            vol_annuel_q3  = q3 * N_s * 52
            demi_iqr = (vol_annuel_q3 - vol_annuel_q1) / 2
            vol_str = f"{fmt_volume(vol_annuel_med)} L ± {fmt_volume(demi_iqr)} L"
            total_A_med += vol_annuel_med
            total_A_borne_inf += vol_annuel_q1
            total_A_borne_sup += vol_annuel_q3
        else:
            vol_str = "Non estimable"
        rows_strates.append({
            'Strate': strate_name,
            'Nb total magasins': N_s,
            'Nb enquêtés': n_s,
            'Volume annuel estimé': vol_str,
        })

    df_aff_strates = pd.DataFrame(rows_strates)
    st.dataframe(df_aff_strates, use_container_width=True)
    # Stockage pour l'export
    st.session_state['strates_A'] = df_aff_strates.copy()
    demi_iqr_total_A = (total_A_borne_sup - total_A_borne_inf) / 2 if total_A_borne_sup > 0 else 0
    st.metric("Marché total (Méthode A)", f"{fmt_volume(total_A_med)} L ± {fmt_volume(demi_iqr_total_A)} L")

    # ─── 3. Méthode B – Approche démographique (refondue, bootstrap) ──
    st.subheader("2. Méthode B – Approche démographique")

    # Mapping des fréquences corrigé
    freq_map = {
        'Plusieurs fois par semaine': 8,
        'Une fois par semaine': 4,
        'Deux à trois fois par mois': 2.5,
        'Une fois par mois': 1,
        'Une fois par trimestre': 0.33,
        'Moins souvent': 1/6
    }

    if 'df_q_f_raw' not in dir() or df_q_f_raw.empty:
        st.warning("Données brutes des questionnaires non chargées.")
    else:
        # Extraction des données pour les trois types
        df_source_b = df_q_f_raw[df_q_f_raw['type'].isin(['menage', 'supermarche_menage', 'supermarche'])].copy()
        rows = []
        for _, row in df_source_b.iterrows():
            qtype = row['type']
            data = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
            if qtype == 'menage':
                nb_pers = data.get('Q1_NbPersonnes')
                freq = data.get('Q3_Frequence')
                qte_nb = data.get('Q4_Quantite_Nombre')
                vol_unit = data.get('Q4_Quantite_VolumeUnitaire')
                pourcent = data.get('Q6_Pourcentages')
                commune = data.get('Commune')
                supermarche_origine = None
            elif qtype == 'supermarche_menage':
                nb_pers = data.get('Q2_NbPersonnes')
                freq = data.get('Q4_Frequence')
                qte_nb = data.get('Q5_Quantite_Nombre')
                vol_unit = data.get('Q5_Quantite_VolumeUnitaire')
                pourcent = data.get('Q7_Pourcentages')
                commune = data.get('Commune')
                supermarche_origine = data.get("Supermarché d'origine")
            else:  # supermarche (acheteur)
                nb_pers = data.get('Q7_NbPersonnes')
                freq = data.get('Q6_Fréquence')
                vol_texte = data.get('Q4_Quantité')
                qte_nb = None
                vol_unit = None
                vol_total_sm = extraire_litres(vol_texte) if vol_texte else None
                pourcent = data.get('Q8_LieuxAchat')
                commune = data.get('Commune')
                supermarche_origine = data.get('Supermarché')

            rows.append({
                'type': qtype,
                'nb_personnes': nb_pers,
                'frequence': freq,
                'quantite_nombre': qte_nb,
                'volume_unitaire_l': vol_unit,
                'volume_total_l_sm': vol_total_sm if qtype == 'supermarche' else None,
                'pourcentages_achat': pourcent,
                'commune': commune,
                'supermarche_origine': supermarche_origine
            })
        df_men_b = pd.DataFrame(rows)

        # Exclure les refus (si la colonne existe)
        if 'statut' in df_men_b.columns:
            df_men_b = df_men_b[df_men_b['statut'] != 'Refus'].copy()

        if df_men_b.empty:
            st.info("Aucun questionnaire exploitable pour la Méthode B.")
        else:
            # Conversion des nombres
            df_men_b['quantite_nombre'] = pd.to_numeric(
                df_men_b['quantite_nombre'].astype(str).str.replace(',', '.'), errors='coerce')
            df_men_b['quantite_nombre'] = df_men_b['quantite_nombre'].replace(0, 1)
            df_men_b['volume_unitaire_l'] = pd.to_numeric(
                df_men_b['volume_unitaire_l'].astype(str).str.replace(',', '.'), errors='coerce')
            mask_ml = df_men_b['volume_unitaire_l'] > 50
            if mask_ml.any():
                df_men_b.loc[mask_ml, 'volume_unitaire_l'] = df_men_b.loc[mask_ml, 'volume_unitaire_l'] / 1000

            # Volume total pour ménage et supermarche_menage
            mask_calc = df_men_b['type'].isin(['menage', 'supermarche_menage'])
            df_men_b['volume_total_l'] = np.nan
            if mask_calc.any():
                df_men_b.loc[mask_calc, 'volume_total_l'] = (
                    df_men_b.loc[mask_calc, 'quantite_nombre'] * df_men_b.loc[mask_calc, 'volume_unitaire_l']
                )
            mask_sm = df_men_b['type'] == 'supermarche'
            df_men_b.loc[mask_sm, 'volume_total_l'] = df_men_b.loc[mask_sm, 'volume_total_l_sm']

            df_men_b['taille_menage'] = pd.to_numeric(df_men_b['nb_personnes'], errors='coerce')

            # Fréquence - nettoyage strict + mapping corrigé
            df_men_b['frequence'] = df_men_b['frequence'].astype(str).str.strip().replace(['', 'nan', 'None', 'none'], np.nan)
            frequences_autorisees = list(freq_map.keys())
            df_men_b.loc[~df_men_b['frequence'].isin(frequences_autorisees), 'frequence'] = np.nan
            df_men_b['freq_num'] = df_men_b['frequence'].map(freq_map)

            # Part supermarché (L_i)
            def extract_pct_supermarche(texte):
                if not isinstance(texte, str):
                    return np.nan
                match = re.search(r'Supermarché.*?(\d+(?:\.\d+)?)\s*%', texte, re.IGNORECASE)
                if match:
                    return float(match.group(1)) / 100.0
                return np.nan
            df_men_b['L'] = df_men_b['pourcentages_achat'].apply(extract_pct_supermarche)

            # Zone socioéconomique
            if not df_sm.empty:
                sm_niveau = dict(zip(df_sm['Nom'].apply(normalize_name), df_sm['Niveau_socio']))
            else:
                sm_niveau = {}
            def attribuer_zone(row):
                if row['type'] in ['supermarche', 'supermarche_menage']:
                    origine = row['supermarche_origine']
                    if not isinstance(origine, str) or origine.strip() == '':
                        return 'Inconnu'
                    key = normalize_name(origine)
                    if key in sm_niveau and sm_niveau[key] and sm_niveau[key] != 'Non renseigné':
                        return sm_niveau[key]
                    best_score, best_val = 0, None
                    for k, v in sm_niveau.items():
                        score = SequenceMatcher(None, key, k).ratio()
                        if score > best_score and score >= 0.8:
                            best_score, best_val = score, v
                    return best_val if best_val else 'Inconnu'
                else:  # menage
                    commune = row['commune']
                    if not isinstance(commune, str) or commune.strip() == '':
                        return 'Inconnu'
                    commune_niveau = load_commune_niveau()
                    commune_niveau_norm = {normalize_name(k): v for k, v in commune_niveau.items()}
                    return commune_niveau_norm.get(normalize_name(commune), 'Non classé')
            df_men_b['zone_socioeco'] = df_men_b.apply(attribuer_zone, axis=1)

            # Filtres de validité (exige L renseigné pour β)
            valide = (
                df_men_b['taille_menage'].notna() & (df_men_b['taille_menage'] > 0) & (df_men_b['taille_menage'] <= 20) &
                df_men_b['volume_total_l'].notna() & (df_men_b['volume_total_l'] > 0) &
                df_men_b['freq_num'].notna() &
                df_men_b['L'].notna()
            )
            df_valide = df_men_b[valide].copy()

            # --- Filtrage des consommations individuelles aberrantes ---
            df_valide['conso_indiv_annuelle'] = (
                12 * df_valide['freq_num'] * df_valide['volume_total_l'] / df_valide['taille_menage']
            )
            seuil_conso = 100  # L/personne/an
            nb_avant = len(df_valide)
            df_valide = df_valide[df_valide['conso_indiv_annuelle'] <= seuil_conso]
            nb_exclus_conso = nb_avant - len(df_valide)

            if nb_exclus_conso > 0:
                st.warning(
                    f"⚠️ {nb_exclus_conso} questionnaires exclus car leur consommation annuelle "
                    f"par personne dépasse {seuil_conso} L (valeur aberrante)."
                )

            # --- Expander de diagnostic des données de la Méthode B ---
            with st.expander("🔬 Diagnostiquer les données de la Méthode B (échantillon)"):
                if not df_valide.empty:
                    # Création d'une copie avec les colonnes utiles
                    df_diag_b = df_valide[['type', 'taille_menage', 'freq_num', 'volume_total_l', 'L', 'zone_socioeco']].copy()
                    df_diag_b['conso_indiv_annuelle'] = (12 * df_diag_b['freq_num'] * df_diag_b['volume_total_l'] / df_diag_b['taille_menage']).round(2)
                    df_diag_b['fi_x_qi'] = (df_diag_b['freq_num'] * df_diag_b['volume_total_l']).round(2)
                    
                    st.write("**Aperçu de 30 questionnaires aléatoires utilisés dans le calcul**")
                    st.dataframe(df_diag_b.sample(min(30, len(df_diag_b)), random_state=42), use_container_width=True)
                    st.caption("`fi_x_qi` = fréquence × volume acheté ; `conso_indiv_annuelle` = consommation annuelle par personne (L/an).")
                    st.write("**Statistiques globales par strate**")
                    for niveau in ['Aisé', 'Moyen', 'Populaire']:
                        sub = df_diag_b[df_diag_b['zone_socioeco'] == niveau]
                        if not sub.empty:
                            st.write(f"**Strate {niveau}** – {len(sub)} questionnaires")
                            st.write(sub[['taille_menage', 'freq_num', 'volume_total_l', 'fi_x_qi', 'conso_indiv_annuelle']].describe())
                else:
                    st.warning("Aucune donnée valide.")

            if df_valide.empty:
                st.warning("Aucun questionnaire valide après filtres.")
            else:
                # Pop
                st.markdown("**Populations de référence et incertitude**")
                col_pop1, col_pop2, col_pop3 = st.columns(3)
                with col_pop1:
                    st.caption("Aisée")
                    pop_aisée_min = st.number_input("Min", value=830000, step=5000, key="pop_aisée_min")
                    pop_aisée_max = st.number_input("Max", value=1020000, step=5000, key="pop_aisée_max")
                with col_pop2:
                    st.caption("Moyenne")
                    pop_moyenne_min = st.number_input("Min", value=3330000, step=10000, key="pop_moy_min")
                    pop_moyenne_max = st.number_input("Max", value=4070000, step=10000, key="pop_moy_max")
                with col_pop3:
                    st.caption("Populaire")
                    pop_populaire_min = st.number_input("Min", value=12500000, step=50000, key="pop_pop_min")
                    pop_populaire_max = st.number_input("Max", value=15250000, step=50000, key="pop_pop_max")

                pop_bounds = {
                    'Aisé':      (pop_aisée_min, pop_aisée_max),
                    'Moyen':     (pop_moyenne_min, pop_moyenne_max),
                    'Populaire': (pop_populaire_min, pop_populaire_max)
                }

                niveaux = ['Aisé', 'Moyen', 'Populaire']
                results = []
                for niveau in niveaux:
                    sub = df_valide[df_valide['zone_socioeco'] == niveau]
                    if sub.empty:
                        continue
                    f = sub['freq_num'].values
                    q = sub['volume_total_l'].values
                    t = sub['taille_menage'].values
                    L = sub['L'].values
                    n = len(sub)

                    def calc_V(f, q, t, L, pop):
                        S_fq = np.sum(f * q)
                        S_t = np.sum(t)
                        S_fqL = np.sum(f * q * L)
                        if S_fq == 0 or S_t == 0:
                            return np.nan
                        qpers = 12 * S_fq / S_t
                        beta = S_fqL / S_fq
                        return pop * beta * qpers

                    pop_min, pop_max = pop_bounds[niveau]
                    B = 2000
                    V_boot = []
                    for _ in range(B):
                        idx = np.random.choice(n, size=n, replace=True)
                        # Tirage aléatoire uniforme de la population entre min et max
                        pop_sample = np.random.uniform(pop_min, pop_max)
                        V_boot.append(calc_V(f[idx], q[idx], t[idx], L[idx], pop_sample))
                    V_boot = np.array(V_boot)
                    V_boot = V_boot[~np.isnan(V_boot)]
                    if len(V_boot) == 0:
                        continue
                    med = np.median(V_boot)
                    q1 = np.percentile(V_boot, 25)
                    q3 = np.percentile(V_boot, 75)
                    demi_iqr = (q3 - q1) / 2

                    # Pour affichage, recalcul sur l'échantillon complet
                    S_fq = np.sum(f * q)
                    S_t = np.sum(t)
                    S_fqL = np.sum(f * q * L)
                    qpers = 12 * S_fq / S_t if S_t > 0 else 0
                    beta = S_fqL / S_fq if S_fq > 0 else 0

                    results.append({
                        'Niveau': niveau,
                        'Population': f"{fmt_volume(pop_min)} – {fmt_volume(pop_max)}",
                        'Questionnaires valides': n,
                        'qpers (L/pers/an)': fmt_nombre(qpers, 2),
                        'β (%)': f"{beta*100:.1f}%",
                        'Volume SM annuel': f"{fmt_volume(med)} L ± {fmt_volume(demi_iqr)} L",
                        '_vol_med': med,
                        '_demi_iqr': demi_iqr
                    })

                if results:
                    df_b = pd.DataFrame(results)
                    st.dataframe(df_b[['Niveau', 'Population', 'Questionnaires valides',
                                       'qpers (L/pers/an)', 'β (%)', 'Volume SM annuel']],
                                 use_container_width=True)
                    total_med = sum(r['_vol_med'] for r in results)
                    total_demi_iqr = np.sqrt(sum(r['_demi_iqr']**2 for r in results))
                    st.metric("Marché total estimé (Méthode B)",
                              f"{fmt_volume(total_med)} L ± {fmt_volume(total_demi_iqr)} L")
                else:
                    st.info("Aucune donnée exploitable pour les strates sélectionnées.")

    # ─── 4. Méthode C – Extrapolation directe ──────────────────
    st.subheader("3. Méthode C – Extrapolation directe (non stratifiée)")
    mags_avec_vh = [mag for mag, data in mag_data.items() if data['Vh_huile_hebdo'] is not None]
    if not mags_avec_vh:
        st.warning("Aucun magasin avec volume huile estimable.")
    else:
        vh_values = np.array([mag_data[m]['Vh_huile_hebdo'] for m in mags_avec_vh])
        n_surveyed = len(vh_values)
        price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
        total_mags_oil = df_sm[(df_sm[price_cols] > 0).any(axis=1)].shape[0] if price_cols else len(df_sm)

        n_boot = 200
        boot_totals = []
        for _ in range(n_boot):
            boot_sample = np.random.choice(vh_values, size=n_surveyed, replace=True)
            total_hebdo_sample = np.sum(boot_sample)
            boot_totals.append(total_hebdo_sample * (total_mags_oil / n_surveyed))
        boot_totals = np.array(boot_totals)
        med_total_hebdo = np.median(boot_totals)
        q1 = np.percentile(boot_totals, 25)
        q3 = np.percentile(boot_totals, 75)
        demi_iqr_hebdo = (q3 - q1) / 2

        vol_annuel_med_C = med_total_hebdo * 52
        vol_annuel_q1 = q1 * 52
        vol_annuel_q3 = q3 * 52
        demi_iqr_annuel_C = (vol_annuel_q3 - vol_annuel_q1) / 2

        st.markdown(f"""
        - Magasins enquêtés avec volume huile : {n_surveyed} / {len(selected_mags)} sélectionnés
        - Total magasins vendant de l'huile (fichier) : {total_mags_oil}
        - Extrapolation : volume total = somme des volumes enquêtés × ({total_mags_oil} / {n_surveyed})
        """)
        st.metric("Marché total (Méthode C)",
                  f"{fmt_volume(vol_annuel_med_C)} L ± {fmt_volume(demi_iqr_annuel_C)} L")

    # ─── 5. Volumes estimés par magasin, chaîne et marque ────
    st.subheader("4. Volumes estimés par magasin, chaîne et marque")

    rows_mag_detail = []
    for mag in selected_mags:
        data = mag_data.get(mag, {})
        has_k = data.get('has_k', False)
        nb_q = data.get('nb_total_q', 0)
        ti = data.get('ti')
        qi = data.get('qi')
        Vh = data.get('Vh_huile_hebdo')
        vol_med = data.get('vol_annuel_med')
        vol_q1 = data.get('vol_annuel_q1')
        vol_q3 = data.get('vol_annuel_q3')
        chaine = data.get('chaine', '')

        if vol_med is not None and vol_q1 is not None and vol_q3 is not None:
            demi = (vol_q3 - vol_q1) / 2
            vol_annuel_str = f"{fmt_volume(vol_med)} L ± {fmt_volume(demi)} L"
        else:
            vol_annuel_str = "N/A"

        Vh_str = f"{fmt_volume(Vh)} L" if Vh is not None else "N/A"

        rows_mag_detail.append({
            'Magasin': mag,
            'Chaîne': chaine,
            'Comptages': 'Oui' if has_k else 'Non',
            'Q. SM': nb_q,
            'Taux achat': f"{ti*100:.1f}%" if ti is not None else "N/A",
            'Panier moy.': f"{fmt_nombre(qi,2)} L" if qi is not None else "N/A",
            'Volume huile / sem.': Vh_str,
            'Volume annuel estimé': vol_annuel_str,
        })

    df_mag_detail = pd.DataFrame(rows_mag_detail)
    st.dataframe(df_mag_detail, use_container_width=True)

    # --- Stockage sécurisé pour l'export ---
    # Vérifier que les DataFrames existent avant de les sauvegarder
    if 'df_aff_strates' in locals():
        st.session_state['strates_A'] = df_aff_strates.copy()
    else:
        st.session_state['strates_A'] = None

    if 'df_mag_detail' in locals():
        st.session_state['magasins_volumes'] = df_mag_detail.copy()
    else:
        st.session_state['magasins_volumes'] = None

    st.subheader("Par chaîne de magasins")
    chaine_data = {}
    for mag, data in mag_data.items():
        ch = data.get('chaine', '') or 'Indépendant'
        if data.get('vol_annuel_med') is not None:
            chaine_data.setdefault(ch, []).append(data['vol_annuel_med'])
    chaine_rows = []
    for ch, vals in chaine_data.items():
        med = np.median(vals)
        q1 = np.percentile(vals, 25)
        q3 = np.percentile(vals, 75)
        demi = (q3 - q1) / 2
        chaine_rows.append({
            'Chaîne': ch,
            'Nb magasins': len(vals),
            'Volume annuel médian': f"{fmt_volume(med)} L ± {fmt_volume(demi)} L"
        })
    if chaine_rows:
        df_chaine = pd.DataFrame(chaine_rows)
        st.dataframe(df_chaine, use_container_width=True)
    else:
        st.info("Aucune donnée.")

    # Volumes par marque (basé sur la Méthode A)
    if not df_supermarche.empty and total_A_med > 0:
        acheteurs = df_supermarche[df_supermarche['Q1'] == 'Oui']
        if not acheteurs.empty:
            marque_counts = acheteurs['marque_clean'].value_counts().reset_index()
            marque_counts.columns = ['Marque', 'Nombre d\'acheteurs']
            total_acheteurs = marque_counts['Nombre d\'acheteurs'].sum()
            marque_counts['Part de marché (%)'] = (marque_counts['Nombre d\'acheteurs'] / total_acheteurs * 100).round(1)
            marque_counts['Volume annuel estimé'] = (marque_counts['Part de marché (%)'] / 100) * total_A_med
            st.subheader("Estimation des volumes par marque (basée sur la méthode A)")
            marque_display = marque_counts.copy()
            marque_display['Part de marché (%)'] = marque_display['Part de marché (%)'].apply(lambda x: f"{x:.1f} %")
            marque_display['Volume annuel estimé'] = marque_display['Volume annuel estimé'].apply(fmt_volume) + ' L'
            st.dataframe(marque_display[['Marque', 'Nombre d\'acheteurs', 'Part de marché (%)', 'Volume annuel estimé']],
                         use_container_width=True)
            fig_marque = px.pie(marque_counts, values='Volume annuel estimé', names='Marque',
                                title="Répartition du marché par marque (volume)")
            fig_marque.update_layout(template="gilroy_export")
            fig_marque = force_black_axes(fig_marque)
            st.plotly_chart(fig_marque, use_container_width=True)
        else:
            st.info("Aucun acheteur dans les questionnaires supermarché.")
    else:
        st.info("Données insuffisantes pour les volumes par marque.")

    # ─── Stockage pour le rapport de synthèse ─────────────────
    st.session_state['total_A_med'] = total_A_med
    st.session_state['demi_iqr_total_A'] = demi_iqr_total_A
    st.session_state['total_med_B'] = total_med if total_med is not None else None
    st.session_state['total_demi_iqr_B'] = total_demi_iqr if total_demi_iqr is not None else None
    st.session_state['vol_annuel_med_C'] = vol_annuel_med_C if vol_annuel_med_C is not None else None
    st.session_state['demi_iqr_annuel_C'] = demi_iqr_annuel_C if demi_iqr_annuel_C is not None else None

    # ─── 6. Synthèse comparative ─────────────────────────────
    st.subheader("5. Synthèse comparative")
    colA, colB, colC = st.columns(3)
    with colA:
        st.metric("Méthode A (strates)", f"{fmt_volume(total_A_med)} L ± {fmt_volume(demi_iqr_total_A)} L")
    with colB:
        if total_med is not None and total_demi_iqr is not None:
            st.metric("Méthode B (démo)", f"{fmt_volume(total_med)} L ± {fmt_volume(total_demi_iqr)} L")
        else:
            st.metric("Méthode B", "N/A")
    with colC:
        if vol_annuel_med_C is not None and demi_iqr_annuel_C is not None:
            st.metric("Méthode C (directe)", f"{fmt_volume(vol_annuel_med_C)} L ± {fmt_volume(demi_iqr_annuel_C)} L")
        else:
            st.metric("Méthode C", "N/A")

# ------------------------------------------------------------
# ONGLET 6 : PRIX & CONCURRENCE (version finale avec formatage et taux global)
# ------------------------------------------------------------
with tabs[6]:
    st.header("🏷️ Analyse des prix et concurrence")

    # Récupération des paramètres globaux de devise
    devise = st.session_state.get("devise_globale", "FC")
    taux = st.session_state.get("taux_change", 2800)

    # Filtrage des prix externes selon les magasins sélectionnés
    prix_ext = df_prices_ext.copy()
    if not prix_ext.empty and selected_mags:
        selected_norm = {normalize_name(m): m for m in selected_mags}
        prix_ext['supermarche_norm'] = prix_ext['supermarche'].apply(normalize_name)
        magasin_mapping_prix = {}
        for sm_norm, sm_orig in selected_norm.items():
            magasin_mapping_prix[sm_norm] = sm_orig
        all_norm = prix_ext['supermarche_norm'].unique()
        for norm in all_norm:
            if norm not in magasin_mapping_prix:
                best_score = 0
                best_match = None
                for sel_norm, sel_orig in selected_norm.items():
                    score = SequenceMatcher(None, norm, sel_norm).ratio()
                    if score > best_score and score >= 0.8:
                        best_score = score
                        best_match = sel_orig
                if best_match:
                    magasin_mapping_prix[norm] = best_match
        prix_ext = prix_ext[prix_ext['supermarche_norm'].isin(magasin_mapping_prix.keys())]

    # Nettoyage des marques
    if not prix_ext.empty:
        prix_ext['marque_officielle'] = apply_brand_mapping_strict(prix_ext['marque'])
        prix_ext = prix_ext.dropna(subset=['marque_officielle'])
        prix_ext['volume_L'] = prix_ext['conditionnement'].apply(extraire_litres)
        prix_ext = prix_ext.dropna(subset=['volume_L'])
        prix_ext['prix_unitaire_FC'] = prix_ext['prix'] / prix_ext['volume_L']
        prix_ext['prix_unitaire_conv'] = prix_ext['prix_unitaire_FC'].apply(
            lambda x: convertir_prix(x, devise, taux)
        )

   # -------------------------------------------------------------
    # 1. Tableau des marques : présence et part de marché
    #    (inclut toutes les marques, même celles uniquement relevées en prix)
    # -------------------------------------------------------------
    st.subheader("📊 Marques : présence et part de marché (enquête supermarché)")

    # --- Marques officielles définies globalement (mapping + prix externes) ---
    official_brands = get_official_brands()   # retourne un set de marques normalisées

    # --- Marques issues des prix externes ---
    marques_prix = pd.DataFrame()
    if not prix_ext.empty:
        marques_prix = prix_ext.groupby('marque_officielle')['supermarche_norm'].apply(set).reset_index()
        marques_prix.columns = ['Marque', 'magasins_prix']
        marques_prix['nb_points_vente_prix'] = marques_prix['magasins_prix'].apply(len)
    else:
        marques_prix = pd.DataFrame(columns=['Marque', 'magasins_prix', 'nb_points_vente_prix'])

    # --- Marques issues des acheteurs (questionnaires) ---
    acheteurs_sm = df_supermarche[df_supermarche['Q1'] == 'Oui'].copy()
    acheteurs_sm = acheteurs_sm.dropna(subset=['marque_clean'])

    marques_achat = pd.DataFrame()
    if not acheteurs_sm.empty:
        pts_vente_achat = acheteurs_sm.groupby('marque_clean')['magasin_officiel'].apply(set).reset_index()
        pts_vente_achat.columns = ['Marque', 'magasins_achat']
        pts_vente_achat['nb_points_vente_achat'] = pts_vente_achat['magasins_achat'].apply(len)
        nb_ach = acheteurs_sm['marque_clean'].value_counts().reset_index()
        nb_ach.columns = ['Marque', 'Nombre d\'acheteurs']
        marques_achat = pts_vente_achat.merge(nb_ach, on='Marque', how='left').fillna(0)
        marques_achat['Nombre d\'acheteurs'] = marques_achat['Nombre d\'acheteurs'].astype(int)
    else:
        marques_achat = pd.DataFrame(columns=['Marque', 'magasins_achat', 'nb_points_vente_achat', 'Nombre d\'acheteurs'])

    # --- Base de toutes les marques à afficher ---
    toutes_marques = pd.DataFrame({'Marque': list(official_brands)})

    # --- Fusion des deux sources ---
    tab_marques = toutes_marques.merge(
        marques_prix[['Marque', 'magasins_prix', 'nb_points_vente_prix']],
        on='Marque', how='left'
    ).merge(
        marques_achat[['Marque', 'magasins_achat', 'nb_points_vente_achat', 'Nombre d\'acheteurs']],
        on='Marque', how='left'
    )

    # Remplacement des NaN par des sets vides pour l'union
    tab_marques['magasins_prix'] = tab_marques['magasins_prix'].apply(lambda x: x if isinstance(x, set) else set())
    tab_marques['magasins_achat'] = tab_marques['magasins_achat'].apply(lambda x: x if isinstance(x, set) else set())

    # Nombre de points de vente total = union des deux sources
    tab_marques['Points de vente'] = tab_marques.apply(
        lambda row: len(row['magasins_prix'] | row['magasins_achat']),
        axis=1
    )
    tab_marques['Points de vente'] = tab_marques['Points de vente'].astype(int)

    # Nombre d'acheteurs et part de marché
    tab_marques['Nombre d\'acheteurs'] = tab_marques['Nombre d\'acheteurs'].fillna(0).astype(int)
    total_acheteurs = tab_marques['Nombre d\'acheteurs'].sum()
    if total_acheteurs > 0:
        tab_marques['Part de marché (%)'] = tab_marques['Nombre d\'acheteurs'].apply(
            lambda x: round(x / total_acheteurs * 100, 1) if x > 0 else None
        )
    else:
        tab_marques['Part de marché (%)'] = None

    # Préparation de l'affichage
    tab_marques_display = tab_marques[['Marque', 'Points de vente', 'Nombre d\'acheteurs', 'Part de marché (%)']].copy()
    tab_marques_display['Part de marché (%)'] = tab_marques_display['Part de marché (%)'].apply(
        lambda x: f"{x:.1f} %" if pd.notna(x) else "N/A"
    )

    # Tri : les marques avec part de marché connue d'abord (décroissant), puis les autres par points de vente décroissant
    tab_marques_display['_sort_pdm'] = tab_marques['Part de marché (%)'].fillna(-1)
    tab_marques_display = tab_marques_display.sort_values(['_sort_pdm', 'Points de vente'], ascending=[False, False])
    tab_marques_display = tab_marques_display.drop(columns=['_sort_pdm'])

    st.dataframe(tab_marques_display, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------
    # 1bis. Graphique des parts de marché des 10 premières marques
    # -------------------------------------------------------------
    st.subheader("📊 Parts de marché des 10 premières marques")

    if not tab_marques.empty:
        # Classement par part de marché décroissante
        top10 = tab_marques.nlargest(10, 'Part de marché (%)').copy()
        # Calcul de la part de marché résiduelle (Autres)
        pdm_autres = 100.0 - top10['Part de marché (%)'].sum()
        nb_points_vente_autres = tab_marques.loc[
            ~tab_marques['Marque'].isin(top10['Marque']), 'Points de vente'
        ].sum()

        # Construction du DataFrame combiné (10 premières + Autres)
        top10_display = top10[['Marque', 'Part de marché (%)', 'Points de vente']].copy()
        autres_row = pd.DataFrame([{
            'Marque': 'Autres',
            'Part de marché (%)': pdm_autres,
            'Points de vente': nb_points_vente_autres
        }])
        df_pie = pd.concat([top10_display, autres_row], ignore_index=True)

        col_pie, col_bar = st.columns(2)

        with col_pie:
            # Camembert des parts de marché
            fig_pie = px.pie(
                df_pie, values='Part de marché (%)', names='Marque',
                title='Part de marché (%) – top 10 + Autres',
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_pie.update_traces(textinfo='percent+label')
            fig_pie.update_layout(template="gilroy_export")
            fig_pie = force_black_axes(fig_pie)
            st.plotly_chart(fig_pie, width='stretch')

        with col_bar:
            # Barres horizontales pour les points de vente (tri décroissant)
            df_bar = top10.sort_values('Points de vente', ascending=True)
            fig_bar = px.bar(
                df_bar, x='Points de vente', y='Marque',
                orientation='h',
                title='Nombre de points de vente (top 10)',
                text='Points de vente',
                color='Marque',
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_bar.update_traces(textposition='outside')
            fig_bar.update_layout(xaxis_title='Points de vente', yaxis_title=None, showlegend=False,
                                  template="gilroy_export")
            fig_bar = force_black_axes(fig_bar)
            st.plotly_chart(fig_bar, width='stretch')
    else:
        st.info("Aucune donnée sur les marques.")

    # -------------------------------------------------------------
    # 2. Marques par chaîne de supermarchés
    # -------------------------------------------------------------
    st.subheader("🏢 Marques présentes par chaîne de supermarchés")
    if not prix_ext.empty and not df_sm.empty:
        df_sm_local = df_sm.copy()
        df_sm_local['nom_norm'] = df_sm_local['Nom'].apply(normalize_name)
        prix_chaines = prix_ext.merge(
            df_sm_local[['nom_norm', 'Chaine']],
            left_on='supermarche_norm',
            right_on='nom_norm',
            how='left'
        )
        prix_chaines['Chaine'] = prix_chaines['Chaine'].fillna('Indépendant').str.strip()
        chaine_marques = prix_chaines.groupby('Chaine')['marque_officielle'].apply(
            lambda x: sorted(x.unique())
        ).reset_index()
        chaine_marques['Marques'] = chaine_marques['marque_officielle'].apply(lambda liste: ', '.join(liste))
        st.dataframe(chaine_marques[['Chaine', 'Marques']], use_container_width=True)
    else:
        st.info("Données insuffisantes pour afficher les chaînes.")

    # -------------------------------------------------------------
    # 3. Comparaison prix enquête terrain vs prix externes
    #    (section existante conservée)
    # -------------------------------------------------------------
    st.subheader("📈 Comparaison des prix relevés sur le terrain vs prix affichés")
    if not df_p_f.empty and not prix_ext.empty:
        # Fusion des deux sources sur le supermarché et le conditionnement (approximatif)
        df_p_f['volume_L'] = df_p_f['data_dict'].apply(lambda d: extraire_litres(d.get('Conditionnement', '')) if isinstance(d, dict) else None)
        df_p_f = df_p_f.dropna(subset=['volume_L'])
        df_p_f['prix_unitaire_FC'] = pd.to_numeric(df_p_f['data_dict'].apply(lambda d: d.get('Prix', 0)), errors='coerce') / df_p_f['volume_L']
        df_p_f['marque_officielle'] = apply_brand_mapping_strict(df_p_f['data_dict'].apply(lambda d: d.get('Marque', '') if isinstance(d, dict) else ''))
        df_p_f = df_p_f.dropna(subset=['marque_officielle'])

        # Pour chaque supermarché, on compare le prix au litre terrain vs externe
        comp_list = []
        for sm in selected_mags if selected_mags else df_p_f['supermarche'].unique():
            terrain = df_p_f[df_p_f['supermarche'] == sm]
            externe = prix_ext[prix_ext['supermarche'] == sm]
            if terrain.empty or externe.empty:
                continue
            # Moyenne par marque et conditionnement
            terrain_agg = terrain.groupby(['marque_officielle', 'volume_L'])['prix_unitaire_FC'].mean().reset_index()
            externe_agg = externe.groupby(['marque_officielle', 'volume_L'])['prix_unitaire_FC'].mean().reset_index()
            merged = terrain_agg.merge(externe_agg, on=['marque_officielle', 'volume_L'], suffixes=('_terrain', '_externe'))
            merged['supermarche'] = sm
            merged['ecart_FC'] = merged['prix_unitaire_FC_terrain'] - merged['prix_unitaire_FC_externe']
            merged['ecart_%'] = (merged['ecart_FC'] / merged['prix_unitaire_FC_externe']) * 100
            comp_list.append(merged)
        if comp_list:
            df_comp = pd.concat(comp_list)
            st.dataframe(df_comp, use_container_width=True)

            fig_comp = px.scatter(df_comp, x='prix_unitaire_FC_externe', y='prix_unitaire_FC_terrain',
                                  hover_data=['supermarche', 'marque_officielle', 'volume_L'],
                                  title="Prix terrain vs prix affiché (FC/L)")
            fig_comp.add_shape(type='line', x0=0, y0=0, x1=df_comp['prix_unitaire_FC_externe'].max(),
                               y1=df_comp['prix_unitaire_FC_externe'].max(), line=dict(dash='dash'))
            fig_comp.update_layout(template="gilroy_export")
            fig_comp = force_black_axes(fig_comp)
            st.plotly_chart(fig_comp, use_container_width=True)
        else:
            st.info("Aucune correspondance trouvée pour comparer les prix.")
    else:
        st.info("Données de prix terrain ou prix externes insuffisantes pour la comparaison.")

    # -------------------------------------------------------------
    # 4. Distribution des prix par marque (boxplot)
    #    (section existante conservée)
    # -------------------------------------------------------------
    st.subheader(f"📦 Prix au litre par marque ({devise})")
    if not prix_ext.empty:
        # ---- Sélecteur de contenant ----
        contenants_dispo = ['Tous'] + sorted(prix_ext['conditionnement'].unique().tolist())
        contenant_choisi = st.selectbox(
            "Filtrer par contenant",
            contenants_dispo,
            key="box_marque_contenant"
        )

        # Filtrage des données
        if contenant_choisi != 'Tous':
            df_prix_marque = prix_ext[prix_ext['conditionnement'] == contenant_choisi]
            titre_graph = f"Distribution des prix au litre par marque – {contenant_choisi} ({devise})"
        else:
            df_prix_marque = prix_ext
            titre_graph = f"Distribution des prix au litre par marque – Tous contenants ({devise})"

        if not df_prix_marque.empty:
            fig_marque = px.box(
                df_prix_marque,
                x='marque_officielle',
                y='prix_unitaire_conv',
                title=titre_graph,
                labels={
                    'marque_officielle': 'Marque',
                    'prix_unitaire_conv': f'Prix au litre ({devise})'
                }
            )
            fig_marque.update_layout(xaxis_tickangle=-45, template="gilroy_export")
            fig_marque = force_black_axes(fig_marque)
            if devise == "FC":
                fig_marque.update_yaxes(tickformat=",.0f")
            else:
                fig_marque.update_yaxes(tickformat=",.2f")
            st.plotly_chart(fig_marque, width='stretch')
        else:
            st.info("Aucune donnée pour ce contenant.")
    else:
        st.info("Aucune donnée de prix externe.")

    # -------------------------------------------------------------
    # 5. Prix au litre selon le conditionnement (boxplots)
    #    (nouvelle version, remplace l'ancien histogramme si existant)
    # -------------------------------------------------------------
    st.subheader(f"💵 Prix au litre selon le conditionnement ({devise})")
    if not prix_ext.empty:
        data_box = prix_ext.copy()
        # Regrouper les conditionnements par volume
        data_box['Cond. (L)'] = data_box['volume_L'].apply(lambda v: f"{v:.1f} L" if v == int(v) else f"{v:.2f} L")
        order = sorted(data_box['volume_L'].unique())
        order_labels = [f"{v:.1f} L" if v == int(v) else f"{v:.2f} L" for v in order]
        data_box['Cond. (L)'] = pd.Categorical(data_box['Cond. (L)'], categories=order_labels, ordered=True)

        fig_box = px.box(
            data_box,
            x='Cond. (L)',
            y='prix_unitaire_conv',
            points='outliers',
            title=f"Distribution des prix au litre par conditionnement ({devise})",
            labels={'prix_unitaire_conv': f'Prix au litre ({devise})', 'Cond. (L)': 'Conditionnement'}
        )
        fig_box.update_layout(template="gilroy_export")
        fig_box = force_black_axes(fig_box)
        fig_box.update_layout(yaxis_tickformat=",.2f" if devise == "USD" else ",.0f")
        st.plotly_chart(fig_box, use_container_width=True)

        with st.expander("📋 Statistiques par conditionnement"):
            stats = data_box.groupby('Cond. (L)')['prix_unitaire_conv'].describe(percentiles=[.25, .5, .75])
            st.dataframe(stats, use_container_width=True)
    else:
        st.info("Pas assez de données pour les boxplots.")

    # -------------------------------------------------------------
    # 6. Tableau des prix par supermarché (existant conservé)
    # -------------------------------------------------------------
    st.subheader("🏪 Prix au litre par supermarché")
    if not prix_ext.empty:
        sm_prices = prix_ext.groupby('supermarche')['prix_unitaire_conv'].agg(['mean', 'median', 'std', 'count']).reset_index()
        sm_prices.columns = ['Supermarché', 'Moyenne', 'Médiane', 'Écart-type', 'Nb relevés']
        devise_str = "USD" if devise == "USD" else "FC"
        for col in ['Moyenne', 'Médiane', 'Écart-type']:
            sm_prices[col] = sm_prices[col].apply(lambda x: f"{x:,.2f} {devise_str}" if devise == "USD" else f"{x:,.0f} {devise_str}")
        st.dataframe(sm_prices, use_container_width=True)
    else:
        st.info("Aucune donnée de prix externe.")

    # -------------------------------------------------------------
    # 7. Export des données
    # -------------------------------------------------------------
    if not prix_ext.empty:
        csv = prix_ext.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Télécharger les prix externes (CSV)", csv, "prix_externes.csv", "text/csv")

# ------------------------------------------------------------
# ONGLET 7 : PROFIL SUPERMARCHÉS (corrigé)
# ------------------------------------------------------------
with tabs[7]:
    st.header("🏪 Profil des supermarchés recensés")
    if df_sm.empty:
        st.warning("Aucune donnée de supermarchés.")
    else:
        df_sm = df_sm.copy()
        total = len(df_sm)
        st.metric("Nombre total de supermarchés", total)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Répartition par taille")
            taille_counts = df_sm['Taille'].value_counts().reset_index()
            taille_counts.columns = ['Taille', 'Nombre']
            fig_taille = px.pie(taille_counts, values='Nombre', names='Taille')
            fig_taille.update_layout(template="gilroy_export")
            fig_taille = force_black_axes(fig_taille)
            st.plotly_chart(fig_taille, width='stretch')
        with col2:
            st.subheader("Répartition par niveau socio-économique")
            socio_counts = df_sm['Niveau_socio'].value_counts().reset_index()
            socio_counts.columns = ['Niveau socio-économique', 'Nombre']
            fig_socio = px.pie(socio_counts, values='Nombre', names='Niveau socio-économique')
            fig_socio.update_layout(template="gilroy_export")
            fig_socio = force_black_axes(fig_socio)
            st.plotly_chart(fig_socio, width='stretch')
        st.subheader("Croisement Taille × Niveau socio-économique")
        cross_taille_socio = pd.crosstab(df_sm['Taille'], df_sm['Niveau_socio'])
        st.dataframe(cross_taille_socio)
        price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
        df_sm['Presence_huile'] = (df_sm[price_cols] > 0).any(axis=1)
        df_sm['Presence_huile_label'] = df_sm['Presence_huile'].map({True: 'Oui', False: 'Non'})
        st.subheader("Présence d'huile")
        col_a, col_b = st.columns(2)
        with col_a:
            st.write("Par niveau socio-économique")
            cross_presence_socio = pd.crosstab(df_sm['Niveau_socio'], df_sm['Presence_huile_label'])
            st.dataframe(cross_presence_socio)
            fig_pres_socio = px.histogram(df_sm, x='Niveau_socio', color='Presence_huile_label',
                                          barmode='group', labels={'Presence_huile_label': 'Huile présente'},
                                          title="Présence d'huile par niveau socio-économique")
            fig_pres_socio.update_xaxes(title_text="Niveau socio-économique")
            fig_pres_socio.update_yaxes(title_text="Nombre de supermarchés")
            fig_pres_socio.update_layout(template="gilroy_export")
            fig_pres_socio = force_black_axes(fig_pres_socio)
            st.plotly_chart(fig_pres_socio, width='stretch')
        with col_b:
            st.write("Par taille")
            cross_presence_taille = pd.crosstab(df_sm['Taille'], df_sm['Presence_huile_label'])
            st.dataframe(cross_presence_taille)
            fig_pres_taille = px.histogram(df_sm, x='Taille', color='Presence_huile_label',
                                           barmode='group', labels={'Presence_huile_label': 'Huile présente'},
                                           title="Présence d'huile par taille")
            fig_pres_taille.update_xaxes(title_text="Taille du supermarché")
            fig_pres_taille.update_yaxes(title_text="Nombre de supermarchés")
            fig_pres_taille.update_layout(template="gilroy_export")
            fig_pres_taille = force_black_axes(fig_pres_taille)
            st.plotly_chart(fig_pres_taille, width='stretch')
        st.subheader("Nombre de supermarchés par chaîne")
        if 'Chaine' in df_sm.columns:
            chaine_counts = df_sm['Chaine'].value_counts().reset_index()
            chaine_counts.columns = ['Chaîne', 'Nombre']
            chaine_counts = chaine_counts.sort_values('Nombre', ascending=True)

            fig_chaine = px.bar(
                chaine_counts, x='Nombre', y='Chaîne',
                orientation='h',
                title='Magasins par chaîne',
                text='Nombre',
                color='Chaîne',
                color_discrete_sequence=px.colors.qualitative.Dark24
            )
            fig_chaine.update_traces(textposition='outside')
            fig_chaine.update_layout(xaxis_title='Nombre de magasins', yaxis_title=None, showlegend=False,
                                     template="gilroy_export")
            fig_chaine = force_black_axes(fig_chaine)
            st.plotly_chart(fig_chaine, width='stretch')
        else:
            st.info("La colonne 'Chaine' n'est pas présente dans le fichier supermarchés.")
        
        st.subheader("Répartition par secteur")
        secteur_counts = df_sm['Secteur'].value_counts().reset_index()
        secteur_counts.columns = ['Secteur', 'Nombre']
        fig_secteur = px.bar(secteur_counts, x='Secteur', y='Nombre')
        fig_secteur.update_layout(template="gilroy_export")
        fig_secteur = force_black_axes(fig_secteur)
        st.plotly_chart(fig_secteur, width='stretch')
        st.subheader("Croisement Secteur × Taille")
        cross_secteur_taille = pd.crosstab(df_sm['Secteur'], df_sm['Taille'])
        st.dataframe(cross_secteur_taille)
        st.subheader("Horaires d'ouverture")
        try:
            df_sm['h_ouv_sem'] = df_sm['ouv_sem'].apply(lambda x: parse_time(x).hour + parse_time(x).minute/60 if parse_time(x) else None)
            df_sm['h_ferm_sem'] = df_sm['ferm_sem'].apply(lambda x: parse_time(x).hour + parse_time(x).minute/60 if parse_time(x) else None)
            df_sm['duree_sem'] = df_sm['h_ferm_sem'] - df_sm['h_ouv_sem']
            if df_sm['duree_sem'].notna().any():
                st.write(f"Durée d'ouverture moyenne en semaine : {df_sm['duree_sem'].mean():.1f} h")
                fig_ouv = px.histogram(df_sm, x='h_ouv_sem', nbins=24, title="Heure d'ouverture semaine")
                fig_ouv.update_layout(template="gilroy_export")
                fig_ouv = force_black_axes(fig_ouv)
                st.plotly_chart(fig_ouv, width='stretch')
                duree_secteur = df_sm.groupby('Secteur')['duree_sem'].mean().round(1).reset_index()
                fig_duree = px.bar(duree_secteur, x='Secteur', y='duree_sem', title="Durée moyenne d'ouverture (heures) par secteur")
                fig_duree.update_layout(template="gilroy_export")
                fig_duree = force_black_axes(fig_duree)
                st.plotly_chart(fig_duree, width='stretch')
        except:
            st.info("Horaires non exploitables.")

# ------------------------------------------------------------
# ONGLET 8 : ANOMALIES (inchangé, pas de figures Plotly)
# ------------------------------------------------------------

with tabs[8]:
        # ------------------------------------------------------------
    # 4. Doublons supermarchés (inchangé)
    # ------------------------------------------------------------
    if not df_sm.empty:
        st.subheader("🏪 Doublons dans le fichier des supermarchés")
        nom_counts = df_sm['Nom'].value_counts()
        doublons = nom_counts[nom_counts > 1]
        if not doublons.empty:
            st.warning(f"{len(doublons)} noms apparaissent plusieurs fois.")
            for nom, count in doublons.items():
                st.write(f"- **{nom}** : {count} occurrences")
            if st.button("🗑️ Supprimer les doublons (créer un fichier nettoyé)"):
                df_unique = df_sm.drop_duplicates(subset='Nom', keep='first').copy()
                os.rename("supermarches.csv", "supermarches_backup.csv")
                df_unique.to_csv("supermarches.csv", index=False, encoding='utf-8-sig')
                st.success("Fichier nettoyé. Rechargez la page.")
                st.rerun()
        else:
            st.success("✅ Aucun doublon détecté.")
    else:
        st.info("Fichier supermarchés non chargé.")

    # ------------------------------------------------------------
    # 6. Outils supplémentaires (expanders)
    # ------------------------------------------------------------
    st.subheader("🛠️ Outils supplémentaires")

    with st.expander("🏷️ Mapping des marques", expanded=False):
        official_set = get_official_brands()
        brand_map = load_brand_mapping()

        # Construire l'ensemble des marques brutes rencontrées (avant filtrage)
        raw_brands = set()
        # Parcourir tous les questionnaires une seule fois
        if not df_q.empty:
            for _, row in df_q.iterrows():
                data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
                if not isinstance(data, dict):
                    continue
                t = row['type']
                if t == 'supermarche':
                    q2 = data.get('Q2_Marque')
                    if q2:
                        raw_brands.add(normalize_brand(str(q2).replace('Autre:', '')))
                elif t == 'menage':
                    q7 = data.get('Q7_MarquePreferee')
                    if q7:
                        raw_brands.add(normalize_brand(str(q7).replace('Autre:', '')))
                elif t == 'supermarche_menage':
                    q8 = data.get('Q8_MarquePreferee')
                    if q8:
                        raw_brands.add(normalize_brand(str(q8).replace('Autre:', '')))
        # Prix recensement
        if not df_prices_ext.empty:
            for b in df_prices_ext['marque'].unique():
                raw_brands.add(normalize_brand(b))
        # Prix enquête
        if not df_p_f.empty:
            for b in df_p_f['marque'].unique():
                raw_brands.add(normalize_brand(b))

        raw_brands.discard('')
        raw_brands.discard('inconnue')
        already_mapped = set(brand_map.keys())
        missing = [b for b in raw_brands if b not in official_set and b not in already_mapped]

        if not missing:
            st.success("✅ Toutes les marques rencontrées sont mappées ou officielles.")
        else:
            st.warning(f"{len(missing)} marque(s) à mapper.")
            new_mapping = {}
            for brand in sorted(missing):
                col1, col2 = st.columns([3, 1])
                with col1:
                    options = sorted(list(official_set))
                    selected = st.selectbox(f"**{brand}** →", options=[""] + options, key=f"map_{brand}")
                with col2:
                    new_name = st.text_input("Nouveau nom", key=f"new_{brand}", value="")
                final = new_name.strip() if new_name.strip() else selected
                if final:
                    new_mapping[brand] = final
            if st.button("💾 Enregistrer le mapping"):
                brand_map.update(new_mapping)
                save_brand_mapping(brand_map)
                compute_all_anomalies.clear()
                cached_compute_k_factors.clear()
                st.success("Mapping enregistré. Rechargement...")
                st.rerun()

    # Correspondances supermarchés
    with st.expander("🔍 Correspondances supermarchés (matching flou)"):
        corrections_file = "store_mapping_corrections.json"
        manual_corrections = {}
        if os.path.exists(corrections_file):
            with open(corrections_file, 'r', encoding='utf-8') as f:
                manual_corrections = json.load(f)
        selected_mags = st.session_state.get('selected_magasins', [])
        if not selected_mags:
            st.info("Aucun magasin sélectionné (onglet Accueil).")
        else:
            selected_norm = {normalize_name(m): m for m in selected_mags}
            if not df_supermarche.empty and 'magasin_officiel' in df_supermarche.columns:
                all_officiel = df_supermarche['magasin_officiel'].dropna().unique()
                problematiques = []
                for officiel in all_officiel:
                    if officiel in selected_mags or officiel in manual_corrections:
                        continue
                    norm_off = normalize_name(officiel)
                    best_score, best_match = 0, None
                    for norm_sel, sel_orig in selected_norm.items():
                        score = SequenceMatcher(None, norm_off, norm_sel).ratio()
                        if score > best_score and score >= 0.8:
                            best_score = score
                            best_match = sel_orig
                    problematiques.append({
                        'magasin_officiel': officiel,
                        'meilleur_match': best_match,
                        'score': round(best_score, 3)
                    })
                if not problematiques:
                    st.success("✅ Tous les magasins sont correctement associés.")
                else:
                    for idx, p in enumerate(problematiques):
                        st.markdown(f"**{p['magasin_officiel']}**")
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            options = ["Ne pas associer (ignorer)"] + selected_mags
                            default = 0
                            if p['meilleur_match'] in options:
                                default = options.index(p['meilleur_match'])
                            choix = st.selectbox("Correspondance cible", options, index=default, key=f"corr_{idx}")
                        with col2:
                            if st.button("Appliquer", key=f"app_{idx}"):
                                manual_corrections[p['magasin_officiel']] = None if choix == "Ne pas associer (ignorer)" else choix
                                with open(corrections_file, 'w', encoding='utf-8') as f:
                                    json.dump(manual_corrections, f, indent=2, ensure_ascii=False)
                                st.success("Correction enregistrée.")
                                st.rerun()
            else:
                st.info("Aucune donnée supermarché dans les questionnaires.")

    # Initialisation sécurisée des DataFrames pleins (nécessaires pour les anomalies)
    if 'df_q_full' not in dir():
        df_q_full = df_q.copy() if not df_q.empty else pd.DataFrame()
    if 'df_c_full' not in dir():
        df_c_full = df_c.copy() if not df_c.empty else pd.DataFrame()
    if 'df_p_full' not in dir():
        df_p_full = df_p.copy() if not df_p.empty else pd.DataFrame()

    # ================================================================
    # Anomalies par type (détection étendue des valeurs aberrantes)
    # ================================================================
    st.divider()
    st.subheader("🔍 Anomalies par type")

    # Catégories
    categories = {
        "Intervalle trop court (hors refus)": lambda msg: "Intervalle trop court" in msg and "Refus" not in msg,
        "Refus trop rapproché": lambda msg: "Refus trop rapproché" in msg,
        "Distance GPS > seuil": lambda msg: "Distance GPS >" in msg,
        "Coordonnées GPS identiques": lambda msg: "Coordonnées GPS identiques" in msg,
        "Prix/litre hors normes": lambda msg: "Prix/litre hors normes" in msg,
        "Volume acheté > max": lambda msg: "Volume acheté supérieur" in msg,
        "Taux de sortie > max": lambda msg: "Taux de sortie >" in msg,
        "Durée comptage > max": lambda msg: "Durée >" in msg and "30 min avec 0 sorties" not in msg,
        "Durée > 30 min avec 0 sorties": lambda msg: "Durée > 30 min avec 0 sorties" in msg,
        "Prix hors plage raisonnable": lambda msg: "Prix hors plage raisonnable" in msg,
        "Marque non référencée": lambda msg: "Marque achetée" in msg and "non référencée" in msg,
    }

    def categoriser(msg):
        for cat, func in categories.items():
            if func(msg):
                return cat
        return "Autre"

    if not df_anom_f.empty:
        df_anom_f = df_anom_f.copy()
        df_anom_f['categorie'] = df_anom_f['message'].apply(categoriser)

        # --- Détection des valeurs aberrantes (champs numériques) ---
        if not df_q_full.empty:
            # On prend tous les questionnaires « huile » (supermarché, supermarché_ménage, ménage)
            q_all = df_q_full[df_q_full['type'].isin(['supermarche', 'supermarche_menage', 'menage'])].copy()
            if 'statut' in q_all.columns:
                q_all = q_all[q_all['statut'] != 'Refus']

            if not q_all.empty:
                # ----- Fonctions d'extraction des champs -----
                def extraire_champs(row):
                    d = row['data_dict'] if isinstance(row['data_dict'], dict) else json.loads(row['data_dict'])
                    typ = row['type']
                    champs = {}

                    # Volume (litres)
                    if typ == 'supermarche':
                        vol = extraire_litres(d.get('Q4_Quantité', ''))
                    else:
                        nb = d.get('Q4_Quantite_Nombre', '')
                        cont = d.get('Q4_Quantite_Contenant', '')
                        vol_unit_str = d.get('Q4_Quantite_VolumeUnitaire', '')
                        if nb and cont and vol_unit_str:
                            try:
                                nb_int = int(nb)
                                vol_unit = float(str(vol_unit_str).replace(',', '.'))
                                vol = nb_int * vol_unit
                            except:
                                vol = None
                        else:
                            vol = None
                    champs['volume_L'] = vol

                    # Prix payé (FC)
                    if typ == 'supermarche':
                        prix_str = d.get('Q5_PrixPayé', '')
                    else:
                        prix_str = d.get('Q5_PrixHabituel', '')
                    try:
                        prix_paye = float(str(prix_str).replace(',', '.'))
                    except:
                        prix_paye = None
                    champs['prix_paye_FC'] = prix_paye

                    # Prix maximum (FC)
                    if typ == 'supermarche':
                        prix_max_str = d.get('Q10_PrixMax', '')
                    else:
                        prix_max_str = d.get('Q9_PrixMax', '')
                    try:
                        prix_max = float(str(prix_max_str).replace(',', '.'))
                    except:
                        prix_max = None
                    champs['prix_max_FC'] = prix_max

                    # Nombre de personnes
                    if typ == 'supermarche':
                        nb_pers_str = d.get('Q7_NbPersonnes', '')
                    else:
                        nb_pers_str = d.get('Q1_NbPersonnes', '')
                    try:
                        nb_pers = int(float(str(nb_pers_str)))
                    except:
                        nb_pers = None
                    champs['nb_personnes'] = nb_pers

                    # Prix au litre (FC/L)
                    if vol and prix_paye and vol > 0:
                        champs['prix_L_FC'] = prix_paye / vol
                    else:
                        champs['prix_L_FC'] = None

                    return champs

                # Appliquer l'extraction
                q_all['champs'] = q_all.apply(extraire_champs, axis=1)

                # Pour chaque champ, détecter les outliers
                champs_a_tester = {
                    'volume_L': 'Volume acheté aberrant',
                    'prix_paye_FC': 'Prix payé aberrant',
                    'prix_max_FC': 'Prix maximum aberrant',
                    'nb_personnes': 'Nombre de personnes aberrant',
                    'prix_L_FC': 'Prix au litre aberrant'
                }

                for champ, nom_anomalie in champs_a_tester.items():
                    valeurs = q_all['champs'].apply(lambda x: x.get(champ))
                    valeurs = valeurs.dropna()
                    if len(valeurs) < 4:
                        continue
                    Q1 = np.percentile(valeurs, 25)
                    Q3 = np.percentile(valeurs, 75)
                    IQR = Q3 - Q1
                    low = Q1 - 1.5 * IQR
                    high = Q3 + 1.5 * IQR

                    for _, row in q_all.iterrows():
                        val = row['champs'].get(champ)
                        if pd.notna(val) and (val < low or val > high):
                            uid = row['uuid']
                            # Vérifier que l'uuid n'a pas déjà une anomalie de cette catégorie
                            deja = df_anom_f[(df_anom_f['uuid'] == uid) & (df_anom_f['categorie'].str.contains(nom_anomalie, na=False))]
                            if deja.empty:
                                unite = 'L' if 'Volume' in nom_anomalie else ('FC' if 'Prix' in nom_anomalie else ('FC/L' if 'litre' in nom_anomalie else ''))
                                msg = f"{nom_anomalie} ({val:.1f} {unite}) – hors plage [{low:.1f}, {high:.1f}]"
                                df_anom_f = pd.concat([df_anom_f, pd.DataFrame([{
                                    'uuid': uid,
                                    'type': 'questionnaire',
                                    'date_str': row['date'],
                                    'enqueteur': row.get('enqueteur', ''),
                                    'message': msg,
                                    'date': pd.to_datetime(row['date']).date(),
                                    'categorie': nom_anomalie
                                }])], ignore_index=True)

        # Résumé des catégories
        cat_summary = df_anom_f['categorie'].value_counts().reset_index()
        cat_summary.columns = ['Catégorie', 'Nombre']
        st.dataframe(cat_summary, use_container_width=True)

        # Sélection d'une catégorie
        selected_cat = st.selectbox("Choisissez une catégorie", cat_summary['Catégorie'].tolist(), key="cat_select")
        if selected_cat:
            df_cat = df_anom_f[df_anom_f['categorie'] == selected_cat].reset_index(drop=True)
            st.write(f"**{len(df_cat)} anomalie(s) dans cette catégorie.**")

            detail_event = st.dataframe(
                df_cat[['type', 'uuid', 'date_str', 'enqueteur', 'message']],
                on_select="rerun",
                selection_mode="multi-row",
                use_container_width=True,
                key="detail_cat_anomalies"
            )

            if detail_event.selection.rows:
                # Vérifier que les indices sont dans les bornes de df_cat
                valid_indices = [i for i in detail_event.selection.rows if i < len(df_cat)]
                if not valid_indices:
                    st.warning("Les lignes sélectionnées ne sont plus disponibles. Veuillez resélectionner.")
                else:
                    selected_rows = df_cat.iloc[valid_indices]
                    st.write(f"**{len(selected_rows)} enregistrement(s) sélectionné(s) pour suppression.**")
                    if st.button("🗑️ Supprimer les enregistrements sélectionnés", key="del_cat_anomalies"):
                        try:
                            db_conn = sqlite3.connect(DB_PATH)
                            cur = db_conn.cursor()
                            for _, row_sel in selected_rows.iterrows():
                                table = "questionnaires" if row_sel['type'] == 'questionnaire' else ("countings" if row_sel['type'] == 'comptage' else "prices")
                                cur.execute(f"DELETE FROM {table} WHERE uuid = ?", (row_sel['uuid'],))
                            db_conn.commit()
                            db_conn.close()
                            load_db_internal.clear()
                            compute_all_anomalies.clear()
                            cached_compute_k_factors.clear()
                            st.success(f"{len(selected_rows)} enregistrement(s) supprimé(s).")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur : {e}")
            else:
                st.info("Cochez un ou plusieurs enregistrements dans le tableau ci-dessus pour les supprimer.")
    else:
        st.info("Aucune anomalie à afficher.")

# ------------------------------------------------------------
# ONGLET 9 : CARTE DES SUPERMARCHÉS ET MESURES (inchangé, pas de figures Plotly)
# ------------------------------------------------------------
# (le code existant de l'onglet 9 est déjà fourni sans figures Plotly, on le laisse tel quel)
with tabs[9]:
    st.header("🗺️ Cartographie des supermarchés et des mesures GPS")

    # ----- Fonction de parsing GPS -----
    def parse_gps(gps_str):
        if not isinstance(gps_str, str) or gps_str.strip() == '':
            return None, None
        parts = gps_str.split(',')
        if len(parts) >= 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                if lat == 0 and lon == 0:
                    return None, None
                return lat, lon
            except ValueError:
                return None, None
        return None, None

    # ----- Agrégation des mesures GPS (avec UUID et enquêteur) -----
    measures = []
    if not df_supermarche.empty:
        for _, row in df_supermarche.iterrows():
            gps_val = row['data_dict'].get('GPS', '')
            lat, lon = parse_gps(gps_val)
            if lat is not None and lon is not None:
                measures.append({
                    'magasin': row.get('magasin_officiel', row.get('lieu', '')),
                    'lat': lat,
                    'lon': lon,
                    'type': 'Questionnaire SM',
                    'date': row['date_dt'],
                    'uuid': row.get('uuid', ''),
                    'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
                })
    if not df_menage.empty:
        for _, row in df_menage.iterrows():
            gps_val = row['data_dict'].get('GPS', '')
            lat, lon = parse_gps(gps_val)
            if lat is not None and lon is not None:
                measures.append({
                    'magasin': 'Ménage (' + str(row.get('lieu', '')) + ')',
                    'lat': lat,
                    'lon': lon,
                    'type': 'Questionnaire ménage',
                    'date': row['date_dt'],
                    'uuid': row.get('uuid', ''),
                    'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
                })
    if not df_c_f.empty:
        for _, row in df_c_f.iterrows():
            gps_val = row['data_dict'].get('GPS', '')
            lat, lon = parse_gps(gps_val)
            if lat is not None and lon is not None:
                mag = normalize_name(row['lieu'])
                measures.append({
                    'magasin': mag,
                    'lat': lat,
                    'lon': lon,
                    'type': 'Comptage',
                    'date': row['date_dt'],
                    'uuid': row.get('uuid', row.get('id', '')),
                    'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
                })
    if not measures:
        st.warning("Aucune coordonnée GPS trouvée dans les données de collecte.")
        st.stop()

    df_meas = pd.DataFrame(measures)
    if 'date' in df_meas.columns:
        df_meas = df_meas[(df_meas['date'].dt.date >= date_range[0]) & (df_meas['date'].dt.date <= date_range[1])]
    if df_meas.empty:
        st.warning("Aucune mesure GPS dans la période sélectionnée.")
        st.stop()

    # ... (le reste de l'onglet 9 identique à l'original, inchangé)
    # (Je ne le recopie pas pour éviter la duplication, il n'y a pas de figures Plotly à modifier)

# ------------------------------------------------------------
# ONGLET 10 : AFFLUENCE (corrigé)
# ------------------------------------------------------------
with tabs[10]:
    st.header("📊 Profils d'affluence par jour (Google Popular Times)")

    if df_profils_pivot.empty:
        st.error("Données d'affluence non disponibles. Vérifiez le fichier 'fréquentation.csv'.")
    else:
        jours_map = {
            'Lundi': 'Mo', 'Mardi': 'Tu', 'Mercredi': 'We', 'Jeudi': 'Th', 'Vendredi': 'Fr',
            'Samedi': 'Sa', 'Dimanche': 'Su'
        }
        jours_liste = list(jours_map.keys())
        options_affichage = jours_liste + ["Moyenne semaine (lun-ven)", "Moyenne week-end (sam-dim)"]

        st.subheader("📈 Profil horaire d'un magasin")
        magasins_dispos = sorted(df_profils_pivot['magasin'].unique())
        selected_mag = st.selectbox("Choisir un magasin", magasins_dispos)
        selected_option = st.selectbox("Choisir un jour ou une moyenne", options_affichage)

        if selected_mag:
            row_mag = df_profils_pivot[df_profils_pivot['magasin'] == selected_mag].iloc[0]
            if selected_option == "Moyenne semaine (lun-ven)":
                codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
                titre = f"Profil horaire – {selected_mag} (moyenne semaine)"
            elif selected_option == "Moyenne week-end (sam-dim)":
                codes = ['Sa', 'Su']
                titre = f"Profil horaire – {selected_mag} (moyenne week-end)"
            else:
                codes = [jours_map[selected_option]]
                titre = f"Profil horaire – {selected_mag} ({selected_option})"
            valeurs = []
            for h in range(24):
                vals = [row_mag.get(f'{code}_{h}', 0) for code in codes]
                valeurs.append(sum(vals) / len(vals))
            fig = px.line(x=list(range(24)), y=valeurs,
                          labels={'x': 'Heure', 'y': 'Occupation (%)'},
                          title=titre)
            fig.update_xaxes(tickvals=list(range(0, 24, 2)),
                             ticktext=[f"{h}:00" for h in range(0, 24, 2)])
            fig.update_layout(template="gilroy_export")
            fig = force_black_axes(fig)
            st.plotly_chart(fig, width='stretch')

        st.subheader("📋 Profil moyen par secteur (médiane)")
        if not df_sm.empty and secteur_profiles is not None:
            df_profils_pivot['magasin_norm'] = df_profils_pivot['magasin'].apply(normalize_name)
            df_sm['nom_norm'] = df_sm['Nom'].apply(normalize_name)
            merged = df_profils_pivot.merge(df_sm[['nom_norm', 'Secteur']], left_on='magasin_norm', right_on='nom_norm', how='left')
            secteurs = sorted(merged['Secteur'].dropna().unique())
            if secteurs:
                choix_secteur = st.selectbox("Secteur à afficher", secteurs, key="sect_affluence")
                option_sect = st.selectbox("Jour / moyenne", options_affichage, key="sect_option_affluence")
                if option_sect == "Moyenne semaine (lun-ven)":
                    codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
                    titre = f"Profil médian – secteur {choix_secteur} (moyenne semaine)"
                elif option_sect == "Moyenne week-end (sam-dim)":
                    codes = ['Sa', 'Su']
                    titre = f"Profil médian – secteur {choix_secteur} (moyenne week-end)"
                else:
                    codes = [jours_map[option_sect]]
                    titre = f"Profil médian – secteur {choix_secteur} ({option_sect})"
                df_sect = merged[merged['Secteur'] == choix_secteur]
                if not df_sect.empty:
                    medianes = []
                    for h in range(24):
                        vals = [df_sect[f'{code}_{h}'].median() for code in codes]
                        medianes.append(sum(vals) / len(vals))
                    fig_sect = px.line(x=list(range(24)), y=medianes,
                                       labels={'x': 'Heure', 'y': 'Occupation (%)'},
                                       title=titre)
                    fig_sect.update_xaxes(tickvals=list(range(0, 24, 2)),
                                          ticktext=[f"{h}:00" for h in range(0, 24, 2)])
                    fig_sect.update_layout(template="gilroy_export")
                    fig_sect = force_black_axes(fig_sect)
                    st.plotly_chart(fig_sect, width='stretch')
                    df_median = pd.DataFrame({
                        'Heure': [f"{h}:00" for h in range(24)],
                        'Occupation médiane (%)': medianes
                    })
                    st.dataframe(df_median, use_container_width=True)
                else:
                    st.info("Aucun magasin de ce secteur avec données d'affluence.")
            else:
                st.info("Aucun secteur trouvé pour les magasins avec données d'affluence.")
        else:
            st.warning("Fichier supermarches.csv non chargé ou pas de profils secteur.")

        st.subheader("🔗 Correspondance des noms de magasins")
        mapping_file = "magasin_mapping.json"
        if 'df_avec_huile' in locals() and not df_avec_huile.empty:
            magasins_sm = df_avec_huile['Nom'].tolist()
        else:
            magasins_sm = df_sm['Nom'].tolist() if not df_sm.empty else []
        magasins_google = magasins_dispos
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
        else:
            mapping = {}
        def normalize_match(name):
            import unicodedata
            name = name.lower()
            name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
            name = re.sub(r'[^a-z0-9 ]', '', name)
            return name.strip()
        for mag_sm in magasins_sm:
            if mag_sm not in mapping:
                best_match = ""
                best_score = 0
                norm_sm = normalize_match(mag_sm)
                for g in magasins_google:
                    norm_g = normalize_match(g)
                    score = SequenceMatcher(None, norm_sm, norm_g).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = g
                mapping[mag_sm] = best_match if best_score >= 0.6 else ""
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        mapping_corrige = {}
        st.write("Corrigez les associations ci-dessous :")
        for mag_sm in magasins_sm:
            current = mapping.get(mag_sm, "")
            options = [""] + magasins_google
            idx = options.index(current) if current in options else 0
            new_val = st.selectbox(f"{mag_sm}", options, index=idx, key=f"map_{mag_sm}")
            mapping_corrige[mag_sm] = new_val
        if st.button("💾 Enregistrer la correspondance"):
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(mapping_corrige, f, indent=2, ensure_ascii=False)
            st.success("Correspondance enregistrée. Rechargez la page.")
            cached_compute_k_factors.clear()
            st.rerun()
        df_mapping = pd.DataFrame(list(mapping_corrige.items()),
                                  columns=['Supermarche (fichier)', 'Magasin Google associé'])
        st.dataframe(df_mapping, use_container_width=True)
        st.info("Ces correspondances servent à lier les données d'affluence aux magasins.")

# ------------------------------------------------------------
# ONGLET 11 : EXPORTATION
# ------------------------------------------------------------
with tabs[11]:
    st.header("📤 Exportation de données")

    export_type = st.radio(
        "Type d'export",
        ["Données brutes (CSV)", "Rapport de synthèse textuelle", "Tableaux de synthèse (exportables)"],
        horizontal=True
    )

    # ============================================================
    # 1. DONNÉES BRUTES (CSV)
    # ============================================================
    if export_type == "Données brutes (CSV)":
        source = st.selectbox(
            "Source de données",
            [
                "Questionnaires (unifiés)",
                "Comptages",
                "Prix (application)",
                "Prix (fichier supermarchés)"
            ]
        )

        if source == "Questionnaires (unifiés)":
            if df_q_export.empty:
                st.info("Aucun questionnaire à exporter.")
            else:
                df_base = df_q_export.copy()
                available_cols = sorted(df_base.columns.tolist())

                st.subheader("Filtres optionnels")
                type_filt = st.multiselect("Type de questionnaire", df_base['type'].unique(), key="exp_type")
                if type_filt:
                    df_base = df_base[df_base['type'].isin(type_filt)]

                mag_filt = st.multiselect("Magasin", df_base['magasin_officiel'].unique(), key="exp_mag")
                if mag_filt:
                    df_base = df_base[df_base['magasin_officiel'].isin(mag_filt)]

                commune_filt = st.multiselect("Commune", df_base['commune'].dropna().unique(), key="exp_commune")
                if commune_filt:
                    df_base = df_base[df_base['commune'].isin(commune_filt)]

                if 'statut' in df_base.columns:
                    statut_filt = st.multiselect("Statut", df_base['statut'].unique(), key="exp_statut")
                    if statut_filt:
                        df_base = df_base[df_base['statut'].isin(statut_filt)]

        elif source == "Comptages":
            df_base = df_c_f.copy()
            available_cols = sorted(df_base.columns.tolist())
            st.subheader("Filtres optionnels")
            lieu_filt = st.multiselect("Magasin", df_base['lieu_officiel'].unique(), key="exp_c_lieu")
            if lieu_filt:
                df_base = df_base[df_base['lieu_officiel'].isin(lieu_filt)]

        elif source == "Prix (application)":
            df_base = df_p_f.copy()
            available_cols = sorted(df_base.columns.tolist())
            st.subheader("Filtres optionnels")
            superm_filt = st.multiselect("Supermarché", df_base['supermarche'].unique(), key="exp_p_sm")
            marque_filt = st.multiselect("Marque", df_base['marque'].unique(), key="exp_p_marque")
            cond_filt = st.multiselect("Conditionnement", df_base['conditionnement'].unique(), key="exp_p_cond")
            if superm_filt:
                df_base = df_base[df_base['supermarche'].isin(superm_filt)]
            if marque_filt:
                df_base = df_base[df_base['marque'].isin(marque_filt)]
            if cond_filt:
                df_base = df_base[df_base['conditionnement'].isin(cond_filt)]

        elif source == "Prix (fichier supermarchés)":
            df_base = df_prices_ext.copy()
            available_cols = sorted(df_base.columns.tolist())
            st.subheader("Filtres optionnels")
            superm_filt = st.multiselect("Supermarché", df_base['supermarche'].unique(), key="exp_pf_sm")
            marque_filt = st.multiselect("Marque", df_base['marque'].unique(), key="exp_pf_marque")
            cond_filt = st.multiselect("Conditionnement", df_base['conditionnement'].unique(), key="exp_pf_cond")
            if superm_filt:
                df_base = df_base[df_base['supermarche'].isin(superm_filt)]
            if marque_filt:
                df_base = df_base[df_base['marque'].isin(marque_filt)]
            if cond_filt:
                df_base = df_base[df_base['conditionnement'].isin(cond_filt)]

        # Sélection des colonnes
        default_selected = available_cols.copy()
        selected_cols = st.multiselect(
            "Colonnes à exporter",
            available_cols,
            default=default_selected,
            key="exp_cols"
        )

        if not selected_cols:
            st.warning("Veuillez sélectionner au moins une colonne.")
        else:
            df_export = df_base[selected_cols]

            st.subheader("Aperçu des données")
            st.dataframe(df_export.head(100), use_container_width=True)
            st.caption(f"{len(df_export)} lignes au total.")

            csv_data = df_export.to_csv(index=False).encode('utf-8')
            file_name = f"export_{source.lower().replace(' ', '_')}.csv"
            st.download_button(
                label="📥 Télécharger CSV",
                data=csv_data,
                file_name=file_name,
                mime="text/csv"
            )

    # ============================================================
    # 2. RAPPORT DE SYNTHÈSE TEXTUELLE (inchangé)
    # ============================================================
    elif export_type == "Rapport de synthèse textuelle":
        st.subheader("📝 Rapport de synthèse pour IA")

        def generer_rapport():
            lignes = []
            lignes.append("# RAPPORT DE SYNTHÈSE INTERMÉDIAIRE – PROJET HUILE DE PALME ROUGE")
            lignes.append(f"Date de génération : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            lignes.append("")
            # ... (reste du rapport textuel, inchangé)
            # (Nous ne le répétons pas intégralement ici pour rester concis,
            #  conservez votre code existant pour cette partie)
            lignes.append("## 8. Notes complémentaires")
            lignes.append("- Les marges d'erreur sont données à ± demi-interquartile (bootstrap).")
            lignes.append("- Les données proviennent des fichiers de collecte et des questionnaires bruts.")
            lignes.append("- Pour toute question, contacter l'équipe de suivi.")
            return "\n".join(lignes)

        rapport = generer_rapport()
        st.text_area("Rapport généré", rapport, height=600)
        st.download_button("📥 Télécharger le rapport (.txt)", rapport, "rapport_synthese.txt")

    # ============================================================
    # 3. TABLEAUX DE SYNTHÈSE EXPORTABLES
    # ============================================================
    elif export_type == "Tableaux de synthèse (exportables)":
        st.subheader("📊 Tableaux des principaux résultats")
        st.caption("Chaque tableau peut être téléchargé individuellement en CSV.")

        # ─── 🛒 SUPERMARCHÉ ─────────────────────────
        st.markdown("### 🛒 Questionnaires Supermarché")
        if 'df_supermarche_full' in dir() and not df_supermarche_full.empty:
            df_sm_q = df_supermarche_full
            acheteurs = df_sm_q[df_sm_q['Q1'] == 'Oui']

            # Synthèse générale
            tab1 = pd.DataFrame({
                'Indicateur': ['Nb répondants', 'Nb acheteurs', 'Taux d\'achat (%)',
                               'Volume moyen (L)', 'Volume médian (L)',
                               'Prix/L moyen (FC)', 'Prix/L médian (FC)'],
                'Valeur': [len(df_sm_q), len(acheteurs), f"{len(acheteurs)/len(df_sm_q)*100:.1f}",
                           f"{acheteurs['vol_litres'].mean():.2f}" if not acheteurs.empty else "N/A",
                           f"{acheteurs['vol_litres'].median():.2f}" if not acheteurs.empty else "N/A",
                           f"{acheteurs['prix_litre'].mean():,.0f}" if not acheteurs.empty else "N/A",
                           f"{acheteurs['prix_litre'].median():,.0f}" if not acheteurs.empty else "N/A"]
            })
            st.dataframe(tab1, use_container_width=True)
            st.download_button("📥 Synthèse", tab1.to_csv(index=False), "sm_synthese.csv", key="dl_sm_synth")

            if not acheteurs.empty:
                # Fréquence d'achat
                freq_counts = acheteurs['Q6'].value_counts().reset_index()
                freq_counts.columns = ['Fréquence', 'Nb']
                st.markdown("**Fréquence d'achat**")
                st.dataframe(freq_counts, use_container_width=True)
                st.download_button("📥 Fréquence", freq_counts.to_csv(index=False), "sm_freq.csv", key="dl_sm_freq")

                # Segmentation démographique
                if 'Sexe' in acheteurs.columns and 'Tranche_age' in acheteurs.columns:
                    demo_sexe = acheteurs['Sexe'].value_counts().reset_index()
                    demo_sexe.columns = ['Sexe', 'Nb']
                    demo_age = acheteurs['Tranche_age'].value_counts().reset_index()
                    demo_age.columns = ['Âge', 'Nb']
                    st.markdown("**Segmentation démographique**")
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.dataframe(demo_sexe, use_container_width=True)
                    with col_d2:
                        st.dataframe(demo_age, use_container_width=True)
                    st.download_button("📥 Sexe", demo_sexe.to_csv(index=False), "sm_sexe.csv", key="dl_sm_sexe")
                    st.download_button("📥 Âge", demo_age.to_csv(index=False), "sm_age.csv", key="dl_sm_age")

                # Marques (top 10 avec volume moyen)
                marque_vol = acheteurs.groupby('marque_clean').agg(
                    nb=('marque_clean', 'count'),
                    vol_moy=('vol_litres', 'mean')
                ).reset_index()
                marque_vol.columns = ['Marque', 'Nb acheteurs', 'Volume moyen (L)']
                marque_vol = marque_vol.sort_values('Nb acheteurs', ascending=False).head(10)
                marque_vol['Volume moyen (L)'] = marque_vol['Volume moyen (L)'].round(2)
                st.markdown("**Top 10 marques (avec volume moyen)**")
                st.dataframe(marque_vol, use_container_width=True)
                st.download_button("📥 Marques + volume", marque_vol.to_csv(index=False), "sm_marques_vol.csv", key="dl_sm_marques_vol")

                # Raisons de choix de marque (top 10)
                if 'Q3' in acheteurs.columns:
                    raisons = acheteurs['Q3'].dropna().str.split(',').explode().str.strip()
                    raisons_counts = raisons.value_counts().head(10).reset_index()
                    raisons_counts.columns = ['Raison', 'Nb']
                    st.markdown("**Top 10 raisons de choix de marque**")
                    st.dataframe(raisons_counts, use_container_width=True)
                    st.download_button("📥 Raisons", raisons_counts.to_csv(index=False), "sm_raisons.csv", key="dl_sm_raisons")

                # Consentement à payer plus cher (taux et critères)
                if 'pret_plus' in acheteurs.columns:
                    pret_oui = acheteurs['pret_plus'].sum()
                    taux_pret = pret_oui / len(acheteurs) * 100
                    tab_consent = pd.DataFrame({
                        'Indicateur': ['Prêts à payer plus', 'Taux (%)'],
                        'Valeur': [f"{pret_oui}/{len(acheteurs)}", f"{taux_pret:.1f}"]
                    })
                    st.markdown("**Consentement à payer plus cher**")
                    st.dataframe(tab_consent, use_container_width=True)
                    st.download_button("📥 Consentement", tab_consent.to_csv(index=False), "sm_consent.csv", key="dl_sm_consent")

                    if pret_oui > 0:
                        crits = acheteurs[acheteurs['pret_plus']]['criteres_consentement'].explode().dropna()
                        crits = crits[~crits.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        crit_counts = crits.value_counts().reset_index()
                        crit_counts.columns = ['Critère', 'Nb']
                        st.markdown("**Critères invoqués**")
                        st.dataframe(crit_counts, use_container_width=True)
                        st.download_button("📥 Critères", crit_counts.to_csv(index=False), "sm_criteres.csv", key="dl_sm_criteres")

                        # Écart de prix par critère
                        df_ecart = acheteurs[acheteurs['pret_plus']].dropna(subset=['prix_num', 'prix_max_num']).copy()
                        if not df_ecart.empty:
                            df_ecart['ecart_rel'] = (df_ecart['prix_max_num'] / df_ecart['prix_num'] - 1) * 100
                            df_ecart = df_ecart[df_ecart['ecart_rel'].abs() < 1000]
                            exploded = df_ecart.explode('criteres_consentement')
                            exploded = exploded[~exploded['criteres_consentement'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                            ecart_crit = exploded.groupby('criteres_consentement')['ecart_rel'].agg(['mean', 'count']).reset_index()
                            ecart_crit.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                            ecart_crit['Écart moyen (%)'] = ecart_crit['Écart moyen (%)'].round(1)
                            st.markdown("**Écart de prix par critère de consentement**")
                            st.dataframe(ecart_crit, use_container_width=True)
                            st.download_button("📥 Écart prix", ecart_crit.to_csv(index=False), "sm_ecart_prix.csv", key="dl_sm_ecart")
        else:
            st.info("Données supermarché non disponibles.")

        # ─── 🏠 MÉNAGES ──────────────────────────────
        st.markdown("### 🏠 Questionnaires Ménages")
        if 'df_menage_unifie' in dir() and not df_menage_unifie.empty:
            df_m = df_menage_unifie
            acheteurs_m = df_m[df_m['achat_huile'].str.lower() == 'oui']

            # Synthèse
            taille_valide = df_m['taille_menage'].between(1, 20)
            tab_m1 = pd.DataFrame({
                'Indicateur': ['Nb total', 'Nb acheteurs huile', 'Taux d\'achat (%)',
                               'Taille moyenne ménage (valide)', 'Taille médiane ménage (valide)'],
                'Valeur': [len(df_m), len(acheteurs_m), f"{len(acheteurs_m)/len(df_m)*100:.1f}",
                           f"{df_m.loc[taille_valide, 'taille_menage'].mean():.1f}",
                           f"{df_m.loc[taille_valide, 'taille_menage'].median():.0f}"]
            })
            st.dataframe(tab_m1, use_container_width=True)
            st.download_button("📥 Synthèse", tab_m1.to_csv(index=False), "men_synthese.csv", key="dl_men_synth")

            # Volume / Prix
            vol_valide = df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= 50)
            prix_valide = df_m['prix_litre'].notna() & (df_m['prix_litre'] <= 10000)
            tab_m2 = pd.DataFrame({
                'Indicateur': ['Volume moyen acheté (L)', 'Volume médian (L)',
                               'Prix/L moyen (FC)', 'Prix/L médian (FC)'],
                'Valeur': [f"{df_m.loc[vol_valide, 'volume_total_l'].mean():.2f}",
                           f"{df_m.loc[vol_valide, 'volume_total_l'].median():.2f}",
                           f"{df_m.loc[prix_valide, 'prix_litre'].mean():,.0f}",
                           f"{df_m.loc[prix_valide, 'prix_litre'].median():,.0f}"]
            })
            st.dataframe(tab_m2, use_container_width=True)
            st.download_button("📥 Volume/Prix", tab_m2.to_csv(index=False), "men_vol_prix.csv", key="dl_men_volprix")

            # Fréquence d'achat (tableau)
            freq_counts = df_m.loc[acheteurs_m.index, 'frequence'].value_counts().reset_index()
            freq_counts.columns = ['Fréquence', 'Nb']
            st.markdown("**Fréquence d'achat (acheteurs)**")
            st.dataframe(freq_counts, use_container_width=True)
            st.download_button("📥 Fréquence", freq_counts.to_csv(index=False), "men_freq.csv", key="dl_men_freq")

            # Taille des ménages par zone socio‑économique
            if 'zone_socioeco' in df_m.columns:
                zone_taille = df_m[taille_valide & (df_m['zone_socioeco'] != 'Inconnu')].groupby('zone_socioeco')['taille_menage'].agg(['mean', 'median', 'count']).reset_index()
                zone_taille.columns = ['Zone', 'Taille moyenne', 'Taille médiane', 'Nb ménages']
                st.markdown("**Taille des ménages par zone socio‑économique**")
                st.dataframe(zone_taille, use_container_width=True)
                st.download_button("📥 Taille par zone", zone_taille.to_csv(index=False), "men_taille_zone.csv", key="dl_men_taille_zone")

            # Volume acheté par tranches (camembert)
            vol_tranches = df_m[df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= 50)].copy()
            if not vol_tranches.empty:
                def tranche_vol(x):
                    if x < 0.5: return '<0,5 L'
                    elif x <= 1: return '0,5-1 L'
                    elif x <= 2: return '1-2 L'
                    elif x <= 3: return '2-3 L'
                    elif x <= 4: return '3-4 L'
                    elif x <= 5: return '4-5 L'
                    else: return '>5 L'
                vol_tranches['Tranche'] = vol_tranches['volume_total_l'].apply(tranche_vol)
                tranche_counts = vol_tranches['Tranche'].value_counts().reset_index()
                tranche_counts.columns = ['Tranche', 'Nb']
                ordre = ['<0,5 L', '0,5-1 L', '1-2 L', '2-3 L', '3-4 L', '4-5 L', '>5 L']
                tranche_counts['Tranche'] = pd.Categorical(tranche_counts['Tranche'], categories=ordre, ordered=True)
                tranche_counts = tranche_counts.sort_values('Tranche')
                st.markdown("**Volume acheté par tranches**")
                st.dataframe(tranche_counts, use_container_width=True)
                st.download_button("📥 Volumes par tranche", tranche_counts.to_csv(index=False), "men_vol_tranches.csv", key="dl_men_tranches")

            # Consentement à payer plus (taux, critères)
            if 'pret_plus' in df_m.columns:
                pret_oui_m = df_m['pret_plus'].sum()
                pret_total = df_m['pret_payer_plus'].notna().sum()
                if pret_total > 0:
                    tab_consent_m = pd.DataFrame({
                        'Indicateur': ['Prêts à payer plus', 'Taux (%)'],
                        'Valeur': [f"{pret_oui_m}/{pret_total}", f"{pret_oui_m/pret_total*100:.1f}"]
                    })
                    st.markdown("**Consentement à payer plus cher**")
                    st.dataframe(tab_consent_m, use_container_width=True)
                    st.download_button("📥 Consentement", tab_consent_m.to_csv(index=False), "men_consent.csv", key="dl_men_consent")
                    if pret_oui_m > 0:
                        crits_m = df_m[df_m['pret_plus']]['criteres'].explode().dropna()
                        crits_m = crits_m[~crits_m.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        crit_counts_m = crits_m.value_counts().reset_index()
                        crit_counts_m.columns = ['Critère', 'Nb']
                        st.markdown("**Critères invoqués**")
                        st.dataframe(crit_counts_m, use_container_width=True)
                        st.download_button("📥 Critères", crit_counts_m.to_csv(index=False), "men_criteres.csv", key="dl_men_criteres")
                        # Écart de prix par critère
                        df_ecart_m = df_m[df_m['pret_plus']].dropna(subset=['prix_num', 'prix_max']).copy()
                        if not df_ecart_m.empty:
                            df_ecart_m['ecart_rel'] = (pd.to_numeric(df_ecart_m['prix_max'], errors='coerce') / pd.to_numeric(df_ecart_m['prix_num'], errors='coerce') - 1) * 100
                            df_ecart_m = df_ecart_m[df_ecart_m['ecart_rel'].notna() & (df_ecart_m['ecart_rel'].abs() < 1000)]
                            exploded_m = df_ecart_m.explode('criteres')
                            exploded_m = exploded_m[~exploded_m['criteres'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                            ecart_crit_m = exploded_m.groupby('criteres')['ecart_rel'].agg(['mean', 'count']).reset_index()
                            ecart_crit_m.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                            ecart_crit_m['Écart moyen (%)'] = ecart_crit_m['Écart moyen (%)'].round(1)
                            st.markdown("**Écart de prix par critère de consentement**")
                            st.dataframe(ecart_crit_m, use_container_width=True)
                            st.download_button("📥 Écart prix", ecart_crit_m.to_csv(index=False), "men_ecart_prix.csv", key="dl_men_ecart")

            # Perception de la qualité
            if 'qualite' in df_m.columns:
                qual_ser = df_m['qualite'].dropna().astype(str).str.split(',').explode().str.strip()
                qual_ser = qual_ser[qual_ser != '']
                qual_counts = qual_ser.value_counts().reset_index()
                qual_counts.columns = ['Critère', 'Nb']
                st.markdown("**Perception de la qualité**")
                st.dataframe(qual_counts, use_container_width=True)
                st.download_button("📥 Qualité", qual_counts.to_csv(index=False), "men_qualite.csv", key="dl_men_qualite")

            # Qualités RougeCongo
            if 'rc_qualites' in df_m.columns:
                rc_qual = df_m['rc_qualites'].dropna().astype(str).str.split(',').explode().str.strip()
                rc_qual = rc_qual[rc_qual != '']
                rc_qual_counts = rc_qual.value_counts().reset_index()
                rc_qual_counts.columns = ['Qualité', 'Nb']
                st.markdown("**Qualités attribuées à RougeCongo**")
                st.dataframe(rc_qual_counts, use_container_width=True)
                st.download_button("📥 Qualités RC", rc_qual_counts.to_csv(index=False), "men_rc_qual.csv", key="dl_men_rc_qual")

            # Lieux d'achat (parts moyennes)
            if 'pourcentages_achat' in df_m.columns:
                df_pct = df_m[df_m['type_original'].isin(['menage', 'supermarche_menage'])].dropna(subset=['pourcentages_achat'])
                if not df_pct.empty:
                    records = []
                    for _, row in df_pct.iterrows():
                        texte = row['pourcentages_achat']
                        if not isinstance(texte, str): continue
                        for part in texte.split(','):
                            part = part.strip()
                            if ':' not in part: continue
                            cat, pct_str = part.split(':', 1)
                            pct = pd.to_numeric(pct_str.strip().replace('%', ''), errors='coerce')
                            if pd.notna(pct):
                                records.append({'Catégorie': cat.strip(), 'Pourcentage': pct})
                    if records:
                        df_lieux = pd.DataFrame(records)
                        lieu_moy = df_lieux.groupby('Catégorie')['Pourcentage'].mean().reset_index()
                        lieu_moy.columns = ['Canal', 'Part moyenne (%)']
                        lieu_moy['Part moyenne (%)'] = lieu_moy['Part moyenne (%)'].round(1)
                        st.markdown("**Lieux d'achat – part moyenne**")
                        st.dataframe(lieu_moy, use_container_width=True)
                        st.download_button("📥 Lieux d'achat", lieu_moy.to_csv(index=False), "men_lieux.csv", key="dl_men_lieux")

            # Segmentation par sexe/âge
            if 'Sexe' in df_m.columns and 'Tranche_age' in df_m.columns:
                seg_sexe = df_m['Sexe'].value_counts().reset_index()
                seg_sexe.columns = ['Sexe', 'Nb']
                seg_age = df_m['Tranche_age'].value_counts().reset_index()
                seg_age.columns = ['Âge', 'Nb']
                st.markdown("**Segmentation démographique**")
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.dataframe(seg_sexe, use_container_width=True)
                with col_m2:
                    st.dataframe(seg_age, use_container_width=True)
                st.download_button("📥 Sexe", seg_sexe.to_csv(index=False), "men_sexe.csv", key="dl_men_sexe")
                st.download_button("📥 Âge", seg_age.to_csv(index=False), "men_age.csv", key="dl_men_age")
        else:
            st.info("Données ménages non disponibles.")

        # ─── 🚶 COMPTAGES & FLUX ────────────────────────
        st.markdown("### 🚶 Comptages & Flux")
        if not df_c_f.empty:
            heures_sem = df_c_f[df_c_f['date_dt'].dt.weekday < 5]['duree_h'].sum()
            heures_we  = df_c_f[df_c_f['date_dt'].dt.weekday >= 5]['duree_h'].sum()
            nb_sessions = len(df_c_f)
            tab_c1 = pd.DataFrame({
                'Indicateur': ['Nb sessions', 'Heures semaine', 'Heures week-end', 'Magasins suivis'],
                'Valeur': [nb_sessions, f"{heures_sem:.1f}", f"{heures_we:.1f}", df_c_f['lieu_officiel'].nunique()]
            })
            st.dataframe(tab_c1, use_container_width=True)
            st.download_button("📥 Synthèse comptages", tab_c1.to_csv(index=False), "compt_synthese.csv", key="dl_compt_synth")

            # Fréquentation par magasin
            if st.session_state.get('freq_magasin') is not None:
                st.markdown("**Fréquentation estimée par magasin**")
                st.dataframe(st.session_state['freq_magasin'], use_container_width=True)
                st.download_button("📥 Télécharger (CSV)", st.session_state['freq_magasin'].to_csv(index=False),
                                   "compt_freq_magasin.csv", key="dl_compt_freq_mag")
            else:
                st.info("Tableau de fréquentation par magasin non disponible (ouvrez l'onglet Comptages & Flux).")

            # Fréquentation par segment
            if st.session_state.get('freq_segment') is not None:
                st.markdown("**Fréquentation par segment (taille × niveau)**")
                st.dataframe(st.session_state['freq_segment'], use_container_width=True)
                st.download_button("📥 Télécharger (CSV)", st.session_state['freq_segment'].to_csv(index=False),
                                   "compt_freq_segment.csv", key="dl_compt_freq_seg")
            else:
                st.info("Tableau par segment non disponible.")

            # Facteurs k (si présents)
            if st.session_state.get('k_summary') is not None:
                st.markdown("**Facteurs k par magasin**")
                st.dataframe(st.session_state['k_summary'], use_container_width=True)
                st.download_button("📥 Facteurs k", st.session_state['k_summary'].to_csv(index=False), "compt_k.csv", key="dl_compt_k")
        else:
            st.info("Données de comptage non disponibles.")

        # ─── 📊 ESTIMATION DU MARCHÉ ──────────────────
        st.markdown("### 📊 Estimation du marché")
        total_A = st.session_state.get('total_A_med', None)
        demi_A = st.session_state.get('demi_iqr_total_A', None)
        total_B = st.session_state.get('total_med_B', None)
        demi_B = st.session_state.get('total_demi_iqr_B', None)
        total_C = st.session_state.get('vol_annuel_med_C', None)
        demi_C = st.session_state.get('demi_iqr_annuel_C', None)

        methods = []
        if total_A is not None:
            methods.append({'Méthode': 'A (strates)', 'Volume annuel': f"{fmt_volume(total_A)} L ± {fmt_volume(demi_A)} L"})
        if total_B is not None:
            methods.append({'Méthode': 'B (démographique)', 'Volume annuel': f"{fmt_volume(total_B)} L ± {fmt_volume(demi_B)} L"})
        if total_C is not None:
            methods.append({'Méthode': 'C (directe)', 'Volume annuel': f"{fmt_volume(total_C)} L ± {fmt_volume(demi_C)} L"})
        if methods:
            df_methods = pd.DataFrame(methods)
            st.dataframe(df_methods, use_container_width=True)
            st.download_button("📥 Synthèse méthodes", df_methods.to_csv(index=False), "estim_methodes.csv", key="dl_estim_methodes")

        # Détail des strates
        if st.session_state.get('strates_A') is not None:
            st.markdown("**Détail par strate (Méthode A)**")
            st.dataframe(st.session_state['strates_A'], use_container_width=True)
            st.download_button("📥 Strates", st.session_state['strates_A'].to_csv(index=False), "estim_strates.csv", key="dl_estim_strates")
        else:
            st.info("Tableau des strates non disponible (ouvrez l'onglet Estimation).")

        # Volume par magasin
        if st.session_state.get('magasins_volumes') is not None:
            st.markdown("**Volumes estimés par magasin**")
            st.dataframe(st.session_state['magasins_volumes'], use_container_width=True)
            st.download_button("📥 Volumes/magasin", st.session_state['magasins_volumes'].to_csv(index=False), "estim_magasins.csv", key="dl_estim_magasins")
        else:
            st.info("Tableau des magasins non disponible.")

        # ─── 🏷️ PRIX & CONCURRENCE ────────────────────
        st.markdown("### 🏷️ Prix & Concurrence")
        if 'df_prices_ext' in dir() and not df_prices_ext.empty:
            # S'assurer que la colonne prix_unitaire_FC existe
            if 'prix_unitaire_FC' not in df_prices_ext.columns:
                # La créer si les colonnes nécessaires existent
                if 'prix' in df_prices_ext.columns and 'volume_L' in df_prices_ext.columns:
                    df_prices_ext['prix_unitaire_FC'] = df_prices_ext['prix'] / df_prices_ext['volume_L']
                elif 'conditionnement' in df_prices_ext.columns and 'prix' in df_prices_ext.columns:
                    # Extraire le volume depuis le conditionnement si possible
                    df_prices_ext['volume_L'] = df_prices_ext['conditionnement'].apply(extraire_litres)
                    df_prices_ext['prix_unitaire_FC'] = df_prices_ext['prix'] / df_prices_ext['volume_L']
                else:
                    st.warning("Impossible de calculer le prix unitaire, colonnes manquantes.")
                    # Ne pas continuer l'affichage des métriques liées au prix unitaire
                    st.stop()  # ou passer à la suite

            # Maintenant on peut utiliser la colonne en toute sécurité
            prix_moy = df_prices_ext['prix_unitaire_FC'].mean()
            nb_releves = len(df_prices_ext)
            nb_marques = df_prices_ext['marque_officielle'].nunique() if 'marque_officielle' in df_prices_ext.columns else 0
            tab_p1 = pd.DataFrame({
                'Indicateur': ['Nb relevés', 'Nb marques', 'Prix/L moyen (FC)'],
                'Valeur': [nb_releves, nb_marques, f"{prix_moy:,.0f}"]
            })
            st.dataframe(tab_p1, use_container_width=True)
            st.download_button("📥 Synthèse prix", tab_p1.to_csv(index=False), "prix_synthese.csv", key="dl_prix_synth")

            # Prix par conditionnement (vérifier aussi l'existence des colonnes)
            if 'conditionnement' in df_prices_ext.columns and 'prix_unitaire_FC' in df_prices_ext.columns:
                cond_prix = df_prices_ext.groupby('conditionnement')['prix_unitaire_FC'].agg(['mean', 'median', 'count']).reset_index()
                cond_prix.columns = ['Conditionnement', 'Prix moyen (FC/L)', 'Prix médian (FC/L)', 'Nb relevés']
                cond_prix['Prix moyen (FC/L)'] = cond_prix['Prix moyen (FC/L)'].round(0)
                cond_prix['Prix médian (FC/L)'] = cond_prix['Prix médian (FC/L)'].round(0)
                st.markdown("**Prix par conditionnement**")
                st.dataframe(cond_prix, use_container_width=True)
                st.download_button("📥 Prix/cond.", cond_prix.to_csv(index=False), "prix_conditionnement.csv", key="dl_prix_cond")

            # Distribution des prix par marque (vérifier colonnes)
            if 'marque_officielle' in df_prices_ext.columns and 'prix_unitaire_FC' in df_prices_ext.columns:
                marque_prix_stats = df_prices_ext.groupby('marque_officielle')['prix_unitaire_FC'].describe(percentiles=[.25, .5, .75]).reset_index()
                marque_prix_stats.columns = ['Marque', 'Nb', 'Moyenne', 'Écart-type', 'Min', 'Q1', 'Médiane', 'Q3', 'Max']
                st.markdown("**Distribution des prix par marque**")
                st.dataframe(marque_prix_stats, use_container_width=True)
                st.download_button("📥 Stats prix/marque", marque_prix_stats.to_csv(index=False), "prix_stats_marque.csv", key="dl_prix_stats_marque")
        else:
            st.info("Données de prix externes non chargées.")

        # ─── 🏪 PROFIL SUPERMARCHÉS ────────────────────
        st.markdown("### 🏪 Profil des supermarchés recensés")
        if not df_sm.empty:
            # Taille
            taille_counts = df_sm['Taille'].value_counts().reset_index()
            taille_counts.columns = ['Taille', 'Nb']
            st.markdown("**Répartition par taille**")
            st.dataframe(taille_counts, use_container_width=True)
            st.download_button("📥 Taille", taille_counts.to_csv(index=False), "profil_taille.csv", key="dl_profil_taille")

            # Niveau socio
            socio_counts = df_sm['Niveau_socio'].value_counts().reset_index()
            socio_counts.columns = ['Niveau', 'Nb']
            st.markdown("**Répartition par niveau socio-économique**")
            st.dataframe(socio_counts, use_container_width=True)
            st.download_button("📥 Niveau", socio_counts.to_csv(index=False), "profil_socio.csv", key="dl_profil_socio")

            # Présence d'huile
            price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
            if price_cols:
                df_sm['Presence_huile'] = (df_sm[price_cols] > 0).any(axis=1)
                huile_counts = df_sm['Presence_huile'].value_counts().reset_index()
                huile_counts.columns = ['Huile présente', 'Nb']
                st.markdown("**Présence d'huile**")
                st.dataframe(huile_counts, use_container_width=True)
                st.download_button("📥 Huile", huile_counts.to_csv(index=False), "profil_huile.csv", key="dl_profil_huile")
        else:
            st.info("Données supermarchés non chargées.")