# pages/09_Cartographie.py
"""Page Cartographie."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
from utils import *
import folium
from streamlit_folium import st_folium
import branca
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
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
date_range = st.session_state.get('sidebar_date_range', (None, None))

st.header("Cartographie")

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
# ----- Agrégation des mesures GPS (avec UUID et enquêteur) -----
def safe_get_gps(row):
    """Extrait la chaîne GPS depuis data_dict, qui peut être un dict ou une str JSON."""
    data = row.get('data_dict', {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    if isinstance(data, dict):
        return data.get('GPS', '')
    return ''
measures = []
# Questionnaires supermarché
if not df_supermarche.empty:
    for _, row in df_supermarche.iterrows():
        gps_val = safe_get_gps(row)
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
# Questionnaires ménage
if not df_menage.empty:
    for _, row in df_menage.iterrows():
        gps_val = safe_get_gps(row)
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
# Comptages
if not df_c_f.empty:
    for _, row in df_c_f.iterrows():
        gps_val = safe_get_gps(row)
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
# ----- Mesures liées à un supermarché (hors ménages) -----
mag_meas = df_meas[~df_meas['magasin'].str.startswith('Ménage')].copy()
mag_meas['magasin_norm'] = mag_meas['magasin'].apply(normalize_name)
# ----- Positions médianes par magasin -----
median_pos = mag_meas.groupby('magasin_norm').agg(
    lat_med=('lat', 'median'),
    lon_med=('lon', 'median'),
    nb_mesures=('lat', 'count')
).reset_index()
if not df_sm.empty:
    nom_map = dict(zip(df_sm['nom_norm'], df_sm['Nom']))
    median_pos['Nom officiel'] = median_pos['magasin_norm'].map(nom_map).fillna(median_pos['magasin_norm'])
else:
    median_pos['Nom officiel'] = median_pos['magasin_norm']
# ----- Positions manuelles -----
manual = load_manual_positions()
def get_final_lat(row):
    key = row['Nom officiel']
    if key in manual and 'lat' in manual[key]:
        return manual[key]['lat']
    return row['lat_med']
def get_final_lon(row):
    key = row['Nom officiel']
    if key in manual and 'lon' in manual[key]:
        return manual[key]['lon']
    return row['lon_med']
median_pos['lat_final'] = median_pos.apply(get_final_lat, axis=1)
median_pos['lon_final'] = median_pos.apply(get_final_lon, axis=1)
median_pos['manuel'] = median_pos['Nom officiel'].apply(lambda x: x in manual)
# ----- Section 1 : Tableau et anomalies (inchangé) -----
st.subheader("📋 Coordonnées médianes des magasins sélectionnés")
mags_selected = st.session_state.get('selected_magasins', [])

df_menage = st.session_state.get('df_menage', pd.DataFrame())

df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
date_range = st.session_state.get('date_range', (None, None))
selected_mags = st.session_state.get('selected_mags', [])
if not mags_selected:
    st.info("Aucun magasin sélectionné (onglet Accueil).")
    st.stop()
selected_norm = {normalize_name(m): m for m in mags_selected}
median_pos_sel = median_pos[median_pos['magasin_norm'].isin(selected_norm.keys())].copy()
if median_pos_sel.empty:
    st.info("Aucun magasin sélectionné ne possède de mesure GPS.")
    st.stop()
display_df = median_pos_sel[['Nom officiel', 'lat_final', 'lon_final', 'nb_mesures']].copy()
display_df.columns = ['Magasin', 'Latitude médiane', 'Longitude médiane', 'Nb mesures']
st.dataframe(display_df, width='stretch')
# Détection des mesures anormales (écart > 150 m)
seuil_anomalie_m = 150
anomalies = []
for _, store_row in median_pos_sel.iterrows():
    store_norm = store_row['magasin_norm']
    store_lat = store_row['lat_med']
    store_lon = store_row['lon_med']
    store_meas = mag_meas[mag_meas['magasin_norm'] == store_norm]
    for _, m_row in store_meas.iterrows():
        dist = haversine(m_row['lat'], m_row['lon'], store_lat, store_lon)
        if dist > seuil_anomalie_m / 1000.0:
            anomalies.append({
                'Magasin': store_row['Nom officiel'],
                'Date': m_row['date'].strftime('%Y-%m-%d %H:%M') if pd.notna(m_row['date']) else '',
                'Type': m_row['type'],
                'Distance (m)': int(dist * 1000),
                'UUID': m_row.get('uuid', ''),
                'Enquêteur': m_row.get('enqueteur', '')
            })
if anomalies:
    st.warning(f"{len(anomalies)} mesure(s) anormale(s) détectée(s) (écart > {seuil_anomalie_m} m de la médiane du magasin).")
    with st.expander("🔍 Voir les mesures anormales"):
        st.dataframe(pd.DataFrame(anomalies), width='stretch')
else:
    st.success("Aucune mesure anormale détectée parmi les magasins sélectionnés.")
# ----- Barre latérale des options de la carte -----
with st.sidebar:
    st.subheader("📊 Options carte")
    show_mesures = st.checkbox("Afficher les mesures individuelles", value=False)
    show_menages = st.checkbox("Inclure les questionnaires ménage", value=False)
    use_cluster = st.checkbox("Regrouper les mesures (clusters)", value=True, disabled=not show_mesures)
    if show_mesures:
        types_dispo = ['Tous'] + list(df_meas['type'].unique())
        type_sel = st.selectbox("Type de mesure à afficher", types_dispo)
    else:
        type_sel = 'Tous'
df_meas_filtered = df_meas.copy()
if not show_menages:
    df_meas_filtered = df_meas_filtered[df_meas_filtered['type'] != 'Questionnaire ménage']
if show_mesures and type_sel != 'Tous':
    df_meas_filtered = df_meas_filtered[df_meas_filtered['type'] == type_sel]
# ----- Couleurs (palette foncée) -----
if not df_sm.empty:
    df_sm_copy = df_sm.copy()
    df_sm_copy['Segment'] = df_sm_copy['Taille'].fillna('?') + ' / ' + df_sm_copy['Niveau_socio'].fillna('?')
    segments_uniques = sorted(df_sm_copy['Segment'].unique())
    from plotly.express import colors as px_colors
    dark_palette = px_colors.qualitative.Dark24
    seg_color_map = {seg: dark_palette[i % len(dark_palette)] for i, seg in enumerate(segments_uniques)}
else:
    df_sm_copy = pd.DataFrame()
    seg_color_map = {'Inconnu': '#1f77b4'}
# ----- Création de la carte (avec échelle) -----
center_lat = median_pos_sel['lat_final'].mean()
center_lon = median_pos_sel['lon_final'].mean()
m = folium.Map(location=[center_lat, center_lon], zoom_start=13,
               tiles='OpenStreetMap', control_scale=True)
# ----- Flèche nord (boussole) -----
north_arrow_html = '''
<div style="position: absolute; bottom: 10px; left: 10px; width: 40px; height: 40px; z-index: 1000;">
    <svg viewBox="0 0 40 40">
        <polygon points="20,0 0,40 40,40" fill="#cc0000" />
        <text x="20" y="34" text-anchor="middle" font-size="11" fill="white" font-weight="bold">N</text>
    </svg>
</div>
'''
m.get_root().html.add_child(folium.Element(north_arrow_html))
# ----- Affichage des supermarchés (cercles non remplis) -----
for _, row in median_pos_sel.iterrows():
    nom_off = row['Nom officiel']
    match = df_sm_copy[df_sm_copy['Nom'] == nom_off]
    segment = match['Segment'].iloc[0] if not match.empty else 'Inconnu'
    couleur = seg_color_map.get(segment, 'gray')
    popup_text = f"""
    <b>{row['Nom officiel']}</b><br>
    Segment : {segment}<br>
    Nb mesures : {row['nb_mesures']}<br>
    Position : {row['lat_final']:.6f}, {row['lon_final']:.6f}<br>
    {'<i>(corrigée manuellement)</i>' if row['manuel'] else '(médiane)'}
    """
    folium.CircleMarker(
        location=[row['lat_final'], row['lon_final']],
        radius=6,
        popup=folium.Popup(popup_text, max_width=250),
        tooltip=row['Nom officiel'],
        color=couleur,
        fill=False,
        weight=3,
        opacity=0.9
    ).add_to(m)
# ----- Mesures individuelles (si demandé) -----
if show_mesures and not df_meas_filtered.empty:
    if use_cluster:
        cluster = MarkerCluster().add_to(m)
    for _, row in df_meas_filtered.iterrows():
        if row['type'] == 'Questionnaire SM':
            couleur = 'green'
        elif row['type'] == 'Questionnaire ménage':
            couleur = 'orange'
        else:
            couleur = 'red'
        popup = f"{row['type']}<br>{row['magasin']}<br>{row['date'].strftime('%Y-%m-%d %H:%M') if pd.notna(row['date']) else ''}"
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=3,
            popup=popup,
            color=couleur,
            fill=True,
            fill_opacity=0.7,
            weight=1
        ).add_to(cluster if use_cluster else m)
# ----- Affichage de la carte -----
st_folium(m, width=900, height=600)
# ----- Légende sous la carte (affichage Streamlit) -----
st.subheader("Légende")
segments_presents = sorted(median_pos_sel['Nom officiel'].apply(
    lambda x: df_sm_copy[df_sm_copy['Nom'] == x]['Segment'].iloc[0] if not df_sm_copy[df_sm_copy['Nom'] == x].empty else 'Inconnu'
).unique())
legend_display = '<div style="display:flex; flex-wrap:wrap; gap:15px; align-items:center; font-size:14px;">'
legend_display += '<b>Supermarchés (segment) :</b>'
for seg in segments_presents:
    color = seg_color_map.get(seg, 'gray')
    legend_display += f'<span style="display:inline-block; margin-left:10px;"><span style="display:inline-block; width:12px; height:12px; border:3px solid {color}; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>{seg}</span>'
if show_mesures:
    legend_display += '<br><b>Mesures :</b>'
    legend_display += '<span style="display:inline-block; margin-left:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:green; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Questionnaire SM</span>'
    legend_display += '<span style="display:inline-block; margin-left:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:red; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Comptage</span>'
    if show_menages:
        legend_display += '<span style="display:inline-block; margin-left:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:orange; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Ménage</span>'
legend_display += '</div>'
st.markdown(legend_display, unsafe_allow_html=True)
# ----- Export HTML (carte + légende) -----
map_html = m.get_root().render()
legend_export = '<div style="margin-top:10px; font-family:Arial; font-size:14px;">'
legend_export += '<b>Légende</b><br/>'
legend_export += 'Supermarchés (segment) :<br/>'
for seg in segments_presents:
    color = seg_color_map.get(seg, 'gray')
    legend_export += f'<span style="display:inline-block; margin-right:10px;"><span style="display:inline-block; width:12px; height:12px; border:3px solid {color}; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>{seg}</span><br/>'
if show_mesures:
    legend_export += '<br/>Mesures :<br/>'
    legend_export += '<span style="display:inline-block; margin-right:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:green; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Questionnaire SM</span><br/>'
    legend_export += '<span style="display:inline-block; margin-right:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:red; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Comptage</span><br/>'
    if show_menages:
        legend_export += '<span style="display:inline-block; margin-right:10px;"><span style="display:inline-block; width:12px; height:12px; background-color:orange; border-radius:50%; margin-right:4px; vertical-align:middle;"></span>Ménage</span><br/>'
legend_export += '</div>'
full_html = map_html.replace('</body>', legend_export + '</body>')
st.download_button(
    label="📥 Télécharger la carte (HTML)",
    data=full_html,
    file_name="carte_supermarches.html",
    mime="text/html",
)
# ============================================================
# NOUVELLE SECTION : ANALYSE SPATIALE DES INDICATEURS (avec cache)
# ============================================================
st.divider()
st.subheader("📍 Analyse spatiale des indicateurs par magasin")
if not mags_selected:
    st.info("Aucun magasin sélectionné.")
else:
    # Coordonnées finales (déjà dans median_pos_sel)
    coord_map = {}
    for _, row in median_pos_sel.iterrows():
        coord_map[row['Nom officiel']] = (row['lat_final'], row['lon_final'])
    # ----- Fonction de calcul des métriques (version avec paramètres) -----
    def compute_store_metrics(mag, df_c_f, df_supermarche_full, df_sm, df_profils_pivot):
        """Retourne fréquentation, taux d'achat, volume annuel pour un magasin."""
        comptages = df_c_f[df_c_f['lieu_officiel'] == mag].copy()
        if comptages.empty:
            return {'frequentation': None, 'ti': None, 'qi': None, 'volume_annuel': None}
        # Récupération des facteurs k (simplifiée)
        jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}
        k_sem_list, k_we_list = [], []
        for _, row in comptages.iterrows():
            date_obj = row['date_dt']
            jour_code = date_obj.strftime('%a')
            jour_google = jour_map.get(jour_code, jour_code)
            # Profil simplifié (uniforme si pas de données Google)
            profil = [1.0]*24  # Simplification pour l'analyse spatiale
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
            if date_obj.weekday() >= 5:
                k_we_list.append(k)
            else:
                k_sem_list.append(k)
        k_sem = np.median(k_sem_list) if k_sem_list else None
        k_we  = np.median(k_we_list) if k_we_list else None
        if k_sem is None and k_we is not None: k_sem = k_we
        if k_we is None and k_sem is not None: k_we = k_sem
        if k_sem is None or k_we is None:
            return {'frequentation': None, 'ti': None, 'qi': None, 'volume_annuel': None}
        # Flux hebdomadaire simplifié (heures d'ouverture 8h-18h)
        heures_sem = list(range(8, 18))
        heures_we = list(range(8, 18))
        clients_sem = [k_sem * 1.0 for _ in heures_sem]
        clients_we  = [k_we * 1.0 for _ in heures_we]
        freq_hebdo = 5 * sum(clients_sem) + 2 * sum(clients_we)
        # Questionnaires supermarché
        df_sm_q = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
        total_q = len(df_sm_q[df_sm_q['statut'] != 'Refus']) if 'statut' in df_sm_q.columns else len(df_sm_q)
        acheteurs = df_sm_q[(df_sm_q['Q1'] == 'Oui') & (df_sm_q['statut'] != 'Refus')] if 'statut' in df_sm_q.columns else df_sm_q[df_sm_q['Q1'] == 'Oui']
        nb_ach = len(acheteurs)
        ti = nb_ach / total_q if total_q > 0 else 0.0
        qi = acheteurs['vol_litres'].mean() if nb_ach > 0 else 0.0
        vol_annuel = freq_hebdo * ti * qi * 52 if (ti is not None and qi is not None) else None
        return {
            'frequentation': freq_hebdo,
            'ti': ti,
            'qi': qi,
            'volume_annuel': vol_annuel
        }
    # ----- Version cachable de la fonction -----
    @st.cache_data(show_spinner=False)
    def compute_store_metrics_cached(mag, df_c_f, df_supermarche_full, df_sm, df_profils_pivot):
        return compute_store_metrics(mag, df_c_f, df_supermarche_full, df_sm, df_profils_pivot)
    # ----- Calcul des métriques pour tous les magasins -----
    store_metrics = {}
    # Utiliser make_hashable (remplace serialize_obj_cols)
    df_c_f_ser = make_hashable(df_c_f)
    df_supermarche_full_ser = make_hashable(df_supermarche_full)
    df_sm_ser = make_hashable(df_sm)
    df_profils_pivot_ser = make_hashable(df_profils_pivot)
    for mag in mags_selected:
        if mag in coord_map:
            store_metrics[mag] = compute_store_metrics_cached(
                mag, df_c_f_ser, df_supermarche_full_ser, df_sm_ser, df_profils_pivot_ser
            )
    # ----- Sélecteur d'indicateur -----
    indicateurs = {
        'Fréquentation hebdomadaire (clients)': 'frequentation',
        'Taux d\'achat (%)': 'ti',
        'Volume annuel estimé (L)': 'volume_annuel'
    }
    choix_indicateur = st.selectbox("Indicateur à afficher sur la carte", list(indicateurs.keys()))
    champ = indicateurs[choix_indicateur]
    if store_metrics:
        # Créer une nouvelle carte centrée sur la moyenne des magasins
        lats = [coord_map[m][0] for m in store_metrics.keys() if m in coord_map]
        lons = [coord_map[m][1] for m in store_metrics.keys() if m in coord_map]
        if not lats:
            st.warning("Aucune coordonnée disponible pour les magasins sélectionnés.")
        else:
            center_lat = np.mean(lats)
            center_lon = np.mean(lons)
            m2 = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles='OpenStreetMap', control_scale=True)
            # Préparer les données pour la colormap
            valeurs = []
            mags_valides = []
            for mag, metric in store_metrics.items():
                val = metric[champ]
                if val is not None and not np.isnan(val) and mag in coord_map:
                    valeurs.append(val)
                    mags_valides.append(mag)
            if valeurs:
                vmin, vmax = min(valeurs), max(valeurs)
                if vmax == vmin:
                    vmax += 1
                colormap = branca.colormap.linear.YlOrRd_09.scale(vmin, vmax)
                for mag in mags_valides:
                    val = store_metrics[mag][champ]
                    color = colormap(val)
                    popup_text = f"<b>{mag}</b><br>{choix_indicateur} : {fmt_nombre(val, 2)}"
                    folium.CircleMarker(
                        location=coord_map[mag],
                        radius=8,
                        color=color,
                        fill=True,
                        fill_opacity=0.8,
                        popup=folium.Popup(popup_text, max_width=250)
                    ).add_to(m2)
                colormap.add_to(m2)
                st_folium(m2, width=900, height=600)
                # Analyse de corrélation spatiale
                st.subheader("📈 Corrélation avec la position géographique")
                df_corr = pd.DataFrame({
                    'Magasin': mags_valides,
                    'latitude': [coord_map[m][0] for m in mags_valides],
                    'longitude': [coord_map[m][1] for m in mags_valides],
                    'indicateur': [store_metrics[m][champ] for m in mags_valides]
                })
                col1, col2 = st.columns(2)
                with col1:
                    fig_lat = px.scatter(df_corr, x='latitude', y='indicateur',
                                         trendline='ols',
                                         title=f"{choix_indicateur} vs Latitude")
                    fig_lat.update_layout(template="gilroy_export")
                    fig_lat = force_black_axes(fig_lat)
                    corr_lat = np.corrcoef(df_corr['latitude'], df_corr['indicateur'])[0,1]
                with col2:
                    fig_lon = px.scatter(df_corr, x='longitude', y='indicateur',
                                         trendline='ols',
                                         title=f"{choix_indicateur} vs Longitude")
                    fig_lon.update_layout(template="gilroy_export")
                    fig_lon = force_black_axes(fig_lon)
                    corr_lon = np.corrcoef(df_corr['longitude'], df_corr['indicateur'])[0,1]
            else:
                st.info("Aucune donnée valide pour l'indicateur choisi.")
    else:
        st.warning("Aucun magasin avec coordonnées et données exploitables.")
# ------------------------------------------------------------
# ONGLET 10 : AFFLUENCE (corrigé avec cache)
# ------------------------------------------------------------
