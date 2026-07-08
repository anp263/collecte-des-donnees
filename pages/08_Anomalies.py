# pages/08_Anomalies.py

"""Page Anomalies."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import os, sys, re, json, hashlib
from utils import *
from analytics import *

# Données
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_p_f = st.session_state.get('df_p_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
df_q = st.session_state.get('df_q', pd.DataFrame())
df_c = st.session_state.get('df_c', pd.DataFrame())
df_p = st.session_state.get('df_p', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])
date_range = st.session_state.get('date_range', (None, None))
magasin_mapping = {}
selected_mags = st.session_state.get('selected_mags', [])
selected_norm = {normalize_name(m): m for m in selected_mags}
selected_enqueteur = st.session_state.get('sidebar_enqueteur', 'Tous')

st.header("⚠️ Gestion des anomalies")
# ------------------------------------------------------------
# 1. Calcul (ou récupération) des anomalies AVEC SÉRIALISATION
# ------------------------------------------------------------
if 'anomaly_records' not in st.session_state:
    # --- Préparation des DataFrames filtrés (identique à l'onglet 1) ---
    df_q_filtre_anom = df_q.copy() if not df_q.empty else pd.DataFrame()
    if not df_q_filtre_anom.empty and 'date_dt' in df_q_filtre_anom.columns:
        mask_q = (df_q_filtre_anom['date_dt'].dt.date >= date_range[0]) & \
                 (df_q_filtre_anom['date_dt'].dt.date <= date_range[1])
        if selected_enqueteur != "Tous":
            mask_q &= (df_q_filtre_anom['enqueteur'] == selected_enqueteur)
        df_q_filtre_anom = df_q_filtre_anom[mask_q]
    df_c_filtre_anom = df_c.copy() if not df_c.empty else pd.DataFrame()
    if not df_c_filtre_anom.empty and 'date_dt' in df_c_filtre_anom.columns:
        mask_c = (df_c_filtre_anom['date_dt'].dt.date >= date_range[0]) & \
                 (df_c_filtre_anom['date_dt'].dt.date <= date_range[1])
        df_c_filtre_anom = df_c_filtre_anom[mask_c]
    df_p_filtre_anom = df_p.copy() if not df_p.empty else pd.DataFrame()
    if not df_p_filtre_anom.empty and 'date_dt' in df_p_filtre_anom.columns:
        mask_p = (df_p_filtre_anom['date_dt'].dt.date >= date_range[0]) & \
                 (df_p_filtre_anom['date_dt'].dt.date <= date_range[1])
        df_p_filtre_anom = df_p_filtre_anom[mask_p]
    settings = load_anomaly_settings()
    prices_ext = df_prices_ext if 'df_prices_ext' in dir() else pd.DataFrame()
    brand_map = load_brand_mapping()
    # --- APPEL SÉRIALISÉ (indispensable pour le cache) ---
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


st.session_state.anomaly_records = compute_all_anomalies(
        make_hashable(df_q_filtre_anom),
        make_hashable(df_c_filtre_anom),
        make_hashable(df_p_filtre_anom),
        settings, prices_ext, brand_map
    )
anomaly_records = st.session_state.anomaly_records
# ------------------------------------------------------------
# 2. Suite de l'onglet (exactement comme avant)
# ------------------------------------------------------------
if not anomaly_records:
    st.success("✅ Aucune anomalie détectée avec les paramètres actuels.")
else:
    st.subheader("📊 Synthèse des anomalies par jour et enquêteur")
    # Construction du DataFrame des anomalies (comme dans votre code actuel)
    df_anom = pd.DataFrame(anomaly_records, columns=['uuid', 'type', 'date_str', 'enqueteur', 'message'])
    df_anom['message'] = df_anom['message'].str.replace('FCFA', 'FC')
    df_anom['date'] = pd.to_datetime(df_anom['date_str'].str[:10], format='%Y-%m-%d', errors='coerce').dt.date
    df_anom = df_anom.dropna(subset=['date']).reset_index(drop=True)
    # Filtrage par la période de la barre latérale
    mask_date_anom = (df_anom['date'] >= date_range[0]) & (df_anom['date'] <= date_range[1])
    df_anom_f = df_anom[mask_date_anom]
    if selected_enqueteur != "Tous":
        df_anom_f = df_anom_f[df_anom_f['enqueteur'] == selected_enqueteur]
    synth = df_anom_f.groupby(['date', 'enqueteur']).size().reset_index(name='nb_anomalies')
    synth['date'] = synth['date'].astype(str)
    event = st.dataframe(
        synth,
        on_select="rerun",
        selection_mode="multi-row",
        width='stretch',
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
                    width='stretch',
                    key=f"detail_multi_{hash(str(pairs))}"
                )
                if detail_event.selection.rows:
                    detail_indices = detail_event.selection.rows
                    st.write(f"**{len(detail_indices)} anomalie(s) cochée(s) pour suppression.**")
                    if st.button("🗑️ Supprimer les anomalies cochées", key=f"del_multi_{hash(str(pairs))}"):
                        try:
                            db_conn = get_db_connection()
                            if db_conn is not None:
                                cur = db_conn.cursor()
                                for _, row_sel in df_detail.iloc[detail_indices].iterrows():
                                    table = "questionnaires" if row_sel['type'] == 'questionnaire' else \
                                            ("countings" if row_sel['type'] == 'comptage' else "prices")
                                    cur.execute(f"DELETE FROM {table} WHERE uuid = ?", (row_sel['uuid'],))
                                db_conn.commit()
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
# 3. Doublons supermarchés (inchangé)
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
    if not df_q.empty:
        q_all = df_q[df_q['type'].isin(['supermarche', 'supermarche_menage', 'menage'])].copy()
        if 'statut' in q_all.columns:
            q_all = q_all[q_all['statut'] != 'Refus']
        if not q_all.empty:
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
            q_all['champs'] = q_all.apply(extraire_champs, axis=1)
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
    st.dataframe(cat_summary, width='stretch')
    # Sélection d'une catégorie
    selected_cat = st.selectbox("Choisissez une catégorie", cat_summary['Catégorie'].tolist(), key="cat_select")
    if selected_cat:
        df_cat = df_anom_f[df_anom_f['categorie'] == selected_cat].reset_index(drop=True)
        st.write(f"**{len(df_cat)} anomalie(s) dans cette catégorie.**")
        detail_event = st.dataframe(
            df_cat[['type', 'uuid', 'date_str', 'enqueteur', 'message']],
            on_select="rerun",
            selection_mode="multi-row",
            width='stretch',
            key="detail_cat_anomalies"
        )
        if detail_event.selection.rows:
            valid_indices = [i for i in detail_event.selection.rows if i < len(df_cat)]
            if not valid_indices:
                st.warning("Les lignes sélectionnées ne sont plus disponibles. Veuillez resélectionner.")
            else:
                selected_rows = df_cat.iloc[valid_indices]
                st.write(f"**{len(selected_rows)} enregistrement(s) sélectionné(s) pour suppression.**")
                if st.button("🗑️ Supprimer les enregistrements sélectionnés", key="del_cat_anomalies"):
                    try:
                        db_conn = get_db_connection()
                        if db_conn is not None:
                            cur = db_conn.cursor()
                            for _, row_sel in selected_rows.iterrows():
                                table = "questionnaires" if row_sel['type'] == 'questionnaire' else \
                                        ("countings" if row_sel['type'] == 'comptage' else "prices")
                                cur.execute(f"DELETE FROM {table} WHERE uuid = ?", (row_sel['uuid'],))
                            db_conn.commit()
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
# ONGLET 9 : CARTE DES SUPERMARCHÉS ET MESURES
# ------------------------------------------------------------
