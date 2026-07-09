# pages/04_Flux.py
"""Page Comptages & Flux."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import numpy as np
from utils import *
from analytics import *
import json
import re

# Récupérer les données depuis la session

import os
import sys
import re
import json
import hashlib
from datetime import datetime, time, date, timedelta

df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
secteur_profiles = st.session_state.get('secteur_profiles', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', pd.DataFrame())

# DataFrames supplémentaires
date_range = st.session_state.get('date_range', (None, None))
df_profils_long = st.session_state.get('df_profils_long', pd.DataFrame())

st.header("Comptages & Flux")

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
# Fonctions internes à l'onglet (inchangées sauf estimate_daily_flow_onglet)
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
def estimate_daily_flow_onglet(magasin, jour_code, k, profil):
    """Nouvelle version avec un seul k."""
    if k is None:
        return [0]*24, 0
    is_we = jour_code in ['Sa', 'Su']
    sm_row = df_sm[df_sm['Nom'] == magasin]
    if sm_row.empty:
        ouvert = [True]*24
    else:
        ouvert = get_opening_hours(sm_row.iloc[0], 'semaine' if not is_we else 'weekend')
    clients = [int(round(k * profil[h])) if ouvert[h] else 0 for h in range(24)]
    return clients, sum(clients)
# --------------------------------------------------------
# Correspondance magasin – profil Google (inchangée)
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
# Calcul des k pour tous les magasins sélectionnés (avec sérialisation)
# --------------------------------------------------------
selected_mags_tuple = tuple(selected_mags)
all_k_data = compute_all_k_data(
    selected_mags_tuple,
    make_hashable(df_c_f),
    df_sm,
    df_profils_pivot,
    make_hashable(secteur_profiles) if secteur_profiles is not None else None,
    magasin_mapping,
    k_overrides
)
# --------------------------------------------------------
# Tableau synthétique des k (adapté)
# --------------------------------------------------------
st.subheader("📊 Synthèse des facteurs k")
rows_synthese = []
for mag in selected_mags:
    data = all_k_data[mag]
    k = data['k']
    details = data['details']
    cv_val = 0.0
    if k is not None and len(details) > 1:
        k_vals = [d['k'] for d in details]
        cv_val = np.std(k_vals) / np.mean(k_vals) if np.mean(k_vals) != 0 else 0.0
    _, source, _ = get_effective_profile(mag, 'Mo')
    rows_synthese.append({
        'Magasin': mag,
        'k_num': k,
        'cv_num': cv_val,
        'Nb comptages': len(details),
        'Source profil': source
    })
df_synthese = pd.DataFrame(rows_synthese)
seuil_cv = st.slider("Seuil d'alerte CV", 0.0, 1.0, 0.3, 0.05, key="cv_slider")
alertes = df_synthese[df_synthese['cv_num'] > seuil_cv]
df_synthese_disp = df_synthese.copy()
df_synthese_disp['k'] = df_synthese_disp['k_num'].apply(lambda x: fmt_nombre(x, 2) if pd.notna(x) else "")
df_synthese_disp['CV'] = df_synthese_disp['cv_num'].apply(lambda x: fmt_nombre(x, 2))
st.dataframe(df_synthese_disp[['Magasin', 'k', 'CV', 'Nb comptages', 'Source profil']], width='stretch')
if not alertes.empty:
    st.warning(f"{len(alertes)} magasin(s) avec une dispersion élevée (CV > {seuil_cv}) :")
    st.dataframe(alertes[['Magasin', 'cv_num']].rename(columns={'cv_num': 'CV'}), width='stretch')
with st.expander("🔧 Forcer manuellement le facteur k"):
    mag_force = st.selectbox("Choisir un magasin", [""] + selected_mags, key="mag_force")
    if mag_force:
        current_over = k_overrides.get(mag_force, {})
        current_k = current_over.get('k', all_k_data[mag_force]['k'])
        new_k = st.number_input(f"k pour {mag_force}", value=float(current_k) if current_k is not None else 0.0, step=10.0)
        if st.button("Appliquer le forçage", key="force_k"):
            overrides = load_k_overrides()
            overrides[mag_force] = {'k': new_k}
            save_k_overrides(overrides)
            st.success("Facteur k forcé. Rechargez la page pour le prendre en compte.")
            st.rerun()
# --------------------------------------------------------
# Graphiques intégrés par magasin (adaptés)
# --------------------------------------------------------
st.subheader("📈 Profil, plages de comptage et évolution des k")
mag_choisi = st.selectbox("Magasin à visualiser", selected_mags, key="mag_vizu")
if mag_choisi:
    data = all_k_data[mag_choisi]
    k = data['k']
    details = data['details']
    jours_sem = ['Mo', 'Tu', 'We', 'Th', 'Fr']
    jours_we  = ['Sa', 'Su']
    profils_sem, profils_we = [], []
    for jour in jours_sem:
        profil, _, _ = get_effective_profile(mag_choisi, jour)
        clients, _ = estimate_daily_flow_onglet(mag_choisi, jour, k, profil)
        profils_sem.append(clients)
    for jour in jours_we:
        profil, _, _ = get_effective_profile(mag_choisi, jour)
        clients, _ = estimate_daily_flow_onglet(mag_choisi, jour, k, profil)
        profils_we.append(clients)
    median_sem = np.median(profils_sem, axis=0) if profils_sem else [0]*24
    median_we  = np.median(profils_we, axis=0) if profils_we else [0]*24
    heures = list(range(24))
    # Agrégation des k par heure (tous types de jours confondus)
    k_par_heure = {h: [] for h in heures}
    for d in details:
        debut_h = d['debut_dt'].hour + d['debut_dt'].minute/60
        fin_h   = d['fin_dt'].hour + d['fin_dt'].minute/60
        for h in range(int(debut_h), min(int(fin_h)+1, 24)):
            k_par_heure[h].append(d['k'])
    # Couverture par heure (inchangé, mais sans distinction semaine/week-end pour les boxplots)
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
    # Boxplots de k (un seul par heure, couleur neutre)
    for h in heures:
        if k_par_heure[h]:
            fig.add_trace(go.Box(y=k_par_heure[h], x=[h]*len(k_par_heure[h]),
                                 name='k', legendgroup='k',
                                 showlegend=(h==0), marker=dict(color='green'),
                                 boxpoints='all', jitter=0.3, pointpos=0, width=0.3),
                          row=1, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Heure", tickvals=heures[::2],
                     ticktext=[f"{h}h" for h in heures[::2]], row=1, col=1)
    fig.update_yaxes(title_text="Clients estimés / heure", tickformat=",.0f", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Facteur k", row=1, col=1, secondary_y=True)
    # Sous-graphique 2
    fig.add_trace(go.Bar(x=heures, y=pct_sem, name='% couverture semaine',
                         marker=dict(color='blue', opacity=0.6)), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Bar(x=heures, y=pct_we, name='% couverture week‑end',
                         marker=dict(color='orange', opacity=0.6)), row=2, col=1, secondary_y=False)
    for h in heures:
        if k_par_heure[h]:
            fig.add_trace(go.Box(y=k_par_heure[h], x=[h]*len(k_par_heure[h]),
                                 name='k', legendgroup='k2',
                                 showlegend=False, marker=dict(color='green'),
                                 boxpoints='all', jitter=0.3, pointpos=0, width=0.3),
                          row=2, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Heure", tickvals=heures[::2],
                     ticktext=[f"{h}h" for h in heures[::2]], row=2, col=1)
    fig.update_yaxes(title_text="% couverture", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Facteur k", row=2, col=1, secondary_y=True)
    fig.update_layout(height=800, title_text=f"Analyse intégrée – {mag_choisi}", template="gilroy_export")
    fig = force_black_axes(fig)
    st.plotly_chart(fig, width='stretch', key="analyse_integree")
    nb_comptages = len(details)
    st.caption(f"Basé sur {nb_comptages} session(s) de comptage pour ce magasin. Les boxplots montrent la distribution des facteurs k par heure.")
# --------------------------------------------------------
# Périodes d’affluence par secteur (Google) – inchangé
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
            fig_heat_sem = px.imshow(df_sem_heat,
                                     labels=dict(x="Heure", y="Secteur", color="Occupation (%)"),
                                     title="Affluence moyenne en semaine (lun-ven)")
            fig_heat_sem.update_xaxes(tickvals=list(range(0,24,2)))
            fig_heat_sem.update_layout(template="gilroy_export")
            fig_heat_sem = force_black_axes(fig_heat_sem)
            st.plotly_chart(fig_heat_sem, width='stretch', key="heat_sem")
            st.caption(f"Basé sur les profils Google de {len(df_sem_heat)} secteurs. Les valeurs sont en % d'occupation maximale.")
        with col2:
            st.markdown("**Week‑end (sam‑dim)**")
            we_data = []
            for secteur in secteurs_a_afficher:
                row = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                vals = [np.mean([row.get(f"{j}_{h}", 0.0) for j in ['Sa','Su']]) for h in range(24)]
                we_data.append(vals)
            df_we_heat = pd.DataFrame(we_data, index=secteurs_a_afficher, columns=[f"{h}h" for h in range(24)])
            fig_heat_we = px.imshow(df_we_heat,
                                    labels=dict(x="Heure", y="Secteur", color="Occupation (%)"),
                                    title="Affluence moyenne en week-end (sam-dim)")
            fig_heat_we.update_xaxes(tickvals=list(range(0,24,2)))
            fig_heat_we.update_layout(template="gilroy_export")
            fig_heat_we = force_black_axes(fig_heat_we)
            st.plotly_chart(fig_heat_we, width='stretch', key="heat_we")
            st.caption(f"Basé sur les profils Google de {len(df_we_heat)} secteurs. Les valeurs sont en % d'occupation maximale.")
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
        fig_pointe.update_yaxes(title_text="Occupation (%)")
        fig_pointe.update_layout(title=f"Profil d’affluence – secteur {secteur_sel} (avec top 3 heures)", template="gilroy_export")
        fig_pointe = force_black_axes(fig_pointe)
        st.plotly_chart(fig_pointe, width='stretch', key="pointe_secteur")
        st.caption(f"Basé sur les données Google Popular Times pour le secteur {secteur_sel}. Les zones colorées mettent en évidence les 3 heures de pointe.")
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
        st.dataframe(df_top, width='stretch')
        st.caption(f"Basé sur les données Google Popular Times pour les {len(secteurs_a_afficher)} secteurs affichés.")
# --------------------------------------------------------
# Couverture des plages horaires (inchangé)
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
        st.plotly_chart(fig_cov, width='stretch', key="cov_hours")
        st.caption(f"Basé sur {len(sessions)} sessions de comptage. Les rectangles colorés montrent les plages horaires couvertes, les zones grisées les horaires d'ouverture du magasin.")
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
# Contrôle de cohérence flux estimé vs réel (adapté)
# --------------------------------------------------------
st.subheader("🔍 Contrôle de cohérence : flux estimé vs flux réel")
mag_c = st.selectbox("Magasin pour cohérence", selected_mags, key="mag_coherence")
if mag_c:
    data = all_k_data[mag_c]
    k = data['k']
    details = data['details']
    if not details:
        st.info("Aucun comptage pour ce magasin.")
    else:
        points = []
        for d in details:
            if k is None: continue
            flux_pred = k * d['G_moy']
            points.append({'flux_réel': d['flux_reel'], 'flux_prédit': flux_pred, 'k': d['k'],
                           'date': d['date'], 'source': d['source']})
        if points:
            df_points = pd.DataFrame(points)
            fig_coher = px.scatter(df_points, x='flux_prédit', y='flux_réel',
                                   hover_data=['date', 'k', 'source'],
                                   labels={'flux_prédit': 'Flux prédit (clients/h)', 'flux_réel': 'Flux réel (clients/h)'},
                                   title=f"Flux réel vs Flux prédit – {mag_c}")
            max_val = max(df_points['flux_prédit'].max(), df_points['flux_réel'].max())
            fig_coher.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], mode='lines',
                                           name='y=x', line=dict(dash='dash', color='black')))
            fig_coher.update_xaxes(title_text="Flux prédit (clients/h)", tickformat=",.0f")
            fig_coher.update_yaxes(title_text="Flux réel (clients/h)", tickformat=",.0f")
            fig_coher.update_layout(template="gilroy_export")
            fig_coher = force_black_axes(fig_coher)
            st.plotly_chart(fig_coher, width='stretch', key="coherence")
            st.caption(f"Basé sur {len(points)} sessions de comptage. La droite y=x représente une prédiction parfaite.")
        else:
            st.info("Impossible de calculer les flux prédits (k manquant).")
# --------------------------------------------------------
# Détection des comptages aberrants (adaptée)
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
    st.dataframe(df_aberr, width='stretch')
    st.caption(f"Basé sur {len(df_aberr)} comptages identifiés comme aberrants selon le seuil IQR.")
else:
    st.success("Aucun comptage aberrant détecté.")
# --------------------------------------------------------
# Gestion des comptages aberrants par magasin (inchangé)
# --------------------------------------------------------
st.subheader("🔧 Gestion des comptages aberrants par magasin")
if not selected_mags:
    st.info("Veuillez sélectionner des magasins dans l'onglet Accueil.")
else:
    mag_aberrant = st.selectbox(
        "Choisir un magasin pour visualiser les comptages",
        selected_mags,
        key="mag_aberrant_select"
    )
if mag_aberrant:
    sessions = df_c_f[df_c_f['lieu_officiel'] == mag_aberrant].copy()
    if sessions.empty:
        st.info("Aucun comptage pour ce magasin.")
    else:
        # Sérialisation avant appel à la fonction cachée
        df_c_f_ser = make_hashable(df_c_f)
        secteur_profiles_ser = make_hashable(secteur_profiles) if secteur_profiles is not None else None
        k, details = cached_compute_k_factors(
            mag_aberrant,
            df_c_f_ser,
            df_sm,
            df_profils_pivot,
            secteur_profiles_ser,
            magasin_mapping
        )
        if not details:
            st.info("Aucune session avec un k calculable (G_moy probablement nul).")
        else:
            df_details = pd.DataFrame(details)
            df_details['Date'] = df_details['date']
            df_details['Début'] = df_details['debut']
            df_details['Fin'] = df_details['fin']
            df_details['Durée (h)'] = df_details['duree_h'].round(2)
            df_details['Total'] = df_details['total']
            df_details['Flux réel (clients/h)'] = df_details['flux_reel'].round(2)
            df_details['G_moy'] = df_details['G_moy'].round(2)
            df_details['k'] = df_details['k'].round(2)
            k_values = df_details['k'].dropna()
            if len(k_values) > 1:
                Q1 = np.percentile(k_values, 25)
                Q3 = np.percentile(k_values, 75)
                IQR = Q3 - Q1
                seuil_bas = Q1 - 1.5 * IQR
                seuil_haut = Q3 + 1.5 * IQR
                st.write("**Statistiques sur k pour ce magasin :**")
                st.write(
                    f"Médiane : {np.median(k_values):.2f}, "
                    f"Q1 : {Q1:.2f}, Q3 : {Q3:.2f}, IQR : {IQR:.2f}"
                )
                st.write(
                    f"Seuils pour aberrants (1.5 IQR) : "
                    f"< {seuil_bas:.2f} ou > {seuil_haut:.2f}"
                )
                df_details['Alerte'] = df_details['k'].apply(
                    lambda x: '⚠️ Aberrant' if (x < seuil_bas or x > seuil_haut) else ''
                )
            else:
                df_details['Alerte'] = ''
            cols_to_show = [
                'Date', 'Début', 'Fin', 'Durée (h)',
                'Total', 'Flux réel (clients/h)', 'G_moy', 'k', 'Alerte'
            ]
            df_display = df_details[cols_to_show].copy()
            df_display.columns = [
                'Date', 'Début', 'Fin', 'Durée (h)',
                'Total', 'Flux réel', 'G_moy', 'k', 'Alerte'
            ]
            st.write("**Sessions de comptage :**")
            selection = st.dataframe(
                df_display,
                width='stretch',
                on_select="rerun",
                selection_mode="multi-row",
                key="aberrant_selection"
            )
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df_details.iloc[selected_indices]
                st.write(f"**{len(selected_rows)} session(s) sélectionnée(s).**")
                st.write("UUID des sessions sélectionnées :")
                st.write(selected_rows['uuid'].tolist())
                if st.button("🗑️ Supprimer les sessions sélectionnées", key="del_aberrant"):
                    try:
                        conn = get_db_connection()
                        if conn is None:
                            st.error("Connexion DB impossible.")
                        else:
                            cur = conn.cursor()
                            uuids_to_delete = selected_rows['uuid'].tolist()
                            placeholders = ','.join(['?'] * len(uuids_to_delete))
                            cur.execute(
                                f"DELETE FROM countings WHERE uuid IN ({placeholders})",
                                uuids_to_delete
                            )
                            conn.commit()
                        load_db_internal.clear()
                        cached_compute_k_factors.clear()
                        st.success(f"{len(uuids_to_delete)} session(s) supprimée(s).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur lors de la suppression : {e}")
            else:
                st.info("Sélectionnez une ou plusieurs lignes pour les supprimer.")
# --------------------------------------------------------
# Estimation de la fréquentation totale par magasin et par segment
# --------------------------------------------------------
st.subheader("📊 Estimation de la fréquentation totale par magasin")
mags_avec_k = [m for m in selected_mags if all_k_data[m]['k'] is not None]
if not mags_avec_k:
    st.info("Aucun magasin avec facteur k calculable (pas assez de comptages).")
else:
    rows_estimation = []
    for mag in mags_avec_k:
        data = all_k_data[mag]
        k = data['k']
        details = data['details']
        profil_sem, _, _ = get_effective_profile(mag, 'Mo')
        profil_we, _, _  = get_effective_profile(mag, 'Sa')
        # Clients par jour (semaine et week‑end) avec le même k
        clients_sem, _ = estimate_daily_flow_onglet(mag, 'Mo', k, profil_sem)
        clients_we, _  = estimate_daily_flow_onglet(mag, 'Sa', k, profil_we)
        sem_jour = sum(clients_sem)
        we_jour  = sum(clients_we)
        total_med = 5 * sem_jour + 2 * we_jour
        # Pas d'intervalle interquartile si on n'a plus qu'un seul k, on peut calculer un écart-type via bootstrap simple
        # On pourrait récupérer les k des sessions pour obtenir une dispersion, mais ici on se contente d'une valeur unique.
        rows_estimation.append({
            'Magasin': mag,
            'Jour semaine': f"{fmt_volume(sem_jour)}",
            'Jour WE': f"{fmt_volume(we_jour)}",
            'Total hebdo': f"{fmt_volume(total_med)}",
            'sem_med': sem_jour,
            'we_med': we_jour,
            'total_med': total_med
        })
    df_estim = pd.DataFrame(rows_estimation)
    st.dataframe(df_estim[['Magasin', 'Jour semaine', 'Jour WE', 'Total hebdo']], width='stretch')
    st.caption(f"Estimations basées sur {len(df_estim)} magasins avec facteur k calculable.")
    # Agrégation par segment
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
            médiane_jour_we=('we_med', 'median'),
            médiane_total=('total_med', 'median')
        ).reset_index()
        agg_median['Jour semaine'] = agg_median['médiane_jour_sem'].apply(lambda x: fmt_volume(x))
        agg_median['Jour WE'] = agg_median['médiane_jour_we'].apply(lambda x: fmt_volume(x))
        agg_median['Total hebdo'] = agg_median['médiane_total'].apply(lambda x: fmt_volume(x))
        st.dataframe(agg_median[['Segment', 'nb_magasins', 'Jour semaine', 'Jour WE', 'Total hebdo']], width='stretch')
        st.caption(f"Basé sur {agg_median['nb_magasins'].sum()} magasins. Médianes des fréquentations.")
        col1, col2 = st.columns(2)
        with col1:
            fig_box_sem = px.box(df_estim, x='Segment', y='sem_med',
                                 labels={'Segment': 'Segment', 'sem_med': 'Clients estimés par jour de semaine'},
                                 title="Clients estimés par jour de semaine", points="all")
            fig_box_sem.update_xaxes(tickangle=45)
            fig_box_sem.update_yaxes(tickformat=",.0f")
            fig_box_sem.update_layout(template="gilroy_export")
            fig_box_sem = force_black_axes(fig_box_sem)
            st.plotly_chart(fig_box_sem, width='stretch', key="box_sem")
            st.caption(f"Basé sur {len(df_estim)} magasins. Les points représentent chaque magasin.")
        with col2:
            fig_box_we = px.box(df_estim, x='Segment', y='we_med',
                                labels={'Segment': 'Segment', 'we_med': 'Clients estimés par jour de week-end'},
                                title="Clients estimés par jour de week-end", points="all")
            fig_box_we.update_xaxes(tickangle=45)
            fig_box_we.update_yaxes(tickformat=",.0f")
            fig_box_we.update_layout(template="gilroy_export")
            fig_box_we = force_black_axes(fig_box_we)
            st.plotly_chart(fig_box_we, width='stretch', key="box_we")
            st.caption(f"Basé sur {len(df_estim)} magasins. Les points représentent chaque magasin.")
        fig_box_total = px.box(df_estim, x='Segment', y='total_med',
                               labels={'Segment': 'Segment', 'total_med': 'Total hebdomadaire estimé'},
                               title="Total hebdomadaire estimé par magasin", points="all")
        fig_box_total.update_xaxes(tickangle=45)
        fig_box_total.update_yaxes(tickformat=",.0f")
        fig_box_total.update_layout(template="gilroy_export")
        fig_box_total = force_black_axes(fig_box_total)
        st.plotly_chart(fig_box_total, width='stretch', key="box_total")
        st.caption(f"Basé sur {len(df_estim)} magasins. Les points représentent chaque magasin.")
    # Stockage sécurisé pour l'export
    if 'df_estim' in locals():
        st.session_state['freq_magasin'] = df_estim[['Magasin', 'Jour semaine', 'Jour WE', 'Total hebdo']].copy()
    else:
        st.session_state['freq_magasin'] = None
    if 'agg_median' in locals():
        st.session_state['freq_segment'] = agg_median[['Segment', 'nb_magasins', 'Jour semaine', 'Jour WE', 'Total hebdo']].copy()
    else:
        st.session_state['freq_segment'] = None
# --------------------------------------------------------
# Diagramme en barres : fréquentation hebdomadaire par magasin
# --------------------------------------------------------
st.subheader("📊 Fréquentation hebdomadaire par magasin (tri décroissant)")
df_estim_sorted = df_estim.sort_values('total_med', ascending=False).copy()
df_estim_sorted['Magasin_court'] = df_estim_sorted['Magasin'].apply(
    lambda x: x[:25] + '...' if len(x) > 25 else x
)
fig_freq_bars = go.Figure()
fig_freq_bars.add_trace(go.Bar(
    x=df_estim_sorted['Magasin_court'],
    y=df_estim_sorted['sem_med'] * 5,
    name='Clients semaine',
    marker_color='steelblue'
))
fig_freq_bars.add_trace(go.Bar(
    x=df_estim_sorted['Magasin_court'],
    y=df_estim_sorted['we_med'] * 2,
    name='Clients week‑end',
    marker_color='darkorange'
))
fig_freq_bars.update_layout(
    barmode='stack',
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
st.caption(f"Basé sur {len(df_estim_sorted)} magasins avec facteur k calculable.")
# ------------------------------------------------------------
# ONGLET 5 : ESTIMATION DU MARCHÉ (corrigé)
# ------------------------------------------------------------
