# pages/11_Export.py

"""Page Export."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import os, sys, re, json, hashlib, io, csv, textwrap
from utils import *
from analytics import *

# Données
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_p_f = st.session_state.get('df_p_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm', pd.DataFrame())
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
df_q = st.session_state.get('df_q', pd.DataFrame())
df_c = st.session_state.get('df_c', pd.DataFrame())
df_p = st.session_state.get('df_p', pd.DataFrame())
df_q_export = st.session_state.get('df_q_export', pd.DataFrame())
df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
df_profils_long = st.session_state.get('df_profils_long', pd.DataFrame())
secteur_profiles = st.session_state.get('secteur_profiles', None)
selected_mags = st.session_state.get('selected_mags', [])
date_range = st.session_state.get('date_range', (None, None))
selected_norm = {normalize_name(m): m for m in selected_mags}
selected_enqueteur = st.session_state.get('sidebar_enqueteur', 'Tous')

st.header("📤 Exportation de données")
export_type = st.radio(
    "Type d'export",
    ["Données brutes (CSV)", "Rapport de synthèse textuelle", "Tableaux de synthèse (exportables)"],
    horizontal=True
)
# ============================================================
# 1. DONNÉES BRUTES (CSV)
# ============================================================
if export_type == "Données brutes (CSV)":
    source = st.selectbox(
        "Source de données",
        [
            "Questionnaires (unifiés)",
            "Comptages",
            "Prix (application)",
            "Prix (fichier supermarchés)"
        ]
    )
    if source == "Questionnaires (unifiés)":
        if df_q_export.empty:
            st.info("Aucun questionnaire à exporter.")
        else:
            df_base = df_q_export.copy()
            available_cols = sorted(df_base.columns.tolist())
            st.subheader("Filtres optionnels")
            type_filt = st.multiselect("Type de questionnaire", df_base['type'].unique(), key="exp_type")
            if type_filt:
                df_base = df_base[df_base['type'].isin(type_filt)]
            mag_filt = st.multiselect("Magasin", df_base['magasin_officiel'].unique(), key="exp_mag")
            if mag_filt:
                df_base = df_base[df_base['magasin_officiel'].isin(mag_filt)]
            commune_filt = st.multiselect("Commune", df_base['commune'].dropna().unique(), key="exp_commune")
            if commune_filt:
                df_base = df_base[df_base['commune'].isin(commune_filt)]
            if 'statut' in df_base.columns:
                statut_filt = st.multiselect("Statut", df_base['statut'].unique(), key="exp_statut")
                if statut_filt:
                    df_base = df_base[df_base['statut'].isin(statut_filt)]
    elif source == "Comptages":
        df_base = df_c_f.copy()
        available_cols = sorted(df_base.columns.tolist())
        st.subheader("Filtres optionnels")
        lieu_filt = st.multiselect("Magasin", df_base['lieu_officiel'].unique(), key="exp_c_lieu")
        if lieu_filt:
            df_base = df_base[df_base['lieu_officiel'].isin(lieu_filt)]
    elif source == "Prix (application)":
        df_base = df_p_f.copy()
        available_cols = sorted(df_base.columns.tolist())
        st.subheader("Filtres optionnels")
        superm_filt = st.multiselect("Supermarché", df_base['supermarche'].unique(), key="exp_p_sm")
        marque_filt = st.multiselect("Marque", df_base['marque'].unique(), key="exp_p_marque")
        cond_filt = st.multiselect("Conditionnement", df_base['conditionnement'].unique(), key="exp_p_cond")
        if superm_filt:
            df_base = df_base[df_base['supermarche'].isin(superm_filt)]
        if marque_filt:
            df_base = df_base[df_base['marque'].isin(marque_filt)]
        if cond_filt:
            df_base = df_base[df_base['conditionnement'].isin(cond_filt)]
    elif source == "Prix (fichier supermarchés)":
        df_base = df_prices_ext.copy()
        available_cols = sorted(df_base.columns.tolist())
        st.subheader("Filtres optionnels")
        superm_filt = st.multiselect("Supermarché", df_base['supermarche'].unique(), key="exp_pf_sm")
        marque_filt = st.multiselect("Marque", df_base['marque'].unique(), key="exp_pf_marque")
        cond_filt = st.multiselect("Conditionnement", df_base['conditionnement'].unique(), key="exp_pf_cond")
        if superm_filt:
            df_base = df_base[df_base['supermarche'].isin(superm_filt)]
        if marque_filt:
            df_base = df_base[df_base['marque'].isin(marque_filt)]
        if cond_filt:
            df_base = df_base[df_base['conditionnement'].isin(cond_filt)]
    # Sélection des colonnes
    default_selected = available_cols.copy()
    selected_cols = st.multiselect(
        "Colonnes à exporter",
        available_cols,
        default=default_selected,
        key="exp_cols"
    )
    if not selected_cols:
        st.warning("Veuillez sélectionner au moins une colonne.")
    else:
        df_export = df_base[selected_cols]
        st.subheader("Aperçu des données")
        st.dataframe(df_export.head(100), width='stretch')
        st.caption(f"{len(df_export)} lignes au total.")
        csv_data = df_export.to_csv(index=False).encode('utf-8')
        file_name = f"export_{source.lower().replace(' ', '_')}.csv"
        st.download_button(
            label="📥 Télécharger CSV",
            data=csv_data,
            file_name=file_name,
            mime="text/csv"
        )
# ============================================================
# 2. RAPPORT DE SYNTHÈSE TEXTUELLE (inchangé)
# ============================================================
elif export_type == "Rapport de synthèse textuelle":
    st.subheader("📝 Rapport de synthèse pour IA")
    def generer_rapport():
        lignes = []
        lignes.append("# RAPPORT DE SYNTHÈSE INTERMÉDIAIRE – PROJET HUILE DE PALME ROUGE")
        lignes.append(f"Date de génération : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        lignes.append("")
        # ... (reste du rapport textuel, inchangé)
        # (Nous ne le répétons pas intégralement ici pour rester concis,
        #  conservez votre code existant pour cette partie)
        lignes.append("## 8. Notes complémentaires")
        lignes.append("- Les marges d'erreur sont données à ± demi-interquartile (bootstrap).")
        lignes.append("- Les données proviennent des fichiers de collecte et des questionnaires bruts.")
        lignes.append("- Pour toute question, contacter l'équipe de suivi.")
        return "\n".join(lignes)
    rapport = generer_rapport()
    st.text_area("Rapport généré", rapport, height=600)
    st.download_button("📥 Télécharger le rapport (.txt)", rapport, "rapport_synthese.txt")
# ============================================================
# 3. TABLEAUX DE SYNTHÈSE EXPORTABLES
# ============================================================
elif export_type == "Tableaux de synthèse (exportables)":
    st.subheader("📊 Tableaux des principaux résultats")
    st.caption("Chaque tableau peut être téléchargé individuellement en CSV.")
    # ─── 🛒 SUPERMARCHÉ ─────────────────────────
    st.markdown("### 🛒 Questionnaires Supermarché")
    if not df_supermarche_full.empty:
        df_sm_q = df_supermarche_full
        acheteurs = df_sm_q[df_sm_q['Q1'] == 'Oui']
        # Synthèse générale
        tab1 = pd.DataFrame({
            'Indicateur': ['Nb répondants', 'Nb acheteurs', 'Taux d\'achat (%)',
                           'Volume moyen (L)', 'Volume médian (L)',
                           'Prix/L moyen (FC)', 'Prix/L médian (FC)'],
            'Valeur': [len(df_sm_q), len(acheteurs), f"{len(acheteurs)/len(df_sm_q)*100:.1f}",
                       f"{acheteurs['vol_litres'].mean():.2f}" if not acheteurs.empty else "N/A",
                       f"{acheteurs['vol_litres'].median():.2f}" if not acheteurs.empty else "N/A",
                       f"{acheteurs['prix_litre'].mean():,.0f}" if not acheteurs.empty else "N/A",
                       f"{acheteurs['prix_litre'].median():,.0f}" if not acheteurs.empty else "N/A"]
        })
        st.dataframe(tab1, width='stretch')
        st.download_button("📥 Synthèse", tab1.to_csv(index=False), "sm_synthese.csv", key="dl_sm_synth")
        if not acheteurs.empty:
            # Fréquence d'achat
            freq_counts = acheteurs['Q6'].value_counts().reset_index()
            freq_counts.columns = ['Fréquence', 'Nb']
            st.markdown("**Fréquence d'achat**")
            st.dataframe(freq_counts, width='stretch')
            st.download_button("📥 Fréquence", freq_counts.to_csv(index=False), "sm_freq.csv", key="dl_sm_freq")
            # Segmentation démographique
            if 'Sexe' in acheteurs.columns and 'Tranche_age' in acheteurs.columns:
                demo_sexe = acheteurs['Sexe'].value_counts().reset_index()
                demo_sexe.columns = ['Sexe', 'Nb']
                demo_age = acheteurs['Tranche_age'].value_counts().reset_index()
                demo_age.columns = ['Âge', 'Nb']
                st.markdown("**Segmentation démographique**")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.dataframe(demo_sexe, width='stretch')
                with col_d2:
                    st.dataframe(demo_age, width='stretch')
                st.download_button("📥 Sexe", demo_sexe.to_csv(index=False), "sm_sexe.csv", key="dl_sm_sexe")
                st.download_button("📥 Âge", demo_age.to_csv(index=False), "sm_age.csv", key="dl_sm_age")
            # Marques (top 10 avec volume moyen)
            marque_vol = acheteurs.groupby('marque_clean').agg(
                nb=('marque_clean', 'count'),
                vol_moy=('vol_litres', 'mean')
            ).reset_index()
            marque_vol.columns = ['Marque', 'Nb acheteurs', 'Volume moyen (L)']
            marque_vol = marque_vol.sort_values('Nb acheteurs', ascending=False).head(10)
            marque_vol['Volume moyen (L)'] = marque_vol['Volume moyen (L)'].round(2)
            st.markdown("**Top 10 marques (avec volume moyen)**")
            st.dataframe(marque_vol, width='stretch')
            st.download_button("📥 Marques + volume", marque_vol.to_csv(index=False), "sm_marques_vol.csv", key="dl_sm_marques_vol")
            # Raisons de choix de marque (top 10)
            if 'Q3' in acheteurs.columns:
                raisons = acheteurs['Q3'].dropna().str.split(',').explode().str.strip()
                raisons_counts = raisons.value_counts().head(10).reset_index()
                raisons_counts.columns = ['Raison', 'Nb']
                st.markdown("**Top 10 raisons de choix de marque**")
                st.dataframe(raisons_counts, width='stretch')
                st.download_button("📥 Raisons", raisons_counts.to_csv(index=False), "sm_raisons.csv", key="dl_sm_raisons")
            # Consentement à payer plus cher (taux et critères)
            if 'pret_plus' in acheteurs.columns:
                pret_oui = acheteurs['pret_plus'].sum()
                taux_pret = pret_oui / len(acheteurs) * 100
                tab_consent = pd.DataFrame({
                    'Indicateur': ['Prêts à payer plus', 'Taux (%)'],
                    'Valeur': [f"{pret_oui}/{len(acheteurs)}", f"{taux_pret:.1f}"]
                })
                st.markdown("**Consentement à payer plus cher**")
                st.dataframe(tab_consent, width='stretch')
                st.download_button("📥 Consentement", tab_consent.to_csv(index=False), "sm_consent.csv", key="dl_sm_consent")
                if pret_oui > 0:
                    crits = acheteurs[acheteurs['pret_plus']]['criteres_consentement'].explode().dropna()
                    crits = crits[~crits.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    crit_counts = crits.value_counts().reset_index()
                    crit_counts.columns = ['Critère', 'Nb']
                    st.markdown("**Critères invoqués**")
                    st.dataframe(crit_counts, width='stretch')
                    st.download_button("📥 Critères", crit_counts.to_csv(index=False), "sm_criteres.csv", key="dl_sm_criteres")
                    # Écart de prix par critère
                    df_ecart = acheteurs[acheteurs['pret_plus']].dropna(subset=['prix_num', 'prix_max_num']).copy()
                    if not df_ecart.empty:
                        df_ecart['ecart_rel'] = (df_ecart['prix_max_num'] / df_ecart['prix_num'] - 1) * 100
                        df_ecart = df_ecart[df_ecart['ecart_rel'].abs() < 1000]
                        exploded = df_ecart.explode('criteres_consentement')
                        exploded = exploded[~exploded['criteres_consentement'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        ecart_crit = exploded.groupby('criteres_consentement')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_crit.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                        ecart_crit['Écart moyen (%)'] = ecart_crit['Écart moyen (%)'].round(1)
                        st.markdown("**Écart de prix par critère de consentement**")
                        st.dataframe(ecart_crit, width='stretch')
                        st.download_button("📥 Écart prix", ecart_crit.to_csv(index=False), "sm_ecart_prix.csv", key="dl_sm_ecart")
    else:
        st.info("Données supermarché non disponibles.")
    # ─── 🏠 MÉNAGES ──────────────────────────────
    st.markdown("### 🏠 Questionnaires Ménages")
    if not df_menage_unifie.empty:
        df_m = df_menage_unifie
        acheteurs_m = df_m[df_m['achat_huile'].str.lower() == 'oui']
        # Synthèse
        taille_valide = df_m['taille_menage'].between(1, 20)
        tab_m1 = pd.DataFrame({
            'Indicateur': ['Nb total', 'Nb acheteurs huile', 'Taux d\'achat (%)',
                           'Taille moyenne ménage (valide)', 'Taille médiane ménage (valide)'],
            'Valeur': [len(df_m), len(acheteurs_m), f"{len(acheteurs_m)/len(df_m)*100:.1f}",
                       f"{df_m.loc[taille_valide, 'taille_menage'].mean():.1f}",
                       f"{df_m.loc[taille_valide, 'taille_menage'].median():.0f}"]
        })
        st.dataframe(tab_m1, width='stretch')
        st.download_button("📥 Synthèse", tab_m1.to_csv(index=False), "men_synthese.csv", key="dl_men_synth")
        # Volume / Prix
        vol_valide = df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= 50)
        prix_valide = df_m['prix_litre'].notna() & (df_m['prix_litre'] <= 10000)
        tab_m2 = pd.DataFrame({
            'Indicateur': ['Volume moyen acheté (L)', 'Volume médian (L)',
                           'Prix/L moyen (FC)', 'Prix/L médian (FC)'],
            'Valeur': [f"{df_m.loc[vol_valide, 'volume_total_l'].mean():.2f}",
                       f"{df_m.loc[vol_valide, 'volume_total_l'].median():.2f}",
                       f"{df_m.loc[prix_valide, 'prix_litre'].mean():,.0f}",
                       f"{df_m.loc[prix_valide, 'prix_litre'].median():,.0f}"]
        })
        st.dataframe(tab_m2, width='stretch')
        st.download_button("📥 Volume/Prix", tab_m2.to_csv(index=False), "men_vol_prix.csv", key="dl_men_volprix")
        # Fréquence d'achat (tableau)
        freq_counts = df_m.loc[acheteurs_m.index, 'frequence'].value_counts().reset_index()
        freq_counts.columns = ['Fréquence', 'Nb']
        st.markdown("**Fréquence d'achat (acheteurs)**")
        st.dataframe(freq_counts, width='stretch')
        st.download_button("📥 Fréquence", freq_counts.to_csv(index=False), "men_freq.csv", key="dl_men_freq")
        # Taille des ménages par zone socio‑économique
        if 'zone_socioeco' in df_m.columns:
            zone_taille = df_m[taille_valide & (df_m['zone_socioeco'] != 'Inconnu')].groupby('zone_socioeco')['taille_menage'].agg(['mean', 'median', 'count']).reset_index()
            zone_taille.columns = ['Zone', 'Taille moyenne', 'Taille médiane', 'Nb ménages']
            st.markdown("**Taille des ménages par zone socio‑économique**")
            st.dataframe(zone_taille, width='stretch')
            st.download_button("📥 Taille par zone", zone_taille.to_csv(index=False), "men_taille_zone.csv", key="dl_men_taille_zone")
        # Volume acheté par tranches (camembert)
        vol_tranches = df_m[df_m['volume_total_l'].notna() & (df_m['volume_total_l'] > 0) & (df_m['volume_total_l'] <= 50)].copy()
        if not vol_tranches.empty:
            def tranche_vol(x):
                if x < 0.5: return '<0,5 L'
                elif x <= 1: return '0,5-1 L'
                elif x <= 2: return '1-2 L'
                elif x <= 3: return '2-3 L'
                elif x <= 4: return '3-4 L'
                elif x <= 5: return '4-5 L'
                else: return '>5 L'
            vol_tranches['Tranche'] = vol_tranches['volume_total_l'].apply(tranche_vol)
            tranche_counts = vol_tranches['Tranche'].value_counts().reset_index()
            tranche_counts.columns = ['Tranche', 'Nb']
            ordre = ['<0,5 L', '0,5-1 L', '1-2 L', '2-3 L', '3-4 L', '4-5 L', '>5 L']
            tranche_counts['Tranche'] = pd.Categorical(tranche_counts['Tranche'], categories=ordre, ordered=True)
            tranche_counts = tranche_counts.sort_values('Tranche')
            st.markdown("**Volume acheté par tranches**")
            st.dataframe(tranche_counts, width='stretch')
            st.download_button("📥 Volumes par tranche", tranche_counts.to_csv(index=False), "men_vol_tranches.csv", key="dl_men_tranches")
        # Consentement à payer plus (taux, critères)
        if 'pret_plus' in df_m.columns:
            pret_oui_m = df_m['pret_plus'].sum()
            pret_total = df_m['pret_payer_plus'].notna().sum()
            if pret_total > 0:
                tab_consent_m = pd.DataFrame({
                    'Indicateur': ['Prêts à payer plus', 'Taux (%)'],
                    'Valeur': [f"{pret_oui_m}/{pret_total}", f"{pret_oui_m/pret_total*100:.1f}"]
                })
                st.markdown("**Consentement à payer plus cher**")
                st.dataframe(tab_consent_m, width='stretch')
                st.download_button("📥 Consentement", tab_consent_m.to_csv(index=False), "men_consent.csv", key="dl_men_consent")
                if pret_oui_m > 0:
                    crits_m = df_m[df_m['pret_plus']]['criteres'].explode().dropna()
                    crits_m = crits_m[~crits_m.str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                    crit_counts_m = crits_m.value_counts().reset_index()
                    crit_counts_m.columns = ['Critère', 'Nb']
                    st.markdown("**Critères invoqués**")
                    st.dataframe(crit_counts_m, width='stretch')
                    st.download_button("📥 Critères", crit_counts_m.to_csv(index=False), "men_criteres.csv", key="dl_men_criteres")
                    # Écart de prix par critère
                    df_ecart_m = df_m[df_m['pret_plus']].dropna(subset=['prix_num', 'prix_max']).copy()
                    if not df_ecart_m.empty:
                        df_ecart_m['ecart_rel'] = (pd.to_numeric(df_ecart_m['prix_max'], errors='coerce') / pd.to_numeric(df_ecart_m['prix_num'], errors='coerce') - 1) * 100
                        df_ecart_m = df_ecart_m[df_ecart_m['ecart_rel'].notna() & (df_ecart_m['ecart_rel'].abs() < 1000)]
                        exploded_m = df_ecart_m.explode('criteres')
                        exploded_m = exploded_m[~exploded_m['criteres'].str.lower().str.contains('non|pas prêt|ne suis pas', na=False)]
                        ecart_crit_m = exploded_m.groupby('criteres')['ecart_rel'].agg(['mean', 'count']).reset_index()
                        ecart_crit_m.columns = ['Critère', 'Écart moyen (%)', 'Nb répondants']
                        ecart_crit_m['Écart moyen (%)'] = ecart_crit_m['Écart moyen (%)'].round(1)
                        st.markdown("**Écart de prix par critère de consentement**")
                        st.dataframe(ecart_crit_m, width='stretch')
                        st.download_button("📥 Écart prix", ecart_crit_m.to_csv(index=False), "men_ecart_prix.csv", key="dl_men_ecart")
        # Perception de la qualité
        if 'qualite' in df_m.columns:
            qual_ser = df_m['qualite'].dropna().astype(str).str.split(',').explode().str.strip()
            qual_ser = qual_ser[qual_ser != '']
            qual_counts = qual_ser.value_counts().reset_index()
            qual_counts.columns = ['Critère', 'Nb']
            st.markdown("**Perception de la qualité**")
            st.dataframe(qual_counts, width='stretch')
            st.download_button("📥 Qualité", qual_counts.to_csv(index=False), "men_qualite.csv", key="dl_men_qualite")
        # Qualités RougeCongo
        if 'rc_qualites' in df_m.columns:
            rc_qual = df_m['rc_qualites'].dropna().astype(str).str.split(',').explode().str.strip()
            rc_qual = rc_qual[rc_qual != '']
            rc_qual_counts = rc_qual.value_counts().reset_index()
            rc_qual_counts.columns = ['Qualité', 'Nb']
            st.markdown("**Qualités attribuées à RougeCongo**")
            st.dataframe(rc_qual_counts, width='stretch')
            st.download_button("📥 Qualités RC", rc_qual_counts.to_csv(index=False), "men_rc_qual.csv", key="dl_men_rc_qual")
        # Lieux d'achat (parts moyennes)
        if 'pourcentages_achat' in df_m.columns:
            df_pct = df_m[df_m['type_original'].isin(['menage', 'supermarche_menage'])].dropna(subset=['pourcentages_achat'])
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
                    lieu_moy = df_lieux.groupby('Catégorie')['Pourcentage'].mean().reset_index()
                    lieu_moy.columns = ['Canal', 'Part moyenne (%)']
                    lieu_moy['Part moyenne (%)'] = lieu_moy['Part moyenne (%)'].round(1)
                    st.markdown("**Lieux d'achat – part moyenne**")
                    st.dataframe(lieu_moy, width='stretch')
                    st.download_button("📥 Lieux d'achat", lieu_moy.to_csv(index=False), "men_lieux.csv", key="dl_men_lieux")
        # Segmentation par sexe/âge
        if 'Sexe' in df_m.columns and 'Tranche_age' in df_m.columns:
            seg_sexe = df_m['Sexe'].value_counts().reset_index()
            seg_sexe.columns = ['Sexe', 'Nb']
            seg_age = df_m['Tranche_age'].value_counts().reset_index()
            seg_age.columns = ['Âge', 'Nb']
            st.markdown("**Segmentation démographique**")
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.dataframe(seg_sexe, width='stretch')
            with col_m2:
                st.dataframe(seg_age, width='stretch')
            st.download_button("📥 Sexe", seg_sexe.to_csv(index=False), "men_sexe.csv", key="dl_men_sexe")
            st.download_button("📥 Âge", seg_age.to_csv(index=False), "men_age.csv", key="dl_men_age")
    else:
        st.info("Données ménages non disponibles.")
    # ─── 🚶 COMPTAGES & FLUX ────────────────────────
    st.markdown("### 🚶 Comptages & Flux")
    if not df_c_f.empty:
        heures_sem = df_c_f[df_c_f['date_dt'].dt.weekday < 5]['duree_h'].sum()
        heures_we  = df_c_f[df_c_f['date_dt'].dt.weekday >= 5]['duree_h'].sum()
        nb_sessions = len(df_c_f)
        tab_c1 = pd.DataFrame({
            'Indicateur': ['Nb sessions', 'Heures semaine', 'Heures week-end', 'Magasins suivis'],
            'Valeur': [nb_sessions, f"{heures_sem:.1f}", f"{heures_we:.1f}", df_c_f['lieu_officiel'].nunique()]
        })
        st.dataframe(tab_c1, width='stretch')
        st.download_button("📥 Synthèse comptages", tab_c1.to_csv(index=False), "compt_synthese.csv", key="dl_compt_synth")
        # Fréquentation par magasin
        if st.session_state.get('freq_magasin') is not None:
            st.markdown("**Fréquentation estimée par magasin**")
            st.dataframe(st.session_state['freq_magasin'], width='stretch')
            st.download_button("📥 Télécharger (CSV)", st.session_state['freq_magasin'].to_csv(index=False),
                               "compt_freq_magasin.csv", key="dl_compt_freq_mag")
        else:
            st.info("Tableau de fréquentation par magasin non disponible (ouvrez l'onglet Comptages & Flux).")
        # Fréquentation par segment
        if st.session_state.get('freq_segment') is not None:
            st.markdown("**Fréquentation par segment (taille × niveau)**")
            st.dataframe(st.session_state['freq_segment'], width='stretch')
            st.download_button("📥 Télécharger (CSV)", st.session_state['freq_segment'].to_csv(index=False),
                               "compt_freq_segment.csv", key="dl_compt_freq_seg")
        else:
            st.info("Tableau par segment non disponible.")
        # Facteurs k (si présents)
        if st.session_state.get('k_summary') is not None:
            st.markdown("**Facteurs k par magasin**")
            st.dataframe(st.session_state['k_summary'], width='stretch')
            st.download_button("📥 Facteurs k", st.session_state['k_summary'].to_csv(index=False), "compt_k.csv", key="dl_compt_k")
    else:
        st.info("Données de comptage non disponibles.")
    # ─── 📊 ESTIMATION DU MARCHÉ ──────────────────
    st.markdown("### 📊 Estimation du marché")
    total_A = st.session_state.get('total_A_med', None)
    demi_A = st.session_state.get('demi_iqr_total_A', None)
    total_B = st.session_state.get('total_med_B', None)
    demi_B = st.session_state.get('total_demi_iqr_B', None)
    total_C = st.session_state.get('vol_annuel_med_C', None)
    demi_C = st.session_state.get('demi_iqr_annuel_C', None)
    methods = []
    if total_A is not None:
        methods.append({'Méthode': 'A (strates)', 'Volume annuel': f"{fmt_volume(total_A)} L ± {fmt_volume(demi_A)} L"})
    if total_B is not None:
        methods.append({'Méthode': 'B (démographique)', 'Volume annuel': f"{fmt_volume(total_B)} L ± {fmt_volume(demi_B)} L"})
    if total_C is not None:
        methods.append({'Méthode': 'C (directe)', 'Volume annuel': f"{fmt_volume(total_C)} L ± {fmt_volume(demi_C)} L"})
    if methods:
        df_methods = pd.DataFrame(methods)
        st.dataframe(df_methods, width='stretch')
        st.download_button("📥 Synthèse méthodes", df_methods.to_csv(index=False), "estim_methodes.csv", key="dl_estim_methodes")
    # Détail des strates
    if st.session_state.get('strates_A') is not None:
        st.markdown("**Détail par strate (Méthode A)**")
        st.dataframe(st.session_state['strates_A'], width='stretch')
        st.download_button("📥 Strates", st.session_state['strates_A'].to_csv(index=False), "estim_strates.csv", key="dl_estim_strates")
    else:
        st.info("Tableau des strates non disponible (ouvrez l'onglet Estimation).")
    # Volume par magasin
    if st.session_state.get('magasins_volumes') is not None:
        st.markdown("**Volumes estimés par magasin**")
        st.dataframe(st.session_state['magasins_volumes'], width='stretch')
        st.download_button("📥 Volumes/magasin", st.session_state['magasins_volumes'].to_csv(index=False), "estim_magasins.csv", key="dl_estim_magasins")
    else:
        st.info("Tableau des magasins non disponible.")
    # ─── 🏷️ PRIX & CONCURRENCE ────────────────────
    st.markdown("### 🏷️ Prix & Concurrence")
    if not df_prices_ext.empty:
        # S'assurer que la colonne prix_unitaire_FC existe
        if 'prix_unitaire_FC' not in df_prices_ext.columns:
            # La créer si les colonnes nécessaires existent
            if 'prix' in df_prices_ext.columns and 'volume_L' in df_prices_ext.columns:
                df_prices_ext['prix_unitaire_FC'] = df_prices_ext['prix'] / df_prices_ext['volume_L']
            elif 'conditionnement' in df_prices_ext.columns and 'prix' in df_prices_ext.columns:
                # Extraire le volume depuis le conditionnement si possible
                df_prices_ext['volume_L'] = df_prices_ext['conditionnement'].apply(extraire_litres)
                df_prices_ext['prix_unitaire_FC'] = df_prices_ext['prix'] / df_prices_ext['volume_L']
            else:
                st.warning("Impossible de calculer le prix unitaire, colonnes manquantes.")
                # Ne pas continuer l'affichage des métriques liées au prix unitaire
                st.stop()  # ou passer à la suite
        # Maintenant on peut utiliser la colonne en toute sécurité
        prix_moy = df_prices_ext['prix_unitaire_FC'].mean()
        nb_releves = len(df_prices_ext)
        nb_marques = df_prices_ext['marque_officielle'].nunique() if 'marque_officielle' in df_prices_ext.columns else 0
        tab_p1 = pd.DataFrame({
            'Indicateur': ['Nb relevés', 'Nb marques', 'Prix/L moyen (FC)'],
            'Valeur': [nb_releves, nb_marques, f"{prix_moy:,.0f}"]
        })
        st.dataframe(tab_p1, width='stretch')
        st.download_button("📥 Synthèse prix", tab_p1.to_csv(index=False), "prix_synthese.csv", key="dl_prix_synth")
        # Prix par conditionnement (vérifier aussi l'existence des colonnes)
        if 'conditionnement' in df_prices_ext.columns and 'prix_unitaire_FC' in df_prices_ext.columns:
            cond_prix = df_prices_ext.groupby('conditionnement')['prix_unitaire_FC'].agg(['mean', 'median', 'count']).reset_index()
            cond_prix.columns = ['Conditionnement', 'Prix moyen (FC/L)', 'Prix médian (FC/L)', 'Nb relevés']
            cond_prix['Prix moyen (FC/L)'] = cond_prix['Prix moyen (FC/L)'].round(0)
            cond_prix['Prix médian (FC/L)'] = cond_prix['Prix médian (FC/L)'].round(0)
            st.markdown("**Prix par conditionnement**")
            st.dataframe(cond_prix, width='stretch')
            st.download_button("📥 Prix/cond.", cond_prix.to_csv(index=False), "prix_conditionnement.csv", key="dl_prix_cond")
        # Distribution des prix par marque (vérifier colonnes)
        if 'marque_officielle' in df_prices_ext.columns and 'prix_unitaire_FC' in df_prices_ext.columns:
            marque_prix_stats = df_prices_ext.groupby('marque_officielle')['prix_unitaire_FC'].describe(percentiles=[.25, .5, .75]).reset_index()
            marque_prix_stats.columns = ['Marque', 'Nb', 'Moyenne', 'Écart-type', 'Min', 'Q1', 'Médiane', 'Q3', 'Max']
            st.markdown("**Distribution des prix par marque**")
            st.dataframe(marque_prix_stats, width='stretch')
            st.download_button("📥 Stats prix/marque", marque_prix_stats.to_csv(index=False), "prix_stats_marque.csv", key="dl_prix_stats_marque")
    else:
        st.info("Données de prix externes non chargées.")
    # ─── 🏪 PROFIL SUPERMARCHÉS ────────────────────
    st.markdown("### 🏪 Profil des supermarchés recensés")
    if not df_sm.empty:
        # Taille
        taille_counts = df_sm['Taille'].value_counts().reset_index()
        taille_counts.columns = ['Taille', 'Nb']
        st.markdown("**Répartition par taille**")
        st.dataframe(taille_counts, width='stretch')
        st.download_button("📥 Taille", taille_counts.to_csv(index=False), "profil_taille.csv", key="dl_profil_taille")
        # Niveau socio
        socio_counts = df_sm['Niveau_socio'].value_counts().reset_index()
        socio_counts.columns = ['Niveau', 'Nb']
        st.markdown("**Répartition par niveau socio-économique**")
        st.dataframe(socio_counts, width='stretch')
        st.download_button("📥 Niveau", socio_counts.to_csv(index=False), "profil_socio.csv", key="dl_profil_socio")
        # Présence d'huile
        price_cols = [c for c in df_sm.columns if ' - ' in c and any(u in c.lower() for u in ['l', 'litre'])]
        if price_cols:
            df_sm['Presence_huile'] = (df_sm[price_cols] > 0).any(axis=1)
            huile_counts = df_sm['Presence_huile'].value_counts().reset_index()
            huile_counts.columns = ['Huile présente', 'Nb']
            st.markdown("**Présence d'huile**")
            st.dataframe(huile_counts, width='stretch')
            st.download_button("📥 Huile", huile_counts.to_csv(index=False), "profil_huile.csv", key="dl_profil_huile")
    else:
        st.info("Données supermarchés non chargées.")