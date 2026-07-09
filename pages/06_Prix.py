# pages/06_Prix.py

"""Page Analyse des prix."""
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

df_p_f = st.session_state.get('df_p_f', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())

st.header("Analyse des prix")

st.header("🏷️ Analyse des prix et concurrence")
# Récupération des paramètres globaux de devise
devise = st.session_state.get("devise_globale", "FC")
taux = st.session_state.get("taux_change", 2800)

df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])
selected_norm = {normalize_name(m): m for m in selected_mags}
date_range = st.session_state.get('date_range', (None, None))
tab_marques = pd.DataFrame()
# Filtrage des prix externes selon les magasins sélectionnés
prix_ext = df_prices_ext.copy()
if not prix_ext.empty and selected_mags:
    selected_norm = {normalize_name(m): m for m in selected_mags}
    prix_ext['supermarche_norm'] = prix_ext['supermarche'].apply(normalize_name)
    magasin_mapping_prix = {}
    for sm_norm, sm_orig in selected_norm.items():
        magasin_mapping_prix[sm_norm] = sm_orig
    all_norm = prix_ext['supermarche_norm'].unique()
    for norm in all_norm:
        if norm not in magasin_mapping_prix:
            best_score = 0
            best_match = None
            for sel_norm, sel_orig in selected_norm.items():
                score = SequenceMatcher(None, norm, sel_norm).ratio()
                if score > best_score and score >= 0.8:
                    best_score = score
                    best_match = sel_orig
            if best_match:
                magasin_mapping_prix[norm] = best_match
    prix_ext = prix_ext[prix_ext['supermarche_norm'].isin(magasin_mapping_prix.keys())]
# Nettoyage des marques
if not prix_ext.empty:
    prix_ext['marque_officielle'] = apply_brand_mapping_strict(prix_ext['marque'], prix_ext)
    prix_ext = prix_ext.dropna(subset=['marque_officielle'])
    prix_ext['volume_L'] = prix_ext['conditionnement'].apply(extraire_litres)
    prix_ext = prix_ext.dropna(subset=['volume_L'])
    # Conversion robuste du prix en numérique
    prix_ext = prix_ext.copy()
    prix_ext['prix_num'] = pd.to_numeric(prix_ext['prix'].astype(str).str.replace(',', '.'), errors='coerce')
    prix_ext['prix_unitaire_FC'] = prix_ext['prix_num'].values.astype(float) / prix_ext['volume_L'].values.astype(float)
    prix_ext['prix_unitaire_conv'] = prix_ext['prix_unitaire_FC'].apply(
        lambda x: convertir_prix(x, devise, taux)
    )
# Récupération du top 8 des marques par nombre d'acheteurs (pour le boxplot)
# On utilise df_supermarche_full (tous les acheteurs, hors refus)
if not df_supermarche_full.empty:
    acheteurs_sm_full = df_supermarche_full[df_supermarche_full['Q1'] == 'Oui']
    if 'statut' in df_supermarche_full.columns:
        acheteurs_sm_full = acheteurs_sm_full[acheteurs_sm_full['statut'] != 'Refus']
    top8_brands_prix = acheteurs_sm_full['marque_clean'].value_counts().head(8).index.tolist()
else:
    top8_brands_prix = []
# -------------------------------------------------------------
# 1. Tableau des marques : présence et part de marché
# -------------------------------------------------------------
st.subheader("📊 Marques : présence et part de marché (enquête supermarché)")
official_brands = get_official_brands(prix_ext) if not prix_ext.empty else set()
# Marques issues des prix externes
marques_prix = pd.DataFrame()
if not prix_ext.empty:
    marques_prix = prix_ext.groupby('marque_officielle')['supermarche_norm'].apply(set).reset_index()
    marques_prix.columns = ['Marque', 'magasins_prix']
    marques_prix['nb_points_vente_prix'] = marques_prix['magasins_prix'].apply(len)
else:
    marques_prix = pd.DataFrame(columns=['Marque', 'magasins_prix', 'nb_points_vente_prix'])

