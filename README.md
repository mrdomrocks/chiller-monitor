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

## Connection

1. Put the chiller on the RUT. A controller with RS485 uses a serial model (for example a RUT956) and RutOS **Services → Modbus** as a Modbus TCP gateway. A controller that already speaks Modbus TCP only needs to be on the RUT LAN.
2. On site, join the RUT Wi-Fi or the site LAN from the laptop. Away from site, bring up the remote route you already use (the laptop VPN, RMS, or mobile data path) before opening this app.
3. Create a site and set the IP address, port 502, and the controller unit id. Connect. The program polls that socket and opens a new one if the link drops.
4. Open **Register map** and match every point to the controller manual: area, address, data type, byte order, scale, and bit. Mark setpoints and coils as writable if the engineer is allowed to change them. Bind the plant slots to those points.

## Tests

```bash
pytest
```
