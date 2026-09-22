# Analysis sandbox image for approved generated scripts

GridLens never builds, pulls, or ships this image. An operator prepares it once on the machine that runs
GridLens, then pastes its immutable image ID into the script review dialog. Until that is done, the
approve-and-run path in the Agent tab fails closed with `SANDBOX_IMAGE_REQUIRED`.

## 1. Choose a base image, pinned by digest

Pick a small scientific-Python image that already has `python`, `pandas`, and `pyarrow`, and pin it by digest
(`repo@sha256:...`), not by tag. A tag can be re-pointed under you; the digest cannot.

This must **not** be the GridPACK solver image. The solver image carries MPI, CUDA libraries, and the
contingency binaries, none of which a reviewed analysis script needs, and reusing it would put the solver
toolchain inside a container that runs model-written code.

Get the digest of a base you already have locally:

    docker image inspect <base>:<tag> --format '{{index .RepoDigests 0}}'

## 2. Build

`ANALYSIS_BASE` is required and has no default, so the `--build-arg` is not optional — a bare
`docker build packaging/agent` fails with `base name (${ANALYSIS_BASE}) should not be blank`. That is
deliberate: `src/gridlens/agent/scripts.py` accepts only an immutable `sha256:<64 hex>` image ID, and a
default tag in the Dockerfile would contradict that pin.

    docker build --build-arg ANALYSIS_BASE=<base image pinned by digest, with pandas and pyarrow> \
      -t gridlens-analysis:0.1.0 packaging/agent

Verified on this machine (DGX Spark, Ubuntu 24.04, Docker 29.6.2, linux/arm64) with the RAPIDS base:

    docker build --build-arg ANALYSIS_BASE=rapidsai/base@sha256:c6c8424ecefd77bdf3d4058b42175cdf9f005d3ff3d58f0b8ce18b779ed4c895 \
      -t gridlens-analysis:0.1.0 packaging/agent

The build adds only the `org.gridlens.purpose=generated-analysis` label that GridLens checks, the
`python -I -B` entrypoint, `NVIDIA_VISIBLE_DEVICES=void`, a world-readable `/opt/conda` (RAPIDS-style bases
restrict it to their own user, and GridLens runs the container as the invoking host UID), and a trailing
`USER 65534:65534`. The image ships no GridLens code and no run data.

## 3. Read the image ID and paste it into GridLens

    docker image inspect gridlens-analysis:0.1.0 --format '{{.Id}}'
    sha256:e45ea8c8745fe71bffb8ac38689c3ad6e5cefbf1ce9e0f46e1682f117dbb06e4

Paste that whole `sha256:...` string into the "Approve and run" dialog. GridLens rejects tags and short IDs,
and it passes `--pull=never`, so the image must already exist in the local Docker daemon of the machine
running GridLens. Rebuilding produces a new ID; re-read it and paste the new one.

## 4. How GridLens runs it

Per execution GridLens creates a container with `--network none`, `--read-only`, `--cap-drop ALL`,
`--security-opt no-new-privileges:true`, `--user <host uid>:<host gid>`, no GPU, 2 CPUs, 1 GiB memory with
swap capped at the same value, 64 PIDs, `nofile`/`fsize`/`cpu` ulimits, tmpfs `/tmp` and `/output`, the run
directory bind-mounted read-only at `/run-data`, and the approved script bind-mounted read-only at
`/analysis.py`. It refuses to run at all if GridLens itself is running as root. Script output is treated as
untrusted and is recorded with its SHA-256 in the session audit log.

## 5. Optional: verify the image against the real sandbox path

With Docker available and the image built:

    GRIDLENS_TEST_SANDBOX_IMAGE=$(docker image inspect gridlens-analysis:0.1.0 --format '{{.Id}}') \
      .venv/bin/python -m pytest tests/test_agent_scripts.py -q

That runs the opt-in isolation test, which asserts from inside the container that it is non-root, has no
NVIDIA devices, no Docker socket, no network, a read-only input mount, and the expected memory/PID/file-size
limits, and that the timeout and output-cap paths remove their containers.
