class Server(object):
    INITIAL = 'initial'
    PENDING = 'pending'
    RUNNING = 'running'
    TERMINATED = 'terminated'
    SHUTTING_DOWN = 'shutting-down'

    def __init__(self, ip, state=INITIAL):
        self.ip = ip
        self.state = state
        self.completed = False

class UpgradeWorkflow(object):
    def __init__(self, controller, server_ips):
        self.controller = controller
        self.curr_index = 0
        workflow = []
        #TODO load saved workflow on startup if it exists. Also set the workflow to the first non-completed server
        for server_ip in server_ips:
            workflow.append(Server(server_ip))
        self.workflow = workflow

    def step(self):
        if self.curr_index >= len(self.workflow):
            return

        server =  self.workflow[self.curr_index]
        status = self.controller.instance_status(server.ip)

        if server.state == Server.INITIAL or server.state == Server.RUNNING:
            cluster_healthy, msg_list = self.controller.cluster_health()
            if not cluster_healthy:
                print '\n'.join(msg_list)
                return

        self._next_step()
        if self.curr_index >= len(self.workflow):
            self._delete_workflow()

    def _next_step(self):
        server =  self.workflow[self.curr_index]
        if server.state == Server.INITIAL:
            self.controller.instance_terminate(server.ip)
            server.state = Server.SHUTTING_DOWN
            self._save_workflow()
        elif server.state == Server.SHUTTING_DOWN:
            status = self.controller.instance_status(server.ip)
            if status == Server.TERMINATED:
                self.controller.cluster_up(server.ip)
                server.state = Server.PENDING
                self._save_workflow()
        elif server.state == Server.PENDING:
            status = self.controller.instance_status(server.ip)
            if status == Server.RUNNING:
                server.state = Server.RUNNING
                server.completed = True
                self.curr_index += 1
                self._save_workflow()

    def _save_workflow(self):
        #TODO save state into json file at each step
        pass

    def _delete_workflow(self):
        #TODO delete workflow file
        pass
