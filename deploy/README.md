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

Database: `sudo -u postgres pg_dump -Fc clinic365 > clinic365-$(date +%F).dump` (schedule it and copy
off the server). Also back up `/opt/clinic365/media` (uploads, lab results) and the env file.

## Uploaded files

`/media/...` (lab results, scans, patient and staff photos) is only served to signed-in staff:
Django checks the session, then nginx sends the file from the `internal` `/protected-media/`
location (X-Accel-Redirect). Someone who copies a file link and opens it while signed out gets
"Sign in to view this file". Keep `alias` in that nginx location equal to `DJANGO_MEDIA_ROOT`.

## Known gaps (not yet handled)

- The Django admin at `/admin/` is reachable from the LAN; restrict it in nginx (see the comment
  there) to the IT office.
