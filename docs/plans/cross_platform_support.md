# Running GridLens on ARM64 Linux and Windows x64 (review of 2026-09-29)

GridLens runs today on one platform: DGX Spark, which is DGX OS 7 (Ubuntu 24.04) on ARM64 with an NVIDIA GB10
GPU. This review covers every source file, packaging file, test, and dependency. It lists what has to change so
that GridLens runs on two more kinds of machine:

- **ARM64 Linux in general**: Ubuntu and similar distributions on ARM machines other than DGX Spark, with or
  without an NVIDIA GPU. Examples are Grace Hopper servers, ARM workstations with PCIe GPUs, cloud ARM servers,
  and Jetson.
- **Windows x64**: the PCs that planners and regulators mostly use.

The findings come from reading the code and from five checks, all run on the DGX Spark:

1. The PyPI release files of all 111 installed packages were checked for `linux_aarch64`, `linux_x86_64`, and
   `win_amd64` wheels.
2. Docker Hub was queried for the platforms published for each GridPACK tag, and `docker buildx imagetools
   inspect` was run on the sandbox base image.
3. The test suite was run with the POSIX-only Python APIs removed (`fcntl`, `resource`, `os.O_NOFOLLOW`,
   `os.setsid`, `os.killpg`, `os.getuid`, `os.WNOHANG`, `signal.SIGKILL`) to find the code paths that fail on
   Windows.
4. The test suite was run in a CPU-only virtual environment with the versions a Windows install resolves today:
   no RAPIDS, pandas 3.0.6, pyarrow 25.0.1, and numpy 2.5.3.
5. A real 168 MB run (`MemphisCase2026`, a copy in a temporary folder) was analyzed once with the GPU
   environment and once with the CPU-only environment, and the results were compared.

Section 9 lists what could not be checked from here and needs real hardware.

## 1. Summary

| Target | State today | Work needed |
|---|---|---|
| DGX Spark (ARM64, GB10, CUDA 13) | Works | None |
| Other ARM64 Linux | Mostly works. Three things fail silently: the analysis on machines without a usable GPU, the analysis on machines with a discrete GPU, and installs on Python 3.10 or older glibc | Small: §4 |
| Windows x64, running the Linux build inside WSL2 | Needs a Linux x86_64 build; the code already runs there | Small to medium: §6 |
| Windows x64, native | Does not start: `import fcntl` fails when the main window loads | Medium to large: §5 and §7 |

The GridPACK solver is not a blocker. It always runs as a Linux container. `pnnl/gridpack:latest`, `v3.7.0`,
`ca-scalability-v3`, and `ca-scalability-v4` are published for both `linux/amd64` and `linux/arm64`. GridLens
already maps the host to the right `--platform` value, including Windows's `AMD64`
(`src/gridlens/core/run_manifest.py:10`). Docker Desktop on Windows runs these images in its WSL2 VM.

The real limits are these:

- **RAPIDS has no native Windows build.** `cudf-cu13`, `dask-cuda`, `rmm-cu13`, `pylibcudf-cu13`,
  `libcudf-cu13`, `libkvikio-cu13`, `librmm-cu13`, `rapids-logger`, and `nvidia-nccl-cu13` publish Linux wheels
  only. GPU analysis on Windows therefore needs WSL2. Native Windows GridLens can use only the CPU Dask backend.
- **The agent layer is written against POSIX.** It uses process groups, `O_NOFOLLOW`, `flock`, `select` on
  pipes, and a Unix Docker socket. That code is where most of the native-Windows work lies.

## 2. What already works everywhere

These were checked and need no change:

- **Non-RAPIDS wheels.** Every dependency outside RAPIDS has `linux_aarch64`, `linux_x86_64`, and `win_amd64`
  wheels. That covers PySide6 6.11, mcp 1.30, pandas, pyarrow, dask, distributed, matplotlib, numpy, psutil,
  and PyInstaller. On Windows, `mcp` also installs `pywin32`, which has wheels.
- **CUDA Python wheels.** `cupy-cuda13x`, `numba-cuda`, `cuda-toolkit`, `cuda-bindings`, and the `nvidia-*` CUDA
  wheels have Windows builds. cuDF does not, so they do not make GPU analysis possible on native Windows.