# Marques issues des acheteurs (questionnaires)
marques_achat = pd.DataFrame(columns=['Marque', 'magasins_achat', 'nb_points_vente_achat', "Nombre d'acheteurs"])
if 'df_supermarche_full' in dir() and not df_supermarche_full.empty:
    acheteurs_sm = df_supermarche_full[df_supermarche_full['Q1'] == 'Oui'].copy() if 'Q1' in df_supermarche_full.columns else df_supermarche_full.copy()
    if not acheteurs_sm.empty and 'marque_clean' in acheteurs_sm.columns:
        acheteurs_sm = acheteurs_sm.dropna(subset=['marque_clean'])
        if not acheteurs_sm.empty:
            pts_vente_achat = acheteurs_sm.groupby('marque_clean')['magasin_officiel'].apply(set).reset_index()
            pts_vente_achat.columns = ['Marque', 'magasins_achat']
            pts_vente_achat['nb_points_vente_achat'] = pts_vente_achat['magasins_achat'].apply(len)
            nb_ach = acheteurs_sm['marque_clean'].value_counts().reset_index()
            nb_ach.columns = ['Marque', "Nombre d'acheteurs"]
            marques_achat = pts_vente_achat.merge(nb_ach, on='Marque', how='left').fillna(0)
            marques_achat["Nombre d'acheteurs"] = marques_achat["Nombre d'acheteurs"].astype(int)

toutes_marques = pd.DataFrame({'Marque': list(official_brands)})
toutes_marques['Marque'] = toutes_marques['Marque'].astype(str)
# Uniformiser les types pour le merge
marques_prix = marques_prix.copy()
marques_prix['Marque'] = marques_prix['Marque'].apply(lambda x: str(x) if pd.notna(x) else '')
marques_achat = marques_achat.copy()
marques_achat['Marque'] = marques_achat['Marque'].apply(lambda x: str(x) if pd.notna(x) else '')
tab_marques = toutes_marques.merge(
    marques_prix[['Marque', 'magasins_prix', 'nb_points_vente_prix']],
    on='Marque', how='left'
).merge(
    marques_achat[['Marque', 'magasins_achat', 'nb_points_vente_achat', "Nombre d'acheteurs"]],
    on='Marque', how='left'
)
tab_marques = tab_marques.copy()
tab_marques['magasins_prix'] = tab_marques['magasins_prix'].apply(lambda x: x if isinstance(x, set) else set())
tab_marques['magasins_achat'] = tab_marques['magasins_achat'].apply(lambda x: x if isinstance(x, set) else set())
nb_points = []
for _, row in tab_marques.iterrows():
    try:
        nb_points.append(len(row['magasins_prix'] | row['magasins_achat']))
    except:
        nb_points.append(0)
tab_marques['Points de vente'] = nb_points
tab_marques["Nombre d'acheteurs"] = tab_marques["Nombre d'acheteurs"].fillna(0).astype(int)
total_acheteurs = tab_marques["Nombre d'acheteurs"].sum()
# Toujours créer la colonne numérique de part de marché
if total_acheteurs > 0:
    tab_marques['_pdm_numeric'] = tab_marques["Nombre d'acheteurs"].apply(
        lambda x: round(x / total_acheteurs * 100, 1) if x > 0 else 0.0
    )
else:
    tab_marques['_pdm_numeric'] = 0.0
