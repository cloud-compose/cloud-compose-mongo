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

class CloudController:
    def __init__(self, cloud_config, ec2_client=None):
        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)
        self.cloud_config = cloud_config
        self.config_data = cloud_config.config_data('cluster')
        self.aws = self.config_data['aws']
        self.ec2 = ec2_client or self._get_ec2_client()

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def servers(self):
        return [node['ip'] for node in self.aws.get('nodes', [])]

    def upgrade(self):
        #TODO
        servers = self.servers()
        #instance_ids = self._instance_ids_from_private_ip(ips)
        #if len(instance_ids) > 0:
        #    self._disable_terminate_protection(instance_ids)
        #    self._ec2_terminate_instances(InstanceIds=instance_ids)
        #    print 'terminated %s' % ','.join(instance_ids)

    def _disable_terminate_protection(self, instance_ids):
        for instance_id in instance_ids:
            self._ec2_modify_instance_attribute(InstanceId=instance_id, DisableApiTermination={"Value": False})

    def _instance_ids_from_private_ip(self, ips):
        instance_ids = []
        filters = [
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "private-ip-address", "Values": ips}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                if 'InstanceId' in instance:
                    instance_ids.append(instance['InstanceId'])

        return instance_ids

    #TODO wait for terminating
    def _wait_for_running(self, instance_id):
        status = 'pending'
        sys.stdout.write("%s is pending start" % instance_id)
        sys.stdout.flush()
        while status == 'pending':
            status = self._instance_status(instance_id)
            time.sleep(1)
            sys.stdout.write('.')
            sys.stdout.flush()
        print ""

    def _instance_status(self, instance_id):
        filters = [
            {
                "Name": "instance-id",
                "Values": [instance_id]
            }
        ]
        instances = self._ec2_describe_instances(Filters=filters)["Reservations"]
        if len(instances) != 1:
            raise Exception("Expected one instance for %s and got %s" % (instance_id, len(instances)))
        return instances[0]["Instances"][0]["State"]["Name"]

    def _is_retryable_exception(exception):
        return not isinstance(exception, botocore.exceptions.ClientError)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_terminate_instances(self, **kwargs):
        return self.ec2.terminate_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_instances(self, **kwargs):
        return self.ec2.describe_instances(**kwargs)
