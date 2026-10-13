"""Globale hurtigtaster. Windows: RegisterHotKey i en egen tråd. Linux/macOS: pynput.

En hurtigtast lagres som tekst, f.eks. "ctrl+alt+shift+1".
"""
import sys
import threading

from PySide6.QtCore import QObject, Signal

MODIFIERS = ("ctrl", "alt", "shift", "win")
KEYS = [*"abcdefghijklmnopqrstuvwxyz0123456789", *(f"f{n}" for n in range(1, 13))]

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetKeyboardLayout.restype = wintypes.HKL
    user32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.HKL)
    user32.ToUnicodeEx.argtypes = (wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
                                   wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HKL)
    kernel32 = ctypes.WinDLL("kernel32")
    MOD_FLAGS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY, WM_APP = 0x0312, 0x8000
    ERROR_HOTKEY_ALREADY_REGISTERED = 1409
    VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12


def parse(combo: str) -> tuple[list[str], str] | None:
    """'Ctrl+Alt+1' -> (['ctrl', 'alt'], '1'), eller None hvis ugyldig."""
    *mods, key = [part.strip().lower() for part in combo.split("+")]
    if key not in KEYS or len(set(mods)) != len(mods) or any(m not in MODIFIERS for m in mods):
        return None
    return [m for m in MODIFIERS if m in mods], key


def normalize(combo: str) -> str:
    parsed = parse(combo)
    return "+".join([*parsed[0], parsed[1]]) if parsed else ""


def display(combo: str) -> str:
    parsed = parse(combo) if combo else None
    if not parsed:
        return ""
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Cmd" if sys.platform == "darwin" else "Win"}
    return "+".join([names[m] for m in parsed[0]] + [parsed[1].upper()])


def _vk(key: str) -> int:
    return ord(key.upper()) if len(key) == 1 else 0x6F + int(key[1:])  # A=0x41, 1=0x31, F1=0x70


def _altgr_char(mods: list[str], key: str) -> str:
    """Tegnet Ctrl+Alt(+Shift)+tast skriver på brukerens tastatur (AltGr = Ctrl+Alt), ellers ''."""
    if not {"ctrl", "alt"} <= set(mods) or "win" in mods:
        return ""
    state = (ctypes.c_ubyte * 256)()
    for vk in (VK_CONTROL, VK_MENU, VK_SHIFT) if "shift" in mods else (VK_CONTROL, VK_MENU):
        state[vk] = 0x80
    layout = user32.GetKeyboardLayout(0)
    buf = ctypes.create_unicode_buffer(8)
    vk = _vk(key)
    # Flagg 0x4: ikke endre tastaturtilstanden (døde taster).
    n = user32.ToUnicodeEx(vk, user32.MapVirtualKeyExW(vk, 0, layout), state, buf, 8, 0x4, layout)
    text = buf.value[:abs(n)]
    return text if n and text.isprintable() else ""


def _taken_by_other_program(mods: list[str], key: str) -> bool:
    flags = sum(MOD_FLAGS[m] for m in mods)
    if user32.RegisterHotKey(None, 0xBFFF, flags, _vk(key)):
        user32.UnregisterHotKey(None, 0xBFFF)
        return False
    return ctypes.get_last_error() == ERROR_HOTKEY_ALREADY_REGISTERED


