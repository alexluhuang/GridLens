# DGX OS 7 install guide

This app targets DGX OS 7 systems based on Ubuntu 24.04. It works on x86_64 DGX servers and on ARM64 DGX
Spark systems, as long as Docker Engine and a matching GridPACK image are available.

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
