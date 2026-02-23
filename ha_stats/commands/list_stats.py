import click
from ha_stats.db import DatabaseManager

@click.command('list')
@click.argument('search_term', required=False)
@click.pass_context
def list_command(ctx, search_term):
    """Vypíše dostupné statistiky (entity_id) v databázi."""
    db: DatabaseManager = ctx.obj['db']
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT statistic_id, unit_of_measurement FROM statistics_meta"
            params = []
            
            if search_term:
                query += " WHERE statistic_id LIKE ?"
                params.append(f"%{search_term}%")
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                click.echo("Nebyly nalezeny žádné statistiky.")
                return

            click.echo(f"Nalezeno {len(rows)} záznamů:")
            for row in rows:
                unit = row['unit_of_measurement'] or "N/A"
                click.echo(f" - {row['statistic_id']} (Unit: {unit})")
                
    except Exception as e:
        click.echo(f"Chyba při čtení databáze: {e}", err=True)
