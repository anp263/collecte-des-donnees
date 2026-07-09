# dashboard.py – Tableau de bord complet enrichi
import os
import sys
import streamlit as st
# Cache vidé une fois (le parsing JSON est maintenant dans le flux principal) - à retirer après
import pandas as pd
import sqlite3
import matplotlib.font_manager as fm
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import re
import datetime
import uuid
import time
import time as _time_module
ENABLE_TIMING = False
ENABLE_TIMING = False
def timed(func):
    """Décorateur inactif."""
    return func
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
def force_black_axes(fig, title_size=18, tick_size=15, caption=None):
    """
    Applique une police noire et des tailles explicites à tous les axes,
    aux légendes, annotations et titres d'une figure Plotly.
    Peut aussi ajouter un caption intégré dans la figure (exportable).
    """
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
        fig.add_annotation(
            text=caption,
            xref="paper", yref="paper",
            x=0.02, y=-0.12,
            showarrow=False,
            font=dict(size=11, color="black", family="Gilroy, sans-serif")
        )
        fig.update_layout(margin=dict(b=80))
    return fig
# ------------------------------------------------------------
# Surcharge de st.plotly_chart pour ajouter le téléchargement
# ------------------------------------------------------------
# Récupérer les dimensions depuis la session (avec des valeurs par défaut)
if "export_width" not in st.session_state:
    st.session_state.export_width = 1000
if "export_height" not in st.session_state:
    st.session_state.export_height = 600
# Sauvegarde de la fonction originale
_original_plotly_chart = st.plotly_chart
import hashlib as _hashlib
# Compteur global unique pour garantir des clés uniques entre toutes les figures
if 'dl_global_counter' not in st.session_state:
    st.session_state.dl_global_counter = 0
def plotly_chart_with_download(figure_or_data, *args, **kwargs):
    """
    Affiche un graphique Plotly et ajoute un bouton de téléchargement PNG.
    Chaque bouton a une clé ABSOLUMENT unique (hash + compteur global),
    ce qui évite les doublons entre re-rendus.
    """
    _original_plotly_chart(figure_or_data, *args, **kwargs)
    import plotly.graph_objects as go
    if not isinstance(figure_or_data, go.Figure):
        return
    fig = figure_or_data
    width = st.session_state.get("export_width", 1000)
    height = st.session_state.get("export_height", 600)
    try:
        img_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
        # Clé = hash + compteur global unique
        fig_hash = _hashlib.md5(fig.to_json().encode()).hexdigest()[:12]
        st.session_state.dl_global_counter += 1
        ctr = st.session_state.dl_global_counter
        key = f"dl_{ctr}_{fig_hash}"
        st.download_button(
            label="📥 Télécharger ce graphique (PNG)",
            data=img_bytes,
            file_name=f"plot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{fig_hash}.png",
            mime="image/png",
            key=key
        )
    except Exception as e:
        st.warning(f"Téléchargement non disponible : {e}")
# Remplacer la fonction native par notre version
st.plotly_chart = plotly_chart_with_download
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
# ============================================================
# Imports des modules optimisés
# ============================================================
import config
from utils import (
    make_hashable, deserialize_obj_cols, fmt_volume, fmt_prix, fmt_nombre,
    normalize_name, normalize_brand, similar, parse_gps, haversine,
    extraire_litres, parse_time, load_brand_mapping, save_brand_mapping,
    get_official_brands, apply_brand_mapping_strict, apply_brand_mapping_soft,
    load_commune_niveau, save_commune_niveau, get_settings_hash, get_sm_hash
)
from data_loader import load_db, load_supermarches, load_frequentation_data
from anomalies import (
    load_anomaly_settings, save_anomaly_settings,
    validate_questionnaire_dynamic, validate_counting_dynamic, validate_price_dynamic,
    compute_context_anomalies_questionnaire_dynamic, compute_context_anomalies_counting_dynamic,
    init_anomalies_table, load_anomalies_from_db, save_anomalies_to_db
)
from analytics import (
    get_profile_for_day, get_opening_hours, cached_compute_k_factors,
    compute_k_factors, estimate_daily_flow, load_k_overrides, save_k_overrides,
    prepare_supermarche_data
)
st.set_page_config(page_title="Dashboard Huile de Palme", layout="wide")
st.title("📊 Étude de marché – Huile de palme rouge à Kinshasa")
# ============================================================
# Constantes et chemins
# ============================================================
# ============================================================
# Connexion DB avec cache et index optimisés
# ============================================================
DB_PATH = "consolidated.db"
@st.cache_resource
def get_db_connection():
    """Retourne une connexion SQLite (multithread-safe)."""
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-200000")  # 200 MB cache
    _ensure_db_indexes(conn)
    return conn
