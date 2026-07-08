# Packaging And Distribution

The recommended DGX Spark distribution artifact is one local Debian package:

```text
dist/gridlens_<version>_<arch>.deb
```

Install it with `apt`, not `dpkg`, so DGX OS can download Docker and shared-library dependencies:

```bash
sudo apt install ./dist/gridlens_0.1.0_arm64.deb
```

The package installs GridLens to `/opt/gridlens`, adds `/usr/bin/gridlens`, enables Docker when systemd is available,
and adds the sudo-invoking user to the `docker` group when that user can be identified. Users must log out and back in
before new Docker group membership is active.

## Build The Package

Build on the same architecture you plan to distribute to. For DGX Spark, build on an ARM64 DGX Spark or equivalent ARM64
Ubuntu 24.04 environment.

One-time build host setup:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip dpkg-dev
```

Build:

```bash
cd /home/alh360/Documents/gridpack-workbench-dev
packaging/deb/build_deb.sh
```

Output on DGX Spark ARM64:

```text
dist/gridlens_0.1.0_arm64.deb
```

The build script creates `.venv-packaging`, installs GridLens with `dev` and full `analysis` extras, runs PyInstaller,
and wraps the frozen app in a Debian package. The resulting `.deb` is large because it bundles RAPIDS/cuDF and related
CUDA Python libraries for DGX Spark. To override the version:

```bash
packaging/deb/build_deb.sh 0.1.1
```

To reuse an existing `dist/GridLens` bundle without rebuilding it:

```bash
GRIDLENS_SKIP_BUNDLE_BUILD=1 packaging/deb/build_deb.sh
```

## What The Package Downloads

On the build machine, Python GUI, analysis, RAPIDS/cuDF, and CUDA Python libraries are downloaded from Python package
indexes into the bundled PyInstaller app.

On the user machine, `apt install ./gridlens_<version>_<arch>.deb` downloads Docker and required Qt/X11 runtime
libraries from configured DGX OS/Ubuntu package repositories.

## Internal Website Distribution

For regulators, publish a simple download page in an approved internal environment:

- app `.deb`;
- SHA-256 checksum;
- versioned release notes;
- required GridPACK image version;
- installation guide;
- troubleshooting guide;
- security statement.

Do not make the installer auto-download GridPACK container images in CEII environments. Provide the image through an
approved internal registry or offline tarball.

## Why Not Flatpak First

Flatpak's sandbox is valuable, but it complicates this product's core needs:

- Docker socket access;
- local project folder access;
- user-managed CEII directories;
- host container runtime behavior;
- possible NVIDIA runtime integration.

Revisit Flatpak later only if the organization has a clear policy for granting those permissions.
