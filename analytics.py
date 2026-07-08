"""
analytics.py – Calculs analytiques (k-factors, estimation marché, etc.)
"""
import json
import os
import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime

from config import K_OVERRIDE_FILE, CACHE_TTL_DATA
from utils import *

# ──────────────────────────────────────────────
# K-factors
# ──────────────────────────────────────────────

def get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles):
    """Récupère le profil de fréquentation pour un jour donné."""
    if not df_profils_pivot.empty and magasin in df_profils_pivot['magasin'].values:
        row = df_profils_pivot[df_profils_pivot['magasin'] == magasin].iloc[0]
        profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
        if max(profil) > 0:
            return profil, "Google direct"
    if magasin in df_sm['Nom'].values:
        secteur = df_sm[df_sm['Nom'] == magasin]['Secteur'].values[0]
        if df_secteur_profiles is not None and secteur in df_secteur_profiles['secteur'].values:
            row_sect = df_secteur_profiles[df_secteur_profiles['secteur'] == secteur].iloc[0]
            profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            return profil, f"Secteur {secteur} (médian)"
    return [1.0] * 24, "Aucun profil"

def get_opening_hours(row_sm, jour_type):
    """Retourne une liste de booléens indiquant si le magasin est ouvert pour chaque heure (0-23)."""
    if jour_type == 'semaine':
        ouverture = str(row_sm.get('ouv_sem', '08:00')).strip()
        fermeture = str(row_sm.get('ferm_sem', '18:00')).strip()
    else:
        ouverture = str(row_sm.get('ouv_we', '08:00')).strip()
        fermeture = str(row_sm.get('ferm_we', '18:00')).strip()

    def parse_horaire(h_str, is_closing=False):
        s = h_str.strip().upper().replace(' ', '')
        if 'H' in s and ':' not in s:
            s = re.sub(r'H', ':', s)
        if ':' not in s and s.isdigit():
            s = s + ':00'
        if ':' not in s and len(s) == 4 and s.isdigit():
            s = s[:2] + ':' + s[2:]
        try:
            t = datetime.strptime(s, '%H:%M')
            h, m = t.hour, t.minute
            if is_closing and h == 0 and m == 0:
                h = 24
            return h, m
        except:
            return (8, 0) if not is_closing else (18, 0)

    import re
    h_ouv, m_ouv = parse_horaire(ouverture, is_closing=False)
    h_ferm, m_ferm = parse_horaire(fermeture, is_closing=True)
    ouv_min = h_ouv * 60 + m_ouv
    ferm_min = h_ferm * 60 + m_ferm
    if ferm_min <= ouv_min:
        ferm_min += 24 * 60
    ouvert = [False] * 24
    for h in range(24):
        debut = h * 60
        fin = (h + 1) * 60
        if debut < ferm_min and fin > ouv_min:
            ouvert[h] = True
    return ouvert

@st.cache_data(ttl=CACHE_TTL_DATA, show_spinner=False)
def cached_compute_k_factors(magasin, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping):
    """Calcule les k-factors (caché) pour un magasin."""
    df_c_f = deserialize_obj_cols(df_c_f)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)

    comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
    if comptages.empty:
        return None, []

    k_list = []
    details = []
    jour_map = {'Mon': 'Mo', 'Tue': 'Tu', 'Wed': 'We', 'Thu': 'Th', 'Fri': 'Fr', 'Sat': 'Sa', 'Sun': 'Su'}

    def get_effective_profile_local(mag, jour_code):
        nom_google = magasin_mapping.get(mag)
        if nom_google and nom_google in df_profils_pivot['magasin'].values:
            row = df_profils_pivot[df_profils_pivot['magasin'] == nom_google].iloc[0]
            profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            if max(profil) > 0:
                return profil, "Google"
        secteur_val = df_sm[df_sm['Nom'] == mag]['Secteur'].values
        if len(secteur_val) > 0 and secteur_profiles is not None:
            secteur_val = secteur_val[0]
            if secteur_val in secteur_profiles['secteur'].values:
                row_sect = secteur_profiles[secteur_profiles['secteur'] == secteur_val].iloc[0]
                profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
                return profil, f"Secteur {secteur_val}"
        return [1.0] * 24, "Uniforme"

    for _, row in comptages.iterrows():
        date_obj = row['date_dt']
        jour_code = date_obj.strftime('%a')
        jour_google = jour_map.get(jour_code, jour_code)
        profil, source = get_effective_profile_local(magasin, jour_google)
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
            nxt = min((h + 1) * 60, end_min)
            frac = (nxt - current) / 60.0
            G_moy += profil[h] * frac
            current = nxt
        G_moy = G_moy / duree if duree > 0 else 0
        if G_moy <= 0:
            continue
        flux_reel = row['total'] / duree
        k = flux_reel / G_moy
        k_list.append(k)
        details.append({
            'date': date_obj.strftime('%Y-%m-%d'),
            'type': 'weekend' if date_obj.weekday() >= 5 else 'semaine',
            'k': k,
            'source': source,
            'debut': debut.strftime('%H:%M'),
            'fin': fin.strftime('%H:%M'),
            'duree_h': duree,
            'total': row['total'],
            'flux_reel': flux_reel,
            'G_moy': G_moy,
            'debut_dt': debut,
            'fin_dt': fin
        })

    k = np.median(k_list) if k_list else None
    return k, details

