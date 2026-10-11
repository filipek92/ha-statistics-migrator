import sqlite3
import pytest
from click.testing import CliRunner

from ha_stats import utils
from ha_stats.cli import cli

# Zjednodušené schéma HA recorderu (jen sloupce, se kterými nástroj pracuje)
SCHEMA = """
CREATE TABLE statistics_meta (
    id INTEGER PRIMARY KEY,
    statistic_id VARCHAR(255),
    source VARCHAR(32),
    unit_of_measurement VARCHAR(255),
    has_mean BOOLEAN,
    has_sum BOOLEAN,
    name VARCHAR(255)
);
CREATE TABLE statistics (
    id INTEGER PRIMARY KEY,
    created_ts FLOAT,
    metadata_id INTEGER,
    start_ts FLOAT,
    mean FLOAT, min FLOAT, max FLOAT,
    last_reset_ts FLOAT,
    state FLOAT,
    sum FLOAT
);
CREATE UNIQUE INDEX ix_statistics_statistic_id_start_ts ON statistics (metadata_id, start_ts);
CREATE TABLE statistics_short_term (
    id INTEGER PRIMARY KEY,
    created_ts FLOAT,
    metadata_id INTEGER,
    start_ts FLOAT,
    mean FLOAT, min FLOAT, max FLOAT,
    last_reset_ts FLOAT,
    state FLOAT,
    sum FLOAT
);
CREATE UNIQUE INDEX ix_statistics_short_term_statistic_id_start_ts ON statistics_short_term (metadata_id, start_ts);
CREATE TABLE states_meta (
    metadata_id INTEGER PRIMARY KEY,
    entity_id VARCHAR(255)
);
CREATE TABLE states (
    state_id INTEGER PRIMARY KEY,
    state VARCHAR(255),
    last_updated_ts FLOAT,
    old_state_id INTEGER,
    metadata_id INTEGER
);
"""

HOUR = 3600
T0 = 1_700_000_000 - (1_700_000_000 % HOUR)


class FakeDb:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def add_meta(self, statistic_id, unit="kWh", has_sum=True, has_mean=False, active=True):
        cur = self.conn.execute(
            "INSERT INTO statistics_meta (statistic_id, source, unit_of_measurement, has_mean, has_sum) VALUES (?, 'recorder', ?, ?, ?)",
            (statistic_id, unit, has_mean, has_sum)
        )
        if active:
            self.conn.execute("INSERT INTO states_meta (entity_id) VALUES (?)", (statistic_id,))
        self.conn.commit()
        return cur.lastrowid

    def add_stats(self, metadata_id, hours_and_sums, table="statistics", period=HOUR, **cols):
        """hours_and_sums: [(index_periody, sum), ...]; další sloupce (mean/min/max) přes cols jako seznamy."""
        for i, (h, s) in enumerate(hours_and_sums):
            extra = {k: v[i] for k, v in cols.items()}
            self.conn.execute(
                f"INSERT INTO {table} (metadata_id, start_ts, sum, mean, min, max) VALUES (?, ?, ?, ?, ?, ?)",
                (metadata_id, T0 + h * period, s, extra.get('mean'), extra.get('min'), extra.get('max'))
            )
        self.conn.commit()

    def sums(self, metadata_id, table="statistics"):
        rows = self.conn.execute(
            f"SELECT sum FROM {table} WHERE metadata_id = ? ORDER BY start_ts", (metadata_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    # Testovací DB je čerstvě změněná – vypneme detekci běžícího HA
    monkeypatch.setattr(utils, "HA_RUNNING_THRESHOLD_SEC", 0)
    db = FakeDb(tmp_path / "home-assistant_v2.db")
    yield db
    db.conn.close()


@pytest.fixture
def run(fake_db):
    runner = CliRunner()

    def _run(args, input=None):
        return runner.invoke(cli, ["--db-path", fake_db.path] + args, input=input, catch_exceptions=False)

    return _run
