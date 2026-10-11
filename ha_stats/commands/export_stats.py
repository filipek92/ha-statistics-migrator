import click
import csv
import sys
from contextlib import contextmanager
from ha_stats.utils import format_ts, get_db


@contextmanager
def open_output(filename):
    """'-' = stdout, jinak soubor."""
    if filename == "-":
        yield sys.stdout
    else:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            yield f


@click.command('export')
@click.argument('entity_ids', nargs=-1)
@click.option('--output', required=False, default="-", help='Cílový soubor pro export (CSV). "-" (default) vypíše na stdout.')
@click.option('--min-max', is_flag=True, help='Přidat sloupce min a max (pouze pokud je exportována jen 1 entita).')
@click.option('--short-term', is_flag=True, help='Použít krátkodobou historii (statistics_short_term) namísto dlouhodobé.')
@click.pass_context
def export_command(ctx, entity_ids, output, min_max, short_term):
    """
    Vyexportuje statistiky pro zadané entity do JEDNOHO CSV souboru.
    Data jsou zarovnána podle času (time-series).
    
    Pokud chcete exportovat více entit najednou, zadejte je jako argumenty:
      ha-stats export sensor.t1 sensor.t2 --output out.csv
    
    Sloupce v CSV:
      - start_ts: Unix timestamp
      - date: Čitelný datum
      - <entity_id>: Hodnota (sum pro kumulativní, mean pro ostatní)
      
    Při použití --min-max (a jedné entitě) přidá sloupce <entity_id>_min a <entity_id>_max.
    """
    db = get_db(ctx)

    # Duplicitní argumenty by vytvořily duplicitní sloupce
    entity_ids = tuple(dict.fromkeys(entity_ids))

    if not entity_ids:
        click.echo("Musíte specifikovat alespoň jednu entitu.", err=True)
        return

    # Pokud je výstup "-", potlačíme informační výpisy, aby nešly do trubky
    to_stdout = output == "-"
    
    if min_max and len(entity_ids) > 1:
        click.echo("⚠️  Varování: Přepínač --min-max je ignorován při exportu více entit najednou.", err=True)
        min_max = False
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Zjistíme ID pro zadané entity a jejich typ (sum vs mean)
        meta_map = {} # {'sensor.x': {'id': 123, 'has_sum': 1}}
        
        placeholders = ','.join('?' for _ in entity_ids)
        cursor.execute(f"SELECT id, statistic_id, has_sum FROM statistics_meta WHERE statistic_id IN ({placeholders})", list(entity_ids))
        rows = cursor.fetchall()
        
        found_ids = set()
        for row in rows:
            sid = row['statistic_id']
            meta_map[sid] = {'id': row['id'], 'has_sum': row['has_sum']}
            found_ids.add(sid)
            
        # Check missing (pouze do stderr)
        for e in entity_ids:
            if e not in found_ids:
                click.echo(f"⚠️ Entita '{e}' nebyla nalezena v DB.", err=True)
        
        if not meta_map:
            return

        table_name = "statistics_short_term" if short_term else "statistics"
        
        if not to_stdout:
            click.echo(f"Exportuji {len(meta_map)} entit do '{output}' (Tabulka: {table_name})...")

        # 2. Načtení dat (vše do paměti)
        data_by_ts = {} # timestamp -> { 'entity_id': val }

        for entity_id in entity_ids:
            if entity_id not in meta_map: continue
            
            m_id = meta_map[entity_id]['id']
            has_sum = meta_map[entity_id]['has_sum']
            
            val_expr = "sum" if has_sum else "COALESCE(mean, state)"
            
            if min_max:
                cursor.execute(f"SELECT start_ts, {val_expr} as val, min, max FROM {table_name} WHERE metadata_id = ? ORDER BY start_ts", (m_id,))
            else:
                cursor.execute(f"SELECT start_ts, {val_expr} as val FROM {table_name} WHERE metadata_id = ? ORDER BY start_ts", (m_id,))
            
            rows = cursor.fetchall()
            
            for row in rows:
                ts = row['start_ts']
                val = row['val']
                
                if ts not in data_by_ts:
                    data_by_ts[ts] = {}
                
                data_by_ts[ts][entity_id] = val
                
                if min_max:
                    data_by_ts[ts][f"{entity_id}_min"] = row['min']
                    data_by_ts[ts][f"{entity_id}_max"] = row['max']

        # 3. Zápis do CSV
        if not to_stdout:
            click.echo(f"  Zapisuji CSV ({len(data_by_ts)} časových bodů)...")
        
        sorted_ts = sorted(data_by_ts.keys())
        
        # Připravíme pole pro hlavičku
        fieldnames = ['start_ts', 'date'] + list(entity_ids)
        if min_max:
            single_id = entity_ids[0]
            fieldnames.extend([f"{single_id}_min", f"{single_id}_max"])
        
        try:
            with open_output(output) as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for ts in sorted_ts:
                    row_data = {
                        'start_ts': ts,
                        'date': format_ts(ts)
                    }
                    for entity_id in entity_ids:
                        row_data[entity_id] = data_by_ts[ts].get(entity_id, '')
                    
                    if min_max:
                        single_id = entity_ids[0]
                        row_data[f"{single_id}_min"] = data_by_ts[ts].get(f"{single_id}_min", '')
                        row_data[f"{single_id}_max"] = data_by_ts[ts].get(f"{single_id}_max", '')
                    
                    writer.writerow(row_data)

            if not to_stdout:
                click.echo(f"✅ Export dokončen: {output}")
            
        except Exception as e:
            click.echo(f"❌ Chyba při zápisu: {e}", err=True)

