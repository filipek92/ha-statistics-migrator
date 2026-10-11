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

## Instalace na HA

```bash
./deploy.sh root@hass.lan        # zabalí nástroj i s knihovnou click a nahraje do /root/ha_stats_tool
ssh root@hass.lan
cd /root/ha_stats_tool && ./ha-stats --help
```

Lokálně (na kopii DB staženou přes `./download.sh [host]`):

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
