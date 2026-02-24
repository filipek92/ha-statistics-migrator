#!/bin/bash

# Zkontroluje argumenty
if [ -z "$1" ]; then
    echo "❌ Chyba: Musíte zadat cílový host (např. 'hass.lan' nebo 'root@xxx')."
    echo "Použití: ./deploy.sh [TARGET_HOST]"
    exit 1
fi

TARGET="$1"
REMOTE_DIR="/root/ha_stats_tool"
PACKAGE_NAME="ha_stats_deploy.tar.gz"
TEMP_DIR="deploy_temp"
CACHE_DIR="libs_cache"

echo "📦 Balím nástroj..."

# 1. Příprava dočasného adresáře
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR/ha_stats"

# 2. Kopírování zdrojových souborů
cp -r ha_stats/* "$TEMP_DIR/ha_stats/"
cp requirements.txt "$TEMP_DIR/"

# 3. Stažení závislostí pro snadné použití (vendorizace) s využitím cache
#    Protože na HA OS může být problém s pip install, přibalíme 'click' rovnou.
if [ -d "$CACHE_DIR" ]; then
    echo "   Používám cachované závislosti z $CACHE_DIR..."
else 
    echo "   Stahuji a cachuji závislosti (click) do $CACHE_DIR..."
    pip install -r requirements.txt --target "$CACHE_DIR" --quiet
fi

# Kopírování z cache do cílového balíčku
cp -r "$CACHE_DIR" "$TEMP_DIR/libs"

# 4. Vytvoření spouštěcího skriptu (wrapper)
cat <<EOF > "$TEMP_DIR/ha-stats"
#!/usr/bin/env python3
import sys
import os

# Přidání libs do cesty, aby Python našel přibalený 'click'
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(script_dir, "libs"))

# Spuštění CLI
from ha_stats.cli import cli

if __name__ == "__main__":
    cli()
EOF

chmod +x "$TEMP_DIR/ha-stats"

# 5. Zabalení do tar.gz
tar -czf "$PACKAGE_NAME" -C "$TEMP_DIR" .
rm -rf "$TEMP_DIR"

echo "🚀 Odesílám na $TARGET..."
scp "$PACKAGE_NAME" "$TARGET:$REMOTE_DIR.tar.gz"

if [ $? -eq 0 ]; then
    echo "✅ Úspěšně odesláno."
    echo "⚙️  Rozbaluji a instaluji na vzdáleném stroji..."
    
    ssh "$TARGET" "mkdir -p $REMOTE_DIR && tar -xzf $REMOTE_DIR.tar.gz -C $REMOTE_DIR && chmod +x $REMOTE_DIR/ha-stats && rm $REMOTE_DIR.tar.gz"
    
    echo "✨ HOTOVO! Nyní se můžeš připojit:"
    echo "   ssh $TARGET"
    echo "   cd $REMOTE_DIR"
    echo "   ./ha-stats --help"
else
    echo "❌ Chyba při odesílání."
    exit 1
fi

# Úklid lokálního archivu
rm "$PACKAGE_NAME"
