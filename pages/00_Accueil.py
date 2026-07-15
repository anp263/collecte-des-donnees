# pages/00_Accueil.py
"""Page d'accueil du dashboard."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
from utils import *
import os, sys, re, json, hashlib
from datetime import datetime, time, date, timedelta

# ============================================================
# Cache des résultats basé sur un hash des paramètres
# ============================================================
def _get_cache_key():
    """Retourne un hash unique pour l'état actuel des filtres."""
    dr = st.session_state.get('sidebar_date_range', (None, None))
    if isinstance(dr, (list, tuple)) and len(dr) >= 2:
        dr_key = f"{dr[0]}_{dr[1]}"
    else:
        dr_key = str(dr)
    key_parts = [
        dr_key,
        str(st.session_state.get('sidebar_enqueteur', 'Tous')),
        str(sorted(st.session_state.get('selected_magasins', []))),
        str(st.session_state.get('devise_globale', 'FC')),
        str(st.session_state.get('taux_change', 2800)),
    ]
    raw = '|'.join(key_parts)
    return hashlib.md5(raw.encode()).hexdigest()

def _get_cached(key, default=None):
    """Récupère une valeur du cache de la page si la clé est valide."""
    cache = st.session_state.get('_accueil_cache', {})
    cache_key = st.session_state.get('_accueil_cache_key', '')
    current_key = _get_cache_key()
    if cache_key == current_key and key in cache:
        return cache[key]
    return default

def _set_cached(key, value):
    """Stocke une valeur dans le cache de la page."""
    current_key = _get_cache_key()
    if '_accueil_cache' not in st.session_state or st.session_state.get('_accueil_cache_key') != current_key:
        st.session_state['_accueil_cache'] = {}
        st.session_state['_accueil_cache_key'] = current_key
    st.session_state['_accueil_cache'][key] = value

def _clear_cache():
    """Vide le cache si les filtres changent."""
    current_key = _get_cache_key()
    if st.session_state.get('_accueil_cache_key') != current_key:
        st.session_state['_accueil_cache'] = {}
        st.session_state['_accueil_cache_key'] = current_key

_clear_cache()

# Récupérer les données depuis la session
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
st.write("Nombre de lignes pour Newlys (Triangle) :", len(df_supermarche_full[df_supermarche_full['magasin_officiel'] == 'Newlys (Triangle)']))
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

# Fonctions originales conservées (pour compatibilité avec d'autres pages)
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
# Progression globale – Fusionnée (plus de semaine/week‑end, plus de ménages)
# ================================================================
st.header("📈 Progression globale")

if not selected_mags:
    st.info("ℹ️ Aucun magasin sélectionné.")
    heures_totales = 0.0
    q_sm_total = 0
    objectif_heures = 0
    objectif_q_sm = 0
    heures_mag = {}
    q_faits = {}