- **Sandbox base image.** `rapidsai/base@sha256:c6c8424e…`, the base that `packaging/agent/README.md` pins, is a
  multi-platform index with `linux/amd64` and `linux/arm64` manifests. The same pin builds the sandbox on an x86
  host.
- **Portable Python code.** The Qt code is portable: the Fusion style, `QFileDialog`, `QDesktopServices`, and
  fonts that fall back to Arial, Segoe UI, and Consolas. File I/O names its encoding almost everywhere. RAW
  cases are read and written with `newline=""`, so line endings are kept (`src/gridlens/psse/parse.py:95`,
  `:101`). `multiprocessing` uses the `spawn` context, and `main()` calls `freeze_support()`.
- **Windows setup branches.** `src/gridlens/agent/setup.py` already handles Windows:
  - It installs Ollama with `OllamaSetup.exe /VERYSILENT` into `%LOCALAPPDATA%\Programs\Ollama`.
  - It installs Hermes with `install.ps1 -NonInteractive -SkipBrowser -SkipComputerUse -Commit <sha>`. All four
    parameters exist in the current script.
  - It starts `ollama serve` with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`.

  `hermes_executable()` also looks in `%LOCALAPPDATA%\hermes\bin`. Hermes documents native Windows support. The
  Hermes and Ollama download URLs for Windows and for Linux ARM64 all return HTTP 200.
- **CPU-only dependency set.** In the CPU-only environment with pandas 3.0.6, pyarrow 25, and numpy 2.5, the
  suite gives 389 passed, 7 skipped, and 1 failed. The two extra skips are the cuDF-only event-index tests. The
  failure (`test_an_automatic_build_that_fails_says_so_in_the_status_line`) assumes RAPIDS is installed: it does
  not expect the CPU-fallback warning dialog. The code itself works with the newer libraries.
- **CPU and GPU results.** On the Memphis run, the CPU Dask analysis and the GPU cuDF analysis produced the same
  974 branch rows and 407 transformer rows, with the same loadings. The one difference is in §4.6.

## 3. Dependencies

`pyproject.toml` declares `requires-python = ">=3.10"` and lists Python 3.10 and `Operating System :: POSIX ::
Linux` as classifiers. The `analysis` extra pins RAPIDS for CUDA 13.

| Package | ARM64 Linux | Windows x64 | Note |
|---|---|---|---|
| PySide6 6.11 | yes (manylinux_2_39) | yes | The ARM64 wheels of 6.8.1 and later need glibc 2.39, which means Ubuntu 24.04 or later. With older glibc, pip falls back to 6.8.0.2 (glibc 2.31) |
| mcp 1.30.0 | yes | yes | Installs `pywin32` on Windows |
| cudf-cu13, pylibcudf-cu13, libcudf-cu13, rmm-cu13, librmm-cu13, libkvikio-cu13, rapids-logger | yes | **no** | Linux only. The cuDF wheels need Python 3.11 or later |
| dask-cuda 26.6 | yes | **no** | One Linux-only wheel. Needs Python 3.11 or later |
| nvidia-nccl-cu13 | yes | **no** | Linux only |
| dask-cudf-cu13, rapids-dask-dependency | pure Python | pure Python | Useless without cuDF |
| cupy-cuda13x, numba-cuda, cuda-toolkit, cuda-bindings, nvidia CUDA wheels | yes | yes | CUDA 13 needs NVIDIA driver 580.65.06 or later, on Linux and on WSL2 |
| pandas, pyarrow, numpy, dask, distributed, matplotlib | yes | yes | Unbounded. Without cuDF, pip resolves pandas 3.0.6, pyarrow 25.0.1, and numpy 2.5.3. With cuDF, it resolves pandas below 2.4 and pyarrow below 24 |
| pyinstaller 6 | yes | yes | |

What has to change:

1. **Raise the Python floor to 3.11.** cuDF 26.6, dask-cuda 26.6, numpy 2.4 and later, matplotlib 3.11, and
   pandas 3 all need Python 3.11 or later. `pip install -e ".[analysis]"` therefore fails on Ubuntu 22.04's
   Python 3.10, which the metadata claims to support. Update the classifiers, and drop the `tomli` fallback in
   `tests/test_package_metadata.py` together with the `dev` extra's `tomli` entry.
2. **Split the GPU stack out of `analysis`.** A single extra cannot be installed on Windows. Two options:
   - Add `; sys_platform == "linux"` markers to the RAPIDS lines.
   - Better: split the extra in two. `analysis` would hold pandas, pyarrow, dask, distributed, matplotlib, and
     psutil, and install everywhere. `gpu` would hold the RAPIDS and CUDA packages, on Linux only.

   Update `requirements-analysis.txt`, `tests/test_package_metadata.py`, `tests/test_debian_packaging.py`, and
   `build_deb.sh` to match. A CUDA 12 variant of `gpu` (`cudf-cu12`, and so on) would cover machines whose
   driver is older than 580: many x86 DGX servers, ARM servers, and WSL2 PCs.
3. **Lock versions for each platform.** Today the Linux GPU build runs pandas 2.3.3 and pyarrow 23, and a
   Windows build would run pandas 3.0.6 and pyarrow 25. The unit tests pass on both, but the two platforms
   should not run different major versions without anyone deciding so. Choose one:
   - Cap `pandas<2.4` and `pyarrow<24` everywhere until RAPIDS allows newer versions.
   - Keep a lock file for each platform, for example with `uv lock` or `pip-compile`, and use it to build each
     artifact.
4. **Add the helper libraries that the Windows work in §5 needs** as core dependencies:
   - `psutil`, for process trees and liveness. It is already installed with `distributed`.
   - `filelock`, for cross-platform locks.
   - `platformdirs`, for per-OS config, cache, and data folders. Its Linux defaults are the XDG folders GridLens
     already uses, so Linux paths do not move.

## 4. ARM64 Linux beyond DGX Spark

1. **A missing GPU sends the analysis to the slowest path.** `_gpu_backends_unavailable()`
   (`src/gridlens/analysis/csv_flat.py:1088`) only checks whether `cudf` and `dask_cudf` can be imported.
   Checked with `CUDA_VISIBLE_DEVICES=` (no visible device): `import cudf` succeeds with only a warning, so
   GridLens decides a GPU is available. It then:
   - never offers the CPU Dask backend;
   - tries cuDF, which fails with `cudaErrorNoDevice`;
   - falls back to single-threaded Python streaming ("Accelerated csv_flat aggregation with auto failed and
     Python streaming was used").

   This happens wherever RAPIDS is installed but no usable GPU exists. The `.deb` always bundles RAPIDS, so it
   happens on every ARM64 machine without an NVIDIA GPU, and on machines whose driver is older than 580. Fix:
   check for a device once, with `cupy.cuda.runtime.getDeviceCount()` inside a `try`, and treat a failure as
   "GPU unavailable".
2. **The backend choice assumes unified memory.** `_should_partition_with_dask_cudf()` (`csv_flat.py:1072`)
   compares the CSV's size with the host's `MemAvailable` from `/proc/meminfo`. That works on DGX Spark, where
   the CPU and the GPU share one 128 GB pool. It is wrong wherever the GPU has its own memory: Grace Hopper (its
   HBM is separate from host LPDDR), any PCIe GPU, and WSL2. On those machines, a CSV smaller than 75% of host
   RAM but larger than GPU memory goes to single-GPU `cudf.read_csv` and runs out of device memory. Fix: base
   the decision on free device memory (`cupy.cuda.Device().mem_info`), unless the device reports itself as
   integrated.
3. **`get_pandas()` catches only `ModuleNotFoundError`** (`src/gridlens/analysis/gpu_pandas.py:10`). A cuDF that
   is installed but broken, for example with a driver that is too old, can raise other exceptions from
   `cudf.pandas.install()`. Catch `Exception` there, as `_backend_importable` already does.
4. **The `.deb` needs glibc 2.39.** The bundle is built on Ubuntu 24.04 and contains PySide6's `manylinux_2_39`
   ARM64 wheels. Either document "Ubuntu 24.04 or later, ARM64" as the supported target, or build on an older
   base. The same applies to `docs/install_dgx_os7.md`, which says the app works on x86_64 DGX servers. Those
   servers also need an x86_64 build (§6) and, with the cu13 pins, driver 580.
5. **Split the package, too.** The `.deb` bundles several GB of RAPIDS even for machines without a GPU. With the
   extras split as in §3, build `gridlens` (CPU) and `gridlens-gpu` packages, or keep one package and rely on
   the device check in item 1.
6. **The "worst contingency" depends on the backend.** On the Memphis run, the CPU and GPU analyses agreed on
   every loading. They disagreed on `max_contingency` for 2 of 974 branch rows and 364 of 407 transformer rows.
   Every one of those rows is a tie, where several events share the maximum loading (for example, a transformer
   loaded 0.00% in all 1,225 events). The CPU backend reports event 0; cuDF reports whichever tied row comes
   first after a merge, such as event 2 or 5. The cause is `_lazy_extreme_label_frame()` (`csv_flat.py:644`),
   which takes `"first"` after `merge` and `groupby`. Row order after those operations is not defined on the GPU.
   A Windows machine (CPU) and a DGX Spark (GPU) would therefore name different worst contingencies for the
   same run. Fix: take the lowest `event_idx` among the tied rows, then attach its contingency name.
7. **Container runtimes other than rootful Docker fail the script sandbox.** `src/gridlens/agent/scripts.py:34`
   pins `unix:///var/run/docker.sock`, and `:179` passes `--runtime runc`. Rootless Docker, whose socket is
   `$XDG_RUNTIME_DIR/docker.sock`, fails, and so do Docker Desktop for Linux and Podman (which uses `crun`, and is
   the default on RHEL-family ARM servers). The GridPACK runner uses the user's Docker context and is not
   affected. Fix: resolve the endpoint from `docker context inspect`, check that it is local, and pass that
   endpoint.
