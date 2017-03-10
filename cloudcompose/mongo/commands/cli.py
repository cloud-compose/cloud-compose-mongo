import click
from cloudcompose.mongo.controller import Controller
from cloudcompose.config import CloudConfig
from cloudcompose.exceptions import CloudComposeException

@click.group()
def cli():
    pass

@cli.command()
@click.option('--use-snapshots/--no-use-snapshots', default=True, help="Use snapshots to initialize volumes with existing data")
@click.option('--upgrade-image/--no-upgrade-image', default=False, help="Upgrade the image to the newest version instead of keeping the cluster consistent")
@click.option('--snapshot-cluster', help="Cluster name to use for snapshot retrieval. It defaults to the current cluster name.")
@click.option('--snapshot-time', help="Use a snapshot on or before this time. It defaults to the current time")
def up(use_snapshots, upgrade_image, snapshot_cluster, snapshot_time):
    """
    upgrades an exist cluster
    """
    try:
        cloud_config = CloudConfig()
        controller = Controller(cloud_config, use_snapshots=use_snapshots, upgrade_image=upgrade_image,
                                snapshot_cluster=snapshot_cluster, snapshot_time=snapshot_time)
        controller.cluster_up()
    except CloudComposeException as ex:
        print ex.message

@cli.command()
@click.option('--force/--no-force', default=False, help="Force the cluster to go down even if terminate protection is enabled")
def down(force):
    """
    destroys an existing cluster
    """
    try:
        cloud_config = CloudConfig()
        controller = Controller(cloud_config)
        controller.cluster_down(force)
    except CloudComposeException as ex:
        print ex.message

@cli.command()
@click.option('--user', default='admin', help="Mongo user")
@click.option('--password', help="Mongo password")
@click.option('--use-snapshots/--no-use-snapshots', default=True, help="Use snapshots to initialize volumes with existing data")
@click.option('--upgrade-image/--no-upgrade-image', default=False, help="Upgrade the image to the newest version instead of keeping the cluster consistent")
@click.option('--single-step/--no-single-step', default=False, help="Perform only one upgrade step and then exit")
def upgrade(user, password, use_snapshots, upgrade_image, single_step):
    """
    upgrades an exist cluster
    """
    try:
        cloud_config = CloudConfig()
        controller = Controller(cloud_config, use_snapshots=use_snapshots, upgrade_image=upgrade_image, user=user, password=password)
        controller.cluster_upgrade(single_step)
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
        controller = Controller(cloud_config, user=user, password=password)
        _, msg_list = controller.cluster_health()
        print '%s' % '\n'.join(msg_list)
    except CloudComposeException as ex:
        print ex.message
