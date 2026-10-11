$ErrorActionPreference = 'Stop'
$anvilProcess = $null
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
try {
    $anvilProcess = Start-Process -FilePath anvil -ArgumentList @('--silent', '--chain-id', '31337', '--port', '8545') -WindowStyle Hidden -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8545' -Method Post -ContentType 'application/json' -Body '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'
            if ($response.result -eq '0x7a69') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Anvil did not become ready on port 8545' }

    $env:FOUNDRY_PROFILE = 'deploy'
    $env:DEMO_OWNER = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
    $env:DEMO_EXECUTOR = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'
    $env:DEMO_APPROVER = '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC'
    $env:DEMO_GUARDIAN = '0x90F79bf6EB2c4f870365E785982E1f101E93b906'
    $env:DEMO_PAYEE = '0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65'
    Push-Location (Join-Path $repoRoot 'contracts')
    forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 --broadcast
    if ($LASTEXITCODE -ne 0) { throw "forge script failed with exit code $LASTEXITCODE" }
    Pop-Location
    Write-Host 'Local deployment manifest: deployments/31337.json'
} finally {
    if ((Get-Location).Path -like (Join-Path $repoRoot 'contracts*')) { Pop-Location }
    if ($null -ne $anvilProcess -and -not $anvilProcess.HasExited) { Stop-Process -Id $anvilProcess.Id -Force }
}
