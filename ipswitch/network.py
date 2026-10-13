"""Finn nettverkskort og bytt IP-oppsett på Windows, Linux og macOS."""
import ipaddress
import os
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

import psutil

from .config import Profile, prefix_to_mask

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # ingen blinkende konsollvinduer
WIRELESS = ("wi-fi", "wifi", "wireless", "wlan", "802.11")


class NetworkError(Exception):
    pass


@dataclass
class Adapter:
    name: str
    description: str
    physical: bool
    up: bool

    @property
    def wireless(self) -> bool:
        text = f"{self.name} {self.description}".lower()
        return self.name.startswith("wl") or any(w in text for w in WIRELESS)

    def label(self) -> str:
        return f"{self.name}  –  {self.description}" if self.description else self.name


# ---------- Finne nettverkskort ----------

def _windows_hardware() -> dict[str, tuple[str, bool]]:
    """Navn -> (beskrivelse, fysisk) fra registeret. Raskt og uavhengig av språk."""
    import winreg
    cls_path = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"
    net_path = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"
    result = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cls_path) as cls:
        for i in range(winreg.QueryInfoKey(cls)[0]):
            try:
                with winreg.OpenKey(cls, winreg.EnumKey(cls, i)) as key:
                    guid = winreg.QueryValueEx(key, "NetCfgInstanceId")[0]
                    desc = winreg.QueryValueEx(key, "DriverDesc")[0]
                    flags = winreg.QueryValueEx(key, "Characteristics")[0]
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{net_path}\{guid}\Connection") as key:
                    name = winreg.QueryValueEx(key, "Name")[0]
            except OSError:
                continue
            physical = bool(flags & 0x4) and "loopback" not in desc.lower()  # 0x4 = NCF_PHYSICAL
            result[name] = (desc, physical)
    return result


def _windows_dhcp_enabled(adapter: str) -> bool:
    """Om DHCP allerede er på (netsh gir feil hvis man slår det på to ganger)."""
    import winreg
    net_path = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"
    tcpip_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, net_path) as net:
        for i in range(winreg.QueryInfoKey(net)[0]):
            guid = winreg.EnumKey(net, i)
            try:
                with winreg.OpenKey(net, rf"{guid}\Connection") as key:
                    if winreg.QueryValueEx(key, "Name")[0] != adapter:
                        continue
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{tcpip_path}\{guid}") as key:
                    return winreg.QueryValueEx(key, "EnableDHCP")[0] == 1
            except OSError:
                continue
    return False


def _mac_services() -> dict[str, str]:
    """Enhet (en0) -> tjenestenavn (Wi-Fi), som networksetup trenger."""
    out = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True).stdout
    services, port = {}, None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and port:
            services[line.split(":", 1)[1].strip()] = port
    return services


def list_adapters(show_all: bool = False) -> list[Adapter]:
    """Kablede kort først, deretter trådløse; tilkoblede før frakoblede."""
    stats = psutil.net_if_stats()
    if sys.platform == "win32":
        hardware = _windows_hardware()
    elif sys.platform == "darwin":
        hardware = {dev: (port, True) for dev, port in _mac_services().items()}
    else:
        hardware = {n: ("", os.path.exists(f"/sys/class/net/{n}/device")) for n in stats}

    adapters = []
    for name, st in stats.items():
        desc, physical = hardware.get(name, ("", False))
        if physical or show_all:
            adapters.append(Adapter(name, desc, physical, st.isup))
    adapters.sort(key=lambda a: (not a.physical, a.wireless, not a.up, a.name.lower()))
    return adapters


def is_up(adapter: str) -> bool:
    stats = psutil.net_if_stats().get(adapter)
    return bool(stats and stats.isup)


def current_ipv4(adapter: str) -> list[str]:
    """IPv4-adressene på kortet akkurat nå, som 'ip/prefiks'."""
    result = []
    for addr in psutil.net_if_addrs().get(adapter, []):
        if addr.family == socket.AF_INET:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{addr.netmask}").prefixlen if addr.netmask else 32
            result.append(f"{addr.address}/{prefix}")
    return result


# ---------- Kommandoer (rene funksjoner, enkle å teste) ----------

