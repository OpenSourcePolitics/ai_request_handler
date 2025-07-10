#!/usr/bin/env bash
# release.sh - Release script for ai_request_handler

set -euo pipefail

# Ensure we are on the main branch
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" != "main" ]]; then
  echo "Error: You must be on the 'main' branch (current: '$current_branch')."
  exit 1
fi

# Prompt for the new tag version
read -r -p "Enter the new tag (e.g., 1.2.3): " TAG
if [[ -z "$TAG" ]]; then
  echo "No tag entered. Exiting."
  exit 1
fi

# Update the tag in flux-sync.yaml
FILE="gitops/flux-sync.yaml"
if [[ ! -f "$FILE" ]]; then
  echo "Error: File $FILE not found!"
  exit 1
fi

# Replace the existing newTag value
if grep -qE 'newTag:' "$FILE"; then
  sed -i.bak -E "s#(newTag:\s*).*\$#\1$TAG#" "$FILE"
  rm -f "${FILE}.bak"
  echo "Updated flux-sync.yaml with newTag: $TAG"
else
  echo "Error: 'newTag:' entry not found in $FILE"
  exit 1
fi

# Commit changes and create Git tag
commit_msg="chore: release ai_request_handler v$TAG"
git add "$FILE"
git commit -m "$commit_msg"

echo "Creating annotated Git tag v$TAG..."
git tag -a "v$TAG" -m "Release ai_request_handler v$TAG"

echo "Pushing commit and tag to remote..."
git push origin main
git push origin "v$TAG"

echo "Release v$TAG completed successfully!"
