import click
from datetime import datetime
from ha_stats.db import DatabaseManager

@click.command('outliers')
@click.argument('entity_id')
@click.option('--threshold', type=float, default=None, help='Pevný práh skoku (např. 1000). Pokud neuvedeno, bude vypočteno ze změny za čas.')
@click.option('--max-rate', type=float, default=None, help='Maximální očekávaná změna za hodinu (např. max výkon kW pro kWh senzor).')
@click.pass_context
def outliers_command(ctx, entity_id, threshold, max_rate):
    """
    Detekuje a opravuje extrémní skoky (outliers) v kumulativních statistikách (sum).
    Ideální pro entity spotřeby, které měly chybný vysoký odečet.
    Pokud nezadáte --threshold, nástroj se zeptá na maximální reálnou změnu (Rate).
    """
    db: DatabaseManager = ctx.obj['db']
    db_path = db.db_path

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Získání Metadata ID
            cursor.execute("SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
            meta_row = cursor.fetchone()
            
            if not meta_row:
                click.echo(f"❌ Entita '{entity_id}' nebyla nalezena.")
                return
            
            m_id = meta_row['id']
            unit = meta_row['unit_of_measurement'] or ""

            click.echo(f"Analyzuji entitu: {entity_id} (ID: {m_id}, Jednotka: {unit})")

            # 2. Určení Threshold logiky
            use_rate = False
            
            if threshold is None:
                if max_rate is None:
                    prompt_text = f"Zadejte maximální možnou změnu za hodinu (Max Rate) v {unit}/h"
                    
                    if unit == 'kWh':
                        prompt_text += f"\n (Např. hlavní jistič 3x25A -> max cca 17 kW. Zadejte '17')"
                    elif unit == 'Wh':
                        # 17 kW = 17000 W(h/h)
                        prompt_text += f"\n (Např. hlavní jistič 3x25A -> max cca 17000 W. Zadejte '17000')"
                    elif unit == 'm³':
                        prompt_text += f"\n (Např. max průtok vodoměru. Zadejte kolik m³ proteče za hodinu)"
                    
                    max_rate = click.prompt(prompt_text, type=float)
                
                click.echo(f"  Nastaven limit změny: {max_rate} {unit}/h")
                use_rate = True
            else:
                click.echo(f"  Hledám skoky > {threshold} {unit} (fixní práh)...")

            # 3. Detekce (výpočet delta v Pythonu pro kompatibilitu se starším SQLite)
            query = """
            SELECT id, start_ts, sum
            FROM statistics
            WHERE metadata_id = ?
            ORDER BY start_ts
            """
            
            cursor.execute(query, (m_id,))
            rows = cursor.fetchall()
            
            outliers = []
            prev_sum = None
            prev_ts = None
            
            for row in rows:
                curr_sum = row['sum']
                curr_ts = row['start_ts']
                
                if prev_sum is None:
                    prev_sum = curr_sum
                    prev_ts = curr_ts
                    continue
                
                # Výpočet delt
                delta = curr_sum - prev_sum
                time_delta = curr_ts - prev_ts
                
                # Posuneme okno
                prev_sum = curr_sum
                prev_ts = curr_ts

                if curr_sum is None or time_delta <= 0:
                    continue
                    
                is_outlier = False
                reason = ""
                
                # Check logic
                if use_rate:
                    # Přepočet max_rate na max_delta pro tento časový interval
                    # time_delta je v sekundách. rate je "za hodinu".
                    hours_diff = time_delta / 3600.0
                    
                    # Povolíme lehkou toleranci (např. 1.1x), abychom nechytali hraniční hodnoty
                    allowed_delta = max_rate * hours_diff * 1.2
                    
                    # Minimální allowed delta (aby nás netrápily desetiny u 1s intervalů)
                    if allowed_delta < 0.1: allowed_delta = 0.1
                    
                    if abs(delta) > allowed_delta:
                        is_outlier = True
                        reason = f"Limit: {allowed_delta:.2f} (pro {int(time_delta/60)} min)"
                else:
                    # Fixní threshold
                    if abs(delta) > threshold:
                        is_outlier = True
                        reason = f"Limit: {threshold}"

                if is_outlier:
                    # Uložíme si důvod pro výpis
                    row_dict = dict(row)
                    row_dict['delta'] = delta
                    row_dict['time_delta'] = time_delta
                    row_dict['reason'] = reason
                    outliers.append(row_dict)
            
            if not outliers:
                click.echo("✅ Žádné extrémní skoky nenalezeny.")
                return

            click.echo(f"\n⚠️  NALEZENO {len(outliers)} PODEZŘELÝCH SKOKŮ:")
            click.echo(f"{'Datum':<20} | {'Hodnota':<10} | {'Skok (Delta)':<12} | {'Interval':<8} | {'Důvod'}")
            click.echo("-" * 80)
            
            for row in outliers:
                ts_str = datetime.fromtimestamp(row['start_ts']).strftime('%Y-%m-%d %H:%M:%S')
                duration_min = round(row['time_delta'] / 60, 1) if row['time_delta'] else 0
                click.echo(f"{ts_str:<20} | {row['sum']:<10.2f} | {row['delta']:<12.2f} | {duration_min:<5} min | {row['reason']}")

            # 4. Potvrzení opravy
            click.echo("\n💡 Oprava: Odečte velikost skoku ode všech následujících záznamů.")
            if not click.confirm("Chcete provést opravu těchto skoků?"):
                return
            
            if click.confirm("Chcete nejprve vytvořit zálohu databáze? (Doporučeno, ale může trvat dlouho)", default=True):
                db.create_backup("outliers")
            
            # 4. Aplikace opravy
            # Musíme aplikovat opravy chronologicky!
            # Pokud máme skok 50000 v čase T1, musíme odečíst 50000 od všech T >= T1.
            
            count_fixes = 0
            for row in outliers:
                jump_ts = row['start_ts']
                jump_val = row['delta']
                
                # Pokud je delta kladná (skok nahoru), musíme odečíst. 
                # Pokud je delta záporná (skok dolů), přičteme.
                
                click.echo(f"  Opravuji skok z času {datetime.fromtimestamp(jump_ts).strftime('%H:%M:%S')} (delta {jump_val:.2f})...")
                
                # Oprava v long-term statistics
                cursor.execute("UPDATE statistics SET sum = sum - ? WHERE metadata_id = ? AND start_ts >= ?", (jump_val, m_id, jump_ts))
                
                # Oprava v short-term statistics
                cursor.execute("UPDATE statistics_short_term SET sum = sum - ? WHERE metadata_id = ? AND start_ts >= ?", (jump_val, m_id, jump_ts))
                
                count_fixes += 1

            conn.commit()
            click.echo(f"✅ Hotovo. Opraveno {count_fixes} skoků.")
            click.echo("Poznámka: Projeví se v grafech po restartu HA nebo obnovení stránky.")

    except Exception as e:
        click.echo(f"Chyba: {e}", err=True)
