from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def export_run_zip(run_dir: str | Path, destination_zip: str | Path | None = None) -> Path:
    run_path = Path(run_dir).expanduser().resolve()
    if destination_zip is None:
        destination_zip = run_path.parent.parent / "exports" / f"{run_path.name}.zip"
    zip_path = Path(destination_zip).expanduser().resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(run_path.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_path.parent))
    return zip_path
