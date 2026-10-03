# RUT Chiller Monitor

Local plant page for a water chiller on a Teltonika RUT. The laptop joins the network first. The app then opens Modbus TCP to the controller IP, the same way Modbus Monitor does, and shows an at-a-glance HMI. The register map — addresses, types, scaling, alarms, and which points can be written — is edited in the app.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

Open http://127.0.0.1:8765 and choose **Demo chiller** to see the HMI without hardware.

The server listens on this computer only. Site profiles stay in `data/` and are not committed.

## Install at home

Build both packages from this repository:

```bash
packaging/build-all.sh
```

- Windows: `dist/ChillerMonitor-0.1.0-Setup.exe`. It installs for the current user, Python included, and adds a desktop shortcut. Windows may warn that the publisher is unknown; choose More info, then Run anyway. Site profiles are kept in `%LOCALAPPDATA%\ChillerMonitor`.
- Linux, 64-bit, Python 3.11–3.14: `dist/chiller-monitor-0.1.0-linux-x86_64.tar.gz`. Extract it and run `./install.sh`. No administrator account is required, and the Python packages are already in the archive. Site profiles are kept in `~/.local/share/chiller-monitor`.

Close the program window to stop it. Choose **Demo chiller** on the page to try the HMI without a controller.

## Connection

1. Put the chiller on the RUT. A controller with RS485 uses a serial model (for example a RUT956) and RutOS **Services → Modbus** as a Modbus TCP gateway. A controller that already speaks Modbus TCP only needs to be on the RUT LAN.
2. On site, join the RUT Wi-Fi or the site LAN from the laptop. Away from site, bring up the remote route you already use (the laptop VPN, RMS, or mobile data path) before opening this app.
3. Create a site and set the IP address, port 502, and the controller unit id. Connect. The program polls that socket and opens a new one if the link drops.
4. Open **Register map** and match every point to the controller manual: area, address, data type, byte order, scale, and bit. Mark setpoints and coils as writable if the engineer is allowed to change them. Bind the plant slots to those points.

The plant page reads the fitted-compressor register and shows that many circuits, each with its load percentage, up to six. A chiller that reports 2 shows two cards. A larger machine shows the extra compressors. Match **Fitted compressors**, each **Compressor N** load, and each run bit to the controller. On the demo chiller that count can be written, so both sizes can be checked.

## Tests

```bash
pytest
```
