import click
from ha_stats.utils import get_db

@click.command('backup')
@click.option('--suffix', default=None, help='Volitelný suffix pro název záložního souboru.')
@click.pass_context
def backup_command(ctx, suffix):
    """
    Vytvoří zálohu databáze (používá SQLite Online Backup API).
    """
    db = get_db(ctx)

    try:
        backup_path = db.create_backup(suffix=suffix or "manual")
        click.echo(f"✅ Záloha úspěšně dokončena: {backup_path}")
    except Exception as e:
        click.echo(f"❌ Chyba při vytváření zálohy: {e}", err=True)