def _ensure_db_indexes(conn):
    """Crée les index SQL essentiels pour accélérer les requêtes."""
    c = conn.cursor()
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_q_uuid ON questionnaires(uuid)",
        "CREATE INDEX IF NOT EXISTS idx_q_enqueteur ON questionnaires(enqueteur)",
        "CREATE INDEX IF NOT EXISTS idx_q_date ON questionnaires(date)",
        "CREATE INDEX IF NOT EXISTS idx_q_type ON questionnaires(type)",
        "CREATE INDEX IF NOT EXISTS idx_q_lieu ON questionnaires(lieu)",
        "CREATE INDEX IF NOT EXISTS idx_c_uuid ON countings(uuid)",
        "CREATE INDEX IF NOT EXISTS idx_c_lieu ON countings(lieu)",
        "CREATE INDEX IF NOT EXISTS idx_c_date ON countings(date)",
        "CREATE INDEX IF NOT EXISTS idx_p_uuid ON prices(uuid)",
        "CREATE INDEX IF NOT EXISTS idx_p_date ON prices(date)",
        "CREATE INDEX IF NOT EXISTS idx_p_supermarche ON prices(supermarche)",
    ]
    for idx in indexes:
        try:
            c.execute(idx)
        except:
            pass
    conn.commit()
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
def make_hashable(df):
    """Convertit TOUTES les colonnes object contenant listes/dicts en JSON. Version la plus simple possible."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            try:
                # Vérifier si au moins une valeur est non-hashable
                test_vals = [v for v in df[col].dropna().values[:50] if v is not None]
                if test_vals and not all(isinstance(v, str) for v in test_vals):
                    df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x)
            except:
                pass
    return df
def deserialize_obj_cols(df):
    """Convertit les chaînes JSON en dict/list pour restaurer les types originaux."""
    df = df.copy()
    for col in df.columns:
        # Vérifier si les valeurs ressemblent à du JSON
        if df[col].apply(
            lambda x: isinstance(x, str) and (x.startswith('{') or x.startswith('['))
        ).any():
            df[col] = df[col].apply(
                lambda x: json.loads(x) if isinstance(x, str) and (x.startswith('{') or x.startswith('[')) else x
            )
    return df
def get_top8_brands_from_acheteurs(df_acheteurs):
    """
    Retourne la liste des 8 marques les plus achetées (par nombre d'acheteurs)
    à partir d'un DataFrame d'acheteurs (avec colonne 'marque_clean').
    """
    if df_acheteurs.empty or 'marque_clean' not in df_acheteurs.columns:
        return []
    counts = df_acheteurs['marque_clean'].value_counts()
    return counts.head(8).index.tolist()
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
@timed
@st.cache_data(ttl=3600, show_spinner="Chargement des données…")
def load_db_internal():
    """Charge les données depuis SQLite. Ne crée PAS data_dict/anomalies_list ici.
    Ces colonnes seront créées APRES le cache dans le flux principal."""
    import time as _tmod
    _t0 = _tmod.time()
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), \
               "Fichier 'consolidated.db' introuvable. Exécutez d'abord process_daily.py."
    try:
        conn = get_db_connection()
        if conn is None:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "Connexion DB impossible."
        _t1 = _tmod.time()
        df_q = pd.read_sql("SELECT uuid, type, date, heure, lieu, enqueteur, test_mode, statut, anomalies, data FROM questionnaires", conn)
        print(f"[DEBUG] load_db: questionnaires = {len(df_q)} lignes ({_tmod.time()-_t1:.1f}s)")
        _t2 = _tmod.time()
        df_c = pd.read_sql("SELECT uuid, date, debut, fin, lieu, enqueteur, test_mode, total, anomalies, data FROM countings", conn)
        print(f"[DEBUG] load_db: countings = {len(df_c)} lignes ({_tmod.time()-_t2:.1f}s)")
        _t3 = _tmod.time()
        df_p = pd.read_sql("SELECT uuid, date, supermarche, marque, conditionnement, prix, enqueteur, test_mode, anomalies, data FROM prices", conn)
        print(f"[DEBUG] load_db: prices = {len(df_p)} lignes ({_tmod.time()-_t3:.1f}s)")
    except sqlite3.Error as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), f"Erreur de lecture de la base : {e}"
    # PAS de parsing JSON ici ! Colonnes 'data' et 'anomalies' restent JSON strings.
    # PAS de make_hashable non plus (DataFrame déjà hashable sans colonnes dict/list)
    if 'statut' not in df_q.columns:
        df_q['statut'] = 'Accepté'
    print(f"[DEBUG] load_db: TEMPS TOTAL = {_tmod.time()-_t0:.1f}s (3 requetes SQL seulement)")
    return df_q, df_c, df_p, None
def load_db():
    df_q, df_c, df_p, err = load_db_internal()
    if err:
        st.error(err)
    return df_q, df_c, df_p
@timed
def prepare_supermarche_data(df_supermarche_full):
    """Ajoute les colonnes dérivées (Sexe, Âge, Tranche_age, consentement) et retourne un tuple (df_enrichi, acheteurs_global_full)."""
    # ⬇️ Désérialisation
    df_supermarche_full = deserialize_obj_cols(df_supermarche_full)
    df = df_supermarche_full.copy()
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
    def tranche_age(age_str):
        if not age_str: return 'Inconnu'
        try:
            age = int(re.search(r'\d+', age_str).group())
            if age < 25: return 'Moins de 25 ans'
            elif age < 35: return '25-34 ans'
            elif age < 50: return '35-49 ans'
            else: return '50 ans et plus'
        except: return 'Inconnu'
    df['Sexe'] = df['SexeAge'].apply(get_sexe)
    df['Âge'] = df['SexeAge'].apply(get_age)
    df['Tranche_age'] = df['Âge'].apply(tranche_age)
    if 'statut' in df.columns:
        df_valides = df[df['statut'] != 'Refus'].copy()
    else:
        df_valides = df.copy()
    acheteurs_global_full = df_valides[df_valides['Q1'] == 'Oui'].copy()
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
    return make_hashable(df), make_hashable(acheteurs_global_full)
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
    return out, df_prices_ext
# ============================================================
# Chargement des données d'affluence
# ============================================================
@timed
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
@timed
def cached_compute_k_factors(magasin, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping):
    # Désérialisation
    df_c_f = deserialize_obj_cols(df_c_f)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)
    comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
    if comptages.empty:
        return None, []
    k_list = []
    details = []
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
        k_list.append(k)
        details.append({
            'date': date_obj.strftime('%Y-%m-%d'),
            'type': 'weekend' if date_obj.weekday() >= 5 else 'semaine',
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
    k = np.median(k_list) if k_list else None
    return k, details
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
    def parse_horaire(h_str, is_closing=False):
        s = h_str.strip().upper().replace(' ', '')
        # Remplacer 'H' par ':' si présent
        if 'H' in s and ':' not in s:
            s = re.sub(r'H', ':', s)
        # Si pas de ':' et que c'est un nombre, ajouter ":00"
        if ':' not in s and s.isdigit():
            s = s + ':00'
        # Gérer les minutes sans séparateur (ex: "2230" -> "22:30")
        if ':' not in s and len(s) == 4 and s.isdigit():
            s = s[:2] + ':' + s[2:]
        try:
            t = datetime.strptime(s, '%H:%M')
            h, m = t.hour, t.minute
            if is_closing and h == 0 and m == 0:
                h = 24
            return h, m
        except:
            # Valeur par défaut : 8h00 pour l'ouverture, 18h00 pour la fermeture
            return (8, 0) if not is_closing else (18, 0)
    h_ouv, m_ouv = parse_horaire(ouverture, is_closing=False)
    h_ferm, m_ferm = parse_horaire(fermeture, is_closing=True)
    # Convertir en minutes
    ouv_min = h_ouv * 60 + m_ouv
    ferm_min = h_ferm * 60 + m_ferm
    # Si fermeture <= ouverture, ajouter 24h (gère le passage à minuit)
    if ferm_min <= ouv_min:
        ferm_min += 24 * 60
    ouvert = [False] * 24
    for h in range(24):
        debut = h * 60
        fin = (h + 1) * 60
        if debut < ferm_min and fin > ouv_min:
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
# Parsing JSON à la volée : on va remplacer les row['data_dict'] par _get_data(row)
# et row['anomalies_list'] par _get_anom(row)
import json as _json
for _df in [df_q, df_c, df_p]:
    if 'data' in _df.columns:
        _df['data_dict'] = _df['data'].apply(lambda x: _json.loads(x) if isinstance(x, str) and len(x) > 0 else {})
    if 'anomalies' in _df.columns:
        _df['anomalies_list'] = _df['anomalies'].apply(lambda x: _json.loads(x) if isinstance(x, str) and len(x) > 0 else [])
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
with st.sidebar:
    st.markdown("---")
    st.header("📐 Taille des graphiques exportés")
    st.session_state.export_width = st.slider("Largeur (px)", 400, 2000, 1000, step=50)
    st.session_state.export_height = st.slider("Hauteur (px)", 300, 1500, 600, step=50)
with st.sidebar:
    if st.button("Tester hachage"):
        try:
            _ = st.cache_data(lambda x: x)(pd.DataFrame({'a': [1,2], 'b': [{'c':3}]}))
        except Exception as e:
            st.error(f"Erreur de hachage : {e}")
        else:
            st.success("Hachage OK")
with st.sidebar:
    st.markdown("---")
    st.header("⚡ Cache")
with st.sidebar:
    st.markdown("---")
    pass
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
            conn = get_db_connection()
            if conn is not None:
                conn.execute("DELETE FROM questionnaires")
                conn.execute("DELETE FROM countings")
                conn.execute("DELETE FROM prices")
                conn.commit()
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
@timed
def compute_all_k_data(selected_mags_tuple, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping, k_overrides):
    # Désérialisation pour compatibilité cache
    df_c_f = deserialize_obj_cols(df_c_f)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)
    selected_mags = list(selected_mags_tuple)
    all_k_data = {}
    for mag in selected_mags:
        k, details = cached_compute_k_factors(mag, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping)
        over = k_overrides.get(mag, {})
        if 'k' in over:
            k = over['k']
        all_k_data[mag] = {'k': k, 'details': details}
    return all_k_data
@timed
def prepare_menage_unifie(df_q_f_raw, df_sm, commune_niveau):
    # ⬇️ Désérialisation pour compatibilité cache
    df_q_f_raw = deserialize_obj_cols(df_q_f_raw)
    """
    Construit le DataFrame unifié des ménages (tous types : menage, supermarche, supermarche_menage)
    avec toutes les colonnes dérivées nécessaires aux analyses de l'onglet 3.
    """
    df_source = df_q_f_raw[df_q_f_raw['type'].isin(['menage', 'supermarche', 'supermarche_menage'])].copy()
    rows_unified = []
    for _, row in df_source.iterrows():
        qtype = row['type']
        data = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
        # --- Détermination de la catégorie ---
        if qtype == 'supermarche':
            achat = str(data.get('Q1_Achat', '')).strip().lower()
            if achat != 'oui':
                continue
            cat = 'Acheteur supermarché'
        elif qtype == 'supermarche_menage':
            cat = 'Non-acheteur supermarché'
        else:
            cat = 'Ménage pur'
        # --- Extraction des champs communs et spécifiques ---
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
    if df_menage_unifie.empty:
        return df_menage_unifie
    # --- Conversions et calculs ---
    df_menage_unifie['quantite_nombre'] = pd.to_numeric(
        df_menage_unifie['quantite_nombre'].astype(str).str.replace(',', '.'), errors='coerce')
    df_menage_unifie['quantite_nombre'] = df_menage_unifie['quantite_nombre'].replace(0, 1)
    df_menage_unifie['volume_unitaire_l'] = pd.to_numeric(
        df_menage_unifie['volume_unitaire_l'].astype(str).str.replace(',', '.'), errors='coerce')
    seuil_ml = 50
    mask_ml = df_menage_unifie['volume_unitaire_l'] > seuil_ml
    df_menage_unifie.loc[mask_ml, 'volume_unitaire_l'] /= 1000
    mask_pur_sm = df_menage_unifie['type_original'].isin(['menage', 'supermarche_menage'])
    df_menage_unifie['volume_total_l'] = np.nan
    if mask_pur_sm.any():
        nb = df_menage_unifie.loc[mask_pur_sm, 'quantite_nombre']
        vol_unit = df_menage_unifie.loc[mask_pur_sm, 'volume_unitaire_l']
        df_menage_unifie.loc[mask_pur_sm, 'volume_total_l'] = nb * vol_unit
    mask_s = df_menage_unifie['type_original'] == 'supermarche'
    if mask_s.any():
        df_menage_unifie.loc[mask_s, 'volume_total_l'] = df_menage_unifie.loc[mask_s, 'volume_total_l_supermarche']
    df_menage_unifie['prix_num'] = pd.to_numeric(
        df_menage_unifie['prix_paye'].astype(str).str.replace(',', '.'), errors='coerce')
    df_menage_unifie['prix_litre'] = np.where(
        (df_menage_unifie['volume_total_l'].notna()) & (df_menage_unifie['volume_total_l'] > 0) & (df_menage_unifie['prix_num'].notna()),
        df_menage_unifie['prix_num'] / df_menage_unifie['volume_total_l'],
        np.nan
    )
    # Correction de la ligne problématique (ChainedAssignment)
    df_menage_unifie['prix_litre'] = df_menage_unifie['prix_litre'].replace([np.inf, -np.inf], np.nan)
    df_menage_unifie['taille_menage'] = pd.to_numeric(df_menage_unifie['nb_personnes'], errors='coerce')
    # --- Marque nettoyée ---
    df_menage_unifie['marque_clean'] = apply_brand_mapping_strict(df_menage_unifie['marque_preferee'])
    mask_sm_menage = df_menage_unifie['type_original'] == 'supermarche_menage'
    df_menage_unifie.loc[mask_sm_menage & (df_menage_unifie['marque_clean'] == 'mbila'), 'marque_clean'] = 'En vrac'
    # --- Consentement à payer plus ---
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
    # --- Fréquence numérique ---
    freq_map = {
        'Plusieurs fois par semaine': 8,
        'Une fois par semaine': 4,
        'Deux à trois fois par mois': 2.5,
        'Une fois par mois': 1,
        'Une fois par trimestre': 0.33,
        'Moins souvent': 0.166
    }
    df_menage_unifie['frequence'] = df_menage_unifie['frequence'].astype(str).str.strip()
    df_menage_unifie.loc[df_menage_unifie['frequence'].str.match(r'^\d+(\.\d+)?$'), 'frequence'] = np.nan
    df_menage_unifie['freq_num'] = df_menage_unifie['frequence'].map(freq_map)
    # --- Zone socioéconomique ---
    sm_niveau = dict(zip(df_sm['Nom'].apply(normalize_name), df_sm['Niveau_socio'])) if not df_sm.empty else {}
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
        commune_niveau_norm = {normalize_name(k): v for k, v in commune_niveau.items()}
        def zone_from_commune(commune):
            if not isinstance(commune, str) or commune.strip() == '':
                return 'Inconnu'
            return commune_niveau_norm.get(normalize_name(commune), 'Non classé')
        df_menage_unifie.loc[mask_m, 'zone_socioeco'] = df_menage_unifie.loc[mask_m, 'commune'].apply(zone_from_commune)
    df_menage_unifie['zone_socioeco'] = df_menage_unifie['zone_socioeco'].replace('', 'Inconnu').fillna('Inconnu')
    if 'statut' in df_menage_unifie.columns:
        df_menage_unifie = df_menage_unifie[df_menage_unifie['statut'] != 'Refus'].copy()
    return make_hashable(df_menage_unifie)
# --------------------------------------------------------------------
# Fonctions cachées pour l'onglet 5 (Estimation du marché)
# --------------------------------------------------------------------
@timed
def compute_market_estimation(
    selected_mags_tuple,
    df_c_f,
    df_supermarche_full,
    df_sm,
    df_q_f_raw,
    df_profils_pivot,
    secteur_profiles,
    magasin_mapping,
    pop_aisée_min, pop_aisée_max,
    pop_moyenne_min, pop_moyenne_max,
    pop_populaire_min, pop_populaire_max,
    all_k_data=None
):
    """
    Retourne un dictionnaire contenant toutes les grandeurs calculées par l'onglet 5.
    """
    # --- Désérialisation des colonnes JSON (cache compatible) ---
    df_c_f = deserialize_obj_cols(df_c_f)
    df_supermarche_full = deserialize_obj_cols(df_supermarche_full)
    df_q_f_raw = deserialize_obj_cols(df_q_f_raw)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)
    # df_sm et df_profils_pivot sont normalement déjà hachables
    selected_mags = list(selected_mags_tuple)
    # --- Fonctions internes (profil, horaires, k, flux) ---
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
        def parse_horaire(h_str, is_closing=False):
            s = h_str.strip().upper().replace(' ', '')
            if 'H' in s and ':' not in s: s = s.replace('H', ':')
            if ':' not in s and s.isdigit(): s = s + ':00'
            if ':' not in s and len(s) == 4 and s.isdigit(): s = s[:2] + ':' + s[2:]
            try:
                t = datetime.strptime(s, '%H:%M')
                h, m = t.hour, t.minute
                if is_closing and h == 0 and m == 0: h = 24
                return h, m
            except:
                return (8, 0) if not is_closing else (18, 0)
        h_ouv, m_ouv = parse_horaire(ouverture, is_closing=False)
        h_ferm, m_ferm = parse_horaire(fermeture, is_closing=True)
        ouv_min = h_ouv*60 + m_ouv
        ferm_min = h_ferm*60 + m_ferm
        if ferm_min <= ouv_min: ferm_min += 24*60
        ouvert = [False]*24
        for h in range(24):
            debut = h*60
            fin = (h+1)*60
            if debut < ferm_min and fin > ouv_min:
                ouvert[h] = True
        return ouvert
    def estimate_daily_flow_marche(magasin, jour_code, k, profil):
        if k is None: return [0]*24, 0
        is_we = jour_code in ['Sa','Su']
        sm_row = df_sm[df_sm['Nom'] == magasin]
        ouvert = [True]*24 if sm_row.empty else get_opening_hours(sm_row.iloc[0], 'semaine' if not is_we else 'weekend')
        clients = [int(round(k*profil[h])) if ouvert[h] else 0 for h in range(24)]
        return clients, sum(clients)
    def weekly_volume_from_k(magasin, k):
        profil_sem, _, _ = get_effective_profile(magasin, 'Mo')
        profil_we, _, _  = get_effective_profile(magasin, 'Sa')
        clients_sem, _ = estimate_daily_flow_marche(magasin, 'Mo', k, profil_sem)
        clients_we, _  = estimate_daily_flow_marche(magasin, 'Sa', k, profil_we)
        return 5*sum(clients_sem) + 2*sum(clients_we)
    # --------------------------------------------------------------------
    # 1. Calcul des volumes hebdomadaires d'huile par magasin enquêté
    # --------------------------------------------------------------------
    mag_data = {}
    for mag in selected_mags:
        # Récupération du k depuis le dictionnaire pré-calculé ou calcul de secours
        if all_k_data and mag in all_k_data and all_k_data[mag]['k'] is not None:
            k = all_k_data[mag]['k']
        else:
            # fallback : calcul direct (ne devrait plus arriver)
            comptages = df_c_f[df_c_f['lieu_officiel'] == mag]
            if not comptages.empty:
                k_vals = []
                for _, row in comptages.iterrows():
                    # formule simplifiée pour obtenir k (comme avant)
                    duree = (row['fin_dt'] - row['debut_dt']).total_seconds()/3600.0
                    if duree > 0:
                        flux = row['total']/duree
                        # profil uniforme en fallback
                        k_vals.append(flux / 1.0)  # G_moy=1 simplifié
                k = np.median(k_vals) if k_vals else None
            else:
                k = None
        total_hebdo_clients = weekly_volume_from_k(mag, k) if k is not None else None
        df_sm_q = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
        nb_total_q = len(df_sm_q[df_sm_q['statut'] != 'Refus']) if 'statut' in df_sm_q.columns else len(df_sm_q)
        acheteurs = df_sm_q[(df_sm_q['Q1']=='Oui') & (df_sm_q['statut']!='Refus')] if 'statut' in df_sm_q.columns else df_sm_q[df_sm_q['Q1']=='Oui']
        nb_acheteurs = len(acheteurs)
        ti = nb_acheteurs / nb_total_q if nb_total_q > 0 else 0.0
        qi = acheteurs['vol_litres'].mean() if nb_acheteurs > 0 else 0.0
        Vh_huile_hebdo = total_hebdo_clients * ti * qi if (total_hebdo_clients is not None and ti is not None and qi is not None) else None
        vol_annuel_med = Vh_huile_hebdo * 52 if Vh_huile_hebdo is not None else None
        match = df_sm[df_sm['Nom'] == mag]
        taille = match.iloc[0]['Taille'] if not match.empty else '?'
        niveau = match.iloc[0]['Niveau_socio'] if not match.empty else '?'
        chaine = match.iloc[0].get('Chaine','') if not match.empty else ''
        mag_data[mag] = {
            'has_k': k is not None,
            'nb_total_q': nb_total_q,
            'nb_acheteurs': nb_acheteurs,
            'ti': ti, 'qi': qi,
            'Vh_huile_hebdo': Vh_huile_hebdo,
            'freq_hebdo': total_hebdo_clients,
            'vol_annuel_med': vol_annuel_med,
            'taille': taille, 'niveau': niveau, 'chaine': chaine
        }
    # --------------------------------------------------------------------
    # MÉTHODE A : estimateur par expansion stratifié + bootstrap stratifié
    # --------------------------------------------------------------------
    strata = df_sm.groupby(['Taille', 'Niveau_socio']).agg(
        N_s=('Nom', 'count'),
        magasins_liste=('Nom', lambda x: list(x))
    ).reset_index()
    strata['Strate'] = strata['Taille'] + ' / ' + strata['Niveau_socio']
    strate_data = {}
    for _, row_str in strata.iterrows():
        key = (row_str['Taille'], row_str['Niveau_socio'])
        N_s = row_str['N_s']
        magasins_possibles = row_str['magasins_liste']
        vols = []
        for mag in magasins_possibles:
            if mag in mag_data and mag_data[mag]['Vh_huile_hebdo'] is not None:
                vols.append(mag_data[mag]['Vh_huile_hebdo'])
        n_s = len(vols)
        strate_data[key] = {
            'N_s': N_s,
            'n_s': n_s,
            'volumes': np.array(vols)
        }
    n_boot = 500  # réduit pour performance, ajustez si nécessaire
    total_hebdo_boot = []
    for _ in range(n_boot):
        total_hebdo = 0.0
        for key, data in strate_data.items():
            vols = data['volumes']
            n_s = data['n_s']
            N_s = data['N_s']
            if n_s == 0:
                continue
            boot_vols = np.random.choice(vols, size=n_s, replace=True)
            sum_boot = np.sum(boot_vols)
            total_strate = sum_boot * (N_s / n_s)
            total_hebdo += total_strate
        total_hebdo_boot.append(total_hebdo)
    total_hebdo_boot = np.array(total_hebdo_boot)
    total_annuel_boot = total_hebdo_boot * 52
    median_total_A = np.median(total_annuel_boot)
    ci_low_A = np.percentile(total_annuel_boot, 2.5)
    ci_high_A = np.percentile(total_annuel_boot, 97.5)
    rows_strates = []
    for _, row_str in strata.iterrows():
        key = (row_str['Taille'], row_str['Niveau_socio'])
        data_str = strate_data[key]
        N_s = data_str['N_s']
        n_s = data_str['n_s']
        if n_s > 0:
            vols = data_str['volumes']
            total_obs = np.sum(vols)
            total_extrap = total_obs * (N_s / n_s)
            vol_annuel_extrap = total_extrap * 52
            vol_str = f"{fmt_volume(vol_annuel_extrap)} L"
        else:
            vol_str = "Non estimable"
        rows_strates.append({
            'Strate': row_str['Strate'],
            'Nb total magasins': N_s,
            'Nb enquêtés': n_s,
            'Volume annuel estimé': vol_str
        })
    df_strates_A = pd.DataFrame(rows_strates)
    # --- Méthode B (démographique) ---
    df_men_b = prepare_menage_unifie(make_hashable(df_q_f_raw), make_hashable(df_sm), load_commune_niveau())
    if 'statut' in df_men_b.columns:
        df_men_b = df_men_b[df_men_b['statut'] != 'Refus']
    if not df_men_b.empty:
        def extract_pct_supermarche(texte):
            if not isinstance(texte, str):
                return np.nan
            match = re.search(r'Supermarché.*?(\d+(?:\.\d+)?)\s*%', texte, re.IGNORECASE)
            return float(match.group(1)) / 100.0 if match else np.nan
        df_men_b['L'] = df_men_b['pourcentages_achat'].apply(extract_pct_supermarche)
        valide = (
            df_men_b['taille_menage'].notna() & (df_men_b['taille_menage'] > 0) & (df_men_b['taille_menage'] <= 20) &
            df_men_b['volume_total_l'].notna() & (df_men_b['volume_total_l'] > 0) &
            df_men_b['freq_num'].notna() & df_men_b['L'].notna()
        )
        df_valide = df_men_b[valide].copy()
        df_valide['conso_indiv_annuelle'] = 12 * df_valide['freq_num'] * df_valide['volume_total_l'] / df_valide['taille_menage']
        seuil_conso = 100
        df_valide = df_valide[df_valide['conso_indiv_annuelle'] <= seuil_conso]
        pop_bounds = {
            'Aisé': (pop_aisée_min, pop_aisée_max),
            'Moyen': (pop_moyenne_min, pop_moyenne_max),
            'Populaire': (pop_populaire_min, pop_populaire_max)
        }
        niveaux = ['Aisé','Moyen','Populaire']
        results_B = []
        for niveau in niveaux:
            sub = df_valide[df_valide['zone_socioeco']==niveau]
            if sub.empty: continue
            f = sub['freq_num'].values; q = sub['volume_total_l'].values; t = sub['taille_menage'].values; L = sub['L'].values
            n = len(sub)
            def calc_V(f,q,t,L,pop):
                S_fq = np.sum(f*q); S_t = np.sum(t); S_fqL = np.sum(f*q*L)
                if S_fq==0 or S_t==0: return np.nan
                qpers = 12*S_fq/S_t
                beta = S_fqL/S_fq
                return pop*beta*qpers
            pop_min, pop_max = pop_bounds[niveau]
            B = 1000  # réduit pour performance
            V_boot = []
            for _ in range(B):
                idx = np.random.choice(n, size=n, replace=True)
                pop_sample = np.random.uniform(pop_min, pop_max)
                V_boot.append(calc_V(f[idx],q[idx],t[idx],L[idx], pop_sample))
            V_boot = np.array(V_boot); V_boot = V_boot[~np.isnan(V_boot)]
            if len(V_boot)==0: continue
            med = np.median(V_boot); q1 = np.percentile(V_boot,25); q3 = np.percentile(V_boot,75)
            demi_iqr = (q3-q1)/2
            S_fq = np.sum(f*q); S_t = np.sum(t); S_fqL = np.sum(f*q*L)
            qpers = 12*S_fq/S_t if S_t>0 else 0
            beta = S_fqL/S_fq if S_fq>0 else 0
            results_B.append({
                'Niveau': niveau,
                'Population': f"{fmt_volume(pop_min)} – {fmt_volume(pop_max)}",
                'Questionnaires valides': n,
                'qpers (L/pers/an)': fmt_nombre(qpers,2),
                'β (%)': f"{beta*100:.1f}%",
                'Volume SM annuel': f"{fmt_volume(med)} L ± {fmt_volume(demi_iqr)} L",
                '_vol_med': med, '_demi_iqr': demi_iqr
            })
        total_med_B = sum(r['_vol_med'] for r in results_B) if results_B else None
        total_demi_iqr_B = np.sqrt(sum(r['_demi_iqr']**2 for r in results_B)) if results_B else None
    else:
        total_med_B = None
        total_demi_iqr_B = None
    # --------------------------------------------------------------------
    # Tableau de détail par magasin
    # --------------------------------------------------------------------
    rows_mag_detail = []
    for mag in selected_mags:
        data = mag_data[mag]
        has_k = data['has_k']
        nb_q = data['nb_total_q']
        ti = data['ti']; qi = data['qi']
        Vh = data['Vh_huile_hebdo']
        vol_annuel = data['vol_annuel_med']
        if vol_annuel is not None:
            vol_annuel_str = f"{fmt_volume(vol_annuel)} L"
        else:
            vol_annuel_str = "N/A"
        Vh_str = f"{fmt_volume(Vh)} L" if Vh is not None else "N/A"
        rows_mag_detail.append({
            'Magasin': mag,
            'Chaîne': data['chaine'],
            'Comptages': 'Oui' if has_k else 'Non',
            'Q. SM': nb_q,
            'Taux achat': f"{ti*100:.1f}%" if ti is not None else "N/A",
            'Panier moy.': f"{fmt_nombre(qi,2)} L" if qi is not None else "N/A",
            'Volume huile / sem.': Vh_str,
            'Volume annuel estimé': vol_annuel_str,
        })
    df_mag_detail = pd.DataFrame(rows_mag_detail)
    # Volume par chaîne
    chaine_data = {}
    for mag, data in mag_data.items():
        ch = data['chaine'] or 'Indépendant'
        vol_annuel = data['vol_annuel_med']
        if vol_annuel is not None:
            chaine_data.setdefault(ch, []).append(vol_annuel)
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
    df_chaine = pd.DataFrame(chaine_rows) if chaine_rows else pd.DataFrame()
    return {
        'mag_data': mag_data,
        'strata_A': df_strates_A,
        'total_A_med': median_total_A,
        'total_A_ci_low': ci_low_A,
        'total_A_ci_high': ci_high_A,
        'total_med_B': total_med_B,
        'total_demi_iqr_B': total_demi_iqr_B,
        'df_mag_detail': df_mag_detail,
        'df_chaine': df_chaine
    }
# --------------------------------------------------------------------
# Fonction pour l'onglet 10 (profils secteur)
# --------------------------------------------------------------------
@timed
@st.cache_data(ttl=3600)
def prepare_secteur_profiles(df_profils_pivot, df_sm):
    if df_profils_pivot.empty or df_sm.empty:
        return None
    df_profils_pivot = df_profils_pivot.copy()
    df_sm = df_sm.copy()
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
    return pd.DataFrame(secteur_profiles_list)
# ============================================================
# Onglets
# ============================================================
# ------------------------------------------------------------
# ONGLET 0 : ACCUEIL
# ------------------------------------------------------------

# ============================================================
# NAVIGATION (remplace les onglets)
# ============================================================
# Stocker toutes les données dans st.session_state
st.session_state['df_q'] = df_q
st.session_state['df_c'] = df_c
st.session_state['df_p'] = df_p
st.session_state['df_q_f'] = df_q_f
st.session_state['df_c_f'] = df_c_f
st.session_state['df_p_f'] = df_p_f
st.session_state['df_sm'] = df_sm
st.session_state['df_prices_ext'] = df_prices_ext
st.session_state['df_supermarche_full'] = df_supermarche_full
st.session_state['df_supermarche'] = df_supermarche
st.session_state['df_menage'] = df_menage
st.session_state['df_q_export'] = df_q_export
st.session_state['df_q_f_raw'] = df_q_f_raw
st.session_state['df_profils_pivot'] = df_profils_pivot
st.session_state['df_profils_long'] = df_profils_long
st.session_state['secteur_profiles'] = secteur_profiles
st.session_state['df_q_avant_filtrage'] = df_q_avant_filtrage
st.session_state['df_supermarche_raw'] = df_supermarche_raw
st.session_state['commune_niveau'] = commune_niveau
st.session_state['selected_mags'] = selected_mags


# DataFrames supplémentaires pour les pages
st.session_state['df_q_raw'] = df_q_raw if 'df_q_raw' in dir() else pd.DataFrame()
st.session_state['df_q'] = df_q
st.session_state['df_c'] = df_c
st.session_state['df_p'] = df_p
st.session_state['df_supermarche'] = df_supermarche
st.session_state['df_menage'] = df_menage
st.session_state['df_supermarche_raw'] = df_supermarche_raw
st.session_state['df_q_avant_filtrage'] = df_q_avant_filtrage
st.session_state['date_range'] = date_range
st.session_state['selected_enqueteur'] = selected_enqueteur
st.session_state['magasin_mapping'] = magasin_mapping if 'magasin_mapping' in dir() else {}

# Navigation vers toutes les pages
pages = [
    st.Page('pages/00_Accueil.py', title='Accueil', icon='📊'),
    st.Page('pages/03_Enqueteurs.py', title='Enquêteurs', icon='👤'),
    st.Page('pages/01_Supermarche.py', title='Supermarché', icon='🛒'),
    st.Page('pages/02_Menages.py', title='Ménages', icon='🏠'),
    st.Page('pages/04_Flux.py', title='Flux & Affluence', icon='📈'),
    st.Page('pages/05_Marche.py', title='Marché', icon='📊'),
    st.Page('pages/06_Prix.py', title='Prix', icon='🏷️'),
    st.Page('pages/07_Profil.py', title='Profil SM', icon='🏪'),
    st.Page('pages/08_Anomalies.py', title='Anomalies', icon='⚠️'),
    st.Page('pages/09_Cartographie.py', title='Carte', icon='🗺️'),
    st.Page('pages/10_Affluence.py', title='Affluence', icon='📊'),
    st.Page('pages/11_Export.py', title='Export', icon='📤'),
]
pg = st.navigation(pages)
pg.run()

# ============================================================
# Stockage des données dans st.session_state pour les pages
# ============================================================
st.session_state['df_sm'] = df_sm
st.session_state['df_prices_ext'] = df_prices_ext
st.session_state['df_q_f'] = df_q_f
st.session_state['df_c_f'] = df_c_f
st.session_state['df_p_f'] = df_p_f
st.session_state['df_q'] = df_q
st.session_state['df_c'] = df_c
st.session_state['df_p'] = df_p
st.session_state['df_supermarche'] = df_supermarche if not df_supermarche.empty else pd.DataFrame()
st.session_state['df_supermarche_full'] = df_supermarche_full if not df_supermarche_full.empty else pd.DataFrame()
st.session_state['df_menage'] = df_menage if not df_menage.empty else pd.DataFrame()
st.session_state['df_q_export'] = df_q_export if not df_q_export.empty else pd.DataFrame()
st.session_state['df_profils_pivot'] = df_profils_pivot if not df_profils_pivot.empty else pd.DataFrame()
st.session_state['df_profils_long'] = df_profils_long if not df_profils_long.empty else pd.DataFrame()
st.session_state['secteur_profiles'] = secteur_profiles if secteur_profiles is not None else pd.DataFrame()