def compute_k_factors(magasin, df_c_f, df_sm, df_profils_pivot, df_secteur_profiles):
    """Calcule les k-factors semaine/week-end pour un magasin."""
    comptages = df_c_f[df_c_f['lieu_officiel'] == magasin].copy()
    if comptages.empty:
        return None, None, {}

    k_sem_list = []
    k_we_list = []
    details = []
    for idx, row in comptages.iterrows():
        date_obj = row['date_dt']
        is_weekend = date_obj.weekday() >= 5
        jour_type = 'weekend' if is_weekend else 'semaine'
        jour_code = date_obj.strftime('%a')
        profil, source = get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles)

        debut = row['debut_dt']
        fin = row['fin_dt']
        duree = (fin - debut).total_seconds() / 3600.0
        if duree <= 0:
            continue

        start_min = debut.hour * 60 + debut.minute
        end_min = fin.hour * 60 + fin.minute
        current = start_min
        G_moy = 0.0
        while current < end_min:
            h = current // 60
            next_min = min((h + 1) * 60, end_min)
            frac = (next_min - current) / 60.0
            G_moy += profil[h] * frac
            current = next_min
        G_moy = G_moy / duree if duree > 0 else 0

        if G_moy <= 0:
            continue

        flux_reel = row['total'] / duree
        k = flux_reel / G_moy

        if jour_type == 'semaine':
            k_sem_list.append(k)
        else:
            k_we_list.append(k)
        details.append({'date': date_obj.strftime('%Y-%m-%d'), 'type': jour_type, 'k': k, 'source': source})

    k_sem = np.median(k_sem_list) if k_sem_list else None
    k_we = np.median(k_we_list) if k_we_list else None
    if k_sem is None and k_we is not None:
        k_sem = k_we
    if k_we is None and k_sem is not None:
        k_we = k_sem

    cv_sem = np.std(k_sem_list) / np.mean(k_sem_list) if len(k_sem_list) > 1 else 0
    cv_we = np.std(k_we_list) / np.mean(k_we_list) if len(k_we_list) > 1 else 0
    anomalies_data = {
        'k_sem_list': k_sem_list, 'k_we_list': k_we_list,
        'cv_sem': cv_sem, 'cv_we': cv_we, 'details': details
    }
    return k_sem, k_we, anomalies_data

def estimate_daily_flow(magasin, jour_code, k_sem, k_we, df_sm, df_profils_pivot, df_secteur_profiles):
    """Estime le flux journalier de clients pour un magasin et un jour donné."""
    is_weekend = jour_code in ['Sa', 'Su']
    k = k_we if is_weekend else k_sem
    if k is None:
        return [0] * 24, 0, "k non disponible"

    profil, source = get_profile_for_day(magasin, jour_code, df_sm, df_profils_pivot, df_secteur_profiles)

    sm_row = df_sm[df_sm['Nom'] == magasin]
    if sm_row.empty:
        ouvert = [True] * 24
    else:
        ouvert = get_opening_hours(sm_row.iloc[0], 'semaine' if not is_weekend else 'weekend')

    clients_par_heure = []
    for h in range(24):
        if ouvert[h]:
            clients = int(round(k * profil[h]))
        else:
            clients = 0
        clients_par_heure.append(clients)
    total = sum(clients_par_heure)
    return clients_par_heure, total, source

