from pymongo import MongoClient
from urllib import quote_plus
from pprint import pprint

class MongoController:
    def __init__(self, servers, user, password):
        self.user = quote_plus(user)
        self.password = quote_plus(password)
        self.servers = servers

    def health(self):
        print 'mongodb is healthy? %s' % self._repl_health(self._repl_status(27018))
        print 'configdb is healthy? %s' % self._repl_health(self._repl_status(27019))

    def _repl_health(self, repl_status):
        healthy = False
        for member in repl_status.get('members', []):
            healthy = True
            # see https://docs.mongodb.com/manual/reference/replica-states/ for details on state numbers
            if member.get('state', 6) not in [1, 2, 7, 10]:
                healthy = False
                break

        return healthy

    def _repl_status(self, port):
        for server in self.servers:
            client = MongoClient('mongodb://%s:%s@%s:%s' % (self.user, self.password, server, port))
            return client.admin.command('replSetGetStatus')

