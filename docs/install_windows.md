# Windows install guide

GridLens runs on Windows x64 in two ways. Both need Docker Desktop, because GridPACK runs only as a Linux
container. The native install runs on Windows 10 or 11; the WSL2 install needs Windows 11, the only version
on which RAPIDS supports WSL2.

| | Native | WSL2 |
|---|---|---|
| Install | The GridLens installer, like any Windows app | The Linux package, inside an Ubuntu 24.04 WSL2 distribution |
| Analysis | CPU Dask | RAPIDS on an NVIDIA GPU |
| Projects | A Windows folder | The Linux file system of the distribution |
| Window | A Windows window | A Linux window, shown on the Windows desktop by WSLg |

RAPIDS publishes Linux wheels only, so the native install analyzes results on the CPU. A GPU analysis on a
Windows PC runs through WSL2. Choose native when the CPU is fast enough for your cases, or when IT does not
allow WSL2 distributions.

## Docker Desktop

Both routes need Docker Desktop with the WSL2 backend:

1. Install Docker Desktop, and let it enable WSL2 when it asks.
2. Start Docker Desktop. Docker on Windows is an application, not a service, so start it before GridLens.
3. Keep it on Linux containers. If the tray menu offers **Switch to Linux containers**, choose it: GridPACK
   images are Linux images, and GridLens's Docker check reports a problem when Docker runs Windows
   containers.
4. Pull the GridPACK image before you open sensitive files:

   ```powershell
   docker pull pnnl/gridpack:latest
   ```

Docker Desktop's terms require a paid subscription for commercial use by larger organizations and by
government entities, so check with IT before you install it. Rancher Desktop, with its dockerd engine, is a
free alternative that provides the same `docker` command.

Docker Desktop runs containers in a WSL2 VM, which by default gets half of the PC's memory. Large
contingency sweeps can need more. To raise it, create `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=48GB
processors=16
```

Then run `wsl --shutdown` and start Docker Desktop again.

## Native install

1. Run `GridLens-<version>-setup.exe`. It installs GridLens for your account only, under
   `%LOCALAPPDATA%\Programs\GridLens`, and needs no administrator password. If SmartScreen warns about an
   unsigned installer, ask the person who gave it to you for a signed build.
2. Start GridLens from the Start menu.

GridLens keeps its settings and caches under `%LOCALAPPDATA%\GridLens`, and projects under
`%UserProfile%\GridLensProjects` unless you choose another folder.

The analysis runs on CPU Dask. Each analysis you start says so, because the GPU backends are not
available; that is expected on native Windows.

Paths longer than 260 characters need the `LongPathsEnabled` policy, which an administrator turns on once
per PC. Deep project folders, long user names, and Clarke's session folders can reach that length.

### Clarke on native Windows

The **Set up Clarke** window installs Hermes Agent with its PowerShell installer, into
`%LOCALAPPDATA%\hermes`, and Ollama with its Windows installer, into
`%LOCALAPPDATA%\Programs\Ollama`. Neither needs an administrator password. Ollama uses an NVIDIA GPU if
the PC has one.

The script sandbox runs approved scripts through Docker Desktop, as the user `nobody` inside Docker's VM.
Build its image as described in `packaging/agent/README.md`, in PowerShell.

## WSL2 install

1. In PowerShell, install Ubuntu 24.04:

   ```powershell
   wsl --install -d Ubuntu-24.04
   ```

2. In Docker Desktop, open **Settings > Resources > WSL integration** and turn it on for Ubuntu-24.04. The
   distribution then has `docker` and `/var/run/docker.sock`, and GridLens uses them as it does on Linux.
3. For GPU analysis, install the NVIDIA Windows driver, version 580 or later for the CUDA 13 build. Do not
   install a Linux driver inside WSL2; the Windows driver serves it. Check with `nvidia-smi` in Ubuntu.
   With an older driver, install GridLens from source with the `analysis-cu12` extra, as
   [Other Linux machines](install_dgx_os7.md#other-linux-machines) describes.
4. Install the x86_64 package in Ubuntu, as on any Ubuntu 24.04 machine:

   ```bash
   sudo apt install ./gridlens_<version>_amd64.deb
   gridlens
   ```

Keep projects in the distribution's own file system, such as `~/GridLensProjects`, which Windows sees as
`\\wsl.localhost\Ubuntu-24.04\home\<user>\GridLensProjects`. GridPACK writes multi-gigabyte result files
through the container's mount, and files under `/mnt/c` are much slower to write from WSL2.

Install Clarke's Ollama inside Ubuntu, as the **Set up Clarke** window does. GridLens accepts only an
Ollama on the loopback address, and with WSL2's default network an Ollama running on the Windows side is
not on the distribution's loopback address.

On WSL2, RAPIDS supports one GPU, and GPU Direct Storage is not available, so cuDF reads files through
the CPU. Neither changes the results.
