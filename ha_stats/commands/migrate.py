import click
from datetime import datetime

def format_ts(ts):
    if ts is None: return "N/A"
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

@click.command('migrate')
@click.pass_context
def migrate_command(ctx):
    """
    Interaktivní průvodce migrací "sirotčích" statistik.
    Řeší překryvy a navazuje kumulativní součty (sum).
    """
    db = ctx.obj['db']
    db_path = db.db_path

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Hledání sirotčích statistik
            click.echo("🔍 Hledám sirotčí záznamy (orphans)...")
            cursor.execute("""
                SELECT id, statistic_id, unit_of_measurement
                FROM statistics_meta 
                WHERE statistic_id NOT IN (SELECT entity_id FROM states_meta)
            """)
            orphans = cursor.fetchall()
            
            source_id = None
            source_name = None
            source_unit = None

            if orphans:
                click.echo(f"\n📍 NALEZENÍ SIROTCI ({len(orphans)}):")
                for idx, row in enumerate(orphans):
                    unit = row['unit_of_measurement'] or 'N/A'
                    click.echo(f" [{idx}] {row['statistic_id']:<50} (Unit: {unit})")
                
                choice = click.prompt("\nVyberte index sirotka (nebo 's' pro vyhledávání)", default="s")
                
                if choice.isdigit():
                    idx = int(choice)
                    if 0 <= idx < len(orphans):
                        source_id = orphans[idx]['id']
                        source_name = orphans[idx]['statistic_id']
                        source_unit = orphans[idx]['unit_of_measurement']

            # Pokud nevybráno z orphans, hledáme manuálně
            if not source_id:
                search = click.prompt("Zadejte část názvu zdrojové entity", type=str)
                cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ?", (f"%{search}%",))
                results = cursor.fetchall()
                
                if not results:
                    click.echo("❌ Žádná entita nenalezena.")
                    return
                
                click.echo("NALEZENÉ ENTITY:")
                for idx, row in enumerate(results):
                    unit = row['unit_of_measurement'] or 'N/A'
                    click.echo(f" [{idx}] {row['statistic_id']} (Unit: {unit})")
                
                idx = click.prompt("Vyberte index (nebo -1 pro zrušení)", type=int)
                if idx < 0: return

                source_id = results[idx]['id']
                source_name = results[idx]['statistic_id']
                source_unit = results[idx]['unit_of_measurement']

            # 2. Výběr cíle (Smart Match)
            click.echo(f"\n🔍 Hledám cíle pro: {source_name}")
            
            # Heuristika pro hledání cílů:
            # 1. Konec názvu (suffix) - typicky se mění prefix zařízení (sensor.old_power -> sensor.new_power)
            # 2. Stejná jednotka - zásadní pro validní migraci
            
            # Zkusíme extrahovat suffix za posledním podtržítkem
            entity_part = source_name.split('.')[-1] # "old_device_energy"
            parts = entity_part.split('_')
            
            potential_suffixes = []
            if len(parts) > 1:
                potential_suffixes.append(parts[-1]) # "energy"
                if len(parts) > 2:
                    potential_suffixes.append(f"{parts[-2]}_{parts[-1]}") # "device_energy"
            
            # Sestavíme query
            query = "SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE id != ?"
            params = [source_id]
            
            # Filtrujeme primárně podle jednotky (pokud je známá)
            if source_unit:
                query += " AND unit_of_measurement = ?"
                params.append(source_unit)
            
            # Pokud máme suffixy, přidáme LIKE podmínky
            if potential_suffixes:
                print(f"   (Hledám entity končící na: {', '.join(potential_suffixes)} se stejnou jednotkou)")
                like_clauses = " OR ".join(["statistic_id LIKE ?" for _ in potential_suffixes])
                query += f" AND ({like_clauses})"
                # Přidáme parametry pro LIKE (s % na začátku)
                for s in potential_suffixes:
                    params.append(f"%_{s}") # Hledáme "_suffix"
            else:
                # Fallback na hledání podobného textu
                query += " AND statistic_id LIKE ?"
                params.append(f"%{entity_part}%")

            cursor.execute(query, params)
            targets = cursor.fetchall()
            
            # Omezíme počet výsledků, abychom nezahltili uživatele
            if len(targets) > 15:
                # Pokud je jich moc, zkusíme řadit podle podobnosti názvu?
                # V SQL to neuděláme snadno, v Pythonu ano.
                # Pro teď jen ořízneme.
                pass 

            target_id = None
            target_name = None
            
            if targets:
                click.echo("\nDOPORUČENÉ CÍLE (Smart Match):")
                targets_map = {}
                display_idx = 0
                for row in targets:
                    match_symbol = "⭐" # Vždy match, protože filtrujeme podle unit (pokud existuje)
                    
                    # Zvýrazníme, pokud je název velmi podobný (např. jen jiný prefix)
                    # Ale pro uživatele stačí seznam.
                    
                    print(f" [{display_idx}] {match_symbol} {row['statistic_id']} ({row['unit_of_measurement']})")
                    targets_map[display_idx] = row
                    display_idx += 1
                
                t_choice = click.prompt("\nVyberte index cíle (nebo 'm' pro manuální zadání)", default="m")
                
                if t_choice.isdigit():
                    idx = int(t_choice)
                    if idx in targets_map:
                        target_id = targets_map[idx]['id']
                        target_name = targets_map[idx]['statistic_id']
            
            if not target_id:
                # Pokud Smart Match nenašel, nabídneme vyhledávání (Search) místo slepého zadání ID
                search_query = click.prompt("Zadejte část názvu cílové entity (nebo přesné ID)", default="")
                if search_query:
                    cursor.execute("SELECT id, statistic_id, unit_of_measurement FROM statistics_meta WHERE statistic_id LIKE ? AND id != ?", (f"%{search_query}%", source_id))
                    manual_results = cursor.fetchall()
                    
                    if manual_results:
                        click.echo("VÝSLEDKY HLEDÁNÍ:")
                        m_map = {}
                        for i, r in enumerate(manual_results):
                            uname = r['unit_of_measurement']
                            warn = "⚠️" if uname != source_unit else "OK"
                            print(f" [{i}] {r['statistic_id']} (Unit: {uname}) {warn}")
                            m_map[i] = r
                        
                        m_choice = click.prompt("Vyberte index (nebo enter pro zrušení)", default="")
                        if m_choice.isdigit() and int(m_choice) in m_map:
                             target_id = m_map[int(m_choice)]['id']
                             target_name = m_map[int(m_choice)]['statistic_id']
                    else:
                        click.echo("❌ Nic nenalezeno.")
                        return
                else:
                    return

            # 3. Analýza konfliktu a offsetu
            click.echo(f"\n⏳ ANALÝZA: {source_name} -> {target_name}")
            
            # Statistiky zdroje
            cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (source_id,))
            s_min, s_max, s_count = cursor.fetchone()
            
            # Statistiky cíle
            cursor.execute("SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM statistics WHERE metadata_id = ?", (target_id,))
            t_min, t_max, t_count = cursor.fetchone()

            click.echo(f"  Zdroj (SIROTEK): {source_name} | {format_ts(s_min)} -> {format_ts(s_max)} ({s_count} záznamů)")
            click.echo(f"  Cíl (AKTIVNÍ):   {target_name} | {format_ts(t_min)} -> {format_ts(t_max)} ({t_count} záznamů)")

            # Check overlap logic
            action_plan = "concat" # concat, merge_delete_source, merge_delete_target
            
            # Scénář A: Sirotek je starší (Standardní migrace) -> s_max < t_min
            # Scénář B: Sirotek je novější (Inverzní migrace, např. 'battery_2') -> s_min > t_max
            # Scénář C: Překryv (Overlap)
            
            cutoff_ts = None
            
            if s_max and t_min and s_max < t_min:
                gap_h = round((t_min - s_max)/3600, 1)
                click.echo(f"  ✅ STANDARDNÍ: Sirotek je starší. Navazuje s mezerou {gap_h} h.")
                action_plan = "concat" # Source ends before Target starts
                
            elif s_min and t_max and s_min > t_max:
                gap_h = round((s_min - t_max)/3600, 1)
                click.echo(f"  ✅ INVERZNÍ: Sirotek je novější (asi dočasný senzor). Navazuje s mezerou {gap_h} h.")
                action_plan = "concat_inverse" # Source starts after Target ends
            
            else:
                # Překryv!
                # Musíme zjistit rozsah překryvu
                overlap_start = max(s_min, t_min) if s_min and t_min else (s_min or t_min)
                overlap_end = min(s_max, t_max) if s_max and t_max else (s_max or t_max)
                overlap_h = round((overlap_end - overlap_start)/3600, 1)
                
                click.echo(f"  ⚠️  VAROVÁNÍ: Překryv dat ({overlap_h} h) v rozsahu {format_ts(overlap_start)} -> {format_ts(overlap_end)}.")
                
                # Rozhodování, co smazat?
                click.echo("  Musíme vyřešit konflikt v překrývajícím se období.")
                choice = click.prompt(
                    "  Která data v tomto období zachovat?\n"
                    f"   [S] Sirotek ({source_name}) - smažeme data z cílové entity v době překryvu\n"
                    f"   [C] Cíl     ({target_name}) - smažeme data ze sirotka (standardní chování)\n"
                    "   Vyberte", default="C"
                )
                
                if choice.upper() == 'S':
                    click.echo("  -> Budou smazána data z CÍLOVÉ entity v době překryvu.")
                    action_plan = "overlap_keep_source"
                else:
                    click.echo("  -> Budou smazána data ze ZDROJOVÉ entity (sirotka).")
                    action_plan = "overlap_keep_target"
            
            # Check Offset (Last sum)
            # Důležité: Offset řešíme pouze pokud má entita 'has_sum=1'. U 'mean' senzorů (teplota) se offset nepřičítá.
            cursor.execute("SELECT has_sum FROM statistics_meta WHERE id = ?", (source_id,))
            source_has_sum = cursor.fetchone()['has_sum']

            offset = 0.0
            if source_has_sum:
                cursor.execute("SELECT sum FROM statistics WHERE metadata_id = ? ORDER BY start_ts DESC LIMIT 1", (source_id,))
                last_sum_row = cursor.fetchone()
                offset = last_sum_row['sum'] if last_sum_row and last_sum_row['sum'] else 0.0
            
                if offset > 0:
                    click.echo(f"  📈 DETEKOVÁN OFFSET (SUM): {offset}")
                    click.echo("      Tato hodnota se přičte ke všem záznamům cílové entity, aby grafy pokračovaly.")
            else:
                click.echo("  ℹ️  Entita nemá 'has_sum', offset se nebude přičítat (OK pro teplotu, výkon atd.).")
            
            # 4. Potvrzení a Migrace
            if not click.confirm("\n❓ Chcete provést sloučení a migraci dat?"):
                click.echo("Operace zrušena.")
                return
            
            if click.confirm("Chcete nejprve vytvořit zálohu databáze? (Doporučeno)", default=True):
                db.create_backup("migrate")
            
            try:
                # 4.1 Delete overlaps
                if action_plan == "overlap_keep_target":
                    click.echo(f"  Mazání duplicitních dat ze SIROTKA ({source_name}) (zachováváme Cíl)...")
                    # Smažeme ze ZDROJE vše, co už je v Cíli (dle t_min, začátku cíle)
                    # Nebo lépe: Vše, co přesahuje do t_min. 
                    # Protože overlap znamená, že zdroj zasahuje do cíle nebo naopak.
                    # Pokud držíme Cíl, zdroj nesmí mít nic, co má Cíl.
                    cursor.execute("DELETE FROM statistics WHERE metadata_id = ? AND start_ts >= ?", (source_id, t_min))
                    cursor.execute("DELETE FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ?", (source_id, t_min))

                elif action_plan == "overlap_keep_source":
                    click.echo(f"  Mazání kolidujících dat z CÍLOVÉ entity ({target_name}) (upřednostňujeme Sirotka)...")
                    # Smažeme z CÍLE vše, co je v intervalu zdroje
                    cursor.execute("DELETE FROM statistics WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?", (target_id, s_min, s_max))
                    cursor.execute("DELETE FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?", (target_id, s_min, s_max))

                # 4.2 Update ID (The Migration) - toto proběhne vždy (spojení)
                click.echo("  Přepisování ID sirotka na aktivní entitu...")
                cursor.execute("UPDATE statistics SET metadata_id = ? WHERE metadata_id = ?", (target_id, source_id))
                cursor.execute("UPDATE statistics_short_term SET metadata_id = ? WHERE metadata_id = ?", (target_id, source_id))
                
                # 4.3 Apply Offset logic
                # Protože jsme právě změnili ID, vše je nyní pod 'target_id'.
                # Musíme rozlišit:
                #  (A) Standard: Zdroj byl starší -> jeho konec je offsetem pro původní Cíl.
                #  (B) Inverse: Zdroj byl novější -> konec původního Cíle je offsetem pro "bývalého" sirotka.
                
                # Jak to poznáme po UPDATE? Podle časů s_max, t_min.
                
                # (A) Standard: s_max < t_min (nebo se dotýkají).
                # Offset (poslední suma zdroje) se přičte k datům Cíle (ty jsou časově dál).
                if offset > 0 and (s_max is not None and t_min is not None) and s_max < t_min:
                     click.echo(f"  Přičítání offsetu {offset} k navazující historii (Standard)...")
                     # Aplikujeme od t_min dál
                     cursor.execute("UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, target_id, t_min))
                     cursor.execute("UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (offset, target_id, t_min))
                
                # (B) Inverzní: s_min > t_max.
                # Zdroj (nyní target_id) začíná v s_min. Původní Cíl končil v t_max.
                # Musíme vzít poslední sumu PŮVODNÍHO CÍLE a přičíst ji k "novým" datům (bývalý zdroj).
                elif (s_min is not None and t_max is not None) and s_min > t_max:
                     # Získáme poslední sumu z původního Cíle (ten končí kolem t_max)
                     # Hledáme poslední záznam před s_min.
                     cursor.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts < ? ORDER BY start_ts DESC LIMIT 1", (target_id, s_min))
                     last_target = cursor.fetchone()
                     target_offset = last_target['sum'] if last_target else 0.0
                     
                     if target_offset > 0:
                          click.echo(f"  Přičítání offsetu {target_offset} k připojené novější historii (Inverzní)...")
                          # Aplikujeme od s_min dál (to jsou data bývalého zdroje)
                          cursor.execute("UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (target_offset, target_id, s_min))
                          cursor.execute("UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (target_offset, target_id, s_min))
                
                # Pokud byl overlap, offsety jsou složité a raději je neděláme automaticky, nebo by to chtělo re-kalkulaci. 
                # (Předpokládáme, že uživatel ví, co dělá, když si vybral overlapping data.)

                # 4.4 Cleanup
                click.echo("  Mažu stará metadata sirotka...")
                cursor.execute("DELETE FROM statistics_meta WHERE id = ?", (source_id,))
                
                conn.commit()
                click.echo("\n✅ HOTOVO! Migrace úspěšně dokončena.")
                
            except Exception as e:
                conn.rollback()
                click.echo(f"\n❌ CHYBA: {e}", err=True)
                click.echo("Všechny změny byly vráceny zpět (rollback).")

    except Exception as e:
        click.echo(f"Chyba: {e}", err=True)
