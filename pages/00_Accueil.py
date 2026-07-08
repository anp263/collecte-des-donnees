# pages/00_Accueil.py
"""Page d'accueil du dashboard."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
from utils import *

# Récupérer les données depuis la session

import os
import sys
import re
import json
import hashlib
from datetime import datetime, time, date, timedelta

df_q = st.session_state.get('df_q', pd.DataFrame())
df_c = st.session_state.get('df_c', pd.DataFrame())
df_p = st.session_state.get('df_p', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_p_f = st.session_state.get('df_p_f', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
df_q_export = st.session_state.get('df_q_export', pd.DataFrame())

st.header("📊 Vue d'ensemble")

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
    st.dataframe(df_avancement, width='stretch')
else:
    st.info("ℹ️ Aucun magasin sélectionné.")
# ================================================================
# Tableau récapitulatif par strate
# ================================================================
if selected_mags:
    st.divider()
    st.subheader("📊 Récapitulatif par strate (taille × niveau socio-économique)")
    # --- 1. Agrégats sur TOUS les supermarchés (fichier complet) ---
    df_sm_complet = df_sm.copy()
    price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
    if price_cols:
        df_sm_complet['vend_huile'] = (df_sm_complet[price_cols] > 0).any(axis=1)
    else:
        df_sm_complet['vend_huile'] = True
    df_strates_complet = df_sm_complet.groupby(['Taille', 'Niveau_socio']).agg(
        nb_total=('Nom', 'count'),
        nb_vend_huile=('vend_huile', 'sum'),
        magasins_complet=('Nom', list)
    ).reset_index()
    # --- 2. Agrégats sur les magasins SÉLECTIONNÉS pour les enquêtes ---
    df_sm_sel = df_sm[df_sm['Nom'].isin(selected_mags)].copy()
    if price_cols:
        df_sm_sel['vend_huile'] = (df_sm_sel[price_cols] > 0).any(axis=1)
    else:
        df_sm_sel['vend_huile'] = True
    df_strates_sel = df_sm_sel.groupby(['Taille', 'Niveau_socio']).agg(
        magasins_sel=('Nom', list)
    ).reset_index()
    # --- 3. Fusion et calcul des indicateurs ---
    df_strates = df_strates_complet.merge(df_strates_sel, on=['Taille', 'Niveau_socio'], how='left')
    df_strates['magasins_sel'] = df_strates['magasins_sel'].apply(lambda x: x if isinstance(x, list) else [])
    # Fonction pour calculer heures et questionnaires sur une liste de magasins (sélectionnés)
    def get_heures_et_questionnaires(magasins):
        heures_sem = 0.0
        heures_we = 0.0
        nb_q = 0
        for mag in magasins:
            if not df_c_f.empty:
                sessions = df_c_f[df_c_f['lieu_officiel'] == mag]
                if not sessions.empty:
                    heures_sem += sessions[sessions['date_dt'].dt.weekday < 5]['duree_h'].sum()
                    heures_we  += sessions[sessions['date_dt'].dt.weekday >= 5]['duree_h'].sum()
            if not df_supermarche_full.empty:
                q_mag = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
                if 'statut' in q_mag.columns:
                    nb_q += len(q_mag[q_mag['statut'] != 'Refus'])
                else:
                    nb_q += len(q_mag)
        return heures_sem + heures_we, nb_q
    rows_strates = []
    for _, row in df_strates.iterrows():
        taille = row['Taille']
        niveau = row['Niveau_socio']
        nb_total = row['nb_total']
        nb_vend_huile = row['nb_vend_huile']
        pct_vend = (nb_vend_huile / nb_total * 100) if nb_total > 0 else 0
        # Magasins sélectionnés (pour enquête)
        mags_sel = row['magasins_sel']
        nb_selected = len(mags_sel)
        # Magasins enquêtés parmi les sélectionnés (ceux avec questionnaire ou comptage)
        mags_couverts = []
        for m in mags_sel:
            has_q = False
            has_c = False
            if not df_supermarche_full.empty:
                q_mag = df_supermarche_full[df_supermarche_full['magasin_officiel'] == m]
                if 'statut' in q_mag.columns:
                    has_q = len(q_mag[q_mag['statut'] != 'Refus']) > 0
                else:
                    has_q = len(q_mag) > 0
            if not df_c_f.empty:
                has_c = len(df_c_f[df_c_f['lieu_officiel'] == m]) > 0
            if has_q or has_c:
                mags_couverts.append(m)
        nb_couverts = len(mags_couverts)
        pct_couvert = (nb_couverts / nb_vend_huile * 100) if nb_vend_huile > 0 else 0
        # Heures et questionnaires pour les magasins sélectionnés
        total_heures, nb_q = get_heures_et_questionnaires(mags_sel)
        # Formatter
        vend_huile_str = f"{nb_vend_huile} ({pct_vend:.1f}%)"
        enquete_str = f"{nb_couverts} ({pct_couvert:.1f}%)" if nb_couverts > 0 else f"0 (0.0%)"
        rows_strates.append({
            'Strate': f"{taille} / {niveau}",
            'Nombre total de supermarché': nb_total,
            'Dont vendant huile non raffinée': vend_huile_str,
            'Dont enquêtés': enquete_str,
            'Heures de comptage valides': f"{total_heures:.1f}",
            'Questionnaires valides': nb_q
        })
    if rows_strates:
        df_strates_resume = pd.DataFrame(rows_strates)
        st.dataframe(df_strates_resume, width='stretch')
    else:
        st.info("Aucune donnée de strate disponible.")
else:
    st.info("Sélectionnez des magasins pour voir le récapitulatif par strate.")
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
