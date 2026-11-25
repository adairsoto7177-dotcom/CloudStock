"""CloudStock deployment orchestrator. Run from the project root."""
import argparse
import ipaddress
import subprocess
import sys
import urllib.request
from pathlib import Path
import boto3
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
REGION = 'us-east-1'


def run(name, *args):
    print('\n>>>', name, flush=True)
    subprocess.run([sys.executable, str(ROOT / 'infrastructure' / name), *args], cwd=ROOT, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ip', help='IPv4 publica; se detecta si se omite')
    p.add_argument('--profile', default='LabInstanceProfile', help='Perfil IAM de EC2')
    p.add_argument('--mantener-rds-local', action='store_true', help='No retirar regla de IP local al finalizar')
    a = p.parse_args()
    env = dotenv_values(ROOT / '.env')
    if not env.get('SECRET_KEY') or not env.get('DB_HOST'):
        raise SystemExit('Configura primero .env y la base de datos de origen.')
    if env.get('AWS_REGION', REGION) != REGION:
        raise SystemExit('Esta version del proyecto usa us-east-1.')
    ip = a.ip or urllib.request.urlopen('https://checkip.amazonaws.com', timeout=10).read().decode().strip()
    ip = ipaddress.IPv4Address(ip)
    if not ip.is_global:
        raise SystemExit('Se requiere una IPv4 publica.')
    rds = boto3.client('rds', region_name=REGION)
    try:
        db = rds.describe_db_instances(DBInstanceIdentifier='cloudstock-db')['DBInstances'][0]
    except rds.exceptions.DBInstanceNotFoundFault:
        db = None
    local = env.get('DB_HOST') in ('localhost', '127.0.0.1', '::1')
    if db is None and not local:
        raise SystemExit('RDS no existe y .env no apunta a MariaDB local. Restaura la configuracion local antes de migrar.')
    if db and db['DBInstanceStatus'] != 'available':
        raise SystemExit('RDS no esta available: '+db['DBInstanceStatus']+'. No se modifico la infraestructura.')
    if db and not local and env.get('DB_HOST') != db.get('Endpoint', {}).get('Address'):
        raise SystemExit('El endpoint de .env no coincide con CloudStock RDS.')
    if local and db:
        raise SystemExit('RDS ya existe pero .env apunta a local. Completa o verifica migrate_rds.py y activar_rds.py manualmente antes de continuar; no se repetira una migracion.')
    cert = ROOT / 'certs' / 'global-bundle.pem'
    if not cert.exists():
        cert.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', cert)
    run('deploy_s3.py')
    if db is None:
        run('deploy_rds.py', '--ip', str(ip), '--region', REGION)
        run('migrate_rds.py')
        run('activar_rds.py')
    else:
        print('RDS existente: se conserva la base de datos; no se migra ni se reabre el acceso local.')
    args = ['--ip', str(ip), '--profile', a.profile]
    if not a.mantener_rds_local:
        args.append('--cerrar-rds')
    run('deploy_ec2.py', *args)
    print('\nDespliegue completado. Usa el tunel SSH mostrado por el script.')

if __name__ == '__main__':
    main()
