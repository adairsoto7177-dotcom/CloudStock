"""Create/reuse CloudStock RDS in the default VPC. Run from project root."""
import argparse
import ipaddress
from getpass import getpass
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.env.rds'
NAME = 'cloudstock-db'
USER = 'cloudadmin'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True, help='Your public IPv4 address')
    parser.add_argument('--region', default='us-east-1')
    args = parser.parse_args()
    ip = ipaddress.IPv4Address(args.ip.strip())
    if not ip.is_global:
        raise SystemExit('Se requiere una IPv4 publica.')
    cidr = f'{ip}/32'
    ec2 = boto3.client('ec2', region_name=args.region)
    rds = boto3.client('rds', region_name=args.region)
    vpcs = ec2.describe_vpcs(Filters=[{'Name':'isDefault','Values':['true']}])['Vpcs']
    if len(vpcs) != 1:
        raise SystemExit('No se encontro una VPC predeterminada; no se crearon recursos.')
    vpc = vpcs[0]['VpcId']
    try:
        existing = rds.describe_db_instances(DBInstanceIdentifier=NAME)['DBInstances'][0]
    except rds.exceptions.DBInstanceNotFoundFault:
        existing = None
    groups = ec2.describe_security_groups(Filters=[{'Name':'vpc-id','Values':[vpc]}, {'Name':'group-name','Values':['cloudstock-rds']}])['SecurityGroups']
    if groups:
        group = groups[0]
        sg = group['GroupId']
        for rule in group.get('IpPermissions', []):
            if (rule.get('IpProtocol') != 'tcp' or rule.get('FromPort') != 3306 or rule.get('ToPort') != 3306
                or any(r['CidrIp'] != cidr for r in rule.get('IpRanges', []))
                or rule.get('Ipv6Ranges') or rule.get('PrefixListIds') or rule.get('UserIdGroupPairs')):
                raise SystemExit('El grupo existente tiene reglas distintas. Revisar antes de continuar.')
    else:
        sg = ec2.create_security_group(GroupName='cloudstock-rds', Description='CloudStock RDS temporary local access', VpcId=vpc, TagSpecifications=[{'ResourceType':'security-group','Tags':[{'Key':'Project','Value':'CloudStock'}]}])['GroupId']
    if existing and (existing['Engine'] != 'mariadb' or existing['MasterUsername'] != USER or {g['VpcSecurityGroupId'] for g in existing['VpcSecurityGroups']} != {sg} or not existing['PubliclyAccessible']):
        raise SystemExit('La instancia existente no coincide con la configuracion de esta fase.')
    try:
        ec2.authorize_security_group_ingress(GroupId=sg, IpProtocol='tcp', FromPort=3306, ToPort=3306, CidrIp=cidr)
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'InvalidPermission.Duplicate':
            raise
    old = dotenv_values(ENV) if ENV.exists() else {}
    password = old.get('DB_PASSWORD')
    if not password:
        password = getpass('Contrasena RDS (12+ caracteres, sin espacios, /, @, comillas): ')
        if password != getpass('Confirmar: '):
            raise SystemExit('No coinciden.')
    if not 12 <= len(password) <= 41 or any(c in password for c in '/@"\' ') or not password.isascii() or not password.isprintable():
        raise SystemExit('Contrasena no valida para esta configuracion.')
    if not existing:
        # Choose a currently offered engine version via the service default.
        rds.create_db_instance(DBInstanceIdentifier=NAME, DBInstanceClass='db.t3.micro', Engine='mariadb', MasterUsername=USER, MasterUserPassword=password, DBName='cloudstock', AllocatedStorage=20, StorageType='gp2', StorageEncrypted=True, VpcSecurityGroupIds=[sg], PubliclyAccessible=True, MultiAZ=False, BackupRetentionPeriod=1, AutoMinorVersionUpgrade=True, DeletionProtection=False, Tags=[{'Key':'Project','Value':'CloudStock'}])
        print('Solicitud de creacion enviada.')
    else:
        print('Reutilizando instancia existente. La contrasena debe ser la original.')
    ENV.touch(exist_ok=True)
    for k,v in {'DB_USER':USER,'DB_PASSWORD':password,'DB_NAME':'cloudstock','DB_PORT':'3306','DB_SSL_CA':str(ROOT / 'certs' / 'global-bundle.pem'),'AWS_REGION':args.region}.items():
        set_key(str(ENV),k,v)
    print('Security group:',sg,'; acceso:',cidr)
    print('Esperando estado available...')
    rds.get_waiter('db_instance_available').wait(DBInstanceIdentifier=NAME, WaiterConfig={'Delay':30,'MaxAttempts':80})
    instance = rds.describe_db_instances(DBInstanceIdentifier=NAME)['DBInstances'][0]
    endpoint = instance['Endpoint']['Address']
    set_key(str(ENV),'DB_HOST',endpoint)
    print('RDS disponible:',endpoint)
    print('Motor:',instance['Engine'],instance['EngineVersion'])
    print('Configuracion guardada en .env.rds (no publicar).')

if __name__ == '__main__':
    main()
