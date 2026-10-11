import click
from ha_stats.utils import get_db, warn_if_ha_running

@click.command('fix')
@click.argument('entity_id')
@click.option('--has-mean/--no-mean', default=None, help='Nastavit has_mean na 1 nebo 0.')
@click.option('--has-sum/--no-sum', default=None, help='Nastavit has_sum na 1 nebo 0.')
@click.pass_context
def fix_command(ctx, entity_id, has_mean, has_sum):
    """
    Opraví nastavení `has_mean` a `has_sum` v metadatech entity.
    Použijte pokud statistiky neukazují součty/průměry správně.
    """
    if has_mean is None and has_sum is None:
        click.echo("Musíte specifikovat alespoň jednu změnu (--has-mean nebo --has-sum).")
        return

    db = get_db(ctx)
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Zjistíme ID metadat
            cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
            row = cursor.fetchone()
            
            if not row:
                click.echo(f"Entita '{entity_id}' nenalezena.")
                return
            
            m_id = row['id']
            
            updates = []
            params = []
            
            if has_mean is not None:
                updates.append("has_mean = ?")
                params.append(1 if has_mean else 0)
                
            if has_sum is not None:
                updates.append("has_sum = ?")
                params.append(1 if has_sum else 0)
            
            params.append(m_id)

            if not warn_if_ha_running(db):
                return
            
            query = f"UPDATE statistics_meta SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            
            click.echo(f"✅ Metadata pro '{entity_id}' (ID: {m_id}) aktualizována.")
            click.echo(f"  Změny: {', '.join(updates)}")
            
    except click.exceptions.Abort:
        raise
    except Exception as e:
        click.echo(f"Chyba při opravě: {e}", err=True)
