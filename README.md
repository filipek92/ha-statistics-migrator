# ha-stats

CLI nástroj pro správu, analýzu a opravu dlouhodobých statistik v databázi Home Assistant (`home-assistant_v2.db`, SQLite).

> ⚠️ **Před každou zapisující operací zastavte Home Assistant** (`ha core stop`) a mějte zálohu.
> Nástroj sám varuje, pokud byla databáze nedávno změněna (HA zřejmě běží), a před každou změnou nabízí zálohu.

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
