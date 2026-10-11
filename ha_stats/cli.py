import click
from ha_stats.db import DatabaseManager
from ha_stats.commands.analyze import analyze_command
from ha_stats.commands.fix import fix_command
from ha_stats.commands.migrate import migrate_command
from ha_stats.commands.list_stats import list_command
from ha_stats.commands.purge import purge_command
from ha_stats.commands.outliers import outliers_command
from ha_stats.commands.backup import backup_command
from ha_stats.commands.export_stats import export_command
from ha_stats.commands.fix_drops import fix_drops_command
from ha_stats.commands.diagnostics import diagnose_command
from ha_stats.commands.clean import clean_command

@click.group()
@click.option('--db-path', type=click.Path(exists=True), help='Cesta k souboru databáze (home-assistant_v2.db).')
@click.pass_context
def cli(ctx, db_path):
    """Nástroj pro správu, analýzu a opravu statistik v Home Assistant databázi."""
    ctx.ensure_object(dict)
    ctx.obj['db'] = None
    try:
        ctx.obj['db'] = DatabaseManager(db_path)
    except FileNotFoundError as e:
        # Chybu ohlásí až příkaz, který DB potřebuje (viz utils.get_db),
        # aby fungovalo např. 'ha-stats list --help' i bez databáze.
        ctx.obj['db_error'] = e

# Registrace příkazů
cli.add_command(analyze_command, name='analyze')
cli.add_command(fix_command, name='fix')
cli.add_command(migrate_command, name='migrate')
cli.add_command(list_command, name='list')
cli.add_command(purge_command, name='purge')
cli.add_command(outliers_command, name='outliers')
cli.add_command(backup_command, name='backup')
cli.add_command(export_command, name='export')
cli.add_command(fix_drops_command, name='fix-drops')
cli.add_command(diagnose_command, name='diagnose')
cli.add_command(clean_command, name='clean')

if __name__ == '__main__':
    cli()
