#!/usr/bin/env bash
# release.sh - Release script for ai_request_handler
# requirements: Git, Github CLI
set -euo pipefail

# Prompt for the new tag version
read -r -p "Enter the new tag (e.g., v1.2.3): " TAG
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

if ! command -v gh &> /dev/null; then
    echo "gh could not be found. Please install gh to proceed."
    echo "| Install yq
> brew install gh
> sudo apt-get install gh"
    exit 1
fi

# Replace the existing newTag value
if grep -qE 'newTag:' "$FILE"; then
  sed -i.bak -E "s#(newTag:\s*).*\$#\1 $TAG#" "$FILE"
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
echo "Tag v$TAG created!"

gh release create "v$TAG"
gh release create "v$TAG" --title "Release v$TAG"


echo "Release v$TAG completed successfully!"

