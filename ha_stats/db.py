import sqlite3
import os
import shutil
import time
import click
from contextlib import contextmanager

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
        conn = sqlite3.connect(self.db_path)
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
        
        # Použijeme SQLite backup API pro konzistentní snapshot i za běhu
        try:
            with sqlite3.connect(self.db_path) as source_conn:
                with sqlite3.connect(backup_path) as dest_conn:
                    
                    def progress_callback(status, remaining, total):
                        if total > 0:
                            # Výpočet procent (remaining jde od total k 0)
                            percent = ((total - remaining) / total) * 100
                            # Vypíšeme jen celé %, aby to nezahlcovalo konzoli (nebo interaktivně)
                            print(f"\r  ⏳ Průběh: {percent:.1f}% ({total - remaining}/{total} stránek)", end="", flush=True)

                    # pages=1000 kopíruje po menších částech, aby fungoval callback a neblokovalo to
                    source_conn.backup(dest_conn, pages=1000, progress=progress_callback)
            
            print() # Nová řádka po dokončení
        except Exception as e:
            click.echo(f"\n  ⚠️ Chyba při SQLite záloze: {e}. Zkouším fallback na kopírování souboru...")
            # Použijeme shutil pro kopírování souboru
            # Pokud je DB zamčená (velmi vzácné při kopírování souboru na Linuxu bez write locku), může to selhat
            try:
                shutil.copy2(self.db_path, backup_path)
            except Exception as e_copy:
                click.echo(f"  ❌ Fallback selhal: {e_copy}")
                raise e_copy
            
        return backup_path

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
