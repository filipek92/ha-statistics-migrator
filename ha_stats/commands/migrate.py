import click
from ha_stats.utils import format_ts, get_db, find_orphans, prompt_index, search_statistic, warn_if_ha_running

STAT_TABLES = ("statistics", "statistics_short_term")


def _time_range(cursor, table, metadata_id):
    cursor.execute(f"SELECT MIN(start_ts), MAX(start_ts), COUNT(*) FROM {table} WHERE metadata_id = ?", (metadata_id,))
    return cursor.fetchone()


def _last_sum(cursor, metadata_id):
    """Poslední nenulová (ne-NULL) suma entity v dlouhodobých statistikách, jinak 0."""
    cursor.execute(
        "SELECT sum FROM statistics WHERE metadata_id = ? AND sum IS NOT NULL ORDER BY start_ts DESC LIMIT 1",
        (metadata_id,)
    )
    row = cursor.fetchone()
    return row['sum'] if row else 0.0


@click.command('migrate')
@click.pass_context
def migrate_command(ctx):
    """
    Interaktivní průvodce migrací "sirotčích" statistik.
    Řeší překryvy a navazuje kumulativní součty (sum).
    """
    db = get_db(ctx)

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Hledání sirotčích statistik
            click.echo("🔍 Hledám sirotčí záznamy (orphans)...")
            orphans = find_orphans(cursor)

            source = None

            if orphans:
                click.echo(f"\n📍 NALEZENÍ SIROTCI ({len(orphans)}):")
                for idx, row in enumerate(orphans):
                    unit = row['unit_of_measurement'] or 'N/A'
                    click.echo(f" [{idx}] {row['statistic_id']:<50} (Unit: {unit})")

                idx = prompt_index("\nVyberte index sirotka (enter pro vyhledávání)", len(orphans))
                if idx is not None:
                    source = orphans[idx]

            # Pokud nevybráno z orphans, hledáme manuálně
            if source is None:
                source = search_statistic(cursor, "Zadejte část názvu zdrojové entity")
                if source is None:
                    return

            source_id = source['id']
            source_name = source['statistic_id']
            source_unit = source['unit_of_measurement']

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
                click.echo(f"   (Hledám entity končící na: {', '.join(potential_suffixes)} se stejnou jednotkou)")
                like_clauses = " OR ".join(["statistic_id LIKE ?" for _ in potential_suffixes])
                query += f" AND ({like_clauses})"
                for s in potential_suffixes:
                    params.append(f"%_{s}") # Hledáme "_suffix"
            else:
                # Fallback na hledání podobného textu
                query += " AND statistic_id LIKE ?"
                params.append(f"%{entity_part}%")

            cursor.execute(query, params)
            targets = cursor.fetchall()

            target = None

            if targets:
                click.echo("\nDOPORUČENÉ CÍLE (Smart Match):")
                for idx, row in enumerate(targets):
                    click.echo(f" [{idx}] ⭐ {row['statistic_id']} ({row['unit_of_measurement']})")

                idx = prompt_index("\nVyberte index cíle (enter pro manuální vyhledání)", len(targets))
                if idx is not None:
                    target = targets[idx]

            if target is None:
                target = search_statistic(
                    cursor, "Zadejte část názvu cílové entity (enter pro zrušení)",
                    exclude_id=source_id, ref_unit=source_unit
                )
                if target is None:
                    return

            target_id = target['id']
            target_name = target['statistic_id']

            if target['unit_of_measurement'] != source_unit:
                click.echo(f"\n⚠️  Jednotky se liší ({source_unit} vs {target['unit_of_measurement']}). Hodnoty se NEpřepočítávají!")

            # 3. Analýza konfliktu a offsetu
            click.echo(f"\n⏳ ANALÝZA: {source_name} -> {target_name}")

            s_min, s_max, s_count = _time_range(cursor, "statistics", source_id)
            t_min, t_max, t_count = _time_range(cursor, "statistics", target_id)

            click.echo(f"  Zdroj (SIROTEK): {source_name} | {format_ts(s_min)} -> {format_ts(s_max)} ({s_count} záznamů)")
            click.echo(f"  Cíl (AKTIVNÍ):   {target_name} | {format_ts(t_min)} -> {format_ts(t_max)} ({t_count} záznamů)")

            # Scénář A: Sirotek je starší (Standardní migrace) -> s_max < t_min
            # Scénář B: Sirotek je novější (Inverzní migrace, např. 'battery_2') -> s_min > t_max
            # Scénář C: Překryv (Overlap)
            # Scénář D: Jedna ze stran nemá dlouhodobá data -> prosté přepsání ID
            if s_count == 0 or t_count == 0:
                click.echo("  ℹ️  Jedna z entit nemá dlouhodobá data – data se jen přepíšou pod cílovou entitu.")
                action_plan = "concat"

            elif s_max < t_min:
                gap_h = round((t_min - s_max)/3600, 1)
                click.echo(f"  ✅ STANDARDNÍ: Sirotek je starší. Navazuje s mezerou {gap_h} h.")
                action_plan = "concat"

            elif s_min > t_max:
                gap_h = round((s_min - t_max)/3600, 1)
                click.echo(f"  ✅ INVERZNÍ: Sirotek je novější (asi dočasný senzor). Navazuje s mezerou {gap_h} h.")
                action_plan = "concat_inverse"

            else:
                overlap_start = max(s_min, t_min)
                overlap_end = min(s_max, t_max)
                overlap_h = round((overlap_end - overlap_start)/3600, 1)

                click.echo(f"  ⚠️  VAROVÁNÍ: Překryv dat ({overlap_h} h) v rozsahu {format_ts(overlap_start)} -> {format_ts(overlap_end)}.")

                click.echo("  Musíme vyřešit konflikt v překrývajícím se období.")
                choice = click.prompt(
                    "  Která data v tomto období zachovat?\n"
                    f"   [S] Sirotek ({source_name}) - smažeme data z cílové entity v době překryvu\n"
                    f"   [C] Cíl     ({target_name}) - smažeme data ze sirotka (standardní chování)\n"
                    "   Vyberte", default="C",
                    type=click.Choice(['S', 'C'], case_sensitive=False)
                )

                if choice.upper() == 'S':
                    click.echo("  -> Budou smazána data z CÍLOVÉ entity v rozsahu sirotka.")
                    action_plan = "overlap_keep_source"
                else:
                    click.echo("  -> Budou smazána data ze ZDROJOVÉ entity (sirotka) v rozsahu cíle.")
                    action_plan = "overlap_keep_target"

            # Offset řešíme pouze pokud mají OBĚ entity 'has_sum=1'. U 'mean' senzorů (teplota) se offset nepřičítá.
            cursor.execute("SELECT id, has_sum FROM statistics_meta WHERE id IN (?, ?)", (source_id, target_id))
            has_sum = {row['id']: bool(row['has_sum']) for row in cursor.fetchall()}
            sums_enabled = has_sum.get(source_id) and has_sum.get(target_id)

            offset = 0.0           # přičte se k datům cíle (standardní scénář)
            inverse_offset = 0.0   # přičte se k datům sirotka (inverzní scénář)

            if not sums_enabled:
                click.echo("  ℹ️  Entity nemají obě 'has_sum', offset se nebude přičítat (OK pro teplotu, výkon atd.).")
            elif action_plan == "concat" and s_count and t_count:
                offset = _last_sum(cursor, source_id)
                if offset:
                    click.echo(f"  📈 DETEKOVÁN OFFSET (SUM): {offset}")
                    click.echo("      Tato hodnota se přičte ke všem záznamům cílové entity, aby grafy pokračovaly.")
            elif action_plan == "concat_inverse":
                inverse_offset = _last_sum(cursor, target_id)
                if inverse_offset:
                    click.echo(f"  📈 DETEKOVÁN OFFSET (SUM): {inverse_offset}")
                    click.echo("      Tato hodnota (poslední suma cíle) se přičte k datům sirotka, aby grafy pokračovaly.")
            elif action_plan.startswith("overlap"):
                click.echo("  ⚠️  Při překryvu se offset nepřepočítává automaticky – na hranici dat může vzniknout skok v 'sum'.")
                click.echo("      Po migraci ho můžete opravit příkazem 'outliers' nebo 'fix-drops'.")

            # 4. Potvrzení a Migrace
            if not click.confirm("\n❓ Chcete provést sloučení a migraci dat?"):
                click.echo("Operace zrušena.")
                return

            if not warn_if_ha_running(db):
                click.echo("Operace zrušena.")
                return

            if click.confirm("Chcete nejprve vytvořit zálohu databáze? (Doporučeno)", default=True):
                db.create_backup("migrate")

            try:
                # 4.1 Delete overlaps
                # Rozsahy počítáme zvlášť pro každou tabulku (krátkodobé statistiky mají jiný rozsah než dlouhodobé).
                for table in STAT_TABLES:
                    if action_plan == "overlap_keep_target":
                        # Ze sirotka smažeme jen to, co spadá do rozsahu cíle (data mimo něj zachováme)
                        k_min, k_max, k_count = _time_range(cursor, table, target_id)
                        if k_count:
                            cursor.execute(
                                f"DELETE FROM {table} WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?",
                                (source_id, k_min, k_max)
                            )
                    elif action_plan == "overlap_keep_source":
                        k_min, k_max, k_count = _time_range(cursor, table, source_id)
                        if k_count:
                            cursor.execute(
                                f"DELETE FROM {table} WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?",
                                (target_id, k_min, k_max)
                            )

                    # Pojistka proti UNIQUE(metadata_id, start_ts): odstraníme případné kolize přesných časů
                    if action_plan == "overlap_keep_source":
                        loser, winner = target_id, source_id
                    else:
                        loser, winner = source_id, target_id
                    cursor.execute(
                        f"DELETE FROM {table} WHERE metadata_id = ? AND start_ts IN "
                        f"(SELECT start_ts FROM {table} WHERE metadata_id = ?)",
                        (loser, winner)
                    )

                # 4.2 Offset – aplikujeme ještě PŘED přepsáním ID, kdy jsou data obou entit od sebe odlišitelná
                if offset:
                    click.echo(f"  Přičítání offsetu {offset} k navazující historii (Standard)...")
                    for table in STAT_TABLES:
                        cursor.execute(f"UPDATE {table} SET sum = sum + ? WHERE metadata_id = ?", (offset, target_id))
                if inverse_offset:
                    click.echo(f"  Přičítání offsetu {inverse_offset} k připojené novější historii (Inverzní)...")
                    for table in STAT_TABLES:
                        cursor.execute(f"UPDATE {table} SET sum = sum + ? WHERE metadata_id = ?", (inverse_offset, source_id))

                # 4.3 Update ID (The Migration)
                click.echo("  Přepisování ID sirotka na aktivní entitu...")
                for table in STAT_TABLES:
                    cursor.execute(f"UPDATE {table} SET metadata_id = ? WHERE metadata_id = ?", (target_id, source_id))

                # 4.4 Cleanup
                click.echo("  Mažu stará metadata sirotka...")
                cursor.execute("DELETE FROM statistics_meta WHERE id = ?", (source_id,))

                conn.commit()
                click.echo("\n✅ HOTOVO! Migrace úspěšně dokončena.")

            except Exception as e:
                conn.rollback()
                click.echo(f"\n❌ CHYBA: {e}", err=True)
                click.echo("Všechny změny byly vráceny zpět (rollback).")

    except click.exceptions.Abort:
        raise
    except Exception as e:
        click.echo(f"Chyba: {e}", err=True)
