"""Page Supermarché."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import json
import re

# Imports avant toute utilisation
from utils import *
from analytics import prepare_supermarche_data

# Récupérer les données depuis la session
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_q_f_raw = st.session_state.get('df_q_f_raw', pd.DataFrame())
df_supermarche_raw = st.session_state.get('df_supermarche_raw', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])
commune_niveau = st.session_state.get('commune_niveau', load_commune_niveau())

st.header("🛒 Questionnaires Supermarché")

# ---- 0. Filtrage obligatoire sur les magasins sélectionnés ----
if not selected_mags:
    st.warning("Aucun magasin sélectionné. Veuillez d'abord choisir des magasins dans l'onglet Accueil.")
    st.stop()

if df_supermarche_full.empty:
    st.info("Aucun questionnaire supermarché trouvé pour les magasins sélectionnés.")
    st.stop()

# Sélecteur de magasin restreint aux magasins sélectionnés
magasins_disponibles = sorted(df_supermarche_full['magasin_officiel'].unique())
mag_sel = st.selectbox("Magasin", ["Tous"] + magasins_disponibles, key="mag_sm")

# Préparation des données enrichies (cache-friendly)
cols_to_drop = ['data_dict', 'data', 'anomalies_list', 'anomalies']
df_supermarche_full_clean = df_supermarche_full.drop(columns=[c for c in cols_to_drop if c in df_supermarche_full.columns], errors='ignore')
df_supermarche_full_clean = make_hashable(df_supermarche_full_clean)
df_show_full_enriched, acheteurs_global_full_raw = prepare_supermarche_data(df_supermarche_full_clean)

# Filtrage supplémentaire par magasin (si l'utilisateur choisit un magasin spécifique)
if mag_sel != "Tous":
    df_show_full = df_show_full_enriched[df_show_full_enriched['magasin_officiel'] == mag_sel]
    acheteurs_global_full = acheteurs_global_full_raw[acheteurs_global_full_raw['magasin_officiel'] == mag_sel]
else:
    df_show_full = df_show_full_enriched
    acheteurs_global_full = acheteurs_global_full_raw

# Version filtrée pour les marques reconnues (déjà filtrée sur sélection)
df_show = df_supermarche.copy() if not df_supermarche.empty else pd.DataFrame()
if mag_sel != "Tous" and not df_show.empty:
    df_show = df_show[df_show['magasin_officiel'] == mag_sel]

if df_show_full.empty:
    st.info("Aucune donnée pour ce magasin.")
    st.stop()

# ---- 0.1 CSS pour réduire l'espace sous les graphiques ----
st.markdown("""
<style>
.stPlotlyChart > div > div > svg {
    height: auto !important;
    max-height: 100%;
}
</style>
""", unsafe_allow_html=True)

# ---- Métriques de synthèse ----
if 'statut' in df_show_full.columns:
    df_show_valides = df_show_full[df_show_full['statut'] != 'Refus']
else:
    df_show_valides = df_show_full

taux_achat = len(acheteurs_global_full) / len(df_show_valides) * 100 if len(df_show_valides) > 0 else 0
vol_moy = acheteurs_global_full['vol_litres'].mean() if not acheteurs_global_full.empty else 0
prix_moy = acheteurs_global_full['prix_litre'].mean() if not acheteurs_global_full.empty else 0

# Filtres sexe/âge (fonction helper locale)
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

# ----- 2. TABLEAU PAR SEGMENT (taille × niveau socio) + graphique ----
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
        plotly_chart_with_local_export(fig_seg_sm,
                                       caption=f"Basé sur {df_seg_sm['Nb questionnaires'].sum()} questionnaires valides (hors refus).",
                                       key="seg_sm_bar")

# ----- 2bis. TAUX D'ACHAT PAR NIVEAU SOCIO-ÉCONOMIQUE DU MAGASIN -----
st.subheader("🏘️ Taux d'achat selon le niveau socio-économique du magasin")
df_sm_q = df_supermarche_full.merge(df_sm[['Nom', 'Niveau_socio']],
                                    left_on='magasin_officiel', right_on='Nom', how='left')
if 'statut' in df_sm_q.columns:
    df_sm_q = df_sm_q[df_sm_q['statut'] != 'Refus']
taux_par_niveau = df_sm_q.groupby('Niveau_socio').apply(
    lambda x: (x['Q1'] == 'Oui').sum() / len(x) * 100 if len(x) > 0 else None
).reset_index(name='Taux d\'achat (%)')
taux_par_niveau.columns = ['Niveau socio-économique', 'Taux d\'achat (%)']
taux_par_niveau = taux_par_niveau.dropna(subset=['Taux d\'achat (%)'])
if not taux_par_niveau.empty:
    fig_niveau = px.bar(taux_par_niveau,
                        x='Niveau socio-économique',
                        y='Taux d\'achat (%)',
                        title="Taux d'achat d'huile de palme selon le niveau socio-économique du supermarché")
    fig_niveau.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
    fig_niveau.update_layout(template="gilroy_export")
    plotly_chart_with_local_export(fig_niveau,
                                   caption=f"Basé sur {len(df_sm_q)} questionnaires valides dans les magasins enquêtés.",
                                   key="niveau_mag_bar")
else:
    st.info("Données insuffisantes.")

# ----- 3. MARQUES ET RAISONS D'ACHAT (top 8 + Autres) -----
st.subheader("🏷️ Marques et raisons d'achat")
acheteurs_global = df_show[df_show['Q1'] == 'Oui'].copy() if not df_show.empty else pd.DataFrame()
acheteurs_filt, _, _ = filter_df(acheteurs_global, "marques")

# Fonction pour nettoyer et regrouper les raisons
def clean_reason(r):
    if not isinstance(r, str):
        return r
    r = r.strip()
    # Fusionner Emballage et Conditionnement
    if r.lower() in ['emballage', 'conditionnement']:
        return 'Emballage'
    return r

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
        plotly_chart_with_local_export(fig_marq,
                                       caption=f"Basé sur {len(acheteurs_filt)} acheteurs. Les pourcentages sont calculés sur l'ensemble des acheteurs (marques reconnues).",
                                       key="marques_pie")
    else:
        st.info("Aucun acheteur avec marque reconnue.")

with col_rais:
    if not acheteurs_filt.empty:
        raisons_series = acheteurs_filt['Q3'].dropna().str.split(',').explode().str.strip()
        raisons_series = raisons_series.apply(normalize_reason)  # <-- AJOUTER CETTE LIGNE
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
            plotly_chart_with_local_export(fig_rais,
                                           caption=f"Basé sur {len(acheteurs_filt)} acheteurs. Un acheteur peut citer plusieurs raisons.",
                                           key="raisons_bar")
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
            plotly_chart_with_local_export(fig_cross,
                                           caption=f"Basé sur {len(exploded_top)} citations parmi les acheteurs des 8 marques principales.",
                                           key="cross_heatmap")

# ----- 4. VOLUMES ACHETÉS (CORRIGÉ) -----
st.subheader("📦 Volumes achetés")
acheteurs_vol, _, _ = filter_df(acheteurs_global, "volumes")
col_vol1, col_vol2 = st.columns(2)
with col_vol1:
    if not acheteurs_vol.empty:
        # Nouveau graphique en barres par catégorie de volume
        def categoriser_volume(v):
            if v < 1: return '< 1 L'
            if v in [1, 2, 2.5, 3, 4, 5, 10]: return f'{v} L'
            if v > 10: return '> 10 L'
            return 'Autres'
        acheteurs_vol['volume_cat'] = acheteurs_vol['vol_litres'].apply(categoriser_volume)
        vol_counts = acheteurs_vol['volume_cat'].value_counts().reset_index()
        vol_counts.columns = ['Volume', 'Nombre']
        ordre_vol = ['< 1 L', '1 L', '2 L', '2.5 L', '3 L', '4 L', '5 L', '10 L', '> 10 L', 'Autres']
        vol_counts['Volume'] = pd.Categorical(vol_counts['Volume'], categories=ordre_vol, ordered=True)
        vol_counts = vol_counts.sort_values('Volume')

        fig_vol = px.bar(vol_counts, x='Volume', y='Nombre',
                         labels={'Volume': 'Volume acheté', 'Nombre': "Nombre d'acheteurs"},
                         title="Distribution des volumes achetés")
        fig_vol.update_traces(texttemplate='%{y}', textposition='outside', textfont=dict(size=12))
        fig_vol.update_layout(template="gilroy_export")
        plotly_chart_with_local_export(fig_vol,
                                       caption=f"Basé sur {len(acheteurs_vol)} acheteurs. Les volumes rares sont regroupés dans 'Autres'.",
                                       key="vol_bar")
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
        plotly_chart_with_local_export(fig_vol_marq,
                                       caption=f"Basé sur {len(df_vol_top8)} acheteurs ayant acheté une marque du top 8.",
                                       key="vol_marque_bar")
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
        fig_freq.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
        fig_freq.update_layout(template="gilroy_export")
        plotly_chart_with_local_export(fig_freq,
                                       caption=f"Basé sur {freq_counts.sum()} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.",
                                       key="freq_bar")
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
            plotly_chart_with_local_export(fig_crit,
                                           caption=f"Basé sur {len(pret_df)} acheteurs prêts à payer plus. Un acheteur peut citer plusieurs critères.",
                                           key="consent_crit_bar")
        else:
            st.info("Aucun critère positif.")
    else:
        st.info("Aucun acheteur prêt à payer plus.")
else:
    st.info("Aucun acheteur.")

# ----- 7. ÉCART DE PRIX PAR CRITÈRE (sans nombre d'acheteurs affiché) -----
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
            # Filtrer les critères vides, None ou négatifs
            def critere_valide(c):
                if not isinstance(c, str) or c.strip() == '':
                    return False
                c_lower = c.strip().lower()
                if any(mot in c_lower for mot in ['non', 'pas prêt', 'ne suis pas']):
                    return False
                return True
            exploded = exploded[exploded['criteres_consentement'].apply(critere_valide)]
            if not exploded.empty:
                ecart_par_crit = exploded.groupby('criteres_consentement')['ecart_rel'].agg(['mean', 'count']).reset_index()
                ecart_par_crit.columns = ['Critère', 'Écart moyen (%)', "Nombre d'acheteurs"]
                ecart_par_crit['Écart moyen (%)'] = ecart_par_crit['Écart moyen (%)'].round(1)
                # Top 8 et autres
                top_ecart = ecart_par_crit.sort_values("Nombre d'acheteurs", ascending=False).head(8)
                autres_ecart = ecart_par_crit.iloc[8:].copy()
                if not autres_ecart.empty:
                    autres_row = pd.DataFrame({
                        'Critère': ['Autres'],
                        'Écart moyen (%)': [autres_ecart['Écart moyen (%)'].mean()],
                        "Nombre d'acheteurs": [autres_ecart["Nombre d'acheteurs"].sum()]
                    })
                    top_ecart = pd.concat([top_ecart, autres_row], ignore_index=True)
                # Graphique : on n'affiche que la valeur de l'écart, pas le nombre d'acheteurs
                fig_ecart_crit = px.bar(
                    top_ecart,
                    x='Critère',
                    y='Écart moyen (%)',
                    text=top_ecart['Écart moyen (%)'].apply(lambda x: f'{x:.1f}%'),
                    labels={'Critère': 'Critère', 'Écart moyen (%)': 'Écart moyen (%)'},
                    title="Pourcentage moyen que les acheteurs sont prêts à payer en plus, par critère (top 8)"
                )
                fig_ecart_crit.update_traces(textposition='outside')
                fig_ecart_crit.update_layout(template="gilroy_export")
                plotly_chart_with_local_export(
                    fig_ecart_crit,
                    caption=f"Basé sur {len(pret_ecart)} acheteurs prêts à payer plus avec données de prix valides.",
                    key="ecart_crit_bar"
                )
                # Boxplot (inchangé)
                with st.expander("📊 Boxplot des écarts par critère (top 8)"):
                    top_crit_list = top_ecart[top_ecart['Critère'] != 'Autres']['Critère'].tolist()
                    df_box = exploded[exploded['criteres_consentement'].isin(top_crit_list)]
                    if not df_box.empty:
                        fig_box = px.box(df_box, x='criteres_consentement', y='ecart_rel',
                                         labels={'criteres_consentement': 'Critère', 'ecart_rel': 'Écart de prix (%)'},
                                         title="Distribution de l'écart de prix par critère")
                        fig_box.update_layout(template="gilroy_export")
                        plotly_chart_with_local_export(fig_box,
                                                       caption=f"Basé sur {len(df_box)} observations.",
                                                       key="ecart_box")
            else:
                st.info("Aucune donnée exploitable.")
        else:
            st.info("Aucun acheteur prêt à payer plus avec données de prix valides.")
    else:
        st.info("Pas assez de données de prix valides.")
else:
    st.info("Aucun acheteur.")

# ----- 8. SEGMENTATION DÉMOGRAPHIQUE (sans boxplot âge/sexe) -----
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
        plotly_chart_with_local_export(fig_sexe,
                                       caption=f"Basé sur {len(acheteurs_seg)} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.",
                                       key="sexe_bar")
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
        plotly_chart_with_local_export(fig_age,
                                       caption=f"Basé sur {len(acheteurs_seg)} acheteurs. Pourcentage calculé sur l'ensemble des acheteurs.",
                                       key="age_bar")
    st.markdown("**Heatmap des acheteurs (Âge × Sexe)**")
    heat_data = pd.crosstab(acheteurs_seg['Tranche_age'], acheteurs_seg['Sexe'])
    if not heat_data.empty:
        fig_heat = px.imshow(heat_data, text_auto=True, aspect="auto",
                             labels=dict(x="Sexe", y="Tranche d'âge", color="Effectif"),
                             title="Nombre d'acheteurs par âge et sexe")
        fig_heat.update_layout(template="gilroy_export")
        plotly_chart_with_local_export(fig_heat,
                                       caption=f"Basé sur {len(acheteurs_seg)} acheteurs. Les effectifs sont indiqués dans chaque case.",
                                       key="heat_age_sexe")
else:
    st.info("Aucun acheteur.")

# ================================================================
# QUESTIONNAIRES NON TRAITÉS
# ================================================================
st.divider()
st.subheader("📋 Questionnaires supermarché non traités (magasins non reconnus ou exclus)")
if not df_supermarche_raw.empty:
    uuids_inclus = set(df_supermarche_full['uuid'].values)
    df_exclus = df_supermarche_raw[~df_supermarche_raw['uuid'].isin(uuids_inclus)]
    if not df_exclus.empty:
        st.warning(f"{len(df_exclus)} questionnaire(s) exclus (magasin non reconnu ou non sélectionné).")
        df_exclus_display = df_exclus[['magasin_officiel', 'date', 'enqueteur', 'uuid']].copy()
        df_exclus_display.columns = ['Magasin relevé', 'Date', 'Enquêteur', 'UUID']
        st.dataframe(df_exclus_display, width='stretch')
    else:
        st.success("✅ Tous les questionnaires supermarché (dans la période et pour l'enquêteur sélectionné) sont inclus dans l'analyse.")
else:
    st.info("Aucune donnée brute disponible pour comparaison.")

# Téléchargement des données brutes
st.download_button("📥 Données brutes (CSV)", df_show_full.to_csv(index=False), "supermarche_data.csv")