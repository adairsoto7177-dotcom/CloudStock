import argparse, ipaddress, os, subprocess, time, tarfile, tempfile, shutil
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values, set_key
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(); p.add_argument('--ip',required=True); p.add_argument('--profile',default='LabInstanceProfile'); p.add_argument('--cerrar-rds',action='store_true'); a=p.parse_args()
cidr=str(ipaddress.IPv4Address(a.ip))+'/32'
env=dotenv_values(ROOT/'.env'); region=env.get('AWS_REGION','us-east-1'); ec=boto3.client('ec2',region_name=region); rds=boto3.client('rds',region_name=region)
db=rds.describe_db_instances(DBInstanceIdentifier='cloudstock-db')['DBInstances'][0]
if db['DBInstanceStatus']!='available': raise SystemExit('RDS no disponible.')
if env.get('DB_HOST')!=db['Endpoint']['Address']: raise SystemExit('Activa RDS primero.')
vpc=db['DBSubnetGroup']['VpcId']; dbgroups=[x['VpcSecurityGroupId'] for x in db['VpcSecurityGroups']]
def auth(group, perm):
    try: ec.authorize_security_group_ingress(GroupId=group,IpPermissions=[perm])
    except ClientError as e:
        if e.response['Error']['Code']!='InvalidPermission.Duplicate': raise

def groups(name): return ec.describe_security_groups(Filters=[{'Name':'vpc-id','Values':[vpc]},{'Name':'group-name','Values':[name]}])['SecurityGroups']
if not all(env.get(k) for k in ('SECRET_KEY','DB_HOST','DB_USER','DB_PASSWORD','DB_NAME','S3_BUCKET')): raise SystemExit('Faltan variables en .env')
for cmd in ('ssh','scp'):
    if not shutil.which(cmd): raise SystemExit('Falta OpenSSH: '+cmd)
required=['app.py','config.py','models.py','storage.py','fotos.py','requirements.txt','templates','static','certs/global-bundle.pem']
for f in required:
    if not (ROOT/f).exists(): raise SystemExit('Falta '+f)
g=groups('cloudstock-web'); sg=g[0]['GroupId'] if g else ec.create_security_group(GroupName='cloudstock-web',Description='CloudStock SSH',VpcId=vpc)['GroupId']
auth(sg,{'IpProtocol':'tcp','FromPort':22,'ToPort':22,'IpRanges':[{'CidrIp':cidr}]})
for group in dbgroups: auth(group,{'IpProtocol':'tcp','FromPort':3306,'ToPort':3306,'UserIdGroupPairs':[{'GroupId':sg}]})
key=ROOT/'cloudstock-web.pem'; keyname='cloudstock-web'
try: ec.describe_key_pairs(KeyNames=[keyname]); exists=True
except ClientError as e:
    if e.response['Error']['Code']!='InvalidKeyPair.NotFound': raise
    exists=False
if exists and not key.exists(): raise SystemExit('Existe la llave AWS pero falta el PEM local; no se puede recuperar.')
if not exists:
    if key.exists(): raise SystemExit('Existe un PEM local sin llave AWS; renombralo antes de continuar.')
    material=ec.create_key_pair(KeyName=keyname)['KeyMaterial']; key.write_text(material,encoding='ascii'); os.chmod(key,0o600)
    if os.name=='nt':
        user=subprocess.check_output(['whoami'],text=True).strip(); subprocess.run(['icacls',str(key),'/inheritance:r','/grant:r',user+':R'],check=True)
instances=[i for r in ec.describe_instances(Filters=[{'Name':'tag:Name','Values':['cloudstock-web']},{'Name':'vpc-id','Values':[vpc]},{'Name':'instance-state-name','Values':['pending','running','stopping','stopped']}])['Reservations'] for i in r['Instances']]
if len(instances)>1: raise SystemExit('Hay varias instancias cloudstock-web; revisa antes de continuar.')
if instances:
    i=instances[0]; iid=i['InstanceId']
    if i['KeyName']!=keyname or sg not in [x['GroupId'] for x in i['SecurityGroups']]: raise SystemExit('Instancia existente incompatible.')
    if i['State']['Name']=='stopping': ec.get_waiter('instance_stopped').wait(InstanceIds=[iid]); ec.start_instances(InstanceIds=[iid])
    elif i['State']['Name']=='stopped': ec.start_instances(InstanceIds=[iid])