# Colonne formatée pour l'affichage
tab_marques['Part de marché (%)'] = tab_marques['_pdm_numeric'].apply(
    lambda x: f"{x:.1f} %" if x > 0 else "N/A"
)
# Préparer l'affichage
tab_marques_display = tab_marques[['Marque', 'Points de vente', "Nombre d'acheteurs", 'Part de marché (%)']].copy()
# Tri par part de marché décroissante (numérique), puis par points de vente
tab_marques_display['_sort_pdm'] = tab_marques['_pdm_numeric']
tab_marques_display = tab_marques_display.sort_values(
    ['_sort_pdm', 'Points de vente'], ascending=[False, False]
)
tab_marques_display = tab_marques_display.drop(columns=['_sort_pdm'])
st.dataframe(tab_marques_display, width='stretch', hide_index=True)
# -------------------------------------------------------------
# 1bis. Graphique des parts de marché des 8 premières marques
# -------------------------------------------------------------
st.subheader("📊 Parts de marché des 8 premières marques")
# Vérification que la colonne nécessaire existe et contient des valeurs
if not tab_marques.empty and '_pdm_numeric' in tab_marques.columns:
    # On ne garde que les marques avec une part de marché > 0 (pour éviter des graphiques vides)
    tab_marques_valid = tab_marques[tab_marques['_pdm_numeric'] > 0].copy()
    if not tab_marques_valid.empty:
        top8 = tab_marques_valid.nlargest(8, '_pdm_numeric').copy()
        # Calcul de la part des "Autres" (marques hors top 8)
        pdm_top8_sum = top8['_pdm_numeric'].sum()
        pdm_autres = 100.0 - pdm_top8_sum
        nb_points_vente_autres = tab_marques_valid.loc[
            ~tab_marques_valid['Marque'].isin(top8['Marque']), 'Points de vente'
        ].sum()
        # Préparation des données pour le camembert
        top8_display = top8[['Marque', '_pdm_numeric', 'Points de vente']].copy()
        top8_display.rename(columns={'_pdm_numeric': 'Part de marché (%)'}, inplace=True)
        autres_row = pd.DataFrame([{
            'Marque': 'Autres',
            'Part de marché (%)': pdm_autres,
            'Points de vente': nb_points_vente_autres
        }])
        df_pie = pd.concat([top8_display, autres_row], ignore_index=True)
        # Trier pour placer "Autres" en dernier
        df_pie['ordre'] = df_pie['Marque'].apply(lambda x: 0 if x != 'Autres' else 1)
        df_pie = df_pie.sort_values('ordre').drop(columns=['ordre'])
        col_pie, col_bar = st.columns(2)
        with col_pie:
            fig_pie = px.pie(
                df_pie, values='Part de marché (%)', names='Marque',
                title='Part de marché (%) – top 8 + Autres',
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_pie.update_traces(textinfo='percent+label', sort=False)
            fig_pie.update_layout(template="gilroy_export")
            fig_pie = force_black_axes(fig_pie)
            st.plotly_chart(fig_pie, width='stretch')
        with col_bar:
            # Barres horizontales pour le nombre de points de vente (top 8 uniquement)
            df_bar = top8.sort_values('Points de vente', ascending=True)
            fig_bar = px.bar(
                df_bar, x='Points de vente', y='Marque',
                orientation='h',
                title='Nombre de points de vente (top 8)',
                text='Points de vente',
                color='Marque',
                labels={'Points de vente': 'Points de vente', 'Marque': 'Marque'},
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_bar.update_traces(textposition='outside')
            fig_bar.update_layout(xaxis_title='Points de vente', yaxis_title=None, showlegend=False,
                                  template="gilroy_export")
            fig_bar = force_black_axes(fig_bar)
            st.plotly_chart(fig_bar, width='stretch')
    else:
        st.info("Aucune marque avec une part de marché > 0.")
else:
    st.info("Aucune donnée sur les parts de marché.")
# -------------------------------------------------------------
# NOUVEAU : Taux d'achat par niveau socio-économique
# -------------------------------------------------------------
st.subheader("📈 Taux d'achat par niveau socio-économique")
if not df_supermarche_full.empty and not df_sm.empty:
    # Fusionner les questionnaires avec les infos de supermarché
    df_q_niveau = df_supermarche_full.copy()
    df_q_niveau['magasin_norm'] = df_q_niveau['magasin_officiel'].apply(normalize_name)
    df_sm_niveau = df_sm[['Nom', 'Niveau_socio']].copy()
    df_sm_niveau['nom_norm'] = df_sm_niveau['Nom'].apply(normalize_name)
    df_q_niveau = df_q_niveau.merge(df_sm_niveau[['nom_norm', 'Niveau_socio']],
                                    left_on='magasin_norm', right_on='nom_norm', how='left')
    # Exclure les refus
    if 'statut' in df_q_niveau.columns:
        df_q_niveau = df_q_niveau[df_q_niveau['statut'] != 'Refus']
    # Compter par niveau
    niveaux = df_q_niveau['Niveau_socio'].dropna().unique()
    data_taux = []
    for niveau in niveaux:
        sub = df_q_niveau[df_q_niveau['Niveau_socio'] == niveau]
        total = len(sub)
        acheteurs = sub[sub['Q1'] == 'Oui']
        nb_ach = len(acheteurs)
        taux = (nb_ach / total * 100) if total > 0 else 0
        data_taux.append({
            'Niveau socio-économique': niveau,
            'Taux d\'achat (%)': round(taux, 1),
            'Nombre de questionnaires': total,
            'Nombre d\'acheteurs': nb_ach
        })
    if data_taux:
        df_taux = pd.DataFrame(data_taux)
        fig_taux = px.bar(df_taux, x='Niveau socio-économique', y="Taux d'achat (%)",
                          text="Taux d'achat (%)",
                          labels={'Taux d\'achat (%)': 'Taux d\'achat (%)'},
                          title="Taux d'achat par niveau socio-économique")
        fig_taux.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig_taux.update_layout(template="gilroy_export")
        fig_taux = force_black_axes(fig_taux)
        st.plotly_chart(fig_taux, width='stretch')
        st.caption(f"Basé sur {df_taux['Nombre de questionnaires'].sum()} questionnaires valides hors refus.")
    else:
        st.info("Données insuffisantes pour le calcul du taux par niveau.")
else:
    st.info("Données de supermarché ou questionnaires manquantes.")
# -------------------------------------------------------------
# 2. Marques par chaîne de supermarchés
# -------------------------------------------------------------
st.subheader("🏢 Marques présentes par chaîne de supermarchés")
if not prix_ext.empty and not df_sm.empty:
    df_sm_local = df_sm.copy()
    df_sm_local['nom_norm'] = df_sm_local['Nom'].apply(normalize_name)
    prix_chaines = prix_ext.merge(
        df_sm_local[['nom_norm', 'Chaine']],
        left_on='supermarche_norm',
        right_on='nom_norm',
        how='left'
    )
    prix_chaines['Chaine'] = prix_chaines['Chaine'].fillna('Indépendant').str.strip()
    chaine_marques = prix_chaines.groupby('Chaine')['marque_officielle'].apply(
        lambda x: sorted(x.unique())
    ).reset_index()
    chaine_marques['Marques'] = chaine_marques['marque_officielle'].apply(lambda liste: ', '.join(liste))
    st.dataframe(chaine_marques[['Chaine', 'Marques']], width='stretch')
else:
    st.info("Données insuffisantes pour afficher les chaînes.")
# -------------------------------------------------------------
# 3. Comparaison prix enquête terrain vs prix externes
# -------------------------------------------------------------
st.subheader("📈 Comparaison des prix relevés sur le terrain vs prix affichés")
if not df_p_f.empty and not prix_ext.empty:
    df_p_f['volume_L'] = df_p_f['data_dict'].apply(lambda d: extraire_litres(d.get('Conditionnement', '')) if isinstance(d, dict) else None)
    df_p_f = df_p_f.dropna(subset=['volume_L'])
    df_p_f['prix_unitaire_FC'] = pd.to_numeric(df_p_f['data_dict'].apply(lambda d: d.get('Prix', 0)), errors='coerce') / df_p_f['volume_L']
    df_p_f['marque_officielle'] = apply_brand_mapping_strict(df_p_f['data_dict'].apply(lambda d: d.get('Marque', '') if isinstance(d, dict) else ''))
    df_p_f = df_p_f.dropna(subset=['marque_officielle'])
    comp_list = []
    for sm in selected_mags if selected_mags else df_p_f['supermarche'].unique():
        terrain = df_p_f[df_p_f['supermarche'] == sm]
        externe = prix_ext[prix_ext['supermarche'] == sm]
        if terrain.empty or externe.empty:
            continue
        terrain_agg = terrain.groupby(['marque_officielle', 'volume_L'])['prix_unitaire_FC'].mean().reset_index()
        externe_agg = externe.groupby(['marque_officielle', 'volume_L'])['prix_unitaire_FC'].mean().reset_index()
        merged = terrain_agg.merge(externe_agg, on=['marque_officielle', 'volume_L'], suffixes=('_terrain', '_externe'))
        merged['supermarche'] = sm
        merged['ecart_FC'] = merged['prix_unitaire_FC_terrain'] - merged['prix_unitaire_FC_externe']
        merged['ecart_%'] = (merged['ecart_FC'] / merged['prix_unitaire_FC_externe']) * 100
        comp_list.append(merged)
    if comp_list:
        df_comp = pd.concat(comp_list)
        st.dataframe(df_comp, width='stretch')
        fig_comp = px.scatter(df_comp, x='prix_unitaire_FC_externe', y='prix_unitaire_FC_terrain',
                              hover_data=['supermarche', 'marque_officielle', 'volume_L'],
                              labels={'prix_unitaire_FC_externe': 'Prix affiché (FC/L)',
                                      'prix_unitaire_FC_terrain': 'Prix terrain (FC/L)'},
                              title="Prix terrain vs prix affiché (FC/L)")
        fig_comp.add_shape(type='line', x0=0, y0=0, x1=df_comp['prix_unitaire_FC_externe'].max(),
                           y1=df_comp['prix_unitaire_FC_externe'].max(), line=dict(dash='dash'))
        fig_comp.update_layout(template="gilroy_export")
        fig_comp = force_black_axes(fig_comp)
        st.plotly_chart(fig_comp, width='stretch')
    else:
        st.info("Aucune correspondance trouvée pour comparer les prix.")
else:
    st.info("Données de prix terrain ou prix externes insuffisantes pour la comparaison.")
# -------------------------------------------------------------
# 4. Distribution des prix par marque (boxplot) – TOP 8 marques
# -------------------------------------------------------------
st.subheader(f"📦 Prix au litre par marque ({devise}) – top 8")
if not prix_ext.empty and top8_brands_prix:
    contenants_dispo = ['Tous'] + sorted(prix_ext['conditionnement'].unique().tolist())
    contenant_choisi = st.selectbox(
        "Filtrer par contenant",
        contenants_dispo,
        key="box_marque_contenant"
    )
    if contenant_choisi != 'Tous':
        df_prix_marque = prix_ext[prix_ext['conditionnement'] == contenant_choisi]
        titre_graph = f"Distribution des prix au litre par marque – {contenant_choisi} ({devise})"
    else:
        df_prix_marque = prix_ext
        titre_graph = f"Distribution des prix au litre par marque – Tous contenants ({devise})"
    if not df_prix_marque.empty:
        df_prix_marque_top8 = df_prix_marque[df_prix_marque['marque_officielle'].isin(top8_brands_prix)]
        if df_prix_marque_top8.empty:
            # Fallback : toutes les marques
            df_prix_marque_top8 = df_prix_marque
        fig_marque = px.box(
            df_prix_marque_top8,
            x='marque_officielle',
            y='prix_unitaire_conv',
            labels={'marque_officielle': 'Marque', 'prix_unitaire_conv': f'Prix au litre ({devise})'},
            title=titre_graph + " (top 8 marques les plus achetées)"
        )
        fig_marque.update_layout(xaxis_tickangle=-45, template="gilroy_export")
        fig_marque = force_black_axes(fig_marque)
        if devise == "FC":
            fig_marque.update_yaxes(tickformat=",.0f")
        else:
            fig_marque.update_yaxes(tickformat=",.2f")
        st.plotly_chart(fig_marque, width='stretch')
        st.caption(f"Basé sur {len(df_prix_marque_top8)} relevés de prix pour les marques du top 8.")
    else:
        st.info("Aucune donnée pour ce contenant.")
else:
    st.info("Aucune donnée de prix externe ou top 8 non disponible.")
# -------------------------------------------------------------
# 5. Prix au litre selon le conditionnement (boxplots)
# -------------------------------------------------------------
st.subheader(f"💵 Prix au litre selon le conditionnement ({devise})")
if not prix_ext.empty:
    data_box = prix_ext.copy()
    data_box['Cond. (L)'] = data_box['volume_L'].apply(lambda v: f"{v:.1f} L" if v == int(v) else f"{v:.2f} L")
    order = sorted(data_box['volume_L'].unique())
    order_labels = [f"{v:.1f} L" if v == int(v) else f"{v:.2f} L" for v in order]
    data_box['Cond. (L)'] = pd.Categorical(data_box['Cond. (L)'], categories=order_labels, ordered=True)
    fig_box = px.box(
        data_box,
        x='Cond. (L)',
        y='prix_unitaire_conv',
        points='outliers',
        title=f"Distribution des prix au litre par conditionnement ({devise})",
        labels={'prix_unitaire_conv': f'Prix au litre ({devise})', 'Cond. (L)': 'Conditionnement'}
    )
    fig_box.update_layout(template="gilroy_export")
    fig_box = force_black_axes(fig_box)
    fig_box.update_layout(yaxis_tickformat=",.2f" if devise == "USD" else ",.0f")
    st.plotly_chart(fig_box, width='stretch')
    with st.expander("📋 Statistiques par conditionnement"):
        stats = data_box.groupby('Cond. (L)')['prix_unitaire_conv'].describe(percentiles=[.25, .5, .75])
        st.dataframe(stats, width='stretch')
else:
    st.info("Pas assez de données pour les boxplots.")
# -------------------------------------------------------------
# 6. Tableau des prix par supermarché
# -------------------------------------------------------------
st.subheader("🏪 Prix au litre par supermarché")
if not prix_ext.empty:
    sm_prices = prix_ext.groupby('supermarche')['prix_unitaire_conv'].agg(['mean', 'median', 'std', 'count']).reset_index()
    sm_prices.columns = ['Supermarché', 'Moyenne', 'Médiane', 'Écart-type', 'Nb relevés']
    devise_str = "USD" if devise == "USD" else "FC"
    for col in ['Moyenne', 'Médiane', 'Écart-type']:
        sm_prices[col] = sm_prices[col].apply(lambda x: f"{x:,.2f} {devise_str}" if devise == "USD" else f"{x:,.0f} {devise_str}")
    st.dataframe(sm_prices, width='stretch')
else:
    st.info("Aucune donnée de prix externe.")
# -------------------------------------------------------------
# 7. Export des données
# -------------------------------------------------------------
if not prix_ext.empty:
    csv = prix_ext.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Télécharger les prix externes (CSV)", csv, "prix_externes.csv", "text/csv")
# ------------------------------------------------------------
# ONGLET 7 : PROFIL SUPERMARCHÉS 
# ------------------------------------------------------------
