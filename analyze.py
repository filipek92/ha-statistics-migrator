import sqlite3
import os
from datetime import datetime

# Seznam cest k prohledání
POTENTIAL_PATHS = [
    'home-assistant_v2.db',
    '/config/home-assistant_v2.db',
    './config/home-assistant_v2.db',
    '../config/home-assistant_v2.db'
]

def find_db():
    for path in POTENTIAL_PATHS:
        if os.path.exists(path):
            return path
    return None

def diagnose_sensor(db_path, entity_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"\n{'='*60}")
    print(f"DIAGNOSTIKA ENTITY: {entity_id}")
    print(f"{'='*60}")

    # 1. Kontrola metadat (ID, jednotky, typy)
    cursor.execute("""
        SELECT id, unit_of_measurement, has_mean, has_sum 
        FROM statistics_meta WHERE statistic_id = ?
    """, (entity_id,))
    meta = cursor.fetchone()
    
    if not meta:
        print(f"❌ Chyba: Entita {entity_id} nebyla v tabulce metadata nalezena.")
        return

    m_id, unit, h_mean, h_sum = meta
    print(f"Interní ID v DB: {m_id}")
    print(f"Jednotka:       {unit if unit else 'NENASTAVENA!'}")
    print(f"Typ statistik:  {'Průměry (Mean)' if h_mean else 'Součty (Sum)'}")
    
    if not h_mean:
        print("⚠️ VAROVÁNÍ: Senzor hladiny by měl mít 'has_mean=1', jinak se v grafech nemusí zobrazit!")

    # 2. Detailní pohled na zlomové období (kolem 21.2.2026)
    print(f"\n--- Srovnání dat kolem 21.02.2026 ---")
    print(f"{'Období':<10} | {'Čas (Local)':<20} | {'Mean':<10} | {'Min':<10} | {'Max':<10}")
    print("-" * 65)

    query = """
    SELECT * FROM (
        SELECT 'STARŠÍ' as p, datetime(start_ts, 'unixepoch', 'localtime'), mean, min, max 
        FROM statistics WHERE metadata_id = ? AND start_ts < strftime('%s', '2026-02-21 00:00:00') 
        ORDER BY start_ts DESC LIMIT 5
    )
    UNION ALL
    SELECT * FROM (
        SELECT 'NOVĚJŠÍ' as p, datetime(start_ts, 'unixepoch', 'localtime'), mean, min, max 
        FROM statistics WHERE metadata_id = ? AND start_ts >= strftime('%s', '2026-02-21 00:00:00') 
        ORDER BY start_ts ASC LIMIT 5
    )
    """
    cursor.execute(query, (m_id, m_id))
    rows = cursor.fetchall()
    
    for r in rows:
        print(f"{r[0]:<10} | {r[1]:<20} | {str(r[2]):<10} | {str(r[3]):<10} | {str(r[4]):<10}")

    # 3. Kontrola duplicitních metadat (častý problém při migraci)
    cursor.execute("SELECT id, statistic_id FROM statistics_meta WHERE statistic_id LIKE ?", (f"%{entity_id.split('.')[-1]}%",))
    duplicates = cursor.fetchall()
    if len(duplicates) > 1:
        print(f"\n⚠️ POZOR: Nalezeny další podobné záznamy v metadatech: {duplicates}")
        print("To může znamenat, že historie je rozdělená pod dvěma různými vnitřními ID!")

    conn.close()

def main():
    db_path = find_db()
    if not db_path:
        print("❌ Soubor home-assistant_v2.db nebyl nalezen.")
        db_path = input("Zadej cestu k DB ručně: ")
        if not os.path.exists(db_path): return

    print(f"✅ Používám databázi: {db_path}")
    
    target_entity = "sensor.sprava_vodovodu_cerpadla_vykon"
    diagnose_sensor(db_path, target_entity)

if __name__ == "__main__":
    main()