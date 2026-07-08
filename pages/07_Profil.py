# pages/07_Profil.py
"""Page Profil des supermarchés."""
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

df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())

st.header("Profil des supermarchés")

st.header("🏪 Profil des supermarchés recensés")
if df_sm.empty:
    st.warning("Aucune donnée de supermarchés.")
else:
    df_sm = df_sm.copy()
    total = len(df_sm)
    st.metric("Nombre total de supermarchés", total)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Répartition par taille")
        taille_counts = df_sm['Taille'].value_counts()
        taille_pct = taille_counts / taille_counts.sum() * 100
        taille_df = taille_pct.reset_index()
        taille_df.columns = ['Taille', 'Pourcentage']
        fig_taille = px.pie(taille_df, values='Pourcentage', names='Taille',
                            title="Répartition par taille")
        fig_taille.update_traces(textinfo='percent+label')
        fig_taille.update_layout(template="gilroy_export")
        fig_taille = force_black_axes(fig_taille)
        st.plotly_chart(fig_taille, width='stretch')
        st.caption(f"Basé sur {total} supermarchés. Les pourcentages sont calculés sur l'ensemble des supermarchés.")
    with col2:
        st.subheader("Répartition par niveau socio-économique")
        socio_counts = df_sm['Niveau_socio'].value_counts()
        socio_pct = socio_counts / socio_counts.sum() * 100
        socio_df = socio_pct.reset_index()
        socio_df.columns = ['Niveau socio-économique', 'Pourcentage']
        fig_socio = px.pie(socio_df, values='Pourcentage', names='Niveau socio-économique',
                           title="Répartition par niveau socio-économique")
        fig_socio.update_traces(textinfo='percent+label')
        fig_socio.update_layout(template="gilroy_export")
        fig_socio = force_black_axes(fig_socio)
        st.plotly_chart(fig_socio, width='stretch')
        st.caption(f"Basé sur {total} supermarchés. Les pourcentages sont calculés sur l'ensemble des supermarchés.")
    st.subheader("Croisement Taille × Niveau socio-économique")
    cross_taille_socio = pd.crosstab(df_sm['Taille'], df_sm['Niveau_socio'])
    st.dataframe(cross_taille_socio)
    price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
    df_sm['Presence_huile'] = (df_sm[price_cols] > 0).any(axis=1)
    df_sm['Presence_huile_label'] = df_sm['Presence_huile'].map({True: 'Oui', False: 'Non'})
    st.subheader("Présence d'huile")
    col_a, col_b = st.columns(2)
    with col_a:
        st.write("Par niveau socio-économique")
        cross_presence_socio = pd.crosstab(df_sm['Niveau_socio'], df_sm['Presence_huile_label'])
        st.dataframe(cross_presence_socio)
        # Histogramme avec pourcentages
        pres_socio = df_sm.groupby(['Niveau_socio', 'Presence_huile_label']).size().reset_index(name='count')
        pres_socio['pct'] = pres_socio.groupby('Niveau_socio')['count'].transform(lambda x: x / x.sum() * 100)
        fig_pres_socio = px.bar(pres_socio, x='Niveau_socio', y='pct', color='Presence_huile_label',
                                barmode='group',
                                labels={'Niveau_socio': 'Niveau socio-économique',
                                        'pct': 'Pourcentage (%)',
                                        'Presence_huile_label': 'Huile présente'},
                                title="Présence d'huile par niveau socio-économique")
        fig_pres_socio.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
        fig_pres_socio.update_layout(template="gilroy_export")
        fig_pres_socio = force_black_axes(fig_pres_socio)
        st.plotly_chart(fig_pres_socio, width='stretch')
        st.caption(f"Basé sur {total} supermarchés. Les pourcentages sont calculés par niveau.")
    with col_b:
        st.write("Par taille")
        cross_presence_taille = pd.crosstab(df_sm['Taille'], df_sm['Presence_huile_label'])
        st.dataframe(cross_presence_taille)
        pres_taille = df_sm.groupby(['Taille', 'Presence_huile_label']).size().reset_index(name='count')
        pres_taille['pct'] = pres_taille.groupby('Taille')['count'].transform(lambda x: x / x.sum() * 100)
        fig_pres_taille = px.bar(pres_taille, x='Taille', y='pct', color='Presence_huile_label',
                                 barmode='group',
                                 labels={'Taille': 'Taille du supermarché',
                                         'pct': 'Pourcentage (%)',
                                         'Presence_huile_label': 'Huile présente'},
                                 title="Présence d'huile par taille")
        fig_pres_taille.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
        fig_pres_taille.update_layout(template="gilroy_export")
        fig_pres_taille = force_black_axes(fig_pres_taille)
        st.plotly_chart(fig_pres_taille, width='stretch')
        st.caption(f"Basé sur {total} supermarchés. Les pourcentages sont calculés par taille.")
    st.subheader("Nombre de supermarchés par chaîne")
    if 'Chaine' in df_sm.columns:
        chaine_counts = df_sm['Chaine'].value_counts().reset_index()
        chaine_counts.columns = ['Chaîne', 'Nombre']
        chaine_counts = chaine_counts.sort_values('Nombre', ascending=True)
        # Calcul des pourcentages
        total_chaines = chaine_counts['Nombre'].sum()
        chaine_counts['Pourcentage'] = (chaine_counts['Nombre'] / total_chaines * 100).round(1)
        fig_chaine = px.bar(
            chaine_counts, x='Nombre', y='Chaîne',
            orientation='h',
            title='Magasins par chaîne',
            text='Pourcentage',
            color='Chaîne',
            color_discrete_sequence=px.colors.qualitative.Dark24,
            labels={'Nombre': 'Nombre de magasins', 'Chaîne': 'Chaîne', 'Pourcentage': '%'}
        )
        fig_chaine.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig_chaine.update_layout(xaxis_title='Nombre de magasins', yaxis_title=None, showlegend=False,
                                 template="gilroy_export")
        fig_chaine = force_black_axes(fig_chaine)
        st.plotly_chart(fig_chaine, width='stretch')
        st.caption(f"Basé sur {total_chaines} supermarchés ayant une chaîne renseignée.")
    else:
        st.info("La colonne 'Chaine' n'est pas présente dans le fichier supermarchés.")
    st.subheader("Répartition par secteur")
    secteur_counts = df_sm['Secteur'].value_counts().reset_index()
    secteur_counts.columns = ['Secteur', 'Nombre']
    secteur_counts['Pourcentage'] = (secteur_counts['Nombre'] / secteur_counts['Nombre'].sum() * 100).round(1)
    fig_secteur = px.bar(
        secteur_counts, x='Secteur', y='Pourcentage',
        labels={'Secteur': 'Secteur', 'Pourcentage': 'Pourcentage des supermarchés (%)'},
        title="Répartition par secteur",
        text='Pourcentage'
    )
    fig_secteur.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
    fig_secteur.update_layout(template="gilroy_export")
    fig_secteur = force_black_axes(fig_secteur)
    st.plotly_chart(fig_secteur, width='stretch')
    st.caption(f"Basé sur {total} supermarchés.")
    st.subheader("Croisement Secteur × Taille")
    cross_secteur_taille = pd.crosstab(df_sm['Secteur'], df_sm['Taille'])
    st.dataframe(cross_secteur_taille)
    st.subheader("Horaires d'ouverture")
    try:
        df_sm['h_ouv_sem'] = df_sm['ouv_sem'].apply(lambda x: parse_time(x).hour + parse_time(x).minute/60 if parse_time(x) else None)
        df_sm['h_ferm_sem'] = df_sm['ferm_sem'].apply(lambda x: parse_time(x).hour + parse_time(x).minute/60 if parse_time(x) else None)
        df_sm['duree_sem'] = df_sm['h_ferm_sem'] - df_sm['h_ouv_sem']
        if df_sm['duree_sem'].notna().any():
            st.write(f"Durée d'ouverture moyenne en semaine : {df_sm['duree_sem'].mean():.1f} h")
            # Histogramme en pourcentage
            ouv_counts = df_sm['h_ouv_sem'].dropna()
            ouv_pct = ouv_counts.value_counts(normalize=True) * 100
            ouv_df = ouv_pct.reset_index()
            ouv_df.columns = ['Heure', 'Pourcentage']
            ouv_df = ouv_df.sort_values('Heure')
            fig_ouv = px.bar(ouv_df, x='Heure', y='Pourcentage',
                             labels={'Heure': "Heure d'ouverture", 'Pourcentage': 'Pourcentage des supermarchés (%)'},
                             title="Heure d'ouverture en semaine")
            fig_ouv.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
            fig_ouv.update_layout(template="gilroy_export")
            fig_ouv = force_black_axes(fig_ouv)
            st.plotly_chart(fig_ouv, width='stretch')
            st.caption(f"Basé sur {len(ouv_counts)} supermarchés ayant une heure d'ouverture renseignée.")
            duree_secteur = df_sm.groupby('Secteur')['duree_sem'].mean().round(1).reset_index()
            fig_duree = px.bar(
                duree_secteur, x='Secteur', y='duree_sem',
                labels={'Secteur': 'Secteur', 'duree_sem': 'Durée moyenne (h)'},
                title="Durée moyenne d'ouverture (heures) par secteur"
            )
            fig_duree.update_layout(template="gilroy_export")
            fig_duree = force_black_axes(fig_duree)
            st.plotly_chart(fig_duree, width='stretch')
            st.caption(f"Basé sur les supermarchés ayant des horaires complets.")
    except Exception:
        st.info("Horaires non exploitables.")
# ------------------------------------------------------------
# ONGLET 8 : ANOMALIES (inchangé, pas de figures Plotly)
# ------------------------------------------------------------
