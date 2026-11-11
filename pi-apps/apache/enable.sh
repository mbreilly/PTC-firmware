#!/bin/bash
# Put every app behind Apache on port 80:  sudo ~/apps/apache/enable.sh      (undo: sudo ~/apps/apache/rollback.sh)
#   http://128.91.45.130/  landing page, /parts-db/ Part-DB, /labels/ /ptc-qc/ /aoi/ /scan-station/ the apps.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo $0"; exit 1; }
HERE=/home/hep/apps/apache
BK=$HERE/backup
ENV=/var/www/partdb/.env.local
URI='http://128.91.45.130/parts-db/'

echo "== backing up the files this changes to $BK"
mkdir -p "$BK"
[ -f "$BK/partdb.conf" ] || cp -a /etc/apache2/sites-available/partdb.conf "$BK/partdb.conf"
[ -f "$BK/env.local" ]   || cp -a "$ENV" "$BK/env.local"
ls /etc/apache2/sites-enabled > "$BK/sites-enabled.before"
ls /etc/apache2/mods-enabled  > "$BK/mods-enabled.before"

echo "== Apache proxy modules"
a2enmod -q proxy proxy_http

echo "== landing page and site"
install -d -m 755 /var/www/pi-apps
install -m 644 "$HERE/landing/index.html" /var/www/pi-apps/index.html
install -m 644 "$HERE/pi-apps.conf" /etc/apache2/sites-available/pi-apps.conf
a2dissite -q partdb || true
a2ensite -q pi-apps

echo "== Part-DB now lives at $URI"
sed -i "s#^DEFAULT_URI=.*#DEFAULT_URI=\"$URI\"#" "$ENV"
grep '^DEFAULT_URI=' "$ENV"
sudo -u www-data php /var/www/partdb/bin/console cache:clear --no-interaction >/dev/null && echo "Part-DB cache cleared"

echo "== checking the config"
if ! apache2ctl configtest; then
    echo "Config test FAILED, undoing."; "$HERE/rollback.sh"; exit 1
fi
systemctl restart apache2
sleep 1
for p in / /parts-db/ /labels/ /ptc-qc/ /aoi/ /scan-station/ /en/; do
    printf '%-15s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "http://128.91.45.130$p")"
done
echo "Done. Open http://128.91.45.130/"
