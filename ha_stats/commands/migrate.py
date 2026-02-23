import click
import shutil
import time
from datetime import datetime

def format_ts(ts):
    if ts is None: return "N/A"
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

def create_backup(db_path):
    timestamp = int(time.time())
    backup_path = f"{db_path}.backup_{timestamp}"
    click.echo(f"  📦 Zálohování databáze: {backup_path}")
    shutil.copy2(db_path, backup_path)
    return backup_path

@click.command('migrate')
@click.pass_context
def migrate_command(ctx):
    """
    Interaktivní průvodce migrací "sirotčích" statistik.
    Řeší překryvy a navazuje kumulativní součty (sum).
    """
    db = ctx.obj['db']
    db_path = db.db_path

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Hledání sirotčích statistik
            click.echo("🔍 Hledám sirotčí záznamy (orphans)...")
            cursor.execute("""
                SELECT id, statistic_id, unit_of_measurement
                FROM statistics_meta 
                WHERE statistic_id NOT IN (SELECT entity_id FROM states_meta)
            """)
            orphans = cursor.fetchall()
            
            source_id = None
            source_name = None
            source_unit = None

            if orphans:
                click.echo(f"\n📍 NALEZENÍ SIROTCI ({len(orphans)}):")
                for idx, row in enumerate(orphans):
                    unit = row['unit_of_measurement'] or 'N/A'
                    click.echo(f" [{idx}] {row['statistic_id']:<50} (Unit: {unit})")
                
                choice = click.prompt("\nVyberte index sirotka (nebo 's' pro vyhledávání)", default="s")
                
                if choice.isdigit():
                    idx = int(choice)
                    if 0 <= idx < len(orphans):
                        source_id = orphans[idx]['id']
                        source_name = orphans[idx]['statistic_id']
                        source_unit = orphans[idx]['unit_of_measurement']

            # Pokud nevybráno z orphans, hledáme manuálně
            if not source_id:
                search = click.prompt("Zadejte část názvu zdrojové entity", type=str)
                cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ?", (f"%{search}%",))
                results = cursor.fetchall()
                
                if not results:
                    click.echo("❌ Žádná entita nenalezena.")
                    return
                
                click.echo("NALEZENÉ ENTITY:")
                for idx, row in enumerate(results):
                    unit = row['unit_of_measurement'] or 'N/A'
                    click.echo(f" [{idx}] {row['statistic_id']} (Unit: {unit})")
                
                idx = click.prompt("Vyberte index (nebo -1 pro zrušení)", type=int)
                if idx < 0: return

                source_id = results[idx]['id']
                source_name = results[idx]['statistic_id']
                source_unit = results[idx]['unit_of_measurement']

            # 2. Výběr cíle (Smart Match)
            click.echo(f"\n🔍 Hledám cíle pro: {source_name}")
            
            # Zkusíme najít část názvu (za poslední tečkou, před prvním podtržítkem po prefixu)
            # Heuristika: vezmeme část názvu entity a najdeme podobné
            name_parts = source_name.split('.')[-1].split('_')
            search_part = name_parts[0] if len(name_parts) > 0 else source_name
            
            cursor.execute("""
                SELECT id, statistic_id, unit_of_measurement 
                FROM statistics_meta 
                WHERE statistic_id LIKE ? AND id != ?
            """, (f"%{search_part}%", source_id))
            targets = cursor.fetchall()

            target_id = None
            target_name = None
            
            if targets:
                click.echo("DOPORUČENÉ CÍLE:")
                targets_map = {}
                display_idx = 0
                for row in targets:
                    match = "⭐" if row['unit_of_measurement'] == source_unit else "  "
                    print(f" [{display_idx}] {match} {row['statistic_id']}")
                    targets_map[display_idx] = row
                    display_idx += 1
                
                t_choice = click.prompt("\nVyberte index cíle (nebo 'm' pro manuální zadání)", default="m")
                
                if t_choice.isdigit():
                    idx = int(t_choice)
                    if idx in targets_map:
                        target_id = targets_map[idx]['id']
                        target_name = targets_map[idx]['statistic_id']
            
            if not target_id:
                target_name_input = click.prompt("Zadejte přesné ID cílové entity (např. sensor.xxx)")
                cursor.execute("SELECT id, statistic_id FROM statistics_meta WHERE statistic_id = ?", (target_name_input,))
                res = cursor.fetchone()
                if not res:
                    click.echo("❌ Cílová entita nenalezena v metadatech.")
                    return
                target_id = res['id']
                target_name = res['statistic_id']

            # 3. Analýza konfliktu a offsetu
            click.echo(f"\n⏳ ANALÝZA: {source_name} -> {target_name}")
            
            # Statistiky zdroje
            cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (source_id,))
            s_min, s_max, s_count = cursor.fetchone()
            
            # Statistiky cíle
            cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (target_id,))
            t_min, t_max, t_count = cursor.fetchone()

            click.echo(f"  Zdroj (OLD): {format_ts(s_min)} -> {format_ts(s_max)} ({s_count} záznamů)")
            click.echo(f"  Cíl (NEW):   {format_ts(t_min)} -> {format_ts(t_max)} ({t_count} záznamů)")

            # Check overlap
            overlap_deletion_cutoff = None
            if t_min and s_max and t_min <= s_max:
                overlap_h = round((s_max - t_min)/3600, 1)
                click.echo(f"  ⚠️  VAROVÁNÍ: Překryv dat ({overlap_h} h)! Nová data začínají dříve ({format_ts(t_min)}), než stará končí.")
                click.echo("      Pokud budete pokračovat, stará data od tohoto času budou smazána.")
                overlap_deletion_cutoff = t_min
            elif s_max and t_min:
                 gap_h = round((t_min - s_max)/3600, 1)
                 click.echo(f"  🕳️  DÍRA: Mezi daty je mezera {gap_h} hodin.")
            
            # Check Offset (Last sum)
            # Důležité: Offset řešíme pouze pokud má entita 'has_sum=1'. U 'mean' senzorů (teplota) se offset nepřičítá.
            cursor.execute("SELECT has_sum FROM statistics_meta WHERE id = ?", (source_id,))
            source_has_sum = cursor.fetchone()['has_sum']

            offset = 0.0
            if source_has_sum:
                cursor.execute("SELECT sum FROM statistics WHERE metadata_id = ? ORDER BY start_ts DESC LIMIT 1", (source_id,))
                last_sum_row = cursor.fetchone()
                offset = last_sum_row['sum'] if last_sum_row and last_sum_row['sum'] else 0.0
            
                if offset > 0:
                    click.echo(f"  📈 DETEKOVÁN OFFSET (SUM): {offset}")
                    click.echo("      Tato hodnota se přičte ke všem záznamům cílové entity, aby grafy pokračovaly.")
            else:
                click.echo("  ℹ️  Entita nemá 'has_sum', offset se nebude přičítat (OK pro teplotu, výkon atd.).")
            
            # 4. Potvrzení a Migrace
            if not click.confirm("\n❓ Chcete provést sloučení a migraci dat?"):
                click.echo("Operace zrušena.")
                return

            create_backup(db_path)
            
            try:
                # 4.1 Delete overlap from SOURCE if needed
                if overlap_deletion_cutoff:
                    click.echo(f"  Mazání překrývajících se starých dat (>= {format_ts(overlap_deletion_cutoff)})...")
                    cursor.execute("DELETE FROM statistics WHERE metadata_id = ? AND start_ts >= ?", (source_id, overlap_deletion_cutoff))
                    cursor.execute("DELETE FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ?", (source_id, overlap_deletion_cutoff))

                # 4.2 Update ID (The Migration)
                click.echo("  Přepisování ID v tabulkách...")
                cursor.execute("UPDATE statistics SET metadata_id = ? WHERE metadata_id = ?", (target_id, source_id))
                cursor.execute("UPDATE statistics_short_term SET metadata_id = ? WHERE metadata_id = ?", (target_id, source_id))
                
                # 4.3 Apply Offset to target data (starting from the gap/overlap point)
                if offset > 0 and t_min:
                    click.echo("  Přičítání offsetu k nové historii...")
                    cursor.execute("UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, target_id, t_min))
                    cursor.execute("UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, target_id, t_min))

                # 4.4 Cleanup
                click.echo("  Mažu stará metadata...")
                cursor.execute("DELETE FROM statistics_meta WHERE id = ?", (source_id,))
                
                conn.commit()
                click.echo("\n✅ HOTOVO! Migrace úspěšně dokončena.")
                
            except Exception as e:
                conn.rollback()
                click.echo(f"\n❌ CHYBA: {e}", err=True)
                click.echo("Všechny změny byly vráceny zpět (rollback).")

    except Exception as e:
        click.echo(f"Chyba: {e}", err=True)
