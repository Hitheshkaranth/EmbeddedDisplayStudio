# native/hmi-gui/build.ps1 -- Windows entry point: forwards to build.sh inside
# WSL Ubuntu, which carries the Qt 6 toolchain (there is no MSVC/MinGW Qt on
# this host). Any arguments are passed through (--test, --clean).
#
#   powershell -ExecutionPolicy Bypass -File native\hmi-gui\build.ps1 --test
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Args)

$distro = if ($env:HMI_WSL_DISTRO) { $env:HMI_WSL_DISTRO } else { "Ubuntu" }
$here = $PSScriptRoot
$wslPath = (wsl -d $distro -u root -- wslpath -a ($here -replace '\\', '/')).Trim()
if (-not $wslPath) { Write-Error "wslpath failed for $here"; exit 2 }

wsl -d $distro -u root -- bash "$wslPath/build.sh" @Args
exit $LASTEXITCODE
