# Run from PowerShell. Press Q or Ctrl+C to stop both services.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.local\analyst\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Analyst Python environment is missing. See docs/analyst-usage.md for setup.'
}

# Check both ports before the API creates a new local session token.
foreach ($port in 8000, 8501) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
    try {
        $listener.ExclusiveAddressUse = $true
        $listener.Start()
    } catch {
        throw "Cannot start the analyst because local port $port is unavailable."
    } finally {
        $listener.Stop()
    }
}

$runService = {
    param($root, $interpreter, $serviceArgs)
    Set-Location -LiteralPath $root
    & $interpreter @serviceArgs 2>&1 | ForEach-Object { $_.ToString() }
    exit $LASTEXITCODE
}
$jobs = @()
try {
    $jobs += Start-Job -Name 'Analyst API' -ScriptBlock $runService -ArgumentList $projectRoot, $python, @('-m', 'app.api.main')
    $uiArgs = @('-m', 'streamlit', 'run', 'app/frontend/main.py', '--server.address=127.0.0.1',
                '--server.port=8501', '--server.headless=true', '--browser.gatherUsageStats=false')
    $jobs += Start-Job -Name 'Analyst UI' -ScriptBlock $runService -ArgumentList $projectRoot, $python, $uiArgs
    Write-Host 'Starting the analyst at http://127.0.0.1:8501. Press Q or Ctrl+C here to stop both services.'
    while ($true) {
        foreach ($job in $jobs) {
            Receive-Job -Job $job -ErrorAction Continue
            if ($job.State -ne 'Running') {
                throw "$($job.Name) exited. See the service output above."
            }
        }
        if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and [Console]::KeyAvailable) {
            if ([Console]::ReadKey($true).Key -eq 'Q') { break }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    foreach ($job in $jobs) {
        Remove-Job -Job $job -Force
    }
}
