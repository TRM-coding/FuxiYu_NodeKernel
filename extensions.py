import docker
docker_client=None


def init_docker():
    global docker_client
    docker_client = docker.from_env()
