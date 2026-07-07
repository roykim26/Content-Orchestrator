$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = "http://127.0.0.1:8020/health"
function Test-Health {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

function Resolve-Python {
    $candidates = @(
        "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe",
        "C:\Users\jinlo\AppData\Local\Programs\Python\Python313\python.exe"
    )

    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) {
            continue
        }

        try {
            & $candidate -c "import sqlmodel" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "No Python interpreter with the required dependencies was found."
}

if (Test-Health) {
    Write-Output "Topic Manager is already available at $healthUrl"
    exit 0
}

$python = Resolve-Python
# Start-Process fully detaches the server from the caller so the shell
# command can return as soon as health checks pass.
$process = Start-Process `
    -FilePath $python `
    -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8020" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (Test-Health) {
        Write-Output "Topic Manager started on http://127.0.0.1:8020/topic-manager"
        exit 0
    }

    if ($process.HasExited) {
        throw "Topic Manager exited during startup. Check orchestrator_8020.err.log for details."
    }
}

throw "Topic Manager did not become healthy within the expected time."
