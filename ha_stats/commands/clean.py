import click
from ha_stats.utils import format_ts, get_db, warn_if_ha_running


def to_number(value):
    """Převod stavu na číslo. Nečíselné stavy ('on', 'unavailable', ...) vrací None."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    # NaN / inf nejsou platné hodnoty senzoru
    if num != num or num in (float('inf'), float('-inf')):
        return None
    return num


def format_state(value):
    """Formát čísla pro sloupec states.state (bez zbytečného '.0')."""
    return f"{value:.10f}".rstrip('0').rstrip('.')


@click.command('clean')
@click.argument('entity_id')
@click.option('--min', 'min_input', type=float, help='Minimální platná hodnota (vše pod bude smazáno/upraveno)')
@click.option('--max', 'max_input', type=float, help='Maximální platná hodnota (vše nad bude smazáno/upraveno)')
@click.option('--fix-mode', type=click.Choice(['delete', 'clamp'], case_sensitive=False), default='delete', help='Režim opravy: delete (smazat řádek) nebo clamp (oříznout na limit). Default: delete.')
@click.option('--short-term', is_flag=True, help='Použít krátkodobé statistiky (statistics_short_term).')
@click.option('--states', is_flag=True, help='Použít tabulku stavů (states).')
@click.pass_context
def clean_command(ctx, entity_id, min_input, max_input, fix_mode, short_term, states):
    """
    Vyhledá a opraví hodnoty mimo platný rozsah (outliers) v sloupci min/max/mean (pro statistiky) nebo state (pro stavy).
    Vhodné pro senzory výkonu, teploty atd., které občas uskočí na nesmyslnou hodnotu.
    Pokud nezadáte limity, nástroj zobrazí extrémy a zeptá se.
    U stavů se zpracovávají jen číselné hodnoty (texty jako 'on', 'unavailable' se ignorují).
    """
    db = get_db(ctx)
    fix_mode = fix_mode.lower()

    if short_term and states:
        click.echo("❌ Nelze použít --short-term a --states současně.")
        return

    is_states = states
    if is_states:
        table = "states"
    else:
        table = "statistics_short_term" if short_term else "statistics"

    min_limit = min_input
    max_limit = max_input

    try:
        with db.get_connection() as conn:
            # Číselný převod v Pythonu – SQLite CAST('on' AS REAL) = 0 by texty považoval za nulu
            conn.create_function("to_number", 1, to_number, deterministic=True)
            cursor = conn.cursor()

            if is_states:
                try:
                    cursor.execute("SELECT metadata_id FROM states_meta WHERE entity_id = ?", (entity_id,))
                except Exception as e:
                    click.echo(f"Chyba při čtení metadat stavů (možná stará verze DB?): {e}")
                    return
                row = cursor.fetchone()
                if not row:
                    click.echo(f"❌ Entita '{entity_id}' nebyla v states_meta nalezena.")
                    return
                meta_id = row[0]
                unit = "(states)"
            else:
                cursor.execute("SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
                meta_row = cursor.fetchone()
                if not meta_row:
                    click.echo(f"❌ Entita '{entity_id}' nebyla v statistics_meta nalezena.")
                    return
                meta_id = meta_row['id']
                unit = meta_row['unit_of_measurement'] or ""

            click.echo(f"Analyzuji entitu: {entity_id} (ID: {meta_id}, Jednotka: {unit}) v tabulce {table}")

            num_expr = "to_number(state)"
            numeric_filter = f"{num_expr} IS NOT NULL"

            if is_states:
                click.echo("  Načítám data stavů pro analýzu (může to chvíli trvat)...")
                cursor.execute(
                    f"SELECT MIN({num_expr}), MAX({num_expr}), AVG({num_expr}) FROM states WHERE metadata_id = ? AND {numeric_filter}",
                    (meta_id,)
                )
            else:
                cursor.execute(f"SELECT MIN(min), MAX(max), AVG(mean) FROM {table} WHERE metadata_id = ?", (meta_id,))
            curr_min, curr_max, curr_avg = cursor.fetchone()

            if curr_min is None or curr_max is None:
                if is_states:
                    click.echo("  Žádná číselná data v databázi.")
                else:
                    click.echo("  Žádná data s min/max (prázdné, nebo kumulativní entita – pro 'sum' použijte 'outliers').")
                return

            avg_str = f"{curr_avg:.2f}" if curr_avg is not None else "N/A"
            click.echo(f"  Současný rozsah dat: {curr_min} ... {curr_max} (Průměr: {avg_str})")

            # --- Interaktivní mód (Určení limitů) ---
            if min_limit is None and max_limit is None:
                click.echo("\n--- Analýza extrémů ---")

                if is_states:
                    for label, order in (("nejvyšších", "DESC"), ("nejnižších", "ASC")):
                        cursor.execute(
                            f"SELECT last_updated_ts, state FROM states WHERE metadata_id = ? AND {numeric_filter} "
                            f"ORDER BY {num_expr} {order} LIMIT 5",
                            (meta_id,)
                        )
                        click.echo(f"  Top 5 {label} hodnot:")
                        for row in cursor.fetchall():
                            click.echo(f"    {format_ts(row['last_updated_ts'])}: {row['state']}")
                else:
                    for label, col, order in (("nejvyšších", "max", "DESC"), ("nejnižších", "min", "ASC")):
                        cursor.execute(
                            f"SELECT start_ts, {col} FROM {table} WHERE metadata_id = ? AND {col} IS NOT NULL "
                            f"ORDER BY {col} {order} LIMIT 5",
                            (meta_id,)
                        )
                        click.echo(f"  Top 5 {label} hodnot ({col}):")
                        for row in cursor.fetchall():
                            click.echo(f"    {format_ts(row['start_ts'])}: {row[col]}")

                if click.confirm("\nChcete definovat limity a provést čištění?", default=True):
                    max_limit = click.prompt("  Nový MAX limit (vše nad bude upraveno)", type=float, default=curr_max)
                    min_limit = click.prompt("  Nový MIN limit (vše pod bude upraveno)", type=float, default=curr_min)
                else:
                    click.echo("Konec.")
                    return

            if min_limit is not None and max_limit is not None and min_limit > max_limit:
                click.echo(f"❌ MIN limit ({min_limit}) je větší než MAX limit ({max_limit}).")
                return

            # Chybějící limit = neomezeno
            sql_min = min_limit if min_limit is not None else -1e15
            sql_max = max_limit if max_limit is not None else 1e15

            click.echo(f"\nHledám záznamy mimo rozsah <{sql_min}, {sql_max}> ...")

            # --- Vyhledání problematických řádků ---
            if is_states:
                cond = f"({numeric_filter} AND ({num_expr} < ? OR {num_expr} > ?))"
                cursor.execute(
                    f"SELECT state_id, last_updated_ts, state FROM states WHERE metadata_id = ? AND {cond} LIMIT 5",
                    (meta_id, sql_min, sql_max)
                )
                preview_rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM states WHERE metadata_id = ? AND {cond}", (meta_id, sql_min, sql_max))
                total_bad = cursor.fetchone()[0]
            else:
                cond = "(min < ? OR max > ?)"
                cursor.execute(
                    f"SELECT id, start_ts, min, max, mean FROM {table} WHERE metadata_id = ? AND {cond} LIMIT 5",
                    (meta_id, sql_min, sql_max)
                )
                preview_rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE metadata_id = ? AND {cond}", (meta_id, sql_min, sql_max))
                total_bad = cursor.fetchone()[0]

            if total_bad == 0:
                click.echo("✅ Všechna data jsou v limitu.")
                return

            click.echo(f"⚠️ Nalezeno {total_bad} záznamů mimo rozsah.")
            click.echo("Náhled problémových dat:")
            for row in preview_rows:
                if is_states:
                    click.echo(f"  ID {row['state_id']} ({format_ts(row['last_updated_ts'])}): state={row['state']}")
                else:
                    click.echo(f"  ID {row['id']} ({format_ts(row['start_ts'])}): min={row['min']}, max={row['max']}, mean={row['mean']}")
            if total_bad > len(preview_rows): click.echo("  ...")

            # --- Oprava ---
            if not click.confirm(f"Chcete provést opravu v režimu '{fix_mode.upper()}'?"):
                click.echo("Akce zrušena.")
                return

            if not warn_if_ha_running(db):
                click.echo("Akce zrušena.")
                return

            if click.confirm("Chcete vytvořit zálohu před opravou? (Doporučeno)", default=True):
                db.create_backup("clean")

            try:
                if is_states:
                    if fix_mode == 'delete':
                        # Navazující stavy odkazují na mazané přes old_state_id – vynulujeme (stejně jako HA purge)
                        cursor.execute(
                            f"UPDATE states SET old_state_id = NULL WHERE old_state_id IN "
                            f"(SELECT state_id FROM states WHERE metadata_id = ? AND {cond})",
                            (meta_id, sql_min, sql_max)
                        )
                        cursor.execute(f"DELETE FROM states WHERE metadata_id = ? AND {cond}", (meta_id, sql_min, sql_max))
                        click.echo(f"🗑️ Smazáno {cursor.rowcount} záznamů ze states.")
                    else:
                        cursor.execute(
                            f"UPDATE states SET state = ? WHERE metadata_id = ? AND {numeric_filter} AND {num_expr} > ?",
                            (format_state(sql_max), meta_id, sql_max)
                        )
                        c1 = cursor.rowcount
                        cursor.execute(
                            f"UPDATE states SET state = ? WHERE metadata_id = ? AND {numeric_filter} AND {num_expr} < ?",
                            (format_state(sql_min), meta_id, sql_min)
                        )
                        c2 = cursor.rowcount
                        click.echo(f"🔧 Upraveno {c1} (nad) + {c2} (pod) záznamů v tabulce states.")
                else:
                    if fix_mode == 'delete':
                        cursor.execute(f"DELETE FROM {table} WHERE metadata_id = ? AND {cond}", (meta_id, sql_min, sql_max))
                        click.echo(f"🗑️ Smazáno {cursor.rowcount} záznamů.")
                    else:
                        # Ořízneme max, mean i min na <sql_min, sql_max>
                        cursor.execute(f"UPDATE {table} SET max = ? WHERE metadata_id = ? AND max > ?", (sql_max, meta_id, sql_max))
                        c_max = cursor.rowcount
                        cursor.execute(f"UPDATE {table} SET mean = ? WHERE metadata_id = ? AND mean > ?", (sql_max, meta_id, sql_max))
                        cursor.execute(f"UPDATE {table} SET min = ? WHERE metadata_id = ? AND min > ?", (sql_max, meta_id, sql_max))

                        cursor.execute(f"UPDATE {table} SET min = ? WHERE metadata_id = ? AND min < ?", (sql_min, meta_id, sql_min))
                        c_min = cursor.rowcount
                        cursor.execute(f"UPDATE {table} SET mean = ? WHERE metadata_id = ? AND mean < ?", (sql_min, meta_id, sql_min))
                        cursor.execute(f"UPDATE {table} SET max = ? WHERE metadata_id = ? AND max < ?", (sql_min, meta_id, sql_min))

                        click.echo(f"🔧 Upraveno: {c_max} maxim (nad), {c_min} minim (pod).")

                conn.commit()
                click.echo("✅ Hotovo.")
            except Exception as e:
                conn.rollback()
                click.echo(f"❌ Chyba: {e}", err=True)
                click.echo("Všechny změny byly vráceny zpět (rollback).")

    except click.exceptions.Abort:
        raise
    except Exception as e:
        click.echo(f"Chyba: {e}", err=True)
