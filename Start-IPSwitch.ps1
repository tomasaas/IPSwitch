[CmdletBinding()]
param(
    [switch]$CreateDesktopShortcut,
    [switch]$SetupOnly
)

$ErrorActionPreference = 'Stop'
try {
    $venv = Join-Path $PSScriptRoot '.venv'
    $python = Join-Path $venv 'Scripts\python.exe'
    $pythonw = Join-Path $venv 'Scripts\pythonw.exe'
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    $stamp = Join-Path $venv '.requirements.sha256'

    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'Oppretter Python-miljo ...'
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            & py.exe -3 -m venv $venv
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -m venv $venv
        } else {
            throw 'Installer Python 3.12 eller nyere fra python.org, og start pa nytt.'
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
            throw 'Kunne ikke opprette .venv. Kontroller at Python 3.12 eller nyere er installert.'
        }
    }

    & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Miljoet .venv virker ikke eller bruker for gammel Python. Gi mappen et annet navn og start igjen med Python 3.12 eller nyere installert.'
    }

    . (Join-Path $venv 'Scripts\Activate.ps1')
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash) {
        Write-Host 'Installerer appens avhengigheter (krever internett ved forste oppstart) ...'
        & $python -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) {
            throw 'Installasjonen feilet. Kontroller internettforbindelsen og prov igjen.'
        }
        Set-Content -LiteralPath $stamp -Value $hash -Encoding ASCII
    }

    if ($CreateDesktopShortcut) {
        $desktop = [Environment]::GetFolderPath('DesktopDirectory')
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktop 'IPSwitch.lnk'))
        $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'Start-IPSwitch.ps1') + '"'
        $shortcut.WorkingDirectory = $PSScriptRoot
        $shortcut.IconLocation = (Join-Path $PSScriptRoot 'ipswitch.ico') + ',0'
        $shortcut.Description = 'Start IP Switch'
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        Write-Host 'IPSwitch-snarvei opprettet pa skrivebordet.'
    }

    if (-not $SetupOnly) {
        Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $PSScriptRoot 'main.py') + '"') -WorkingDirectory $PSScriptRoot
    }
} catch {
    Write-Host ("Kunne ikke starte IP Switch: " + $_.Exception.Message) -ForegroundColor Red
    # Also show errors when the desktop shortcut starts PowerShell minimized.
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'IP Switch - oppstartsfeil') | Out-Null
    exit 1
}