# ──────────────────────────────────────────────
# K-overrides
# ──────────────────────────────────────────────

def load_k_overrides():
    if os.path.exists(K_OVERRIDE_FILE):
        with open(K_OVERRIDE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_k_overrides(overrides):
    with open(K_OVERRIDE_FILE, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2)

# ──────────────────────────────────────────────
# Préparation des données supermarché
# ──────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_DATA)
def prepare_supermarche_data(df_supermarche_full):
    """
    Ajoute les colonnes dérivées (Sexe, Âge, Tranche_age, consentement)
    et retourne un tuple (df_enrichi, acheteurs_global_full).
    """
    import re
    df_supermarche_full = deserialize_obj_cols(df_supermarche_full)
    df = df_supermarche_full.copy()

    def get_sexe(x):
        if not isinstance(x, str):
            return None
        if 'Sexe:' in x:
            m = re.search(r'Sexe:\s*([FH])', x)
            return m.group(1) if m else None
        if 'F' in x.upper() and 'H' not in x.upper():
            return 'F'
        if 'H' in x.upper():
            return 'H'
        return None

    def get_age(x):
        if not isinstance(x, str):
            return None
        m = re.search(r'Âge:\s*(\d+[-+]*\d*)', x)
        if m:
            return m.group(1)
        m2 = re.search(r'(\d{2})', x)
        return m2.group(1) if m2 else None

    def tranche_age(age_str):
        if not age_str:
            return 'Inconnu'
        try:
            age = int(re.search(r'\d+', age_str).group())
            if age < 25:
                return 'Moins de 25 ans'
            elif age < 35:
                return '25-34 ans'
            elif age < 50:
                return '35-49 ans'
            else:
                return '50 ans et plus'
        except:
            return 'Inconnu'

    df['Sexe'] = df['SexeAge'].apply(get_sexe)
    df['Âge'] = df['SexeAge'].apply(get_age)
    df['Tranche_age'] = df['Âge'].apply(tranche_age)

    if 'statut' in df.columns:
        df_valides = df[df['statut'] != 'Refus'].copy()
    else:
        df_valides = df.copy()

    acheteurs_global_full = df_valides[df_valides['Q1'] == 'Oui'].copy()

    def is_willing_to_pay_more(crit_list):
        if not crit_list:
            return False
        for crit in crit_list:
            crit_lower = crit.strip().lower()
            if any(phrase in crit_lower for phrase in ['non', 'pas prêt', 'ne suis pas prêt', 'aucun']):
                return False
        return True

    acheteurs_global_full['criteres_consentement'] = acheteurs_global_full['criteres_consentement'].apply(
        lambda x: x if isinstance(x, list) else []
    )
    acheteurs_global_full['pret_plus'] = acheteurs_global_full['criteres_consentement'].apply(is_willing_to_pay_more)

    return df, acheteurs_global_full

# ============================================================

# ============================================================
# Fonctions pour pages
# ============================================================

def compute_all_k_data(selected_mags_tuple, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping, k_overrides):
    # Désérialisation pour compatibilité cache
    df_c_f = deserialize_obj_cols(df_c_f)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)
    selected_mags = list(selected_mags_tuple)
    all_k_data = {}
    for mag in selected_mags:
        k, details = cached_compute_k_factors(mag, df_c_f, df_sm, df_profils_pivot, secteur_profiles, magasin_mapping)
        over = k_overrides.get(mag, {})
        if 'k' in over:
            k = over['k']
        all_k_data[mag] = {'k': k, 'details': details}
    return all_k_data

