import click
import sqlite3
from datetime import datetime

@click.command('analyze')
@click.argument('entity_id')
@click.pass_context
def analyze_command(ctx, entity_id):
    """
    Provede detailní analýzu statistik pro danou entitu.
    Zkontroluje metadata, duplicity, počet záznamů a aktuální stav.
    """
    db = ctx.obj.get('db')
    if not db:
        click.echo("Chyba: Databáze není dostupná.")
        return

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Fetch Metadata
            cursor.execute("SELECT * FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
            meta_rows = cursor.fetchall()
            
            click.echo(f"\n--- ANALÝZA ENTITY: {entity_id} ---")
            
            if not meta_rows:
                click.echo("❌ Entita nebyla nalezena v tabulce statistics_meta.")
                return

            for row in meta_rows:
                m_id = row['id']
                unit = row['unit_of_measurement']
                has_mean = row['has_mean']
                has_sum = row['has_sum']
                
                click.echo(f"\nMetadata ID: {m_id}")
                click.echo(f"  Unit: {unit}")
                click.echo(f"  Has Mean: {has_mean}")
                click.echo(f"  Has Sum: {has_sum}")
                
                # Basic checks
                if "sensor" in entity_id and not has_mean and not has_sum:
                    click.echo("  ⚠️ VAROVÁNÍ: Senzor by měl mít has_mean=1 nebo has_sum=1.")
                
                # Check for duplicates in statistics
                cursor.execute("SELECT COUNT(*), MIN(start_ts), MAX(start_ts) FROM statistics WHERE metadata_id = ?", (m_id,))
                stats = cursor.fetchone()
                count, min_ts, max_ts = stats
                
                if count and count > 0:
                    min_date = datetime.fromtimestamp(min_ts).strftime('%Y-%m-%d %H:%M:%S') if min_ts else "N/A"
                    max_date = datetime.fromtimestamp(max_ts).strftime('%Y-%m-%d %H:%M:%S') if max_ts else "N/A"
                    click.echo(f"  Počet záznamů v 'statistics': {count}")
                    click.echo(f"  Rozsah dat: {min_date} - {max_date}")
                else:
                    click.echo("  ⚠️ Žádná data v tabulce statistics.")

                # Check short term statistics
                cursor.execute("SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id = ?", (m_id,))
                short_count = cursor.fetchone()[0]
                click.echo(f"  Počet záznamů v 'statistics_short_term': {short_count}")

            # 2. Check for Metadata Duplicates
            if len(meta_rows) > 1:
                click.echo("\n❌ NALEZENY DUPLICITY V METADATECH!")
                click.echo("Entita má více záznamů v statistics_meta. To může způsobovat problémy.")

            # 3. Check current state in `states` table (if available) check by linking via states_meta if needed, 
            # but usually we look up by entity_id string in states_meta
            
            click.echo("\n--- KONTROLA TABULKY STATES ---")
            cursor.execute("SELECT metadata_id FROM states_meta WHERE entity_id = ?", (entity_id,))
            state_meta = cursor.fetchone()
            
            if state_meta:
                sm_id = state_meta[0]
                click.echo(f"Nalezeno v states_meta pod ID: {sm_id}")
                
                # Get latest state
                cursor.execute("SELECT state, last_updated_ts FROM states WHERE metadata_id = ? ORDER BY last_updated_ts DESC LIMIT 1", (sm_id,))
                latest_state = cursor.fetchone()
                
                if latest_state:
                    l_state = latest_state['state']
                    l_ts = latest_state['last_updated_ts']
                    l_date = datetime.fromtimestamp(l_ts).strftime('%Y-%m-%d %H:%M:%S') if l_ts else "N/A"
                    click.echo(f"Poslední známý stav: {l_state} (změněno: {l_date})")
                else:
                    click.echo("⚠️ Žádný záznam v tabulce states (historie).")
            else:
                click.echo("⚠️ Entita nenalezena v states_meta (žádná historie stavů).")

    except Exception as e:
        click.echo(f"Chyba při analýze: {e}", err=True)
