"""
data_loader.py – Chargement des données (DB, CSV, cache)
"""
import os
import json
import re
import sqlite3
import hashlib
import pandas as pd
import streamlit as st

from config import DB_PATH, SUPERMARCHES_CSV, FREQUENTATION_CSV, CACHE_TTL_DATA
from utils import make_hashable, deserialize_obj_cols, normalize_name, to_float


# ══════════════════════════════════════════════════════════
# Base de données (questionnaires, comptages, prix)
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=CACHE_TTL_DATA)
def load_db_internal():
    """Charge toutes les données depuis la base SQLite."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), \
               "Fichier 'consolidated.db' introuvable. Exécutez d'abord process_daily.py."
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

    df_q = make_hashable(df_q)
    df_c = make_hashable(df_c)
    df_p = make_hashable(df_p)

    return df_q, df_c, df_p, None


def load_db():
    """Wrapper avec gestion d'erreur."""
    df_q, df_c, df_p, err = load_db_internal()
    if err:
        st.error(err)
    return df_q, df_c, df_p


# ══════════════════════════════════════════════════════════
# Supermarchés
# ══════════════════════════════════════════════════════════

@st.cache_data
def load_supermarches_internal():
    """Charge le fichier supermarches.csv et extrait les prix externes."""
    encodings = ['utf-8-sig', 'latin1', 'cp1252']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(SUPERMARCHES_CSV, encoding=enc, skip_blank_lines=False)
            break
        except Exception:
            continue
    if df is None:
        return pd.DataFrame(), pd.DataFrame(), "Fichier supermarches.csv illisible."

    df.columns = [_clean_column_name(c) for c in df.columns]

    nom_col = _find_nom_col(df)
    if not nom_col:
        return pd.DataFrame(), pd.DataFrame(), "Colonne 'Nom du supermarché' introuvable."

    socio_col = next((c for c in df.columns if 'socio' in c.lower() or 'niveau' in c.lower()), None)
    price_cols = [c for c in df.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]

    data_id = {
        'Nom': df[nom_col].astype(str).str.strip(),
        'Chaine': df['Chaine'].astype(str).str.strip() if 'Chaine' in df.columns else '',
        'Secteur': df['Secteur'].astype(str).str.strip() if 'Secteur' in df.columns else '',
        'Niveau_socio': df[socio_col].astype(str).str.strip() if socio_col else '',
        'Taille': df['Taille'].astype(str).str.strip() if 'Taille' in df.columns else '',
        'ouv_sem': df['Horaire d\'ouverture semaine'].astype(str).str.strip()
                   if 'Horaire d\'ouverture semaine' in df.columns else '',
        'ferm_sem': df['Horaire de fermeture semaine'].astype(str).str.strip()
                    if 'Horaire de fermeture semaine' in df.columns else '',
        'ouv_we': df['Horaire d\'ouverture weekend'].astype(str).str.strip()
                  if 'Horaire d\'ouverture weekend' in df.columns else '',
        'ferm_we': df['Horaire de fermeture weekend'].astype(str).str.strip()
                   if 'Horaire de fermeture weekend' in df.columns else '',
    }
    df_id = pd.DataFrame(data_id)

    df_prices = df[price_cols].copy()
    for c in price_cols:
        df_prices[c] = df_prices[c].apply(to_float)

    out = pd.concat([df_id, df_prices], axis=1)
    out = out[out['Nom'].notna() & (out['Nom'] != '')]

    # Extraction des prix externes
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
    """Wrapper avec gestion d'erreur."""
    out, df_prices_ext, msg = load_supermarches_internal()
    if "illisible" in msg or "introuvable" in msg:
        st.error(msg)
    elif msg:
        st.success(msg)
    return out, df_prices_ext


# ══════════════════════════════════════════════════════════
# Fréquentation
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=CACHE_TTL_DATA)
def load_frequentation_data():
    """Charge et parse le fichier fréquentation.csv en pivot long."""
    if not os.path.exists(FREQUENTATION_CSV):
        st.warning("Fichier 'fréquentation.csv' introuvable.")
        return pd.DataFrame(), pd.DataFrame()

    encodings = ['utf-8', 'latin1', 'cp1252']
    df_raw = None
    for enc in encodings:
        try:
            df_raw = pd.read_csv(FREQUENTATION_CSV, encoding=enc)
            break
        except:
            continue
    if df_raw is None:
        st.error("Impossible de lire 'fréquentation.csv'")
        return pd.DataFrame(), pd.DataFrame()

    mag_col = _find_mag_col(df_raw)
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


# ══════════════════════════════════════════════════════════
# Fonctions internes
# ══════════════════════════════════════════════════════════

def _clean_column_name(name):
    if not isinstance(name, str):
        name = str(name)
    name = name.replace('�%', '%').replace('�', '%')
    name = name.replace('\xa0', ' ')
    name = name.strip()
    if ' - ' in name:
        parts = name.split(' - ')
        name = parts[0].strip() + ' - ' + parts[1].strip()
    return name


def _find_nom_col(df):
    if 'Nom du supermarché' in df.columns:
        return 'Nom du supermarché'
    for c in df.columns:
        if 'nom' in c.lower() and 'supermarche' in c.lower():
            return c
    return None


def _find_mag_col(df):
    if 'title' in df.columns:
        return 'title'
    possible = [c for c in df.columns if 'title' in c.lower() or 'nom' in c.lower()]
    return possible[0] if possible else df.columns[0]


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
