# DGX OS 7 Install Guide

This app targets DGX OS 7 systems based on Ubuntu 24.04. It should work on x86_64 DGX servers and ARM64 DGX Spark systems as long as Docker Engine and the matching GridPACK image are available.

## One-Time System Checks

```bash
cat /etc/os-release
uname -m
python3 --version
docker --version
docker info
```

Architecture mapping:

```text
x86_64  -> linux/amd64
aarch64 -> linux/arm64
```

## Docker

Use Docker Engine on DGX OS 7. The app can run Docker without `sudo` only if the user has Docker socket access. Adding a user to the `docker` group grants root-level host privileges through Docker, so this should be approved by the organization's IT/security team.

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker run hello-world
```

If policy does not allow Docker group membership, keep the app in a managed workstation account or build an approved local service wrapper. Avoid prompting regulators for terminal commands during normal use.

## GridPACK Image

Pull or load the image before sensitive CEII inputs are used:

```bash
docker pull pnnl/gridpack:latest
```

For production, pin a versioned image instead of using `latest`:

```text
your-registry/gridpack-ca:0.1.0
```

Offline environments can receive an image tarball:

```bash
docker load -i gridpack-ca-0.1.0-linux-arm64.tar
docker image inspect your-registry/gridpack-ca:0.1.0
```

## App Install

Install the distributed package with `apt` so Docker and shared-library dependencies are downloaded automatically:

```bash
sudo apt install ./gridlens_0.1.0_arm64.deb
```

Log out and back in if the installer added your account to the `docker` group, then run:

```bash
gridlens
```

For development and packaging builds, see `docs/packaging_distribution.md`.

The package bundles GridLens Python libraries, including RAPIDS/cuDF for DGX Spark analysis. It does not bundle the
GridPACK Docker image; load or pull the approved image before running sensitive cases.
