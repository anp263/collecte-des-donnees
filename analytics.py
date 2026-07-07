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
from utils import deserialize_obj_cols


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