8. **Jetson is not covered.** RAPIDS wheels target SBSA systems such as DGX Spark and Grace Hopper, not Jetson
   Orin. Ollama publishes `ollama-linux-arm64-jetpack6.tar.zst` and `-jetpack5` builds (both return HTTP 200)
   for GPU inference on Jetson. `install_ollama()` always downloads the generic `ollama-linux-arm64.tar.zst`,
   which runs on the CPU on Jetson. This matters only if Jetson is a target.
9. **GPU GridPACK images are separate.** The cuDSS GridPACK images (`alh360/griddsspack:*-arm64`,
   `gridpack-cudss-arm64:*`) are ARM64 only and are not published. GridLens never adds `--gpus`; a GPU solver
   run relies on the user's extra Docker arguments. Another architecture needs its own build of that image.
   This is outside GridLens's code.
10. **Headless ARM servers need a remote display** (X forwarding, VNC, or similar). GridLens has no headless
    mode apart from the MCP and job entry points.

## 5. Native Windows: code changes

With `fcntl` removed, 13 test modules fail to import. With `fcntl` importable but raising on use, and the other
POSIX attributes removed, the results are 21 failed and 93 errors, 105 of them from `os.O_NOFOLLOW`. With
`O_NOFOLLOW` replaced by 0, the next layer is 85 failures:

