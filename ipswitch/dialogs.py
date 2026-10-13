"""Profildialog og feltet for å ta opp hurtigtaster."""
import re
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QWidget)

from .config import Profile, parse_prefix, prefix_to_mask, validate
from .hotkeys import Hotkeys, display, normalize

OK_STYLE = "color: #2e7d32"
ERROR_STYLE = "color: #c62828"


def row(*widgets) -> QWidget:
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return w


class HotkeyEdit(QLineEdit):
    """Klikk i feltet og trykk tastekombinasjonen. Backspace/Delete fjerner den."""

    changed = Signal(str)

    def __init__(self, hotkeys: Hotkeys, combo: str = ""):
        super().__init__()
        self.hotkeys = hotkeys
        self.combo = normalize(combo)
        self.setText(display(self.combo))
        self.setPlaceholderText("Klikk her og trykk tastene")

    def set_combo(self, combo: str) -> None:
        self.combo = normalize(combo)
        self.setText(display(self.combo))
        self.changed.emit(self.combo)

    def focusInEvent(self, event):
        self.hotkeys.pause()  # ellers fanger Windows tastene før feltet ser dem
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.hotkeys.resume()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        mods = event.modifiers()
        names = [name for flag, name in ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
                                         (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "win")) if mods & flag]
        if sys.platform == "darwin":  # Qt bytter om Cmd og Ctrl på Mac
            names = ["win" if n == "ctrl" else "ctrl" if n == "win" else n for n in names]
        if not names and event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self.set_combo("")
        elif not names and event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            event.ignore()  # la dialogen håndtere Esc/Enter
        elif key := self._key_name(event):
            self.set_combo("+".join(names + [key]))
        else:
            self.setText("+".join(n.capitalize() for n in names) + "+…" if names else "")  # "Ctrl+Alt+…"

    def keyReleaseEvent(self, event):
        self.setText(display(self.combo))

    @staticmethod
    def _key_name(event) -> str:
        # På Windows gir den virtuelle tastekoden riktig tall også med Shift nede (Shift+1 = 1, ikke !).
        code = event.nativeVirtualKey() if sys.platform == "win32" else event.key()
        if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A:
            return chr(code).lower()
        f_key = event.key() - Qt.Key_F1
        return f"f{f_key + 1}" if 0 <= f_key < 12 else ""


class ProfileDialog(QDialog):
    def __init__(self, parent, profile: Profile, in_use: dict[str, str], other_names: list[str],
                 hotkeys: Hotkeys, advanced: bool, number: int):
        super().__init__(parent)
        self.setWindowTitle("Profil")
        self.setMinimumWidth(460)
        self.hotkeys, self.in_use, self.other_names, self.number = hotkeys, in_use, other_names, number
        self.hotkey_problem = ""

        self.name = QLineEdit(profile.name)
        self.dhcp = QRadioButton("Automatisk (DHCP)")
        self.static = QRadioButton("Statisk IP")
        (self.static if profile.mode == "static" else self.dhcp).setChecked(True)
        self.ip = QLineEdit(profile.ip, placeholderText="f.eks. 192.168.1.10")
        self.mask = QLineEdit(str(profile.prefix), placeholderText="24 eller 255.255.255.0")
        self.mask_hint = QLabel()
        self.gateway = QLineEdit(profile.gateway, placeholderText="valgfri")
        self.dns = QLineEdit(", ".join(profile.dns), placeholderText="valgfri, f.eks. 8.8.8.8, 1.1.1.1")
        self.hotkey = HotkeyEdit(hotkeys, profile.hotkey)
        suggest = QPushButton("Foreslå")
        suggest.clicked.connect(lambda: self.hotkey.set_combo(hotkeys.suggest(in_use, number)))
        clear = QPushButton("Fjern")
        clear.clicked.connect(lambda: self.hotkey.set_combo(""))
        self.hotkey_status = QLabel(wordWrap=True)
        self.error = QLabel(wordWrap=True, styleSheet=ERROR_STYLE)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Cancel).setText("Avbryt")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        self.form = QFormLayout(self)
        self.form.addRow("Navn:", self.name)
        self.form.addRow("Type:", row(self.dhcp, self.static))
        self.form.addRow("IP-adresse:", self.ip)
        self.mask_row = row(self.mask, self.mask_hint)
        self.form.addRow("Nettmaske:", self.mask_row)
        self.form.addRow("Gateway:", self.gateway)
        self.form.addRow("DNS:", self.dns)
        self.form.addRow("Hurtigtast:", row(self.hotkey, suggest, clear))
        self.form.addRow("", self.hotkey_status)
        self.form.addRow(self.error)
        self.form.addRow(self.buttons)
        self.form.setRowVisible(self.dns, advanced)

        for edit in (self.name, self.ip, self.mask, self.gateway, self.dns):
            edit.textChanged.connect(self.refresh)
        self.static.toggled.connect(self.refresh)
        self.hotkey.changed.connect(self.on_hotkey_changed)
        self.on_hotkey_changed(self.hotkey.combo)

    def profile(self) -> Profile:
        static = self.static.isChecked()
        try:
            prefix = parse_prefix(self.mask.text())
        except ValueError:
            prefix = -1 if static else 24
        return Profile(
            name=self.name.text().strip(),
            mode="static" if static else "dhcp",
            ip=self.ip.text().strip() if static else "",
            prefix=prefix,
            gateway=self.gateway.text().strip() if static else "",
            dns=[d for d in re.split(r"[,;\s]+", self.dns.text()) if d],
            hotkey=self.hotkey.combo,
        )

    def on_hotkey_changed(self, combo: str) -> None:
        self.hotkey_problem = self.hotkeys.check(combo, self.in_use) if combo else ""
        if not combo:
            self.hotkey_status.setText("Ingen hurtigtast – profilen kan fortsatt brukes fra vinduet og ikonet.")
            self.hotkey_status.setStyleSheet("")
        elif self.hotkey_problem:
            self.hotkey_status.setText("✗ " + self.hotkey_problem)
            self.hotkey_status.setStyleSheet(ERROR_STYLE)
        else:
            self.hotkey_status.setText("✓ Ledig")
            self.hotkey_status.setStyleSheet(OK_STYLE)
        self.refresh()

    def refresh(self) -> None:
        static = self.static.isChecked()
        for widget in (self.ip, self.mask_row, self.gateway):
            self.form.setRowVisible(widget, static)
        p = self.profile()
        self.mask_hint.setText(f"= /{p.prefix}  ({prefix_to_mask(p.prefix)})" if p.prefix > 0 else "")
        if static and p.prefix < 0:
            error = "Ugyldig nettmaske. Skriv f.eks. 24 eller 255.255.255.0."
        elif p.name in self.other_names:
            error = "Det finnes allerede en profil med dette navnet."
        else:
            error = validate(p)
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not error and not self.hotkey_problem)
