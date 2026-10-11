import sqlite3
import os
import time
import click
from contextlib import contextmanager, closing

POTENTIAL_PATHS = [
    "home-assistant_v2.db",
    "config/home-assistant_v2.db",
    "/config/home-assistant_v2.db",
    "../config/home-assistant_v2.db"
]

class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = db_path or self._find_db()
        if not self.db_path:
            raise FileNotFoundError("Databáze nebyla nalezena. Zadejte cestu parametrem --db-path.")

    def _find_db(self):
        for path in POTENTIAL_PATHS:
            if os.path.exists(path):
                return path
        return None

    @contextmanager
    def get_connection(self):
        # timeout: počkáme na zámek (např. při commitu recorderu), než vyhodíme "database is locked"
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_backup(self, suffix=""):
        timestamp = int(time.time())
        name_part = f"_{suffix}" if suffix else ""
        backup_path = f"{self.db_path}.backup{name_part}_{timestamp}"
        click.echo(f"  📦 Zálohování databáze (SQLite backup API): {backup_path}")

        # Použijeme SQLite backup API pro konzistentní snapshot i za běhu (včetně dat ve WAL)
        try:
            with closing(sqlite3.connect(self.db_path, timeout=30)) as source_conn:
                with closing(sqlite3.connect(backup_path)) as dest_conn:

                    def progress_callback(status, remaining, total):
                        if total > 0:
                            # Výpočet procent (remaining jde od total k 0)
                            percent = ((total - remaining) / total) * 100
                            print(f"\r  ⏳ Průběh: {percent:.1f}% ({total - remaining}/{total} stránek)", end="", flush=True)

                    # pages=1000 kopíruje po menších částech, aby fungoval callback a neblokovalo to
                    source_conn.backup(dest_conn, pages=1000, progress=progress_callback)

            print() # Nová řádka po dokončení
        except Exception as e:
            click.echo(f"\n  ⚠️ Chyba při SQLite záloze: {e}. Zkouším fallback přes VACUUM INTO...")
            # Prosté kopírování souboru by ignorovalo -wal soubor a záloha by mohla být nekonzistentní.
            # VACUUM INTO vytvoří konzistentní snapshot stejně jako backup API.
            self._remove_quietly(backup_path)
            try:
                with closing(sqlite3.connect(self.db_path, timeout=30)) as source_conn:
                    source_conn.execute("VACUUM INTO ?", (backup_path,))
            except Exception as e_vacuum:
                self._remove_quietly(backup_path)
                click.echo(f"  ❌ Fallback selhal: {e_vacuum}")
                raise e_vacuum

        return backup_path

    @staticmethod
    def _remove_quietly(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def get_metadata(self, conn, entity_id):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
        return cursor.fetchone()

    def get_all_metadata(self, conn, search=None):
        cursor = conn.cursor()
        query = "SELECT * FROM statistics_meta"
        params = []
        if search:
            query += " WHERE statistic_id LIKE ?"
            params.append(f"%{search}%")
        cursor.execute(query, params)
        return cursor.fetchall()
