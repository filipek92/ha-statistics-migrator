# ha-stats

CLI nástroj pro správu, analýzu a opravu dlouhodobých statistik v databázi Home Assistant (`home-assistant_v2.db`, SQLite).

> [!CAUTION]
> **POUŽITÍ NA VLASTNÍ ODPOVĚDNOST.**
>
> Tento nástroj **přímo upravuje a maže data** v databázi Home Assistant mimo jakoukoli oficiální podporu HA.
> Nejde o oficiální nástroj Home Assistant a není nijak testován proti všem verzím schématu databáze.
> Chybné použití, chyba v nástroji nebo změna schématu v nové verzi HA může vést k **nevratné ztrátě
> nebo poškození historie, statistik i celé databáze**.
>
> - **Vždy si před použitím vytvořte zálohu** celé databáze (příkaz `backup` nebo záloha HA) a ověřte, že jde obnovit.
> - **Před každou zapisující operací zastavte Home Assistant** (`ha core stop`). Nástroj varuje, pokud byla databáze
>   nedávno změněna (HA zřejmě běží), ale nemusí to poznat vždy.
> - Pokud je to možné, pracujte nejprve na **kopii databáze** (`./download.sh`) a výsledek si zkontrolujte.
>
> Software je poskytován „tak, jak je“, bez jakékoli záruky (viz [LICENSE](LICENSE)). Autor nenese
> **žádnou odpovědnost** za ztrátu dat ani jiné škody vzniklé jeho použitím.

## Instalace na HA (doporučeno): Advanced SSH & Web Terminal + git clone

1. Nainstalujte doplněk **Advanced SSH & Web Terminal** (Nastavení → Doplňky → Obchod s doplňky).
2. V záložce **Konfigurace** doplňku přidejte balíčky, aby se instalovaly při každém startu doplňku:

   ```yaml
   packages:
     - git
     - python3
     - py3-click
   ```

   Doplněk uložte a restartujte.
3. Otevřete terminál (webový nebo přes SSH) a naklonujte repozitář do `/share`, kde přežije restart doplňku:

   ```bash
   cd /share
   git clone https://github.com/filipek92/ha-statistics-migrator.git
   cd ha-statistics-migrator
   ```

4. Ověřte, že nástroj funguje. Databázi `/config/home-assistant_v2.db` najde sám:

   ```bash
   python3 -m ha_stats.cli --help
   python3 -m ha_stats.cli list
   ```

5. Před jakoukoli změnou udělejte zálohu a zastavte Home Assistant. Po dokončení ho znovu spusťte:

   ```bash
   python3 -m ha_stats.cli backup
   ha core stop
   python3 -m ha_stats.cli migrate      # případně jiný zapisující příkaz
   ha core start
   ```

Aktualizace na novou verzi: `cd /share/ha-statistics-migrator && git pull`.

> [!NOTE]
> Zálohy (`home-assistant_v2.db.backup_*`) vznikají vedle databáze v `/config` a mají velikost celé DB.
> Staré zálohy průběžně mažte, jinak zabírají místo a zvětšují i zálohy Home Assistantu.

## Alternativa: nasazení z počítače (`deploy.sh`)

```bash
./deploy.sh root@hass.lan        # zabalí nástroj i s knihovnou click a nahraje do /root/ha_stats_tool
ssh root@hass.lan
cd /root/ha_stats_tool && ./ha-stats --help
```

## Lokální použití

Na kopii DB stažené přes `./download.sh [host]`:

```bash
pip install -r requirements.txt
python3 -m ha_stats.cli --db-path home-assistant_v2.db list
```

## Příkazy

| Příkaz | Zápis do DB | Popis |
|---|---|---|
| `list [hledání]` | – | Přehled statistik se stavem (aktivní / staré / sirotci / externí / prázdné) |
| `analyze ENTITY` | – | Detail metadat, počtů záznamů a posledního stavu |
| `diagnose [ENTITY]` | volitelně | Spojité bloky a díry v datech, možnost smazat blok |
| `export ENTITY...` | – | Export do CSV (`--output soubor.csv`, jinak stdout) |
| `backup` | – | Konzistentní záloha DB (SQLite backup API) |
| `migrate` | ✔ | Převod historie sirotka na novou entitu, navázání `sum` |
| `outliers ENTITY` | ✔ | Oprava extrémních skoků v `sum` |
| `fix-drops ENTITY` | ✔ | Oprava poklesů v `sum` (výpadky zarovná, resety posune) |
| `clean ENTITY` | ✔ | Ořez / smazání hodnot mimo rozsah (min/max/mean nebo `--states`) |
| `fix ENTITY` | ✔ | Nastavení `has_mean` / `has_sum` v metadatech |
| `purge [ENTITY]` | ✔ | Smazání statistiky (s historií jen s `--force`) |

## Testy

```bash
pip install pytest
python3 -m pytest tests
```

## Licence

[MIT](LICENSE) © 2026 Filip Richter
