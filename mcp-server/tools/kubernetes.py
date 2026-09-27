from typing import Annotated

from pydantic import Field

from data import fake_cluster
from data.fake_cluster import Service

DEFAULT_LOG_LINES = 20
MAX_LOG_LINES = 200


def list_deployments(namespace: str = "default") -> dict:
    """List deployments in a namespace with image, desired/ready replicas and last rollout time.

    Use this first to see which services exist and whether any rollout happened recently.
    """
    deployments = [d for d in fake_cluster.DEPLOYMENTS if d["namespace"] == namespace]
    return {"namespace": namespace, "deployments": deployments}


def get_pod_status(service: Service) -> dict:
    """Get the pods backing a service: phase, readiness, status reason and restart count.

    A high restart count or a CrashLoopBackOff status means the container keeps dying;
    check get_logs next.
    """
    return {"service": service, "pods": fake_cluster.PODS[service]}


def get_logs(
    service: Service,
    lines: Annotated[
        int, Field(ge=1, le=MAX_LOG_LINES, description="How many recent lines to return")
    ] = DEFAULT_LOG_LINES,
) -> dict:
    """Get the most recent log lines for a service (newest last)."""
    return {"service": service, "lines": fake_cluster.LOGS[service][-lines:]}


KUBERNETES_TOOLS = (list_deployments, get_pod_status, get_logs)
