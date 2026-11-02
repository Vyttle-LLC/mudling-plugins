#!/bin/sh
# Commits the index at $1 to the `index` branch and pushes it, one commit each
# time. The branch holds nothing else, and the app fetches the file from it.
set -eu

index=$1
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
if git fetch --depth=1 origin index; then
	git switch --create index FETCH_HEAD
else
	git switch --orphan index
fi
cp "$index" index.json
git add index.json
if git diff --cached --quiet; then
	echo "The index hasn't changed: a re-run of a published commit."
	exit 0
fi
git commit --message "Publish the index for $GITHUB_SHA"
git push origin index
