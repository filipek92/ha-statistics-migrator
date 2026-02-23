import sqlite3

DB_PATH = '/config/home-assistant_v2.db'
ENTITY_ID = 'sensor.sprava_vodovodu_cerpadla_vykon'

def fix_metadata():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Nejdřív zjistíme současný stav
    cursor.execute("SELECT id, has_mean, has_sum FROM statistics_meta WHERE statistic_id = ?", (ENTITY_ID,))
    row = cursor.fetchone()
    
    if not row:
        print("Entita nenalezena.")
        return

    m_id, h_mean, h_sum = row
    print(f"Původní nastavení pro ID {m_id}: has_mean={h_mean}, has_sum={h_sum}")

    # 2. Provedeme opravu
    try:
        cursor.execute("""
            UPDATE statistics_meta 
            SET has_mean = 1, has_sum = 0 
            WHERE id = ?
        """, (m_id,))
        
        conn.commit()
        print("✅ Úspěšně opraveno! Nastaveno has_mean=1 a has_sum=0.")
        print("Nyní restartuj Home Assistant, aby se projevily změny v grafech.")
    except Exception as e:
        print(f"❌ Chyba při zápisu: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_metadata()