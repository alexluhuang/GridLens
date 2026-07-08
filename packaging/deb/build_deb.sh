#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"
VERSION="${1:-$(python3 "${ROOT_DIR}/scripts/package_version.py")}"
ARCH="${GRIDLENS_DEB_ARCH:-$(dpkg --print-architecture)}"
DIST_DIR="${ROOT_DIR}/dist/GridLens"
PACKAGE_ROOT="${ROOT_DIR}/build/deb/gridlens_${VERSION}_${ARCH}"
VENV_DIR="${GRIDLENS_PACKAGE_VENV:-${ROOT_DIR}/.venv-packaging}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-${ROOT_DIR}/build/matplotlib-cache}"
mkdir -p "${MPLCONFIGDIR}"

if [[ "${GRIDLENS_SKIP_BUNDLE_BUILD:-0}" != "1" ]]; then
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
  "${VENV_DIR}/bin/python" -m pip install -e "${ROOT_DIR}[dev,analysis]"
  "${VENV_DIR}/bin/pyinstaller" --clean --noconfirm "${ROOT_DIR}/packaging/pyinstaller/gridlens.spec"
fi

if [[ ! -x "${DIST_DIR}/GridLens" ]]; then
  echo "PyInstaller output not found at ${DIST_DIR}/GridLens"
  exit 1
fi

rm -rf "${PACKAGE_ROOT}"
mkdir -p "${PACKAGE_ROOT}/DEBIAN"
mkdir -p "${PACKAGE_ROOT}/opt/gridlens"
mkdir -p "${PACKAGE_ROOT}/usr/bin"
mkdir -p "${PACKAGE_ROOT}/usr/share/applications"
mkdir -p "${PACKAGE_ROOT}/usr/share/doc/gridlens"
mkdir -p "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps"

cp -R "${DIST_DIR}/." "${PACKAGE_ROOT}/opt/gridlens/"
sed \
  -e "s/^Version:.*/Version: ${VERSION}/" \
  -e "s/^Architecture:.*/Architecture: ${ARCH}/" \
  "${ROOT_DIR}/packaging/deb/control" > "${PACKAGE_ROOT}/DEBIAN/control"
cp "${ROOT_DIR}/packaging/deb/postinst" "${PACKAGE_ROOT}/DEBIAN/postinst"
cp "${ROOT_DIR}/packaging/deb/postrm" "${PACKAGE_ROOT}/DEBIAN/postrm"
chmod 0755 "${PACKAGE_ROOT}/DEBIAN/postinst"
chmod 0755 "${PACKAGE_ROOT}/DEBIAN/postrm"
ln -s /opt/gridlens/GridLens "${PACKAGE_ROOT}/usr/bin/gridlens"
cp "${ROOT_DIR}/packaging/deb/gridlens.desktop" "${PACKAGE_ROOT}/usr/share/applications/gridlens.desktop"
cp "${ROOT_DIR}/packaging/deb/README.Debian" "${PACKAGE_ROOT}/usr/share/doc/gridlens/README.Debian"
cp "${ROOT_DIR}/packaging/deb/copyright" "${PACKAGE_ROOT}/usr/share/doc/gridlens/copyright"
cp "${ROOT_DIR}/src/gridlens/resources/gridlens.svg" \
  "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps/gridlens.svg"
chmod 0644 "${PACKAGE_ROOT}/DEBIAN/control"
chmod 0644 "${PACKAGE_ROOT}/usr/share/applications/gridlens.desktop"
chmod 0644 "${PACKAGE_ROOT}/usr/share/doc/gridlens/README.Debian"
chmod 0644 "${PACKAGE_ROOT}/usr/share/doc/gridlens/copyright"
chmod 0644 "${PACKAGE_ROOT}/usr/share/icons/hicolor/scalable/apps/gridlens.svg"

dpkg-deb --root-owner-group --build "${PACKAGE_ROOT}" "${ROOT_DIR}/dist/gridlens_${VERSION}_${ARCH}.deb"
echo "Created ${ROOT_DIR}/dist/gridlens_${VERSION}_${ARCH}.deb"
