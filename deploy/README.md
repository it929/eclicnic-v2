# Deploying Clinic365 EMR (on-prem Linux)

Layout assumed below (change paths consistently if yours differ):

| What | Where |
|---|---|
| Django project (this `clinic365/` folder) | `/opt/clinic365/clinic365` |
| Python virtualenv | `/opt/clinic365/venv` |
| Built React app (`frontend/dist`) | `/opt/clinic365/frontend` |
| Static / uploaded files | `/opt/clinic365/staticfiles`, `/opt/clinic365/media` |
| Secrets and settings | `/etc/clinic365/clinic365.env` |
| Logs | `/var/log/clinic365/` and `journalctl -u clinic365` |

Settings: `clinic365.settings_production` inherits everything from `settings.py` and only overrides
production values, all read from the env file. It refuses to start without a real secret key,
database password and host names, so a misconfigured server fails loudly instead of running insecurely.

## First install

```bash
# 0. Server clock on Lagos time (cron jobs and logs use it; Django uses TIME_ZONE itself)
sudo timedatectl set-timezone Africa/Lagos

# 1. System packages and the service user
sudo apt install python3-venv python3-dev postgresql nginx
sudo useradd --system --home /opt/clinic365 --shell /usr/sbin/nologin clinic365
sudo mkdir -p /opt/clinic365/{staticfiles,media,frontend} /var/log/clinic365 /etc/clinic365
sudo chown -R clinic365:clinic365 /opt/clinic365 /var/log/clinic365

# 2. Database
sudo -u postgres createuser --pwprompt clinic365
sudo -u postgres createdb --owner clinic365 clinic365

# 3. Code + Python packages (copy the clinic365/ folder to /opt/clinic365/clinic365 first)
sudo -u clinic365 python3 -m venv /opt/clinic365/venv
sudo -u clinic365 /opt/clinic365/venv/bin/pip install -r /opt/clinic365/clinic365/requirements.txt

# 4. Environment file: fill in every value (secret key, DB password, host names, email)
sudo cp deploy/clinic365.env.example /etc/clinic365/clinic365.env
sudo nano /etc/clinic365/clinic365.env
sudo chown root:clinic365 /etc/clinic365/clinic365.env && sudo chmod 640 /etc/clinic365/clinic365.env

# 5. Helper for management commands (loads the env file)
sudo install -m 755 deploy/bin/clinic365-manage /usr/local/bin/clinic365-manage
sudo -u clinic365 clinic365-manage check --deploy     # only HTTPS warnings expected on plain HTTP
sudo -u clinic365 clinic365-manage migrate
sudo -u clinic365 clinic365-manage collectstatic --noinput
sudo -u clinic365 clinic365-manage createsuperuser     # first admin account

# 6. Frontend (on any machine with Node): build and copy dist/ to the server
cd frontend && npm ci && npm run build
#   then copy frontend/dist/* to /opt/clinic365/frontend/

# 7. Services
sudo cp deploy/systemd/clinic365.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now clinic365
sudo cp deploy/nginx/clinic365.conf /etc/nginx/sites-available/clinic365   # edit server_name
sudo ln -s /etc/nginx/sites-available/clinic365 /etc/nginx/sites-enabled/clinic365
sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx

# 8. Scheduled jobs (notification clean-up 02:30, day book email 23:05)
sudo cp deploy/cron/clinic365-notifications /etc/cron.d/ && sudo chmod 644 /etc/cron.d/clinic365-notifications
```

Check: open `http://<server>/` (login page), `http://<server>/health` (200).

## Updating to a new release

```bash
# copy the new clinic365/ code over /opt/clinic365/clinic365 (keep media/ and the env file)
sudo -u clinic365 /opt/clinic365/venv/bin/pip install -r /opt/clinic365/clinic365/requirements.txt
sudo -u clinic365 clinic365-manage migrate
sudo -u clinic365 clinic365-manage collectstatic --noinput
sudo systemctl restart clinic365
# copy the new frontend/dist/* to /opt/clinic365/frontend/ (users get it on their next page load)
```

## HTTPS

When nginx has a certificate (`listen 443 ssl` + a port-80 redirect), set `DJANGO_HTTPS=1` in the env
file and restart. Do **not** set it on plain HTTP: secure cookies are not sent over HTTP and nobody
could sign in.

## Backups

What is backed up every night (01:30), by `deploy/bin/clinic365-backup`:

- the **database** (`pg_dump`, compressed; checked readable and given a SHA-256 checksum);
- **uploaded files** in `DJANGO_MEDIA_ROOT` (lab results, scans, photos): daily rsync snapshots,
  unchanged files are hard links so they take no extra space;
