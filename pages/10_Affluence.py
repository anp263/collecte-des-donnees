# pages/10_Affluence.py
"""Page Profils d'affluence."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
df_profils_long = st.session_state.get('df_profils_long', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())

df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_profils_long = st.session_state.get('df_profils_long', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])

st.header("Profils d'affluence")

st.header("📊 Profils d'affluence par jour (Google Popular Times)")
if df_profils_pivot.empty:
    st.error("Données d'affluence non disponibles. Vérifiez le fichier 'fréquentation.csv'.")
else:
    jours_map = {
        'Lundi': 'Mo', 'Mardi': 'Tu', 'Mercredi': 'We', 'Jeudi': 'Th', 'Vendredi': 'Fr',
        'Samedi': 'Sa', 'Dimanche': 'Su'
    }
    jours_liste = list(jours_map.keys())
    OPTIONS_AFFICHAGE = jours_liste + [
        "Moyenne semaine (lun-ven)",
        "Moyenne week-end (sam-dim)",
        "Tous les jours",
        "Moyenne sur tous les jours"
    ]
    # ─── Graphique 1 : Profil horaire d'un magasin ───
    st.subheader("📈 Profil horaire d'un magasin")
    magasins_dispos = sorted(df_profils_pivot['magasin'].unique())
    selected_mag = st.selectbox("Choisir un magasin", magasins_dispos)
    selected_option = st.selectbox("Choisir un jour ou une moyenne", OPTIONS_AFFICHAGE, key="opt_mag")
    if selected_mag:
        row_mag = df_profils_pivot[df_profils_pivot['magasin'] == selected_mag].iloc[0]
        fig = go.Figure()
        if selected_option == "Tous les jours":
            couleurs = px.colors.qualitative.Set1
            for i, jour in enumerate(jours_liste):
                code = jours_map[jour]
                valeurs = [row_mag.get(f'{code}_{h}', 0) for h in range(24)]
                fig.add_trace(go.Scatter(
                    x=list(range(24)), y=valeurs,
                    mode='lines', name=jour,
                    line=dict(color=couleurs[i % len(couleurs)])
                ))
            fig.update_layout(
                title=f"Profils horaires – {selected_mag} (tous les jours)",
                xaxis_title="Heure", yaxis_title="Occupation (%)",
                legend_title="Jour"
            )
        else:
            if selected_option == "Moyenne semaine (lun-ven)":
                codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
                titre = f"Profil horaire – {selected_mag} (moyenne semaine)"
            elif selected_option == "Moyenne week-end (sam-dim)":
                codes = ['Sa', 'Su']
                titre = f"Profil horaire – {selected_mag} (moyenne week-end)"
            elif selected_option == "Moyenne sur tous les jours":
                codes = list(jours_map.values())
                titre = f"Profil horaire – {selected_mag} (moyenne sur tous les jours)"
            else:
                codes = [jours_map[selected_option]]
                titre = f"Profil horaire – {selected_mag} ({selected_option})"
            valeurs = [sum(row_mag.get(f'{code}_{h}', 0) for code in codes) / len(codes) for h in range(24)]
            fig = px.line(x=list(range(24)), y=valeurs,
                          labels={'x': 'Heure', 'y': 'Occupation (%)'},
                          title=titre)
        fig.update_xaxes(tickvals=list(range(0, 24, 2)), ticktext=[f"{h}:00" for h in range(0, 24, 2)])
        fig.update_layout(template="gilroy_export")
        fig = force_black_axes(fig)
        st.plotly_chart(fig, width='stretch')
        # Tableau de données pour ce magasin
        if selected_option == "Tous les jours":
            data_dict = {'Heure': [f"{h}:00" for h in range(24)]}
            for jour in jours_liste:
                code = jours_map[jour]
                data_dict[jour] = [row_mag.get(f'{code}_{h}', 0) for h in range(24)]
            df_display = pd.DataFrame(data_dict)
        else:
            if selected_option == "Moyenne semaine (lun-ven)":
                codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
            elif selected_option == "Moyenne week-end (sam-dim)":
                codes = ['Sa', 'Su']
            elif selected_option == "Moyenne sur tous les jours":
                codes = list(jours_map.values())
            else:
                codes = [jours_map[selected_option]]
            valeurs = [sum(row_mag.get(f'{code}_{h}', 0) for code in codes) / len(codes) for h in range(24)]
            df_display = pd.DataFrame({
                'Heure': [f"{h}:00" for h in range(24)],
                'Occupation (%)': valeurs
            })
        st.dataframe(df_display, width='stretch')
    # ─── Graphique 2 : Profil moyen par secteur ───
    st.subheader("📋 Profil moyen par secteur (médiane)")
    if not df_sm.empty:
        # Utilisation du cache
        df_profils_pivot_ser = make_hashable(df_profils_pivot)
        df_sm_ser = make_hashable(df_sm)
        secteur_profiles = prepare_secteur_profiles(df_profils_pivot_ser, df_sm_ser)
        if secteur_profiles is not None and not secteur_profiles.empty:
            secteurs = sorted(secteur_profiles['secteur'].unique())
            if secteurs:
                choix_secteur = st.selectbox("Secteur à afficher", secteurs, key="sect_affluence")
                option_sect = st.selectbox("Jour / moyenne", OPTIONS_AFFICHAGE, key="sect_option_affluence")
                # Récupération des données du secteur
                row_sec = secteur_profiles[secteur_profiles['secteur'] == choix_secteur].iloc[0]
                # Utiliser les codes comme clés pour rester cohérent avec les options
                medians_by_day = {}
                for jour in jours_liste:
                    code = jours_map[jour]
                    medians_by_day[code] = [row_sec.get(f'{code}_{h}', 0) for h in range(24)]
                fig_sect = go.Figure()
                if option_sect == "Tous les jours":
                    couleurs = px.colors.qualitative.Set1
                    for i, jour in enumerate(jours_liste):
                        code = jours_map[jour]
                        fig_sect.add_trace(go.Scatter(
                            x=list(range(24)), y=medians_by_day[code],
                            mode='lines', name=jour,
                            line=dict(color=couleurs[i % len(couleurs)])
                        ))
                    fig_sect.update_layout(
                        title=f"Profils médians – secteur {choix_secteur} (tous les jours)",
                        xaxis_title="Heure", yaxis_title="Occupation (%)",
                        legend_title="Jour"
                    )
                else:
                    if option_sect == "Moyenne semaine (lun-ven)":
                        codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
                        titre = f"Profil médian – secteur {choix_secteur} (moyenne semaine)"
                    elif option_sect == "Moyenne week-end (sam-dim)":
                        codes = ['Sa', 'Su']
                        titre = f"Profil médian – secteur {choix_secteur} (moyenne week-end)"
                    elif option_sect == "Moyenne sur tous les jours":
                        codes = list(jours_map.values())
                        titre = f"Profil médian – secteur {choix_secteur} (moyenne sur tous les jours)"
                    else:
                        codes = [jours_map[option_sect]]
                        titre = f"Profil médian – secteur {choix_secteur} ({option_sect})"
                    valeurs = [np.mean([medians_by_day[jour][h] for jour in codes]) for h in range(24)]
                    fig_sect = px.line(x=list(range(24)), y=valeurs,
                                       labels={'x': 'Heure', 'y': 'Occupation (%)'},
                                       title=titre)
                fig_sect.update_xaxes(tickvals=list(range(0, 24, 2)), ticktext=[f"{h}:00" for h in range(0, 24, 2)])
                fig_sect.update_layout(template="gilroy_export")
                fig_sect = force_black_axes(fig_sect)
                st.plotly_chart(fig_sect, width='stretch')
                # Tableau de données pour le secteur
                if option_sect == "Tous les jours":
                    data_dict = {'Heure': [f"{h}:00" for h in range(24)]}
                    for jour in jours_liste:
                        data_dict[jour] = medians_by_day[jour]
                    df_display = pd.DataFrame(data_dict)
                else:
                    if option_sect == "Moyenne semaine (lun-ven)":
                        codes = ['Mo', 'Tu', 'We', 'Th', 'Fr']
                    elif option_sect == "Moyenne week-end (sam-dim)":
                        codes = ['Sa', 'Su']
                    elif option_sect == "Moyenne sur tous les jours":
                        codes = list(jours_map.values())
                    else:
                        codes = [jours_map[option_sect]]
                    valeurs = [np.mean([medians_by_day[jour][h] for jour in codes]) for h in range(24)]
                    df_display = pd.DataFrame({
                        'Heure': [f"{h}:00" for h in range(24)],
                        'Occupation (%)': valeurs
                    })
                st.dataframe(df_display, width='stretch')
            else:
                st.info("Aucun secteur trouvé.")
        else:
            st.info("Profils secteur non disponibles.")
    else:
        st.warning("Fichier supermarches.csv non chargé.")
    