# pages/01_Supermarche.py
"""Page Supermarché."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import json
import re

# Récupérer les données depuis la session
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_q_f_raw = st.session_state.get('df_q_f_raw', pd.DataFrame())
df_supermarche_raw = st.session_state.get('df_supermarche_raw', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])

# Fonctions nécessaires
from analytics import prepare_supermarche_data
import os
import sys
import re
import json
import hashlib
from datetime import datetime, time, date, timedelta

from analytics import prepare_supermarche_data
from utils import *
from analytics import *

st.header("🛒 Questionnaires Supermarché")
if df_supermarche_full.empty:
    st.info("Aucun questionnaire supermarché trouvé pour les magasins sélectionnés.")
else:
    # Sélecteur de magasin
    magasins_disponibles = sorted(df_supermarche_full['magasin_officiel'].unique())
    mag_sel = st.selectbox("Magasin", ["Tous"] + magasins_disponibles, key="mag_sm")
    # ---- APPEL À LA VERSION CACHÉE (enrichit df_supermarche_full et retourne les acheteurs avec consentement) ----
    # Supprimer les colonnes non hashables
    cols_to_drop = ['data_dict', 'data', 'anomalies_list', 'anomalies']
    df_supermarche_full_clean = df_supermarche_full.drop(columns=[c for c in cols_to_drop if c in df_supermarche_full.columns], errors='ignore')
    df_supermarche_full_clean = make_hashable(df_supermarche_full_clean)   # une seule fois
    df_show_full_enriched, acheteurs_global_full_raw = prepare_supermarche_data(df_supermarche_full_clean)
    # Filtrage par magasin
    if mag_sel != "Tous":
        df_show_full = df_show_full_enriched[df_show_full_enriched['magasin_officiel'] == mag_sel]
        acheteurs_global_full = acheteurs_global_full_raw[acheteurs_global_full_raw['magasin_officiel'] == mag_sel]
    else:
        df_show_full = df_show_full_enriched
        acheteurs_global_full = acheteurs_global_full_raw
    # Version filtrée pour les marques reconnues (ne change pas)
    df_show = df_supermarche.copy() if not df_supermarche.empty else pd.DataFrame()
    if mag_sel != "Tous" and not df_show.empty:
        df_show = df_show[df_show['magasin_officiel'] == mag_sel]
    if df_show_full.empty:
        st.info("Aucune donnée pour ce magasin.")
    else:
        # --- Recalcul des métriques de synthèse ---
                    # --- Calcul des métriques de synthèse ---
        if 'statut' in df_show_full.columns:
            df_show_valides = df_show_full[df_show_full['statut'] != 'Refus']
        else:
            df_show_valides = df_show_full
        # On réutilise l'acheteurs_global_full déjà filtré et enrichi (contient 'pret_plus')
        taux_achat = len(acheteurs_global_full) / len(df_show_valides) * 100 if len(df_show_valides) > 0 else 0
        vol_moy = acheteurs_global_full['vol_litres'].mean() if not acheteurs_global_full.empty else 0
        prix_moy = acheteurs_global_full['prix_litre'].mean() if not acheteurs_global_full.empty else 0
        # Filtres sexe/âge
        def filter_df(data, key_suffix):
            col1, col2 = st.columns(2)
            with col1:
                sexe_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key=f"sexe_{key_suffix}")
            with col2:
                age_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"],
                                       key=f"age_{key_suffix}")
            filtered = data.copy()
            if sexe_sel != "Tous": filtered = filtered[filtered['Sexe'] == sexe_sel]
            if age_sel != "Tous": filtered = filtered[filtered['Tranche_age'] == age_sel]
            return filtered, sexe_sel, age_sel
        # ----- 1. SYNTHÈSE GÉNÉRALE -----
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Taux d'achat", f"{taux_achat:.1f}%")
        col2.metric("Vol. moyen (L)", f"{fmt_volume(vol_moy,2)} L")
        col3.metric("Prix/L", fmt_prix(prix_moy, st.session_state.get("devise_globale", "FC")))
        col4.metric("Acheteurs", len(acheteurs_global_full))
        # ----- 2. TABLEAU PAR SEGMENT (inchangé) -----
        st.subheader("📊 Synthèse par segment de magasin (taille × niveau socio-économique)")
        if not df_sm.empty and not df_supermarche_full.empty:
            df_sm_seg = df_sm[['Nom', 'Taille', 'Niveau_socio']].copy()
            df_sm_seg['nom_norm'] = df_sm_seg['Nom'].apply(normalize_name)
            df_q_seg = df_supermarche_full.copy()
            df_q_seg['magasin_norm'] = df_q_seg['magasin_officiel'].apply(normalize_name)
            df_q_seg = df_q_seg.merge(df_sm_seg[['nom_norm', 'Taille', 'Niveau_socio']],
                                      left_on='magasin_norm', right_on='nom_norm', how='left')
            tailles = sorted(df_q_seg['Taille'].dropna().unique())
            niveaux = sorted(df_q_seg['Niveau_socio'].dropna().unique())
            rows_seg = []
            for taille in tailles:
                for niveau in niveaux:
                    mask = (df_q_seg['Taille'] == taille) & (df_q_seg['Niveau_socio'] == niveau)
                    sub = df_q_seg[mask]
                    if sub.empty:
                        continue
                    if 'statut' in sub.columns:
                        sub_valides = sub[sub['statut'] != 'Refus']
                    else:
                        sub_valides = sub
                    total_q = len(sub_valides)
                    acheteurs = sub_valides[sub_valides['Q1'] == 'Oui']
                    nb_acheteurs = len(acheteurs)
                    taux_achat_seg = (nb_acheteurs / total_q * 100) if total_q > 0 else 0
                    vol_moy_seg = acheteurs['vol_litres'].mean() if nb_acheteurs > 0 else 0
                    prix_moy_seg = acheteurs['prix_litre'].mean() if nb_acheteurs > 0 else 0
                    rows_seg.append({
                        'Taille': taille,
                        'Niveau socio-économique': niveau,
                        'Nb questionnaires': total_q,
                        'Taux d\'achat (%)': round(taux_achat_seg, 1),
                        'Volume moyen (L)': fmt_volume(vol_moy_seg, 2) + " L",
                        'Prix moyen (FC/L)': fmt_prix(prix_moy_seg, "FC") + "/L"
                    })
            if rows_seg:
                df_seg_sm = pd.DataFrame(rows_seg)
                st.dataframe(df_seg_sm, width='stretch')
                fig_seg_sm = px.bar(df_seg_sm[df_seg_sm['Nb questionnaires'] > 0],
                                    x='Taille',
                                    y="Taux d'achat (%)",
                                    color='Niveau socio-économique',
                                    barmode='group',
                                    labels={'Taille': 'Taille du magasin',
                                            'Taux d\'achat (%)': 'Taux d\'achat (%)',
                                            'Niveau socio-économique': 'Niveau'},
                                    title="Taux d'achat par segment (taille × niveau)")
                fig_seg_sm.update_layout(template="gilroy_export")
                fig_seg_sm = force_black_axes(fig_seg_sm)
                st.plotly_chart(fig_seg_sm, width='stretch')
                st.caption(f"Basé sur {df_seg_sm['Nb questionnaires'].sum()} questionnaires valides (hors refus).")
        # ----- 3. MARQUES ET RAISONS D'ACHAT (avec top 8 + Autres) -----
        st.subheader("🏷️ Marques et raisons d'achat")
        acheteurs_global = df_show[df_show['Q1'] == 'Oui'].copy() if not df_show.empty else pd.DataFrame()
        acheteurs_filt, _, _ = filter_df(acheteurs_global, "marques")
        # Calcul du top 8 pour les données filtrées
        def get_top8_brands_from_acheteurs(df_acheteurs):
            if df_acheteurs.empty or 'marque_clean' not in df_acheteurs.columns:
                return []
            counts = df_acheteurs['marque_clean'].value_counts()
            return counts.head(8).index.tolist()
        top8_brands = get_top8_brands_from_acheteurs(acheteurs_filt)
        col_marq, col_rais = st.columns(2)
        with col_marq:
            if not acheteurs_filt.empty and top8_brands:
                marque_counts = acheteurs_filt['marque_clean'].value_counts()
                marque_pct = marque_counts / marque_counts.sum() * 100
                top8_pct = marque_pct[marque_pct.index.isin(top8_brands)]
                autres_pct = marque_pct[~marque_pct.index.isin(top8_brands)].sum()
                pie_data = pd.DataFrame({
                    'Marque': top8_pct.index.tolist() + (['Autres'] if autres_pct > 0 else []),
                    'Pourcentage': top8_pct.tolist() + ([autres_pct] if autres_pct > 0 else [])
                })
                pie_data['ordre'] = pie_data['Marque'].apply(lambda x: 0 if x != 'Autres' else 1)
                pie_data = pie_data.sort_values('ordre').drop(columns=['ordre'])
                fig_marq = px.pie(pie_data, values='Pourcentage', names='Marque',
                                title="Marques achetées (top 8 + Autres)")
                fig_marq.update_traces(textinfo='percent+label', sort=False)
                fig_marq.update_layout(template="gilroy_export")
                fig_marq = force_black_axes(fig_marq)
                st.plotly_chart(fig_marq, width='stretch')
                st.caption(f"Basé sur {len(acheteurs_filt)} acheteurs. Les pourcentages sont calculés sur l'ensemble des acheteurs (marques reconnues).")
            else:
                st.info("Aucun acheteur avec marque reconnue.")
        with col_rais:
            if not acheteurs_filt.empty:
                raisons_series = acheteurs_filt['Q3'].dropna().str.split(',').explode().str.strip()
                raisons_counts = raisons_series.value_counts()
                raisons_pct = raisons_counts / len(acheteurs_filt) * 100
                raisons_df = raisons_pct.reset_index()
                raisons_df.columns = ['Raison', 'Pourcentage']
                if not raisons_df.empty:
                    fig_rais = px.bar(raisons_df,
                                      x='Raison', y='Pourcentage',
                                      labels={'Raison': 'Raison évoquée', 'Pourcentage': 'Pourcentage des acheteurs (%)'},
                                      title="Raisons de choix de la marque")
                    fig_rais.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                    fig_rais.update_layout(template="gilroy_export")
                    fig_rais = force_black_axes(fig_rais)
                    st.plotly_chart(fig_rais, width='stretch')
                    st.caption(f"Basé sur {len(acheteurs_filt)} acheteurs. Un acheteur peut citer plusieurs raisons.")
                else:
                    st.info("Aucune raison.")
            else:
                st.info("Aucun acheteur.")
        # Croisement marque × raison
        if not acheteurs_filt.empty and 'Q3' in acheteurs_filt.columns and top8_brands:
            temp = acheteurs_filt[['marque_clean', 'Q3']].dropna(subset=['marque_clean'])
            temp = temp[temp['marque_clean'].isin(top8_brands)]
            temp = temp[temp['Q3'].notna() & (temp['Q3'].astype(str).str.strip() != '')]
            if not temp.empty:
                exploded = temp.assign(Raison=temp['Q3'].astype(str).str.split(',')).explode('Raison')
                exploded['Raison'] = exploded['Raison'].str.strip()
                exploded = exploded[exploded['Raison'] != '']
                exploded_top = exploded.reset_index(drop=True)
                if not exploded_top.empty:
                    cross = pd.crosstab(exploded_top['marque_clean'], exploded_top['Raison'])
                    st.subheader("🔗 Raisons par marque")
                    fig_cross = px.imshow(cross,
                                          text_auto=True,
                                          aspect="auto",
                                          labels=dict(x="Raison", y="Marque", color="Effectif"),
                                          title="Effectifs marque × raison (top 8 marques)")
                    fig_cross.update_layout(template="gilroy_export")
                    fig_cross = force_black_axes(fig_cross)
                    st.plotly_chart(fig_cross, width='stretch')
                    st.caption(f"Basé sur {len(exploded_top)} citations parmi les acheteurs des 8 marques principales.")
        # ----- 4. VOLUMES ACHETÉS -----
        st.subheader("📦 Volumes achetés")
        acheteurs_vol, _, _ = filter_df(acheteurs_global, "volumes")
        col_vol1, col_vol2 = st.columns(2)
        with col_vol1:
            if not acheteurs_vol.empty:
                fig_vol_hist = px.histogram(acheteurs_vol, x='vol_litres', nbins=20,
                                            histnorm='percent',
                                            labels={'vol_litres': 'Volume (L)', 'percent': 'Pourcentage des acheteurs'},
                                            title="Distribution des volumes achetés (litres)")
                fig_vol_hist.update_traces(texttemplate=None)
                fig_vol_hist.update_xaxes(tickformat=",.0f")
                fig_vol_hist.update_layout(template="gilroy_export")
                fig_vol_hist = force_black_axes(fig_vol_hist)
                st.plotly_chart(fig_vol_hist, width='stretch')
                st.caption(f"Basé sur {len(acheteurs_vol)} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.")
            else:
                st.info("Aucun acheteur.")
        with col_vol2:
            if not acheteurs_vol.empty and 'marque_clean' in acheteurs_vol.columns and top8_brands:
                df_vol_top8 = acheteurs_vol[acheteurs_vol['marque_clean'].isin(top8_brands)]
                vol_par_marque = df_vol_top8.groupby('marque_clean')['vol_litres'].mean().reset_index()
                vol_par_marque.columns = ['Marque', 'Volume moyen (L)']
                vol_par_marque = vol_par_marque.sort_values('Volume moyen (L)', ascending=False)
                fig_vol_marq = px.bar(vol_par_marque,
                                      x='Marque', y='Volume moyen (L)',
                                      labels={'Marque': 'Marque', 'Volume moyen (L)': 'Volume moyen (L)'},
                                      title="Volume moyen par marque (top 8)")
                fig_vol_marq.update_yaxes(tickformat=",.0f")
                fig_vol_marq.update_layout(template="gilroy_export")
                fig_vol_marq = force_black_axes(fig_vol_marq)
                st.plotly_chart(fig_vol_marq, width='stretch')
                st.caption(f"Basé sur {len(df_vol_top8)} acheteurs ayant acheté une marque du top 8.")
            else:
                st.info("Aucun acheteur.")
        # ----- 5. FRÉQUENCE D'ACHAT -----
        st.subheader("📅 Fréquence d'achat")
        acheteurs_freq, _, _ = filter_df(acheteurs_global, "freq")
        if not acheteurs_freq.empty:
            def clean_q6(val):
                if isinstance(val, str) and val.strip() != '' and val.strip().lower() not in ['nan', 'none']:
                    return val
                return pd.NA
            acheteurs_freq['Q6_clean'] = acheteurs_freq['Q6'].apply(clean_q6)
            freq_counts = acheteurs_freq['Q6_clean'].dropna().value_counts()
            if not freq_counts.empty:
                freq_pct = freq_counts / freq_counts.sum() * 100
                freq_df = freq_pct.reset_index()
                freq_df.columns = ['Fréquence', 'Pourcentage']
                fig_freq = px.bar(freq_df,
                                  x='Fréquence', y='Pourcentage',
                                  labels={'Fréquence': 'Fréquence', 'Pourcentage': 'Pourcentage des acheteurs (%)'},
                                  title="Fréquence d'achat (acheteurs)")
                fig_freq.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                fig_freq.update_layout(template="gilroy_export")
                fig_freq = force_black_axes(fig_freq)
                st.plotly_chart(fig_freq, width='stretch')
                st.caption(f"Basé sur {freq_counts.sum()} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.")
            else:
                st.info("Aucune réponse.")
        else:
            st.info("Aucun acheteur.")
        # ----- 6. CONSENTEMENT À PAYER PLUS (taux et critères) -----
        st.subheader("💵 Consentement à payer plus cher")
        acheteurs_cons, _, _ = filter_df(acheteurs_global_full, "consent")
        if not acheteurs_cons.empty:
            nb_pret = acheteurs_cons['pret_plus'].sum()
            tx_pret = (nb_pret / len(acheteurs_cons) * 100) if len(acheteurs_cons) else 0
            st.metric("Prêts à payer plus", f"{tx_pret:.1f}% ({nb_pret}/{len(acheteurs_cons)} acheteurs)")
            with st.expander("🔍 Détail des réponses brutes (Q9)"):
                reponses_brutes = acheteurs_cons['Q9'].value_counts().reset_index()
                reponses_brutes.columns = ['Réponse originale', 'Nombre']
                st.dataframe(reponses_brutes, width='stretch')
            pret_df = acheteurs_cons[acheteurs_cons['pret_plus'] == True]
            if not pret_df.empty:
                all_criteria = pret_df['criteres_consentement'].explode()
                all_criteria = all_criteria[~all_criteria.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                crit_counts = all_criteria.value_counts()
                crit_pct = crit_counts / len(pret_df) * 100
                crit_df = crit_pct.reset_index()
                crit_df.columns = ['Critère', 'Pourcentage']
                if not crit_df.empty:
                    st.subheader("📋 Critères invoqués pour accepter de payer plus (top 8)")
                    top_crit = crit_df.head(8)
                    autres_crit = crit_df.iloc[8:]['Pourcentage'].sum()
                    if autres_crit > 0:
                        top_crit = pd.concat([top_crit, pd.DataFrame({'Critère': ['Autres'], 'Pourcentage': [autres_crit]})], ignore_index=True)
                    fig_crit = px.bar(top_crit, x='Critère', y='Pourcentage',
                                      labels={'Critère': 'Critère', 'Pourcentage': 'Pourcentage des acheteurs prêts à payer plus (%)'},
                                      title="Critères de consentement à payer plus")
                    fig_crit.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                    fig_crit.update_layout(template="gilroy_export")
                    fig_crit = force_black_axes(fig_crit)
                    st.plotly_chart(fig_crit, width='stretch')
                    st.caption(f"Basé sur {len(pret_df)} acheteurs prêts à payer plus. Un acheteur peut citer plusieurs critères.")
                else:
                    st.info("Aucun critère positif.")
            else:
                st.info("Aucun acheteur prêt à payer plus.")
        else:
            st.info("Aucun acheteur.")
        # ----- 7. ÉCART DE PRIX PAR CRITÈRE -----
        st.subheader("💰 Consentement à payer plus par critère (% d'écart de prix)")
        acheteurs_ecart, _, _ = filter_df(acheteurs_global_full, "ecart")
        if not acheteurs_ecart.empty:
            acheteurs_ecart = acheteurs_ecart.dropna(subset=['prix_num', 'prix_max_num']).copy()
            if not acheteurs_ecart.empty:
                acheteurs_ecart['ecart_rel'] = (acheteurs_ecart['prix_max_num'] / acheteurs_ecart['prix_num'] - 1) * 100
                pret_ecart = acheteurs_ecart[acheteurs_ecart['pret_plus'] == True]
                if not pret_ecart.empty:
                    pret_ecart['criteres_consentement'] = pret_ecart['criteres_consentement'].apply(
                        lambda x: x if isinstance(x, list) else [])
                    exploded = pret_ecart.explode('criteres_consentement')
                    exploded = exploded[~exploded['criteres_consentement'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    if not exploded.empty:
                        ecart_par_crit = exploded.groupby('criteres_consentement')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_par_crit.columns = ['Critère', 'Écart moyen (%)', "Nombre d'acheteurs"]
                        ecart_par_crit['Écart moyen (%)'] = ecart_par_crit['Écart moyen (%)'].round(1)
                        top_ecart = ecart_par_crit.sort_values("Nombre d'acheteurs", ascending=False).head(8)
                        autres_ecart = ecart_par_crit.iloc[8:].copy()
                        if not autres_ecart.empty:
                            autres_row = pd.DataFrame({
                                'Critère': ['Autres'],
                                'Écart moyen (%)': [autres_ecart['Écart moyen (%)'].mean()],
                                "Nombre d'acheteurs": [autres_ecart["Nombre d'acheteurs"].sum()]
                            })
                            top_ecart = pd.concat([top_ecart, autres_row], ignore_index=True)
                        fig_ecart_crit = px.bar(top_ecart, x='Critère', y='Écart moyen (%)',
                                                text="Nombre d'acheteurs",
                                                labels={'Critère': 'Critère',
                                                        'Écart moyen (%)': 'Écart moyen (%)'},
                                                title="Pourcentage moyen que les acheteurs sont prêts à payer en plus, par critère (top 8)")
                        fig_ecart_crit.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_ecart_crit.update_layout(template="gilroy_export")
                        fig_ecart_crit = force_black_axes(fig_ecart_crit)
                        st.plotly_chart(fig_ecart_crit, width='stretch')
                        st.caption(f"Basé sur {len(pret_ecart)} acheteurs prêts à payer plus avec données de prix valides.")
                        with st.expander("📊 Boxplot des écarts par critère (top 8)"):
                            top_crit_list = top_ecart[top_ecart['Critère'] != 'Autres']['Critère'].tolist()
                            df_box = exploded[exploded['criteres_consentement'].isin(top_crit_list)]
                            if not df_box.empty:
                                fig_box = px.box(df_box, x='criteres_consentement', y='ecart_rel',
                                                 labels={'criteres_consentement': 'Critère', 'ecart_rel': 'Écart de prix (%)'},
                                                 title="Distribution de l'écart de prix par critère")
                                fig_box.update_layout(template="gilroy_export")
                                fig_box = force_black_axes(fig_box)
                                st.plotly_chart(fig_box, width='stretch')
                                st.caption(f"Basé sur {len(df_box)} observations. Les points représentent les acheteurs.")
                else:
                    st.info("Aucun acheteur prêt à payer plus avec données de prix valides.")
            else:
                st.info("Pas assez de données de prix valides.")
        else:
            st.info("Aucun acheteur.")
        # ----- 8. SEGMENTATION DÉMOGRAPHIQUE -----
        st.subheader("👥 Segmentation des acheteurs")
        acheteurs_seg = acheteurs_global_full.copy()
        if not acheteurs_seg.empty:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Acheteurs par sexe**")
                sexe_counts = acheteurs_seg['Sexe'].value_counts()
                sexe_pct = sexe_counts / sexe_counts.sum() * 100
                sexe_df = sexe_pct.reset_index()
                sexe_df.columns = ['Sexe', 'Pourcentage']
                fig_sexe = px.bar(sexe_df, x='Sexe', y='Pourcentage',
                                  color='Sexe',
                                  labels={'Sexe': 'Sexe', 'Pourcentage': 'Pourcentage des acheteurs (%)'},
                                  title="Acheteurs par sexe")
                fig_sexe.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                fig_sexe.update_layout(template="gilroy_export")
                fig_sexe = force_black_axes(fig_sexe)
                st.plotly_chart(fig_sexe, width='stretch')
                st.caption(f"Basé sur {len(acheteurs_seg)} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.")
            with col2:
                st.markdown("**Acheteurs par âge**")
                age_counts = acheteurs_seg['Tranche_age'].value_counts()
                age_pct = age_counts / age_counts.sum() * 100
                age_df = age_pct.reset_index()
                age_df.columns = ["Tranche d'âge", 'Pourcentage']
                fig_age = px.bar(age_df, x="Tranche d'âge", y='Pourcentage',
                                 color="Tranche d'âge",
                                 labels={"Tranche d'âge": "Âge", 'Pourcentage': 'Pourcentage des acheteurs (%)'},
                                 title="Acheteurs par tranche d'âge")
                fig_age.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                fig_age.update_layout(template="gilroy_export")
                fig_age = force_black_axes(fig_age)
                st.plotly_chart(fig_age, width='stretch')
                st.caption(f"Basé sur {len(acheteurs_seg)} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.")
            st.markdown("**Heatmap des acheteurs (Âge × Sexe)**")
            heat_data = pd.crosstab(acheteurs_seg['Tranche_age'], acheteurs_seg['Sexe'])
            if not heat_data.empty:
                fig_heat = px.imshow(heat_data, text_auto=True, aspect="auto",
                                     labels=dict(x="Sexe", y="Tranche d'âge", color="Effectif"),
                                     title="Nombre d'acheteurs par âge et sexe")
                fig_heat.update_layout(template="gilroy_export")
                fig_heat = force_black_axes(fig_heat)
                st.plotly_chart(fig_heat, width='stretch')
                st.caption(f"Basé sur {len(acheteurs_seg)} acheteurs. Les effectifs sont indiqués dans chaque case.")
            st.markdown("**Volume acheté par âge et sexe**")
            vol_data = acheteurs_seg[['Sexe', 'Tranche_age', 'vol_litres']].dropna()
            if not vol_data.empty:
                fig_box_age = px.box(vol_data, x='Tranche_age', y='vol_litres', color='Sexe',
                                     labels={'Tranche_age': 'Âge', 'vol_litres': 'Volume (L)', 'Sexe': 'Sexe'},
                                     title="Distribution du volume acheté (L) par âge et sexe")
                fig_box_age.update_yaxes(tickformat=",.0f")
                fig_box_age.update_layout(template="gilroy_export")
                fig_box_age = force_black_axes(fig_box_age)
                st.plotly_chart(fig_box_age, width='stretch')
                st.caption(f"Basé sur {len(vol_data)} acheteurs. La boîte montre la médiane et les quartiles.")
            else:
                st.info("Données de volume insuffisantes.")
        else:
            st.info("Aucun acheteur.")
        # ----- 9. PERCEPTION DE LA QUALITÉ & NOTORIÉTÉ -----
        st.subheader("🔍 Perception de la qualité & Notoriété de RougeCongo des clients des supermarchés")
        if 'statut' in df_supermarche_full.columns:
            acheteurs_sm = df_supermarche_full[(df_supermarche_full['Q1'] == 'Oui') & (df_supermarche_full['statut'] != 'Refus')].copy()
        else:
            acheteurs_sm = df_supermarche_full[df_supermarche_full['Q1'] == 'Oui'].copy()
        sm_menage = df_q_f[df_q_f['type'] == 'supermarche_menage'].copy()
        if 'statut' in sm_menage.columns:
            sm_menage = sm_menage[sm_menage['statut'] != 'Refus']
        if not sm_menage.empty:
            sm_menage['Q_Qualite'] = sm_menage['data_dict'].apply(lambda d: d.get('Q_Qualite') if isinstance(d, dict) else None)
            sm_menage['RC_Conn']   = sm_menage['data_dict'].apply(lambda d: d.get('Q_RC_Connaissance') if isinstance(d, dict) else None)
            sm_menage['RC_Qual']   = sm_menage['data_dict'].apply(lambda d: d.get('Q_RC_Qualités') if isinstance(d, dict) else None)
            sm_menage['SexeAgeClasse'] = sm_menage['data_dict'].apply(lambda d: d.get('Q10_SexeAgeClasse') if isinstance(d, dict) else None)
            def get_sexe_from_qsm_menage(x):
                if not isinstance(x, str): return None
                parts = x.split('-')
                if len(parts) >= 1:
                    sexe = parts[0].strip().upper()
                    if sexe in ['F', 'H']: return sexe
                return None
            def get_age_from_qsm_menage(x):
                if not isinstance(x, str): return None
                match = re.search(r'(\d+[-+]*\d*\s*ans?)', x)
                if match: return match.group(1)
                return None
            sm_menage['Sexe'] = sm_menage['SexeAgeClasse'].apply(get_sexe_from_qsm_menage)
            sm_menage['Âge'] = sm_menage['SexeAgeClasse'].apply(get_age_from_qsm_menage)
            # Ajout de la tranche d'âge pour sm_menage (utilise la fonction tranche_age déjà définie)
            def tranche_age(age_str):
                if not age_str: return 'Inconnu'
                try:
                    age = int(re.search(r'\d+', age_str).group())
                    if age < 25: return 'Moins de 25 ans'
                    elif age < 35: return '25-34 ans'
                    elif age < 50: return '35-49 ans'
                    else: return '50 ans et plus'
                except: return 'Inconnu'
            sm_menage['Tranche_age'] = sm_menage['Âge'].apply(tranche_age)
        else:
            sm_menage = pd.DataFrame(columns=['Q_Qualite', 'RC_Conn', 'RC_Qual', 'Sexe', 'Âge', 'Tranche_age'])
        acheteurs_sm = acheteurs_sm.rename(columns={'Q11': 'Q_Qualite'})
        cols_to_keep = ['Q_Qualite', 'RC_Conn', 'RC_Qual', 'Sexe', 'Âge', 'Tranche_age']
        for col in cols_to_keep:
            if col not in acheteurs_sm.columns: acheteurs_sm[col] = None
            if col not in sm_menage.columns: sm_menage[col] = None
        df_combined = pd.concat([acheteurs_sm[cols_to_keep], sm_menage[cols_to_keep]], ignore_index=True)
        if df_combined.empty:
            st.info("Aucune donnée disponible pour l'analyse de la perception et de la notoriété.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                sexe_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key="qual_sexe")
            with col2:
                age_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"], key="qual_age")
            df_combined_filt = df_combined.copy()
            if sexe_sel != "Tous": df_combined_filt = df_combined_filt[df_combined_filt['Sexe'] == sexe_sel]
            if age_sel != "Tous": df_combined_filt = df_combined_filt[df_combined_filt['Tranche_age'] == age_sel]
            st.caption(f"Population combinée : {len(df_combined)} répondants (acheteurs + non-acheteurs réinterrogés)")
            st.subheader("🧪 Perception de la qualité")
            if not df_combined_filt.empty and df_combined_filt['Q_Qualite'].notna().any():
                qual_series = df_combined_filt['Q_Qualite'].dropna().astype(str).str.split(',').explode().str.strip()
                qual_series = qual_series[qual_series != '']
                qual_series = qual_series.apply(lambda x: x.split(':', 1)[1].strip() if x.lower().startswith('autre:') else x)
                qual_counts = qual_series.value_counts()
                nb_qual_rep = df_combined_filt['Q_Qualite'].notna().sum()
                qual_pct = qual_counts / nb_qual_rep * 100
                qual_df = qual_pct.reset_index()
                qual_df.columns = ['Critère', 'Pourcentage']
                qual_df['groupe'] = qual_df['Pourcentage'].apply(lambda x: 'Autres' if x < 1 else x)
                qual_df_agg = qual_df.groupby('groupe')['Pourcentage'].sum().reset_index()
                qual_df_agg.columns = ['Critère', 'Pourcentage']
                qual_df_agg['ordre'] = qual_df_agg['Critère'].apply(lambda x: 0 if x != 'Autres' else 1)
                qual_df_agg = qual_df_agg.sort_values('ordre').drop(columns=['ordre'])
                fig_qual = px.bar(qual_df_agg, x='Critère', y='Pourcentage',
                                labels={'Critère': 'Critère de qualité', 'Pourcentage': 'Pourcentage des répondants (%)'},
                                title="Critères de reconnaissance de la qualité de l'huile")
                fig_qual.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                fig_qual.update_layout(template="gilroy_export")
                fig_qual = force_black_axes(fig_qual)
                st.plotly_chart(fig_qual, width='stretch')
                st.caption(f"Basé sur {nb_qual_rep} répondants ayant répondu à cette question. Un répondant peut citer plusieurs critères. Les critères à moins de 1% sont regroupés dans 'Autres'.")
            else:
                st.info("Aucune réponse sur la reconnaissance de la qualité.")
            st.subheader("📣 Notoriété de RougeCongo")
            col_conn, col_qual_rc = st.columns(2)
            with col_conn:
                if not df_combined_filt.empty and df_combined_filt['RC_Conn'].notna().any():
                    conn_counts = df_combined_filt['RC_Conn'].dropna().loc[lambda x: x != ''].value_counts()
                    nb_conn_rep = df_combined_filt['RC_Conn'].notna().sum()
                    conn_pct = conn_counts / nb_conn_rep * 100
                    conn_df = conn_pct.reset_index()
                    conn_df.columns = ['Réponse', 'Pourcentage']
                    fig_conn = px.bar(conn_df, x='Réponse', y='Pourcentage',
                                    labels={'Réponse': 'Réponse', 'Pourcentage': 'Pourcentage des répondants (%)'},
                                    title="Notoriété de RougeCongo")
                    fig_conn.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                    fig_conn.update_layout(template="gilroy_export")
                    fig_conn = force_black_axes(fig_conn)
                    st.plotly_chart(fig_conn, width='stretch')
                    st.caption(f"Basé sur {nb_conn_rep} répondants ayant répondu à cette question.")
                else:
                    st.info("Aucune donnée sur la connaissance.")
            with col_qual_rc:
                if not df_combined_filt.empty and df_combined_filt['RC_Qual'].notna().any():
                    qual_rc_series = df_combined_filt['RC_Qual'].dropna().astype(str).str.split(',').explode().str.strip()
                    qual_rc_series = qual_rc_series[qual_rc_series != '']
                    qual_rc_series = qual_rc_series.apply(lambda x: x.split(':', 1)[1].strip() if x.lower().startswith('autre:') else x)
                    qual_rc_counts = qual_rc_series.value_counts()
                    nb_rc_qual_rep = df_combined_filt['RC_Qual'].notna().sum()
                    qual_rc_pct = qual_rc_counts / nb_rc_qual_rep * 100
                    qual_rc_df = qual_rc_pct.reset_index()
                    qual_rc_df.columns = ['Qualité', 'Pourcentage']
                    qual_rc_df['groupe'] = qual_rc_df['Pourcentage'].apply(lambda x: 'Autres' if x < 1 else x)
                    qual_rc_agg = qual_rc_df.groupby('groupe')['Pourcentage'].sum().reset_index()
                    qual_rc_agg.columns = ['Qualité', 'Pourcentage']
                    qual_rc_agg['ordre'] = qual_rc_agg['Qualité'].apply(lambda x: 0 if x != 'Autres' else 1)
                    qual_rc_agg = qual_rc_agg.sort_values('ordre').drop(columns=['ordre'])
                    fig_rc_qual = px.bar(qual_rc_agg, x='Qualité', y='Pourcentage',
                                        labels={'Qualité': 'Qualité évoquée', 'Pourcentage': 'Pourcentage des répondants (%)'},
                                        title="Qualités attribuées à RougeCongo")
                    fig_rc_qual.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
                    fig_rc_qual.update_layout(template="gilroy_export")
                    fig_rc_qual = force_black_axes(fig_rc_qual)
                    st.plotly_chart(fig_rc_qual, width='stretch')
                    st.caption(f"Basé sur {nb_rc_qual_rep} répondants ayant répondu à cette question. Les qualités à moins de 1% sont regroupées dans 'Autres'. Un répondant peut citer plusieurs qualités.")
                else:
                    st.info("Aucune réponse sur les qualités.")
        # ================================================================
        # QUESTIONNAIRES NON TRAITÉS
        # ================================================================
        st.divider()
        st.subheader("📋 Questionnaires supermarché non traités (magasins non reconnus ou exclus)")
        if not df_supermarche_raw.empty:
            uuids_inclus = set(df_supermarche_full['uuid'].values)
            df_exclus = df_supermarche_raw[~df_supermarche_raw['uuid'].isin(uuids_inclus)]
            if not df_exclus.empty:
                st.warning(f"{len(df_exclus)} questionnaire(s) exclus car le magasin n'a pas été rapproché d'un magasin sélectionné.")
                df_exclus_display = df_exclus[['magasin_officiel', 'date', 'enqueteur', 'uuid']].copy()
                df_exclus_display.columns = ['Magasin relevé', 'Date', 'Enquêteur', 'UUID']
                st.dataframe(df_exclus_display, width='stretch')
            else:
                st.success("✅ Tous les questionnaires supermarché (dans la période et pour l'enquêteur sélectionné) sont inclus dans l'analyse.")
        else:
            st.info("Aucune donnée brute disponible pour comparaison.")
        # ----- 10. TÉLÉCHARGEMENT -----
        st.download_button("📥 Données brutes (CSV)", df_show_full.to_csv(index=False), "supermarche_data.csv")
# ------------------------------------------------------------
# ONGLET 3 : MÉNAGES
# ------------------------------------------------------------