- the **env file, nginx and systemd config** (kept readable by the clinic365 user only).

Kept: the last 14 nightly copies, plus the first copy of each of the last 8 weeks and 12 months
(about 32 database copies), and 7 media snapshots. Change with `BACKUP_KEEP_*` in the env file.

Every Sunday (04:00) `clinic365-restore-test` restores the newest copy into a throwaway database,
checks patients, encounters, prescriptions, lab results, admissions, bills, receipts and users
against the live database, and drops the throwaway database. Every morning (07:30)
`manage.py check_backups` tells Admin and CMD (notification bell, and email to `BACKUP_ALERT_EMAIL`)
if a backup failed, is late, has no off-site copy, or the drill failed. Administrators also see a
banner on the dashboard.

### Install (once, as root)

Files in `deploy/` must keep Unix line endings. If they were edited or copied from Windows, fix them
first, or the scripts fail with `bash\r: No such file` and cron skips the jobs:
`sudo apt install -y dos2unix && dos2unix deploy/bin/* deploy/cron/*`. (Do this for the scripts
already installed too: `clinic365-manage` and `/etc/cron.d/clinic365-notifications`.)

```bash
sudo install -m 755 deploy/bin/clinic365-backup       /usr/local/bin/clinic365-backup
sudo install -m 755 deploy/bin/clinic365-restore-test /usr/local/bin/clinic365-restore-test
sudo mkdir -p /var/backups/clinic365 /var/log/clinic365
sudo chown clinic365: /var/backups/clinic365 /var/log/clinic365 && sudo chmod 700 /var/backups/clinic365
sudo apt install -y rsync postgresql-client          # pg_dump must match (or be newer than) the server version
sudo -u postgres psql -c "ALTER ROLE clinic365 CREATEDB;"   # lets the restore drill create its throwaway DB
# set BACKUP_REMOTE and/or BACKUP_RCLONE in /etc/clinic365/clinic365.env (see clinic365.env.example)
sudo -u clinic365 clinic365-backup --dry-run && sudo -u clinic365 clinic365-backup
sudo -u clinic365 clinic365-restore-test
sudo -u clinic365 clinic365-manage check_backups
sudo cp deploy/cron/clinic365-backup /etc/cron.d/clinic365-backup && sudo chmod 644 /etc/cron.d/clinic365-backup
```

**Off-site copy is required.** Backups on the same server do not survive a disk failure, theft,
fire or ransomware. Until `BACKUP_REMOTE` or `BACKUP_RCLONE` is set, every check reports
"Backups are kept only on this server". For a remote machine, give the clinic365 user an ssh key
(`sudo -u clinic365 ssh-keygen`, copy it to the backup machine) and test
`sudo -u clinic365 ssh backup@HOST true` once.

### Restoring after a disaster

1. Install the server as above (code, venv, env file from the backup's `config/` folder).
2. Database (into an empty database owned by clinic365):
   ```bash
   cd /var/backups/clinic365/db && sha256sum --check clinic365_YYYY-MM-DD_HHMMSS.dump.sha256
   sudo -u postgres createdb -O clinic365 clinic365
   pg_restore --no-owner --no-privileges -h 127.0.0.1 -U clinic365 -d clinic365 clinic365_YYYY-MM-DD_HHMMSS.dump
   ```
3. Uploaded files: `sudo rsync -a /var/backups/clinic365/media/YYYY-MM-DD_HHMMSS/ /opt/clinic365/media/`
   (or `tar -xzf media_....tar.gz -C /opt/clinic365/media`), then `sudo chown -R clinic365: /opt/clinic365/media`.
4. `clinic365-manage migrate`, `sudo systemctl restart clinic365`, sign in and open a few patients,
   lab results and bills to check.

Practise this once on a spare machine; the weekly drill proves the database part automatically.

## Uploaded files

`/media/...` (lab results, scans, patient and staff photos) is only served to signed-in staff:
Django checks the session, then nginx sends the file from the `internal` `/protected-media/`
location (X-Accel-Redirect). Someone who copies a file link and opens it while signed out gets
"Sign in to view this file". Keep `alias` in that nginx location equal to `DJANGO_MEDIA_ROOT`.

## Known gaps (not yet handled)

- Old Django pages outside `/api/` are read-only for signed-in staff (`DJANGO_LEGACY_PAGES=readonly`); set it to `off` once
  nobody uses them (the React app does not).
- The Django admin at `/admin/` is reachable from the LAN; restrict it in nginx (see the comment
  there) to the IT office.
