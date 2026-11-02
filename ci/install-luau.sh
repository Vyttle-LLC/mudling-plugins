#!/bin/sh
# Downloads the pinned luau-analyze into $1 and checks it against its hash.
# Reads LUAU_VERSION and LUAU_UBUNTU_SHA256 from the environment.
set -eu

folder=$1
mkdir -p "$folder"
curl --fail --silent --show-error --location --output "$folder/luau.zip" \
	"https://github.com/luau-lang/luau/releases/download/$LUAU_VERSION/luau-ubuntu.zip"
echo "$LUAU_UBUNTU_SHA256  $folder/luau.zip" | sha256sum --check --quiet
unzip -q -o "$folder/luau.zip" luau-analyze -d "$folder"
chmod +x "$folder/luau-analyze"
