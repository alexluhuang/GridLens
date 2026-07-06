#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist/GridLens"
PACKAGE_ROOT="${ROOT_DIR}/build/deb/gridlens_${VERSION}"

if [[ ! -x "${DIST_DIR}/GridLens" ]]; then
  echo "PyInstaller output not found at ${DIST_DIR}/GridLens"
  echo "Build it first with: pyinstaller packaging/pyinstaller/gridlens.spec"
  exit 1
fi

rm -rf "${PACKAGE_ROOT}"
mkdir -p "${PACKAGE_ROOT}/DEBIAN"
mkdir -p "${PACKAGE_ROOT}/opt/gridlens"
mkdir -p "${PACKAGE_ROOT}/usr/share/applications"
mkdir -p "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps"

cp -R "${DIST_DIR}/." "${PACKAGE_ROOT}/opt/gridlens/"
cp "${ROOT_DIR}/packaging/deb/control" "${PACKAGE_ROOT}/DEBIAN/control"
cp "${ROOT_DIR}/packaging/deb/postinst" "${PACKAGE_ROOT}/DEBIAN/postinst"
chmod 0755 "${PACKAGE_ROOT}/DEBIAN/postinst"
cp "${ROOT_DIR}/packaging/deb/gridlens.desktop" "${PACKAGE_ROOT}/usr/share/applications/gridlens.desktop"
cp "${ROOT_DIR}/src/gridlens/resources/gridlens.svg" \
  "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps/gridlens.svg"

dpkg-deb --build "${PACKAGE_ROOT}" "${ROOT_DIR}/dist/gridlens_${VERSION}.deb"
echo "Created ${ROOT_DIR}/dist/gridlens_${VERSION}.deb"
