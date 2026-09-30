# DGX OS 7 install guide

This app targets DGX OS 7 systems based on Ubuntu 24.04, such as DGX Spark. It also runs on other ARM64 and
x86_64 Linux machines with an NVIDIA GPU; see [Other Linux machines](#other-linux-machines). For Windows,
see the [Windows install guide](install_windows.md).

## One-time system checks

```bash
cat /etc/os-release
uname -m
python3 --version
docker --version
docker info
```

The architecture maps to a Docker platform as follows:

```text
x86_64  -> linux/amd64
aarch64 -> linux/arm64
```

## Docker

Use Docker Engine on DGX OS 7. The app can run Docker without `sudo` only if your account has access to the
Docker socket. Adding a user to the `docker` group grants root-level host privileges through Docker, so ask
your IT or security team to approve it first.

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker run hello-world
```

If policy does not allow membership in the `docker` group, keep the app in a managed workstation account or
build an approved local service wrapper. Avoid asking regulators to run terminal commands during normal use.

## GridPACK image

Pull or load the image before you work with sensitive CEII inputs:

```bash
docker pull pnnl/gridpack:latest
```

In production, pin a versioned image instead of `latest`:

```text
your-registry/gridpack-ca:0.1.0
```

An offline environment can receive the image as a tarball:

```bash
docker load -i gridpack-ca-0.1.0-linux-arm64.tar
docker image inspect your-registry/gridpack-ca:0.1.0
```

## App install

Install the distributed package with `apt`, which downloads the Docker and shared-library dependencies for
you:

```bash
sudo apt install ./gridlens_0.1.0_arm64.deb
```

If the installer added your account to the `docker` group, log out and back in. Then run:

```bash
gridlens
```

The package bundles the GridLens Python libraries, including RAPIDS and cuDF for DGX Spark analysis. It does
not bundle the GridPACK Docker image, so load or pull the approved image before you run sensitive cases.

For development and packaging builds, see [Packaging and distribution](packaging_distribution.md).

## Other Linux machines

GridLens runs on any ARM64 or x86_64 Linux machine with an NVIDIA GPU, Docker, and a GridPACK image for its
architecture. `pnnl/gridpack:latest` and `v3.7.0`, which write the CSV flat output the analyses read, are
published for both `linux/amd64` and `linux/arm64`, as are `ca-scalability-v3` and `ca-scalability-v4`.

The package needs Ubuntu 24.04 or later, or another distribution with glibc 2.39 or later, because its
Python and PySide6 are built there; `apt` refuses it on an older system. Build a package for each
architecture on that architecture, as [Packaging and distribution](packaging_distribution.md) describes. On
an older distribution, such as Ubuntu 22.04, install from source with Python 3.11 or later.

The package's GPU analysis uses RAPIDS for CUDA 13, which needs NVIDIA driver 580 or later. Check the driver
with `nvidia-smi`. With an older driver, GridLens finds no usable GPU and offers CPU Dask. To use the GPU with
a CUDA 12 driver, install from source with the CUDA 12 extra:

```bash
python -m pip install -e ".[dev,analysis-cu12]"
```

GridLens sizes a single-GPU analysis to the memory the GPU can use. DGX Spark's GB10 shares the host's
memory, so the host's available memory decides there. A GPU with its own memory, such as Grace Hopper's or a
PCIe card's, is limited by its free device memory too, and a larger result file is analyzed in partitions
with dask-cuDF.

RAPIDS does not support Jetson Orin, so the analysis there runs on CPU Dask. On a Jetson with JetPack 5 or
6, the **Set up Clarke** window also installs Ollama's JetPack libraries, so Clarke's model runs on the GPU.

The script sandbox uses the Docker daemon that the `docker` command uses: `DOCKER_HOST`, or the current
docker context, such as rootless Docker's. It refuses a daemon reached over the network. The sandbox asks for
the `runc` runtime, which Podman's Docker compatibility may not provide.

GridLens is a desktop application. On a headless server, run it over a remote desktop or X forwarding.

