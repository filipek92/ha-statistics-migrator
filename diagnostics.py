import sqlite3

DB_PATH = '/config/home-assistant_v2.db'
ENTITY_ID = 'sensor.sprava_vodovodu_hladina_vrtu'

def deep_check(db_path, entity_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"--- Hloubková kontrola konfliktů ---")
    
    # 1. Hledáme VŠECHNA metadata pro toto jméno
    cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
    metas = cursor.fetchall()
    
    print(f"Nalezena metadata v DB ({len(metas)}x):")
    for m in metas:
        print(f"  -> ID: {m[0]}, Identifikátor: {m[1]}, Jednotka: {m[2]}")
        # Pro každé ID spočítáme záznamy
        cursor.execute("SELECT COUNT(*) FROM statistics WHERE metadata_id = ?", (m[0],))
        count = cursor.fetchone()[0]
        print(f"     Počet datových bodů pro toto ID: {count}")

    # 2. Kontrola stavu v tabulce states (aktuální stav v HA)
    print(f"\n--- Aktuální stav entity v HA (tabulka states) ---")
    cursor.execute("SELECT state_id, state, last_updated_ts FROM states_meta sm JOIN states s ON sm.metadata_id = s.metadata_id WHERE sm.entity_id = ? ORDER BY s.last_updated_ts DESC LIMIT 1", (entity_id,))
    state = cursor.fetchone()
    if state:
        print(f"  Aktuální hodnota v HA: {state[1]}")
    else:
        print("  ⚠️ Entita nemá žádný aktuální stav v tabulce states!")

    conn.close()

if __name__ == "__main__":
    deep_check(DB_PATH, ENTITY_ID)
