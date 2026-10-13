"""Start ved oppstart: Oppgaveplanlegger (Windows), autostart-fil (Linux), LaunchAgent (macOS)."""
import os
import plistlib
import shlex
import subprocess
import sys

TASK = "IPSwitch"
LINUX_FILE = os.path.expanduser("~/.config/autostart/ipswitch.desktop")
MAC_FILE = os.path.expanduser("~/Library/LaunchAgents/no.ipswitch.plist")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _powershell(script: str) -> None:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        f"$ErrorActionPreference = 'Stop'; {script}"], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("oem", "replace").strip() or "Oppgaveplanleggeren svarte med en feil.")


def command() -> list[str]:
    """Kommandoen som starter appen rett i systemstatusfeltet."""
    if getattr(sys, "frozen", False):  # PyInstaller-exe
        return [sys.executable, "--tray"]
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    python = sys.executable
    if sys.platform == "win32":
        python = python.replace("python.exe", "pythonw.exe")  # uten konsollvindu
    return [python, main, "--tray"]


def is_enabled() -> bool:
    if sys.platform == "win32":
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True, creationflags=NO_WINDOW)
        return r.returncode == 0
    return os.path.exists(MAC_FILE if sys.platform == "darwin" else LINUX_FILE)


def enable() -> None:
    cmd = command()
    if sys.platform == "win32":
        # Oppgaveplanlegger med høyeste rettigheter: admin ved pålogging uten UAC-spørsmål.
        # Standardinnstillingene hindrer start på batteri, så det slås av eksplisitt.
        def q(s):
            return "'" + s.replace("'", "''") + "'"
        _powershell(
            f"$a = New-ScheduledTaskAction -Execute {q(cmd[0])} -Argument {q(subprocess.list2cmdline(cmd[1:]))};"
            '$u = "$env:USERDOMAIN\\$env:USERNAME";'
            "$t = New-ScheduledTaskTrigger -AtLogOn -User $u;"
            "$p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest;"
            "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
            " -ExecutionTimeLimit 0;"
            f"Register-ScheduledTask -TaskName {TASK} -Action $a -Trigger $t -Principal $p -Settings $s -Force"
            " | Out-Null"
        )
    elif sys.platform == "darwin":
        os.makedirs(os.path.dirname(MAC_FILE), exist_ok=True)
        with open(MAC_FILE, "wb") as f:
            plistlib.dump({"Label": "no.ipswitch", "ProgramArguments": cmd, "RunAtLoad": True}, f)
    else:
        os.makedirs(os.path.dirname(LINUX_FILE), exist_ok=True)
        with open(LINUX_FILE, "w", encoding="utf-8") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName=IP Switch\nExec={shlex.join(cmd)}\n")


def disable() -> None:
    if sys.platform == "win32":
        _powershell(f"Unregister-ScheduledTask -TaskName {TASK} -Confirm:$false")
    else:
        path = MAC_FILE if sys.platform == "darwin" else LINUX_FILE
        if os.path.exists(path):
            os.remove(path)
