# Architecture

GridPACK Workbench separates the consumer GUI from the execution engine. The GUI gathers input files and settings. The core layer creates a local project and run folder. The runner layer builds a Docker argument list and runs GridPACK. The analysis layer reads local outputs and creates reports.

```text
PySide6 GUI
  -> core project manager
  -> Docker/GridPACK runner
  -> pnnl/gridpack Docker container
  -> local output files
  -> local analysis and reports
```

## Project Folders

A regulator-facing project is stored under:

```text
~/GridPACKWorkbenchProjects/
  Project_Name/
    project.json
    original_inputs/
    runs/
      2026-06-12_15-30-22/
        manifest.json
        status.json
        work/
        logs/run.log
        reports/
    exports/
```

The `original_inputs/` directory stores the project input files. Every run copies those files into that run's `work/` directory. Docker sees only the run's `work/` directory, mounted at `/app/workspace`.

## Docker Boundary

GridPACK's Docker documentation describes `/app/workspace` as the working directory and shows `mpirun -n ...` inside the container. This app follows that model and also adds security and reproducibility defaults:

- `--network none`
- `--pull=never`
- `--platform linux/amd64` or `linux/arm64`
- `-u uid:gid`
- `-e HOME=/tmp`
- `-v run/work:/app/workspace`
- `-w /app/workspace`

The command is built as a Python list and passed to `subprocess.Popen` without a shell. This avoids shell quoting problems and command injection risks.

## Audit Files

Each run creates:

- `manifest.json`: image, executable, XML file, MPI process count, platform, input hashes, and exact Docker command.
- `status.json`: running/completed/failed state and return code.
- `logs/run.log`: command and streamed GridPACK output.

## Analysis Layer

The first analysis layer is deliberately conservative. It can:

- list output files;
- estimate success/failure counts from `success.txt`;
- write `output_inventory.csv`;
- write `analysis_summary.json`;
- create `success_summary.svg`;
- write `report.html`;
- export a run ZIP.

The next production step is to add exact parsers for the real `success.txt`, `pflow_mm.txt`, `vmag_mm.txt`, `qflow_mm.txt`, and other GridPACK output formats used by your workflow.
