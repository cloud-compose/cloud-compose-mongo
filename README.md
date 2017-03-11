# Cloud Compose Mongo plugin
The Cloud Compose Mongo plugin simplifies the process of running MongoDB with Cloud Compose. 

For an example project that uses Cloud Compose see [Docker MongoDB](https://github.com/washingtonpost/docker-mongodb).

Cloud Compose Mongo supports all the standard Cloud Compose Cluster commands like up, down.
## upgrade command
Once you have a running MongoDB cluster using the Cloud Compose Cluster plugin use the following command to upgrade the cluster:
```
cd my-configs
pip install cloud-compose-mongo
cloud-compose mongo upgrade
```
The upgrade command will make sure your replica set is healthy before starting the upgrade. It will start the upgrade with the secondary nodes and finish with the primary node. It assumes that both your configdb and mongodb processes are replica sets. If the primary servers are not the same host, it will step down the configdb until the primary servers are on the same how. 

## health command
The health command checks if the replica set is healthy and then prints the results to the console.
```
cloud-compose mongo health
```

## restoring a database
To restore a database use the standard `up` command to create a new cluster with the `--snapshot-time` option to specifiy which snapshot to use. The `--snapshot-time` option will find the most recent backup that is on or before this time. 
If you are cloning a running cluster, you will need to create a new cluster with a different name and IP addresses. You can then supply the `--snapshot-cluster` option to specify the source cluster name to pull the snapshot from. If you don't supply the `--snapshot-cluster` option it assumes you are restoring from the cluster specified in the cloud-compose.yml.
```
cloud-compose mongo up --snapshot-time '2016-12-21 15:00'
```