| Failures | Cause |
|---:|---|
| 68 | `fcntl.flock` |
| 11 | `os.WNOHANG` |
| 8 | `os.killpg` |
| 4 | `signal.SIGKILL` |
| 4 | `os.getuid` |

The list below is ordered by what blocks first. Most items fit in one small module, for example
`gridlens/core/platform.py`, which the agent, analysis, and runner code would call instead of `os` and
`signal`.

### 5.1 Blocks startup or every agent action

1. **`import fcntl` at module level**, in `src/gridlens/analysis/service.py:3` and
   `src/gridlens/agent/tool_base.py:17`. Importing `gridlens.gui.main_window` fails through `analysis_tab` →
   `analysis.service`; this was confirmed by importing it with `fcntl` blocked. Replace both locks with
   `filelock`, or with a helper that uses `msvcrt.locking` on Windows:
   - `service.py:53` locks the analysis builds, one at a time across processes.
   - `tool_base.py:168` locks the audit, where the call ID is counted under the lock.
2. **`os.O_NOFOLLOW`** in `session.py:99` and `:108`, `jobs.py:75`, `conversation_log.py:244`,
   `tool_base.py:168` and `:267`, and `service.py:54`. Every session, audit, and job write uses it. Replace it
   with `getattr(os, "O_NOFOLLOW", 0)`, plus an `os.lstat` check before opening on Windows that refuses a
   symlink or a reparse point (`stat.FILE_ATTRIBUTE_REPARSE_POINT`). `scoped_path` already refuses symlinks
   along the path. Creating a symlink on Windows also needs administrator rights or Developer Mode.
