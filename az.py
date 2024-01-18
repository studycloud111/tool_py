import socket
import time
import uuid
import json
import os
import logging
import argparse
import requests
from requests.exceptions import ConnectionError, Timeout, RequestException
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109 import DeleteDomainRecordRequest, AddDomainRecordRequest, \
    DescribeDomainRecordsRequest

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
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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


def load_azure():
    global azure_vms
    azure_vms = []
    with open(args.file, 'r') as f:
        configs = f.read().split('\n')
        for config in configs:
            config = config.split(',')
            if len(config) > 6:
                try:
                    tenant_id, client_id, client_secret, subscription_id, resource_group, region, *vm_names = config
                    credential = ClientSecretCredential(tenant_id, client_id, client_secret)
                    compute_client = ComputeManagementClient(credential, subscription_id)
                    network_client = NetworkManagementClient(credential, subscription_id)
                    vms = {vm_name: None for vm_name in vm_names}
                    azure_vms.append({
                        'compute_client': compute_client,
                        'network_client': network_client,
                        'resource_group': resource_group,
                        'region': region,
                        'vms': vms
                    })
                except Exception as e:
                    print(e)


load_azure()


while True:
    all_ips = []
    for azure in azure_vms:
        for vm_name in azure['vms']:
            try:
                vm = azure['compute_client'].virtual_machines.get(azure['resource_group'], vm_name)
                nic_name = vm.network_profile.network_interfaces[0].id.split('/')[-1]
                nic = azure['network_client'].network_interfaces.get(azure['resource_group'], nic_name)

                public_ip_address_object = nic.ip_configurations[0].public_ip_address

                if not public_ip_address_object:
                    print(f"VM {vm_name} does not have a public IP address. Creating one...")

                    # Create a new public IP
                    public_ip_name = f"{vm_name}-ip"  # Assuming VM names are unique
                    public_ip_params = {
                        'location': azure['region'],
                        'public_ip_allocation_method': 'Static'
                    }
                    new_public_ip = azure['network_client'].public_ip_addresses.begin_create_or_update(
                        azure['resource_group'],
                        public_ip_name,
                        public_ip_params
                    ).result()

                    # Associate the new public IP to the network interface
                    nic.ip_configurations[0].public_ip_address = new_public_ip
                    azure['network_client'].network_interfaces.begin_create_or_update(azure['resource_group'], nic_name,
                                                                                      nic).result()

                    public_ip = new_public_ip
                    public_ip_address = new_public_ip.ip_address
                else:
                    public_ip_id = public_ip_address_object.id
                    public_ip_name = public_ip_id.split('/')[-1]
                    public_ip = azure['network_client'].public_ip_addresses.get(azure['resource_group'], public_ip_name)
                    public_ip_address = public_ip.ip_address
                if public_ip_address:
                    all_ips.append(public_ip_address)  # 收集所有的IP地址
                fqdn = public_ip.dns_settings.fqdn if public_ip.dns_settings else None

                if not fqdn:
                    random_label = "a" + str(uuid.uuid4()).split('-')[0][:15]
                    public_ip.dns_settings = {
                        'domain_name_label': random_label
                    }
                    public_ip = azure['network_client'].public_ip_addresses.begin_create_or_update(
                        azure['resource_group'], public_ip_name, public_ip).result()
                    fqdn = public_ip.dns_settings.fqdn

                if not connect(public_ip_address):
                    print(vm_name, public_ip_address, 'change ip')
                    # 获取阿里云解析记录的RecordId
                    record_id = get_record_id(args.domain, args.rr, public_ip_address)
                     # 删除阿里云解析记录
                    if record_id:
                        delete_record(record_id)
                    existing_domain_name_label = public_ip.dns_settings.domain_name_label if public_ip.dns_settings else None
                    if not existing_domain_name_label:
                        existing_domain_name_label = "a" + str(uuid.uuid4()).split('-')[0][:15]

                    # Step 1: Disassociate the public IP from the network interface
                    nic.ip_configurations[0].public_ip_address = None
                    azure['network_client'].network_interfaces.begin_create_or_update(azure['resource_group'], nic_name,
                                                                                      nic).result()

                    # Step 2: Delete the public IP
                    azure['network_client'].public_ip_addresses.begin_delete(azure['resource_group'],
                                                                             public_ip_name).result()
                    time.sleep(10)

                    # Step 3: Create a new public IP
                    new_public_ip_params = {
                        'location': azure['region'],
                        'public_ip_allocation_method': 'Static',
                        'dns_settings': {
                            'domain_name_label': existing_domain_name_label
                        }
                    }
                    azure['network_client'].public_ip_addresses.begin_create_or_update(azure['resource_group'],
                                                                                       public_ip_name,
                                                                                       new_public_ip_params).result()

                    # Step 4: Reassociate the new public IP to the network interface
                    updated_public_ip = azure['network_client'].public_ip_addresses.get(azure['resource_group'],
                                                                                        public_ip_name)
                    nic.ip_configurations[0].public_ip_address = updated_public_ip
                    azure['network_client'].network_interfaces.begin_create_or_update(azure['resource_group'], nic_name,
                                                                                      nic).result()
                    if not updated_public_ip.dns_settings or not updated_public_ip.dns_settings.fqdn:
                        random_label = "a" + str(uuid.uuid4()).split('-')[0][:15]
                        updated_public_ip.dns_settings = {
                            'domain_name_label': random_label
                        }
                        updated_public_ip = azure['network_client'].public_ip_addresses.begin_create_or_update(
                            azure['resource_group'],
                            public_ip_name,updated_public_ip).result()

                    updated_ip_address = updated_public_ip.ip_address
                    all_ips.append(updated_ip_address)
                    all_ips.remove(public_ip_address)
                    # 如果DNS记录中不存在这个IP，就添加新的解析记录
                    if get_record_id(args.domain, args.rr, updated_ip_address) is None:
                        line = 'default'  # 默认线路
                        add_record(args.domain, args.rr, 'A', updated_ip_address, TTL=args.ttl)
                    fqdn = updated_public_ip.dns_settings.fqdn if updated_public_ip.dns_settings else None
                    print(f"New IP Address for {vm_name}: {updated_ip_address}, FQDN: {fqdn}")

                else:
                    try:
                        is_resolved = get_record_id(args.domain, args.rr, public_ip_address)
                        if not is_resolved:  # 如果IP没有解析
                            print(f"{vm_name} {public_ip_address} has not been resolved in DNS.")
                            try:
                                # 如果DNS记录中不存在这个IP，就添加新的解析记录
                                #   .  default：默认 telecom：中国电信 unicom：中国联通 mobile：中国移动
                                if get_record_id(args.domain, args.rr, public_ip_address) is None:
                                    line = 'default'  # 默认线路
                                    add_record(args.domain, args.rr, 'A', public_ip_address, TTL=args.ttl)
                            except Exception as e:
                                print(vm_name, e, "adding DNS record failed")
                        else:
                            print(f"{vm_name} {public_ip_address} is already resolved in DNS.")
                    except Exception as e:
                        print(vm_name, e, "error checking DNS resolution")
                    print(vm_name, public_ip_address, 'connect success, FQDN：' + fqdn)
            except Exception as e:
                print(f"Error with VM {vm_name}: {e}")
                load_azure()
    print(all_ips)
    ensure_only_my_ips(args.domain, args.rr, 'A', all_ips)
    time.sleep(60)
