# Packaging And Distribution

The recommended distribution path is:

```text
development editable install
  -> PyInstaller onedir build
  -> internal pilot tarball
  -> Debian package for DGX OS 7
  -> signed package and internal website download
```

## Build With PyInstaller

```bash
cd /home/alh360/Documents/gridpack-workbench-dev
source .venv/bin/activate
python -m pip install -e ".[dev]"
pyinstaller packaging/pyinstaller/gridpack-workbench.spec
```

Output:

```text
dist/GridPACKWorkbench/
  GridPACKWorkbench
  _internal/
```

Test:

```bash
./dist/GridPACKWorkbench/GridPACKWorkbench
```

## Pilot Tarball

For a small internal pilot:

```bash
cd dist
tar -czf GridPACKWorkbench-0.1.0-linux.tar.gz GridPACKWorkbench
```

A pilot user can unpack and run:

```bash
tar -xzf GridPACKWorkbench-0.1.0-linux.tar.gz
./GridPACKWorkbench/GridPACKWorkbench
```

## Debian Package

After PyInstaller succeeds:

```bash
packaging/deb/build_deb.sh 0.1.0
```

Output:

```text
dist/gridpack-workbench_0.1.0.deb
```

Install:

```bash
sudo apt install ./dist/gridpack-workbench_0.1.0.deb
```

The installed layout is:

```text
/opt/gridpack-workbench/
/usr/share/applications/gridpack-workbench.desktop
/usr/share/icons/hicolor/scalable/apps/gridpack-workbench.svg
```

## Internal Website Distribution

For regulators, publish a simple download page in an approved internal environment:

- app `.deb`;
- SHA-256 checksum;
- versioned release notes;
- required Docker/GridPACK image version;
- installation guide;
- troubleshooting guide;
- security statement.

Do not make the installer auto-download container images in CEII environments. Provide the image through an approved internal registry or offline tarball.

## Why Not Flatpak First

Flatpak's sandbox is valuable, but it complicates this product's core needs:

- Docker socket access;
- local project folder access;
- user-managed CEII directories;
- host container runtime behavior;
- possible NVIDIA runtime integration.

Revisit Flatpak later only if the organization has a clear policy for granting those permissions.
