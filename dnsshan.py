import logging
import json
import requests
from requests.exceptions import ConnectionError, Timeout, RequestException
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109 import DescribeDomainRecordsRequest, DeleteDomainRecordRequest

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 阿里云API客户端初始化
client = AcsClient('<your-access-key-id>', '<your-access-key-secret>', 'cn-hangzhou')

def get_domain_records(domain):
    """获取指定域名的所有DNS解析记录"""
    request = DescribeDomainRecordsRequest()
    request.set_DomainName(domain)
    request.set_accept_format('json')
    response = client.do_action_with_exception(request)
    records = json.loads(str(response, encoding='utf-8'))
    return records['DomainRecords']['Record']

def delete_dns_record(record_id):
    """删除指定的DNS解析记录"""
    request = DeleteDomainRecordRequest()
    request.set_RecordId(record_id)
    response = client.do_action_with_exception(request)
    logger.info(f"已删除DNS记录：{record_id}")

def check_port(api_url, ip, port=22, retries=10):
    """检查指定IP的端口是否开放，带重试逻辑"""
    for attempt in range(retries):
        try:
            response = requests.get(api_url, params={"ip": ip, "port": port}, timeout=10)
            if response.status_code == 200 and response.json().get("open", False):
                logger.info(f"端口在 {ip} 上开放")
                return True
            logger.info(f"尝试 {attempt + 1}/{retries}：端口在 {ip} 上未开放")
        except ConnectionError:
            logger.error(f"尝试 {attempt + 1}/{retries}：连接错误")
        except Timeout:
            logger.error(f"尝试 {attempt + 1}/{retries}：请求超时")
        except RequestException as e:
            logger.error(f"尝试 {attempt + 1}/{retries}：请求异常：{e}")
        if attempt < retries - 1:
            logger.info("正在重试...")
    return False

def process_domain_records(api_url, domain):
    """处理单个域名的所有DNS记录"""
    records = get_domain_records(domain)
    for record in records:
        ip = record['Value']
        if not check_port(api_url, ip):
            logger.error(f"所有尝试失败，端口在 {ip} 上未开放，删除记录：{record['RecordId']}")
            delete_dns_record(record['RecordId'])

if __name__ == "__main__":
    # 示例：请替换以下变量值
    api_url = "<your-api-url>"
    domains = ["example.com", "anotherexample.com"]  # 需要检查的域名列表
    for domain in domains:
        process_domain_records(api_url, domain)
