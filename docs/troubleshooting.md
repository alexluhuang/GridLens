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

## Docker on Windows

If the Run tab's Docker check says the engine is not reachable, start Docker Desktop and check again. Docker
on Windows is an application, not a service, so it is not running until someone starts it.

If the check says Docker runs Windows containers, open Docker Desktop's tray menu and choose **Switch to
Linux containers**. GridPACK images are Linux images.

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
docker run --rm --mount "type=bind,source=$PWD,target=/app/workspace" -w /app/workspace \
  pnnl/gridpack:latest mpirun -n 4 ca.x input.xml
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

The tab states the remedy for most problems in the line above the conversation, next to **Set up
Clarke…**. The entries here cover what it cannot tell you from inside the app.

### Set up Clarke stops while installing

The window's log shows the installer's own output. The Hermes installer needs `git`, and unpacking Ollama
on Linux needs `zstd`; install them (`sudo apt install git zstd`) and press the install button again. Both
downloads need internet access to hermes-agent.nousresearch.com, github.com, and ollama.com. On a machine
without it, install Hermes Agent 0.21.4, Ollama, and a model from approved media, and GridLens uses them.

### The runtime check reports a version it does not support

Each adapter is pinned to the CLI version it was tested against and refuses anything else rather than guess
at a changed output format. Upgrading Hermes therefore disables the tab until someone validates the adapter
against the new version. **Set up Clarke…** reinstalls the supported version; note that it updates the
Hermes checkout in `~/.hermes/hermes-agent` for every use of Hermes on this account.

### Ollama is running, but no models are listed

GridLens lists only local models that report tool support, and hides Ollama cloud models by design. Confirm
what Ollama offers:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

If a model you expect is missing from that output, install it from **Install or remove models…** at the end
of the **Local model** list. If it appears there but not in
GridLens, it does not advertise the `tools` capability and cannot drive the agent.

### The endpoint is refused even though Ollama answers

GridLens resolves the endpoint before it sends anything and fails closed unless every resolved address is
loopback. A hostname that resolves to a LAN address is rejected on purpose, as is an `http_proxy` setting
that would redirect local inference. Use `http://127.0.0.1:11434`.

### Answers stop at "analysis is not built"

The tools read the compact analysis cache, never the multi-gigabyte flat result, and they refuse a stale
cache rather than quote numbers from it. Ask Clarke to prepare the run for analysis, or click **Generate
Graphs** in the Branch or Transformer Analysis tab. A cache built by an older GridLens version counts as
stale, so a run that used to work needs rebuilding after an upgrade.

### Contingency drill-down says the index is missing or stale

The per-contingency and per-branch tools need the optional Parquet index. Ask Clarke to build the run's
contingency drill-down index. The index records the size and modification
time of the flat result it was built from, so re-running the case invalidates it and you have to rebuild.

### Approving a script reports that the sandbox image is required

GridLens never builds or pulls the analysis image. Prepare it once and paste its `sha256:` ID into the review
dialog, as described in `packaging/agent/README.md`. GridLens rejects a tag or a short ID, and passes
`--pull=never`, so the image has to exist in the local Docker daemon.

### A hosted runtime cannot be selected

Codex and Claude Code are disabled in this build. Sending project-derived data to an online model conflicts
with the local-only rule, and turning that rule off is a written governance decision rather than a setting.
See [CEII security notes](security_ceii.md).

### A cufile.log file appears

The GPU file reader used by the analysis writes a diagnostic log. GridLens sends it to
`~/.cache/gridlens/cufile.log`, or under `$XDG_CACHE_HOME`, so it no longer appears beside run or job files.
Set `CUFILE_LOGFILE_PATH` to put it somewhere else.

## The analysis uses CPU Dask on a machine with an NVIDIA GPU

GridLens uses the GPU only when the CUDA runtime reports a usable device. The warning before the analysis
names the reason: RAPIDS is not installed, or RAPIDS is installed but there is no usable NVIDIA GPU. For the
second, check that:

- `nvidia-smi` lists the GPU. Inside a container or WSL2, the GPU has to be passed through.
- The driver is version 580 or later, which the CUDA 13 build of RAPIDS needs. With an older driver,
  install from source with the `analysis-cu12` extra; see the [DGX OS 7 install guide](install_dgx_os7.md).
- `CUDA_VISIBLE_DEVICES` is not set to an empty value.

On native Windows the analysis always runs on CPU Dask, because RAPIDS has no Windows build. For GPU
analysis there, use WSL2; see the [Windows install guide](install_windows.md).

## A project folder is refused on Windows

Windows reserves `CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, and `LPT1` to `LPT9` as device names, so no
folder can have one of them. GridLens suggests `CON_Project` for a project named `CON`.

Windows also does not tell folder names apart by case, so `test` and `Test` are one folder. GridLens refuses
a new project whose folder differs from an existing one only in case, because saving it would change the
existing project. Choose another name.
