# Creates the kind cluster (if missing), builds and loads the sample-service images,
# and deploys the manifests. Safe to re-run: it redeploys changed code/manifests.
. (Join-Path $PSScriptRoot "common.ps1")

function Initialize-SecretEnvFile {
    $secretFile = Resolve-RepoPath $Config.SecretEnvFile
    if (Test-Path $secretFile) { return }
    $randomKey = [guid]::NewGuid().ToString("N")
    (Get-Content (Resolve-RepoPath $Config.SecretEnvExample)) `
        -replace "^PAYMENT_API_KEY=.*", "PAYMENT_API_KEY=$randomKey" |
        Set-Content -Encoding ascii $secretFile
    Write-Host "Created $($Config.SecretEnvFile) with a random dev key."
}

function New-ClusterIfMissing {
    $clusters = (Invoke-NativeQuietly kind @("get", "clusters")).Output
    if ($clusters -contains $Config.ClusterName) {
        Write-Host "Cluster '$($Config.ClusterName)' already exists."
        return
    }
    Invoke-Native kind @("create", "cluster", "--name", $Config.ClusterName, "--config", (Resolve-RepoPath $Config.KindConfig))
}

function Get-ManifestImages {
    # The manifests are the single source of truth for image names and tags.
    $rendered = Invoke-Native kubectl @("kustomize", (Resolve-RepoPath $Config.ManifestsDir))
    $rendered | Select-String -Pattern "^\s+image:\s*(\S+)" | ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique
}

function Publish-ServiceImage([string]$Image) {
    $serviceName = $Image.Split(":")[0]
    $context = Resolve-RepoPath (Join-Path $Config.ServicesDir $serviceName)
    Invoke-Native docker @(
        "build", "--quiet",
        "--file", (Resolve-RepoPath $Config.Dockerfile),
        "--build-arg", "APP_ENTRYPOINT=$($Config.ServiceEntrypoint)",
        "--build-arg", "APP_PORT=$($Config.ServicePort)",
        "--tag", $Image,
        $context
    ) | Out-Null
    Invoke-Native kind @("load", "docker-image", $Image, "--name", $Config.ClusterName)
}

Assert-DockerRunning
Initialize-SecretEnvFile
New-ClusterIfMissing
Invoke-Native kubectl @("config", "use-context", "kind-$($Config.ClusterName)")

foreach ($image in Get-ManifestImages) {
    Write-Host "Building and loading $image"
    Publish-ServiceImage $image
}

Invoke-Native kubectl @("apply", "-k", (Resolve-RepoPath $Config.ManifestsDir))
Invoke-Native kubectl @(
    "wait", "deployment", "--for=condition=Available",
    "--namespace", $Config.Namespace, "--selector", $Config.PartOfLabel, "--timeout", $Config.RolloutTimeout
)
Invoke-Native kubectl @("get", "deployments,replicasets,pods,services", "--namespace", $Config.Namespace)
