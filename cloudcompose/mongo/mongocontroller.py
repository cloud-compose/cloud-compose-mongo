from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from urllib import quote_plus
from pprint import pprint

class MongoController:
    def __init__(self, servers, user, password):
        self.user = quote_plus(user)
        self.password = quote_plus(password)
        self.servers = servers

    def health(self):
        self._repl_set_health(27018, 'mongodb')
        self._repl_set_health(27019, 'configdb')

    def _repl_set_health(self, port, node_type):
        unhealthy_nodes = self._repl_set_unhealthy_nodes(self._repl_set_status(port))
        if len(unhealthy_nodes) == 0:
            print '%s is HEALTHY' % node_type
            return True
        else:
            print '%s is SICK because of the following nodes: %s' % (node_type, ' '.join(unhealthy_nodes))
            return False

    def _repl_set_unhealthy_nodes(self, repl_status):
        unhealthy_nodes = []
        for member in repl_status.get('members', []):
            # see https://docs.mongodb.com/manual/reference/replica-states/ for details on state numbers
            if member.get('state', 6) not in [1, 2, 7, 10]:
                node_name = member['name'].split(':')[0]
                unhealthy_nodes.append(node_name)

        return unhealthy_nodes

    def _repl_set_status(self, port):
        for server in self.servers:
            try:
                client = MongoClient('mongodb://%s:%s@%s:%s' % (self.user, self.password, server, port), serverselectiontimeoutms=3000)
                return client.admin.command('replSetGetStatus')
            except ServerSelectionTimeoutError:
                continue

