class FakeOperations:
    """Records the changes it is asked to make instead of making them (tests, `make up`)."""

    def __init__(self):
        self.performed: list[str] = []

    def restart_deployment(self, namespace: str, name: str) -> str:
        return self._record(f"Restarted deployment {name}.")

    def scale_deployment(self, namespace: str, name: str, replicas: int) -> str:
        return self._record(f"Scaled deployment {name} to {replicas} replicas.")

    def rollback_deployment(self, namespace: str, name: str, revision: int) -> str:
        return self._record(f"Rolled back deployment {name} to the pod template of revision {revision}.")

    def _record(self, done: str) -> str:
        self.performed.append(done)
        return done
