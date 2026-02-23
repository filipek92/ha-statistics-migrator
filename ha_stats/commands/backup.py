import click
from ha_stats.db import DatabaseManager

@click.command('backup')
@click.option('--suffix', default=None, help='Volitelný suffix pro název záložního souboru.')
@click.pass_context
def backup_command(ctx, suffix):
    """
    Vytvoří zálohu databáze (používá SQLite Online Backup API).
    """
    db: DatabaseManager = ctx.obj.get('db')
    if not db:
        click.echo("Chyba: Databáze nebyla inicializována.", err=True)
        return

    try:
        backup_path = db.create_backup(suffix=suffix or "manual")
        click.echo(f"✅ Záloha úspěšně dokončena: {backup_path}")
    except Exception as e:
        click.echo(f"❌ Chyba při vytváření zálohy: {e}", err=True)
