#!/usr/bin/env bash
# Create or publish this checkout as a public GitHub repository.
# The script never prints or stores authentication tokens.
set -euo pipefail

REPO_NAME="${1:-scheiber-can-analysis-nmea2000}"
DESCRIPTION="Scheiber proprietary CAN reverse engineering, Raspberry Pi/SH-C30A capture workflow, and proposed NMEA 2000 mapping"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v gh >/dev/null 2>&1 || fail "GitHub CLI is required: https://cli.github.com/"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "run this script from inside the project checkout"

gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not authenticated; run: gh auth login"

OWNER="${GITHUB_OWNER:-$(gh api user --jq .login)}"
FULL_NAME="${OWNER}/${REPO_NAME}"
EXPECTED_URL="https://github.com/${FULL_NAME}.git"
CURRENT_BRANCH="$(git branch --show-current)"

[[ -n "$CURRENT_BRANCH" ]] || fail "detached HEAD is not supported"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  fail "expected branch 'main', found '${CURRENT_BRANCH}'"
fi

if gh repo view "$FULL_NAME" >/dev/null 2>&1; then
  printf 'Repository already exists: https://github.com/%s\n' "$FULL_NAME"

  if git remote get-url origin >/dev/null 2>&1; then
    ACTUAL_URL="$(git remote get-url origin)"
    case "$ACTUAL_URL" in
      "$EXPECTED_URL"|"git@github.com:${FULL_NAME}.git") ;;
      *) fail "origin points to '${ACTUAL_URL}', not '${EXPECTED_URL}'" ;;
    esac
  else
    git remote add origin "$EXPECTED_URL"
  fi

  git push -u origin main
else
  gh repo create "$FULL_NAME" \
    --public \
    --description "$DESCRIPTION" \
    --source . \
    --remote origin \
    --push
fi

printf '\nPublished: https://github.com/%s\n' "$FULL_NAME"
printf 'Visibility check: '
gh repo view "$FULL_NAME" --json visibility --jq .visibility
printf 'Default branch: '
gh repo view "$FULL_NAME" --json defaultBranchRef --jq .defaultBranchRef.name
