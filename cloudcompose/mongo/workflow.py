from os.path import isdir, dirname, isfile
import os
import json

class Server(object):
    INITIAL = 'initial'
    PENDING = 'pending'
    CHECKING = 'checking'
    RUNNING = 'running'
    TERMINATED = 'terminated'
    SHUTTING_DOWN = 'shutting-down'

    def __init__(self, private_ip, instance_id, state=INITIAL, completed=False):
        self.private_ip = private_ip
        self.instance_id = instance_id
        self.state = state
        self.completed = completed

class UpgradeWorkflow(object):
    def __init__(self, controller, cluster_name, servers):
	self.workflow_file = '/tmp/cloud-compose/mongo.upgrade.workflow.%s.json' % cluster_name
        self.controller = controller
        self.curr_index = 0
        workflow = []
        self.workflow = self._load_workflow(servers)

    def step(self):
        if self.curr_index >= len(self.workflow):
            return False

        server =  self.workflow[self.curr_index]

        if server.state == Server.INITIAL or server.state == Server.RUNNING:
            cluster_healthy, msg_list = self.controller.cluster_health()
            if not cluster_healthy:
                print '\n'.join(msg_list)
                return False

        self._next_step()
        if self.curr_index >= len(self.workflow):
            self._delete_workflow()
            return False
        else:
            return True

    def _next_step(self):
        server =  self.workflow[self.curr_index]
        if server.state == Server.INITIAL:
            self.controller.instance_terminate(server.instance_id)
            server.state = Server.SHUTTING_DOWN
            self._save_workflow()
        elif server.state == Server.SHUTTING_DOWN:
            status = self.controller.instance_status(server.instance_id)
            if status == Server.TERMINATED:
                self.controller.cluster_up()
                server.state = Server.PENDING
                self._save_workflow()
        elif server.state in [server.CHECKING, Server.PENDING]:
            instance_id, status = self.controller.instance_by_private_ip(server.private_ip)
            if instance_id is None:
                return
            if status == Server.RUNNING:
                cluster_healthy, _ = self.controller.cluster_health()
                if cluster_healthy:
                    server.state = Server.RUNNING
                    server.completed = True
                    self.curr_index += 1
                else:
                    server.state = Server.CHECKING
                server.instance_id = instance_id
                self._save_workflow()

    def _load_workflow(self, servers):
        workflow = []
        if isfile(self.workflow_file):
            with open(self.workflow_file) as f:
                data = json.load(f)
            for server in data:
                server = Server(server['private_ip'], server['instance_id'], server['state'], server['completed'])
                if server.completed:
                    self.curr_index += 1
                workflow.append(server)
        else:
            workflow.extend(servers)

        return workflow

    def _save_workflow(self):
        workflow_dir = dirname(self.workflow_file)
        if not isdir(workflow_dir):
            os.makedirs(workflow_dir)

        with open(self.workflow_file, 'w') as f:
            json.dump(self.toJSON(), f)

    def toJSON(self):
        workflow_list = []
        for server in self.workflow:
            workflow_list.append({'private_ip': server.private_ip, 'instance_id': server.instance_id,
                                  'state': server.state, 'completed': server.completed})

        return workflow_list

    def _delete_workflow(self):
        if isfile(self.workflow_file):
            os.remove(self.workflow_file)