else:
    subnets=ec.describe_subnets(Filters=[{'Name':'vpc-id','Values':[vpc]},{'Name':'default-for-az','Values':['true']}])['Subnets']
    if not subnets: raise SystemExit('No hay subred predeterminada; revisar VPC.')
    images=ec.describe_images(Owners=['099720109477'],Filters=[{'Name':'name','Values':['ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*']},{'Name':'state','Values':['available']}])['Images']
    if not images: raise SystemExit('No se encontro AMI Ubuntu.')
    ami=max(images,key=lambda x:x['CreationDate'])
    i=ec.run_instances(ImageId=ami['ImageId'],InstanceType='t3.micro',MinCount=1,MaxCount=1,KeyName=keyname,IamInstanceProfile={'Name':a.profile},NetworkInterfaces=[{'DeviceIndex':0,'SubnetId':subnets[0]['SubnetId'],'Groups':[sg],'AssociatePublicIpAddress':True}],MetadataOptions={'HttpTokens':'required'},BlockDeviceMappings=[{'DeviceName':ami['RootDeviceName'],'Ebs':{'VolumeSize':10,'VolumeType':'gp3','DeleteOnTermination':True}}],TagSpecifications=[{'ResourceType':'instance','Tags':[{'Key':'Name','Value':'cloudstock-web'}]}])['Instances'][0]; iid=i['InstanceId']
print('EC2:',iid,flush=True); ec.get_waiter('instance_running').wait(InstanceIds=[iid]); ec.get_waiter('instance_status_ok').wait(InstanceIds=[iid]); i=ec.describe_instances(InstanceIds=[iid])['Reservations'][0]['Instances'][0]; host=i['PublicIpAddress']; target='ubuntu@'+host
ssh=['ssh','-i',str(key),'-o','StrictHostKeyChecking=accept-new','-o','ConnectTimeout=10','-o','BatchMode=yes',target]
for attempt in range(30):
    if subprocess.run(ssh+['true']).returncode==0: break
    time.sleep(5)
else: raise SystemExit('SSH no disponible.')
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp); remoteenv=tmp/'.env'; remoteenv.touch(mode=0o600)
    for k in ('SECRET_KEY','DB_HOST','DB_PORT','DB_USER','DB_PASSWORD','DB_NAME','S3_BUCKET','AWS_REGION'):
        if env.get(k) is not None: set_key(str(remoteenv),k,env[k])
    set_key(str(remoteenv),'DB_SSL_CA','/opt/cloudstock/certs/global-bundle.pem')
    archive=tmp/'cloudstock.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for f in required: t.add(ROOT/f,arcname=f)
        t.add(remoteenv,arcname='.env')
    subprocess.run(ssh+['umask 077; mkdir -p ~/.cloudstock-deploy; chmod 700 ~/.cloudstock-deploy'],check=True)
    subprocess.run(['scp','-i',str(key),'-o','StrictHostKeyChecking=accept-new',str(archive),str(ROOT/'infrastructure/bootstrap_ec2.sh'),target+':.cloudstock-deploy/'],check=True)
    subprocess.run(ssh+['bash ~/.cloudstock-deploy/bootstrap_ec2.sh'],check=True)
print('EC2:',iid,'IP:',host,'SG:',sg)
print(f'ssh -i "{key}" -N -L 8080:127.0.0.1:8000 {target}')
if a.cerrar_rds:
    for group in dbgroups:
        rules=ec.describe_security_groups(GroupIds=[group])['SecurityGroups'][0]['IpPermissions']
        for rule in rules:
            if rule.get('IpProtocol')=='tcp' and rule.get('FromPort')==3306 and rule.get('ToPort')==3306:
                for ip in rule.get('IpRanges',[]):
                    if ip['CidrIp']==cidr: ec.revoke_security_group_ingress(GroupId=group,IpPermissions=[{'IpProtocol':'tcp','FromPort':3306,'ToPort':3306,'IpRanges':[{'CidrIp':cidr}]}])
    print('Regla local actual retirada; revisar otras reglas existentes.')
