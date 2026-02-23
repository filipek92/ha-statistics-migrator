import sqlite3
import os
import shutil
from datetime import datetime

def format_ts(ts):
    if ts is None: return "N/A"
    return datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M:%S')

def main():
    db_path = '/config/home-assistant_v2.db' if os.path.exists('/config/home-assistant_v2.db') else 'home-assistant_v2.db'
    
    print("="*70)
    print("🛡️  HA ORPHAN & TIME-LINE MIGRATOR 2026")
    print(f"📂 Databáze: {os.path.abspath(db_path)}")
    print("="*70)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. TVOJE SQL LOGIKA - Nabídka skutečných sirotků
    query_orphans = """
    SELECT a.id, a.statistic_id, a.unit_of_measurement
    FROM statistics_meta as a
    LEFT JOIN states_meta as b ON b.entity_id = a.statistic_id
    WHERE b.metadata_id IS NULL
    """
    cursor.execute(query_orphans)
    orphans = cursor.fetchall()

    if not orphans:
        print("\n✅ Žádní sirotci podle SQL nenalezeni. Můžeš hledat ručně [S].")
    else:
        print(f"\n📍 NALEZENÍ SIROTCI ({len(orphans)}):")
        print(f"{'Idx':<5} | {'Entity ID':<50} | {'Jednotka'}")
        print("-" * 75)
        for i, (mid, eid, unit) in enumerate(orphans):
            print(f" [{i+1:>2}] | {eid:<50} | {unit}")

    # 2. VÝBĚR ZDROJE (STARÉ ENTITY)
    choice = input("\nVyber číslo sirotka, nebo [S] pro ruční hledání: ").lower()
    
    if choice == 's':
        search = input("Zadej část názvu staré entity: ")
        cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ?", (f'%{search}%',))
        search_res = cursor.fetchall()
        if not search_res: print("❌ Nic nenalezeno."); return
        for i, (mid, eid, unit) in enumerate(search_res):
            print(f" [{i+1}] ID:{mid} | {eid} ({unit})")
        idx = int(input("Vyber číslo: ")) - 1
        old_mid, old_eid, old_unit = search_res[idx]
    elif choice.isdigit():
        idx = int(choice) - 1
        old_mid, old_eid, old_unit = orphans[idx]
    else:
        return

    # 3. CHYTRÁ NABÍDKA CÍLE (Smart-Match)
    # Zkusíme najít kandidáty, co mají podobný název a jsou aktivní v states_meta
    print(f"\n🔍 Hledám aktivní cíle pro '{old_eid}'...")
    name_part = old_eid.split('.')[-1].split('_')[0]
    cursor.execute("""
        SELECT a.id, a.statistic_id, a.unit_of_measurement
        FROM statistics_meta a
        JOIN states_meta b ON a.statistic_id = b.entity_id
        WHERE a.statistic_id LIKE ? AND a.id != ?
    """, (f'%{name_part}%', old_mid))
    
    targets = cursor.fetchall()
    if targets:
        print("\nDOPORUČENÉ CÍLE:")
        for i, (mid, eid, unit) in enumerate(targets):
            match = "⭐" if unit == old_unit else "  "
            print(f" [{i+1}] {match} {eid} ({unit})")
        t_choice = input("\nVyber číslo cíle, nebo zadej celé ID ručně: ")
        if t_choice.isdigit():
            new_mid, new_eid, new_unit = targets[int(t_choice)-1]
        else:
            new_eid = t_choice.strip()
            cursor.execute("SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (new_eid,))
            new_mid, new_unit = cursor.fetchone()
    else:
        new_eid = input("Žádná shoda. Zadej přesné ID cílové entity: ").strip()
        cursor.execute("SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (new_eid,))
        new_mid, new_unit = cursor.fetchone()

    # 4. KONTROLA ČASOVÝCH OS
    cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (old_mid,))
    o_min, o_max, o_count = cursor.fetchone()
    cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (new_mid,))
    n_min, n_max, n_count = cursor.fetchone()

    print(f"\n" + "="*70)
    print(f"📅 ANALÝZA ČASOVÉ OSY")
    print(f"="*70)
    print(f"STARÁ DATA: {format_ts(o_min)} ---> {format_ts(o_max)} ({o_count} bodů)")
    print(f"NOVÁ DATA:  {format_ts(n_min)} ---> {format_ts(n_max)} ({n_count} bodů)")

    if n_min and o_max:
        if n_min <= o_max:
            overlap_h = round((o_max - n_min)/3600, 1)
            print(f"⚠️  SOUBĚH: Data se překrývají o {overlap_h} hodin. Překryv bude ze staré entity odstraněn.")
        else:
            gap_h = round((n_min - o_max)/3600, 1)
            print(f"🕳️  DÍRA: Mezi daty je mezera {gap_h} hodin.")

    # 5. KONTROLA SUMY (OFFSET)
    cursor.execute("SELECT sum FROM statistics WHERE metadata_id = ? ORDER BY start_ts DESC LIMIT 1", (old_mid,))
    res_sum = cursor.fetchone()
    offset = res_sum[0] if res_sum and res_sum[0] else 0
    print(f"📈 OFFSET: Poslední hodnota sumy staré entity je {offset}.")

    # 6. FINÁLNÍ POTVRZENÍ A ZÁLOHA
    print("\n" + "!"*70)
    confirm = input(f"Sloučit {old_eid} -> {new_eid}?\nNapiš 'POTVRZUJI': ")

    if confirm == 'POTVRZUJI':
        # Vytvoření zálohy s timestampem
        ts_string = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_name = f"{db_path}_{ts_string}.bak"
        print(f"\n📦 Vytvářím bezpečnou zálohu: {bak_name}...")
        shutil.copy2(db_path, bak_name)

        try:
            # Řešení souběhu: pokud nová data začala dřív než stará skončila, smažeme ten konec starých
            if n_min and o_max and n_min <= o_max:
                cursor.execute("DELETE FROM statistics WHERE metadata_id = ? AND start_ts >= ?", (old_mid, n_min))
                cursor.execute("DELETE FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ?", (old_mid, n_min))

            # Samotná migrace (přepsání metadata_id)
            cursor.execute("UPDATE statistics SET metadata_id = ? WHERE metadata_id = ?", (new_mid, old_mid))
            cursor.execute("UPDATE statistics_short_term SET metadata_id = ? WHERE metadata_id = ?", (new_mid, old_mid))
            
            # Oprava sumy (offsetu) pro nová data, aby navazovala na konec starých
            if offset > 0:
                cursor.execute("UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, new_mid, n_min if n_min else 0))
                cursor.execute("UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, new_mid, n_min if n_min else 0))
            
            # Odstranění starého (nyní prázdného) záznamu v meta tabulce
            cursor.execute("DELETE FROM statistics_meta WHERE id = ?", (old_mid,))
            
            conn.commit()
            print("\n✅ HOTOVO. Historie byla úspěšně sloučena a sirotek odstraněn.")
        except Exception as e:
            print(f"❌ CHYBA: {e}")
            conn.rollback()
    else:
        print("\n❌ Akce zrušena.")
    
    conn.close()

if __name__ == "__main__":
    main()