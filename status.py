"""Read-only AWS status for CloudStock."""
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
REGION = 'us-east-1'

def main():
    env = dotenv_values(ROOT / '.env')
    account = boto3.client('sts', region_name=REGION).get_caller_identity()['Account']
    ec = boto3.client('ec2', region_name=REGION)
    rd = boto3.client('rds', region_name=REGION)
    s3 = boto3.client('s3', region_name=REGION)
    print('CloudStock |', REGION)
    print('\nEC2:')
    found = False
    for page in ec.get_paginator('describe_instances').paginate(Filters=[{'Name':'tag:Name','Values':['cloudstock-web']},{'Name':'instance-state-name','Values':['pending','running','stopping','stopped','shutting-down']}]):
        for reservation in page['Reservations']:
            for i in reservation['Instances']:
                found = True
                print(i['InstanceId'], i['InstanceType'], i['State']['Name'], 'IP:', i.get('PublicIpAddress','-'))
    if not found: print('No encontrada')
    print('\nRDS:')
    try:
        d = rd.describe_db_instances(DBInstanceIdentifier='cloudstock-db')['DBInstances'][0]
        print(d['DBInstanceIdentifier'], d['Engine'], d['DBInstanceClass'], d['DBInstanceStatus'])
        print('Endpoint:', d.get('Endpoint',{}).get('Address','-'))
        for g in d['VpcSecurityGroups']:
            group = ec.describe_security_groups(GroupIds=[g['VpcSecurityGroupId']])['SecurityGroups'][0]
            print('Grupo:',group['GroupId'],'reglas de entrada:',group['IpPermissions'])
    except rd.exceptions.DBInstanceNotFoundFault: print('No encontrada')
    print('\nS3:')
    bucket = env.get('S3_BUCKET') or f'cloudstock-{account}-{REGION}'
    try:
        s3.head_bucket(Bucket=bucket,ExpectedBucketOwner=account)
        print(bucket, 'Versionado:',s3.get_bucket_versioning(Bucket=bucket,ExpectedBucketOwner=account).get('Status','Desactivado'))
        print('Bloqueo publico:',s3.get_public_access_block(Bucket=bucket,ExpectedBucketOwner=account)['PublicAccessBlockConfiguration'])
    except ClientError as e: print('No se pudo consultar:',e.response['Error']['Code'])
    print('\nConsulta finalizada. No se modificaron recursos.')

if __name__ == '__main__': main()
