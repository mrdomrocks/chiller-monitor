Chiller Monitor for Linux (64-bit)

This archive installs a private copy for your user. It does not need an administrator account. Wheels for Python 3.11, 3.12, 3.13, and 3.14 are included, so the install does not download Python packages.

1. Extract this archive.
2. In the chiller-monitor directory, run: ./install.sh
3. Open Chiller Monitor from the application menu, or run ~/.local/bin/chiller-monitor
4. The page opens at http://127.0.0.1:8765
5. Choose Demo chiller to try the HMI without a controller.

Close the terminal window to stop the program. Site profiles stay in ~/.local/share/chiller-monitor. Run ./uninstall.sh to remove the program and leave those profiles in place.

Opening Chiller Monitor checks GitHub. When a newer build is published, this copy installs it and reopens. Site profiles are kept.
