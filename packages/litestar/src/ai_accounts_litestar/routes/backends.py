from litestar import Controller


class BackendsController(Controller):
    path = "/api/v1/backends"
    tags = ["backends"]
