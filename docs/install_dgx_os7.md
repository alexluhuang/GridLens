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

Development install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
gridpack-workbench
```

Production install should use the `.deb` built from `docs/packaging_distribution.md`.
