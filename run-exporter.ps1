$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-QuotedArgument {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Test-RequiresAdministrator {
    param([string[]]$Arguments)

    if ($Arguments.Count -eq 0) {
        return $true
    }
    if ($Arguments -contains '--help' -or $Arguments -contains '-h') {
        return $false
    }
    if ($Arguments -contains '--live') {
        return $true
    }

    foreach ($arg in $Arguments) {
        if (-not $arg.StartsWith('-')) {
            return $false
        }
    }
    return $true
}

if ((Test-RequiresAdministrator -Arguments $args) -and -not (Test-IsAdministrator)) {
    Write-Host 'Administrator permission is required for live packet capture.'
    Write-Host 'Windows will show a UAC prompt so the exporter can listen to game network traffic.'
    Write-Host ''
    $answer = Read-Host 'Continue and request administrator access? (Y/N)'
    if ($answer -notin @('Y', 'y', 'Yes', 'yes')) {
        Write-Host 'Cancelled. Run again when you are ready.'
        exit 1
    }
    Write-Host 'Requesting administrator access...'

    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-NoExit',
        '-File', (ConvertTo-QuotedArgument $PSCommandPath)
    )

    foreach ($arg in $args) {
        $arguments += ConvertTo-QuotedArgument $arg
    }

    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList ($arguments -join ' ')
    exit
}

function Get-PythonCommand {
    $python = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $py = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, '-3')
    }

    throw 'Python 3.10 or newer is required. Install Python, then run this script again.'
}

$pythonCommand = @(Get-PythonCommand)
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'

$pythonExe = $pythonCommand[0]
if ($pythonCommand.Count -gt 1) {
    & "$pythonExe" $pythonCommand[1] -m nte_history_exporter.cli @args
} else {
    & "$pythonExe" -m nte_history_exporter.cli @args
}
