import boto3
import socket
import time
import json
import os
import logging
import argparse
import requests
from requests.exceptions import ConnectionError, Timeout, RequestException
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109 import DeleteDomainRecordRequest, AddDomainRecordRequest, DescribeDomainRecordsRequest


# 获取环境变量，如果环境变量不存在，则使用后面的默认值
default_domain = os.getenv('DOMAIN', 'default_domain.com')
default_rr = os.getenv('RR', 'default_rr')
default_ttl = os.getenv('TTL', '1')
default_file = os.getenv('FILE', 'default_file.txt')
default_port = os.getenv('PORT', '8080')
default_alikey = os.getenv('ALIKEY', 'LTAI5tE8E6TT67PQSWRJKij4')
default_alista = os.getenv('ALISTA', 'aWuq0JtnKXZKYkt2jOvpMQDIKvo5uI')
default_api = os.getenv('api', '159.75.83.139')

# 解析命令行参数
parser = argparse.ArgumentParser(description="脚本用于获取记录ID")
parser.add_argument("--domain", type=str, default=default_domain, help="域名")
parser.add_argument("--rr", type=str, default=default_rr, help="子域名")
parser.add_argument("--ttl", type=str, default=default_ttl, help="记录值")
parser.add_argument("--file", type=str, default=default_file, help="文件路径")
parser.add_argument("--port", type=int, default=int(default_port), help="端口号")
parser.add_argument("--alikey", type=str, default=default_alikey, help="YOUR_ACCESS_KEY_ID")
parser.add_argument("--alista", type=str, default=default_alista, help="YOUR_ACCESS_SECRET")
parser.add_argument("--api", type=str, default=default_api, help="你的端口检测api")
args = parser.parse_args()

# 初始化阿里云客户端
ali_client = AcsClient(args.alikey, args.alista, 'cn-hangzhou')

# 获取与指定子域和记录类型匹配的所有记录
def get_all_records(domain, subdomain, record_type):
    request = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
    request.set_DomainName(domain)
    response = ali_client.do_action_with_exception(request)
    all_records = json.loads(response)
    matched_records = [
        record for record in all_records.get('DomainRecords', {}).get('Record', [])
        if record.get('RR') == subdomain and record.get('Type') == record_type
    ]
    return matched_records

# 确保只有我的IP在解析记录中
def ensure_only_my_ips(domain, subdomain, record_type, my_ips):
    records = get_all_records(domain, subdomain, record_type)

    to_delete = [record for record in records if record['Value'] not in my_ips]

    for record in to_delete:
        try:
            delete_record(record['RecordId'])
            logger.info(f"Deleted record {record['RecordId']} with IP {record['Value']}.")
        except Exception as e:
            logger.info(f"Error deleting record {record['RecordId']}: {e}")

# 获取解析记录的ID
def get_record_id(DomainName, RR, IP):
    request = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
    request.set_DomainName(DomainName)
    response = ali_client.do_action_with_exception(request)
    records = json.loads(response.decode('utf-8'))
    for record in records['DomainRecords']['Record']:
        if record['RR'] == RR and record['Value'] == IP:
            return record['RecordId']
    return None

# 删除解析记录
def delete_record(RecordId):
    request = DeleteDomainRecordRequest.DeleteDomainRecordRequest()
    request.set_RecordId(RecordId)
    ali_client.do_action_with_exception(request)


# 添加解析记录
def add_record(DomainName, RR, Type, Value, TTL=600, Line='default'):
    request = AddDomainRecordRequest.AddDomainRecordRequest()
    request.set_DomainName(DomainName)
    request.set_RR(RR)
    request.set_Type(Type)
    request.set_Value(Value)
    request.set_TTL(TTL)
    request.set_Line(Line)
    ali_client.do_action_with_exception(request)

# 日志记录器设置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 检查是否能连接到指定IP和端口
def connect(ip):
    api_url = f"http://{args.api}:10080/check_port"
    retries = 3  # 设置重试次数

    for attempt in range(retries):
        try:
            response = requests.get(api_url, params={"ip": ip, "port": args.port}, timeout=10)
            if response.status_code == 200:
                try:
                    result = response.json()
                    return result.get("open", False)
                except ValueError:  # 包括JSON解码错误
                    print("无法解析JSON响应")
            else:
                print(f"API返回非200状态码：{response.status_code}")
        except ConnectionError:
            print("连接错误")
        except Timeout:
            print("请求超时")
        except RequestException as e:
            print(f"请求发生错误: {e}")

        print(f"尝试 {attempt + 1}/{retries} 失败，正在重试...")
    return False

