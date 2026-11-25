from pathlib import Path
import os
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.env'
load_dotenv(ENV)
region = os.getenv('AWS_REGION', 'us-east-1')
try:
    account = boto3.client('sts', region_name=region).get_caller_identity()['Account']
    bucket = os.getenv('S3_BUCKET') or f'cloudstock-{account}-{region}'
    s3 = boto3.client('s3', region_name=region)
    try:
        s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
        print('Bucket existente:', bucket)
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket', 'NotFound'):
            raise
        args = {'Bucket':bucket}
        if region != 'us-east-1':
            args['CreateBucketConfiguration'] = {'LocationConstraint':region}
        s3.create_bucket(**args)
        print('Bucket creado:', bucket)
    s3.put_public_access_block(Bucket=bucket, ExpectedBucketOwner=account, PublicAccessBlockConfiguration={'BlockPublicAcls':True,'IgnorePublicAcls':True,'BlockPublicPolicy':True,'RestrictPublicBuckets':True})
    s3.put_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=account, VersioningConfiguration={'Status':'Enabled'})
    print('Versionado:', s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=account).get('Status'))
    set_key(str(ENV), 'S3_BUCKET', bucket, quote_mode='never')
    set_key(str(ENV), 'AWS_REGION', region, quote_mode='never')
    print('Acceso público bloqueado. Configuración guardada en .env.')
except (ClientError, BotoCoreError) as exc:
    raise SystemExit(f'No se completó la configuración S3: {exc}')
