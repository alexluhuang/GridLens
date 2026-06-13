#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist/GridPACKWorkbench"
PACKAGE_ROOT="${ROOT_DIR}/build/deb/gridpack-workbench_${VERSION}"

if [[ ! -x "${DIST_DIR}/GridPACKWorkbench" ]]; then
  echo "PyInstaller output not found at ${DIST_DIR}/GridPACKWorkbench"
  echo "Build it first with: pyinstaller packaging/pyinstaller/gridpack-workbench.spec"
  exit 1
fi

rm -rf "${PACKAGE_ROOT}"
mkdir -p "${PACKAGE_ROOT}/DEBIAN"
mkdir -p "${PACKAGE_ROOT}/opt/gridpack-workbench"
mkdir -p "${PACKAGE_ROOT}/usr/share/applications"
mkdir -p "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps"

cp -R "${DIST_DIR}/." "${PACKAGE_ROOT}/opt/gridpack-workbench/"
cp "${ROOT_DIR}/packaging/deb/control" "${PACKAGE_ROOT}/DEBIAN/control"
cp "${ROOT_DIR}/packaging/deb/postinst" "${PACKAGE_ROOT}/DEBIAN/postinst"
chmod 0755 "${PACKAGE_ROOT}/DEBIAN/postinst"
cp "${ROOT_DIR}/packaging/deb/gridpack-workbench.desktop" "${PACKAGE_ROOT}/usr/share/applications/gridpack-workbench.desktop"
cp "${ROOT_DIR}/src/gridpack_workbench/resources/gridpack-workbench.svg" \
  "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps/gridpack-workbench.svg"

dpkg-deb --build "${PACKAGE_ROOT}" "${ROOT_DIR}/dist/gridpack-workbench_${VERSION}.deb"
echo "Created ${ROOT_DIR}/dist/gridpack-workbench_${VERSION}.deb"
