#!/usr/bin/env bash
# Publish the packaged Studio to GitHub Packages as a NuGet package.
#
#   packaging/publish_nuget.sh <path/to/EmbeddedDisplayStudio.exe> <version>
#
# Runs on a Windows runner (Git Bash). Needs GITHUB_TOKEN with packages:write
# and GITHUB_REPOSITORY_OWNER, both set by Actions. The release page stays the
# primary download; this makes the same binary appear under Packages.
set -euo pipefail

exe="$1"
version="${2#v}"
owner="${GITHUB_REPOSITORY_OWNER:?}"
here="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -d)"

[ -f "$exe" ] || { echo "::error::no executable at $exe"; exit 1; }

# The NuGet CLI is on the Windows images; fetch it if an image ever drops it.
nuget=nuget
if ! command -v nuget >/dev/null 2>&1; then
  curl -fsSL -o "$out/nuget.exe" https://dist.nuget.org/win-x86-commandline/latest/nuget.exe
  nuget="$out/nuget.exe"
fi

"$nuget" pack "$here/EmbeddedDisplayStudio.nuspec" \
  -Properties "version=$version;exe=$(cd "$(dirname "$exe")" && pwd -W 2>/dev/null || pwd)/$(basename "$exe")" \
  -OutputDirectory "$out" -NoPackageAnalysis -NonInteractive

package="$out/EmbeddedDisplayStudio.$version.nupkg"
ls -l "$package"
dotnet nuget push "$package" \
  --source "https://nuget.pkg.github.com/$owner/index.json" \
  --api-key "${GITHUB_TOKEN:?}" \
  --skip-duplicate
echo "Published EmbeddedDisplayStudio $version to GitHub Packages"
