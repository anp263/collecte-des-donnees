"""Page Ménages."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import json
import re

from utils import *
from analytics import *

# Récupérer les données depuis la session
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
secteur_profiles = st.session_state.get('secteur_profiles', None)
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])
df_q_f_raw = st.session_state.get('df_q_f_raw', pd.DataFrame())


# Fonctions
def prepare_menage_unifie(df_q_f_raw, df_sm, commune_niveau):
    df_q_f_raw = deserialize_obj_cols(df_q_f_raw)
    df_source = df_q_f_raw[df_q_f_raw['type'].isin(['menage', 'supermarche', 'supermarche_menage'])].copy()
    rows_unified = []
    for _, row in df_source.iterrows():
        qtype = row['type']
        data = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
        if qtype == 'supermarche':
            achat = str(data.get('Q1_Achat', '')).strip().lower()
            if achat != 'oui':
                continue
            cat = 'Acheteur supermarché'
        elif qtype == 'supermarche_menage':
            cat = 'Non-acheteur supermarché'
        else:
            cat = 'Ménage pur'
        if qtype == 'menage':
            sexe_age = data.get('Q10_SexeAgeClasse')
            nb_pers = data.get('Q1_NbPersonnes')
            achat_huile = str(data.get('Q2_Achat', '')).strip()
            freq = data.get('Q3_Frequence')
            marque = data.get('Q7_MarquePreferee')
            qte_nb = data.get('Q4_Quantite_Nombre')
            contenant = data.get('Q4_Quantite_Contenant')
            vol_unit = data.get('Q4_Quantite_VolumeUnitaire')
            prix = data.get('Q5_PrixHabituel')
            pourcent = data.get('Q6_Pourcentages')
            pret_plus = data.get('Q8_PretPayerPlus')
            prix_max = data.get('Q9_PrixMax')
            qualite = data.get('Q_Qualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = None
            supermarche_origine = None
            commune = data.get('Commune')
        elif qtype == 'supermarche_menage':
            sexe_age = data.get('Q11_SexeAgeClasse')
            nb_pers = data.get('Q2_NbPersonnes')
            achat_huile = str(data.get('Q3_Achat', '')).strip()
            freq = data.get('Q4_Frequence')
            marque = data.get('Q8_MarquePreferee')
            qte_nb = data.get('Q5_Quantite_Nombre')
            contenant = data.get('Q5_Quantite_Contenant')
            vol_unit = data.get('Q5_Quantite_VolumeUnitaire')
            prix = data.get('Q6_PrixHabituel')
            pourcent = data.get('Q7_Pourcentages')
            pret_plus = data.get('Q9_PretPayerPlus')
            prix_max = data.get('Q10_PrixMax')
            qualite = data.get('Q_Qualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = None
            supermarche_origine = data.get("Supermarché d'origine")
            commune = data.get('Commune')
        else:  # supermarche
            sexe_age = data.get('Q12_SexeAge')
            nb_pers = data.get('Q7_NbPersonnes')
            achat_huile = 'Oui'
            freq = data.get('Q6_Fréquence')
            marque = data.get('Q2_Marque')
            qte_nb = None
            contenant = None
            vol_unit = None
            vol_texte = data.get('Q4_Quantité')
            vol_total_sm = extraire_litres(vol_texte) if vol_texte else None
            prix = data.get('Q5_PrixPayé')
            pourcent = data.get('Q8_LieuxAchat')
            pret_plus = data.get('Q9_PretPayerPlus')
            prix_max = data.get('Q10_PrixMax')
            qualite = data.get('Q11_ReconnaitreQualite')
            rc_conn = data.get('Q_RC_Connaissance')
            rc_qual = data.get('Q_RC_Qualités')
            raison = data.get('Q3_Raison')
            supermarche_origine = data.get('Supermarché')
            commune = data.get('Commune')
        unified = {
            'uuid': row['uuid'],
            'date': row['date'],
            'enqueteur': row['enqueteur'],
            'categorie': cat,
            'type_original': qtype,
            'sexe_age': sexe_age,
            'nb_personnes': nb_pers,
            'achat_huile': achat_huile,
            'frequence': freq,
            'marque_preferee': marque,
            'quantite_nombre': qte_nb,
            'contenant': contenant,
            'volume_unitaire_l': vol_unit,
            'prix_paye': prix,
            'pourcentages_achat': pourcent,
            'pret_payer_plus': pret_plus,
            'prix_max': prix_max,
            'qualite': qualite,
            'rc_connaissance': rc_conn,
            'rc_qualites': rc_qual,
            'raison_choix': raison,
            'commune': commune,
            'supermarche_origine': supermarche_origine,
            'volume_total_l_supermarche': vol_total_sm if qtype == 'supermarche' else None,
        }
        rows_unified.append(unified)
    df_menage_unifie = pd.DataFrame(rows_unified)
    if df_menage_unifie.empty:
        return df_menage_unifie
    df_menage_unifie['quantite_nombre'] = pd.to_numeric(
        df_menage_unifie['quantite_nombre'].astype(str).str.replace(',', '.'), errors='coerce')
    df_menage_unifie['quantite_nombre'] = df_menage_unifie['quantite_nombre'].replace(0, 1)
    df_menage_unifie['volume_unitaire_l'] = pd.to_numeric(
        df_menage_unifie['volume_unitaire_l'].astype(str).str.replace(',', '.'), errors='coerce')
    seuil_ml = 50
    mask_ml = df_menage_unifie['volume_unitaire_l'] > seuil_ml
    df_menage_unifie.loc[mask_ml, 'volume_unitaire_l'] /= 1000
    mask_pur_sm = df_menage_unifie['type_original'].isin(['menage', 'supermarche_menage'])
    df_menage_unifie['volume_total_l'] = np.nan
    if mask_pur_sm.any():
        nb = df_menage_unifie.loc[mask_pur_sm, 'quantite_nombre']
        vol_unit = df_menage_unifie.loc[mask_pur_sm, 'volume_unitaire_l']
        df_menage_unifie.loc[mask_pur_sm, 'volume_total_l'] = nb * vol_unit
    mask_s = df_menage_unifie['type_original'] == 'supermarche'
    if mask_s.any():
        df_menage_unifie.loc[mask_s, 'volume_total_l'] = df_menage_unifie.loc[mask_s, 'volume_total_l_supermarche']
    df_menage_unifie['prix_num'] = pd.to_numeric(
        df_menage_unifie['prix_paye'].astype(str).str.replace(',', '.'), errors='coerce')
    df_menage_unifie['prix_litre'] = np.where(
        (df_menage_unifie['volume_total_l'].notna()) & (df_menage_unifie['volume_total_l'] > 0) & (df_menage_unifie['prix_num'].notna()),
        df_menage_unifie['prix_num'] / df_menage_unifie['volume_total_l'],
        np.nan
    )
    df_menage_unifie['prix_litre'] = df_menage_unifie['prix_litre'].replace([np.inf, -np.inf], np.nan)
    df_menage_unifie['taille_menage'] = pd.to_numeric(df_menage_unifie['nb_personnes'], errors='coerce')
    df_menage_unifie['marque_clean'] = apply_brand_mapping_strict(df_menage_unifie['marque_preferee'])
    mask_sm_menage = df_menage_unifie['type_original'] == 'supermarche_menage'
    df_menage_unifie.loc[mask_sm_menage & (df_menage_unifie['marque_clean'] == 'mbila'), 'marque_clean'] = 'En vrac'
    def pret_plus_val(texte):
        if not isinstance(texte, str):
            return False
        crit_list = parse_criteres_smart(texte)
        for c in crit_list:
            if any(mot in c.lower() for mot in ['non', 'pas prêt', 'ne suis pas prêt', 'aucun']):
                return False
        return len(crit_list) > 0
    df_menage_unifie['pret_plus'] = df_menage_unifie['pret_payer_plus'].apply(pret_plus_val)
    df_menage_unifie['criteres'] = df_menage_unifie['pret_payer_plus'].apply(parse_criteres_smart)
    freq_map = {
        'Plusieurs fois par semaine': 8,
        'Une fois par semaine': 4,
        'Deux à trois fois par mois': 2.5,
        'Une fois par mois': 1,
        'Une fois par trimestre': 0.33,
        'Moins souvent': 0.166
    }
    df_menage_unifie['frequence'] = df_menage_unifie['frequence'].astype(str).str.strip()
    df_menage_unifie.loc[df_menage_unifie['frequence'].str.match(r'^\d+(\.\d+)?$'), 'frequence'] = np.nan
    df_menage_unifie['freq_num'] = df_menage_unifie['frequence'].map(freq_map)
    sm_niveau = dict(zip(df_sm['Nom'].apply(normalize_name), df_sm['Niveau_socio'])) if not df_sm.empty else {}
    def zone_via_magasin(origine):
        if not isinstance(origine, str) or origine.strip() == '':
            return None
        key = normalize_name(origine)
        if key in sm_niveau and sm_niveau[key] and sm_niveau[key] != 'Non renseigné':
            return sm_niveau[key]
        best_score, best_val = 0, None
        for k, v in sm_niveau.items():
            score = SequenceMatcher(None, key, k).ratio()
            if score > best_score and score >= 0.8:
                best_score, best_val = score, v
        return best_val
    mask_s_sm = df_menage_unifie['type_original'].isin(['supermarche', 'supermarche_menage'])
    df_menage_unifie['zone_socioeco'] = ''
    if mask_s_sm.any():
        df_menage_unifie.loc[mask_s_sm, 'zone_socioeco'] = df_menage_unifie.loc[mask_s_sm, 'supermarche_origine'].apply(zone_via_magasin)
    mask_m = df_menage_unifie['type_original'] == 'menage'
    if mask_m.any():
        commune_niveau_norm = {normalize_name(k): v for k, v in commune_niveau.items()}
        def zone_from_commune(commune):
            if not isinstance(commune, str) or commune.strip() == '':
                return 'Inconnu'
            return commune_niveau_norm.get(normalize_name(commune), 'Non classé')
        df_menage_unifie.loc[mask_m, 'zone_socioeco'] = df_menage_unifie.loc[mask_m, 'commune'].apply(zone_from_commune)
    df_menage_unifie['zone_socioeco'] = df_menage_unifie['zone_socioeco'].replace('', 'Inconnu').fillna('Inconnu')
    if 'statut' in df_menage_unifie.columns:
        df_menage_unifie = df_menage_unifie[df_menage_unifie['statut'] != 'Refus'].copy()
    return make_hashable(df_menage_unifie)


st.header("🏠 Questionnaires Ménage")
if not df_q_f_raw.empty:
    df_raw_clean = make_hashable(df_q_f_raw)
    df_sm_clean = make_hashable(df_sm)
    df_menage_unifie = prepare_menage_unifie(df_raw_clean, df_sm_clean, load_commune_niveau())
    df_menage_unifie = make_hashable(df_menage_unifie)
else:
    df_menage_unifie = pd.DataFrame()

if df_menage_unifie.empty:
    st.info("Aucune donnée ménage disponible pour la période et l'enquêteur sélectionnés.")
else:
    cat_options = {
        "Tous": "Tous",
        "1. Acheteurs supermarché": "Acheteur supermarché",
        "2. Non-acheteurs supermarché": "Non-acheteur supermarché",
        "3. Ménages purs": "Ménage pur"
    }
    cat_label = st.selectbox("Catégorie de questionnaire", list(cat_options.keys()), index=0)
    cat_value = cat_options[cat_label]
    df_m = df_menage_unifie.copy()
    if cat_value != "Tous":
        df_m = df_m[df_m['categorie'] == cat_value]

    def get_sexe_menage(x):
        if not isinstance(x, str): return None
        parts = x.split('-')
        if len(parts) >= 1:
            sexe = parts[0].strip().upper()
            if sexe in ['F', 'H']: return sexe
        return None

    def get_age_menage(x):
        if not isinstance(x, str): return None
        match = re.search(r'(\d+[-+]*\d*\s*ans?)', x)
        return match.group(1) if match else None

    df_m['Sexe'] = df_m['sexe_age'].apply(get_sexe_menage)
    df_m['Âge'] = df_m['sexe_age'].apply(get_age_menage)
    df_m['Tranche_age'] = df_m['Âge'].apply(tranche_age)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        communes_disponibles = sorted(df_m['commune'].dropna().unique())
        commune_sel = st.selectbox("Commune", ["Tous"] + communes_disponibles, key="menage_commune")
    with col_f2:
        sexe_menage_sel = st.selectbox("Sexe", ["Tous", "F", "H"], key="menage_sexe")
    with col_f3:
        age_menage_sel = st.selectbox("Âge", ["Tous", "Moins de 25 ans", "25-34 ans", "35-49 ans", "50 ans et plus"], key="menage_age")

    if commune_sel != "Tous":
        df_m = df_m[df_m['commune'] == commune_sel]
    if sexe_menage_sel != "Tous":
        df_m = df_m[df_m['Sexe'] == sexe_menage_sel]
    if age_menage_sel != "Tous":
        df_m = df_m[df_m['Tranche_age'] == age_menage_sel]

    if df_m.empty:
        st.info("Aucune donnée après filtrage.")
    else:
        nb_total = len(df_m)
        seuil_taille = 20
        seuil_volume = 50
        taille_valide = df_m['taille_menage'].notna() & (df_m['taille_menage'] > 0) & (df_m['taille_menage'] <= seuil_taille)
        volume_valide = df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= seuil_volume)
        acheteurs_vol_valide = (df_m['achat_huile'].str.lower() == 'oui') & volume_valide
        nb_taille = taille_valide.sum()
        nb_taille_exclus = df_m['taille_menage'].notna().sum() - nb_taille
        nb_volume = volume_valide.sum()
        nb_prix_l = df_m['prix_litre'].notna().sum()
        nb_freq = df_m.loc[df_m['achat_huile'].str.lower() == 'oui', 'frequence'].notna().sum()
        nb_marque = df_m['marque_clean'].notna().sum()
        nb_qual = df_m['qualite'].notna().sum()
        nb_rc_conn = df_m['rc_connaissance'].notna().sum()
        nb_rc_qual = df_m['rc_qualites'].notna().sum()
        nb_consent = df_m['pret_payer_plus'].notna().sum()
        nb_pourcent = df_m['pourcentages_achat'].notna().sum()

        with st.expander("📋 Récapitulatif des effectifs par section", expanded=True):
            recap = pd.DataFrame({
                "Section": [
                    "Total questionnaires affichés",
                    "Distribution taille ménage (≤20 pers.)",
                    "Volume acheté / Prix au litre",
                    "Fréquence d'achat (acheteurs)",
                    "Marque (préférée ou achetée)",
                    "Perception qualité",
                    "Notoriété RougeCongo (connaissance)",
                    "Qualités RougeCongo",
                    "Consentement à payer plus",
                    "Lieux d'achat / Pourcentages"
                ],
                "Nombre de réponses": [
                    nb_total, nb_taille, nb_volume, nb_freq, nb_marque,
                    nb_qual, nb_rc_conn, nb_rc_qual, nb_consent, nb_pourcent
                ]
            })
            st.dataframe(recap, width='stretch', hide_index=True)
            if nb_taille_exclus > 0:
                st.caption(f"⚠️ {nb_taille_exclus} ménages exclus de la distribution de taille (taille ≤ 0 ou > {seuil_taille} pers.).")
            st.write("**Répartition par catégorie :**")
            st.write(df_m['categorie'].value_counts().to_dict())

        st.divider()
        st.subheader("📊 Synthèse")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Questionnaires", nb_total)
        taille_moy = df_m.loc[taille_valide, 'taille_menage'].mean()
        c2.metric("Taille moyenne du ménage", f"{taille_moy:.1f} pers.",
                  help=f"Calculée sur {nb_taille} ménages valides")
        vol_moy = df_m.loc[(df_m['achat_huile'].str.lower() == 'oui') & volume_valide, 'volume_total_l'].mean()
        c3.metric("Volume moyen acheté", f"{fmt_volume(vol_moy,2)} L",
                  help=f"Moyenne sur {acheteurs_vol_valide.sum()} acheteurs avec volume ≤ {seuil_volume} L")
        prix_moy = df_m.loc[df_m['prix_litre'].notna(), 'prix_litre'].mean()
        devise_aff = st.session_state.get("devise_globale", "FC")
        if pd.isna(prix_moy):
            c4.metric("Prix moyen au litre", "N/A")
        else:
            c4.metric("Prix moyen au litre", fmt_prix(prix_moy, devise_aff))
        nb_acheteurs = (df_m['achat_huile'].str.lower() == 'oui').sum()
        pct_acheteurs = (nb_acheteurs / nb_total * 100) if nb_total > 0 else 0
        c5.metric("% Acheteurs d'huile", f"{pct_acheteurs:.1f}%")
        freq_mode = df_m.loc[df_m['achat_huile'].str.lower() == 'oui', 'frequence'].mode()
        freq_mode_str = freq_mode.iloc[0] if not freq_mode.empty else "N/A"
        st.caption(f"Fréquence la plus citée (acheteurs) : {freq_mode_str}")

        st.subheader("👥 Profil des ménages")
        col_a, col_b = st.columns(2)
        with col_a:
            data_taille = df_m.loc[taille_valide, 'taille_menage']
            fig_taille = px.histogram(data_taille, x='taille_menage', nbins=20,
                                      histnorm='percent',
                                      labels={'taille_menage': 'Nombre de personnes', 'percent': 'Pourcentage des ménages (%)'},
                                      title="Distribution de la taille des ménages")
            fig_taille.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
            fig_taille.update_traces(textfont=dict(size=12))
            fig_taille.update_layout(template="gilroy_export")
            plotly_chart_with_local_export(
                fig_taille,
                caption=f"Basé sur {nb_taille} ménages valides (exclusion de {nb_taille_exclus} ménages non valides).",
                key="menage_taille"
            )

        with col_b:
            zone_counts = df_m['zone_socioeco'].value_counts()
            zone_pct = zone_counts / zone_counts.sum() * 100
            zone_df = zone_pct.reset_index()
            zone_df.columns = ['Zone socioéconomique', 'Pourcentage']
            zone_df = zone_df[zone_df['Zone socioéconomique'] != 'Inconnu']
            nb_inconnus_zone = len(df_m[df_m['zone_socioeco'] == 'Inconnu'])
            ordre = ['Aisé', 'Moyen', 'Populaire', 'Non classé']
            zone_df['ordre'] = zone_df['Zone socioéconomique'].apply(
                lambda x: ordre.index(x) if x in ordre else 99)
            zone_df = zone_df.sort_values('ordre')
            fig_zone = px.bar(zone_df, x='Zone socioéconomique', y='Pourcentage',
                              color='Zone socioéconomique',
                              labels={'Zone socioéconomique': 'Zone', 'Pourcentage': 'Pourcentage des ménages (%)'},
                              title="Ménages interrogés par zone socioéconomique",
                              color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_zone.update_traces(texttemplate='%{y:.1f}%', textposition='outside')
            fig_zone.update_traces(textfont=dict(size=12))
            fig_zone.update_layout(showlegend=False, template="gilroy_export")
            total_menages = zone_counts[zone_counts.index != 'Inconnu'].sum()
            plotly_chart_with_local_export(
                fig_zone,
                caption=f"Basé sur {total_menages} ménages (exclusion de {nb_inconnus_zone} ménages 'Inconnu').",
                key="menage_zone"
            )

        st.subheader("📏 Taille moyenne du ménage par zone socioéconomique")
        df_tz = df_m[taille_valide & (df_m['zone_socioeco'] != 'Inconnu')]
        taille_zone = df_tz.groupby('zone_socioeco')['taille_menage'].mean().reset_index()
        taille_zone.columns = ['Zone socioéconomique', 'Taille moyenne']
        taille_zone['ordre'] = taille_zone['Zone socioéconomique'].apply(
            lambda x: ordre.index(x) if x in ordre else 99)
        taille_zone = taille_zone.sort_values('ordre')
        fig_tz = px.bar(taille_zone, x='Zone socioéconomique', y='Taille moyenne',
                        text='Taille moyenne', color='Zone socioéconomique',
                        labels={'Zone socioéconomique': 'Zone', 'Taille moyenne': 'Taille moyenne (personnes)'},
                        color_discrete_sequence=px.colors.qualitative.Pastel)
        fig_tz.update_traces(texttemplate='%{text:.1f} pers.', textposition='outside')
        fig_tz.update_traces(textfont=dict(size=12))
        fig_tz.update_layout(showlegend=False, yaxis_title="Personnes", template="gilroy_export")
        plotly_chart_with_local_export(
            fig_tz,
            caption=f"Basé sur {len(df_tz)} ménages valides avec zone connue.",
            key="menage_taille_zone"
        )

        st.subheader("📍 Habitudes d'achat par commune")
        if 'commune' in df_m.columns and df_m['commune'].notna().any():
            communes_counts = df_m['commune'].value_counts()
            communes_ok = communes_counts[communes_counts >= 5].index.tolist()
            if communes_ok:
                df_commune = df_m[df_m['commune'].isin(communes_ok)].copy()
                acheteurs_mask = df_commune['achat_huile'].str.lower() == 'oui'
                df_vol_commune = df_commune[acheteurs_mask & df_commune['volume_total_l'].notna()].copy()
                if not df_vol_commune.empty:
                    vol_moy = df_vol_commune.groupby('commune')['volume_total_l'].mean().reset_index()
                    vol_moy.columns = ['Commune', 'Volume moyen (L)']
                    fig_vol = px.bar(vol_moy, x='Commune', y='Volume moyen (L)',
                                    title="Volume moyen acheté par commune (acheteurs)",
                                    labels={'Commune': 'Commune', 'Volume moyen (L)': 'Litres'},
                                    text='Volume moyen (L)')
                    fig_vol.update_traces(texttemplate='%{text:.1f} L', textposition='outside')
                    fig_vol.update_traces(textfont=dict(size=12))
                    fig_vol.update_layout(template="gilroy_export")
                    plotly_chart_with_local_export(
                        fig_vol,
                        caption=f"Basé sur {len(df_vol_commune)} acheteurs. Seules les communes avec ≥5 répondants sont affichées.",
                        key="menage_vol_commune"
                    )
                else:
                    st.info("Pas assez de données de volume par commune.")
                df_freq_commune = df_commune[acheteurs_mask & df_commune['frequence'].notna()].copy()
                if not df_freq_commune.empty:
                    freq_cross = pd.crosstab(df_freq_commune['commune'], df_freq_commune['frequence'])
                    freq_pct = freq_cross.div(freq_cross.sum(axis=1), axis=0) * 100
                    freq_pct = freq_pct.reset_index().melt(id_vars='commune', var_name='Fréquence', value_name='Pourcentage')
                    fig_freq = px.bar(freq_pct, x='commune', y='Pourcentage', color='Fréquence',
                                    title="Répartition des fréquences d'achat par commune (acheteurs)",
                                    labels={'commune': 'Commune', 'Pourcentage': 'Pourcentage des acheteurs (%)'},
                                    barmode='stack', text_auto='.1f')
                    fig_freq.update_traces(textfont=dict(size=12))
                    fig_freq.update_layout(template="gilroy_export")
                    plotly_chart_with_local_export(
                        fig_freq,
                        caption=f"Basé sur {len(df_freq_commune)} acheteurs. Les pourcentages sont calculés par commune.",
                        key="menage_freq_commune"
                    )
                else:
                    st.info("Pas assez de données de fréquence par commune.")
                mask_pct = df_commune['type_original'].isin(['menage', 'supermarche_menage'])
                df_pct_commune = df_commune[mask_pct & df_commune['pourcentages_achat'].notna()].copy()
                if not df_pct_commune.empty:
                    records = []
                    for _, row in df_pct_commune.iterrows():
                        commune = row['commune']
                        texte = row['pourcentages_achat']
                        if not isinstance(texte, str):
                            continue
                        for part in texte.split(','):
                            part = part.strip()
                            if ':' not in part:
                                continue
                            cat, pct_str = part.split(':', 1)
                            pct = pd.to_numeric(pct_str.strip().replace('%', ''), errors='coerce')
                            if pd.notna(pct):
                                records.append({'Commune': commune, 'Catégorie': cat.strip(), 'Pourcentage': pct})
                    if records:
                        df_lieux_comm = pd.DataFrame(records)
                        lieu_moy = df_lieux_comm.groupby(['Commune', 'Catégorie'])['Pourcentage'].mean().reset_index()
                        fig_lieu = px.bar(lieu_moy, x='Commune', y='Pourcentage', color='Catégorie',
                                        title="Part moyenne des canaux d'achat par commune",
                                        labels={'Commune': 'Commune', 'Pourcentage': 'Part moyenne (%)'},
                                        barmode='stack', text_auto='.1f')
                        fig_lieu.update_traces(textfont=dict(size=12))
                        fig_lieu.update_layout(template="gilroy_export")
                        plotly_chart_with_local_export(
                            fig_lieu,
                            caption=f"Basé sur {len(df_pct_commune)} répondants. Les pourcentages sont des moyennes par répondant.",
                            key="menage_lieu_commune"
                        )
                    else:
                        st.info("Données de lieux d'achat non exploitables.")
                else:
                    st.info("Pas assez de données de lieux d'achat par commune.")
            else:
                st.info("Aucune commune avec suffisamment de répondants (≥5) pour afficher des graphiques.")
        else:
            st.info("La colonne 'commune' est absente ou vide dans les données.")

        st.subheader("🛒 Volume et fréquence d'achat")
        col1, col2 = st.columns(2)
        with col1:
            df_vol = df_m[df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= seuil_volume)].copy()
            if not df_vol.empty:
                def categorize_volume(v):
                    if v < 1: return '< 1 L'
                    if v in [1, 2, 2.5, 3, 4, 5, 10]: return f'{v} L'
                    if v > 10: return '> 10 L'
                    return 'Autres'
                df_vol['volume_label'] = df_vol['volume_total_l'].apply(categorize_volume)
                vol_counts = df_vol['volume_label'].value_counts().reset_index()
                vol_counts.columns = ['Volume', 'Nombre']
                ordre_vol = ['< 1 L', '1 L', '2 L', '2.5 L', '3 L', '4 L', '5 L', '10 L', '> 10 L', 'Autres']
                vol_counts['Volume'] = pd.Categorical(vol_counts['Volume'], categories=ordre_vol, ordered=True)
                vol_counts = vol_counts.sort_values('Volume')
                fig_vol = px.bar(vol_counts, x='Volume', y='Nombre',
                                 labels={'Volume': 'Volume acheté', 'Nombre': "Nombre d'acheteurs"},
                                 title="Distribution des volumes achetés")
                fig_vol.update_traces(texttemplate='%{y}', textposition='outside', textfont=dict(size=12))
                fig_vol.update_layout(template="gilroy_export")
                plotly_chart_with_local_export(
                    fig_vol,
                    caption=f"Basé sur {len(df_vol)} répondants avec un volume valide (≤ {seuil_volume} L).",
                    key="menage_vol_dist"
                )
            else:
                st.info("Aucun volume valide.")
        with col2:
            freq_df = df_m[df_m['achat_huile'].str.lower() == 'oui'].dropna(subset=['frequence'])
            if not freq_df.empty:
                freq_counts = freq_df['frequence'].value_counts()
                freq_pct = freq_counts / freq_counts.sum() * 100
                freq_df_plot = freq_pct.reset_index()
                freq_df_plot.columns = ['Fréquence', 'Pourcentage']
                fig_freq = px.pie(freq_df_plot, values='Pourcentage', names='Fréquence',
                                  title="Fréquence d'achat (acheteurs)")
                fig_freq.update_traces(textinfo='percent+label', textfont=dict(size=12))
                fig_freq.update_layout(template="gilroy_export")
                plotly_chart_with_local_export(
                    fig_freq,
                    caption=f"Basé sur {len(freq_df)} acheteurs.",
                    key="menage_freq_pie"
                )
            else:
                st.info("Aucune fréquence renseignée pour les acheteurs.")

        st.subheader("🏷️ Marque (préférée ou achetée)")
        marque_serie = df_m['marque_clean'].dropna()
        top8_marques_men = marque_serie.value_counts().head(8).index.tolist()
        marque_counts = marque_serie.value_counts()
        marque_pct = marque_counts / len(df_m) * 100
        marque_df = marque_pct.reset_index()
        marque_df.columns = ['Marque', 'Pourcentage']
        top8_df = marque_df[marque_df['Marque'].isin(top8_marques_men)]
        autres_pct = marque_df[~marque_df['Marque'].isin(top8_marques_men)]['Pourcentage'].sum()
        if autres_pct > 0:
            top8_df = pd.concat([top8_df, pd.DataFrame({'Marque': ['Autres'], 'Pourcentage': [autres_pct]})], ignore_index=True)
        top8_df['ordre'] = top8_df['Marque'].apply(lambda x: 0 if x != 'Autres' else 1)
        top8_df = top8_df.sort_values('ordre').drop(columns=['ordre'])
        if not top8_df.empty:
            fig_marque = px.pie(top8_df, values='Pourcentage', names='Marque',
                                title="Répartition des marques (top 8 + Autres)")
            fig_marque.update_traces(textinfo='percent+label', sort=False, textfont=dict(size=12))
            fig_marque.update_layout(template="gilroy_export")
            plotly_chart_with_local_export(
                fig_marque,
                caption=f"Basé sur {marque_serie.notna().sum()} réponses avec marque reconnue. Pourcentage calculé sur l'ensemble des répondants ({len(df_m)}).",
                key="menage_marque"
            )
        else:
            st.info("Aucune marque.")
        with st.expander("🔍 Inspecter les marques brutes pour une marque sélectionnée"):
            marque_choisie = st.selectbox("Choisir une marque (clean)", top8_marques_men if top8_marques_men else [""])
            if marque_choisie:
                sub_inspect = df_m[df_m['marque_clean'] == marque_choisie][['uuid', 'type_original', 'marque_preferee', 'marque_clean']]
                st.dataframe(sub_inspect, width='stretch')

        st.subheader("💲 Prix au litre")
        seuil_prix_affichage = 10000
        prix_plot = df_m[(df_m['prix_litre'].notna()) & (df_m['prix_litre'] <= seuil_prix_affichage)]
        nb_exclus_prix = df_m['prix_litre'].notna().sum() - len(prix_plot)
        if not prix_plot.empty:
            fig_prix = px.box(prix_plot, y='prix_litre',
                              labels={'prix_litre': f'Prix au litre ({devise_aff})'},
                              title="Distribution du prix au litre")
            if devise_aff == "FC":
                fig_prix.update_yaxes(tickformat=",.0f", ticksuffix=" FC")
            else:
                fig_prix.update_yaxes(tickformat=",.2f", tickprefix="$ ")
            fig_prix.update_layout(template="gilroy_export")
            plotly_chart_with_local_export(
                fig_prix,
                caption=f"Basé sur {len(prix_plot)} réponses (≤ {fmt_nombre(seuil_prix_affichage,0)} FC/L). {nb_exclus_prix} valeurs extrêmes exclues.",
                key="menage_prix_box"
            )
        else:
            st.info("Aucune valeur de prix au litre disponible.")

        st.subheader("💵 Consentement à payer plus cher")
        if nb_consent > 0:
            pret_oui = df_m['pret_plus'].sum()
            tx = pret_oui / nb_consent * 100 if nb_consent else 0
            st.metric("Prêts à payer plus", f"{tx:.1f}% ({int(pret_oui)}/{nb_consent})")
            if pret_oui > 0:
                crits = df_m[df_m['pret_plus']]['criteres'].explode().dropna()
                crits = crits[~crits.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                crit_counts = crits.value_counts()
                crit_pct = crit_counts / pret_oui * 100
                crit_df = crit_pct.reset_index()
                crit_df.columns = ['Critère', 'Pourcentage']
                top_crit = crit_df.head(8)
                autres_crit = crit_df.iloc[8:]['Pourcentage'].sum()
                if autres_crit > 0:
                    top_crit = pd.concat([top_crit, pd.DataFrame({'Critère': ['Autres'], 'Pourcentage': [autres_crit]})], ignore_index=True)
                top_crit['ordre'] = top_crit['Critère'].apply(lambda x: 0 if x != 'Autres' else 1)
                top_crit = top_crit.sort_values('ordre').drop(columns=['ordre'])
                fig_crit = px.bar(top_crit, x='Critère', y='Pourcentage',
                                  labels={'Critère': 'Critère', 'Pourcentage': 'Pourcentage des prêts à payer plus (%)'},
                                  title="Critères pour payer plus cher (top 8)")
                fig_crit.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
                fig_crit.update_layout(template="gilroy_export")
                plotly_chart_with_local_export(
                    fig_crit,
                    caption=f"Basé sur {pret_oui} répondants prêts à payer plus. Un répondant peut citer plusieurs critères.",
                    key="menage_crit_consent"
                )
                df_pret = df_m[df_m['pret_plus']].dropna(subset=['prix_num', 'prix_max']).copy()
                if not df_pret.empty:
                    df_pret['ecart_rel'] = (pd.to_numeric(df_pret['prix_max'], errors='coerce') /
                                            pd.to_numeric(df_pret['prix_num'], errors='coerce') - 1) * 100
                    df_pret = df_pret[df_pret['ecart_rel'].notna() & (df_pret['ecart_rel'].abs() < 1000)]
                    exploded = df_pret.explode('criteres')
                    exploded = exploded[~exploded['criteres'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    if not exploded.empty:
                        ecart_crit = exploded.groupby('criteres')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_crit.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                        ecart_crit['Écart moyen (%)'] = ecart_crit['Écart moyen (%)'].round(1)
                        top_ecart = ecart_crit.sort_values('Nb répondants', ascending=False).head(8)
                        autres_ecart = ecart_crit.iloc[8:].copy()
                        if not autres_ecart.empty:
                            autres_row = pd.DataFrame({
                                'Critère': ['Autres'],
                                'Écart moyen (%)': [autres_ecart['Écart moyen (%)'].mean()],
                                'Nb répondants': [autres_ecart['Nb répondants'].sum()]
                            })
                            top_ecart = pd.concat([top_ecart, autres_row], ignore_index=True)
                        top_ecart['ordre'] = top_ecart['Critère'].apply(lambda x: 0 if x != 'Autres' else 1)
                        top_ecart = top_ecart.sort_values('ordre').drop(columns=['ordre'])
                        fig_ecart = px.bar(top_ecart, x='Critère', y='Écart moyen (%)',
                                           text='Nb répondants',
                                           labels={'Critère': 'Critère', 'Écart moyen (%)': 'Écart moyen (%)'},
                                           title="% moyen que les acheteurs sont prêts à payer en plus, par critère (top 8)")
                        fig_ecart.update_traces(texttemplate='%{text}', textposition='outside', textfont=dict(size=12))
                        fig_ecart.update_layout(template="gilroy_export")
                        plotly_chart_with_local_export(
                            fig_ecart,
                            caption=f"Basé sur {len(df_pret)} répondants prêts à payer plus avec données de prix valides.",
                            key="menage_ecart_consent"
                        )
                else:
                    st.info("Données insuffisantes pour le calcul de l'écart.")
            else:
                st.info("Aucun répondant prêt à payer plus.")
        else:
            st.info("Données non disponibles.")

        st.subheader("🧪 Perception de la qualité")
        if nb_qual > 0:
            qual_ser = df_m['qualite'].dropna().astype(str).str.split(',').explode().str.strip()
            qual_ser = qual_ser[qual_ser != '']
            qual_ser = qual_ser.apply(lambda x: x.split(':',1)[1].strip() if x.lower().startswith('autre:') else x)
            qual_counts = qual_ser.value_counts()
            qual_pct = qual_counts / nb_qual * 100
            qual_df = qual_pct.reset_index()
            qual_df.columns = ['Critère', 'Pourcentage']
            qual_df['groupe'] = qual_df['Pourcentage'].apply(lambda x: 'Autres' if x < 1 else x)
            qual_df_main = qual_df[qual_df['groupe'] != 'Autres'].copy()
            autres_pct_qual = qual_df[qual_df['groupe'] == 'Autres']['Pourcentage'].sum()
            if autres_pct_qual > 0:
                qual_df_main = pd.concat([qual_df_main, pd.DataFrame({'Critère': ['Autres'], 'Pourcentage': [autres_pct_qual]})], ignore_index=True)
            qual_df_main['ordre'] = qual_df_main['Critère'].apply(lambda x: 0 if x != 'Autres' else 1)
            qual_df_main = qual_df_main.sort_values('ordre').drop(columns=['ordre'])
            if not qual_df_main.empty:
                fig_qual = px.bar(qual_df_main, x='Critère', y='Pourcentage',
                                  labels={'Critère': 'Critère', 'Pourcentage': 'Pourcentage des répondants (%)'},
                                  title="Critères de reconnaissance de la qualité de l'huile")
                fig_qual.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
                fig_qual.update_layout(template="gilroy_export")
                plotly_chart_with_local_export(
                    fig_qual,
                    caption=f"Basé sur {nb_qual} répondants ayant répondu à la question. Les critères à moins de 1% sont regroupés dans 'Autres'.",
                    key="menage_qualite"
                )
            else:
                st.info("Aucun critère.")
        else:
            st.info("Aucune réponse.")

        st.subheader("📣 Notoriété de RougeCongo")
        col_c, col_q = st.columns(2)
        with col_c:
            if nb_rc_conn > 0:
                conn = df_m['rc_connaissance'].dropna().loc[lambda x: x != '']
                conn_counts = conn.value_counts()
                # CORRECTION: pourcentage calculé sur les répondants à cette question (et non total)
                conn_pct = conn_counts / conn_counts.sum() * 100
                conn_df = conn_pct.reset_index()
                conn_df.columns = ['Réponse', 'Pourcentage']
                if not conn_df.empty:
                    fig_conn = px.bar(conn_df, x='Réponse', y='Pourcentage',
                                      labels={'Réponse': 'Réponse', 'Pourcentage': 'Pourcentage des répondants à la question (%)'},
                                      title="Connaissance de RougeCongo (parmi ceux qui ont répondu)")
                    fig_conn.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
                    fig_conn.update_layout(template="gilroy_export")
                    plotly_chart_with_local_export(
                        fig_conn,
                        caption=f"Basé sur {nb_rc_conn} répondants ayant répondu à la question.",
                        key="menage_rc_conn"
                    )
                else:
                    st.info("Aucune réponse valide.")
            else:
                st.info("Aucune donnée.")
        with col_q:
            if nb_rc_qual > 0:
                # CORRECTION: on filtre d'abord ceux qui connaissent (oui) puis on calcule les % sur ce sous-groupe
                df_rc_connus = df_m[df_m['rc_connaissance'].astype(str).str.lower().str.contains('oui')]
                qual_rc = df_rc_connus['rc_qualites'].dropna().astype(str).str.split(',').explode().str.strip()
                qual_rc = qual_rc[qual_rc != '']
                qual_rc = qual_rc.apply(lambda x: x.split(':',1)[1].strip() if x.lower().startswith('autre:') else x)
                qc = qual_rc.value_counts()
                # Pourcentage sur le nombre de répondants qui connaissent ET ont répondu à la question
                qc_pct = qc / len(df_rc_connus) * 100
                qc_df = qc_pct.reset_index()
                qc_df.columns = ['Qualité', 'Pourcentage']
                qc_df['groupe'] = qc_df['Pourcentage'].apply(lambda x: 'Autres' if x < 1 else x)
                qc_df_main = qc_df[qc_df['groupe'] != 'Autres'].copy()
                autres_pct_qc = qc_df[qc_df['groupe'] == 'Autres']['Pourcentage'].sum()
                if autres_pct_qc > 0:
                    qc_df_main = pd.concat([qc_df_main, pd.DataFrame({'Qualité': ['Autres'], 'Pourcentage': [autres_pct_qc]})], ignore_index=True)
                qc_df_main['ordre'] = qc_df_main['Qualité'].apply(lambda x: 0 if x != 'Autres' else 1)
                qc_df_main = qc_df_main.sort_values('ordre').drop(columns=['ordre'])
                if not qc_df_main.empty:
                    fig_rc_qual = px.bar(qc_df_main, x='Qualité', y='Pourcentage',
                                         labels={'Qualité': 'Qualité', 'Pourcentage': 'Pourcentage des connaisseurs (%)'},
                                         title="Qualités associées à RougeCongo (parmi ceux qui connaissent)")
                    fig_rc_qual.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
                    fig_rc_qual.update_layout(template="gilroy_export")
                    plotly_chart_with_local_export(
                        fig_rc_qual,
                        caption=f"Basé sur {len(df_rc_connus)} répondants connaissant RougeCongo.",
                        key="menage_rc_qual"
                    )
                else:
                    st.info("Aucune réponse.")
            else:
                st.info("Aucune réponse.")

        st.subheader("📍 Lieux d'achat / Répartition des dépenses")
        if nb_pourcent > 0:
            mask_pct = df_m['type_original'].isin(['menage', 'supermarche_menage'])
            df_pct = df_m[mask_pct].dropna(subset=['pourcentages_achat'])
            if not df_pct.empty:
                records = []
                for _, row in df_pct.iterrows():
                    texte = row['pourcentages_achat']
                    if not isinstance(texte, str): continue
                    for part in texte.split(','):
                        part = part.strip()
                        if ':' not in part: continue
                        cat, pct_str = part.split(':', 1)
                        pct = pd.to_numeric(pct_str.strip().replace('%', ''), errors='coerce')
                        if pd.notna(pct):
                            records.append({'Catégorie': cat.strip(), 'Pourcentage': pct})
                if records:
                    df_lieux = pd.DataFrame(records)
                    df_moy = df_lieux.groupby('Catégorie')['Pourcentage'].mean().reset_index()
                    df_moy.columns = ['Catégorie', 'Pourcentage moyen']
                    fig_lieux = px.bar(df_moy, x='Catégorie', y='Pourcentage moyen',
                                       labels={'Catégorie': 'Canal d\'achat', 'Pourcentage moyen': 'Part moyenne (%)'},
                                       title="Lieu d'achat de l'huile de palme")
                    fig_lieux.update_traces(texttemplate='%{y:.1f}%', textposition='outside', textfont=dict(size=12))
                    fig_lieux.update_layout(template="gilroy_export")
                    plotly_chart_with_local_export(
                        fig_lieux,
                        caption=f"Basé sur {len(df_pct)} questionnaires. Les pourcentages sont des moyennes par répondant.",
                        key="menage_lieux"
                    )
                else:
                    st.info("Aucune répartition exploitable.")
            else:
                st.info("Aucune donnée de pourcentages.")
            if (df_m['type_original'] == 'supermarche').any():
                st.info("Les acheteurs supermarché ne sont pas inclus (question différente).")
        else:
            st.info("Aucune donnée.")

        st.download_button("📥 Télécharger les données (CSV)", df_m.to_csv(index=False), "menages.csv")