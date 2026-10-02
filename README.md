# RUT Chiller Monitor

Local plant page for a water chiller reached through a Teltonika RUT. The app brings up the router’s WireGuard or OpenVPN profile, polls the controller with Modbus TCP, and shows an at-a-glance HMI. The register map — addresses, types, scaling, alarms, and which points can be written — is edited in the app.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

Open http://127.0.0.1:8765 and choose **Demo chiller** to see the HMI without hardware.

The server listens on this computer only. Site profiles and VPN files stay in `data/` and are not committed.

## On the Teltonika

1. Put the chiller on the RUT. A controller with RS485 uses a serial model (for example a RUT956) and RutOS **Services → Modbus** as a Modbus TCP gateway. A controller that already speaks Modbus TCP only needs to be on the RUT LAN.
2. Create a WireGuard or OpenVPN server under **Services → VPN** and export the client profile. Teltonika RMS VPN also works: connect that tunnel yourself and choose **Already connected** in this app.
3. Create a site, upload the profile, and set the Modbus host to the address that answers on port 502 once the tunnel is up. The unit id is the controller’s Modbus address.
4. Open **Register map** and match every point to the controller manual: area, address, data type, byte order, scale, and bit. Mark setpoints and coils as writable if the engineer is allowed to change them. Bind the plant slots to those points.

WireGuard and OpenVPN need permission to create a network interface. If `sudo` is not available non-interactively, bring the tunnel up in the operating system and leave VPN set to **Already connected**.

## Tests

```bash
pytest
```
