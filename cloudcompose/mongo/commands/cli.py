import click
from cloudcompose.mongo.cloudcontroller import CloudController
from cloudcompose.mongo.mongocontroller import MongoController
from cloudcompose.config import CloudConfig
from cloudcompose.exceptions import CloudComposeException

@click.group()
def cli():
    pass

@cli.command()
@click.option('--use-snapshots/--no-use-snapshots', default=True, help="Use snapshots to initialize volumes with existing data")
@click.option('--upgrade-image/--no-upgrade-image', default=False, help="Upgrade the image to the newest version instead of keeping the cluster consistent")
def upgrade(use_snapshots, upgrade_image):
    """
    upgrades an exist cluster
    """
    try:
        #TODO
        raise "not implemented"
    except CloudComposeException as ex:
        print ex.message

@cli.command()
@click.option('--user', default='admin', help="Mongo user")
@click.option('--password', help="Mongo password")
def health(user, password):
    """
    destroys an existing cluster
    """
    try:
        cloud_config = CloudConfig()
        cloud_controller = CloudController(cloud_config)
        servers = cloud_controller.servers()
        mongo_controller = MongoController(servers, user, password)
        health_status = mongo_controller.health()
    except CloudComposeException as ex:
        print ex.message