class Hotkeys(QObject):
    """Holder de globale hurtigtastene registrert og sender `triggered(combo)` når en trykkes."""

    triggered = Signal(str)

    def __init__(self):
        super().__init__()
        self._combos: list[str] = []
        self._registered: set[str] = set()
        self._paused = False
        self.failed: list[str] = []
        if sys.platform == "win32":
            self._queue: list[str] = []
            self._done = threading.Event()
            ready = threading.Event()
            threading.Thread(target=self._windows_loop, args=(ready,), daemon=True).start()
            ready.wait()
        else:
            self._listener = None

    def set(self, combos: list[str]) -> list[str]:
        """Erstatter alle hurtigtaster. Returnerer de som ikke kunne registreres."""
        self._combos = [c for c in combos if c]
        if not self._paused:
            self._register(self._combos)
        return self.failed

    def pause(self) -> None:
        """Slå av midlertidig mens brukeren tar opp en ny hurtigtast."""
        self._paused = True
        self._register([])

    def resume(self) -> None:
        self._paused = False
        self._register(self._combos)

    def check(self, combo: str, in_use: dict[str, str]) -> str:
        """Tom streng hvis hurtigtasten kan brukes, ellers en kort forklaring."""
        parsed = parse(combo)
        if not parsed:
            return "Bruk en bokstav, et tall eller F1–F12 sammen med Ctrl/Alt/Shift/Win."
        mods, key = parsed
        combo = normalize(combo)
        if combo in in_use:
            return f"Brukes allerede av {in_use[combo]}."
        if len(mods) < 2:
            return "Bruk minst to av Ctrl, Alt, Shift og Win, så den ikke krasjer med andre programmer."
        if sys.platform == "win32":
            if "win" in mods and not key.startswith("f"):
                return "Reservert for Windows-snarveier."
            char = _altgr_char(mods, key)
            if char:
                return f"Brukes til å skrive «{char}» på tastaturet ditt (AltGr = Ctrl+Alt)."
            if combo not in self._registered and _taken_by_other_program(mods, key):
                return "Opptatt av et annet program."
        return ""

    def suggest(self, in_use: dict[str, str], number: int = 1) -> str:
        """Første ledige av Ctrl+Alt+Shift+<tall> (helst profilens nummer), deretter F1–F12."""
        digits = "1234567890"
        start = (number - 1) % 10
        for key in [*digits[start:], *digits[:start], *(f"f{n}" for n in range(1, 13))]:
            combo = f"ctrl+alt+shift+{key}"
            if not self.check(combo, in_use):
                return combo
        return ""

    def _register(self, combos: list[str]) -> None:
        if sys.platform == "win32":
            self._queue = list(combos)
            self._done.clear()
            user32.PostThreadMessageW(self._thread_id, WM_APP, 0, 0)
            self._done.wait(2)
        else:
            self.failed = self._register_pynput(combos)
        self._registered = set(combos) - set(self.failed)

    def _windows_loop(self, ready: threading.Event) -> None:
        # RegisterHotKey knytter tastene til tråden som registrerer dem, så alt skjer her.
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # oppretter meldingskøen
        ready.set()
        ids: dict[int, str] = {}
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:  # venter uten å bruke CPU
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.triggered.emit(ids[msg.wParam])
            elif msg.message == WM_APP:
                for hotkey_id in ids:
                    user32.UnregisterHotKey(None, hotkey_id)
                ids.clear()
                failed = []
                for hotkey_id, combo in enumerate(self._queue, start=1):
                    mods, key = parse(combo)
                    flags = sum(MOD_FLAGS[m] for m in mods) | MOD_NOREPEAT
                    if user32.RegisterHotKey(None, hotkey_id, flags, _vk(key)):
                        ids[hotkey_id] = combo
                    else:
                        failed.append(combo)
                self.failed = failed
                self._done.set()

    def _register_pynput(self, combos: list[str]) -> list[str]:
        try:
            from pynput import keyboard
        except Exception:  # f.eks. Wayland uten X: globale hurtigtaster er ikke mulig
            return list(combos)
        if self._listener:
            self._listener.stop()
            self._listener = None
        if not combos:
            return []
        names = {"ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "win": "<cmd>"}
        mapping = {}
        for combo in combos:
            mods, key = parse(combo)
            spec = "+".join([names[m] for m in mods] + [f"<{key}>" if len(key) > 1 else key])
            mapping[spec] = lambda c=combo: self.triggered.emit(c)
        self._listener = keyboard.GlobalHotKeys(mapping)
        self._listener.start()
        return []