def windows_commands(adapter: str, p: Profile) -> list[list[str]]:
    base = ["netsh", "interface", "ipv4"]
    name = f"name={adapter}"
    if p.mode == "dhcp":
        cmds = [base + ["set", "address", name, "source=dhcp"]]
    else:
        cmds = [base + ["set", "address", name, "source=static", f"address={p.ip}",
                        f"mask={prefix_to_mask(p.prefix)}", f"gateway={p.gateway or 'none'}"]]
    if p.dns:
        cmds.append(base + ["set", "dnsservers", name, "source=static", f"address={p.dns[0]}",
                            "register=primary", "validate=no"])
        for i, dns in enumerate(p.dns[1:], start=2):
            cmds.append(base + ["add", "dnsservers", name, f"address={dns}", f"index={i}", "validate=no"])
    elif p.mode == "dhcp":
        cmds.append(base + ["set", "dnsservers", name, "source=dhcp"])
    else:
        cmds.append(base + ["set", "dnsservers", name, "source=static", "address=none"])
    return cmds


def linux_commands(connection: str, p: Profile) -> list[list[str]]:
    mod = ["nmcli", "connection", "modify", connection]
    dns = ",".join(p.dns)
    if p.mode == "dhcp":
        mod += ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", dns]
    else:
        mod += ["ipv4.method", "manual", "ipv4.addresses", f"{p.ip}/{p.prefix}",
                "ipv4.gateway", p.gateway, "ipv4.dns", dns]
    return [mod, ["nmcli", "connection", "up", connection]]


def mac_commands(service: str, p: Profile) -> list[list[str]]:
    if p.mode == "dhcp":
        cmds = [["networksetup", "-setdhcp", service]]
    else:
        cmds = [["networksetup", "-setmanual", service, p.ip, prefix_to_mask(p.prefix), p.gateway]]
    return cmds + [["networksetup", "-setdnsservers", service, *(p.dns or ["empty"])]]


# ---------- Bytte ----------

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW)


def _output(r: subprocess.CompletedProcess) -> str:
    encoding = "oem" if sys.platform == "win32" else "utf-8"
    return (r.stdout + r.stderr).decode(encoding, "replace").strip()


def is_admin() -> bool:
    if sys.platform == "win32":
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


def apply(adapter: str, p: Profile) -> str:
    """Bytter oppsett og returnerer en kort beskrivelse. Gir NetworkError ved feil."""
    if sys.platform == "win32":
        if not is_admin():
            raise NetworkError("Mangler administratortilgang. Start IP Switch på nytt og svar Ja på spørsmålet om å tillate endringer.")
        cmds = windows_commands(adapter, p)
        if p.mode == "dhcp" and _windows_dhcp_enabled(adapter):
            cmds = cmds[1:]  # DHCP er allerede på; oppdater bare DNS
    elif sys.platform == "darwin":
        service = _mac_services().get(adapter)
        if not service:
            raise NetworkError(f"Fant ikke nettverkstjenesten for {adapter}.")
        cmds = mac_commands(service, p)
        if not is_admin():  # én passorddialog for alle kommandoene
            script = " && ".join(shlex.join(c) for c in cmds).replace("\\", "\\\\").replace('"', '\\"')
            cmds = [["osascript", "-e", f'do shell script "{script}" with administrator privileges']]
    else:
        r = _run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", adapter])
        connection = _output(r) if r.returncode == 0 else ""
        if connection in ("", "--"):
            raise NetworkError(f"Fant ingen aktiv NetworkManager-tilkobling på {adapter}.")
        cmds = linux_commands(connection, p)

    for cmd in cmds:
        r = _run(cmd)
        if r.returncode != 0 and sys.platform.startswith("linux") and not is_admin():
            r = _run(["pkexec", *cmd])  # be om passord hvis polkit nekter
        if r.returncode != 0:
            raise NetworkError(_output(r) or f"Kommandoen feilet: {' '.join(cmd)}")

    if p.mode == "static":
        # Vent til Windows/OS-et faktisk har tatt i bruk adressen.
        wanted = f"{p.ip}/{p.prefix}"
        for _ in range(20):
            if wanted in current_ipv4(adapter):
                break
            time.sleep(0.25)
        return wanted
    return "DHCP"
