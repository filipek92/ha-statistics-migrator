#!/bin/bash
set -e
echo "Creating a backup of the Home Assistant database..."
ssh hass.lan cp /config/home-assistant_v2.db /config/home-assistant_v2.db.download
echo "Downloading the backup to the local machine..."
scp hass.lan:config/home-assistant_v2.db.download ./home-assistant_v2.db
echo "Cleaning up the backup file on the Home Assistant server..."
ssh hass.lan rm /config/home-assistant_v2.db.download
echo "Download complete. The database has been saved as home-assistant_v2.db in the current directory."