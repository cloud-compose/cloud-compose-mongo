from os import environ
import sys
from os.path import abspath, dirname, join, isfile
import logging
from cloudcompose.exceptions import CloudComposeException
from cloudcompose.util import require_env_var
import boto3
import botocore
from time import sleep
import time, datetime
from retrying import retry
from pprint import pprint
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure
from urllib import quote_plus
from pprint import pprint
from workflow import UpgradeWorkflow, Server
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.exceptions import CloudComposeException

class Controller(object):
    def __init__(self, cloud_config, use_snapshots=None, upgrade_image=None, user=None, password=None):
        logging.basicConfig(level=logging.ERROR)
        if user:
            self.user = quote_plus(user)
        if password:
            self.password = quote_plus(password)
        self.logger = logging.getLogger(__name__)
        self.cloud_config = cloud_config
        self.use_snapshots = use_snapshots
        self.upgrade_image = upgrade_image
        self.config_data = cloud_config.config_data('cluster')
        self.aws = self.config_data['aws']
        self.ec2 = self._get_ec2_client()

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def cluster_up(self):
        ci = CloudInit()
        cloud_controller = CloudController(self.cloud_config)
        cloud_controller.up(ci, self.use_snapshots, self.upgrade_image)

    def cluster_upgrade(self, single_step):
        servers = self.servers()
        workflow = UpgradeWorkflow(self, self.config_data['name'], servers)
        if single_step:
            workflow.step()
        else:
            while workflow.step():
                sys.stdout.write('.')
                sys.stdout.flush()
                sleep(10)

    def cluster_health(self):
        msg_list = []
        mongodb_health, mongodb_msg = self._repl_set_health(27018, 'mongodb')
        configdb_health, configdb_msg = self._repl_set_health(27019, 'configdb')
        msg_list.append(mongodb_msg)
        msg_list.append(configdb_msg)
        return mongodb_health and configdb_health, msg_list

    def _repl_set_health(self, port, node_type):
        unhealthy_nodes, healthy_nodes = self._repl_set_unhealthy_nodes(self._repl_set_status(port))
        if len(unhealthy_nodes) == 0:
            if len(healthy_nodes) == 3:
                msg = '%s is HEALTHY' % node_type
                return True, msg
            else:
                msg = '%s is SICK because none of the nodes are healthy' % (node_type)
                return False, msg
        else:
            msg = '%s is SICK because of the following nodes: %s' % (node_type, ' '.join(unhealthy_nodes))
            return False, msg

    def _repl_set_unhealthy_nodes(self, repl_status):
        unhealthy_nodes = []
        healthy_nodes = []
        for member in repl_status.get('members', []):
            # see https://docs.mongodb.com/manual/reference/replica-states/ for details on state numbers
            node_name = member['name'].split(':')[0]
            if member.get('state', 6) in [1, 2, 7, 10]:
                healthy_nodes.append(node_name)
            else:
                unhealthy_nodes.append(node_name)

        return unhealthy_nodes, healthy_nodes

    def server_ips(self):
        return [node['ip'] for node in self.aws.get('nodes', [])]

    def servers(self):
        servers = []
        primary_instance_name = self._primary_instance_name()
        primary_server = None

        for server_ip in self.server_ips():
            instance_id, instance_name = self._instance_from_private_ip(server_ip)
            server = Server(private_ip=server_ip, instance_id=instance_id)
            if primary_instance_name == instance_name:
                primary_server = server
            else:
                servers.append(server)

        # upgrade the primary last
        if primary_server:
            servers.append(primary_server)
        return servers

    def _primary_instance_name(self):
        repl_status = self._repl_set_status(27018)
        primary_node_name = None
        primary_instance_name = None
        for member in repl_status.get('members', []):
            node_name = member['name'].split(':')[0]
            node_num = node_name[4:]
            if member.get('state', 6) == 1:
                primary_node_name = node_name
                primary_instance_name = '%s-%s' % (self.config_data['name'], node_num)

        repl_status = self._repl_set_status(27019)
        for member in repl_status.get('members', []):
            node_name = member['name'].split(':')[0]
            if member.get('state', 6) == 1:
                if node_name != primary_node_name:
                    raise CloudComposeException('ERROR: configdb and mongodb must be PRIMARY on the same EC2 instance before the upgrade can proceed. Use rs.stepDown() until the same EC2 instance is PRIMARY for both configdb and mongodb')

        return primary_instance_name

    def _repl_set_status(self, port):
        for server_ip in self.server_ips():
            try:
                client = MongoClient('mongodb://%s:%s@%s:%s' % (self.user, self.password, server_ip, port), serverselectiontimeoutms=3000)
                return client.admin.command('replSetGetStatus')
            except OperationFailure:
                continue
            except ServerSelectionTimeoutError:
                continue
        return {}

    def instance_terminate(self, instance_id):
        self._disable_terminate_protection(instance_id)
        self._ec2_terminate_instances(InstanceIds=[instance_id])

    def instance_by_private_ip(self, private_ip):
        filters = [
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'private-ip-address', 'Values': [private_ip]}
        ]
        instances = self._ec2_describe_instances(Filters=filters)['Reservations']
        if len(instances) != 1:
            return None, None
        instance = instances[0]['Instances'][0]
        return instance['InstanceId'], instance['State']['Name']

    def instance_status(self, instance_id):
        filters = [{ 'Name': 'instance-id', 'Values': [instance_id] }]
        instances = self._ec2_describe_instances(Filters=filters)['Reservations']
        if len(instances) != 1:
            raise Exception('Expected one instance for %s and got %s' % (instance_id, len(instances)))
        return instances[0]['Instances'][0]['State']['Name']

    def _disable_terminate_protection(self, instance_id):
        self._ec2_modify_instance_attribute(InstanceId=instance_id, DisableApiTermination={'Value': False})

    def _instance_from_private_ip(self, private_ip):
        instance_id = None
        instance_name = None
        filters = [
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'private-ip-address', 'Values': [private_ip]}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                if 'InstanceId' in instance:
                    instance_id = instance['InstanceId']
                    instance_name = self._get_tag('Name', instance['Tags'])
                    break

        return instance_id, instance_name

    def _get_tag(self, key, tags):
        for tag in tags:
            if tag["Key"] == key:
                return tag["Value"]

    def _is_retryable_exception(exception):
        return not isinstance(exception, botocore.exceptions.ClientError)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_modify_instance_attribute(self, **kwargs):
        return self.ec2.modify_instance_attribute(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_terminate_instances(self, **kwargs):
        return self.ec2.terminate_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_instances(self, **kwargs):
        return self.ec2.describe_instances(**kwargs)
