import boto3
import logging
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# 配置日志记录，包括时间戳、日志级别和消息
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def read_credentials(filename):
    """从指定文件中读取AWS凭证(access_key_id和secret_access_key)。"""
    with open(filename, 'r') as file:
        # 读取第一行并分割为access_key_id和secret_access_key
        access_key_id, secret_access_key = file.readline().strip().split(',')
        return access_key_id, secret_access_key

def check_vcpu_quota(region_name, required_vcpus=8):
    """检查指定地区的EC2 vCPU配额是否满足要求"""
    client = boto3.client('service-quotas', region_name=region_name)
    try:
        # 示例：查询按需标准（A、C、D、H、I、M、R、T、Z）实例的vCPU配额
        response = client.get_service_quota(
            ServiceCode='ec2',
            QuotaCode='L-1216C47A'  # 此配额代码为按需实例vCPU配额，可能需要调整
        )
        quota_value = response['Quota']['Value']
        logging.info(f"Current vCPU quota in {region_name}: {quota_value}")
        return quota_value >= required_vcpus
    except Exception as e:
        logging.error(f"Failed to check vCPU quota in {region_name}: {e}")
        return False

def create_key_pair(client):
    """在AWS中创建新的SSH密钥对，并返回密钥对名称。"""
    # 使用UUID生成唯一的密钥对名称
    key_pair_name = f"key-pair-{uuid4()}"
    try:
        # 创建密钥对
        key_pair = client.create_key_pair(keyPairName=key_pair_name)
        logging.info(f"已创建密钥对: {key_pair}")
        # 注意：这里只返回密钥对名称，实际应用中还需处理私钥的保存
        return key_pair
    except Exception as e:
        logging.error(f"创建密钥对失败: {e}")
        return None

def open_all_ports(client, instance_name):
    """为指定的LightSail实例开放所有端口"""
    try:
        # 开放所有TCP和UDP端口
        client.put_instance_public_ports(
            instanceName=instance_name,
            portInfos=[
                {'fromPort': 0, 'toPort': 65535, 'protocol': 'tcp'},
                {'fromPort': 0, 'toPort': 65535, 'protocol': 'udp'}
            ]
        )
        logging.info(f"已为实例: {instance_name} 开放所有端口")
    except Exception as e:
        logging.error(f"开放所有端口失败 {instance_name}: {e}")

def create_lightsail_instance(client, instance_prefix, region, index, user_data):
    """创建一个LightSail实例，并返回实例ID。包含重试逻辑。"""
    # 生成实例名称，基于前缀、地区和索引
    # 在实例名称中使用随机字符串部分
    random_part = uuid4().hex[:8]  # 生成8字符长的随机字符串
    instance_name = f"{instance_prefix}-{random_part}-{index}"  # 使用随机部分构造实例名称
    # 为每个实例动态创建新的密钥对
    key_pair_name = create_key_pair(client)
    if not key_pair_name:
        return None

    # 尝试创建实例，最多重试3次
    for attempt in range(3):
        try:
            # 调用API创建LightSail实例
            response = client.create_instances(
                instanceNames=[instance_name],
                availabilityZone=f"{region}a",
                blueprintId="debian_10",  # Debian系统的蓝图ID
                bundleId="nano_2_0",  # 实例套餐
                keyPairName=key_pair_name,  # 使用新创建的密钥对
                userData=user_data  # 用户数据，用于实例启动时执行的脚本
            )
            # 获取并返回创建的实例ID
            instance_id = response['operations'][0]['resourceName']
            logging.info(f"Created instance {instance_id} in {region}.")
            # 实例创建成功后，开放所有端口
            open_all_ports(client, instance_name)
            return instance_id
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} failed to create instance in '{region}': {e}")
            time.sleep(2 ** attempt)  # 指数退避策略等待
    return None


def worker(credentials, region, count, user_data_script):
    """为指定地区并发创建多个实例的工作函数，并仅在实例成功创建时记录实例详情。"""
    # 使用给定的AWS凭证创建会话和客户端
    session = boto3.Session(
        aws_access_key_id=credentials['access_key_id'],
        aws_secret_access_key=credentials['secret_access_key'],
        region_name=region
    )
    client = session.client('lightsail')

    # 创建指定数量的实例，并收集成功创建的实例ID
    successful_instance_ids = []
    for i in range(1, count + 1):
        instance_id = create_lightsail_instance(client, "sl-ls-name", region, i, user_data_script)
        if instance_id:
            successful_instance_ids.append(instance_id)

    # 如果有成功创建的实例，则返回地区和实例ID列表；否则返回None
    if successful_instance_ids:
        return region, successful_instance_ids
    else:
        logging.info(f"No instances were created successfully in {region}.")
        return region, None


def main(credentials_file, user_data_scripts):
    """主函数，读取凭证，为每个地区并发创建实例，并记录实例详情。"""
    # 指定地区和每个地区要创建的实例数量
    regions = ['ap-northeast-1', 'ap-southeast-1']
    instance_counts = [2, 2]

    # 读取AWS凭证
    access_key_id, secret_access_key = read_credentials(credentials_file)
    credentials = {'access_key_id': access_key_id, 'secret_access_key': secret_access_key}

    # 使用线程池并发创建实例
    with ThreadPoolExecutor(max_workers=len(regions)) as executor:
        futures = []
        for region, count in zip(regions, instance_counts):
            # 检查vCPU配额是否满足要求
            if check_vcpu_quota(region, 8):
                # 为每个地区获取对应的用户数据脚本
                user_data_script = user_data_scripts[region]
                # 提交任务到线程池
                futures.append(executor.submit(worker, credentials, region, count, user_data_script))
            else:
                logging.warning(f"vCPU quota in {region} does not meet the requirement. Skipping instance creation.")

        # 等待所有任务完成，并记录实例详情到文件
        for future in as_completed(futures):
            region, instance_ids = future.result()
            if instance_ids:  # 确保存在成功创建的实例
                output_filename = f"instance_details_{region}.csv"
                with open(output_filename, 'a') as file:
                    file.write(f"{access_key_id},{secret_access_key},{region},lightsail,{','.join(instance_ids)}\n")
                logging.info(f"Instance details for region {region} have been saved to {output_filename}.")
            else:
                logging.info(f"No instances to save for region {region}.")


if __name__ == '__main__':
    credentials_file = 'aws.txt'
    user_data_scripts = {
        'ap-northeast-1': "#!/bin/bash\nwget -q --show-progress https://example.com/path/to/hy2jp.sh -O hy2jp.sh && chmod +x hy2jp.sh && bash hy2jp.sh",
        'ap-southeast-1': "#!/bin/bash\nwget -q --show-progress https://example.com/path/to/hy2sg.sh -O hy2sg.sh && chmod +x hy2sg.sh && bash hy2sg.sh"
    }
    main(credentials_file, user_data_scripts)
