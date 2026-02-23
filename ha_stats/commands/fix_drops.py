import click
import shutil
import time
from datetime import datetime
from ha_stats.db import DatabaseManager

@click.command('fix-drops')
@click.argument('entity_id')
@click.option('--preview/--no-preview', default=True, help='Zobrazit seznam nalezených propadů (default: True).')
@click.pass_context
def fix_drops_command(ctx, entity_id, preview):
    """
    Opraví 'propady' u kumulativních senzorů (sum).
    
    Pokud sensor klesne (což fyzicky nemá, např. total_energy), HA to může 
    interpretovat jako reset a přidat obrovskou hodnotu do sum.
    Nebo prostě v datech zůstane díra/skok dolů.
    
    Tento nástroj najde místa, kde sum(t) < sum(t-1) a dorovná je.
    """
    db: DatabaseManager = ctx.obj.get('db')
    if not db: return

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # 1. Získání ID
        cursor.execute("SELECT id, statistic_id, has_sum FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
        meta = cursor.fetchone()
        if not meta:
            click.echo(f"Entita '{entity_id}' nenalezena.")
            return

        m_id = meta['id']
        if not meta['has_sum']:
            click.echo(f"⚠️ Entita '{entity_id}' není kumulativní (has_sum=0). Nemá smysl opravovat propady.")
            return

        click.echo(f"Analyzuji propady pro: {entity_id} (ID: {m_id})...")

        # 2. Hledání propadů
        # Najdeme místa, kde aktuální sum je MENŠÍ než předchozí sum
        # To u kumulativních senzorů znamená buď reset, nebo chybu.
        # Pokud je to chyba (krátkodobý výpadek na 0), chceme to ignorovat/přemostit.
        # Defacto chceme, aby sum() byla neklesající funkce.
        
        # Načteme celou řadu (pro jistotu, SQL window funkce by byly složitější na update logic)
        cursor.execute("SELECT id, start_ts, sum FROM statistics WHERE metadata_id = ? ORDER BY start_ts", (m_id,))
        rows = cursor.fetchall()
        
        drops = []
        max_seen_sum = 0.0
        
        # První průchod - detekce
        for row in rows:
            curr_sum = row['sum']
            if curr_sum is None: continue
            
            if curr_sum < max_seen_sum:
                # Propad!
                diff = max_seen_sum - curr_sum
                drops.append({
                    'ts': row['start_ts'],
                    'val': curr_sum,
                    'max_prev': max_seen_sum,
                    'diff': diff
                })
            else:
                max_seen_sum = curr_sum

        if not drops:
            click.echo("✅ Žádné propady nenalezeny. Suma je monotónně rostoucí.")
            return

        click.echo(f"⚠️ NALEZENO {len(drops)} PROPADŮ (klesající sum):")
        if preview:
            click.echo(f"{'Datum':<20} | {'Hodnota':<10} | {'Mělo být >=':<12} | {'Rozdíl':<10}")
            for d in drops[:20]: # Show first 20
                dt = datetime.fromtimestamp(d['ts']).strftime('%Y-%m-%d %H:%M:%S')
                click.echo(f"{dt:<20} | {d['val']:<10.2f} | {d['max_prev']:<12.2f} | -{d['diff']:<10.2f}")
            if len(drops) > 20:
                click.echo(f"... a {len(drops)-20} dalších.")

        click.echo("\n💡 Oprava: Nastaví hodnotu 'sum' na poslední známé maximum.")
        click.echo("   (Tím se zajistí, že křivka neklesá. Ideální pro drobné výpadky.)")
        
        if click.confirm("Chcete provést opravu?"):
            if click.confirm("Chcete vytvořit zálohu před opravou? (Doporučeno)", default=True):
                db.create_backup("fix_drops")
            
            # 3. Aplikace opravy
            # Musíme projít znovu a updatovat. SQL update by byl složitý ("update to max(prev)"), 
            # v Pythonu to uděláme iterativně.
            
            click.echo("Opravuji databázi...")
            count = 0
            
            # Musíme znovu iterovat a udržovat max_seen_sum, a rovnou updatovat ty špatné
            max_seen_sum = 0.0
            cursor.execute("BEGIN TRANSACTION")
            try:
                for row in rows:
                    curr_sum = row['sum']
                    r_id = row['id']
                    
                    if curr_sum is None: continue

                    if curr_sum < max_seen_sum:
                        # Update na max_seen_sum
                        # Tím "vyžehlíme" propad na rovnou čáru
                        cursor.execute("UPDATE statistics SET sum = ? WHERE id = ?", (max_seen_sum, r_id))
                        count += 1
                    else:
                        max_seen_sum = curr_sum
                
                # To samé pro short_term? 
                # Short term se maže po 10 dnech, ale pro konzistenci by to bylo fajn.
                # Ale short_term má jinou strukturu a ID. Pro zjednodušení řešíme jen long-term statistics.
                
                conn.commit()
                click.echo(f"✅ Hotovo. Opraveno {count} záznamů.")
                
            except Exception as e:
                conn.rollback()
                click.echo(f"❌ Chyba: {e}")

