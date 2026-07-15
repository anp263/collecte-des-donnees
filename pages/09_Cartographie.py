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
import os
from io import BytesIO

# -------------------------------------------------------------------
# Récupération des données depuis la session
# -------------------------------------------------------------------
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
date_range = st.session_state.get('sidebar_date_range', (None, None))
selected_mags = st.session_state.get('selected_mags', [])

st.header("🗺️ Cartographie des supermarchés et des mesures GPS")

# -------------------------------------------------------------------
# Fonction d'export PNG avec contrôle du zoom
# -------------------------------------------------------------------
def folium_to_png(folium_map, width=900, height=600, center=None, zoom=None):
    """Capture PNG de la carte en respectant le centre et le zoom (si fournis)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "playwright n'est pas installé. Exécutez : pip install playwright && playwright install chromium"
        )
    html = folium_map.get_root().render()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html)
        # Récupérer l'ID de la carte dans le code généré
        map_id = page.evaluate("""Object.keys(window).find(key => key.startsWith('map_'))""")
        if map_id:
            if center is not None and zoom is not None:
                page.evaluate(
                    f"window['{map_id}'].setView([{center[0]}, {center[1]}], {zoom})"
                )
        # Masquer le contrôle de zoom
        page.evaluate("document.querySelector('.leaflet-control-zoom')?.style.setProperty('display','none','important')")
        page.wait_for_timeout(3000)
        img_bytes = page.screenshot(full_page=False, type='png')
        browser.close()
    return img_bytes

# -------------------------------------------------------------------
# Parsing GPS et agrégation (inchangé)
# -------------------------------------------------------------------
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

def safe_get_gps(row):
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
if not df_supermarche.empty:
    for _, row in df_supermarche.iterrows():
        lat, lon = parse_gps(safe_get_gps(row))
        if lat and lon:
            measures.append({
                'magasin': row.get('magasin_officiel', row.get('lieu', '')),
                'lat': lat, 'lon': lon,
                'type': 'Questionnaire SM',
                'date': row['date_dt'],
                'uuid': row.get('uuid', ''),
                'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
            })
if not df_menage.empty:
    for _, row in df_menage.iterrows():
        lat, lon = parse_gps(safe_get_gps(row))
        if lat and lon:
            measures.append({
                'magasin': 'Ménage (' + str(row.get('lieu', '')) + ')',
                'lat': lat, 'lon': lon,
                'type': 'Questionnaire ménage',
                'date': row['date_dt'],
                'uuid': row.get('uuid', ''),
                'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
            })
if not df_c_f.empty:
    for _, row in df_c_f.iterrows():
        lat, lon = parse_gps(safe_get_gps(row))
        if lat and lon:
            measures.append({
                'magasin': normalize_name(row['lieu']),
                'lat': lat, 'lon': lon,
                'type': 'Comptage',
                'date': row['date_dt'],
                'uuid': row.get('uuid', row.get('id', '')),
                'enqueteur': row.get('enqueteur', row.get('Enquêteur', ''))
            })

if not measures:
    st.warning("Aucune coordonnée GPS trouvée.")
    st.stop()

df_meas = pd.DataFrame(measures)
if 'date' in df_meas.columns and date_range[0] and date_range[1]:
    df_meas = df_meas[(df_meas['date'].dt.date >= date_range[0]) & (df_meas['date'].dt.date <= date_range[1])]
if df_meas.empty:
    st.warning("Aucune mesure GPS dans la période sélectionnée.")
    st.stop()

mag_meas = df_meas[~df_meas['magasin'].str.startswith('Ménage')].copy()
mag_meas['magasin_norm'] = mag_meas['magasin'].apply(normalize_name)

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

# -------------------------------------------------------------------
# Magasins sélectionnés
# -------------------------------------------------------------------
mags_selected = st.session_state.get('selected_magasins', [])
if not mags_selected:
    st.info("Aucun magasin sélectionné (onglet Accueil).")
    st.stop()
selected_norm = {normalize_name(m): m for m in mags_selected}
median_pos_sel = median_pos[median_pos['magasin_norm'].isin(selected_norm.keys())].copy()
if median_pos_sel.empty:
    st.info("Aucun magasin sélectionné ne possède de mesure GPS.")
    st.stop()

st.subheader("📋 Coordonnées médianes des magasins sélectionnés")
display_df = median_pos_sel[['Nom officiel', 'lat_final', 'lon_final', 'nb_mesures']].copy()
display_df.columns = ['Magasin', 'Latitude médiane', 'Longitude médiane', 'Nb mesures']
st.dataframe(display_df, width='stretch')

# Détection des mesures anormales
seuil_anomalie_m = 150
anomalies = []
for _, store_row in median_pos_sel.iterrows():
    store_norm = store_row['magasin_norm']
    store_lat, store_lon = store_row['lat_med'], store_row['lon_med']
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
    st.warning(f"{len(anomalies)} mesure(s) anormale(s) détectée(s).")
    with st.expander("🔍 Voir les mesures anormales"):
        st.dataframe(pd.DataFrame(anomalies), width='stretch')
else:
    st.success("Aucune mesure anormale détectée.")

# -------------------------------------------------------------------
# Options de la carte (sidebar)
# -------------------------------------------------------------------
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

# Couleurs des segments
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

# -------------------------------------------------------------------
# CARTE PRINCIPALE (m) – légende en haut à droite
# -------------------------------------------------------------------
center_lat = median_pos_sel['lat_final'].mean()
center_lon = median_pos_sel['lon_final'].mean()
m = folium.Map(location=[center_lat, center_lon], zoom_start=13,
               tiles='OpenStreetMap', control_scale=True)

# Flèche nord (haut gauche)
north_arrow_html = '''
<div style="position: absolute; top: 10px; left: 10px; width: 40px; height: 40px; z-index: 1000;">
    <svg viewBox="0 0 40 40">
        <polygon points="20,0 0,40 40,40" fill="#cc0000" />
        <text x="20" y="34" text-anchor="middle" font-size="11" fill="white" font-weight="bold">N</text>
    </svg>
</div>
'''
m.get_root().html.add_child(folium.Element(north_arrow_html))

# Légende en haut à droite
segments_presents = sorted(set(median_pos_sel['Nom officiel'].apply(
    lambda x: df_sm_copy[df_sm_copy['Nom'] == x]['Segment'].iloc[0] if not df_sm_copy[df_sm_copy['Nom'] == x].empty else 'Inconnu'
)))
legend_items = ['<b>Supermarchés (segment) :</b><br>']
for seg in segments_presents:
    color = seg_color_map.get(seg, 'gray')
    legend_items.append(f'<span style="display:inline-block; width:12px; height:12px; border:3px solid {color}; border-radius:50%; margin-right:4px;"></span> {seg}<br>')
if show_mesures:
    legend_items.append('<br><b>Mesures :</b><br>')
    legend_items.append('<span style="display:inline-block; width:12px; height:12px; background:green; border-radius:50%; margin-right:4px;"></span> Questionnaire SM<br>')
    legend_items.append('<span style="display:inline-block; width:12px; height:12px; background:red; border-radius:50%; margin-right:4px;"></span> Comptage<br>')
    if show_menages:
        legend_items.append('<span style="display:inline-block; width:12px; height:12px; background:orange; border-radius:50%; margin-right:4px;"></span> Ménage<br>')
legend_html = f'''
<div style="position: absolute; top: 10px; right: 10px; z-index: 1000; background: white; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; line-height: 1.4;">
{"".join(legend_items)}
</div>
'''
m.get_root().html.add_child(folium.Element(legend_html))

# Marqueurs des supermarchés
for _, row in median_pos_sel.iterrows():
    nom_off = row['Nom officiel']
    match = df_sm_copy[df_sm_copy['Nom'] == nom_off]
    segment = match['Segment'].iloc[0] if not match.empty else 'Inconnu'
    couleur = seg_color_map.get(segment, 'gray')
    popup_text = f"""
    <b>{nom_off}</b><br>
    Segment : {segment}<br>
    Nb mesures : {row['nb_mesures']}<br>
    Position : {row['lat_final']:.6f}, {row['lon_final']:.6f}<br>
    {'<i>(corrigée manuellement)</i>' if row['manuel'] else '(médiane)'}
    """
    folium.CircleMarker(
        location=[row['lat_final'], row['lon_final']],
        radius=6,
        popup=folium.Popup(popup_text, max_width=250),
        tooltip=nom_off,
        color=couleur,
        fill=False,
        weight=3,
        opacity=0.9
    ).add_to(m)

# Mesures individuelles
if show_mesures and not df_meas_filtered.empty:
    from folium.plugins import MarkerCluster
    if use_cluster:
        cluster = MarkerCluster().add_to(m)
    for _, row in df_meas_filtered.iterrows():
        couleur = 'green' if row['type'] == 'Questionnaire SM' else ('orange' if 'ménage' in row['type'] else 'red')
        popup = f"{row['type']}<br>{row['magasin']}<br>{row['date'].strftime('%Y-%m-%d %H:%M') if pd.notna(row['date']) else ''}"
        marker = folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=3,
            popup=popup,
            color=couleur,
            fill=True,
            fill_opacity=0.7,
            weight=1
        )
        marker.add_to(cluster if use_cluster else m)

# Affichage Streamlit avec clé pour récupérer centre/zoom
map_data = st_folium(m, width=900, height=600, key="main_map")
if map_data and "center" in map_data and "zoom" in map_data:
    st.session_state['main_map_center'] = (map_data['center']['lat'], map_data['center']['lng'])
    st.session_state['main_map_zoom'] = map_data['zoom']
else:
    st.session_state['main_map_center'] = (center_lat, center_lon)
    st.session_state['main_map_zoom'] = 13

# Exports
map_html_export = m.get_root().render()
st.download_button(
    label="📥 Télécharger la carte (HTML)",
    data=map_html_export,
    file_name="carte_supermarches.html",
    mime="text/html",
)

if st.button("📥 Télécharger la carte en PNG (avec zoom actuel)"):
    try:
        center = st.session_state.get('main_map_center', (center_lat, center_lon))
        zoom = st.session_state.get('main_map_zoom', 13)
        png_bytes = folium_to_png(m, 900, 600, center=center, zoom=zoom)
        st.download_button(
            label="Télécharger PNG",
            data=png_bytes,
            file_name="carte_supermarches.png",
            mime="image/png",
        )
    except ImportError:
        st.error("Playwright non installé. Exécutez : pip install playwright && playwright install chromium")
    except Exception as e:
        st.error(f"Erreur : {e}")

# =====================================================================
# ANALYSE SPATIALE DES INDICATEURS (seconde carte)
# =====================================================================
st.divider()
st.subheader("📍 Analyse spatiale des indicateurs par magasin")
if not mags_selected:
    st.info("Aucun magasin sélectionné.")
else:
    coord_map = {}
    for _, row in median_pos_sel.iterrows():
        coord_map[row['Nom officiel']] = (row['lat_final'], row['lon_final'])

    # Fonction de calcul des métriques
    def compute_store_metrics(mag, df_c_f, df_supermarche_full, df_sm, df_profils_pivot):
        comptages = df_c_f[df_c_f['lieu_officiel'] == mag].copy()
        if comptages.empty:
            return {'frequentation': None, 'ti': None, 'qi': None, 'volume_annuel': None}
        jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}
        k_sem_list, k_we_list = [], []
        for _, row in comptages.iterrows():
            date_obj = row['date_dt']
            jour_code = date_obj.strftime('%a')
            jour_google = jour_map.get(jour_code, jour_code)
            profil = [1.0]*24
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
        heures_sem = list(range(8, 18))
        heures_we = list(range(8, 18))
        clients_sem = [k_sem * 1.0 for _ in heures_sem]
        clients_we  = [k_we * 1.0 for _ in heures_we]
        freq_hebdo = 5 * sum(clients_sem) + 2 * sum(clients_we)
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

    @st.cache_data(show_spinner=False)
    def compute_store_metrics_cached(mag, df_c_f_ser, df_supermarche_full_ser, df_sm_ser, df_profils_pivot_ser):
        return compute_store_metrics(mag, df_c_f_ser, df_supermarche_full_ser, df_sm_ser, df_profils_pivot_ser)

    store_metrics = {}
    df_c_f_ser = make_hashable(df_c_f)
    df_supermarche_full_ser = make_hashable(df_supermarche_full)
    df_sm_ser = make_hashable(df_sm)
    df_profils_pivot_ser = make_hashable(df_profils_pivot)

    for mag in mags_selected:
        if mag in coord_map:
            store_metrics[mag] = compute_store_metrics_cached(
                mag, df_c_f_ser, df_supermarche_full_ser, df_sm_ser, df_profils_pivot_ser
            )

    indicateurs = {
        'Fréquentation hebdomadaire (clients)': 'frequentation',
        "Taux d'achat (%)": 'ti',
        'Volume annuel estimé (L)': 'volume_annuel'
    }
    choix_indicateur = st.selectbox("Indicateur à afficher sur la carte", list(indicateurs.keys()))
    champ = indicateurs[choix_indicateur]

    if store_metrics:
        lats = [coord_map[m][0] for m in store_metrics if m in coord_map]
        lons = [coord_map[m][1] for m in store_metrics if m in coord_map]
        if not lats:
            st.warning("Aucune coordonnée disponible.")
        else:
            center_lat, center_lon = np.mean(lats), np.mean(lons)
            m2 = folium.Map(location=[center_lat, center_lon], zoom_start=13,
                            tiles='OpenStreetMap', control_scale=True)
            # Flèche nord
            m2.get_root().html.add_child(folium.Element(north_arrow_html))

            # Récupération des valeurs valides
            valeurs = []
            mags_valides = []
            for mag, met in store_metrics.items():
                val = met[champ]
                if val is not None and not np.isnan(val) and mag in coord_map:
                    valeurs.append(val)
                    mags_valides.append(mag)

            if valeurs:
                vmin, vmax = np.nanmin(valeurs), np.nanmax(valeurs)
                if vmax == vmin:
                    vmax += 1

                # Colormap standard sans modification des labels
                colormap = branca.colormap.LinearColormap(
                    colors=branca.colormap.linear.YlOrRd_09.colors,
                    vmin=vmin,
                    vmax=vmax,
                    caption=choix_indicateur
                )

                # Ajouter les marqueurs avec la couleur
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

                # Ajouter la colormap à la carte
                m2.add_child(colormap)

                # Affichage de la carte avec clé pour récupérer le zoom
                map_data2 = st_folium(m2, width=900, height=600, key="analysis_map")
                if map_data2 and "center" in map_data2 and "zoom" in map_data2:
                    st.session_state['analysis_map_center'] = (map_data2['center']['lat'], map_data2['center']['lng'])
                    st.session_state['analysis_map_zoom'] = map_data2['zoom']
                else:
                    st.session_state['analysis_map_center'] = (center_lat, center_lon)
                    st.session_state['analysis_map_zoom'] = 13

                # Export HTML
                map2_html = m2.get_root().render()
                st.download_button(
                    label="📥 Télécharger la carte d'analyse spatiale (HTML)",
                    data=map2_html,
                    file_name="carte_analyse_spatiale.html",
                    mime="text/html",
                )

                if st.button("📥 Télécharger cette carte en PNG"):
                    try:
                        center = st.session_state.get('analysis_map_center', (center_lat, center_lon))
                        zoom = st.session_state.get('analysis_map_zoom', 13)
                        png_bytes = folium_to_png(m2, 900, 600, center=center, zoom=zoom)
                        st.download_button(
                            label="Télécharger PNG",
                            data=png_bytes,
                            file_name="carte_analyse_spatiale.png",
                            mime="image/png",
                        )
                    except ImportError:
                        st.error("Playwright non installé. Exécutez : pip install playwright && playwright install chromium")
                    except Exception as e:
                        st.error(f"Erreur : {e}")

                # Corrélation spatiale
                st.subheader("📈 Corrélation avec la position géographique")
                df_corr = pd.DataFrame({
                    'Magasin': mags_valides,
                    'latitude': [coord_map[m][0] for m in mags_valides],
                    'longitude': [coord_map[m][1] for m in mags_valides],
                    'indicateur': [store_metrics[m][champ] for m in mags_valides]
                })
                col1, col2 = st.columns(2)
                with col1:
                    fig_lat = px.scatter(df_corr, x='latitude', y='indicateur', trendline='ols',
                                         title=f"{choix_indicateur} vs Latitude")
                    fig_lat.update_layout(template="gilroy_export")
                    fig_lat = force_black_axes(fig_lat)
                    st.plotly_chart(fig_lat, use_container_width=True)
                with col2:
                    fig_lon = px.scatter(df_corr, x='longitude', y='indicateur', trendline='ols',
                                         title=f"{choix_indicateur} vs Longitude")
                    fig_lon.update_layout(template="gilroy_export")
                    fig_lon = force_black_axes(fig_lon)
                    st.plotly_chart(fig_lon, use_container_width=True)
            else:
                st.info("Aucune donnée valide pour l'indicateur choisi.")
    else:
        st.warning("Aucun magasin avec coordonnées et données exploitables.")