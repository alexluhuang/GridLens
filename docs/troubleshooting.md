# Troubleshooting

## Docker Permission Denied

Symptom:

```text
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

Cause: the current user cannot access Docker Engine.

Fix options:

- Ask IT/security to approve Docker group access.
- Log out and back in after `usermod -aG docker`.
- Use a managed service account or approved local service wrapper.

If `/etc/group` already lists your username in the `docker` group but `id` does not, your current login session has stale group membership. Run:

```bash
newgrp docker
docker ps
python3 scripts/check_environment.py
```

If that works, close the old terminal and continue in the new shell. A full logout/login also refreshes group membership.

Docker normally creates `/var/run/docker.sock` for group `docker`. Check it with:

```bash
ls -l /var/run/docker.sock
```

Expected shape:

```text
srw-rw---- 1 root docker ... /var/run/docker.sock
```

If the socket is owned by another group, restart Docker and re-check:

```bash
sudo systemctl restart docker
ls -l /var/run/docker.sock
```

## Image Not Available

The app defaults to `--pull=never`, so a run fails if the image is missing.

Fix:

```bash
docker pull pnnl/gridpack:latest
```

or load an approved image tarball:

```bash
docker load -i gridpack-ca-0.1.0-linux-arm64.tar
```

## Output Files Owned By Root

The app runs Docker with `-u uid:gid` by default. If old runs produced root-owned files, fix ownership from an admin shell:

```bash
sudo chown -R "$USER:$USER" ~/GridPACKWorkbenchProjects
```

## MPI Fails In Container

Confirm the manual command works first:

```bash
docker run --rm -v "$PWD:/app/workspace" -w /app/workspace pnnl/gridpack:latest \
  mpirun -n 4 ca.x input.xml
```

Then compare it with the command recorded in `manifest.json` and `logs/run.log`.

## GUI Does Not Start

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
gridpack-workbench
```

On minimal Ubuntu systems, Qt may also need desktop libraries installed by IT through apt.
