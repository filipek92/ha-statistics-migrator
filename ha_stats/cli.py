import click
from ha_stats.db import DatabaseManager
from ha_stats.commands.analyze import analyze_command
from ha_stats.commands.fix import fix_command
from ha_stats.commands.migrate import migrate_command
from ha_stats.commands.list_stats import list_command
from ha_stats.commands.purge import purge_command

@click.group()
@click.option('--db-path', type=click.Path(exists=True), help='Cesta k souboru databáze (home-assistant_v2.db).')
@click.pass_context
def cli(ctx, db_path):
    """Nástroj pro správu, analýzu a opravu statistik v Home Assistant databázi."""
    ctx.ensure_object(dict)
    try:
        ctx.obj['db'] = DatabaseManager(db_path)
    except FileNotFoundError as e:
        # Pouze vyvoláme chybu, pokud je spuštěn příkaz vyžadující DB
        # Click to odchytí později, nebo subcommands spadnou
        # Ale chceme vyhodit hezkou hlášku, pokud DB nenajdeme hned
        if ctx.invoked_subcommand != 'help': 
             click.echo(f"Chyba: {e}", err=True)
             # Nevypínáme hned, některé příkazy (např. budoucí help) by mohly projít, 
             # ale pro většinu to bude fatal. Necháme to na subcommandech.
        ctx.obj['db_error'] = e

# Registrace příkazů
cli.add_command(analyze_command, name='analyze')
cli.add_command(fix_command, name='fix')
cli.add_command(migrate_command, name='migrate')
cli.add_command(list_command, name='list')
cli.add_command(purge_command, name='purge')

if __name__ == '__main__':
    cli()
