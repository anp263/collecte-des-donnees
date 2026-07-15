# pages/08_Anomalies.py
"""Page Anomalies."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import os, sys, re, json, hashlib
from difflib import SequenceMatcher
from utils import *
from analytics import *

# ----- Données depuis la session -----
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
date_range = st.session_state.get('sidebar_date_range', (datetime.today().date(), datetime.today().date()))
selected_enqueteur = st.session_state.get('sidebar_enqueteur', 'Tous')

# ----- Filtrage des données brutes (période + enquêteur) -----
df_q_filtre = df_q.copy() if not df_q.empty else pd.DataFrame()
if not df_q_filtre.empty and 'date_dt' in df_q_filtre.columns:
    mask_q = (df_q_filtre['date_dt'].dt.date >= date_range[0]) & (df_q_filtre['date_dt'].dt.date <= date_range[1])
    if selected_enqueteur != "Tous":
        mask_q &= (df_q_filtre['enqueteur'] == selected_enqueteur)
    df_q_filtre = df_q_filtre[mask_q]

df_c_filtre = df_c.copy() if not df_c.empty else pd.DataFrame()
if not df_c_filtre.empty and 'date_dt' in df_c_filtre.columns:
    mask_c = (df_c_filtre['date_dt'].dt.date >= date_range[0]) & (df_c_filtre['date_dt'].dt.date <= date_range[1])
    df_c_filtre = df_c_filtre[mask_c]

df_p_filtre = df_p.copy() if not df_p.empty else pd.DataFrame()
if not df_p_filtre.empty and 'date_dt' in df_p_filtre.columns:
    mask_p = (df_p_filtre['date_dt'].dt.date >= date_range[0]) & (df_p_filtre['date_dt'].dt.date <= date_range[1])
    df_p_filtre = df_p_filtre[mask_p]

# ----- Fonction de calcul des anomalies (mise en cache) -----
@st.cache_data(show_spinner="Calcul des anomalies...")
def compute_all_anomalies_cached(df_q_filtre, df_c_filtre, df_p_filtre, settings, df_prices_ext, brand_map):
    """
    Calcule l'ensemble des anomalies pour les questionnaires, comptages et prix filtrés.
    Les DataFrames sont passés hashables (colonnes JSON converties).
    """
    # Désérialisation éventuelle
    df_q_filtre = deserialize_obj_cols(df_q_filtre)
    df_c_filtre = deserialize_obj_cols(df_c_filtre)
    df_p_filtre = deserialize_obj_cols(df_p_filtre)

    anomalies = []

    # --- Questionnaires ---
    if not df_q_filtre.empty:
        q = df_q_filtre.copy()
        q['datetime'] = pd.to_datetime(q['date'] + ' ' + q['heure'], errors='coerce')
        q = q.dropna(subset=['datetime'])

        # 1) Validations intrinsèques
        for _, row in q.iterrows():
            rec = row['data_dict']
            qtype = row['type']
            msgs = validate_questionnaire_dynamic(rec, qtype, settings)
            for m in msgs:
                anomalies.append((row['uuid'], 'questionnaire', row['date'], row['enqueteur'], m))

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
                        anomalies.append((
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
                    anomalies.append((
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
                        anomalies.append((
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
                anomalies.append((
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
                    anomalies.append((
                        row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                        f"Marque achetée « {marque_clean} » non référencée dans le supermarché « {lieu} »"
                    ))

    # --- Comptages ---
    if not df_c_filtre.empty:
        for _, row in df_c_filtre.iterrows():
            rec = row['data_dict']
            msgs = validate_counting_dynamic(rec, settings)
            for m in msgs:
                anomalies.append((row['uuid'], 'comptage', row['date'], row['enqueteur'], m))

        c = df_c_filtre.copy()
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
                    anomalies.append((
                        row['uuid'], 'comptage', row['date'], row['enqueteur'],
                        f"Distance GPS > {settings['distance_gps_comptage_m']} m "
                        f"par rapport à la médiane de '{lieu}' ({dist_km*1000:.0f} m)"
                    ))

    # --- Prix ---
    if not df_p_filtre.empty:
        for _, row in df_p_filtre.iterrows():
            rec = row['data_dict']
            msgs = validate_price_dynamic(rec, settings)
            for m in msgs:
                anomalies.append((row['uuid'], 'prix', row['date'], row['enqueteur'], m))

    return anomalies

# ----- Chargement des paramètres et calcul -----
settings = load_anomaly_settings()
brand_map = load_brand_mapping()
# Rendre les DataFrames hashables pour le cache
df_q_hash = make_hashable(df_q_filtre)
df_c_hash = make_hashable(df_c_filtre)
df_p_hash = make_hashable(df_p_filtre)

anomaly_records = compute_all_anomalies_cached(df_q_hash, df_c_hash, df_p_hash, settings, df_prices_ext, brand_map)

# ----- Construction du DataFrame d'anomalies -----
if anomaly_records:
    df_anom = pd.DataFrame(anomaly_records, columns=['uuid', 'type', 'date_str', 'enqueteur', 'message'])
    df_anom['message'] = df_anom['message'].str.replace('FCFA', 'FC')
    df_anom['date'] = pd.to_datetime(df_anom['date_str'].str[:10], format='%Y-%m-%d', errors='coerce').dt.date
    df_anom = df_anom.dropna(subset=['date']).reset_index(drop=True)
    # Appliquer le filtre période + enquêteur sur les anomalies (redondant mais sûr)
    mask_date_anom = (df_anom['date'] >= date_range[0]) & (df_anom['date'] <= date_range[1])
    df_anom_f = df_anom[mask_date_anom]
    if selected_enqueteur != "Tous":
        df_anom_f = df_anom_f[df_anom_f['enqueteur'] == selected_enqueteur]
else:
    df_anom_f = pd.DataFrame()

st.header("⚠️ Gestion des anomalies")

if anomaly_records:
    # ----- Synthèse par enquêteur et par jour -----
    st.subheader("📊 Synthèse des anomalies par enquêteur")
    if not df_anom_f.empty:
        synth_enq = df_anom_f.groupby('enqueteur').size().reset_index(name='Nombre d\'anomalies')
        st.dataframe(synth_enq, width='stretch')
    else:
        st.info("Aucune anomalie trouvée pour la période/enquêteur sélectionnés.")

    # ----- Détail par jour pour un enquêteur sélectionné -----
    st.subheader("📅 Détail journalier par enquêteur")
    if not df_anom_f.empty:
        enqueteurs = sorted(df_anom_f['enqueteur'].unique())
        choix = st.selectbox("Choisir un enquêteur", enqueteurs, key="detail_enq")
        df_detail = df_anom_f[df_anom_f['enqueteur'] == choix]
        if not df_detail.empty:
            detail_jour = df_detail.groupby('date').size().reset_index(name='Anomalies')
            detail_jour['date'] = detail_jour['date'].astype(str)
            st.dataframe(detail_jour, width='stretch')
    else:
        st.info("Aucune anomalie.")

    # ----- Affichage détaillé avec possibilité de suppression -----
    st.subheader("🔍 Détail de toutes les anomalies")
    event = st.dataframe(
        df_anom_f[['type', 'uuid', 'date', 'enqueteur', 'message']],
        on_select="rerun",
        selection_mode="multi-row",
        width='stretch',
        key="all_anomalies"
    )
    if event.selection.rows:
        selected_indices = event.selection.rows
        selected_rows = df_anom_f.iloc[selected_indices]
        st.write(f"**{len(selected_rows)} anomalie(s) sélectionnée(s)**")
        if st.button("🗑️ Supprimer les enregistrements sélectionnés", key="del_anomalies"):
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
                compute_all_anomalies_cached.clear()
                st.success(f"{len(selected_rows)} enregistrement(s) supprimé(s).")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {e}")
else:
    st.success("✅ Aucune anomalie détectée avec les paramètres actuels.")

# ----- Doublons supermarchés -----
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

# ----- Outils supplémentaires -----
st.subheader("🛠️ Outils supplémentaires")

# --- Mapping des marques avec enregistrement groupé ---
with st.expander("🏷️ Mapping des marques", expanded=False):
    official_set = get_official_brands(df_prices_ext)
    brand_map = load_brand_mapping()
    # Construire l'ensemble des marques brutes rencontrées (avant filtrage)
    raw_brands = set()
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
    if not df_prices_ext.empty:
        for b in df_prices_ext['marque'].unique():
            raw_brands.add(normalize_brand(b))
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
        choix_marques = {}
        for brand in sorted(missing):
            st.markdown(f"**{brand}**")
            col1, col2 = st.columns([3, 1])
            with col1:
                options = sorted(list(official_set))
                selected = st.selectbox(f"Marque cible", options=[""] + options, key=f"map_{brand}")
            with col2:
                new_name = st.text_input("Nouveau nom (si non listé)", key=f"new_{brand}", value="")
            final = new_name.strip() if new_name.strip() else selected
            choix_marques[brand] = final
        if st.button("💾 Enregistrer toutes les correspondances de marques", key="save_all_brands"):
            nouvelles_marques = {b: v for b, v in choix_marques.items() if v}
            if nouvelles_marques:
                brand_map.update(nouvelles_marques)
                save_brand_mapping(brand_map)
                st.success(f"{len(nouvelles_marques)} correspondance(s) de marques enregistrée(s).")
                st.rerun()
            else:
                st.info("Aucune nouvelle correspondance à enregistrer.")

# --- Correspondances supermarchés (avec enregistrement groupé) ---
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
        # Récupérer les données brutes (avant tout filtrage)
        df_q_raw = st.session_state.get('df_q_raw', pd.DataFrame())
        if not df_q_raw.empty and 'magasin_officiel' in df_q_raw.columns:
            # On prend tous les magasins_officiel uniques des questionnaires supermarché (type 'supermarche')
            all_officiel = df_q_raw[df_q_raw['type'] == 'supermarche']['magasin_officiel'].dropna().unique()
            problematiques = []
            for officiel in all_officiel:
                # Nettoyer le nom (supprimer " → commune" si présent)
                cleaned = officiel.split(' → ')[0].strip() if ' → ' in officiel else officiel
                # Vérifier si ce nom (nettoyé) est déjà dans les sélectionnés ou les corrections
                if cleaned in selected_mags:
                    continue
                if officiel in manual_corrections and manual_corrections[officiel] is not None:
                    continue
                # Vérifier également si la normalisation correspond à un sélectionné
                norm_off = normalize_name(cleaned)
                if norm_off in {normalize_name(m) for m in selected_mags}:
                    continue
                # Si aucune correspondance, on le propose
                problematiques.append(officiel)

            if not problematiques:
                st.success("✅ Tous les magasins sont correctement associés.")
            else:
                st.warning(f"{len(problematiques)} magasin(s) non associés. Choisissez une correspondance pour chacun :")
                # Dictionnaire pour stocker les choix de l'utilisateur
                choix_utilisateur = {}
                for idx, officiel in enumerate(problematiques):
                    st.markdown(f"**{officiel}**")
                    options = ["Ne pas associer (ignorer)"] + selected_mags
                    # Optionnel : calculer un meilleur match suggéré (sans l'appliquer automatiquement)
                    # On peut afficher une suggestion dans le label
                    default = 0
                    # Pour une suggestion, on peut calculer le meilleur score et le mettre en défaut
                    # (mais on laisse l'utilisateur choisir)
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        choix = st.selectbox("Correspondance cible", options, index=default, key=f"corr_{idx}")
                    # Stocker le choix
                    choix_utilisateur[officiel] = choix

                # Bouton pour enregistrer toutes les corrections en une fois
                if st.button("💾 Enregistrer toutes les correspondances", key="save_all_corrections"):
                    nouvelles_corrections = {}
                    for officiel, choix in choix_utilisateur.items():
                        if choix != "Ne pas associer (ignorer)":
                            nouvelles_corrections[officiel] = choix
                        else:
                            nouvelles_corrections[officiel] = None
                    # Mettre à jour le fichier
                    manual_corrections.update(nouvelles_corrections)
                    with open(corrections_file, 'w', encoding='utf-8') as f:
                        json.dump(manual_corrections, f, indent=2, ensure_ascii=False)
                    st.success(f"{len(nouvelles_corrections)} correspondance(s) enregistrée(s).")
                    st.rerun()
        else:
            st.info("Aucune donnée brute disponible pour la correspondance.")

# --- Mapping Google Popular Times (centralisé) ---
with st.expander("🗺️ Correspondance magasin → Profil Google (Popular Times)", expanded=False):
    st.markdown("""
    Associez chaque magasin sélectionné à son profil Google Popular Times.
    - Choisissez un nom exact figurant dans les données Google (fichier fréquentation.csv).
    - Ou laissez vide pour utiliser le profil médian du secteur du magasin.
    - Les correspondances seront enregistrées dans `magasin_mapping.json`.
    """)

    # Charger les données nécessaires
    df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
    df_sm = st.session_state.get('df_sm', pd.DataFrame())
    selected_mags = st.session_state.get('selected_magasins', [])
    mapping_file = "magasin_mapping.json"

    if not selected_mags:
        st.info("Aucun magasin sélectionné (onglet Accueil).")
    elif df_profils_pivot.empty:
        st.warning("Aucune donnée Google Popular Times (fichier 'fréquentation.csv' introuvable ou vide).")
    else:
        # Charger le mapping existant
        magasin_mapping = {}
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                magasin_mapping = json.load(f)

        # Préparer les options : profils Google direct + profils secteur
        magasins_dispos_google = sorted(df_profils_pivot['magasin'].unique())
        # Récupérer les secteurs depuis df_sm
        secteurs_dispos = sorted(df_sm['Secteur'].unique()) if not df_sm.empty else []
        secteur_options = [f"Profil médian secteur {s}" for s in secteurs_dispos]
        options = secteur_options + magasins_dispos_google

        # Dictionnaire pour stocker les choix
        choix_google = {}

        # Pour chaque magasin sélectionné, proposer un choix
        for mag in selected_mags:
            current_val = magasin_mapping.get(mag, "")
            # Déterminer le secteur du magasin pour proposer un défaut
            secteur_mag = None
            if not df_sm.empty:
                row = df_sm[df_sm['Nom'] == mag]
                if not row.empty:
                    secteur_mag = row.iloc[0]['Secteur']
            default_secteur_str = f"Profil médian secteur {secteur_mag}" if secteur_mag and f"Profil médian secteur {secteur_mag}" in options else ""
            if not current_val or current_val not in options:
                current_val = default_secteur_str if default_secteur_str else options[0] if options else ""
            idx = options.index(current_val) if current_val in options else 0
            new_val = st.selectbox(f"**{mag}**", options, index=idx, key=f"google_{mag}")
            choix_google[mag] = new_val

        if st.button("💾 Enregistrer toutes les correspondances Google", key="save_all_google_central"):
            clean_mapping = {}
            for mag, val in choix_google.items():
                if val.startswith("Profil médian secteur "):
                    # On ne stocke rien (on utilisera le profil secteur par défaut)
                    pass
                else:
                    clean_mapping[mag] = val
            with open(mapping_file, 'w', encoding='utf-8') as f:
                json.dump(clean_mapping, f, indent=2, ensure_ascii=False)
            st.success(f"{len(clean_mapping)} correspondance(s) enregistrée(s).")
            st.rerun()