def load_frequentation_data():
    if not os.path.exists("fréquentation.csv"):
        st.warning("Fichier 'fréquentation.csv' introuvable.")
        return pd.DataFrame(), pd.DataFrame()
    encodings = ['utf-8', 'latin1', 'cp1252']
    df_raw = None
    for enc in encodings:
        try:
            df_raw = pd.read_csv("fréquentation.csv", encoding=enc)
            break
        except:
            continue
    if df_raw is None:
        st.error("Impossible de lire 'fréquentation.csv'")
        return pd.DataFrame(), pd.DataFrame()
    if 'title' in df_raw.columns:
        mag_col = 'title'
    else:
        possible = [c for c in df_raw.columns if 'title' in c.lower() or 'nom' in c.lower()]
        mag_col = possible[0] if possible else df_raw.columns[0]
    occ_cols = [c for c in df_raw.columns if c.endswith('occupancyPercent')]
    hour_cols = [c for c in df_raw.columns if c.endswith('/hour')]
    if not occ_cols or not hour_cols:
        st.error("Colonnes occupancyPercent/hour manquantes.")
        return pd.DataFrame(), pd.DataFrame()
    occ_to_hour = {}
    for occ in occ_cols:
        hour_candidate = occ.replace('occupancyPercent', 'hour')
        if hour_candidate in hour_cols:
            occ_to_hour[occ] = hour_candidate
    records = []
    for idx, row in df_raw.iterrows():
        magasin = row[mag_col]
        for occ_col, hour_col in occ_to_hour.items():
            heure_val = row.get(hour_col)
            occ_val = row.get(occ_col)
            if pd.notna(heure_val) and pd.notna(occ_val):
                try:
                    heure = int(float(heure_val))
                    occ = float(occ_val)
                    parts = occ_col.split('/')
                    if len(parts) >= 3:
                        jour = parts[1]
                        records.append({
                            'magasin': magasin,
                            'jour': jour,
                            'heure': heure,
                            'occupancy': occ
                        })
                except:
                    pass
    if not records:
        return pd.DataFrame(), pd.DataFrame()
    df_long = pd.DataFrame(records)
    df_long['key'] = df_long['jour'] + '_' + df_long['heure'].astype(str)
    pivot = df_long.pivot_table(index='magasin', columns='key', values='occupancy', fill_value=0)
    pivot = pivot.reset_index()
    jours = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
    for jour in jours:
        for h in range(24):
            col_name = f"{jour}_{h}"
            if col_name not in pivot.columns:
                pivot[col_name] = 0
    other_cols = [c for c in pivot.columns if c != 'magasin']
    other_cols.sort()
    pivot = pivot[['magasin'] + other_cols]
    return pivot, df_long
# ============================================================
# Fonctions pour la méthode A
# ============================================================



def prepare_secteur_profiles(df_profils_pivot, df_sm):
    if df_profils_pivot.empty or df_sm.empty:
        return None
    df_profils_pivot = df_profils_pivot.copy()
    df_sm = df_sm.copy()
    df_profils_pivot['magasin_norm'] = df_profils_pivot['magasin'].apply(normalize_name)
    df_sm['nom_norm'] = df_sm['Nom'].apply(normalize_name)
    merged = df_profils_pivot.merge(df_sm[['nom_norm', 'Secteur']], left_on='magasin_norm', right_on='nom_norm', how='left')
    secteur_profiles_list = []
    for secteur in merged['Secteur'].dropna().unique():
        sub = merged[merged['Secteur'] == secteur]
        cols = [c for c in sub.columns if c not in ['magasin', 'magasin_norm', 'Secteur', 'nom_norm']]
        median_row = {'secteur': secteur}
        for c in cols:
            median_row[c] = sub[c].median()
        secteur_profiles_list.append(median_row)
    return pd.DataFrame(secteur_profiles_list)
# ============================================================
# Onglets
# ============================================================


