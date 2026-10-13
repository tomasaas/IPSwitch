"""Profiler og innstillinger, lagret som JSON i brukerens konfigmappe."""
import ipaddress
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "IPSwitch")


CONFIG_PATH = os.path.join(config_dir(), "config.json")


@dataclass
class Profile:
    name: str
    mode: str = "dhcp"  # "dhcp" eller "static"
    ip: str = ""
    prefix: int = 24
    gateway: str = ""
    dns: list[str] = field(default_factory=list)
    hotkey: str = ""

    def summary(self) -> str:
        if self.mode == "dhcp":
            return "Automatisk (DHCP)"
        text = f"{self.ip}/{self.prefix}"
        if self.gateway:
            text += f"  →  {self.gateway}"
        return text


@dataclass
class Settings:
    adapter: str = ""
    show_all_adapters: bool = False
    tray: bool = True
    keep_running: bool = True  # fortsett i bakgrunnen når vinduet lukkes
    notifications: bool = True
    advanced: bool = False
    cycle_hotkey: str = ""
    active: dict[str, str] = field(default_factory=dict)  # nettverkskort -> sist brukte profil
    profiles: list[Profile] = field(default_factory=list)


def _known(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def default_settings() -> Settings:
    return Settings(profiles=[Profile("DHCP (automatisk)", hotkey="ctrl+alt+shift+1")])


def load() -> Settings:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        settings = Settings(**_known(Settings, data))
        settings.profiles = [Profile(**_known(Profile, p)) for p in data.get("profiles", [])]
        return settings
    except FileNotFoundError:
        return default_settings()
    except (ValueError, TypeError, AttributeError):
        # Ødelagt fil: ta vare på den og start på nytt.
        os.replace(CONFIG_PATH, CONFIG_PATH + ".bak")
        return default_settings()


def save(settings: Settings) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def parse_prefix(text: str) -> int:
    """'24', '/24' eller '255.255.255.0' -> 24. Gir ValueError hvis ugyldig."""
    text = text.strip().lstrip("/")
    if text.isdigit():
        prefix = int(text)
        if not 1 <= prefix <= 32:
            raise ValueError(text)
        return prefix
    return ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen


def prefix_to_mask(prefix: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def validate(p: Profile) -> str:
    """Returnerer en feilmelding, eller tom streng hvis profilen er gyldig."""
    if not p.name.strip():
        return "Profilen må ha et navn."
    for dns in p.dns:
        try:
            ipaddress.IPv4Address(dns)
        except ValueError:
            return f"«{dns}» er ikke en gyldig DNS-adresse."
    if p.mode == "dhcp":
        return ""
    try:
        iface = ipaddress.IPv4Interface(f"{p.ip}/{p.prefix}")
    except ValueError:
        return "Skriv inn en gyldig IP-adresse, f.eks. 192.168.1.10."
    net = iface.network
    if p.prefix <= 30 and iface.ip in (net.network_address, net.broadcast_address):
        return f"{iface.ip} er nettverks- eller kringkastingsadressen i {net}. Velg en annen."
    if p.gateway:
        try:
            gw = ipaddress.IPv4Address(p.gateway)
        except ValueError:
            return "Gatewayen er ikke en gyldig IP-adresse."
        if gw not in net:
            return f"Gatewayen {gw} ligger utenfor nettet {net}."
        if gw == iface.ip:
            return "Gatewayen kan ikke være den samme som IP-adressen."
    return ""
