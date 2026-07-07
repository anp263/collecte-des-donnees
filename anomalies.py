"""
anomalies.py – Détection et validation des anomalies
"""
import json
import numpy as np
from datetime import datetime

from config import DEFAULT_ANOMALY_SETTINGS, ANOMALY_SETTINGS_FILE
from utils import parse_gps, haversine, extraire_litres


# ──────────────────────────────────────────────
# Gestion des paramètres
# ──────────────────────────────────────────────

def load_anomaly_settings():
    import os
    if os.path.exists(ANOMALY_SETTINGS_FILE):
        with open(ANOMALY_SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_ANOMALY_SETTINGS.copy()


def save_anomaly_settings(settings):
    with open(ANOMALY_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ──────────────────────────────────────────────
# Validation intrinsèque
# ──────────────────────────────────────────────

def validate_questionnaire_dynamic(record, qtype, settings):
    """Validation intrinsèque paramétrable (UUID, prix/L, volume)."""
    anomalies = []

    if qtype == "supermarche":
        quantite_str = record.get('Q4_Quantité', '')
        prix_str = record.get('Q5_PrixPayé', '')
        if quantite_str and prix_str:
            vol = extraire_litres(quantite_str)
            try:
                prix = float(prix_str.replace(',', '.'))
                if vol and vol > 0:
                    prix_litre = prix / vol
                    if prix_litre < settings['prix_litre_min_fc'] or prix_litre > settings['prix_litre_max_fc']:
                        anomalies.append(f'Prix/litre hors normes ({prix_litre:.0f} FC/L)')
            except:
                pass

    elif qtype in ("menage", "supermarche_menage"):
        nb = record.get('Q4_Quantite_Nombre', '')
        cont = record.get('Q4_Quantite_Contenant', '')
        vol_unit_str = record.get('Q4_Quantite_VolumeUnitaire', '')
        prix_hab_str = record.get('Q5_PrixHabituel', '')
        if nb and cont and vol_unit_str:
            try:
                nb_int = int(nb)
                vol_unit = float(vol_unit_str.replace(',', '.'))
                vol_total = nb_int * vol_unit
                if vol_total > settings['volume_max_litres']:
                    anomalies.append(f'Volume acheté supérieur à {settings["volume_max_litres"]} L ({vol_total} L)')
                if prix_hab_str:
                    prix = float(prix_hab_str.replace(',', '.'))
                    if vol_total > 0:
                        prix_litre = prix / vol_total
                        if prix_litre < settings['prix_litre_min_fc'] or prix_litre > settings['prix_litre_max_fc']:
                            anomalies.append(f'Prix/litre hors normes ({prix_litre:.0f} FC/L)')
            except:
                pass

    return anomalies


def validate_counting_dynamic(record, settings):
    """Validation des comptages paramétrable."""
    anomalies = []
    debut = record.get('Heure début', '')
    fin = record.get('Heure fin', '')
    total_str = record.get('Total', '0')
    try:
        total = int(total_str)
        if debut and fin:
            fmt = '%H:%M:%S'
            t1 = datetime.strptime(debut, fmt)
            t2 = datetime.strptime(fin, fmt)
            duree = (t2 - t1).total_seconds() / 3600.0
            if duree > settings['duree_max_heures']:
                anomalies.append(f'Durée > {settings["duree_max_heures"]} h ({duree:.1f} h)')
            if duree > 0.5 and total == 0:
                anomalies.append('Durée > 30 min avec 0 sorties')
            if duree > 0 and total > 0 and (total / duree) > settings['taux_sortie_max_par_heure']:
                anomalies.append(f'Taux de sortie > {settings["taux_sortie_max_par_heure"]}/h ({total/duree:.0f}/h)')
    except:
        pass
    return anomalies


def validate_price_dynamic(record, settings):
    """Validation des prix paramétrable."""
    anomalies = []
    prix_str = record.get('Prix', '')
    try:
        prix = float(prix_str.replace(',', '.'))
        if prix < settings['prix_min_fc'] or prix > settings['prix_max_fc']:
            anomalies.append(f'Prix hors plage raisonnable ({prix} FC)')
    except:
        pass
    return anomalies


# ──────────────────────────────────────────────
# Validation contextuelle
# ──────────────────────────────────────────────

def compute_context_anomalies_questionnaire_dynamic(conn, uuid, record, qtype, settings):
    """Validation contextuelle paramétrable (intervalles, GPS)."""
    anomalies = []
    anom_counter = 1
    c = conn.cursor()
    date_str = record.get('Date', '')
    heure_str = record.get('Heure', '')
    if not date_str or not heure_str:
        return anomalies
    try:
        dt_new = datetime.strptime(f"{date_str} {heure_str}", '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return anomalies
    enqueteur = record.get('Enquêteur', '')

    c.execute("""
        SELECT uuid, type, date, heure, statut, data FROM questionnaires
        WHERE enqueteur = ? AND (type = 'supermarche' OR type = 'supermarche_menage')
          AND uuid != ?
        ORDER BY date, heure
    """, (enqueteur, uuid))
    existing_rows = c.fetchall()

    seq = []
    for row in existing_rows:
        r_uuid, r_type, r_date, r_heure, r_statut, r_data_json = row
        data = json.loads(r_data_json) if r_data_json else {}
        achat = data.get('Q3_Achat', '').strip().lower() if r_type == 'supermarche_menage' else None
        seq.append({
            'uuid': r_uuid, 'type': r_type, 'date': r_date, 'heure': r_heure,
            'statut': r_statut, 'achat': achat
        })

    new_achat = None
    if qtype == 'supermarche_menage':
        new_achat = record.get('Q3_Achat', '').strip().lower()
    seq.append({
        'uuid': uuid, 'type': qtype, 'date': date_str, 'heure': heure_str,
        'statut': record.get('Statut', ''), 'achat': new_achat
    })
    seq.sort(key=lambda x: (x['date'], x['heure']))

    for i in range(len(seq) - 1):
        prev = seq[i]
        curr = seq[i + 1]
        if prev['uuid'] != uuid and curr['uuid'] != uuid:
            continue
        try:
            dt_prev = datetime.strptime(f"{prev['date']} {prev['heure']}", '%Y-%m-%d %H:%M:%S')
            dt_curr = datetime.strptime(f"{curr['date']} {curr['heure']}", '%Y-%m-%d %H:%M:%S')
            delta = (dt_curr - dt_prev).total_seconds()
        except:
            continue

        if prev['statut'] == 'Refus':
            if delta < settings['refus_min_secondes']:
                anomalies.append(
                    f"[{anom_counter}] Refus trop rapproché ({delta:.0f} s) "
                    f"- {curr['type']} après {prev['type']} (min {settings['refus_min_secondes']} s)"
                )
                anom_counter += 1
            continue

        if curr['type'] == 'supermarche_menage' and prev['type'] == 'supermarche':
            continue
        if prev['type'] == 'supermarche_menage' and prev['achat'] == 'non':
            continue

        if delta < settings['intervalle_min_secondes']:
            anomalies.append(
                f"[{anom_counter}] Intervalle trop court entre {curr['type']} et {prev['type']} "
                f"({delta:.0f} s) – minimum {settings['intervalle_min_secondes']}s "
                f"(précédent UUID: {prev['uuid']})"
            )
            anom_counter += 1

    # Vérification GPS
    gps_str = record.get('GPS', '')
    lat_new, lon_new = parse_gps(gps_str)
    if lat_new is None or lon_new is None:
        return anomalies

    if qtype in ('supermarche', 'supermarche_menage'):
        if qtype == 'supermarche':
            lieu = record.get('Supermarché', '')
        else:
            lieu = record.get("Supermarché d'origine", '')
        if lieu:
            c.execute("""
                SELECT uuid, type, data FROM questionnaires
                WHERE (type = 'supermarche' OR type = 'supermarche_menage')
                  AND lieu = ? AND uuid != ?
            """, (lieu, uuid))
            coords = []
            for row in c.fetchall():
                _, _, other_data_json = row
                try:
                    other_rec = json.loads(other_data_json)
                    olat, olon = parse_gps(other_rec.get('GPS', ''))
                    if olat is not None and olon is not None:
                        coords.append((olat, olon))
                except:
                    pass
            if coords:
                lats = [c[0] for c in coords]
                lons = [c[1] for c in coords]
                lat_med = np.median(lats)
                lon_med = np.median(lons)
                dist = haversine(lat_new, lon_new, lat_med, lon_med)
                seuil_km = settings['distance_gps_questionnaire_m'] / 1000.0
                if dist > seuil_km:
                    anomalies.append(
                        f"[{anom_counter}] Distance GPS > {settings['distance_gps_questionnaire_m']} m "
                        f"par rapport à la médiane de '{lieu}' ({dist * 1000:.0f} m)"
                    )
                    anom_counter += 1

    elif qtype == 'menage':
        lat_str = f"{lat_new:.5f}"
        lon_str = f"{lon_new:.5f}"
        c.execute("SELECT uuid, data FROM questionnaires WHERE type = 'menage' AND uuid != ?", (uuid,))
        for row in c.fetchall():
            other_uuid, other_data_json = row
            try:
                other_rec = json.loads(other_data_json)
                olat, olon = parse_gps(other_rec.get('GPS', ''))
                if olat is not None and olon is not None:
                    if f"{olat:.5f}" == lat_str and f"{olon:.5f}" == lon_str:
                        anomalies.append(
                            f"[{anom_counter}] Coordonnées GPS identiques à un autre ménage ({lat_str}, {lon_str})"
                        )
                        anom_counter += 1
                        break
            except:
                pass

    return anomalies


def compute_context_anomalies_counting_dynamic(conn, uuid, record, settings):
    """Validation contextuelle des comptages (GPS)."""
    anomalies = []
    anom_counter = 1
    gps_str = record.get('GPS', '')
    lat_new, lon_new = parse_gps(gps_str)
    if lat_new is None or lon_new is None:
        return anomalies
    lieu = record.get('Supermarché', '')
    if not lieu:
        return anomalies
    c = conn.cursor()
    c.execute("SELECT uuid, data FROM countings WHERE lieu = ? AND uuid != ?", (lieu, uuid))
    coords = []
    for row in c.fetchall():
        other_uuid, other_data = row
        try:
            other_rec = json.loads(other_data)
            olat, olon = parse_gps(other_rec.get('GPS', ''))
            if olat is not None and olon is not None:
                coords.append((olat, olon))
        except:
            pass
    if coords:
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        lat_med = np.median(lats)
        lon_med = np.median(lons)
        dist = haversine(lat_new, lon_new, lat_med, lon_med)
        seuil_km = settings['distance_gps_comptage_m'] / 1000.0
        if dist > seuil_km:
            anomalies.append(
                f"[{anom_counter}] Distance GPS > {settings['distance_gps_comptage_m']} m "
                f"par rapport à la médiane des comptages du même supermarché "
                f"'{lieu}' ({dist * 1000:.0f} m)"
            )
    return anomalies


# ──────────────────────────────────────────────
# Base de données anomalies
# ──────────────────────────────────────────────

def init_anomalies_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS anomalies_dashboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT,
            type TEXT,
            date TEXT,
            enqueteur TEXT,
            anomaly_text TEXT,
            settings_hash TEXT,
            created_at TEXT
        )
    """)
    conn.commit()


def load_anomalies_from_db(conn, settings_hash):
    cur = conn.cursor()
    cur.execute(
        "SELECT uuid, type, date, enqueteur, anomaly_text "
        "FROM anomalies_dashboard WHERE settings_hash = ?",
        (settings_hash,)
    )
    rows = cur.fetchall()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def save_anomalies_to_db(conn, anomalies, settings_hash):
    cur = conn.cursor()
    cur.execute("DELETE FROM anomalies_dashboard WHERE settings_hash = ?", (settings_hash,))
    now = datetime.now().isoformat()
    for (uuid_val, typ, date_val, enqueteur, text) in anomalies:
        cur.execute(
            "INSERT INTO anomalies_dashboard (uuid, type, date, enqueteur, anomaly_text, settings_hash, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uuid_val, typ, date_val, enqueteur, text, settings_hash, now)
        )
    conn.commit()