else:
    cached = _get_cached('progression')
    if cached is not None:
        heures_totales = cached['heures_totales']
        q_sm_total = cached['q_sm_total']
        objectif_heures = cached['objectif_heures']
        objectif_q_sm = cached['objectif_q_sm']
        heures_mag = cached['heures_mag']
        q_faits = cached['q_faits']
    else:
        # Restriction aux magasins sélectionnés pour les heures de comptage
        df_c_f_sel = df_c_f[df_c_f['lieu_officiel'].isin(selected_mags)] if not df_c_f.empty else pd.DataFrame()
        heures_totales = df_c_f_sel['duree_h'].sum() if not df_c_f_sel.empty else 0.0

        # Questionnaires supermarché valides (uniquement magasins sélectionnés)
        if not df_supermarche_full.empty:
            df_sm_valides = df_supermarche_full[df_supermarche_full['statut'] != 'Refus']
            df_sm_valides_sel = df_sm_valides[df_sm_valides['magasin_officiel'].isin(selected_mags)]
            q_sm_total = len(df_sm_valides_sel)
        else:
            q_sm_total = 0

        # Objectifs globaux (fusion des objectifs semaine + week‑end)
        objectif_heures = len(selected_mags) * 8    # 8h par magasin
        objectif_q_sm = len(selected_mags) * 100     # 100 questionnaires par magasin

        # Heures totales par magasin pour le tableau de détail
        heures_mag = {}
        for mag in selected_mags:
            sessions_mag = df_c_f_sel[df_c_f_sel['lieu_officiel'] == mag] if not df_c_f_sel.empty else pd.DataFrame()
            h_total = sessions_mag['duree_h'].sum() if not sessions_mag.empty else 0.0
            heures_mag[mag] = h_total

        # Questionnaires par magasin
        q_faits = {}
        for mag in selected_mags:
            if not df_supermarche_full.empty:
                df_mag = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
                valides = df_mag[df_mag['statut'] != 'Refus'] if 'statut' in df_mag.columns else df_mag
                q_faits[mag] = len(valides)
            else:
                q_faits[mag] = 0

        _set_cached('progression', {
            'heures_totales': heures_totales,
            'q_sm_total': q_sm_total,
            'objectif_heures': objectif_heures,
            'objectif_q_sm': objectif_q_sm,
            'heures_mag': heures_mag,
            'q_faits': q_faits
        })

# Affichage des métriques de progression (fusionnées)
col1, col2 = st.columns(2)
with col1:
    ratio_heures = min(1.0, heures_totales / objectif_heures) if objectif_heures > 0 else 0
    st.metric("Heures totales de comptage", f"{heures_totales:.1f} / {objectif_heures:.0f}")
    st.progress(ratio_heures)
with col2:
    ratio_q_sm = min(1.0, q_sm_total / objectif_q_sm) if objectif_q_sm > 0 else 0
    st.metric("Questionnaires supermarché valides", f"{q_sm_total} / {objectif_q_sm:.0f}")
    st.progress(ratio_q_sm)

# ================================================================
# Tableau de détail par magasin (heures totales)
# ================================================================
if selected_mags:
    rows_avancement = []
    for mag in selected_mags:
        h_total = heures_mag.get(mag, 0.0)
        q = q_faits.get(mag, 0)
        pct_heures = (h_total / 8) * 100 if h_total > 0 else 0
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
            'Heures totales': f"{h_total:.1f}",
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

    df_sm_sel = df_sm[df_sm['Nom'].isin(selected_mags)].copy()
    if price_cols:
        df_sm_sel['vend_huile'] = (df_sm_sel[price_cols] > 0).any(axis=1)
    else:
        df_sm_sel['vend_huile'] = True
    df_strates_sel = df_sm_sel.groupby(['Taille', 'Niveau_socio']).agg(
        magasins_sel=('Nom', list)
    ).reset_index()

    df_strates = df_strates_complet.merge(df_strates_sel, on=['Taille', 'Niveau_socio'], how='left')
    df_strates['magasins_sel'] = df_strates['magasins_sel'].apply(lambda x: x if isinstance(x, list) else [])

    def get_heures_et_questionnaires(magasins):
        heures_tot = 0.0
        nb_q = 0
        for mag in magasins:
            if not df_c_f.empty:
                sessions = df_c_f[df_c_f['lieu_officiel'] == mag]
                if not sessions.empty:
                    heures_tot += sessions['duree_h'].sum()
            if not df_supermarche_full.empty:
                q_mag = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
                if 'statut' in q_mag.columns:
                    nb_q += len(q_mag[q_mag['statut'] != 'Refus'])
                else:
                    nb_q += len(q_mag)
        return heures_tot, nb_q

    rows_strates = []
    for _, row in df_strates.iterrows():
        taille = row['Taille']
        niveau = row['Niveau_socio']
        nb_total = row['nb_total']
        nb_vend_huile = row['nb_vend_huile']
        pct_vend = (nb_vend_huile / nb_total * 100) if nb_total > 0 else 0
        mags_sel = row['magasins_sel']
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
        total_heures, nb_q = get_heures_et_questionnaires(mags_sel)
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