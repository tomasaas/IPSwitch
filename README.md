# IP Switch

Bytt IP-oppsett på nettverkskortet med én hurtigtast i stedet for å klikke deg gjennom Windows-innstillingene.

- Lag så mange profiler du vil: **DHCP** eller **statisk IP** med nettmaske (og valgfri gateway/DNS).
- Gi hver profil en **hurtigtast**, f.eks. `Ctrl+Alt+Shift+1`. Appen sjekker selv om tasten er ledig.
- Bytt fra **systemstatusfeltet** (ikonet nede til høyre) eller med «Bruk»-knappen i vinduet.
- **Start ved oppstart** gjør at appen ligger klar i bakgrunnen uten UAC-spørsmål.

Windows 10/11 er hovedmålet. Linux (NetworkManager) og macOS fungerer også, men er mindre testet.

## Bruk

1. Start `IPSwitch.exe` og svar Ja på administrator-spørsmålet. Windows krever admin for å endre IP; appen ber om det selv.
2. Velg nettverkskort øverst. Kablet kort velges automatisk første gang.
3. Klikk **+ Ny profil**, fyll inn IP og nettmaske (`24` eller `255.255.255.0` er det samme), og trykk OK.
4. Trykk hurtigtasten, eller klikk ikonet i systemstatusfeltet og velg profilen.

Med **Kjør videre når vinduet lukkes** på fortsetter appen i bakgrunnen (hurtigtaster og ikonet virker) når du lukker vinduet. Velg **Avslutt** i ikonmenyen for å stoppe den.

> Windows 11 gjemmer nye ikoner under pilen **^**. Dra ikonet ned på oppgavelinja hvis du vil ha det synlig hele tiden.

### Hurtigtaster

Klikk i hurtigtastfeltet og trykk kombinasjonen. Feltet sier fra om tasten
- allerede brukes av et annet program,
- er en Windows-snarvei,
- brukes til å skrive et tegn på tastaturet ditt. På norsk tastatur er `AltGr` det samme som `Ctrl+Alt`, så `Ctrl+Alt+2` er `@`.

`Ctrl+Alt+Shift+<tall>` er nesten alltid ledig, og det er det appen foreslår.

### Avansert

Huk av **Avansert** for å få fram
- alle nettverkskort (også virtuelle, VPN osv.),
- DNS-servere i profilene,
- en hurtigtast som blar til neste profil,
- valg for varsler og en knapp som åpner konfigmappa.

Innstillingene ligger i `%APPDATA%\IPSwitch\config.json` (Linux: `~/.config/IPSwitch`, macOS: `~/Library/Application Support/IPSwitch`).

## Kjøre fra kildekode

### Enkel oppstart på Windows

Installer **Python 3.12 eller nyere** hvis du ikke allerede har det. Dobbeltklikk deretter på **`Start-IPSwitch.cmd`** i repo-mappen. Den:

- oppretter og aktiverer `.venv` ved behov,
- installerer appens avhengigheter første gang og når `requirements.txt` endres,
- lager **IPSwitch** på skrivebordet med appens `.ico`-ikon,
- starter appen, som selv ber om administrator-tilgang.

Bruk skrivebordssnarveien ved senere oppstart. Første oppsett krever internett; vanlig oppstart bruker det lokale miljøet. Snarveien starter med et minimert PowerShell-vindu som lukkes når appen er startet. Repo-mappen må bli liggende; flytter du den, kjør `Start-IPSwitch.cmd` igjen for å oppdatere snarveien.

`.venv` følger ikke med når du kloner: miljøet er maskinavhengig og opprettes lokalt. Ingen bygging av `.exe` er nødvendig. Startfilene endrer ikke maskinens permanente PowerShell-policy.

Du kan også starte fra PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-IPSwitch.ps1
# Bare sett opp miljøet og skrivebordssnarveien, uten å starte appen:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-IPSwitch.ps1 -SetupOnly -CreateDesktopShortcut
```

### Manuelt oppsett / utvikling

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py          # ber om administrator-tilgang (UAC) ved start
.venv\Scripts\pip install -r requirements-dev.txt  # kun for tester og exe-bygging
.venv\Scripts\python -m pytest        # tester
```

## Bygge exe

```
.venv\Scripts\pyinstaller --onefile --windowed --icon ipswitch.ico --name IPSwitch main.py
```

Resultatet havner i `dist\IPSwitch.exe`. Vinduet og systemstatusfeltet bruker ikonet som er bygget inn i exe-fila, så `--icon` er nok. Linux og macOS bygges med samme kommando på en maskin med det OS-et, fordi PyInstaller ikke kan lage filer for andre systemer.

Exe-fila er ikke signert. Windows SmartScreen kan derfor vise «Windows beskyttet PC-en» første gang; velg *Mer informasjon → Kjør likevel*.

## Linux og macOS

- **Linux:** bruker `nmcli` (NetworkManager) og endrer den aktive tilkoblingen på kortet. Hurtigtaster fungerer på X11. Wayland tillater ikke globale hurtigtaster fra apper; der må du bruke ikonmenyen eller vinduet.
- **macOS:** bruker `networksetup` og ber om administratorpassord ved bytte. Hurtigtaster krever at appen får tilgang under *Personvern og sikkerhet → Tilgjengelighet*.
