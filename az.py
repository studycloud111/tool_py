import socket
import time
import uuid
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient


def connect(ip):
    for i in range(2):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sc:
                sc.settimeout(10)
                if sc.connect_ex((ip, 22)) == 0:
                    sc.shutdown(socket.SHUT_RDWR)
                    return False
        except:
            pass
    return True


azure_vms = []

with open('azure_config.txt', 'r') as f:
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

while True:
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

                fqdn = public_ip.dns_settings.fqdn if public_ip.dns_settings else None

                if not fqdn:
                    random_label = "a" + str(uuid.uuid4()).split('-')[0][:15]
                    public_ip.dns_settings = {
                        'domain_name_label': random_label
                    }
                    public_ip = azure['network_client'].public_ip_addresses.begin_create_or_update(
                        azure['resource_group'], public_ip_name, public_ip).result()
                    fqdn = public_ip.dns_settings.fqdn

                if connect(public_ip_address):
                    print(vm_name, public_ip_address, 'change ip')
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
                    fqdn = updated_public_ip.dns_settings.fqdn if updated_public_ip.dns_settings else None
                    print(f"New IP Address for {vm_name}: {updated_ip_address}, FQDN: {fqdn}")

                else:
                    print(vm_name, public_ip_address, 'connect success, FQDN：' + fqdn)
            except Exception as e:
                print(f"Error with VM {vm_name}: {e}")

    time.sleep(10)

tenant_id,client_id,client_secret,subscription_id,resource_group,region,vm_name1,vm_name2,...
