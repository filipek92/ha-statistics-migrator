import click
import sqlite3
import time
from datetime import datetime
from ha_stats.db import DatabaseManager

def format_ts_rel(ts):
    if not ts: return "N/A"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime('%Y-%m-%d')

@click.command('list')
@click.argument('search_term', required=False)
@click.option('--no-details', is_flag=True, help='Rychlý výpis bez počítání záznamů (rychlejší).')
@click.pass_context
def list_command(ctx, search_term, no_details):
    """
    Vypíše statistiky. Zobrazí počet záznamů, datum poslední změny a status.
    Zelená (🟢) = Aktivní (< 7 dní), Červená (🔴) = Staré data.
    """
    db: DatabaseManager = ctx.obj['db']
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Pokud uživatel chce jen rychlý seznam (bez JOINu na data)
            if no_details:
                query = "SELECT id, statistic_id, unit_of_measurement FROM statistics_meta"
                params = []
                if search_term:
                    query += " WHERE statistic_id LIKE ?"
                    params.append(f"%{search_term}%")
                
                cursor.execute(query, params)
                rows = cursor.fetchall()

                if not rows:
                    click.echo("Nebyly nalezeny žádné statistiky.")
                    return

                click.echo(f"Nalezeno {len(rows)} záznamů (bez detailů):")
                for row in rows:
                    unit = row['unit_of_measurement'] or "N/A"
                    click.echo(f" [{row['id']}] {row['statistic_id']} (Unit: {unit})")
                return

            # Detailní query s JOINem na statistiky (pomalé, ale užitečné)
            # Používáme MAX(start_ts) pro zjištění poslední aktivity
            click.echo("Načítám statistiky (to může chvíli trvat)...")
            
            # Optimalizace: nejdřív najdeme ID podle search, pak spočítáme stats
            # (Doing direct join on huge DB can be slow if we scan everything)
            
            base_query = "SELECT id, statistic_id, unit_of_measurement FROM statistics_meta"
            params = []
            if search_term:
                base_query += " WHERE statistic_id LIKE ?"
                params.append(f"%{search_term}%")
            
            cursor.execute(base_query, params)
            meta_rows = cursor.fetchall()
            
            if not meta_rows:
                click.echo("Nic nenalezeno.")
                return

            results = []
            now_ts = time.time()
            
            with click.progressbar(meta_rows, label="Analyzuji data") as bar:
                for row in bar:
                    mid = row['id']
                    # Získáme Count a Max TS pro toto ID
                    # Index na metadata_id v tabulce statistics by měl existovat
                    cursor.execute("SELECT COUNT(*), MIN(start_ts), MAX(start_ts) FROM statistics WHERE metadata_id = ?", (mid,))
                    stats = cursor.fetchone()
                    count = stats[0]
                    first_ts = stats[1]
                    last_ts = stats[2]
                    
                    results.append({
                        'id': mid,
                        'name': row['statistic_id'],
                        'unit': row['unit_of_measurement'],
                        'count': count,
                        'first_ts': first_ts,
                        'last_ts': last_ts
                    })
            
            # Seřadíme podle last_seen (nejnovější nahoře)
            results.sort(key=lambda x: x['last_ts'] or 0, reverse=True)

            # Formátovaný výstup
            click.echo("\n" + "="*115)
            click.echo(f"{'ID':<5} | {'St':<2} | {'Entity ID':<50} | {'Jedn.':<6} | {'Záznamů':<8} | {'Od':<10} | {'Do'}")
            click.echo("-" * 115)

            for res in results:
                mid = res['id']
                eid = res['name']
                if len(eid) > 48: eid = eid[:45] + "..."
                
                unit = res['unit'] or "-"
                if len(unit) > 6: unit = unit[:6]

                count = res['count']
                first_ts = res['first_ts']
                last_ts = res['last_ts']
                
                first_seen_str = format_ts_rel(first_ts) if first_ts else "-"
                last_seen_str = format_ts_rel(last_ts) if last_ts else "NIKDY"
                
                # Status Ikonka
                icon = "🟢"
                if not last_ts:
                    icon = "⚪" # Nikdy
                elif (now_ts - last_ts) > (7 * 24 * 3600): # 7 dní
                    icon = "🔴" # Staré
                
                if count == 0:
                    icon = "⚠️ "
                
                click.echo(f"{mid:<5} | {icon} | {eid:<50} | {unit:<6} | {count:<8} | {first_seen_str:<10} | {last_seen_str}")
            
            click.echo("\nLegenda: 🟢 Aktivní (<7 dní) | 🔴 Neaktivní (>7 dní) | ⚪ Žádná data | ⚠️  Bez záznamů")

    except Exception as e:
        click.echo(f"Chyba při čtení databáze: {e}", err=True)
