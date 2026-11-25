import os
import io
import uuid
import boto3
from botocore.config import Config
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024

class StorageUnavailable(Exception):
    pass


def storage():
    bucket = os.getenv('S3_BUCKET', '').strip()
    if not bucket or os.getenv('S3_SIMULAR_FALLO', '0') == '1':
        raise StorageUnavailable('Almacenamiento no disponible.')
    client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'),
                          config=Config(signature_version='s3v4', connect_timeout=3,
                                        read_timeout=5, retries={'total_max_attempts': 2}))
    return client, bucket


def preparar_imagen(archivo):
    data = archivo.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Selecciona una imagen de hasta 5 MB.')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ('JPEG', 'PNG', 'WEBP') or img.width * img.height > 16000000:
                raise ValueError('Usa JPG, PNG o WEBP de hasta 16 megapíxeles.')
            img = ImageOps.exif_transpose(img).convert('RGB')
            img.thumbnail((1200, 1200))
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('El archivo no es una imagen válida.') from exc


def guardar_imagen(archivo, clave=None):
    data = preparar_imagen(archivo)
    client, bucket = storage()
    clave = clave or f'productos/{uuid.uuid4().hex}.jpg'
    client.put_object(Bucket=bucket, Key=clave, Body=data, ContentType='image/jpeg', ServerSideEncryption='AES256')
    return clave


def versiones(clave):
    client, bucket = storage()
    resultado = []
    for page in client.get_paginator('list_object_versions').paginate(Bucket=bucket, Prefix=clave):
        resultado.extend(v for v in page.get('Versions', []) if v['Key'] == clave)
    return resultado


def restaurar(clave, version):
    client, bucket = storage()
    client.copy_object(Bucket=bucket, Key=clave, CopySource={'Bucket':bucket,'Key':clave,'VersionId':version}, ServerSideEncryption='AES256')