3. **Reading pipes with `selectors`**, in `src/gridlens/agent/controller.py:116` and `scripts.py:64`. On Windows,
   `select()` accepts only sockets, so every agent turn and every sandbox run would fail with WinError 10038. The
   simulation cannot show this, because pipes can be selected on Linux. Replace it with one reader thread per
   stream feeding a queue, and keep the existing wall-clock deadline, byte caps, and stderr tail.
4. **Process groups.** Three things fail:
   - `os.setsid()` (`service.py:18`) and `os.killpg()` (`process.py:56` and `:64`, `jobs.py:235`,
     `service.py:35` and `:41`) do not exist on Windows.
   - `signal.SIGKILL` does not exist on Windows.
   - `start_new_session=True` is silently ignored on Windows (`process.py:77`, `jobs.py:206`, `hermes.py:175`,
     `claude_code.py:160`, `scripts.py:223`).

   On Windows:
   - Start each child with `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`.
   - Put a runtime and its MCP server in a Job Object, and kill the tree by closing the job. `psutil`'s
     `children(recursive=True)` is a simpler fallback, but it can miss processes that start while it runs.
   - Start job workers with `CREATE_BREAKAWAY_FROM_JOB`, so they outlive the MCP server that started them (§9).
5. **Worker liveness**, in `jobs.py:128–148`. `os.waitpid(pid, os.WNOHANG)` fails, because Windows `waitpid`
   takes a process handle and has no `WNOHANG`. `os.kill(pid, 0)` is not a liveness probe on Windows, where
   signal 0 is `CTRL_C_EVENT`. Use `psutil.pid_exists`, and compare the process's creation time with the record
   so that a reused PID is not mistaken for the worker.
6. **Cancelling a job** relies on a `SIGTERM` handler (`jobs.py:391`). Windows cannot deliver that signal to
   another process: `os.kill` with `SIGTERM` calls `TerminateProcess`, which kills the worker before it records
   the cancellation and leaves its analysis child running. Use a portable channel instead: `cancel_job` writes
   a `cancel` file in the job folder, and the worker polls for it. Kill the process tree only after the grace
   period.
7. **The minimal child environment**, in `process.py:22`. It keeps `PATH`, `HOME`, `USER`, `LANG`, `LC_ALL`, and
   `TMPDIR`. On Windows, a child also needs `SYSTEMROOT`, `WINDIR`, `SYSTEMDRIVE`, `COMSPEC`, `PATHEXT`, `TEMP`,
   `TMP`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`, `LOCALAPPDATA`, `PROGRAMDATA`, `USERNAME`, and
   `PROCESSOR_ARCHITECTURE`. Without `SYSTEMROOT`, Winsock does not initialize, so Hermes cannot reach Ollama
   and the MCP stdio loop cannot start. Without `USERPROFILE` and `APPDATA`, the CLIs cannot find their
   configuration, and `Path.home()` fails. Keep one allowlist per OS. `LD_LIBRARY_PATH_ORIG` (`:28`) applies to
   Linux only.

### 5.2 Script sandbox (`src/gridlens/agent/scripts.py`)

The rest of the agent works without the sandbox, so this can come after §5.1:

- `DOCKER_HOST = "unix:///var/run/docker.sock"` (`:34`). Docker Desktop on Windows listens on
  `npipe:////./pipe/docker_engine`. Resolve the endpoint as in §4.7.
- The root check `os.getuid() == 0` (`:175`) and `--user uid:gid` (`:181`). On Windows, pass
  `--user 65534:65534`. Files in Docker Desktop bind mounts can be read by any user in the container. A host
  administrator check is optional, because the containers run in the VM.
- The `--mount type=bind,src=C:\…` form (`:184`) is correct for Windows paths. The existing check against commas
  in paths still applies.

### 5.3 Correct but degraded on Windows

