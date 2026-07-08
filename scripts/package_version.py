from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    in_project = False
    for line in project_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and stripped.startswith("version"):
            _, value = stripped.split("=", 1)
            print(value.strip().strip('"'))
            return 0
    print(f"Unable to find [project].version in {project_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