def prepare_menage_unifie(df_q_f_raw, df_sm, commune_niveau):
    # ⬇️ Désérialisation pour compatibilité cache
    df_q_f_raw = deserialize_obj_cols(df_q_f_raw)
    """
    Construit le DataFrame unifié des ménages (tous types : menage, supermarche, supermarche_menage)
    avec toutes les colonnes dérivées nécessaires aux analyses de l'onglet 3.
    """
    df_source = df_q_f_raw[df_q_f_raw['type'].isin(['menage', 'supermarche', 'supermarche_menage'])].copy()
    rows_unified = []
    for _, row in df_source.iterrows():
        qtype = row['type']
        data = row['data_dict'] if isinstance(row['data_dict'], dict) else {}
        # --- Détermination de la catégorie ---
        if qtype == 'supermarche':
            achat = str(data.get('Q1_Achat', '')).strip().lower()
            if achat != 'oui':
                continue
            cat = 'Acheteur supermarché'
        elif qtype == 'supermarche_menage':
            cat = 'Non-acheteur supermarché'
        else:
            cat = 'Ménage pur'
        # --- Extraction des champs communs et spécifiques ---
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
    # --- Conversions et calculs ---
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
    # Correction de la ligne problématique (ChainedAssignment)
    df_menage_unifie['prix_litre'] = df_menage_unifie['prix_litre'].replace([np.inf, -np.inf], np.nan)
    df_menage_unifie['taille_menage'] = pd.to_numeric(df_menage_unifie['nb_personnes'], errors='coerce')
    # --- Marque nettoyée ---
    df_menage_unifie['marque_clean'] = apply_brand_mapping_strict(df_menage_unifie['marque_preferee'])
    mask_sm_menage = df_menage_unifie['type_original'] == 'supermarche_menage'
    df_menage_unifie.loc[mask_sm_menage & (df_menage_unifie['marque_clean'] == 'mbila'), 'marque_clean'] = 'En vrac'
    # --- Consentement à payer plus ---
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
    # --- Fréquence numérique ---
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
    # --- Zone socioéconomique ---
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

    def compute_all_anomalies(df_q_full, df_c_full, df_p_full, settings, df_prices_ext, brand_map):
        # ⬇️ Désérialisation pour compatibilité cache
        df_q_full = deserialize_obj_cols(df_q_full)
        df_c_full = deserialize_obj_cols(df_c_full)
        df_p_full = deserialize_obj_cols(df_p_full)
        all_anomalies = []
        # --- Questionnaires ---
        if not df_q_full.empty:
            q = df_q_full.copy()
            q['datetime'] = pd.to_datetime(q['date'] + ' ' + q['heure'], errors='coerce')
            q = q.dropna(subset=['datetime'])
            # 1) Validations intrinsèques
            for _, row in q.iterrows():
                rec = row['data_dict']
                qtype = row['type']
                msgs = validate_questionnaire_dynamic(rec, qtype, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'questionnaire', row['date'], row['enqueteur'], m))
            # 2) Intervalles temporels par enquêteur
            for enqueteur, grp in q.groupby('enqueteur'):
                grp_sorted = grp.sort_values('datetime')
                for i in range(len(grp_sorted) - 1):
                    prev = grp_sorted.iloc[i]
                    curr = grp_sorted.iloc[i + 1]
                    delta = (curr['datetime'] - prev['datetime']).total_seconds()
                    if delta <= 0:
                        continue
                    if prev.get('statut') == 'Refus':
                        if delta < settings['refus_min_secondes']:
                            all_anomalies.append((
                                curr['uuid'], 'questionnaire', curr['date'], enqueteur,
                                f"Refus trop rapproché ({delta:.0f} s) - {curr['type']} après {prev['type']} "
                                f"(min {settings['refus_min_secondes']} s)"
                            ))
                        continue
                    curr_type = curr['type']
                    prev_type = prev['type']
                    if curr_type == 'supermarche_menage' and prev_type == 'supermarche':
                        continue
                    if prev_type == 'supermarche_menage':
                        data_prev = prev['data_dict']
                        if data_prev.get('Q3_Achat', '').strip().lower() == 'non':
                            continue
                    if delta < settings['intervalle_min_secondes']:
                        all_anomalies.append((
                            curr['uuid'], 'questionnaire', curr['date'], enqueteur,
                            f"Intervalle trop court entre {curr_type} et {prev_type} "
                            f"({delta:.0f} s) – minimum {settings['intervalle_min_secondes']}s (UUID précédent: {prev['uuid']})"
                        ))
            # 3) GPS supermarché / supermarche_menage
            sm_q = q[q['type'].isin(['supermarche', 'supermarche_menage'])].copy()
            if not sm_q.empty:
                sm_q['lat'] = sm_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
                )
                sm_q['lon'] = sm_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
                )
                sm_q_valid = sm_q.dropna(subset=['lat', 'lon'])
                for lieu, grp_lieu in sm_q_valid.groupby('lieu'):
                    if len(grp_lieu) < 2:
                        continue
                    lat_med = grp_lieu['lat'].median()
                    lon_med = grp_lieu['lon'].median()
                    for idx, row in grp_lieu.iterrows():
                        dist_km = haversine(row['lat'], row['lon'], lat_med, lon_med)
                        seuil_km = settings['distance_gps_questionnaire_m'] / 1000.0
                        if dist_km > seuil_km:
                            all_anomalies.append((
                                row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                                f"Distance GPS > {settings['distance_gps_questionnaire_m']} m "
                                f"par rapport à la médiane de '{lieu}' ({dist_km*1000:.0f} m)"
                            ))
            # 4) GPS ménages (doublons)
            menage_q = q[q['type'] == 'menage'].copy()
            if not menage_q.empty:
                menage_q['lat'] = menage_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
                )
                menage_q['lon'] = menage_q['data_dict'].apply(
                    lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
                )
                menage_valid = menage_q.dropna(subset=['lat', 'lon'])
                menage_valid['lat_round'] = menage_valid['lat'].round(5)
                menage_valid['lon_round'] = menage_valid['lon'].round(5)
                duplicate_groups = menage_valid.groupby(['lat_round', 'lon_round']).filter(lambda x: len(x) > 1)
                for _, row in duplicate_groups.iterrows():
                    all_anomalies.append((
                        row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                        f"Coordonnées GPS identiques à un autre ménage ({row['lat_round']}, {row['lon_round']})"
                    ))
            # 5) Marques non référencées
            if not df_prices_ext.empty:
                mag_marques = {}
                for _, row in df_prices_ext.iterrows():
                    mag = normalize_name(row['supermarche'])
                    marque = normalize_brand(row['marque'])
                    marque = brand_map.get(marque, marque)
                    mag_marques.setdefault(mag, set()).add(marque)
                acheteurs_sm = q[(q['type'] == 'supermarche') & 
                                (q['data_dict'].apply(lambda d: d.get('Q1_Achat', '') == 'Oui' if isinstance(d, dict) else False))]
                for _, row in acheteurs_sm.iterrows():
                    lieu = row['lieu']
                    norm_lieu = normalize_name(lieu)
                    if norm_lieu not in mag_marques:
                        continue
                    marque_brute = row['data_dict'].get('Q2_Marque', '')
                    if not marque_brute:
                        continue
                    marque_clean = normalize_brand(marque_brute.replace('Autre:', ''))
                    marque_clean = brand_map.get(marque_clean, marque_clean)
                    if marque_clean and marque_clean not in mag_marques[norm_lieu]:
                        all_anomalies.append((
                            row['uuid'], 'questionnaire', row['date'], row['enqueteur'],
                            f"Marque achetée « {marque_clean} » non référencée dans le supermarché « {lieu} »"
                        ))
        # --- Comptages ---
        if not df_c_full.empty:
            for _, row in df_c_full.iterrows():
                rec = row['data_dict']
                msgs = validate_counting_dynamic(rec, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'comptage', row['date'], row['enqueteur'], m))
            c = df_c_full.copy()
            c['lat'] = c['data_dict'].apply(
                lambda d: parse_gps(d.get('GPS', ''))[0] if isinstance(d, dict) else None
            )
            c['lon'] = c['data_dict'].apply(
                lambda d: parse_gps(d.get('GPS', ''))[1] if isinstance(d, dict) else None
            )
            c_valid = c.dropna(subset=['lat', 'lon'])
            for lieu, grp in c_valid.groupby('lieu'):
                if len(grp) < 2:
                    continue
                lat_med = grp['lat'].median()
                lon_med = grp['lon'].median()
                for _, row in grp.iterrows():
                    dist_km = haversine(row['lat'], row['lon'], lat_med, lon_med)
                    seuil_km = settings['distance_gps_comptage_m'] / 1000.0
                    if dist_km > seuil_km:
                        all_anomalies.append((
                            row['uuid'], 'comptage', row['date'], row['enqueteur'],
                            f"Distance GPS > {settings['distance_gps_comptage_m']} m "
                            f"par rapport à la médiane de '{lieu}' ({dist_km*1000:.0f} m)"
                        ))
        # --- Prix ---
        if not df_p_full.empty:
            for _, row in df_p_full.iterrows():
                rec = row['data_dict']
                msgs = validate_price_dynamic(rec, settings)
                for m in msgs:
                    all_anomalies.append((row['uuid'], 'prix', row['date'], row['enqueteur'], m))
        return all_anomalies
        # Filtrage préalable sur la période et l'enquêteur sélectionnés
        df_q_filtre_anom = df_q if 'df_q' in dir() else pd.DataFrame()
        df_c_filtre_anom = df_c if 'df_c' in dir() else pd.DataFrame()
        df_p_filtre_anom = df_p if 'df_p' in dir() else pd.DataFrame()
        if not df_q_filtre_anom.empty and 'date_dt' in df_q_filtre_anom.columns:
            mask_q_anom = (df_q_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_q_filtre_anom['date_dt'].dt.date <= date_range[1])
            df_q_filtre_anom = df_q_filtre_anom[mask_q_anom]
            if selected_enqueteur != "Tous":
                df_q_filtre_anom = df_q_filtre_anom[df_q_filtre_anom['enqueteur'] == selected_enqueteur]
        if not df_c_filtre_anom.empty and 'date_dt' in df_c_filtre_anom.columns:
            mask_c_anom = (df_c_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_c_filtre_anom['date_dt'].dt.date <= date_range[1])
            df_c_filtre_anom = df_c_filtre_anom[mask_c_anom]
        if not df_p_filtre_anom.empty and 'date_dt' in df_p_filtre_anom.columns:
            mask_p_anom = (df_p_filtre_anom['date_dt'].dt.date >= date_range[0]) & (df_p_filtre_anom['date_dt'].dt.date <= date_range[1])
            df_p_filtre_anom = df_p_filtre_anom[mask_p_anom]
        brand_map = load_brand_mapping()
        prices_ext = df_prices_ext if 'df_prices_ext' in dir() else pd.DataFrame()
        with st.spinner("Calcul des anomalies (cette opération est mise en cache)..."):
            df_q_clean = make_hashable(df_q_filtre_anom)
            df_c_clean = make_hashable(df_c_filtre_anom)
            df_p_clean = make_hashable(df_p_filtre_anom)
            anomaly_records = compute_all_anomalies(df_q_clean, df_c_clean, df_p_clean, settings, prices_ext, brand_map)
        # ------------------------------------------------------------
        # Comptage des anomalies par enquêteur et par jour
        # ------------------------------------------------------------
        if anomaly_records:
            df_anom = pd.DataFrame(anomaly_records, columns=['uuid', 'type', 'date_str', 'enqueteur', 'message'])
            df_anom['message'] = df_anom['message'].str.replace('FCFA', 'FC')
            df_anom['date'] = pd.to_datetime(df_anom['date_str'].str[:10], format='%Y-%m-%d', errors='coerce').dt.date
            df_anom = df_anom.dropna(subset=['date']).reset_index(drop=True)
            # Filtrage par la période de la barre latérale
            mask_date_anom = (df_anom['date'] >= date_range[0]) & (df_anom['date'] <= date_range[1])
            df_anom_f = df_anom[mask_date_anom]
            if selected_enqueteur != "Tous":
                df_anom_f = df_anom_f[df_anom_f['enqueteur'] == selected_enqueteur]
            anom_count_enq = df_anom_f.groupby('enqueteur').size().to_dict()
        else:
            df_anom_f = pd.DataFrame()
            anom_count_enq = {}
        # ------------------------------------------------------------
        # Tableau de synthèse par enquêteur (avec anomalies intégrées)
        # ------------------------------------------------------------
        st.subheader("📊 Synthèse par enquêteur")
        lignes_global = []
        for canon in tous_canoniques:
            stats = compute_stats(canon)
            lignes_global.append({
                'Enquêteur': canon,
                'Nb questionnaires SM (total)': stats['nb_q_total'],
                'Nb Q1=Oui': stats['nb_q1_oui'],
                '% Acheteur SM': f"{stats['pct_acheteur']:.1f}%",
                'Heures comptage': f"{stats['heures_comptage']:.1f}",
                '% Refus SM': f"{stats['pct_refus']:.1f}%",
                'Anomalies': anom_count_enq.get(canon, 0),
                'Heures travail effectif': f"{stats['travail']:.1f}",
                'Temps de travail effectif (h)': f"{stats['temps_estime_total']:.1f}"
            })
        df_global = pd.DataFrame(lignes_global)
        st.dataframe(df_global, width='stretch')
        # ------------------------------------------------------------
        # Détail journalier pour un enquêteur sélectionné
        # ------------------------------------------------------------
        st.subheader("📅 Détail journalier")
        choix_enqueteur = st.selectbox("Choisir un enquêteur", tous_canoniques)
        if choix_enqueteur:
            q_sel = df_q_ni[df_q_ni['enqueteur_canon'] == choix_enqueteur] if not df_q_ni.empty else pd.DataFrame()
            c_sel = df_c_ni[df_c_ni['enqueteur_canon'] == choix_enqueteur] if not df_c_ni.empty else pd.DataFrame()
            dates = set()
            if not q_sel.empty:
                dates.update(q_sel['date_dt'].dt.date)
            if not c_sel.empty:
                dates.update(c_sel['date_dt'].dt.date)
            dates = sorted(dates)
            anom_count_jour = df_anom_f[df_anom_f['enqueteur'] == choix_enqueteur].groupby('date').size().to_dict() if not df_anom_f.empty else {}
            lignes_jour = []
            for jour in dates:
                q_jour = q_sel[(q_sel['type'] == 'supermarche') & (q_sel['date_dt'].dt.date == jour)].copy()
                total_sm = len(q_jour)
                if total_sm > 0:
                    q_jour['statut_norm'] = q_jour['statut'].apply(
                        lambda x: unicodedata.normalize('NFKD', str(x))
                                    .encode('ASCII', 'ignore')
                                    .decode('utf-8')
                                    .strip()
                                    .lower()
                    )
                    refus = q_jour['statut_norm'].isin(['refus', 'refuse']).sum()
                    accept = q_jour[~q_jour['statut_norm'].isin(['refus', 'refuse'])]
                else:
                    refus = 0
                    accept = pd.DataFrame()
                nb_accept = len(accept)
                q1_oui = accept['data_dict'].apply(
                    lambda d: d.get('Q1_Achat', '') == 'Oui' if isinstance(d, dict) else False
                ).sum() if nb_accept > 0 else 0
                pct_acheteur = (q1_oui / nb_accept * 100) if nb_accept > 0 else 0.0
                pct_refus = (refus / total_sm * 100) if total_sm > 0 else 0.0
                c_all_jour = c_sel[c_sel['date_dt'].dt.date == jour]
                heures_comptage = c_all_jour[c_all_jour['duree_h'] > 5/60]['duree_h'].sum() if not c_all_jour.empty else 0.0
                timestamps = []
                q_all_jour = q_sel[q_sel['date_dt'].dt.date == jour]
                if not q_all_jour.empty:
                    timestamps.extend(q_all_jour['date_dt'].tolist())
                if not c_all_jour.empty:
                    timestamps.extend(c_all_jour['debut_dt'].tolist())
                    timestamps.extend(c_all_jour['fin_dt'].tolist())
                timestamps = [ts for ts in timestamps if pd.notna(ts)]
                travail_jour = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0 if timestamps else 0.0
                lignes_jour.append({
                    'Date': jour.strftime('%Y-%m-%d'),
                    'Nb questionnaires SM (total)': total_sm,
                    'Nb Q1=Oui': q1_oui,
                    '% Acheteur SM': f"{pct_acheteur:.1f}%",
                    'Heures comptage': f"{heures_comptage:.1f}",
                    '% Refus SM': f"{pct_refus:.1f}%",
                    'Anomalies': anom_count_jour.get(jour, 0),
                    'Temps de présence sur le terrain (h)': f"{travail_jour:.1f}"
                })
            df_jour = pd.DataFrame(lignes_jour)
            st.dataframe(df_jour, width='stretch')
