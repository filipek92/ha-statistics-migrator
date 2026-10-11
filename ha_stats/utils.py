import os
import time
import click
from datetime import datetime

# Pokud byla DB změněna před méně než tolika sekundami, HA nejspíš běží
HA_RUNNING_THRESHOLD_SEC = 120


def format_ts(ts, fmt='%Y-%m-%d %H:%M:%S'):
    if ts is None: return "N/A"
    return datetime.fromtimestamp(ts).strftime(fmt)


def get_db(ctx):
    """Vrátí DatabaseManager z kontextu, nebo ukončí příkaz srozumitelnou chybou."""
    db = ctx.obj.get('db') if ctx.obj else None
    if db is None:
        error = ctx.obj.get('db_error') if ctx.obj else None
        raise click.ClickException(str(error or "Databáze není dostupná. Zadejte cestu parametrem --db-path."))
    return db


def warn_if_ha_running(db):
    """
    Zápis do DB za běhu HA koliduje s recorderem (a jeho cache metadat).
    Pokud byla DB (nebo WAL) nedávno změněna, varuje a vyžádá potvrzení.
    Vrací True, pokud se má pokračovat.
    """
    paths = [p for p in (db.db_path, db.db_path + "-wal") if os.path.exists(p)]
    if not paths:
        return True
    age = time.time() - max(os.path.getmtime(p) for p in paths)
    if age >= HA_RUNNING_THRESHOLD_SEC:
        return True

    click.echo(f"\n⚠️  Databáze byla změněna před {int(age)} s – Home Assistant zřejmě běží!")
    click.echo("   Před zápisem zastavte HA (např. 'ha core stop'), jinak hrozí kolize s recorderem.")
    return click.confirm("   Přesto pokračovat?", default=False)


def find_orphans(cursor):
    """
    Statistiky, ke kterým neexistuje entita v states_meta.
    Externí statistiky (např. 'tibber:energy') nejsou entity, proto se vynechávají.
    NOT EXISTS místo NOT IN – NOT IN vrací prázdný výsledek, pokud je v podmnožině NULL.
    """
    cursor.execute("""
        SELECT id, statistic_id, unit_of_measurement
        FROM statistics_meta sm
        WHERE statistic_id NOT LIKE '%:%'
          AND NOT EXISTS (SELECT 1 FROM states_meta s WHERE s.entity_id = sm.statistic_id)
    """)
    return cursor.fetchall()


def is_external_statistic(statistic_id):
    return ':' in statistic_id


def prompt_index(text, count, allow_cancel=True):
    """Vyžádá index v rozsahu 0..count-1. Při zrušení (-1 / prázdný vstup) vrací None."""
    while True:
        choice = click.prompt(text, default="" if allow_cancel else None, show_default=False)
        choice = str(choice).strip()
        if allow_cancel and choice in ("", "-1", "q"):
            return None
        if choice.isdigit() and 0 <= int(choice) < count:
            return int(choice)
        click.echo(f"❌ Neplatný index (0–{count - 1}).")


def search_statistic(cursor, prompt_text, exclude_id=None, ref_unit=None):
    """
    Interaktivní vyhledání statistiky podle části názvu.
    Vrací řádek statistics_meta (id, statistic_id, unit_of_measurement), nebo None.
    """
    search = click.prompt(prompt_text, default="", show_default=False).strip()
    if not search:
        return None

    query = "SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ?"
    params = [f"%{search}%"]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    cursor.execute(query, params)
    results = cursor.fetchall()

    if not results:
        click.echo("❌ Žádná entita nenalezena.")
        return None

    click.echo("\nNALEZENÉ ENTITY:")
    for idx, row in enumerate(results):
        unit = row['unit_of_measurement'] or 'N/A'
        warn = ""
        if ref_unit is not None:
            warn = " OK" if row['unit_of_measurement'] == ref_unit else " ⚠️ jiná jednotka"
        click.echo(f" [{idx}] {row['statistic_id']} (Unit: {unit}){warn}")

    idx = prompt_index("Vyberte index (enter pro zrušení)", len(results))
    return results[idx] if idx is not None else None
