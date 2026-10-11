#!/bin/bash
set -e

HOST="${1:-hass.lan}"
REMOTE_DB="/config/home-assistant_v2.db"
REMOTE_COPY="/config/home-assistant_v2.db.download"

echo "Creating a consistent snapshot of the Home Assistant database on $HOST..."
# Prosté 'cp' by ignorovalo data v -wal souboru (kopie může být nekonzistentní).
# SQLite backup API vytvoří konzistentní snapshot i za běhu HA.
ssh "$HOST" "python3 -c \"
import sqlite3
src = sqlite3.connect('$REMOTE_DB', timeout=30)
dst = sqlite3.connect('$REMOTE_COPY')
src.backup(dst)
dst.close()
src.close()
\""

echo "Downloading the snapshot to the local machine..."
scp "$HOST:$REMOTE_COPY" ./home-assistant_v2.db

echo "Cleaning up the snapshot file on the Home Assistant server..."
ssh "$HOST" rm "$REMOTE_COPY"
echo "Download complete. The database has been saved as home-assistant_v2.db in the current directory."
