"""Controlled cleanup. Default is read-only plan; explicit confirmation required."""
import argparse
from pathlib import Path
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
REGION = 'us-east-1'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ejecutar',action='store_true')
    p.add_argument('--borrar-datos',action='store_true',help='Incluye RDS y todas las versiones de S3; por defecto conserva datos')
    p.add_argument('--sin-snapshot',action='store_true',help='No crear snapshot final de RDS (irreversible)')
    a=p.parse_args()
    if a.sin_snapshot and not a.borrar_datos: p.error('--sin-snapshot requiere --borrar-datos')
    account=boto3.client('sts',region_name=REGION).get_caller_identity()['Account']
    ec=boto3.client('ec2',region_name=REGION); rd=boto3.client('rds',region_name=REGION); s3=boto3.client('s3',region_name=REGION)
    env=dotenv_values(ROOT/'.env')
    expected=f'cloudstock-{account}-{REGION}'
    bucket=env.get('S3_BUCKET') or expected
    try: d=rd.describe_db_instances(DBInstanceIdentifier='cloudstock-db')['DBInstances'][0]
    except rd.exceptions.DBInstanceNotFoundFault: d=None
    filters=[{'Name':'tag:Name','Values':['cloudstock-web']},{'Name':'instance-state-name','Values':['pending','running','stopping','stopped']}]
    instances=[i for pg in ec.get_paginator('describe_instances').paginate(Filters=filters) for r in pg['Reservations'] for i in r['Instances']]
    if len(instances)>1: raise SystemExit('Varias instancias coinciden; no se eliminara ninguna.')
    for i in instances:
        if i.get('KeyName')!='cloudstock-web' or not any(g['GroupName']=='cloudstock-web' for g in i['SecurityGroups']):
            raise SystemExit('EC2 no coincide con la configuracion esperada.')
        if d and i['VpcId']!=d['DBSubnetGroup']['VpcId']: raise SystemExit('VPC incompatible.')
    if a.borrar_datos:
        if bucket!=expected: raise SystemExit('Nombre de bucket distinto al esperado; se requiere revision manual.')
        if d:
            tags=rd.list_tags_for_resource(ResourceName=d['DBInstanceArn'])['TagList']
            if {'Key':'Project','Value':'CloudStock'} not in tags: raise SystemExit('RDS no tiene etiqueta CloudStock.')
            if d.get('DeletionProtection'): raise SystemExit('RDS tiene proteccion de borrado; no se desactivara automaticamente.')
    print('PLAN:', 'EC2 '+str([i['InstanceId'] for i in instances]))
    print('RDS:', 'eliminar' if a.borrar_datos and d else 'conservar/no existe')
    print('S3:', 'eliminar objetos, versiones y bucket '+bucket if a.borrar_datos else 'conservar')
    print('Snapshot final:', 'no' if a.sin_snapshot else 'si, cuando se elimine RDS (puede generar costo)')
    print('Grupos de seguridad y llave AWS se conservan para reutilizacion; PEM local no se toca.')
    if not a.ejecutar:
        print('Solo consulta; no se elimino nada.'); return
    if input('Escribe ELIMINAR CLOUDSTOCK para confirmar: ').strip()!='ELIMINAR CLOUDSTOCK':
        print('Cancelado.'); return
    if instances:
        ids=[i['InstanceId'] for i in instances]; ec.terminate_instances(InstanceIds=ids); ec.get_waiter('instance_terminated').wait(InstanceIds=ids); print('EC2 terminada.')
    if not a.borrar_datos: return
    if d:
        if d['DBInstanceStatus']!='deleting':
            kwargs={'DBInstanceIdentifier':'cloudstock-db','SkipFinalSnapshot':a.sin_snapshot,'DeleteAutomatedBackups':True}
            if not a.sin_snapshot:
                kwargs['FinalDBSnapshotIdentifier']='cloudstock-final-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
            rd.delete_db_instance(**kwargs)
        rd.get_waiter('db_instance_deleted').wait(DBInstanceIdentifier='cloudstock-db',WaiterConfig={'Delay':30,'MaxAttempts':80}); print('RDS eliminada.')
    try: s3.head_bucket(Bucket=bucket,ExpectedBucketOwner=account)
    except ClientError as e:
        if e.response['Error']['Code'] in ('404','NoSuchBucket','NotFound'): print('Bucket no existe.'); return
        raise
    # Re-read first page until empty, avoiding pagination while deleting.
    while True:
        page=s3.list_object_versions(Bucket=bucket,ExpectedBucketOwner=account,MaxKeys=1000)
        objects=[{'Key':x['Key'],'VersionId':x['VersionId']} for x in page.get('Versions',[])+page.get('DeleteMarkers',[])]
        if not objects: break
        result=s3.delete_objects(Bucket=bucket,ExpectedBucketOwner=account,Delete={'Objects':objects,'Quiet':True})
        if result.get('Errors'): raise RuntimeError('No se pudieron borrar algunas versiones; revisar permisos.')
    for page in s3.get_paginator('list_multipart_uploads').paginate(Bucket=bucket,ExpectedBucketOwner=account):
        for upload in page.get('Uploads',[]): s3.abort_multipart_upload(Bucket=bucket,Key=upload['Key'],UploadId=upload['UploadId'],ExpectedBucketOwner=account)
    s3.delete_bucket(Bucket=bucket,ExpectedBucketOwner=account); print('Bucket eliminado.')

if __name__=='__main__': main()
