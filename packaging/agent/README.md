# Analysis sandbox image for approved generated scripts

GridLens never builds, pulls, or ships this image. You prepare it once on the machine that runs GridLens,
then paste its immutable image ID into the script review dialog. Until you do, the approve-and-run path in
the Agent tab fails closed with `SANDBOX_IMAGE_REQUIRED`.

## 1. Choose a base image, pinned by digest

Pick a small scientific-Python image that already has `python`, `pandas`, and `pyarrow`. Pin it by digest
(`repo@sha256:...`) rather than by tag, because someone can re-point a tag under you and cannot re-point a
digest.

Do not use the GridPACK solver image. It carries MPI, CUDA libraries, and the contingency binaries, none of
which a reviewed analysis script needs, and reusing it would put the solver toolchain inside a container
that runs model-written code.

To read the digest of a base you already have locally:

```bash
docker image inspect <base>:<tag> --format '{{index .RepoDigests 0}}'
```

## 2. Build

`ANALYSIS_BASE` is required and has no default, so the `--build-arg` is not optional. A bare
`docker build packaging/agent` fails with `base name (${ANALYSIS_BASE}) should not be blank`. That is
deliberate: `src/gridlens/agent/scripts.py` accepts only an immutable `sha256:<64 hex>` image ID, and a
default tag in the Dockerfile would contradict that pin.

```bash
docker build --build-arg ANALYSIS_BASE=<base image pinned by digest, with pandas and pyarrow> \
  -t gridlens-analysis:0.1.0 packaging/agent
```

This was verified on a DGX Spark running Ubuntu 24.04, Docker 29.6.2, and linux/arm64, using the RAPIDS base:

```bash
docker build --build-arg ANALYSIS_BASE=rapidsai/base@sha256:c6c8424ecefd77bdf3d4058b42175cdf9f005d3ff3d58f0b8ce18b779ed4c895 \
  -t gridlens-analysis:0.1.0 packaging/agent
```

The build adds the `org.gridlens.purpose=generated-analysis` label that GridLens checks, the `python -I -B`
entrypoint, `NVIDIA_VISIBLE_DEVICES=void`, a world-readable `/opt/conda`, and a trailing `USER 65534:65534`.
The `/opt/conda` change matters because RAPIDS-style bases restrict its directories and some of its files to
their own user and group, and GridLens runs the container as the invoking host UID. An image built before
2026-09-24 opened only three directories, so `import pyarrow` failed as a normal user: it could not load
`libxml2.so.16`, one of about 5,000 files readable only by the `conda` group. Rebuild such an image. The image
ships no GridLens code and no run data.

Check that a normal user can import what scripts use:

```bash
docker run --rm --network none --user 65534:65534 <image ID> -c "import pandas, pyarrow.dataset; print('ok')"
```

## 3. Read the image ID and paste it into GridLens

```bash
docker image inspect gridlens-analysis:0.1.0 --format '{{.Id}}'
sha256:e45ea8c8745fe71bffb8ac38689c3ad6e5cefbf1ce9e0f46e1682f117dbb06e4
```

Paste that whole `sha256:...` string into the **Approve this script and run** dialog. GridLens rejects tags
and short IDs, and it passes `--pull=never`, so the image has to exist already in the local Docker daemon of
the machine running GridLens. Rebuilding produces a new ID, so read it again and paste the new one.

## 4. How GridLens runs it

For each execution, GridLens creates a container with `--network none`, `--read-only`, `--cap-drop ALL`,
`--security-opt no-new-privileges:true`, `--user <host uid>:<host gid>`, no GPU, 2 CPUs, 1 GiB of memory with
swap capped at the same value, 64 PIDs, `nofile`, `fsize`, and `cpu` ulimits, a tmpfs at `/tmp` and
`/output`, the run directory bind-mounted read-only at `/run-data`, and the approved script bind-mounted
read-only at `/analysis.py`. It refuses to run at all if GridLens itself is running as root. GridLens treats
script output as untrusted and records it with its SHA-256 in the session audit log.

## 5. Optional: verify the image against the real sandbox path

With Docker available and the image built:

```bash
GRIDLENS_TEST_SANDBOX_IMAGE=$(docker image inspect gridlens-analysis:0.1.0 --format '{{.Id}}') \
  .venv/bin/python -m pytest tests/test_agent_scripts.py -q
```

That runs the opt-in isolation test. From inside the container, it asserts that the process is non-root and
has no NVIDIA devices, no Docker socket, no network, a read-only input mount, and the expected memory, PID,
and file-size limits. It also asserts that the timeout and output-cap paths remove their containers.
