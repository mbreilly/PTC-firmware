# Pi apps

Apps that run on the PartsDB bench Pi (`~/apps/<name>` on the Pi). The Pi's own
copies are plain git repos with **no remote**; these folders were added from them with
`git subtree`, so their history is kept here.

| Folder | What it is |
|---|---|
| `ql_labels/` | Label designer and printer for the Brother QL-810W (served at `/labels/`, port 8097). |
| `partdb_station/` | Part-DB scan station: scan a part label, look it up and save it in Part-DB (`/scan-station/`, port 8095). Its Part-DB API token lives on the Pi in `~/.config/partdb-station/config.json` and is not in git. |
| `apache/` | Apache reverse-proxy config for the Pi's port 80: the landing page and the paths for Part-DB and each app (`pi-apps.conf`, `landing/index.html`, `enable.sh`, `rollback.sh`). |

To update a folder from the Pi later:

    git subtree pull --prefix=pi-apps/<name> hep@128.91.45.130:apps/<name> master
