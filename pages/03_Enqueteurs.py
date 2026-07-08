# pages/03_Enqueteurs.py
"""Page Statistiques par enquêteur."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
from utils import *
import json
import re

# Récupérer les données depuis la session

import os
import sys
import re
import json
import hashlib
from datetime import datetime, time, date, timedelta

df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_p_f = st.session_state.get('df_p_f', pd.DataFrame())

df_q = st.session_state.get('df_q', pd.DataFrame())
df_c = st.session_state.get('df_c', pd.DataFrame())
df_p = st.session_state.get('df_p', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
date_range = st.session_state.get('date_range', (None, None))
selected_enqueteur = st.session_state.get('selected_enqueteur', 'Tous')

st.header("Statistiques par enquêteur")

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
@timed
@st.cache_data(ttl=3600, show_spinner="Calcul des anomalies en cours...")
def compute_all_anomalies(df_q_full, df_c_full, df_p_full, settings, df_prices_ext, brand_map):
    # ⬇️ Désérialisation pour compatibilité cache
    df_q_full = deserialize_obj_cols(df_q_full)
    df_c_full = deserialize_obj_cols(df_c_full)
    df_p_full = deserialize_obj_cols(df_p_full)
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
        # 5) Marques non référencées
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
        df_q_clean = make_hashable(df_q_filtre_anom)
        df_c_clean = make_hashable(df_c_filtre_anom)
        df_p_clean = make_hashable(df_p_filtre_anom)
        anomaly_records = compute_all_anomalies(df_q_clean, df_c_clean, df_p_clean, settings, prices_ext, brand_map)
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
    st.dataframe(df_global, width='stretch')
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
        st.dataframe(df_jour, width='stretch')
# ------------------------------------------------------------
# ONGLET 2 : SUPERMARCHÉ
# ------------------------------------------------------------
