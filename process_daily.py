#!/usr/bin/env python3
"""
process_daily.py – Traitement quotidien des exports CSV de l'enquête.
Placez les fichiers CSV dans "input/" et lancez ce script.
NOTE: Les anomalies ne sont plus calculées ici. Elles sont calculées dynamiquement par le dashboard.
"""

import os, csv, sqlite3, json
from datetime import datetime
from uuid import UUID

INPUT_DIR = "input"
OUTPUT_DIR = "output"
ARCHIVE_DIR = "archive"
DB_PATH = "consolidated.db"

def log(msg, level="INFO"):
    print(f"[{datetime.now():%H:%M:%S}] [{level}] {msg}", flush=True)

# ----------------------------------------------------------------------
# Base de données
# ----------------------------------------------------------------------
def create_db(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS questionnaires (
        uuid TEXT PRIMARY KEY, type TEXT, date TEXT, heure TEXT,
        lieu TEXT, enqueteur TEXT, test_mode INTEGER, statut TEXT,
        anomalies TEXT, data TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS countings (
        uuid TEXT PRIMARY KEY, date TEXT, debut TEXT, fin TEXT,
        lieu TEXT, enqueteur TEXT, test_mode INTEGER, total INTEGER,
        anomalies TEXT, data TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS prices (
        uuid TEXT PRIMARY KEY, date TEXT, supermarche TEXT, marque TEXT,
        conditionnement TEXT, prix REAL, enqueteur TEXT, test_mode INTEGER,
        anomalies TEXT, data TEXT)""")
    conn.commit()

# ----------------------------------------------------------------------
# Parsing CSV
# ----------------------------------------------------------------------
def parse_section(lines, start_idx, section_name):
    i = start_idx + 1
    headers = None
    data_rows = []
    while i < len(lines) and not lines[i].strip().startswith('=== '):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        try:
            reader = csv.reader([line])
            row = next(reader)
        except Exception as e:
            log(f"Ligne {i+1} ignorée (erreur CSV) : {e}", "WARN")
            i += 1
            continue
        if headers is None:
            headers = [h.strip() for h in row]
            log(f"En-têtes de la section '{section_name}' : {len(headers)} colonnes")
        else:
            if len(row) == len(headers):
                data_rows.append(row)
            else:
                log(f"Ligne {i+1} ignorée : nombre de colonnes incorrect", "WARN")
        i += 1
    return headers, data_rows, i

def record_from_row(headers, row):
    return {headers[i]: row[i] for i in range(len(headers))}

# ----------------------------------------------------------------------
# Insertions sans calcul d'anomalies
# ----------------------------------------------------------------------
def _is_valid_uuid(uuid_str):
    try:
        UUID(uuid_str)
        return True
    except:
        log(f"UUID invalide : {uuid_str}", "WARN")
        return False

def insert_questionnaire(conn, qtype, record):
    uuid = record.get('UUID', '').strip()
    if not uuid or not _is_valid_uuid(uuid):
        return False
    c = conn.cursor()
    c.execute('SELECT uuid FROM questionnaires WHERE uuid = ?', (uuid,))
    if c.fetchone():
        log(f"Doublon questionnaire ignoré : {uuid}", "WARN")
        return False

    date = record.get('Date', '')
    heure = record.get('Heure', '')
    enqueteur = record.get('Enquêteur', '')
    test_mode = 1 if record.get('Mode test', '').strip().lower() == 'oui' else 0
    statut = record.get('Statut', 'Accepté')
    lieu = ''
    if qtype == 'supermarche':
        lieu = record.get('Supermarché', '')
    elif qtype == 'menage':
        lieu = record.get('Commune', '')
    elif qtype == 'supermarche_menage':
        origine = record.get("Supermarché d'origine", '')
        commune = record.get('Commune', '')
        lieu = f"{origine} → {commune}"

    # Pas d'anomalies calculées ici
    anomalies = "[]"

    try:
        c.execute("""INSERT INTO questionnaires (uuid, type, date, heure, lieu, enqueteur, test_mode, statut, anomalies, data)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (uuid, qtype, date, heure, lieu, enqueteur, test_mode, statut,
                   anomalies,
                   json.dumps(record, ensure_ascii=False)))
        conn.commit()
        log(f"Insertion questionnaire OK : {uuid}")
        return True
    except Exception as e:
        log(f"Erreur insertion questionnaire {uuid} : {e}", "ERROR")
        return False

def insert_counting(conn, record):
    uuid = record.get('UUID', '').strip()
    if not uuid or not _is_valid_uuid(uuid):
        return False
    c = conn.cursor()
    c.execute('SELECT uuid FROM countings WHERE uuid = ?', (uuid,))
    if c.fetchone():
        log(f"Doublon comptage ignoré : {uuid}", "WARN")
        return False

    date = record.get('Date', '')
    debut = record.get('Heure début', '')
    fin = record.get('Heure fin', '')
    lieu = record.get('Supermarché', '')
    enqueteur = record.get('Enquêteur', '')
    test_mode = 1 if record.get('Mode test', '').strip().lower() == 'oui' else 0
    total_str = record.get('Total', '0')
    try:
        total = int(total_str)
    except:
        total = 0

    # Calcul de la durée en minutes (pour filtrage, mais on garde les mêmes règles)
    try:
        fmt = '%H:%M:%S'
        t1 = datetime.strptime(debut, fmt)
        t2 = datetime.strptime(fin, fmt)
        duree_minutes = (t2 - t1).total_seconds() / 60.0
    except:
        duree_minutes = 0

    # Filtrage des comptages non significatifs (inchangé)
    if total < 10:
        log(f"Comptage ignoré (total < 10) : {uuid} - total={total}", "WARN")
        return False
    if duree_minutes < 10:
        log(f"Comptage ignoré (durée < 10 min) : {uuid} - durée={duree_minutes:.1f} min", "WARN")
        return False

    anomalies = "[]"

    try:
        c.execute("""INSERT INTO countings (uuid, date, debut, fin, lieu, enqueteur, test_mode, total, anomalies, data)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (uuid, date, debut, fin, lieu, enqueteur, test_mode, total,
                   anomalies,
                   json.dumps(record, ensure_ascii=False)))
        conn.commit()
        log(f"Insertion comptage OK : {uuid}")
        return True
    except Exception as e:
        log(f"Erreur insertion comptage {uuid} : {e}", "ERROR")
        return False

def insert_price(conn, record):
    uuid = record.get('UUID', '').strip()
    if not uuid or not _is_valid_uuid(uuid):
        return False
    c = conn.cursor()
    c.execute('SELECT uuid FROM prices WHERE uuid = ?', (uuid,))
    if c.fetchone():
        log(f"Doublon prix ignoré : {uuid}", "WARN")
        return False

    date = record.get('Date', '')
    supermarche = record.get('Supermarché', '')
    marque = record.get('Marque', '')
    conditionnement = record.get('Conditionnement', '')
    prix_str = record.get('Prix', '')
    try:
        prix = float(prix_str.replace(',', '.'))
    except:
        prix = 0.0
    enqueteur = record.get('Enquêteur', '')
    test_mode = 1 if record.get('Mode test', '').strip().lower() == 'oui' else 0

    anomalies = "[]"

    try:
        c.execute("""INSERT INTO prices (uuid, date, supermarche, marque, conditionnement, prix, enqueteur, test_mode, anomalies, data)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (uuid, date, supermarche, marque, conditionnement, prix, enqueteur, test_mode,
                   anomalies,
                   json.dumps(record, ensure_ascii=False)))
        conn.commit()
        log(f"Insertion prix OK : {uuid}")
        return True
    except Exception as e:
        log(f"Erreur insertion prix {uuid} : {e}", "ERROR")
        return False

# ----------------------------------------------------------------------
# Traitement d'un fichier
# ----------------------------------------------------------------------
def process_file(filepath, conn):
    log(f"Traitement du fichier : {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    except Exception as e:
        log(f"Impossible de lire le fichier : {e}", "ERROR")
        return

    lines = content.splitlines()
    log(f"Fichier chargé, {len(lines)} lignes")
    i = 0
    counts = {"supermarche": 0, "menage": 0, "supermarche_menage": 0, "comptages": 0, "prix": 0}

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('=== QUESTIONNAIRES SUPERMARCHÉ ==='):
            headers, data, next_i = parse_section(lines, i, "supermarche")
            if headers and 'UUID' in headers:
                for row in data:
                    record = record_from_row(headers, row)
                    if insert_questionnaire(conn, 'supermarche', record):
                        counts["supermarche"] += 1
            i = next_i
        elif line.startswith('=== QUESTIONNAIRES MÉNAGE ==='):
            headers, data, next_i = parse_section(lines, i, "menage")
            if headers and 'UUID' in headers:
                for row in data:
                    record = record_from_row(headers, row)
                    if insert_questionnaire(conn, 'menage', record):
                        counts["menage"] += 1
            i = next_i
        elif line.startswith('=== QUESTIONNAIRES SUPERMARCHÉ → MÉNAGE ==='):
            headers, data, next_i = parse_section(lines, i, "supermarche_menage")
            if headers and 'UUID' in headers:
                for row in data:
                    record = record_from_row(headers, row)
                    if insert_questionnaire(conn, 'supermarche_menage', record):
                        counts["supermarche_menage"] += 1
            i = next_i
        elif line.startswith('=== COMPTAGES ==='):
            headers, data, next_i = parse_section(lines, i, "comptages")
            if headers and 'UUID' in headers:
                for row in data:
                    record = record_from_row(headers, row)
                    if insert_counting(conn, record):
                        counts["comptages"] += 1
            i = next_i
        elif line.startswith('=== PRIX ==='):
            headers, data, next_i = parse_section(lines, i, "prix")
            if headers and 'UUID' in headers:
                for row in data:
                    record = record_from_row(headers, row)
                    if insert_price(conn, record):
                        counts["prix"] += 1
            i = next_i
        else:
            i += 1

    log(f"Résumé pour {os.path.basename(filepath)} : "
        f"Supermarche={counts['supermarche']}, "
        f"Ménage={counts['menage']}, "
        f"SM→Ménage={counts['supermarche_menage']}, "
        f"Comptages={counts['comptages']}, "
        f"Prix={counts['prix']}")

# ----------------------------------------------------------------------
# Exports (inchangés)
# ----------------------------------------------------------------------
def export_all(conn):
    c = conn.cursor()
    # Questionnaires valides (anomalies vide)
    c.execute("SELECT * FROM questionnaires WHERE test_mode = 0 AND statut = 'Accepté' AND anomalies = '[]'")
    with open(os.path.join(OUTPUT_DIR, 'merged_valid_questionnaires.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([desc[0] for desc in c.description])
        writer.writerows(c.fetchall())

    # Comptages valides
    c.execute("SELECT * FROM countings WHERE test_mode = 0 AND anomalies = '[]'")
    with open(os.path.join(OUTPUT_DIR, 'merged_valid_countings.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([desc[0] for desc in c.description])
        writer.writerows(c.fetchall())

    # Prix valides
    c.execute("SELECT * FROM prices WHERE test_mode = 0 AND anomalies = '[]'")
    with open(os.path.join(OUTPUT_DIR, 'merged_valid_prices.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([desc[0] for desc in c.description])
        writer.writerows(c.fetchall())

    # Anomalies (ne sera jamais rempli, mais on garde)
    with open(os.path.join(OUTPUT_DIR, 'anomalies.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['table', 'uuid', 'anomalies'])
        for table in ['questionnaires', 'countings', 'prices']:
            c.execute(f"SELECT uuid, anomalies FROM {table} WHERE anomalies != '[]'")
            for row in c.fetchall():
                writer.writerow([table, row[0], row[1]])

    # Test data
    with open(os.path.join(OUTPUT_DIR, 'test_data.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['table', 'uuid', 'enqueteur', 'date', 'data'])
        for table, date_col, enqueteur_col in [('questionnaires', 'date', 'enqueteur'),
                                               ('countings', 'date', 'enqueteur'),
                                               ('prices', 'date', 'enqueteur')]:
            c.execute(f"SELECT uuid, {date_col}, {enqueteur_col}, data FROM {table} WHERE test_mode = 1")
            for row in c.fetchall():
                writer.writerow([table, row[0], row[2], row[1], row[3]])

    log("Exports terminés.")

# ----------------------------------------------------------------------
def main():
    for d in [OUTPUT_DIR, ARCHIVE_DIR, INPUT_DIR]:
        os.makedirs(d, exist_ok=True)

    csv_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.csv')]
    if not csv_files:
        log("Aucun fichier CSV trouvé dans le dossier 'input/'.")
        return

    log(f"{len(csv_files)} fichier(s) CSV trouvé(s) dans 'input/'.")
    conn = sqlite3.connect(DB_PATH)
    create_db(conn)

    for filename in csv_files:
        filepath = os.path.join(INPUT_DIR, filename)
        try:
            process_file(filepath, conn)
        except Exception as e:
            log(f"ERREUR inattendue lors du traitement de {filename} : {e}", "ERROR")
            continue

        try:
            os.rename(filepath, os.path.join(ARCHIVE_DIR, filename))
            log(f"Fichier archivé : {filename}")
        except Exception as e:
            log(f"Impossible d'archiver {filename} : {e}", "ERROR")

    export_all(conn)
    conn.close()
    log("Traitement terminé avec succès.")

if __name__ == '__main__':
    main()