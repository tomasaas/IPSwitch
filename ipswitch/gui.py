"""Hovedvindu og ikon i systemstatusfeltet."""
import getpass
import html
import os
import sys
import threading

from PySide6.QtCore import QFileInfo, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QFileIconProvider, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from . import autostart, config, network
from .config import Profile, Settings
from .dialogs import ERROR_STYLE, OK_STYLE, HotkeyEdit, ProfileDialog
from .hotkeys import Hotkeys, display


def app_icon() -> QIcon:
    if getattr(sys, "frozen", False):  # exe: bruk ikonet som er bygget inn i exe-fila (--icon)
        return QFileIconProvider().icon(QFileInfo(sys.executable))
    return QIcon(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ipswitch.ico"))


class MainWindow(QWidget):
    applied = Signal(str, str, str, str)  # nettverkskort, profil, resultat, feilmelding

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.busy = False
        self.pending: Profile | None = None
        self.told_about_tray = False
        self.setWindowTitle("IP Switch")
        self.setWindowIcon(app_icon())
        self.resize(600, 520)

        self.hotkeys = Hotkeys()
        self.hotkeys.triggered.connect(self.on_hotkey)
        self.applied.connect(self.on_applied)

        # Nettverkskort
        self.adapter_box = QComboBox()
        self.adapter_box.currentIndexChanged.connect(self.on_adapter_changed)
        refresh = QPushButton("Oppdater")
        refresh.clicked.connect(self.load_adapters)
        self.adapter_status = QLabel()

        # Profiler
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda: self.edit_profile())
        new_btn, edit_btn, delete_btn = QPushButton("+ Ny profil"), QPushButton("Rediger"), QPushButton("Slett")
        new_btn.clicked.connect(self.new_profile)
        edit_btn.clicked.connect(lambda: self.edit_profile())
        delete_btn.clicked.connect(self.delete_profile)

        # Innstillinger nederst
        self.autostart_box = QCheckBox("Start ved oppstart", checked=autostart.is_enabled())
        self.autostart_box.toggled.connect(self.on_autostart_toggled)
        tray_box = QCheckBox("Ikon i systemstatusfeltet", checked=settings.tray)
        tray_box.toggled.connect(self.on_tray_toggled)
        keep_running_box = QCheckBox("Kjør videre når vinduet lukkes", checked=settings.keep_running)
        keep_running_box.toggled.connect(self.on_keep_running_toggled)
        advanced_box = QCheckBox("Avansert", checked=settings.advanced)
        advanced_box.toggled.connect(self.on_advanced_toggled)

        # Avansert
        show_all = QCheckBox("Vis alle nettverkskort (også virtuelle)", checked=settings.show_all_adapters)
        show_all.toggled.connect(self.on_show_all_toggled)
        notify = QCheckBox("Vis varsel når IP byttes", checked=settings.notifications)
        notify.toggled.connect(self.on_notify_toggled)
        self.cycle_edit = HotkeyEdit(self.hotkeys, settings.cycle_hotkey)
        self.cycle_edit.changed.connect(self.on_cycle_changed)
        self.cycle_status = QLabel()
        open_folder = QPushButton("Åpne konfigmappe")
        open_folder.clicked.connect(self.open_config_folder)
        open_folder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.advanced = QGroupBox("Avansert")
        self.advanced_form = form = QFormLayout(self.advanced)
        form.addRow(show_all)
        form.addRow(notify)
        form.addRow("Hurtigtast for neste profil:", self.cycle_edit)
        form.addRow("", self.cycle_status)
        form.addRow(open_folder)
        form.setRowVisible(self.cycle_status, False)

        self.message = QLabel(wordWrap=True)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Nettverkskort:"))
        top.addWidget(self.adapter_box, 1)
        top.addWidget(refresh)
        layout.addLayout(top)
        layout.addWidget(self.adapter_status)
        layout.addWidget(QLabel("<b>Profiler</b>"))
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        for b in (new_btn, edit_btn, delete_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(self.message)
        bottom = QHBoxLayout()
        bottom.addWidget(self.autostart_box)
        bottom.addWidget(tray_box)
        bottom.addWidget(keep_running_box)
        bottom.addStretch()
        bottom.addWidget(advanced_box)
        layout.addLayout(bottom)
        layout.addWidget(self.advanced)
        self.advanced.setVisible(settings.advanced)

        # Systemstatusfelt
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self.fill_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.setVisible(settings.tray)

        # Statuslinja oppdateres bare mens vinduet vises.
        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.update_status)

        self.load_adapters()
        self.register_hotkeys()

    # ---------- Nettverkskort ----------

    def load_adapters(self) -> None:
        adapters = network.list_adapters(self.settings.show_all_adapters)
        if not self.settings.adapter and adapters:
            self.settings.adapter = adapters[0].name  # første gang: kablet kort foretrekkes
            config.save(self.settings)
        self.adapter_box.blockSignals(True)
        self.adapter_box.clear()
        for a in adapters:
            self.adapter_box.addItem(a.label(), a.name)
        if self.settings.adapter and self.adapter_box.findData(self.settings.adapter) < 0:
            self.adapter_box.addItem(f"{self.settings.adapter}  (finnes ikke nå)", self.settings.adapter)
        self.adapter_box.setCurrentIndex(self.adapter_box.findData(self.settings.adapter))
        self.adapter_box.blockSignals(False)
        self.refresh_profiles()
        self.update_status()

    def on_adapter_changed(self, index: int) -> None:
        self.settings.adapter = self.adapter_box.itemData(index)
        config.save(self.settings)
        self.refresh_profiles()
        self.update_status()

    def update_status(self) -> None:
        name = self.settings.adapter
        if not name:
            self.adapter_status.setText("Fant ingen nettverkskort.")
            return
        ips = ", ".join(network.current_ipv4(name)) or "ingen IPv4-adresse"
        state = "Tilkoblet" if network.is_up(name) else "Frakoblet"
        self.adapter_status.setText(f"{state}  ·  Nå: {ips}")

    # ---------- Profiler ----------

    def active_profile(self) -> str:
        return self.settings.active.get(self.settings.adapter, "")

    def refresh_profiles(self) -> None:
        row = self.list.currentRow()
        self.list.clear()
        for p in self.settings.profiles:
            item = QListWidgetItem(self.list)
            widget = self.profile_row(p)
            item.setSizeHint(widget.sizeHint())
            self.list.setItemWidget(item, widget)
        self.list.setCurrentRow(min(row, self.list.count() - 1))
        active = self.active_profile()
        self.tray.setToolTip(f"IP Switch – {active}" if active else "IP Switch")

    def profile_row(self, p: Profile) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 3, 6, 3)
        mark = QLabel("✓" if p.name == self.active_profile() else "", styleSheet=OK_STYLE)
        mark.setFixedWidth(16)
        text = QLabel(f"<b>{html.escape(p.name)}</b><br><span style='color:gray'>{html.escape(p.summary())}</span>")
        hotkey = QLabel(display(p.hotkey) or "–")
        if p.hotkey in self.hotkeys.failed:
            hotkey.setText("⚠ " + hotkey.text())
            hotkey.setStyleSheet(ERROR_STYLE)
            hotkey.setToolTip("Hurtigtasten er opptatt av et annet program. Rediger profilen og velg en annen.")
        use = QPushButton("Bruk")
        use.clicked.connect(lambda _=False, p=p: self.apply_profile(p))
        layout.addWidget(mark)
        layout.addWidget(text, 1)
        layout.addWidget(hotkey)
        layout.addWidget(use)
        return widget

    def in_use(self, exclude: Profile | None = None) -> dict[str, str]:
        """Hurtigtaster som allerede er tatt i appen -> hva de brukes til."""
        used = {p.hotkey: f"profilen «{p.name}»" for p in self.settings.profiles if p.hotkey and p is not exclude}
        if self.settings.cycle_hotkey:
            used[self.settings.cycle_hotkey] = "«neste profil»"
        return used

    def new_profile(self) -> None:
        number = len(self.settings.profiles) + 1
        p = Profile(f"Profil {number}", mode="static", hotkey=self.hotkeys.suggest(self.in_use(), number))
        self.edit_profile(p, new=True)

    def edit_profile(self, p: Profile | None = None, new: bool = False) -> None:
        profiles = self.settings.profiles
        if p is None:
            row = self.list.currentRow()
            if row < 0:
                return
            p = profiles[row]
        number = len(profiles) + 1 if new else profiles.index(p) + 1
        names = [q.name for q in profiles if q is not p]
        dialog = ProfileDialog(self, p, self.in_use(exclude=p), names, self.hotkeys, self.settings.advanced, number)
        if not dialog.exec():
            return
        result = dialog.profile()
        if new:
            profiles.append(result)
        else:
            profiles[profiles.index(p)] = result
            for adapter, name in self.settings.active.items():  # profilen kan ha fått nytt navn
                if name == p.name:
                    self.settings.active[adapter] = result.name
        config.save(self.settings)
        self.register_hotkeys()

    def delete_profile(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        p = self.settings.profiles[row]
        box = QMessageBox(QMessageBox.Question, "Slett profil", f"Slette profilen «{p.name}»?", parent=self)
        delete = box.addButton("Slett", QMessageBox.DestructiveRole)
        box.addButton("Avbryt", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is delete:
            del self.settings.profiles[row]
            config.save(self.settings)
            self.register_hotkeys()

    # ---------- Bytte ----------

    def apply_profile(self, p: Profile) -> None:
        adapter = self.settings.adapter
        if not adapter:
            self.show_message("Velg et nettverkskort først.", error=True)
            return
        if self.busy:  # et bytte pågår: ta det nyeste etterpå
            self.pending = p
            return
        self.busy = True
        self.show_message(f"Bytter til {p.name} …")
        threading.Thread(target=self._apply_in_background, args=(adapter, p), daemon=True).start()

    def _apply_in_background(self, adapter: str, p: Profile) -> None:
        try:
            self.applied.emit(adapter, p.name, network.apply(adapter, p), "")
        except Exception as e:
            self.applied.emit(adapter, p.name, "", str(e) or type(e).__name__)

    def on_applied(self, adapter: str, name: str, result: str, error: str) -> None:
        self.busy = False
        if error:
            self.show_message(f"Kunne ikke bytte til {name}: {error}", error=True)
            self.notify("Bytte feilet", f"{name}: {error}", error=True)
        else:
            self.settings.active[adapter] = name
            config.save(self.settings)
            self.show_message(f"Byttet til {name} ({result}) på {adapter}.")
            self.notify(f"Byttet til {name}", f"{result} på {adapter}")
            self.refresh_profiles()
            self.update_status()
        if self.pending:
            p, self.pending = self.pending, None
            self.apply_profile(p)

    def on_hotkey(self, combo: str) -> None:
        if combo == self.settings.cycle_hotkey:
            self.cycle()
            return
        for p in self.settings.profiles:
            if p.hotkey == combo:
                self.apply_profile(p)
                return

    def cycle(self) -> None:
        profiles = self.settings.profiles
        if profiles:
            names = [p.name for p in profiles]
            active = self.active_profile()
            index = names.index(active) + 1 if active in names else 0
            self.apply_profile(profiles[index % len(profiles)])

    def register_hotkeys(self) -> None:
        combos = [p.hotkey for p in self.settings.profiles] + [self.settings.cycle_hotkey]
        failed = self.hotkeys.set(combos)
        if self.settings.cycle_hotkey in failed:
            self.set_cycle_status("⚠ Opptatt av et annet program. Velg en annen.", error=True)
        self.refresh_profiles()

    # ---------- Meldinger ----------

    def show_message(self, text: str, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(ERROR_STYLE if error else "")

    def notify(self, title: str, text: str, error: bool = False) -> None:
        if self.tray.isVisible() and (self.settings.notifications or error):
            icon = QSystemTrayIcon.Critical if error else QSystemTrayIcon.Information
            self.tray.showMessage(title, text, icon, 4000)

    # ---------- Innstillinger ----------

    def on_autostart_toggled(self, on: bool) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            autostart.enable() if on else autostart.disable()
            error = ""
        except Exception as e:
            error = (str(e).splitlines() or [""])[0]
        QApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "IP Switch", "Kunne ikke endre oppstartsinnstillingen. "
                                f"Ble administrator-spørsmålet avslått?\n\n{error}")
            self.autostart_box.blockSignals(True)
            self.autostart_box.setChecked(autostart.is_enabled())
            self.autostart_box.blockSignals(False)

    def on_tray_toggled(self, on: bool) -> None:
        self.settings.tray = on
        config.save(self.settings)
        self.tray.setVisible(on)

    def on_keep_running_toggled(self, on: bool) -> None:
        self.settings.keep_running = on
        config.save(self.settings)

    def on_advanced_toggled(self, on: bool) -> None:
        self.settings.advanced = on
        config.save(self.settings)
        self.advanced.setVisible(on)

    def on_show_all_toggled(self, on: bool) -> None:
        self.settings.show_all_adapters = on
        config.save(self.settings)
        self.load_adapters()

    def on_notify_toggled(self, on: bool) -> None:
        self.settings.notifications = on
        config.save(self.settings)

    def on_cycle_changed(self, combo: str) -> None:
        in_use = {k: v for k, v in self.in_use().items() if k != self.settings.cycle_hotkey}
        problem = self.hotkeys.check(combo, in_use) if combo else ""
        self.set_cycle_status(("✗ " + problem) if problem else ("✓ Ledig" if combo else ""), error=bool(problem))
        if not problem:
            self.settings.cycle_hotkey = combo
            config.save(self.settings)
            self.register_hotkeys()

    def set_cycle_status(self, text: str, error: bool = False) -> None:
        self.cycle_status.setText(text)
        self.cycle_status.setStyleSheet(ERROR_STYLE if error else OK_STYLE)
        self.advanced_form.setRowVisible(self.cycle_status, bool(text))

    def open_config_folder(self) -> None:
        os.makedirs(config.config_dir(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(config.config_dir()))

    # ---------- Vindu og systemstatusfelt ----------

    def fill_tray_menu(self) -> None:
        menu = self.tray_menu
        menu.clear()
        menu.addAction(self.settings.adapter or "Ingen nettverkskort").setEnabled(False)
        for p in self.settings.profiles:
            action = menu.addAction(p.name + (f"\t{display(p.hotkey)}" if p.hotkey else ""))
            action.setCheckable(True)
            action.setChecked(p.name == self.active_profile())
            action.triggered.connect(lambda _=False, p=p: self.apply_profile(p))
        menu.addSeparator()
        menu.addAction("Åpne IP Switch", self.show_window)
        menu.addAction("Avslutt", QApplication.quit)

    def on_tray_activated(self, reason) -> None:
        # Venstreklikk viser samme meny som høyreklikk (på Mac gjør systemet det selv).
        if reason == QSystemTrayIcon.Trigger and sys.platform != "darwin":
            self.tray_menu.popup(QCursor.pos())

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event):
        self.update_status()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        if not self.settings.keep_running:
            QApplication.quit()
            return
        # Appen lever videre: hurtigtastene og ikonet i systemstatusfeltet virker fortsatt.
        event.ignore()
        self.hide()
        if self.tray.isVisible() and not self.told_about_tray:
            self.told_about_tray = True
            self.tray.showMessage("IP Switch kjører fortsatt",
                                  "Hurtigtastene virker. Klikk ikonet for å bytte profil eller avslutte.")


def relaunch_as_admin(argv: list[str]) -> bool:
    """Starter appen på nytt som administrator (ett UAC-spørsmål). False hvis brukeren sa nei."""
    import ctypes
    import subprocess
    if getattr(sys, "frozen", False):  # exe
        exe, args = sys.executable, argv[1:]
    else:  # fra kildekode: pythonw, så det ikke dukker opp et konsollvindu
        exe, args = sys.executable.replace("python.exe", "pythonw.exe"), [os.path.abspath(argv[0]), *argv[1:]]
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), None, 1) > 32


def run(argv: list[str]) -> int:
    if sys.platform == "win32":  # eget ikon på oppgavelinja, også når appen kjøres fra Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IPSwitch")
    app = QApplication(argv)
    app.setApplicationName("IP Switch")
    app.setQuitOnLastWindowClosed(False)

    # Bare én instans: kjører appen allerede, vises det vinduet i stedet.
    server_name = f"IPSwitch-{getpass.getuser()}"
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(500):
        return 0

    # Å endre IP og lage oppstartsoppgaven krever administrator på Windows.
    if sys.platform == "win32" and not network.is_admin() and relaunch_as_admin(argv):
        return 0

    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.WorldAccessOption)  # så en ny start uten admin også når fram
    server.listen(server_name)

    window = MainWindow(config.load())
    server.newConnection.connect(lambda: (server.nextPendingConnection().deleteLater(), window.show_window()))
    if "--tray" not in argv:
        window.show()
    elif not window.tray.isVisible():
        window.showMinimized()  # uten ikon i systemstatusfeltet må appen synes på oppgavelinja
    return app.exec()