1. **Console windows.** A windowed (`console=False`) build opens a console window for every console child it
   starts: each `docker` probe, `docker run`, Hermes, and Ollama. Pass `creationflags=CREATE_NO_WINDOW` from one
   helper, for every `subprocess.run` and `Popen` in `runner/` and `agent/`.
2. **Decoding subprocess output.** `text=True` without an encoding (`gridpack_runner.py:134`, `:157`, `:236`;
   `docker_probe.py:22`) decodes with the ANSI code page (cp1252). UTF-8 output then shows up garbled, and bytes
   that cp1252 does not define (0x81, 0x8D, 0x8F, 0x90, 0x9D) raise `UnicodeDecodeError` in the loop that
   streams the run's output. Pass `encoding="utf-8", errors="replace"`. Also consider running the frozen app in
   UTF-8 mode (`PYTHONUTF8=1`).
3. **Atomic replace.** `os.replace` onto a file that another process has open fails on Windows with WinError 5,
   because Python opens files without `FILE_SHARE_DELETE`. The job poller reads `job.json` every two seconds
   while the worker rewrites it, so this will happen during long runs. It affects:
   - `jobs.py:78`
   - `conversation_log.py:246`
   - `session.py:134` and `:261`
   - `event_index.py:141`
   - `interactive.py:203`

   Add a helper that retries with backoff for a few hundred milliseconds.
4. **Paths.**
   - `/tmp` defaults: `csv_flat.py:31` (Dask spill folder), `analysis_tab.py:26` and `distributions.py:13`
     (`MPLCONFIGDIR`), and `service.py:53` (the lock). On Windows, `/tmp` becomes `C:\tmp`.
   - XDG folders: `app_settings.py:14` (settings), `main.py:35` (cache and the `cufile.log` redirect), and
     `setup.py:130`, which already branches for Windows.

   Move all of them to `platformdirs`: `%LOCALAPPDATA%\GridLens\…` on Windows, unchanged on Linux.
   `tests/conftest.py` isolates the settings through `XDG_CONFIG_HOME`, so it has to follow.
5. **Docker on Windows.**
   - Check that the daemon runs Linux containers (`docker version --format '{{.Server.Os}}'` returns `linux`).
     Docker Desktop can be switched to Windows containers, and then every GridPACK image fails.
   - When the engine is unreachable, tell the user to start Docker Desktop. GridLens's current messages assume
     a system service and the `docker` group.
   - `-v C:\…\work:/app/workspace` (`docker_command.py:91`) works, but `--mount type=bind,…` cannot be misread.
   - `-u uid:gid` and `HOME=/tmp` are already skipped where `os.getuid` is missing (`docker_command.py:78`).
6. **File names.** `sanitize_project_name` (`core/validation.py:7`) accepts `CON`, `NUL`, `AUX`, `PRN`,
   `COM1`–`COM9`, and `LPT1`–`LPT9`. Windows cannot create folders with those names. Projects whose names differ
   only in case collide on Windows.
7. **Long paths.** Session, job, and index paths such as `…\Clarke conversations\<id>\generated\executions\<32 hex>\script.py`
   approach the 260-character `MAX_PATH` limit when user names or project folders are long. Mark the frozen
   executable `longPathAware` and document the `LongPathsEnabled` policy. Qt and Python both honor it.
8. **Provider text and arguments.**
   - `claude_code.py:39` gives a `curl … | bash` install command, which works on Linux only. Windows uses
     `irm https://claude.ai/install.ps1 | iex`.
   - `claude_code.py:135` passes the 9,447-character system prompt on the command line. That is under the
     32,767-character `CreateProcess` limit, but over `cmd.exe`'s 8,191-character limit when `claude` is an npm
     `.cmd` shim. Pass the prompt through a file instead: the adapter already writes `runtime/system_prompt.txt`,
     and Claude Code has a flag for reading the system prompt from a file.
   - `setup.py:281` names `~/.local/bin` in a Windows error message.
   - `_run_logged` stops the installer with `process.terminate()`, which leaves its child processes running on
     Windows.

   The hosted runtimes are disabled by policy, so these rank below the Hermes path.
9. **Linux-only developer scripts.** `scripts/run_app.sh` (bash); `scripts/check_environment.py` (`id`,
   `getent`, GNU `stat -c`, and `/var/run/docker.sock`); and `scripts/benchmark_agent_index.py` (`resource`).

