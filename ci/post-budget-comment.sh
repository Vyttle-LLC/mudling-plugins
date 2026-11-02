#!/bin/sh
# Puts the budget comment in $1 on the open pull request for the branch that CI
# ran on, replacing the last one. Reads HEAD_OWNER, HEAD_BRANCH and HEAD_SHA,
# which come from GitHub's record of the run, never from the run's own files.
set -eu

body=$1
if [ ! -s "$body" ]; then
	echo "No budget to show."
	exit 0
fi
number=$(gh api --method GET "repos/$GITHUB_REPOSITORY/pulls" \
	--field "head=$HEAD_OWNER:$HEAD_BRANCH" --field state=open \
	--jq ".[] | select(.head.sha == \"$HEAD_SHA\") | .number")
if [ -z "$number" ]; then
	echo "No open pull request for $HEAD_SHA: it has probably moved on."
	exit 0
fi
existing=$(gh api --paginate "repos/$GITHUB_REPOSITORY/issues/$number/comments" \
	--jq '.[] | select(.user.login == "github-actions[bot]" and (.body | startswith("<!-- registry-budget -->"))) | .id' |
	head -n 1)
if [ -n "$existing" ]; then
	gh api --method PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$existing" --field "body=@$body" >/dev/null
else
	gh api --method POST "repos/$GITHUB_REPOSITORY/issues/$number/comments" --field "body=@$body" >/dev/null
fi