# 从文件加载AWS服务数据
def load_aws():
    global aws
    aws = [] 
    with open(args.file, 'r') as f:
        data = f.read().split('\n')
        for item in data:
            item = item.split(',')
            if len(item) > 4:
                # 确定服务类型，是EC2还是Lightsail
                service = item[3]
                try:
                    # 如果是EC2实例
                    if service == 'ec2':
                        client = boto3.client('ec2', region_name=item[2], aws_access_key_id=item[0], aws_secret_access_key=item[1])
                        ids = {}
                        response = client.describe_instances(InstanceIds=item[4:])
                        for reservation in response['Reservations']:
                            for instance in reservation['Instances']:
                                ids[instance['InstanceId']] = instance['PublicIpAddress']
                                
                    # 如果是Lightsail实例
                    elif service == 'lightsail':
                        client = boto3.client('lightsail', region_name=item[2], aws_access_key_id=item[0], aws_secret_access_key=item[1])
                        ids = {}
                        for instance_id in item[4:]:
                            response = client.get_instance(instanceName=instance_id)
                            ids[response['instance']['name']] = response['instance']['publicIpAddress']
                    else:
                        continue
                    
                    # 添加客户端、ID、地域和服务类型到aws列表中
                    aws.append({'client': client, "ids": ids, 'region_name': item[2], 'service': service})
                    
                except Exception as e:
                    logger.error(e)

# 主循环
load_aws()
while True:
    all_ips = []
    for a in aws:
        for k, v in a['ids'].items():
            all_ips.append(v)  # 收集所有的IP地址
            current_region = a['region_name']  # 获取当前的region_name
            print(current_region)
            if not connect(v):  # 如果连接失败，我们认为需要更换 IP
                logger.info(f"{k}, {v}, attempting to change ip")
                
                if a['service'] == 'ec2':
                    record_id = get_record_id(args.domain, args.rr, v)
                    if record_id:
                        delete_record(record_id)

                    try:
                        response = a['client'].describe_addresses()
                        for address in response['Addresses']:
                            if address.get('InstanceId') == k:
                                a['client'].disassociate_address(AssociationId=address['AssociationId'])
                                a['client'].release_address(AllocationId=address['AllocationId'])
                    except Exception as e:
                        logger.error(f"{k}, {e}")

                    try:
                        new_address = a['client'].allocate_address(Domain='vpc')
                        a['client'].associate_address(InstanceId=k, AllocationId=new_address['AllocationId'])
                    except Exception as e:
                        logger.error(f"{k}, {e}")

                elif a['service'] == 'lightsail':  # 如果是Lightsail实例
                    try:
                        a['client'].detach_static_ip(staticIpName=k + 'ipv4')
                    except Exception as e:
                        logger.error(f"{k}, {e}")

                    try:
                        a['client'].release_static_ip(staticIpName=k + 'ipv4')
                    except Exception as e:
                        logger.error(f"{k}, {e}")
                    try:
                        a['client'].allocate_static_ip(staticIpName=k + 'ipv4')
                    except Exception as e:
                        logger.error(f"{k}, {e}")
                    try:
                        a['client'].attach_static_ip(staticIpName=k + 'ipv4', instanceName=k)
                    except Exception as e:
                        logger.error(f"{k}, {e}")

                # 更新新的IP地址
                try:
                    if a['service'] == 'ec2':
                        response = a['client'].describe_instances(InstanceIds=[k])
                        new_ip = response['Reservations'][0]['Instances'][0]['PublicIpAddress']
                    elif a['service'] == 'lightsail':
                        response = a['client'].get_instance(instanceName=k)
                        new_ip = response['instance']['publicIpAddress']

                    all_ips.append(new_ip)
                    all_ips.remove(v)
                    if get_record_id(args.domain, args.rr, new_ip) is None:
                        line = 'default'
                        if a.get('region_name') == 'ap-northeast-1':
                            line = 'unicom'
                        elif a.get('region_name') == 'ap-southeast-1':
                            line = 'telecom'
                        add_record(args.domain, args.rr, 'A', new_ip, TTL=args.ttl)
                    logger.info(f"{k}, {v} -> {new_ip}, ip change successful")
                    a["ids"][k] = new_ip
                except Exception as e:
                    logger.error(f"{k}, {e}, ip change failed")
                    load_aws()

            else:  # 如果连接成功，检查是否已解析
                try:
                    is_resolved = get_record_id(args.domain, args.rr, v)
                    if not is_resolved:
                        logger.info(f"{k} {v} has not been resolved in DNS.")
                        if get_record_id(args.domain, args.rr, v) is None:
                            line = 'default'
                            if a.get('region_name') == 'ap-northeast-1':
                                line = 'unicom'
                            elif a.get('region_name') == 'ap-southeast-1':
                                line = 'telecom'
                            add_record(args.domain, args.rr, 'A', v, TTL=args.ttl)
                    else:
                        logger.info(f"{k} {v} is already resolved in DNS.")
                except Exception as e:
                    logger.info(k, e, "error checking DNS resolution")
                logger.info(f"{k}, {v}, connect success")
    logger.info(all_ips)
    ensure_only_my_ips(args.domain, args.rr, 'A', all_ips)
    time.sleep(60)