## 6. Windows through WSL2 (the Linux build)

Every Windows machine needs WSL2 for GridPACK anyway, because Docker Desktop's Linux containers run in a WSL2 VM.
Running the Linux build of GridLens inside an Ubuntu 24.04 WSL2 distribution adds little to that requirement.
WSLg shows the Qt window on the Windows desktop. What this route needs:

1. **An x86_64 Linux build.** The PyInstaller spec's `.so` globs and `build_deb.sh` already work on x86_64.
   Build on an x86_64 Ubuntu 24.04 host (or runner) to get `gridlens_<version>_amd64.deb`. RAPIDS publishes
   x86_64 wheels.
2. **Docker in the distribution.** Docker Desktop's WSL integration exposes `/var/run/docker.sock` inside the
   distribution, so the runner and the sandbox work unchanged. Docker Engine installed in the distribution works
   too.
3. **GPU analysis.** It needs Windows 11, an NVIDIA driver of 580 or later for the cu13 wheels (§3.2 covers older
   drivers), and a single GPU. GPU Direct Storage is not supported, and cuDF falls back to its compatibility
   mode. The GPU on these machines has its own memory, so §4.2 applies.
4. **Ollama inside WSL2.** GridLens accepts only a loopback Ollama endpoint. With WSL2's default NAT networking,
   an Ollama running on the Windows side is not reachable at `127.0.0.1` from the distribution, unless WSL
   mirrored networking is on. Running `setup.py`'s Linux install inside the distribution avoids this.
5. **Project storage.** Keep the projects folder in the Linux file system (`~/GridLensProjects`, which Windows
   sees as `\\wsl.localhost\Ubuntu\home\…`), not under `/mnt/c`. GridPACK writes multi-gigabyte `*_flat.csv`
   files through the bind mount, and I/O between the two file systems is much slower.
6. **Documentation.** Write an install guide covering enabling WSL, installing Ubuntu 24.04, turning on Docker
   Desktop's WSL integration, installing the `.deb`, and setting VM memory in `.wslconfig`. By default, WSL2
   gives the VM half of the host's memory, and large contingency sweeps need more.

§4.1, §4.2, and §4.6 also affect this route. No other code change is needed.

## 7. Native Windows: packaging

1. **A Windows PyInstaller spec**, or OS branches in the current one:
   - Drop the RAPIDS collection and the `.so` globs (`gridlens.spec:164–168`).
   - Make the `numba_cuda_redirector` runtime hook (`:187`) conditional. Today it imports
     `_numba_cuda_redirector` unconditionally, so a build without `numba-cuda` fails at startup.
   - Add an `.ico` icon; only an SVG exists.
   - Add a version resource.
   - Turn UPX off (`upx=True` at `:209` and `:217`). UPX-compressed Qt DLLs break, and antivirus tools flag them.
2. **A second, console executable.** Build `gridlens-cli.exe` with `console=True` in the same `COLLECT`, and
   have `gridlens_command()` (`process.py:33`) return it on Windows. `--mcp-server` talks MCP over stdio,
   `--agent-job` writes a log, and `--agent-tool` prints results, so none of them should depend on how a windowed
   `GridLens.exe` handles standard streams. With §5.3.1 in place, a console helper started from the GUI opens no
   window.
3. **Installer and signing.** Build a per-user installer (Inno Setup, WiX, or MSIX) into
   `%LOCALAPPDATA%\Programs\GridLens`, with a Start-menu entry. Sign it with Authenticode, so SmartScreen does
   not block the download on managed PCs.
4. **Prerequisites to document.**
   - Docker Desktop with the WSL2 backend. Its terms require a paid subscription for commercial use by larger
     organizations and by government entities, which includes many regulators, so check with IT. Rancher
     Desktop (moby engine) is a free alternative that exposes the same `docker` CLI and a named pipe.
   - Pulling `pnnl/gridpack:latest`.
   - Building the sandbox image, which is optional.

## 8. Tests, CI, and documentation

