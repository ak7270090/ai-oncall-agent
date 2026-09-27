# Deletes the kind cluster (all pods, images loaded into it, and state).
. (Join-Path $PSScriptRoot "common.ps1")

Assert-DockerRunning
Invoke-Native kind @("delete", "cluster", "--name", $Config.ClusterName)
