#!/bin/sh
# Publishes a GitHub release for the version in extension/manifest.json, the
# repository's one version number, with the extension attached as a zip. Being
# the only way to release, it is what guarantees every release carries the zip.
#
#   bump "version" in extension/manifest.json, commit, push, then: scripts/release.sh
set -eu
cd "$(dirname "$0")/.."
version=$(python3 -c 'import json; print(json.load(open("extension/manifest.json"))["version"])')
tag="v$version"
[ -z "$(git status --porcelain)" ] || { echo "release: commit your changes first" >&2; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "release: HEAD is not origin/main" >&2; exit 1; }

zip="dist/open-browser-use-extension-$version.zip"
mkdir -p dist
rm -f "$zip"
# The extension files at the zip's root, so it unzips into a folder Chrome's
# "Load unpacked" takes as is.
(cd extension && zip -qr "../$zip" . -x '*.DS_Store')
zip -qj "$zip" LICENSE

gh release create "$tag" "$zip" --target "$(git rev-parse HEAD)" --title "$tag" --generate-notes
