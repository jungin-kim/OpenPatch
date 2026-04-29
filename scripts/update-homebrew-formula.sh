#!/usr/bin/env bash
# Update Formula/repooperator.rb sha256 and version for a new npm release.
#
# Usage:
#   ./scripts/update-homebrew-formula.sh <version>
#
# Example:
#   ./scripts/update-homebrew-formula.sh 0.2.3
#
# After running this script:
#   1. Review the diff in Formula/repooperator.rb
#   2. Commit: git add Formula/repooperator.rb && git commit -m "chore: update Homebrew formula to v<version>"
#   3. Push and open a PR if you maintain a homebrew tap repo

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>" >&2
  exit 1
fi

FORMULA="$(cd "$(dirname "$0")/.." && pwd)/Formula/repooperator.rb"
TARBALL_URL="https://registry.npmjs.org/repooperator/-/repooperator-${VERSION}.tgz"

echo "Fetching tarball to compute sha256…"
SHA256=$(curl -fsSL "$TARBALL_URL" | shasum -a 256 | awk '{print $1}')
echo "  sha256: $SHA256"

# Update version in url line
sed -i.bak \
  "s|repooperator-[0-9]*\.[0-9]*\.[0-9]*.tgz|repooperator-${VERSION}.tgz|g" \
  "$FORMULA"

# Update sha256 line
sed -i.bak \
  "s|sha256 \"[^\"]*\"|sha256 \"${SHA256}\"|g" \
  "$FORMULA"

# Clean up backup files created by sed -i on macOS
rm -f "${FORMULA}.bak"

echo "Updated $FORMULA"
echo ""
echo "Diff:"
git diff "$FORMULA" || true
