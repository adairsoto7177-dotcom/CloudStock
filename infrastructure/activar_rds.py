"""Switch local application to RDS, keeping a private local configuration backup."""
from pathlib import Path
from shutil import copy2
from dotenv import dotenv_values, set_key
from migrate_rds import connect

ROOT = Path(__file__).resolve().parents[1]
active = ROOT / '.env'
backup = ROOT / '.env.local'
remote = dotenv_values(ROOT / '.env.rds')
if not backup.exists():
    copy2(active, backup)
with connect(remote, True) as conn:
    with conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM usuarios')
        if cursor.fetchone()[0] == 0:
            raise SystemExit('No hay usuarios en RDS; primero migra los datos.')
for k in ('DB_HOST','DB_PORT','DB_USER','DB_PASSWORD','DB_NAME','DB_SSL_CA'):
    set_key(str(active),k,remote[k])
print('CloudStock configurado para RDS. Respaldo: .env.local')
