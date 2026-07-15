"""Page Estimation du marché."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import numpy as np
import os, sys, re, json, hashlib
from utils import *
from analytics import *
from collections import defaultdict

# Données
df_q_f = st.session_state.get('df_q_f', pd.DataFrame())
df_c_f = st.session_state.get('df_c_f', pd.DataFrame())
df_p_f = st.session_state.get('df_p_f', pd.DataFrame())
df_sm = st.session_state.get('df_sm_huile', st.session_state.get('df_sm', pd.DataFrame()))
df_supermarche_full = st.session_state.get('df_supermarche_full', pd.DataFrame())
df_q_f_raw = st.session_state.get('df_q_f_raw', pd.DataFrame())
df_profils_pivot = st.session_state.get('df_profils_pivot', pd.DataFrame())
secteur_profiles = st.session_state.get('secteur_profiles', None)
df_prices_ext = st.session_state.get('df_prices_ext', pd.DataFrame())
df_menage = st.session_state.get('df_menage', pd.DataFrame())
df_supermarche = st.session_state.get('df_supermarche', pd.DataFrame())
selected_mags = st.session_state.get('selected_mags', [])
if not df_sm.empty and selected_mags:
    original_count = len(selected_mags)
    selected_mags = [m for m in selected_mags if m in df_sm['Nom'].values]
    if len(selected_mags) < original_count:
        st.warning(
            f"⚠️ {original_count - len(selected_mags)} magasin(s) sélectionné(s) ne venden(t) pas d'huile de palme rouge "
            f"et ont été exclus de l'estimation du marché."
        )
date_range = st.session_state.get('date_range', (None, None))
magasin_mapping = {}

# Fonction de calcul
def compute_market_estimation(
    selected_mags_tuple,
    df_c_f,
    df_supermarche_full,
    df_sm,
    df_q_f_raw,
    df_profils_pivot,
    secteur_profiles,
    magasin_mapping,
    pop_aisée_min, pop_aisée_max,
    pop_moyenne_min, pop_moyenne_max,
    pop_populaire_min, pop_populaire_max,
    all_k_data=None
):
    """
    Retourne un dictionnaire contenant toutes les grandeurs calculées par l'onglet 5.
    """
    # --- Désérialisation des colonnes JSON (cache compatible) ---
    df_c_f = deserialize_obj_cols(df_c_f)
    df_supermarche_full = deserialize_obj_cols(df_supermarche_full)
    df_q_f_raw = deserialize_obj_cols(df_q_f_raw)
    if secteur_profiles is not None:
        secteur_profiles = deserialize_obj_cols(secteur_profiles)
    # df_sm et df_profils_pivot sont normalement déjà hachables
    selected_mags = list(selected_mags_tuple)
    # --- Fonctions internes (profil, horaires, k, flux) ---
    def get_effective_profile(magasin, jour_code):
        nom_google = magasin_mapping.get(magasin)
        if nom_google and nom_google in df_profils_pivot['magasin'].values:
            row = df_profils_pivot[df_profils_pivot['magasin'] == nom_google].iloc[0]
            profil = [row.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
            if max(profil) > 0:
                return profil, "Google", nom_google
        secteur = df_sm[df_sm['Nom'] == magasin]['Secteur'].values
        if len(secteur) > 0 and secteur_profiles is not None:
            secteur = secteur[0]
            if secteur in secteur_profiles['secteur'].values:
                row_sect = secteur_profiles[secteur_profiles['secteur'] == secteur].iloc[0]
                profil = [row_sect.get(f"{jour_code}_{h}", 0.0) for h in range(24)]
                return profil, f"Secteur {secteur}", "Profil secteur"
        return [1.0]*24, "Uniforme", "Aucun"
    def get_opening_hours(row_sm, jour_type):
        if jour_type == 'semaine':
            ouverture = str(row_sm.get('ouv_sem', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_sem', '18:00')).strip()
        else:
            ouverture = str(row_sm.get('ouv_we', '08:00')).strip()
            fermeture = str(row_sm.get('ferm_we', '18:00')).strip()
        def parse_horaire(h_str, is_closing=False):
            s = h_str.strip().upper().replace(' ', '')
            if 'H' in s and ':' not in s: s = s.replace('H', ':')
            if ':' not in s and s.isdigit(): s = s + ':00'
            if ':' not in s and len(s) == 4 and s.isdigit(): s = s[:2] + ':' + s[2:]
            try:
                t = datetime.strptime(s, '%H:%M')
                h, m = t.hour, t.minute
                if is_closing and h == 0 and m == 0: h = 24
                return h, m
            except:
                return (8, 0) if not is_closing else (18, 0)
        h_ouv, m_ouv = parse_horaire(ouverture, is_closing=False)
        h_ferm, m_ferm = parse_horaire(fermeture, is_closing=True)
        ouv_min = h_ouv*60 + m_ouv
        ferm_min = h_ferm*60 + m_ferm
        if ferm_min <= ouv_min: ferm_min += 24*60
        ouvert = [False]*24
        for h in range(24):
            debut = h*60
            fin = (h+1)*60
            if debut < ferm_min and fin > ouv_min:
                ouvert[h] = True
        return ouvert
    def estimate_daily_flow_marche(magasin, jour_code, k, profil):
        if k is None: return [0]*24, 0
        is_we = jour_code in ['Sa','Su']
        sm_row = df_sm[df_sm['Nom'] == magasin]
        ouvert = [True]*24 if sm_row.empty else get_opening_hours(sm_row.iloc[0], 'semaine' if not is_we else 'weekend')
        clients = [int(round(k*profil[h])) if ouvert[h] else 0 for h in range(24)]
        return clients, sum(clients)
    def weekly_volume_from_k(magasin, k):
        profil_sem, _, _ = get_effective_profile(magasin, 'Mo')
        profil_we, _, _  = get_effective_profile(magasin, 'Sa')
        clients_sem, _ = estimate_daily_flow_marche(magasin, 'Mo', k, profil_sem)
        clients_we, _  = estimate_daily_flow_marche(magasin, 'Sa', k, profil_we)
        return 5*sum(clients_sem) + 2*sum(clients_we)
    # --------------------------------------------------------------------
    # 1. Calcul des volumes hebdomadaires d'huile par magasin enquêté
    # --------------------------------------------------------------------
    mag_data = {}
    for mag in selected_mags:
        # Récupération du k depuis le dictionnaire pré-calculé ou calcul de secours
        if all_k_data and mag in all_k_data and all_k_data[mag]['k'] is not None:
            k = all_k_data[mag]['k']
        else:
            # fallback : calcul direct (ne devrait plus arriver)
            comptages = df_c_f[df_c_f['lieu_officiel'] == mag]
            if not comptages.empty:
                k_vals = []
                for _, row in comptages.iterrows():
                    # formule simplifiée pour obtenir k (comme avant)
                    duree = (row['fin_dt'] - row['debut_dt']).total_seconds()/3600.0
                    if duree > 0:
                        flux = row['total']/duree
                        # profil uniforme en fallback
                        k_vals.append(flux / 1.0)  # G_moy=1 simplifié
                k = np.median(k_vals) if k_vals else None
            else:
                k = None
        total_hebdo_clients = weekly_volume_from_k(mag, k) if k is not None else None
        df_sm_q = df_supermarche_full[df_supermarche_full['magasin_officiel'] == mag]
        nb_total_q = len(df_sm_q[df_sm_q['statut'] != 'Refus']) if 'statut' in df_sm_q.columns else len(df_sm_q)
        acheteurs = df_sm_q[(df_sm_q['Q1']=='Oui') & (df_sm_q['statut']!='Refus')] if 'statut' in df_sm_q.columns else df_sm_q[df_sm_q['Q1']=='Oui']
        nb_acheteurs = len(acheteurs)
        ti = nb_acheteurs / nb_total_q if nb_total_q > 0 else 0.0
        qi = acheteurs['vol_litres'].mean() if nb_acheteurs > 0 else 0.0
        Vh_huile_hebdo = total_hebdo_clients * ti * qi if (total_hebdo_clients is not None and ti is not None and qi is not None) else None
        vol_annuel_med = Vh_huile_hebdo * 52 if Vh_huile_hebdo is not None else None
        match = df_sm[df_sm['Nom'] == mag]
        taille = match.iloc[0]['Taille'] if not match.empty else '?'
        niveau = match.iloc[0]['Niveau_socio'] if not match.empty else '?'
        chaine = match.iloc[0].get('Chaine','') if not match.empty else ''
        mag_data[mag] = {
            'has_k': k is not None,
            'nb_total_q': nb_total_q,
            'nb_acheteurs': nb_acheteurs,
            'ti': ti, 'qi': qi,
            'Vh_huile_hebdo': Vh_huile_hebdo,
            'freq_hebdo': total_hebdo_clients,
            'vol_annuel_med': vol_annuel_med,
            'taille': taille, 'niveau': niveau, 'chaine': chaine
        }
    # --------------------------------------------------------------------
    # MÉTHODE A : estimateur par expansion stratifié + bootstrap stratifié
    # --------------------------------------------------------------------
    strata = df_sm.groupby(['Taille', 'Niveau_socio']).agg(
        N_s=('Nom', 'count'),
        magasins_liste=('Nom', lambda x: list(x))
    ).reset_index()
    strata['Strate'] = strata['Taille'] + ' / ' + strata['Niveau_socio']
    strate_data = {}
    for _, row_str in strata.iterrows():
        key = (row_str['Taille'], row_str['Niveau_socio'])
        N_s = row_str['N_s']
        magasins_possibles = row_str['magasins_liste']
        vols = []
        for mag in magasins_possibles:
            if mag in mag_data and mag_data[mag]['Vh_huile_hebdo'] is not None:
                vols.append(mag_data[mag]['Vh_huile_hebdo'])
        n_s = len(vols)
        strate_data[key] = {
            'N_s': N_s,
            'n_s': n_s,
            'volumes': np.array(vols)
        }
    n_boot = 500  # réduit pour performance, ajustez si nécessaire
    total_hebdo_boot = []
    for _ in range(n_boot):
        total_hebdo = 0.0
        for key, data in strate_data.items():
            vols = data['volumes']
            n_s = data['n_s']
            N_s = data['N_s']
            if n_s == 0:
                continue
            boot_vols = np.random.choice(vols, size=n_s, replace=True)
            sum_boot = np.sum(boot_vols)
            total_strate = sum_boot * (N_s / n_s)
            total_hebdo += total_strate
        total_hebdo_boot.append(total_hebdo)
    total_hebdo_boot = np.array(total_hebdo_boot)
    total_annuel_boot = total_hebdo_boot * 52
    median_total_A = np.median(total_annuel_boot)
    ci_low_A = np.percentile(total_annuel_boot, 2.5)
    ci_high_A = np.percentile(total_annuel_boot, 97.5)
    rows_strates = []
    for _, row_str in strata.iterrows():
        key = (row_str['Taille'], row_str['Niveau_socio'])
        data_str = strate_data[key]
        N_s = data_str['N_s']
        n_s = data_str['n_s']
        if n_s > 0:
            vols = data_str['volumes']
            total_obs = np.sum(vols)
            total_extrap = total_obs * (N_s / n_s)
            vol_annuel_extrap = total_extrap * 52
            vol_str = f"{fmt_volume(vol_annuel_extrap)} L"
        else:
            vol_str = "Non estimable"
        rows_strates.append({
            'Strate': row_str['Strate'],
            'Nb total magasins': N_s,
            'Nb enquêtés': n_s,
            'Volume annuel estimé': vol_str
        })
    df_strates_A = pd.DataFrame(rows_strates)
    # --- Méthode B (démographique) ---
    df_men_b = prepare_menage_unifie(make_hashable(df_q_f_raw), make_hashable(df_sm), load_commune_niveau())
    if 'statut' in df_men_b.columns:
        df_men_b = df_men_b[df_men_b['statut'] != 'Refus']
    if not df_men_b.empty:
        def extract_pct_supermarche(texte):
            if not isinstance(texte, str):
                return np.nan
            match = re.search(r'Supermarché.*?(\d+(?:\.\d+)?)\s*%', texte, re.IGNORECASE)
            return float(match.group(1)) / 100.0 if match else np.nan
        df_men_b['L'] = df_men_b['pourcentages_achat'].apply(extract_pct_supermarche)
        valide = (
            df_men_b['taille_menage'].notna() & (df_men_b['taille_menage'] > 0) & (df_men_b['taille_menage'] <= 20) &
            df_men_b['volume_total_l'].notna() & (df_men_b['volume_total_l'] > 0) &
            df_men_b['freq_num'].notna() & df_men_b['L'].notna()
        )
        df_valide = df_men_b[valide].copy()
        df_valide['conso_indiv_annuelle'] = 12 * df_valide['freq_num'] * df_valide['volume_total_l'] / df_valide['taille_menage']
        seuil_conso = 100
        df_valide = df_valide[df_valide['conso_indiv_annuelle'] <= seuil_conso]
        pop_bounds = {
            'Aisé': (pop_aisée_min, pop_aisée_max),
            'Moyen': (pop_moyenne_min, pop_moyenne_max),
            'Populaire': (pop_populaire_min, pop_populaire_max)
        }
        niveaux = ['Aisé','Moyen','Populaire']
        results_B = []
        for niveau in niveaux:
            sub = df_valide[df_valide['zone_socioeco']==niveau]
            if sub.empty: continue
            f = sub['freq_num'].values; q = sub['volume_total_l'].values; t = sub['taille_menage'].values; L = sub['L'].values
            n = len(sub)
            def calc_V(f,q,t,L,pop):
                S_fq = np.sum(f*q); S_t = np.sum(t); S_fqL = np.sum(f*q*L)
                if S_fq==0 or S_t==0: return np.nan
                qpers = 12*S_fq/S_t
                beta = S_fqL/S_fq
                return pop*beta*qpers
            pop_min, pop_max = pop_bounds[niveau]
            B = 1000  # réduit pour performance
            V_boot = []
            for _ in range(B):
                idx = np.random.choice(n, size=n, replace=True)
                pop_sample = np.random.uniform(pop_min, pop_max)
                V_boot.append(calc_V(f[idx],q[idx],t[idx],L[idx], pop_sample))
            V_boot = np.array(V_boot); V_boot = V_boot[~np.isnan(V_boot)]
            if len(V_boot)==0: continue
            med = np.median(V_boot); q1 = np.percentile(V_boot,25); q3 = np.percentile(V_boot,75)
            demi_iqr = (q3-q1)/2
            S_fq = np.sum(f*q); S_t = np.sum(t); S_fqL = np.sum(f*q*L)
            qpers = 12*S_fq/S_t if S_t>0 else 0
            beta = S_fqL/S_fq if S_fq>0 else 0
            results_B.append({
                'Niveau': niveau,
                'Population': f"{fmt_volume(pop_min)} – {fmt_volume(pop_max)}",
                'Questionnaires valides': n,
                'qpers (L/pers/an)': fmt_nombre(qpers,2),
                'β (%)': f"{beta*100:.1f}%",
                'Volume SM annuel': f"{fmt_volume(med)} L ± {fmt_volume(demi_iqr)} L",
                '_vol_med': med, '_demi_iqr': demi_iqr
            })
        total_med_B = sum(r['_vol_med'] for r in results_B) if results_B else None
        total_demi_iqr_B = np.sqrt(sum(r['_demi_iqr']**2 for r in results_B)) if results_B else None
    else:
        total_med_B = None
        total_demi_iqr_B = None
    # --------------------------------------------------------------------
    # Tableau de détail par magasin
    # --------------------------------------------------------------------
    rows_mag_detail = []
    for mag in selected_mags:
        data = mag_data[mag]
        has_k = data['has_k']
        nb_q = data['nb_total_q']
        ti = data['ti']; qi = data['qi']
        Vh = data['Vh_huile_hebdo']
        vol_annuel = data['vol_annuel_med']
        if vol_annuel is not None:
            vol_annuel_str = f"{fmt_volume(vol_annuel)} L"
        else:
            vol_annuel_str = "N/A"
        Vh_str = f"{fmt_volume(Vh)} L" if Vh is not None else "N/A"
        rows_mag_detail.append({
            'Magasin': mag,
            'Chaîne': data['chaine'],
            'Comptages': 'Oui' if has_k else 'Non',
            'Q. SM': nb_q,
            'Taux achat': f"{ti*100:.1f}%" if ti is not None else "N/A",
            'Panier moy.': f"{fmt_nombre(qi,2)} L" if qi is not None else "N/A",
            'Volume huile / sem.': Vh_str,
            'Volume annuel estimé': vol_annuel_str,
        })
    df_mag_detail = pd.DataFrame(rows_mag_detail)
    # Volume par chaîne
    chaine_data = {}
    for mag, data in mag_data.items():
        ch = data['chaine'] or 'Indépendant'
        vol_annuel = data['vol_annuel_med']
        if vol_annuel is not None:
            chaine_data.setdefault(ch, []).append(vol_annuel)
    chaine_rows = []
    for ch, vals in chaine_data.items():
        med = np.median(vals)
        q1 = np.percentile(vals, 25)
        q3 = np.percentile(vals, 75)
        demi = (q3 - q1) / 2
        chaine_rows.append({
            'Chaîne': ch,
            'Nb magasins': len(vals),
            'Volume annuel médian': f"{fmt_volume(med)} L ± {fmt_volume(demi)} L"
        })
    df_chaine = pd.DataFrame(chaine_rows) if chaine_rows else pd.DataFrame()
    return {
        'mag_data': mag_data,
        'strata_A': df_strates_A,
        'total_A_med': median_total_A,
        'total_A_ci_low': ci_low_A,
        'total_A_ci_high': ci_high_A,
        'total_med_B': total_med_B,
        'total_demi_iqr_B': total_demi_iqr_B,
        'df_mag_detail': df_mag_detail,
        'df_chaine': df_chaine
    }

st.header("📊 Estimation du marché de l'huile de palme rouge à Kinshasa")
if df_sm.empty:
    st.error("Fichier supermarches.csv manquant.")
    st.stop()
if not selected_mags:
    st.warning("Aucun magasin sélectionné dans l'onglet Accueil.")
    st.stop()
# Paramètres de population (pour la méthode B)
st.markdown("**Populations de référence (Méthode B)**")
col_pop1, col_pop2, col_pop3 = st.columns(3)
with col_pop1:
    st.caption("Aisée")
    pop_aisée_min = st.number_input("Min", value=830000, step=5000, key="pop_aisée_min")
    pop_aisée_max = st.number_input("Max", value=1020000, step=5000, key="pop_aisée_max")
with col_pop2:
    st.caption("Moyenne")
    pop_moyenne_min = st.number_input("Min", value=3330000, step=10000, key="pop_moy_min")
    pop_moyenne_max = st.number_input("Max", value=4070000, step=10000, key="pop_moy_max")
with col_pop3:
    st.caption("Populaire")
    pop_populaire_min = st.number_input("Min", value=12500000, step=50000, key="pop_pop_min")
    pop_populaire_max = st.number_input("Max", value=15250000, step=50000, key="pop_pop_max")
# Boutons d'action
col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    lancer = st.button("🚀 Lancer / actualiser les calculs", key="run_market")
with col_btn2:
    if st.button("🔄 Vider le cache et recalculer"):
        st.cache_data.clear()
        st.session_state.pop('market_results', None)
        st.session_state.market_calculated = False
        st.rerun()
# Initialisation état
if 'market_calculated' not in st.session_state:
    st.session_state.market_calculated = False
if lancer or st.session_state.get('market_results') is not None:
    if lancer or st.session_state.get('market_results') is None:
        with st.spinner("Calculs en cours (optimisés)..."):
            # Préparer les profils secteur (avec sérialisation pour le cache)
            df_profils_pivot_ser = make_hashable(df_profils_pivot)   # <-- AJOUTÉ
            df_sm_ser = make_hashable(df_sm)                         # <-- AJOUTÉ
            secteur_profiles = prepare_secteur_profiles(df_profils_pivot_ser, df_sm_ser)  # <-- MODIFIÉ
            mapping_file = "magasin_mapping.json"
            magasin_mapping = {}
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    magasin_mapping = json.load(f)
            # Récupérer les k déjà calculés (sérialisation pour compatibilité cache)
            all_k_data = compute_all_k_data(
                tuple(selected_mags),
                make_hashable(df_c_f),
                df_sm,
                df_profils_pivot,
                make_hashable(secteur_profiles) if secteur_profiles is not None else None,
                magasin_mapping,
                load_k_overrides()
            )
            # Appel principal avec sérialisation des DataFrames
            results = compute_market_estimation(
                tuple(selected_mags),
                make_hashable(df_c_f),
                make_hashable(df_supermarche_full),
                df_sm,
                make_hashable(df_q_f_raw),
                df_profils_pivot,
                make_hashable(secteur_profiles) if secteur_profiles is not None else None,
                magasin_mapping,
                pop_aisée_min, pop_aisée_max,
                pop_moyenne_min, pop_moyenne_max,
                pop_populaire_min, pop_populaire_max,
                all_k_data=all_k_data
            )
            st.session_state.market_results = results
            st.session_state.market_calculated = True
    else:
        results = st.session_state.market_results
    # --- Affichage des résultats (inchangé) ---
    st.success("✅ Calculs terminés.")
    # Diagnostic
    with st.expander("🔍 Critères de magasin enquêté (diagnostic)", expanded=True):
        diag_rows = []
        for mag in selected_mags:
            data = results['mag_data'].get(mag, {})
            has_k = data.get('has_k', False)
            has_q = data.get('nb_total_q', 0) > 0
            can_estimate = data.get('Vh_huile_hebdo') is not None
            diag_rows.append({
                'Magasin': mag,
                'Comptages': 'Oui' if has_k else 'Non',
                'Questionnaires SM': 'Oui' if has_q else 'Non',
                'Volume huile estimable': 'Oui' if can_estimate else 'Non'
            })
        df_diag = pd.DataFrame(diag_rows)
        st.dataframe(df_diag, width='stretch')
        nb_est = sum(1 for d in diag_rows if d['Volume huile estimable'] == 'Oui')
        nb_q = sum(1 for d in diag_rows if d['Questionnaires SM'] == 'Oui')
        st.caption(f"{nb_q} magasin(s) avec questionnaires SM, {nb_est} magasin(s) avec volume huile estimable.")
    # ─── Méthode A (strates, estimateur par expansion) ───
    st.subheader("1. Méthode A – Strates (estimateur par expansion)")
    st.markdown(r"""
    **Principe :** Pour chaque strate (taille × niveau socio-économique), on calcule le volume total des magasins enquêtés, 
    puis on l'extrapole au nombre total de magasins de la strate (multiplication par \(N_s / n_s\)). 
    L'incertitude est estimée par bootstrap stratifié (500 réplications).
    """)
    strata_A = results['strata_A']
    st.dataframe(strata_A, width='stretch')
    total_A_med = results['total_A_med']
    total_A_ci_low = results['total_A_ci_low']
    total_A_ci_high = results['total_A_ci_high']
    st.metric(
        "Marché total annuel (Méthode A)",
        f"{fmt_volume(total_A_med)} L",
        help=f"Intervalle de confiance à 95% : [{fmt_volume(total_A_ci_low)} – {fmt_volume(total_A_ci_high)}] L"
    )
    st.caption(f"La valeur centrale est la médiane des volumes simulés. L'intervalle de confiance à 95% est [ {fmt_volume(total_A_ci_low)} – {fmt_volume(total_A_ci_high)} ] L.")
    st.session_state['strates_A'] = strata_A
    # ─── Méthode B (démographique) ───
    st.subheader("2. Méthode B – Approche démographique")
    if results['total_med_B'] is not None:
        st.metric(
            "Marché total annuel (Méthode B)",
            f"{fmt_volume(results['total_med_B'])} L ± {fmt_volume(results['total_demi_iqr_B'])} L"
        )
    else:
        st.info("Méthode B non calculable (données ménages insuffisantes).")
    # ─── Volumes par magasin ───
    st.subheader("3. Volumes estimés par magasin")
    df_mag_detail = results['df_mag_detail']
    st.dataframe(df_mag_detail, width='stretch')
    st.session_state['magasins_volumes'] = df_mag_detail
    # ─── Par chaîne ───
    if not results['df_chaine'].empty:
        st.subheader("4. Volume annuel médian par chaîne de magasins")
        st.dataframe(results['df_chaine'], width='stretch')
    # ─── Synthèse comparative ───
    st.subheader("5. Synthèse comparative")
    colA, colB = st.columns(2)
    with colA:
        st.metric("Méthode A (strates)", f"{fmt_volume(total_A_med)} L",
                  delta=f"IC 95% : [{fmt_volume(total_A_ci_low)} – {fmt_volume(total_A_ci_high)}] L")
    with colB:
        if results['total_med_B'] is not None:
            st.metric("Méthode B (démographique)",
                      f"{fmt_volume(results['total_med_B'])} L ± {fmt_volume(results['total_demi_iqr_B'])} L")
        else:
            st.metric("Méthode B", "N/A")
    # Stockage pour le rapport d'export
    st.session_state['total_A_med'] = results['total_A_med']
    st.session_state['total_A_ci_low'] = results['total_A_ci_low']
    st.session_state['total_A_ci_high'] = results['total_A_ci_high']
    st.session_state['total_med_B'] = results['total_med_B']
    st.session_state['total_demi_iqr_B'] = results['total_demi_iqr_B']
else:
    st.info("ℹ️ Cliquez sur « Lancer / actualiser les calculs » pour estimer le marché.")
# =====================================================================
# 6. Corrélations
# =====================================================================
st.subheader("6. Analyses de corrélation")
if 'market_results' in st.session_state:
    results = st.session_state.market_results
    corr_rows = []
    for mag, data in results['mag_data'].items():
        if data['freq_hebdo'] is not None or data['ti'] is not None:
            corr_rows.append({
                'Magasin': mag,
                'Fréquentation hebdo (clients)': data.get('freq_hebdo'),
                'Taux d\'achat (%)': data.get('ti', None) * 100 if data.get('ti') is not None else None,
                'Panier moyen (L)': data.get('qi'),
                'Volume huile / sem (L)': data.get('Vh_huile_hebdo'),
                'Volume annuel (L)': data.get('vol_annuel_med'),
                'Taille': data.get('taille'),
                'Niveau socio-éco': data.get('niveau'),
                'Taille x Niveau': f"{data.get('taille')} / {data.get('niveau')}"
            })
    df_corr = pd.DataFrame(corr_rows)
    if not df_corr.empty:
        # Fréquentation vs taille/niveau
        st.markdown("**Fréquentation vs. Taille et Niveau socio-économique**")
        col1, col2 = st.columns(2)
        with col1:
            fig1 = px.box(df_corr.dropna(subset=['Fréquentation hebdo (clients)']),
                          x='Taille', y='Fréquentation hebdo (clients)',
                          points="all", color='Taille',
                          title="Fréquentation hebdomadaire par Taille")
            fig1.update_layout(template="gilroy_export", showlegend=False)
            fig1 = force_black_axes(fig1)
            st.plotly_chart(fig1, width='stretch')
        with col2:
            fig2 = px.box(df_corr.dropna(subset=['Fréquentation hebdo (clients)']),
                          x='Niveau socio-éco', y='Fréquentation hebdo (clients)',
                          points="all", color='Niveau socio-éco',
                          title="Fréquentation hebdomadaire par Niveau")
            fig2.update_layout(template="gilroy_export", showlegend=False)
            fig2 = force_black_axes(fig2)
            st.plotly_chart(fig2, width='stretch')
        fig3 = px.box(df_corr.dropna(subset=['Fréquentation hebdo (clients)']),
                      x='Taille x Niveau', y='Fréquentation hebdo (clients)',
                      points="all", color='Taille x Niveau',
                      title="Fréquentation hebdomadaire par Taille × Niveau")
        fig3.update_layout(template="gilroy_export", showlegend=False, xaxis_tickangle=-45)
        fig3 = force_black_axes(fig3)
        st.plotly_chart(fig3, width='stretch')
        # Taux d'achat
        st.markdown("**Taux d'achat (%) vs. Taille et Niveau socio-économique**")
        col3, col4 = st.columns(2)
        with col3:
            fig4 = px.box(df_corr.dropna(subset=['Taux d\'achat (%)']),
                          x='Taille', y='Taux d\'achat (%)', points="all", color='Taille',
                          title="Taux d'achat par Taille")
            fig4.update_layout(template="gilroy_export", showlegend=False)
            fig4 = force_black_axes(fig4)
            st.plotly_chart(fig4, width='stretch')
        with col4:
            fig5 = px.box(df_corr.dropna(subset=['Taux d\'achat (%)']),
                          x='Niveau socio-éco', y='Taux d\'achat (%)', points="all", color='Niveau socio-éco',
                          title="Taux d'achat par Niveau")
            fig5.update_layout(template="gilroy_export", showlegend=False)
            fig5 = force_black_axes(fig5)
            st.plotly_chart(fig5, width='stretch')
        # Panier moyen
        st.markdown("**Panier moyen (L) vs. Taille et Niveau socio-économique**")
        col5, col6 = st.columns(2)
        with col5:
            fig6 = px.box(df_corr.dropna(subset=['Panier moyen (L)']),
                          x='Taille', y='Panier moyen (L)', points="all", color='Taille',
                          title="Panier moyen par Taille")
            fig6.update_layout(template="gilroy_export", showlegend=False)
            fig6 = force_black_axes(fig6)
            st.plotly_chart(fig6, width='stretch')
        with col6:
            fig7 = px.box(df_corr.dropna(subset=['Panier moyen (L)']),
                          x='Niveau socio-éco', y='Panier moyen (L)', points="all", color='Niveau socio-éco',
                          title="Panier moyen par Niveau")
            fig7.update_layout(template="gilroy_export", showlegend=False)
            fig7 = force_black_axes(fig7)
            st.plotly_chart(fig7, width='stretch')
        # Volume annuel
        st.markdown("**Volume annuel estimé (L) vs. Taille et Niveau socio-économique**")
        col7, col8 = st.columns(2)
        with col7:
            fig8 = px.box(df_corr.dropna(subset=['Volume annuel (L)']),
                          x='Taille', y='Volume annuel (L)', points="all", color='Taille',
                          title="Volume annuel par Taille")
            fig8.update_layout(template="gilroy_export", showlegend=False)
            fig8 = force_black_axes(fig8)
            st.plotly_chart(fig8, width='stretch')
        with col8:
            fig9 = px.box(df_corr.dropna(subset=['Volume annuel (L)']),
                          x='Niveau socio-éco', y='Volume annuel (L)', points="all", color='Niveau socio-éco',
                          title="Volume annuel par Niveau")
            fig9.update_layout(template="gilroy_export", showlegend=False)
            fig9 = force_black_axes(fig9)
            st.plotly_chart(fig9, width='stretch')
        fig10 = px.box(df_corr.dropna(subset=['Volume annuel (L)']),
                       x='Taille x Niveau', y='Volume annuel (L)', points="all", color='Taille x Niveau',
                       title="Volume annuel par Taille × Niveau")
        fig10.update_layout(template="gilroy_export", showlegend=False, xaxis_tickangle=-45)
        fig10 = force_black_axes(fig10)
        st.plotly_chart(fig10, width='stretch')
    else:
        st.info("Aucune donnée pour les corrélations.")
# ------------------------------------------------------------
# ONGLET 6 : PRIX & CONCURRENCE 
# ------------------------------------------------------------
