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
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure, AutoReconnect
from urllib import quote_plus
from pprint import pprint
from workflow import UpgradeWorkflow, Server
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.exceptions import CloudComposeException
from base64 import b64decode

class Controller(object):
    def __init__(self, cloud_config, use_snapshots=None, upgrade_image=None, user=None, password=None, snapshot_cluster=None, snapshot_time=None):
        logging.basicConfig(level=logging.ERROR)
        self.config_data = cloud_config.config_data('cluster')
        self.kms = self._get_kms_client()
        if password is None:
            password = self._lookup_password()
        if user:
            self.user = quote_plus(user)
        if password:
            self.password = quote_plus(password)
        self.logger = logging.getLogger(__name__)
        self.cloud_config = cloud_config
        self.use_snapshots = use_snapshots
        self.upgrade_image = upgrade_image
        self.snapshot_cluster = snapshot_cluster
        self.snapshot_time = snapshot_time
        self.aws = self.config_data['aws']
        self.ec2 = self._get_ec2_client()

    def _lookup_password(self):
        encrypted_password = self.config_data.get('secrets', {}).get('MONGODB_ADMIN_PASSWORD')
        if encrypted_password:
            return self._kms_decrypt(CiphertextBlob=b64decode(encrypted_password)).get('Plaintext')

        return None

    def _get_kms_client(self):
        return boto3.client('kms', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def cluster_up(self, silent=False):
        ci = CloudInit()
        cloud_controller = CloudController(self.cloud_config, silent=silent)
        cloud_controller.up(ci, self.use_snapshots, self.upgrade_image, self.snapshot_cluster, self.snapshot_time)

    def cluster_down(self, force):
        cloud_controller = CloudController(self.cloud_config)
        cloud_controller.down(force)

    def cluster_upgrade(self, single_step):
        servers, primary_node_name = self.servers()
        workflow = UpgradeWorkflow(self, self.config_data['name'], servers)
        if single_step:
            workflow.step()
        else:
            while workflow.step():
                sleep(10)

    def cluster_health(self):
        msg_list = []
        mongodb_health, mongodb_msg = self._repl_set_health(27018, 'mongodb')
        configdb_health, configdb_msg = self._repl_set_health(27019, 'configdb')
        msg_list.append(mongodb_msg)
        msg_list.append(configdb_msg)
        return mongodb_health and configdb_health, msg_list

    def _repl_set_health(self, port, node_type):
        unhealthy_nodes, secondary_nodes, primary_node = self._repl_set_stats(self._repl_set_status(port))
        if len(unhealthy_nodes) == 0:
            if len(secondary_nodes) >= 2 and primary_node:
                msg = '%s is HEALTHY' % node_type
                return True, msg
            else:
                msg = '%s is SICK because none of the nodes are healthy' % (node_type)
                return False, msg
        else:
            msg = '%s is SICK because of the following nodes: %s' % (node_type, ' '.join(unhealthy_nodes))
            return False, msg

    def _repl_set_stats(self, repl_status):
        unhealthy_nodes = []
        secondary_nodes = []
        primary_node = None
        for member in repl_status.get('members', []):
            # see https://docs.mongodb.com/manual/reference/replica-states/ for details on state numbers
            node_name = member['name'].split(':')[0]
            member_state = member.get('state', 6)
            if member_state == 1:
                primary_node = node_name
            elif member_state == 2:
                secondary_nodes.append(node_name)
            elif member_state not in [1, 2, 7, 10]:
                unhealthy_nodes.append(node_name)

        return unhealthy_nodes, secondary_nodes, primary_node

    def server_ips(self):
        return [node['ip'] for node in self.aws.get('nodes', [])]

    def servers(self):
        servers = []
        primary_instance_name, primary_node_name = self.primary_instance_name()
        primary_server = None

        for server_ip in self.server_ips():
            instance_id, instance_name = self._instance_from_private_ip(server_ip)
            server = Server(private_ip=server_ip, instance_id=instance_id, instance_name=instance_name)
            if primary_instance_name == instance_name:
                primary_server = server
            else:
                servers.append(server)

        # upgrade the primary last
        if primary_server:
            servers.append(primary_server)
        return servers, primary_node_name

    def primary_instance_name(self):
        repl_status = self._repl_set_status(27018)
        primary_node_name = None
        primary_instance_name = None
        for member in repl_status.get('members', []):
            node_name = member['name'].split(':')[0]
            node_num = node_name[4:]
            if member.get('state', 6) == 1:
                primary_node_name = node_name
                primary_instance_name = '%s-%s' % (self.config_data['name'], node_num)

        return primary_instance_name, primary_node_name

    def align_primaries(self):
        msg_prefix = 'ERROR: unable to make the same EC2 instance PRIMARY for both mongodb and configdb because %s'
        mongodb_health, _ = self._repl_set_health(27018, 'mongodb')
        if not mongodb_health:
            raise CloudComposeException(msg_prefix % 'mongodb is SICK')

        configdb_health, _ = self._repl_set_health(27019, 'configdb')
        if not configdb_health:
            raise CloudComposeException(msg_prefix % 'configdb is SICK')

        _, primary_node_name = self.primary_instance_name()
        members = self._repl_set_status(27019).get('members', [])
        for member in members:
            node_name = member['name'].split(':')[0]
            if member.get('state', 6) == 1:
                if node_name != primary_node_name:
                    self._stepdown_configdb(members, node_name, primary_node_name)

    def _stepdown_configdb(self, members, old_primary, new_primary):
        self._freeze_other_secondaries(members, old_primary, new_primary)
        self._elect_new_primary(members, old_primary, new_primary)

    def _freeze_other_secondaries(self, members, old_primary, new_primary):
        for member in members:
            node_name = member['name'].split(':')[0]
            node_num = node_name[4:]
            if member.get('state', 6) == 2 and node_name not in [old_primary, new_primary]:
                self._repl_set_freeze(node_num, 27019)

    def _elect_new_primary(self, members, old_primary, new_primary):
        for member in members:
            node_name = member['name'].split(':')[0]
            node_num = node_name[4:]
            # if this is the current PRIMARY then step down
            if member.get('state', 6) == 1 and node_name not in [new_primary]:
                self._repl_step_down(node_num, 27019)

        # wait for new primary to be elected
        count = 0
        sleep_seconds = 10
        max_sleep_seconds = 120
        while max_sleep_seconds > (sleep_seconds * count):
            configdb_health, _ = self._repl_set_health(27019, 'configdb')
            if configdb_health:
                break
            else:
                time.sleep(sleep_seconds)
                count += 1

    def _repl_set_freeze(self, node_num, port):
        server_ip = self._find_server_by_node_num(node_num)
        client = MongoClient('mongodb://%s:%s@%s:%s' % (self.user, self.password, server_ip, port), serverselectiontimeoutms=3000)
        client.admin.command('replSetFreeze', 60)

    def _repl_step_down(self, node_num, port):
        server_ip = self._find_server_by_node_num(node_num)
        try:
            client = MongoClient('mongodb://%s:%s@%s:%s' % (self.user, self.password, server_ip, port), serverselectiontimeoutms=3000)
            client.admin.command('replSetStepDown', 60)
        except AutoReconnect:
            pass

    def _find_server_by_node_num(self, node_num):
        for node in self.aws.get('nodes', []):
            if int(node['id']) == int(node_num):
                return node['ip']

        return None

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

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _kms_decrypt(self, **kwargs):
        return self.kms.decrypt(**kwargs)
