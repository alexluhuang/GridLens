# Troubleshooting

## Docker permission denied

Symptom:

```text
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

Cause: your account cannot reach Docker Engine.

Fixes:

- Ask your IT or security team to approve Docker group access.
- Log out and back in after `usermod -aG docker`.
- Use a managed service account or an approved local service wrapper.

If `/etc/group` already lists your username in the `docker` group but `id` does not, your login session has
stale group membership. Run:

```bash
newgrp docker
docker ps
python3 scripts/check_environment.py
```

If that works, close the old terminal and continue in the new shell. Logging out and back in also refreshes
group membership.

Docker normally creates `/var/run/docker.sock` for the `docker` group. Check it:

```bash
ls -l /var/run/docker.sock
```

Expect this shape:

```text
srw-rw---- 1 root docker ... /var/run/docker.sock
```

If another group owns the socket, restart Docker and check again:

```bash
sudo systemctl restart docker
ls -l /var/run/docker.sock
```

## Image not available

The app defaults to `--pull=never`, so a run fails when the image is missing.

Fix:

```bash
docker pull pnnl/gridpack:latest
```

Or load an approved image tarball:

```bash
docker load -i gridpack-ca-0.1.0-linux-arm64.tar
```

## Output files owned by root

The app runs Docker with `-u uid:gid` by default. If older runs produced root-owned files, fix the ownership
from an admin shell:

```bash
sudo chown -R "$USER:$USER" ~/GridLensProjects
```

## MPI fails in the container

Confirm the manual command works first:

```bash
docker run --rm -v "$PWD:/app/workspace" -w /app/workspace pnnl/gridpack:latest \
  mpirun -n 4 ca.x input.xml
```

Then compare it with the command recorded in `manifest.json` and `logs/run.log`.

## GUI does not start

Install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
gridlens
```

On a minimal Ubuntu system, Qt may also need desktop libraries that IT installs through apt.

## Agent tab

The tab states the remedy for most problems in its diagnostics line. The entries here cover what it cannot
tell you from inside the app.

### The runtime check reports a version it does not support

Each adapter is pinned to the CLI version it was tested against and refuses anything else rather than guess
at a changed output format. Upgrading Hermes therefore disables the tab until someone validates the adapter
against the new version. Either reinstall the supported version or open an issue with the version you have.

### Ollama is running, but no models are listed

GridLens lists only local models that report tool support, and hides Ollama cloud models by design. Confirm
what Ollama offers:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

If a model you expect is missing from that output, pull it yourself. If it appears there but not in
GridLens, it does not advertise the `tools` capability and cannot drive the agent.

### The endpoint is refused even though Ollama answers

GridLens resolves the endpoint before it sends anything and fails closed unless every resolved address is
loopback. A hostname that resolves to a LAN address is rejected on purpose, as is an `http_proxy` setting
that would redirect local inference. Use `http://127.0.0.1:11434`.

### Answers stop at "analysis is not built"

The tools read the compact analysis cache, never the multi-gigabyte flat result, and they refuse a stale
cache rather than quote numbers from it. Click **Build / refresh analysis** in the Agent tab. A cache built
by an older GridLens version counts as stale, so a run that used to work needs rebuilding after an upgrade.

### Contingency drill-down says the index is missing or stale

The per-contingency and per-branch tools need the optional Parquet index. Select **Include contingency
drill-down index**, then click **Build / refresh analysis**. The index records the size and modification
time of the flat result it was built from, so re-running the case invalidates it and you have to rebuild.

### Approving a script reports that the sandbox image is required

GridLens never builds or pulls the analysis image. Prepare it once and paste its `sha256:` ID into the review
dialog, as described in `packaging/agent/README.md`. GridLens rejects a tag or a short ID, and passes
`--pull=never`, so the image has to exist in the local Docker daemon.

### A hosted runtime cannot be selected

Codex and Claude Code are disabled in this build. Sending project-derived data to an online model conflicts
with the local-only rule, and turning that rule off is a written governance decision rather than a setting.
See [CEII security notes](security_ceii.md).
