import click
from ha_stats.utils import get_db, find_orphans, prompt_index, warn_if_ha_running

@click.command('purge')
@click.argument('entity_id', required=False)
@click.option('--force', is_flag=True, help='Vynutit smazání i pokud existuje historie.')
@click.pass_context
def purge_command(ctx, entity_id, force):
    """
    Smaže statistiky pro danou entitu.
    Pokud nezadáte ENTITY_ID, nabídne seznam sirotčích statistik k smazání.
    
    Pokud entita nemá žádná data, smaže ji rovnou.
    Pokud data má, vyžaduje přepínač --force.
    """
    db = get_db(ctx)

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Pokud není zadáno ID, nabídneme sirotky
            if not entity_id:
                click.echo("🔍 Hledám sirotčí záznamy (entity bez aktivního stavu)...")
                orphans = find_orphans(cursor)
                
                if not orphans:
                    click.echo("✅ Žádní sirotci nenalezeni. Zadejte prosím ID entity jako argument.")
                    return

                # Načteme s countem
                orphans_data = []
                for row in orphans:
                    cursor.execute("SELECT COUNT(*) FROM statistics WHERE metadata_id = ?", (row['id'],))
                    cnt = cursor.fetchone()[0]
                    orphans_data.append({
                        'id': row['id'], 
                        'statistic_id': row['statistic_id'], 
                        'unit': row['unit_of_measurement'], 
                        'count': cnt
                    })

                click.echo(f"\n📍 NALEZENÍ SIROTCI ({len(orphans)}):")
                for idx, row in enumerate(orphans_data):
                    unit = row['unit'] or 'N/A'
                    count = row['count']
                    click.echo(f" [{idx}] {row['statistic_id']:<50} (Unit: {unit}, Záznamů: {count})")
                
                idx = prompt_index("\nVyberte index entity ke smazání (enter pro konec)", len(orphans_data))
                if idx is None:
                    return
                entity_id = orphans_data[idx]['statistic_id']

            # 1. Získání ID metadat
            cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
            row = cursor.fetchone()
            
            if not row:
                click.echo(f"❌ Entita '{entity_id}' nebyla nalezena v metadatech.")
                return
            
            m_id = row['id']

            # 2. Kontrola existence dat
            cursor.execute("SELECT COUNT(*) FROM statistics WHERE metadata_id = ?", (m_id,))
            count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id = ?", (m_id,))
            short_count = cursor.fetchone()[0]
            
            total_records = count + short_count

            if total_records > 0:
                click.echo(f"⚠️  Entita '{entity_id}' má historii:")
                click.echo(f"   - Dlouhodobá: {count} záznamů")
                click.echo(f"   - Krátkodobá: {short_count} záznamů")
                
                if not force:
                    click.echo("\n❌ Smazání zamítnuto. Entita obsahuje data.")
                    click.echo("💡 Použijte přepínač --force pro vynucené smazání.")
                    return
                else:
                    click.echo("\n⚠️  Byl použit přepínač --force. Mažu veškerou historii!")
                    # 3. Potvrzení (pouze pokud je force)
                    if not click.confirm(f"Opravdu chcete nenávratně smazat '{entity_id}'?"):
                        return

                    if not warn_if_ha_running(db):
                        return
                    
                    if click.confirm("Chcete vytvořit zálohu před smazáním?", default=True):
                        db.create_backup("delete")
                    
                    # 4. Mazání
                    click.echo("  Mazání z tabulky statistics...")
                    cursor.execute("DELETE FROM statistics WHERE metadata_id = ?", (m_id,))
                    
                    click.echo("  Mazání z tabulky statistics_short_term...")
                    cursor.execute("DELETE FROM statistics_short_term WHERE metadata_id = ?", (m_id,))
            else:
                click.echo(f"ℹ️  Entita '{entity_id}' je prázdná (žádná historie). Může být bezpečně smazána.")
                if not warn_if_ha_running(db):
                    return

            click.echo("  Odstraňování metadat...")
            cursor.execute("DELETE FROM statistics_meta WHERE id = ?", (m_id,))
            
            conn.commit()
            click.echo(f"✅ Entita '{entity_id}' byla úspěšně odstraněna.")

    except click.exceptions.Abort:
        raise
    except Exception as e:
        click.echo(f"Chyba při mazání: {e}", err=True)
