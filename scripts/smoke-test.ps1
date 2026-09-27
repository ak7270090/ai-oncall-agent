# Places an order through order-service, which calls user-service and payment-service
# inside the cluster. Exercises Service DNS, ConfigMap URLs and the payment Secret.
. (Join-Path $PSScriptRoot "common.ps1")

$portForward = Start-Process kubectl -PassThru -WindowStyle Hidden -ArgumentList @(
    "port-forward", "--namespace", $Config.Namespace,
    "service/$($Config.SmokeTestService)", "$($Config.SmokeTestLocalPort):$($Config.SmokeTestServicePort)"
)
try {
    $baseUrl = "http://127.0.0.1:$($Config.SmokeTestLocalPort)"
    $deadline = (Get-Date).AddSeconds(15)
    while ($true) {
        try { Invoke-RestMethod "$baseUrl/health" | Out-Null; break }
        catch { if ((Get-Date) -gt $deadline) { throw "port-forward to $($Config.SmokeTestService) never came up" }; Start-Sleep -Milliseconds 500 }
    }
    $order = Invoke-RestMethod -Method Post "$baseUrl/orders" -ContentType "application/json" -Body '{"user_id": 1, "amount": 42.5}'
    $order | Format-List
    if ($order.status -ne "confirmed") { throw "unexpected order status: $($order.status)" }
    Write-Host "Smoke test passed."
}
finally {
    Stop-Process -Id $portForward.Id -ErrorAction SilentlyContinue
}
