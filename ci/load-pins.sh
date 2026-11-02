#!/bin/sh
# Hands ci/pins.env to the rest of the job, and stops it plainly if the MUDling
# commit hasn't been set to a real one.
set -eu

grep -v '^#' ci/pins.env >>"$GITHUB_ENV"
commit=$(sed -n 's/^MUDLING_COMMIT=//p' ci/pins.env)
if ! printf '%s' "$commit" | grep -Eq '^[0-9a-f]{40}$'; then
	echo "::error file=ci/pins.env::MUDLING_COMMIT is '$commit'. Set it to a full commit on Vyttle-LLC/mudling that has mudling plugin test."
	exit 1
fi
