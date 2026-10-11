from click.testing import CliRunner
import pytest

from ha_stats.cli import cli
from ha_stats.utils import find_orphans
from ha_stats.commands.fix_drops import compute_drop_fixes


def test_missing_db_reports_error_instead_of_traceback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 1
    assert "Databáze nebyla nalezena" in result.output
    assert "KeyError" not in result.output


def test_subcommand_help_works_without_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["list", "--help"])
    assert result.exit_code == 0


# --- find_orphans -----------------------------------------------------------

def test_find_orphans_skips_external_and_tolerates_null_entity(fake_db):
    fake_db.add_meta("sensor.active")
    fake_db.add_meta("sensor.orphan", active=False)
    fake_db.add_meta("tibber:energy", active=False)
    fake_db.conn.execute("INSERT INTO states_meta (entity_id) VALUES (NULL)")
    fake_db.conn.commit()

    names = [r['statistic_id'] for r in find_orphans(fake_db.conn.cursor())]
    assert names == ["sensor.orphan"]


# --- fix-drops --------------------------------------------------------------

def _rows(sums):
    return [(i, i * 3600, s) for i, s in enumerate(sums)]


def test_drop_fixes_flatten_transient_dip():
    updates, drops = compute_drop_fixes(_rows([10, 20, 0, 0, 21, 22]))
    assert updates == {2: 20, 3: 20}
    assert [d['action'] for d in drops] == ["flatten", "flatten"]


def test_drop_fixes_shift_permanent_reset():
    updates, drops = compute_drop_fixes(_rows([10, 20, 1, 2, 3]))
    # Po resetu pokračuje spotřeba (+1/h) od úrovně 20, nic se neztratí
    assert updates == {2: 20, 3: 21, 4: 22}
    assert [d['action'] for d in drops] == ["shift"]


def test_drop_fixes_negative_sums_are_not_drops():
    updates, drops = compute_drop_fixes(_rows([-50, -40, -30, None, -20]))
    assert updates == {} and drops == []


def test_fix_drops_command_fixes_long_and_short_term(fake_db, run):
    mid = fake_db.add_meta("sensor.energy")
    fake_db.add_stats(mid, [(0, 10), (1, 20), (2, 1), (3, 2)])
    fake_db.add_stats(mid, [(0, 10), (1, 20), (2, 1), (3, 2)], table="statistics_short_term", period=300)

    result = run(["fix-drops", "sensor.energy"], input="y\nn\n")
    assert "Opraveno 2 dlouhodobých a 2 krátkodobých" in result.output
    assert fake_db.sums(mid) == [10, 20, 20, 21]
    assert fake_db.sums(mid, "statistics_short_term") == [10, 20, 20, 21]


# --- outliers ---------------------------------------------------------------

def test_outliers_tolerates_null_sum_and_fixes_jump(fake_db, run):
    mid = fake_db.add_meta("sensor.energy")
    fake_db.add_stats(mid, [(0, 1), (1, 2), (2, None), (3, 1003), (4, 1004)])

    result = run(["outliers", "sensor.energy", "--threshold", "100"], input="y\nn\n")
    assert "Chyba" not in result.output
    assert "Opraveno 1 skoků" in result.output
    assert fake_db.sums(mid) == [1, 2, None, 2, 3]


# --- migrate ----------------------------------------------------------------

def test_migrate_standard_applies_offset(fake_db, run):
    old = fake_db.add_meta("sensor.old_energy", active=False)
    new = fake_db.add_meta("sensor.new_energy")
    fake_db.add_stats(old, [(0, 1), (1, 2), (2, 3)])
    fake_db.add_stats(new, [(5, 1), (6, 2)])

    # sirotek [0], cíl [0], potvrzení, bez zálohy
    result = run(["migrate"], input="0\n0\ny\nn\n")
    assert "Migrace úspěšně dokončena" in result.output
    assert fake_db.sums(new) == [1, 2, 3, 4, 5]
    assert fake_db.query("SELECT COUNT(*) FROM statistics_meta WHERE id = ?", (old,))[0][0] == 0


def test_migrate_inverse_with_mean_sensor(fake_db, run):
    # Teplotní senzor: has_sum=0, sum je NULL – dřív padalo na `None > 0`
    tgt = fake_db.add_meta("sensor.room_temperature", unit="°C", has_sum=False, has_mean=True)
    src = fake_db.add_meta("sensor.room_2_temperature", unit="°C", has_sum=False, has_mean=True, active=False)
    fake_db.add_stats(tgt, [(0, None), (1, None)], mean=[20, 21])
    fake_db.add_stats(src, [(5, None), (6, None)], mean=[22, 23])

    result = run(["migrate"], input="0\n0\ny\nn\n")
    assert "Migrace úspěšně dokončena" in result.output
    means = [r[0] for r in fake_db.query("SELECT mean FROM statistics WHERE metadata_id = ? ORDER BY start_ts", (tgt,))]
    assert means == [20, 21, 22, 23]


