#!/usr/bin/env bash
# Fallback browser setup for a machine where `playwright install --with-deps`
# cannot be run because there is no root.
#
# The normal path is the one in the README:
#     python3 -m playwright install --with-deps chromium
#
# This script is for the case where that fails with
#     error while loading shared libraries: libnspr4.so: cannot open shared object file
# and `sudo` is not available. It downloads the .deb packages chromium needs,
# unpacks them under build/pwdeps/ (git-ignored) and leaves them there.
# engine.py looks for that directory and puts it on LD_LIBRARY_PATH itself, so
# nothing else has to change.
#
# Debian/Ubuntu only. It installs nothing system-wide.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$REPO/build/pwdeps"
mkdir -p "$DEST/debs" "$DEST/root"
cd "$DEST/debs"

PKGS=(libnspr4 libnss3 libasound2t64 libatk1.0-0t64 libatk-bridge2.0-0t64
      libcups2t64 libxkbcommon0 libatspi2.0-0t64 libxdamage1 libxfixes3
      libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libxcomposite1)

for p in "${PKGS[@]}"; do
  apt-get download "$p" >/dev/null 2>&1 || echo "  (skipped $p — not in this distro's archive)"
done

for d in *.deb; do dpkg -x "$d" "$DEST/root"; done

echo "unpacked into $DEST/root"
echo "engine.py will pick this up automatically."

# The mock portal is entirely in Japanese. Without a CJK font the headless
# browser renders every glyph as a box, which only matters for the screenshots
# the engine writes to build/screens/ — the automation itself reads text, not
# pixels, and works either way.
if ! fc-list 2>/dev/null | grep -qi 'cjk\|noto sans jp'; then
  echo "note: no CJK font found. Screenshots will show tofu boxes."
  echo "      apt-get download fonts-noto-cjk && dpkg -x fonts-noto-cjk*.deb ~/.fontpkg"
  echo "      cp \$(find ~/.fontpkg -name '*.ttc') ~/.fonts/ && fc-cache -f"
fi
