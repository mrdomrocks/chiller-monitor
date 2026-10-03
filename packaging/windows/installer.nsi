Unicode True
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!define APPNAME "Chiller Monitor"
!define APPVER "0.1.0"

Name "${APPNAME}"
OutFile "__OUTFILE__"
InstallDir "$LOCALAPPDATA\Programs\ChillerMonitor"
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

Function LaunchApp
  ExecShell "open" "$INSTDIR\Chiller Monitor.bat"
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "staging\app"
  File /r "staging\static"
  File /r "staging\python"
  File "staging\Chiller Monitor.bat"
  File "staging\README.txt"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\Chiller Monitor.lnk" "$INSTDIR\Chiller Monitor.bat"
  CreateShortcut "$SMPROGRAMS\Uninstall Chiller Monitor.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Chiller Monitor.lnk" "$INSTDIR\Chiller Monitor.bat"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Chiller Monitor.lnk"
  Delete "$SMPROGRAMS\Chiller Monitor.lnk"
  Delete "$SMPROGRAMS\Uninstall Chiller Monitor.lnk"
  RMDir /r "$INSTDIR"
SectionEnd
