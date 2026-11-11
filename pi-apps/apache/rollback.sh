#!/bin/bash
# Undo enable.sh: Part-DB back at http://128.91.45.130/ as before.   sudo ~/apps/apache/rollback.sh
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo $0"; exit 1; }
BK=/home/hep/apps/apache/backup
a2dissite -q pi-apps 2>/dev/null
[ -f "$BK/partdb.conf" ] && cp -a "$BK/partdb.conf" /etc/apache2/sites-available/partdb.conf
a2ensite -q partdb
[ -f "$BK/env.local" ] && cp -a "$BK/env.local" /var/www/partdb/.env.local
sudo -u www-data php /var/www/partdb/bin/console cache:clear --no-interaction >/dev/null && echo "Part-DB cache cleared"
if [ -f "$BK/mods-enabled.before" ]; then
    for m in proxy_http proxy; do grep -q "^$m.load$" "$BK/mods-enabled.before" || a2dismod -q -f "$m"; done
fi
apache2ctl configtest && systemctl restart apache2
curl -s -o /dev/null -w "Part-DB at /: %{http_code}\n" http://128.91.45.130/
