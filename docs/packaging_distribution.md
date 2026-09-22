# Packaging and distribution

The recommended DGX Spark distribution artifact is one local Debian package:

```text
dist/gridlens_<version>_<arch>.deb
```

Install it with `apt` rather than `dpkg`, so DGX OS can download Docker and the shared-library dependencies:

```bash
sudo apt install ./dist/gridlens_0.1.0_arm64.deb
```

The package installs GridLens to `/opt/gridlens`, adds `/usr/bin/gridlens`, enables Docker when systemd is
available, and adds the sudo-invoking user to the `docker` group when it can identify that user. You have to
log out and back in before new Docker group membership takes effect.

## Build the package

Build on the same architecture you plan to distribute to. For DGX Spark, build on an ARM64 DGX Spark or an
equivalent ARM64 Ubuntu 24.04 environment.

One-time build host setup:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip dpkg-dev
```

Build:

```bash
cd /path/to/gridpack-workbench-dev
packaging/deb/build_deb.sh
```

Output on DGX Spark ARM64:

```text
dist/gridlens_0.1.0_arm64.deb
```

The build script creates `.venv-packaging`, installs GridLens with the `dev` and full `analysis` extras, runs
PyInstaller, and wraps the frozen app in a Debian package. The resulting `.deb` is large because it bundles
RAPIDS, cuDF, and the related CUDA Python libraries for DGX Spark.

To override the version:

```bash
packaging/deb/build_deb.sh 0.1.1
```

To reuse an existing `dist/GridLens` bundle without rebuilding it:

```bash
GRIDLENS_SKIP_BUNDLE_BUILD=1 packaging/deb/build_deb.sh
```

## What ships, and what does not

The `.deb` contains the frozen GridLens app and its Python dependencies. It contains no model, no inference
engine, no provider CLI, no GridPACK solver image, and no generated-analysis sandbox image.

The bundle ships:

- `PySide6` and `mcp==1.30.0`, the two pinned runtime dependencies in `pyproject.toml` and
  `requirements.txt`.
- The `dev` and full `analysis` extras installed on the build host, including RAPIDS, cuDF, CUDA Python,
  PyArrow, Dask, and matplotlib.
- `src/gridlens/resources`.

`mcp` needs two things from the PyInstaller spec, because the frozen binary starts the GridLens MCP server as
a child process. First, `mcp` is in the spec's `metadata_packages`, so `copy_metadata` bundles its
distribution metadata. Second, `mcp.server.fastmcp` and `mcp.server.stdio` are listed as hidden imports,
because PyInstaller cannot see them through the SDK's lazy imports. Dropping either one produces a binary
whose Agent tab fails only at MCP startup.

The operator or the user supplies the rest:

- The GridPACK solver image, through an approved internal registry or an offline tarball.
- The Hermes Agent CLI, Ollama, and any local model. The user installs these. GridLens never installs a CLI,
  signs a user in, or downloads a model.
- The generated-analysis sandbox image. GridLens runs it with `--pull=never` and requires its immutable
  `sha256` image ID, so it has to exist locally on the machine running GridLens. Build it from the recipe
  under `packaging/agent/` before you open CEII inputs, and see [CEII security notes](security_ceii.md).

## What the package downloads

On the build machine, the Python GUI, analysis, RAPIDS, cuDF, and CUDA Python libraries come from Python
package indexes into the bundled PyInstaller app.

On the user machine, `apt install ./gridlens_<version>_<arch>.deb` downloads Docker and the required Qt and
X11 runtime libraries from the configured DGX OS and Ubuntu package repositories.

## Internal website distribution

For regulators, publish a simple download page in an approved internal environment, holding:

- The app `.deb`.
- Its SHA-256 checksum.
- Versioned release notes.
- The required GridPACK image version.
- The installation guide.
- The troubleshooting guide.
- The security statement.

Do not let the installer auto-download GridPACK container images in a CEII environment. Provide the image
through an approved internal registry or an offline tarball.

## Why not Flatpak first

Flatpak's sandbox is valuable, but it complicates this product's core needs:

- Docker socket access.
- Local project folder access.
- User-managed CEII directories.
- Host container runtime behavior.
- Possible NVIDIA runtime integration.

Revisit Flatpak later, once the organization has a clear policy for granting those permissions.