- **POSIX-only tests.** Mark or rewrite the tests that assume POSIX:
  - `tests/test_analysis_service.py`, which imports `fcntl` and calls `os.setsid`
  - the `0o600` mode assertions in `tests/test_agent_conversation_log.py:41` and `:98`
  - the symlink tests in `test_agent_file_tools.py:256` and `test_agent_tools.py:186`, `:365`, and `:687`, which
    need Developer Mode on Windows
  - the fake executables written as shell scripts in `test_agent_setup.py:118` and `:140`
  - the `/tmp` literals in several tests
  - `tests/test_debian_packaging.py`, which applies to Linux only
- **Tests that assume RAPIDS.** `test_an_automatic_build_that_fails_says_so_in_the_status_line` fails in a
  CPU-only environment. Stub `cpu_dask_fallback_warning` there, so the test passes with or without RAPIDS.
- **CI.** The repository has none. Add GitHub Actions jobs for `ubuntu-24.04-arm`, `ubuntu-24.04` (x86_64), and
  `windows-latest`, running the unit tests on the CPU-only dependency set, plus a build of each platform's
  artifact. Keep the DGX Spark, or a self-hosted runner, for the GPU and Docker integration tests
  (`GRIDLENS_TEST_SANDBOX_IMAGE`, `GRIDLENS_TEST_HERMES`).
- **Documentation.**
  - `docs/user_guide.md:67–72` and `docs/architecture.md` tell users to run `pnnl/gridpack:ca-scalability-v2`.
    That tag is no longer on Docker Hub; name `latest` or `v3.7.0`, and `ca-scalability-v3` or `-v4`. An earlier
    check found that `latest` (3.7.0) writes the csv_flat files GridLens parses; the v3 and v4 tags were not
    checked for format in this review.
  - `README.md`, `docs/install_dgx_os7.md`, and `docs/packaging_distribution.md` describe DGX Spark only. Add a
    platform matrix and install guides for WSL2 and for native Windows.
  - `pyproject.toml` classifiers: add `Operating System :: Microsoft :: Windows`.

## 9. To verify on real hardware

- **Windows stdio and the helper executable.** Check that Hermes's MCP client, started by GridLens with the
  Windows environment from §5.1.7, starts `gridlens-cli.exe --mcp-server` and exchanges messages over stdio.
- **Job Objects.** Check whether Hermes (or Claude Code) puts its MCP server in a Job Object that kills its
  members when the job closes. If it does, a job worker started from a tool call dies at the end of the turn
  unless it breaks away (`CREATE_BREAKAWAY_FROM_JOB`), and breaking away needs the job to allow it.
- **The Hermes launcher.** Find the file name of the launcher that `install.ps1` puts in
  `%LOCALAPPDATA%\hermes\bin`. `hermes_executable()` looks only for `hermes.exe`.
- **GridPACK and CRLF.** Check whether GridPACK reads RAW and contingency files with Windows line endings. Users
  on Windows will supply them, and GridLens copies inputs byte for byte.
- **CPU Dask speed.** Time the CPU Dask analysis of an 8–16 GB `*_flat.csv` on a typical Windows PC. The Memphis
  check was 168 MB and ran on the DGX Spark's CPU (2.1 s, against 1.7 s on the GPU).
- **Discrete GPUs.** Check `cudf.pandas` and the dask-cuda path on a PCIe GPU under WSL2, after the §4.2 fix.

## 10. Suggested order

Sizes are rough: S is at most a day, M a few days, L one to two weeks.

1. **S.** §3.1 and §3.2 (Python floor, extras split), §4.1, §4.3, §4.6, and the RAPIDS-dependent test. These
   help every platform, including DGX Spark.
2. **S.** §4.2 (device-memory check) and §4.7 (Docker endpoint resolution).
3. **S–M.** An x86_64 Linux build and the WSL2 guide (§6). This gives Windows users a working GridLens,
   including GPU analysis on suitable PCs, before the native port.
4. **M.** The platform module: locks, `O_NOFOLLOW`, process trees, liveness, cancellation, the environment
   allowlist, platform folders, replace with retry, and `CREATE_NO_WINDOW` (§5.1, §5.3). Then the threaded
   pipe reader (§5.1.3).
5. **M.** The Windows PyInstaller spec, the console helper, the installer, and signing (§7), and the sandbox
   endpoint on Windows (§5.2).
6. **M.** CI on the three platforms, the test changes, and the documentation (§8). Then the checks in §9 on a
   Windows 11 x64 PC.
