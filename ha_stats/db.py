import sqlite3
import os
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
