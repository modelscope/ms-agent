def is_docker_daemon_running():
    """
    Check if the Docker daemon is running.
    """
    import docker

    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False