def test_migrate_inverse_applies_target_offset(fake_db, run):
    tgt = fake_db.add_meta("sensor.house_energy")
    src = fake_db.add_meta("sensor.house_2_energy", active=False)
    fake_db.add_stats(tgt, [(0, 5), (1, 10)])
    fake_db.add_stats(src, [(5, 1), (6, 2)])

    result = run(["migrate"], input="0\n0\ny\nn\n")
    assert "Migrace úspěšně dokončena" in result.output
    assert fake_db.sums(tgt) == [5, 10, 11, 12]


def test_migrate_overlap_keep_target_preserves_source_outside_target_range(fake_db, run):
    tgt = fake_db.add_meta("sensor.new_power", unit="W", has_sum=False, has_mean=True)
    src = fake_db.add_meta("sensor.old_power", unit="W", has_sum=False, has_mean=True, active=False)
    # Sirotek: 0..9, cíl: 3..5 -> zachovat cíl, ze sirotka smazat jen 3..5
    fake_db.add_stats(src, [(h, None) for h in range(10)], mean=[100] * 10)
    fake_db.add_stats(tgt, [(h, None) for h in range(3, 6)], mean=[200] * 3)

    result = run(["migrate"], input="0\n0\nC\ny\nn\n")
    assert "Migrace úspěšně dokončena" in result.output
    means = [r[0] for r in fake_db.query("SELECT mean FROM statistics WHERE metadata_id = ? ORDER BY start_ts", (tgt,))]
    assert means == [100, 100, 100, 200, 200, 200, 100, 100, 100, 100]


# --- clean ------------------------------------------------------------------

def _add_states(fake_db, entity_id, values):
    mid = fake_db.conn.execute("INSERT INTO states_meta (entity_id) VALUES (?)", (entity_id,)).lastrowid
    prev = None
    for i, v in enumerate(values):
        prev = fake_db.conn.execute(
            "INSERT INTO states (state, last_updated_ts, old_state_id, metadata_id) VALUES (?, ?, ?, ?)",
            (v, 1_700_000_000 + i, prev, mid)
        ).lastrowid
    fake_db.conn.commit()
    return mid


def test_clean_states_ignores_text_and_nulls_old_state_id(fake_db, run):
    mid = _add_states(fake_db, "sensor.power", ["10", "unavailable", "99999", "12", "on"])

    result = run(["clean", "sensor.power", "--states", "--min", "5", "--max", "1000"], input="y\nn\n")
    assert "Nalezeno 1 záznamů" in result.output
    states = [r['state'] for r in fake_db.query("SELECT state FROM states WHERE metadata_id = ? ORDER BY state_id", (mid,))]
    assert states == ["10", "unavailable", "12", "on"]
    # Žádný stav neodkazuje na smazaný řádek
    dangling = fake_db.query(
        "SELECT COUNT(*) FROM states s WHERE old_state_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM states p WHERE p.state_id = s.old_state_id)"
    )[0][0]
    assert dangling == 0


def test_clean_statistics_clamp(fake_db, run):
    mid = fake_db.add_meta("sensor.temp", unit="°C", has_sum=False, has_mean=True)
    fake_db.add_stats(mid, [(0, None), (1, None)], mean=[20, 500], min=[19, 18], max=[21, 900])

    result = run(["clean", "sensor.temp", "--max", "50", "--fix-mode", "clamp"], input="y\nn\n")
    assert "Hotovo" in result.output
    rows = fake_db.query("SELECT mean, min, max FROM statistics WHERE metadata_id = ? ORDER BY start_ts", (mid,))
    assert [tuple(r) for r in rows] == [(20, 19, 21), (50, 18, 50)]


# --- backup -----------------------------------------------------------------

def test_backup_creates_consistent_copy(fake_db, run, tmp_path):
    mid = fake_db.add_meta("sensor.energy")
    fake_db.add_stats(mid, [(0, 1), (1, 2)])

    result = run(["backup", "--suffix", "test"])
    assert "Záloha úspěšně dokončena" in result.output
    backups = list(tmp_path.glob("home-assistant_v2.db.backup_test_*"))
    assert len(backups) == 1

    import sqlite3
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM statistics").fetchone()[0] == 2
