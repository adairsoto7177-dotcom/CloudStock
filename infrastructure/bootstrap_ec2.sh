#!/bin/bash
set -euo pipefail
trap 'rm -f "$HOME/.cloudstock-deploy/cloudstock.tar.gz"' EXIT
sudo apt-get update -q
sudo apt-get install -y python3-venv
sudo mkdir -p /opt/cloudstock
sudo chown ubuntu:ubuntu /opt/cloudstock
chmod 700 /opt/cloudstock
umask 077
tar -xzf "$HOME/.cloudstock-deploy/cloudstock.tar.gz" -C /opt/cloudstock
chmod 600 /opt/cloudstock/.env
cd /opt/cloudstock
python3 -m venv venv
venv/bin/pip install -r requirements.txt gunicorn
venv/bin/python - <<'PY'
from app import app
from models import db
from sqlalchemy import text
from storage import storage
with app.app_context():
    print('RDS:',db.session.execute(text('SELECT DATABASE()')).scalar())
    client,bucket=storage(); client.list_objects_v2(Bucket=bucket,MaxKeys=1); print('S3: OK')
PY
sudo tee /etc/systemd/system/cloudstock.service >/dev/null <<'UNIT'
[Unit]
Description=CloudStock Gunicorn
After=network-online.target
Wants=network-online.target
[Service]
User=ubuntu
WorkingDirectory=/opt/cloudstock
ExecStart=/opt/cloudstock/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 app:app
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable cloudstock
sudo systemctl restart cloudstock
for i in {1..15}; do if curl -fsS http://127.0.0.1:8000/login >/dev/null; then echo 'CloudStock: HTTP OK'; exit 0; fi; sleep 2; done
sudo journalctl -u cloudstock -n 20 --no-pager
exit 1
