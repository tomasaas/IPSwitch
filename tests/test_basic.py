import json

import pytest

from ipswitch import config, hotkeys, network
from ipswitch.config import Profile, parse_prefix, prefix_to_mask, validate


@pytest.mark.parametrize("text, prefix", [("24", 24), ("/16", 16), (" 255.255.255.0 ", 24), ("255.255.255.252", 30)])
def test_parse_prefix(text, prefix):
    assert parse_prefix(text) == prefix


@pytest.mark.parametrize("text", ["", "0", "33", "255.0.255.0", "abc"])
def test_parse_prefix_invalid(text):
    with pytest.raises(ValueError):
        parse_prefix(text)


def test_prefix_to_mask():
    assert prefix_to_mask(24) == "255.255.255.0"
    assert prefix_to_mask(21) == "255.255.248.0"


def test_validate():
    assert validate(Profile("DHCP")) == ""
    assert validate(Profile("Kontor", "static", "10.0.0.50", 24, "10.0.0.1")) == ""
    assert validate(Profile("", "dhcp"))
    assert validate(Profile("x", "static", "10.0.0.300", 24))
    assert validate(Profile("x", "static", "10.0.0.0", 24))  # nettverksadresse
    assert validate(Profile("x", "static", "10.0.0.255", 24))  # kringkasting
    assert validate(Profile("x", "static", "10.0.0.5", 24, "10.0.1.1"))  # gateway utenfor nettet
    assert validate(Profile("x", "static", "10.0.0.5", 32)) == ""
    assert validate(Profile("x", "dhcp", dns=["8.8.8.8", "nei"]))


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    assert config.load().profiles[0].mode == "dhcp"  # standard første gang
    settings = config.Settings(adapter="Ethernet", profiles=[Profile("A", "static", "1.2.3.4", 8, dns=["8.8.8.8"])])
    config.save(settings)
    assert config.load() == settings


def test_load_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{ikke json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    assert config.load() == config.default_settings()
    assert (tmp_path / "config.json.bak").exists()


def test_load_ignores_unknown_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"adapter": "Wi-Fi", "gammelt": 1, "profiles": [{"name": "A", "x": 2}]}), "utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    settings = config.load()
    assert settings.adapter == "Wi-Fi" and settings.profiles == [Profile("A")]


def test_windows_commands_dhcp():
    assert network.windows_commands("Wi-Fi 2", Profile("D")) == [
        ["netsh", "interface", "ipv4", "set", "address", "name=Wi-Fi 2", "source=dhcp"],
        ["netsh", "interface", "ipv4", "set", "dnsservers", "name=Wi-Fi 2", "source=dhcp"],
    ]


def test_windows_commands_static():
    p = Profile("S", "static", "192.168.0.10", 24, "192.168.0.1", ["8.8.8.8", "1.1.1.1"])
    assert network.windows_commands("Ethernet", p) == [
        ["netsh", "interface", "ipv4", "set", "address", "name=Ethernet", "source=static",
         "address=192.168.0.10", "mask=255.255.255.0", "gateway=192.168.0.1"],
        ["netsh", "interface", "ipv4", "set", "dnsservers", "name=Ethernet", "source=static",
         "address=8.8.8.8", "register=primary", "validate=no"],
        ["netsh", "interface", "ipv4", "add", "dnsservers", "name=Ethernet", "address=1.1.1.1",
         "index=2", "validate=no"],
    ]


def test_windows_commands_static_without_gateway_or_dns():
    cmds = network.windows_commands("Ethernet", Profile("S", "static", "10.0.0.5", 8))
    assert cmds[0][-1] == "gateway=none"
    assert cmds[1][-1] == "address=none"


def test_linux_and_mac_commands():
    p = Profile("S", "static", "10.0.0.5", 24, "10.0.0.1")
    assert network.linux_commands("Kablet", p)[0][4:8] == ["ipv4.method", "manual", "ipv4.addresses", "10.0.0.5/24"]
    assert network.linux_commands("Kablet", Profile("D"))[0][4:6] == ["ipv4.method", "auto"]
    assert network.mac_commands("Wi-Fi", p)[0] == ["networksetup", "-setmanual", "Wi-Fi", "10.0.0.5",
                                                  "255.255.255.0", "10.0.0.1"]
    assert network.mac_commands("Wi-Fi", Profile("D"))[1] == ["networksetup", "-setdnsservers", "Wi-Fi", "empty"]


def test_hotkey_parse_and_display():
    assert hotkeys.normalize("Shift+CTRL+alt+1") == "ctrl+alt+shift+1"
    assert hotkeys.normalize("ctrl+alt+F5") == "ctrl+alt+f5"
    assert hotkeys.normalize("ctrl+ctrl+1") == ""
    assert hotkeys.normalize("ctrl+alt+") == ""
    assert hotkeys.normalize("hyper+1") == ""
    assert hotkeys.display("ctrl+alt+shift+f12") == "Ctrl+Alt+Shift+F12"
    assert hotkeys.display("") == ""
