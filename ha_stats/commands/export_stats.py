import click
import csv
import os
from datetime import datetime
from ha_stats.db import DatabaseManager

@click.command('export')
@click.argument('entity_ids', nargs=-1)
@click.option('--output', type=click.Path(dir_okay=False), required=False, default="export_stats.csv", help='Cílový soubor pro export (CSV). Default: export_stats.csv')
@click.pass_context
def export_command(ctx, entity_ids, output):
    """
    Vyexportuje statistiky pro zadané entity do JEDNOHO CSV souboru.
    Data jsou zarovnána podle času (time-series).
    
    Pokud chcete exportovat více entit najednou, zadejte je jako argumenty:
      ha-stats export sensor.t1 sensor.t2 --output out.csv
    
    Sloupce v CSV:
      - start_ts: Unix timestamp
      - date: Čitelný datum
      - <entity_id>: Hodnota (sum pro kumulativní, mean pro ostatní)
    """
    db: DatabaseManager = ctx.obj.get('db')
    if not db: return

    if not entity_ids:
        click.echo("Musíte specifikovat alespoň jednu entitu.")
        return

    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Zjistíme ID pro zadané entity a jejich typ (sum vs mean)
        meta_map = {} # {'sensor.x': {'id': 123, 'has_sum': 1}}
        
        placeholders = ','.join('?' for _ in entity_ids)
        cursor.execute(f"SELECT id, statistic_id, has_sum FROM statistics_meta WHERE statistic_id IN ({placeholders})", entity_ids)
        rows = cursor.fetchall()
        
        found_ids = set()
        for row in rows:
            sid = row['statistic_id']
            meta_map[sid] = {'id': row['id'], 'has_sum': row['has_sum']}
            found_ids.add(sid)
            
        # Check missing
        for e in entity_ids:
            if e not in found_ids:
                click.echo(f"⚠️ Entita '{e}' nebyla nalezena v DB.")
        
        if not meta_map:
            return

        click.echo(f"Exportuji {len(meta_map)} entit do '{output}'...")

        # 2. Načtení dat (vše do paměti)
        data_by_ts = {} # timestamp -> { 'entity_id': val }

        for entity_id in entity_ids:
            if entity_id not in meta_map: continue
            
            m_id = meta_map[entity_id]['id']
            has_sum = meta_map[entity_id]['has_sum']
            
            # Logika výběru sloupce:
            # - Pokud has_sum=1 (energie, voda, plyn) -> zajímá nás 'sum' (kumulativní stav).
            # - Pokud has_sum=0 (teplota, výkon, vlhkost) -> zajímá nás 'mean' (průměrná hodnota).
            #   Pokud je mean NULL, zkusíme 'state'.
            
            val_expr = "sum" if has_sum else "COALESCE(mean, state)"
            
            cursor.execute(f"SELECT start_ts, {val_expr} as val FROM statistics WHERE metadata_id = ? ORDER BY start_ts", (m_id,))
            rows = cursor.fetchall()
            
            for row in rows:
                ts = row['start_ts']
                val = row['val']
                
                if ts not in data_by_ts:
                    data_by_ts[ts] = {}
                
                data_by_ts[ts][entity_id] = val

        # 3. Zápis do CSV
        click.echo(f"  Zapisuji CSV ({len(data_by_ts)} časových bodů)...")
        sorted_ts = sorted(data_by_ts.keys())
        
        try:
            with open(output, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['start_ts', 'date'] + list(entity_ids)
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for ts in sorted_ts:
                    row_data = {
                        'start_ts': ts,
                        'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    # Přidáme hodnoty pro každou entitu v daném čase
                    for entity_id in entity_ids:
                        # Pokud data chybí, necháme prázdné nebo 'None'? CSV DictWriter nechá prázdné, což je OK.
                        row_data[entity_id] = data_by_ts[ts].get(entity_id, '')
                    
                    writer.writerow(row_data)

            click.echo(f"✅ Export dokončen: {output}")
            
        except Exception as e:
            click.echo(f"❌ Chyba při zápisu: {e}", err=True)

