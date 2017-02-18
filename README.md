# Cloud Compose Mongo plugin
The Cloud Compose Mongo plugin simplifies the process of running MongoDB with Cloud Compose. 

For an example project that uses Cloud Compose see [Docker MongoDB](https://github.com/washingtonpost/docker-mongodb).

## upgrade command
Once you have a running MongoDB cluster using the Cloud Compose Cluster plugin use the following command to upgrade the cluster:
```
cd my-configs
pip install cloud-compose-mongo
cloud-compose mongo upgrade
```
The upgrade command will make sure your replica set is healthy before starting the upgrade. It will start the upgrade with the secondary nodes and finish with the primary node. It assumes that both your configdb and mongodb processes are replica sets. If the primary servers are not the same host, it will step down the configdb until the primary servers are on the same how. 
