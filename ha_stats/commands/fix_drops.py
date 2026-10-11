import click
from ha_stats.utils import format_ts, get_db, warn_if_ha_running

STAT_TABLES = ("statistics", "statistics_short_term")


def compute_drop_fixes(rows, mode="auto", recovery_hours=24.0):
    """
    Spočítá opravy, aby byla řada 'sum' neklesající.

    rows: seznam (id, start_ts, sum) seřazený podle start_ts.
    mode:
      - 'flatten': propad se zarovná na poslední hodnotu (pro krátké výpadky, data se pak vrátí).
      - 'shift':   propad je reset – všechna další data se posunou o velikost propadu.
      - 'auto':    pokud se data do `recovery_hours` vrátí na úroveň před propadem -> flatten, jinak shift.

    Vrací (updates, drops):
      updates: {id: nová_suma}
      drops:   seznam propadů {'ts', 'val', 'max_prev', 'diff', 'action'}
    """
    window = recovery_hours * 3600
    offset = 0.0
    last = None  # poslední (opravená) suma
    updates = {}
    drops = []

    for i, (r_id, ts, raw) in enumerate(rows):
        if raw is None:
            continue

        val = raw + offset
        if last is not None and val < last:
            action = mode
            if mode == "auto":
                # Vrátí se data (po započtení stávajícího offsetu) v daném okně na úroveň `last`?
                action = "shift"
                for _, ts_next, raw_next in rows[i + 1:]:
                    if ts_next - ts > window:
                        break
                    if raw_next is not None and raw_next + offset >= last:
                        action = "flatten"
                        break

            drops.append({'ts': ts, 'val': val, 'max_prev': last, 'diff': last - val, 'action': action})
            if action == "shift":
                offset += last - val
            val = last

        if val != raw:
            updates[r_id] = val
        last = val

    return updates, drops


def _load_rows(cursor, table, m_id):
    cursor.execute(f"SELECT id, start_ts, sum FROM {table} WHERE metadata_id = ? ORDER BY start_ts", (m_id,))
    return [(r['id'], r['start_ts'], r['sum']) for r in cursor.fetchall()]


@click.command('fix-drops')
@click.argument('entity_id')
@click.option('--preview/--no-preview', default=True, help='Zobrazit seznam nalezených propadů (default: True).')
@click.option('--mode', type=click.Choice(['auto', 'flatten', 'shift'], case_sensitive=False), default='auto',
              help='auto (default): krátký výpadek zarovná, trvalý reset posune; flatten: vždy zarovnat; shift: vždy posunout.')
@click.option('--recovery-hours', type=float, default=24.0, show_default=True,
              help='Režim auto: do kolika hodin se data musí vrátit, aby šlo o výpadek (ne reset).')
@click.pass_context
def fix_drops_command(ctx, entity_id, preview, mode, recovery_hours):
    """
    Opraví 'propady' u kumulativních senzorů (sum).

    Pokud sensor klesne (což fyzicky nemá, např. total_energy), HA to může
    interpretovat jako reset a přidat obrovskou hodnotu do sum.
    Nebo prostě v datech zůstane díra/skok dolů.

    Tento nástroj najde místa, kde sum(t) < sum(t-1), a opraví je:
    krátké výpadky zarovná, trvalé resety vyrovná posunem následujících dat.
    Opravuje dlouhodobé i krátkodobé statistiky.
    """
    db = get_db(ctx)
    mode = mode.lower()

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

        click.echo(f"Analyzuji propady pro: {entity_id} (ID: {m_id}, režim: {mode})...")

        # 2. Hledání propadů – zvlášť pro dlouhodobé a krátkodobé statistiky
        plan = {}
        for table in STAT_TABLES:
            plan[table] = compute_drop_fixes(_load_rows(cursor, table, m_id), mode, recovery_hours)

        updates_long, drops = plan["statistics"]
        updates_short, drops_short = plan["statistics_short_term"]

        if not drops and not drops_short:
            click.echo("✅ Žádné propady nenalezeny. Suma je monotónně rostoucí.")
            return

        click.echo(f"⚠️ NALEZENO {len(drops)} PROPADŮ v dlouhodobých a {len(drops_short)} v krátkodobých statistikách:")
        if preview and drops:
            click.echo(f"{'Datum':<20} | {'Hodnota':<10} | {'Mělo být >=':<12} | {'Rozdíl':<10} | {'Oprava'}")
            for d in drops[:20]: # Show first 20
                action = "zarovnat" if d['action'] == "flatten" else "posunout dál"
                click.echo(f"{format_ts(d['ts']):<20} | {d['val']:<10.2f} | {d['max_prev']:<12.2f} | -{d['diff']:<9.2f} | {action}")
            if len(drops) > 20:
                click.echo(f"... a {len(drops)-20} dalších.")

        click.echo("\n💡 Oprava:")
        click.echo("   - zarovnat: krátký výpadek se nastaví na poslední známou hodnotu (data se pak vrátí),")
        click.echo("   - posunout dál: trvalý reset – všechna další data se zvednou o velikost propadu.")
        click.echo(f"   Změní se {len(updates_long)} dlouhodobých a {len(updates_short)} krátkodobých záznamů.")

        if not click.confirm("Chcete provést opravu?"):
            return

        if not warn_if_ha_running(db):
            return

        if click.confirm("Chcete vytvořit zálohu před opravou? (Doporučeno)", default=True):
            db.create_backup("fix_drops")

        # 3. Aplikace opravy
        click.echo("Opravuji databázi...")
        try:
            for table in STAT_TABLES:
                updates, _ = plan[table]
                cursor.executemany(
                    f"UPDATE {table} SET sum = ? WHERE id = ?",
                    [(val, r_id) for r_id, val in updates.items()]
                )
            conn.commit()
            click.echo(f"✅ Hotovo. Opraveno {len(updates_long)} dlouhodobých a {len(updates_short)} krátkodobých záznamů.")

        except Exception as e:
            conn.rollback()
            click.echo(f"❌ Chyba: {e}", err=True)
