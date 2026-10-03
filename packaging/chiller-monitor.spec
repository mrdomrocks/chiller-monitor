Name:           chiller-monitor
Version:        0.1.0
Release:        3%{?dist}
Summary:        Local HMI for a chiller polled over Modbus TCP
License:        LicenseRef-Proprietary
URL:            https://github.com/mrdomrocks/chiller-monitor
BuildArch:      x86_64

# The Python libraries are bundled for this ABI. Automatic dependency scans
# would require distro packages that do not exist for this stack.
AutoReqProv:    no
BuildRequires:  python3
BuildRequires:  python3-pip
Requires:       python(abi) = 3.14
Requires:       python3-gobject
Requires:       gtk3
Requires:       webkit2gtk4.1

# Bundled wheels are already built. Do not strip or recompile them.
%define debug_package %{nil}
%define __os_install_post %{nil}

%description
Local plant page for a water chiller reached over Modbus TCP.
The program listens on 127.0.0.1:8765 and stores site profiles
in each user's ~/.local/share/chiller-monitor directory.

%prep
:

%install
rm -rf %{buildroot}
install -d %{buildroot}/opt/chiller-monitor
cp -a %{_repodir}/app %{_repodir}/static %{buildroot}/opt/chiller-monitor/
find %{buildroot}/opt/chiller-monitor -type d -name __pycache__ -print0 | xargs -0 -r rm -rf
python3 -m pip install \
  --target %{buildroot}/opt/chiller-monitor/lib \
  --disable-pip-version-check \
  --only-binary=:all: \
  -r %{_repodir}/packaging/requirements-runtime.txt
rm -rf %{buildroot}/opt/chiller-monitor/lib/bin
find %{buildroot}/opt/chiller-monitor/lib -type d -name __pycache__ -print0 | xargs -0 -r rm -rf
install -d %{buildroot}%{_bindir}
install -m 0755 %{_repodir}/packaging/rpm/chiller-monitor.sh %{buildroot}%{_bindir}/chiller-monitor
install -d %{buildroot}%{_datadir}/applications
install -m 0644 %{_repodir}/packaging/rpm/chiller-monitor.desktop %{buildroot}%{_datadir}/applications/chiller-monitor.desktop
install -d %{buildroot}%{_docdir}/chiller-monitor
install -m 0644 %{_repodir}/packaging/rpm/README.txt %{buildroot}%{_docdir}/chiller-monitor/README

%files
/opt/chiller-monitor
%{_bindir}/chiller-monitor
%{_datadir}/applications/chiller-monitor.desktop
%{_docdir}/chiller-monitor

%post
update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :

%postun
update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :

%changelog
* Sat Oct 03 2026 Chiller Monitor <local@localhost> - 0.1.0-3
- Customise the plant display from inside the application.
* Sat Oct 03 2026 Chiller Monitor <local@localhost> - 0.1.0-2
- Open the plant page in its own window.
* Sat Oct 03 2026 Chiller Monitor <local@localhost> - 0.1.0-1
- Package the local chiller HMI for installation with dnf.
