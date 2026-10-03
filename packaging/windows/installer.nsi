Unicode True
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "FileFunc.nsh"
!insertmacro GetSize

!define APPNAME "Chiller Monitor"
!define APPVER "0.1.0"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChillerMonitor"

Name "${APPNAME}"
OutFile "__OUTFILE__"
InstallDir "$LOCALAPPDATA\Programs\ChillerMonitor"
InstallDirRegKey HKCU "${UNINSTKEY}" "InstallLocation"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start Chiller Monitor"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

VIProductVersion "0.1.0.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "Chiller Monitor setup"
VIAddVersionKey "FileVersion" "${APPVER}"
VIAddVersionKey "CompanyName" "Chiller Monitor"
VIAddVersionKey "LegalCopyright" "Copyright 2026"

Function LaunchApp
  ExecShell "open" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\chiller-monitor.pyw"'
FunctionEnd

Section "Install"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "staging\app"
  File /r "staging\static"
  File /r "staging\python"
  File "staging\Chiller Monitor.bat"
  File "staging\chiller-monitor.pyw"
  File "staging\chiller-monitor.ico"
  File "staging\README.txt"
  File "staging\REVISION"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\Chiller Monitor"
  CreateShortcut "$SMPROGRAMS\Chiller Monitor\Chiller Monitor.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\chiller-monitor.pyw"' "$INSTDIR\chiller-monitor.ico" 0 "" "" "Chiller Monitor"
  CreateShortcut "$SMPROGRAMS\Chiller Monitor\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Chiller Monitor.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\chiller-monitor.pyw"' "$INSTDIR\chiller-monitor.ico" 0 "" "" "Chiller Monitor"

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${APPVER}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "Chiller Monitor"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Chiller Monitor.lnk"
  Delete "$SMPROGRAMS\Chiller Monitor\Chiller Monitor.lnk"
  Delete "$SMPROGRAMS\Chiller Monitor\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Chiller Monitor"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
SectionEnd
