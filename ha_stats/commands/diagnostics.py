import click
from datetime import datetime, timedelta

def format_ts(ts):
    if ts is None: return "N/A"
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

def format_duration(seconds):
    hours = seconds / 3600
    if hours < 24:
        return f"{hours:.1f} h"
    days = hours / 24
    return f"{days:.1f} dní"

@click.command('diagnose')
@click.argument('entity_id', required=False)
@click.option('--threshold', default=2.0, help='Práh pro detekci díry v hodinách (default: 2.0 h).')
@click.pass_context
def diagnose_command(ctx, entity_id, threshold):
    """
    Analyzuje kontinuitu dat entity a hledá díry v záznamech.
    Vypíše seznam spojitých bloků a mezer.
    """
    db = ctx.obj['db']
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Výběr entity
        target_id = None
        target_name = None
        target_unit = None

        if not entity_id:
            # Interaktivní výběr
            search = click.prompt("Zadejte název entity (nebo část) pro diagnostiku", type=str)
            cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ?", (f"%{search}%",))
            results = cursor.fetchall()
            
            if not results:
                click.echo("❌ Žádná entita nenalezena.")
                return
            
            click.echo("\nNALEZENÉ ENTITY:")
            for idx, row in enumerate(results):
                unit = row['unit_of_measurement'] or 'N/A'
                click.echo(f" [{idx}] {row['statistic_id']} (Unit: {unit})")
            
            idx = click.prompt("Vyberte index (nebo -1 pro zrušení)", type=int)
            if idx < 0: return

            target_id = results[idx]['id']
            target_name = results[idx]['statistic_id']
            target_unit = results[idx]['unit_of_measurement']
        else:
            # Přímé zadání ID nebo názvu
            cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
            row = cursor.fetchone()
            if row:
                target_id = row['id']
                target_name = row['statistic_id']
                target_unit = row['unit_of_measurement']
            else:
                click.echo(f"❌ Entita '{entity_id}' nebyla nalezena (přesná shoda).")
                return

        # 2. Načtení dat
        click.echo(f"\n📊 ANALÝZA KONTINUITY: {target_name} (ID: {target_id})")
        click.echo("Načítám záznamy...")
        
        cursor.execute("SELECT start_ts, state, sum FROM statistics WHERE metadata_id = ? ORDER BY start_ts ASC", (target_id,))
        records = cursor.fetchall()
        
        count = len(records)
        click.echo(f"Počet záznamů: {count}")
        
        if count == 0:
            click.echo("⚠️  Žádná data k analýze.")
            return

        # 3. Analýza bloků a děr
        blocks = []
        gaps = []
        
        # Práh v sekundách
        threshold_sec = threshold * 3600
        
        current_block_start = records[0]['start_ts']
        current_block_count = 1
        last_ts = records[0]['start_ts']
        
        for i in range(1, count):
            ts = records[i]['start_ts']
            diff = ts - last_ts
            
            if diff > threshold_sec:
                # Našli jsme díru -> ukončíme blok
                block_end = last_ts
                blocks.append({
                    'start': current_block_start,
                    'end': block_end,
                    'count': current_block_count,
                    'duration': block_end - current_block_start
                })
                
                # Zaznamenáme díru
                gaps.append({
                    'start': last_ts,
                    'end': ts,
                    'duration': diff
                })
                
                # Start nového bloku
                current_block_start = ts
                current_block_count = 1
            else:
                current_block_count += 1
            
            last_ts = ts
        
        # Přidáme poslední blok
        blocks.append({
            'start': current_block_start,
            'end': last_ts,
            'count': current_block_count,
            'duration': last_ts - current_block_start
        })

        # 4. Výpis výsledků
        click.echo(f"\n✅ NALEZENÉ SPOJITÉ BLOKY (tolerance mezery < {threshold} h):")
        click.echo(f"{'#':<3} | {'ZAČÁTEK':<20} | {'KONEC':<20} | {'DÉLKA':<12} | {'ZÁZNAMŮ':<8}")
        click.echo("-" * 75)
        
        for i, b in enumerate(blocks):
            dur = format_duration(b['duration'])
            click.echo(f"{i+1:<3} | {format_ts(b['start']):<20} | {format_ts(b['end']):<20} | {dur:<12} | {b['count']:<8}")

        if gaps:
            click.echo(f"\n❌ NALEZENÉ DÍRY (> {threshold} h):")
            click.echo(f"{'#':<3} | {'OD (Konec bloku)':<20} | {'DO (Začátek dalšího)':<20} | {'DÉLKA':<12}")
            click.echo("-" * 70)
            for i, g in enumerate(gaps):
                dur = format_duration(g['duration'])
                click.echo(f"{i+1:<3} | {format_ts(g['start']):<20} | {format_ts(g['end']):<20} | {dur:<12}")
        else:
            click.echo("\n✨ Data jsou perfektně spojitá (žádné velké díry).")
        
        # 5. Možnost mazání
        choice = click.prompt("\nChcete smazat některý z nalezených bloků? (číslo bloku #, nebo enter pro konec)", default="")
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(blocks):
                to_delete = blocks[idx]
                click.echo(f"\n⚠️  VAROVÁNÍ: Chystáte se smazat blok #{choice}:")
                click.echo(f"   Od: {format_ts(to_delete['start'])}")
                click.echo(f"   Do: {format_ts(to_delete['end'])}")
                click.echo(f"   Celkem {to_delete['count']} záznamů.")
                
                if click.confirm("Opravdu chcete tato data TRVALE smazat?"):
                    if click.confirm("Vytvořit zálohu před smazáním?", default=True):
                         db.create_backup("delete_block")
                    
                    try:
                        count_long = cursor.execute(
                            "DELETE FROM statistics WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?", 
                            (target_id, to_delete['start'], to_delete['end'])
                        ).rowcount
                        
                        count_short = cursor.execute(
                            "DELETE FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?", 
                            (target_id, to_delete['start'], to_delete['end'])
                        ).rowcount
                        
                        conn.commit()
                        click.echo(f"\n✅ Smazáno {count_long} záznamů z dlouhodobé a {count_short} z krátkodobé historie.")
                    except Exception as e:
                        conn.rollback()
                        click.echo(f"❌ Chyba při mazání: {e}")
            else:
                click.echo("❌ Neplatné číslo bloku.")

