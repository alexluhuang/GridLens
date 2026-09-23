"""Tools that read every field of every file in a GridLens project.

These tools let any model, through any runtime, inspect a project's inputs and outputs without file tools
of its own: `list_files` finds files, `describe_file` explains one, and `query_table`, `read_text_file`,
and `read_document` read it as a table, as numbered lines, or as the fields of a JSON or XML document.

`query_table` understands CSV files (GridPACK csv_flat outputs and GridLens caches), GridPACK's
whitespace-separated text tables such as `pflow_mm.txt`, Parquet files, and each section of a PSS/E RAW
case. It streams a file rather than loading it, so it works on multi-gigabyte results, though a full scan
of such a file takes minutes.

Paths are absolute, or relative to the project. Either way they must lie inside a GridLens project folder
or inside this session's folder, whose `results/` holds the complete copies of large tool results.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import heapq
from itertools import islice
import json
import os
from pathlib import Path
from typing import Iterable, Iterator
import xml.etree.ElementTree as ET

from gridlens.agent.policy import AgentError
from gridlens.agent.session import PROJECT_FILE, scoped_path
from gridlens.agent.tool_base import ToolBase, page_result, tool
from gridlens.analysis.raw_sections import find_section, read_raw_sections
from gridlens.analysis.table_schemas import TABLE_SCHEMAS


FILE_TOOL_NAMES = ("list_files", "describe_file", "query_table", "read_text_file", "read_document")
# A memory guard, not a result limit: a page this large should be read in pages or processed with code.
MAX_ROWS_IN_MEMORY = 1_000_000
MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
SAMPLE_ROWS = 5
FILTER_OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "contains", "startswith", "in")
GRIDPACK_TABLE_FILES = {schema["file"]: name for name, schema in TABLE_SCHEMAS.items()}
TEXT_SUFFIXES = {".txt", ".log", ".out", ".con", ".mon", ".sub", ".dyr", ".m", ".md", ".py", ".yaml", ".yml", ".jsonl"}


def file_kind(path: Path) -> str:
    """Name how GridLens reads the file at path: raw_case, xml, json, csv, gridpack_table, parquet, text, or binary."""
    suffix = path.suffix.lower()
    if suffix == ".raw":
        return "raw_case"
    if suffix == ".xml":
        return "xml"
    if suffix == ".json":
        return "json"
    if suffix == ".parquet":
        return "parquet"
    if suffix in (".csv", ".tsv"):
        return "csv"
    if path.name in GRIDPACK_TABLE_FILES:
        return "gridpack_table"
    if suffix in TEXT_SUFFIXES:
        return "text"
    try:
        with path.open("rb") as handle:
            return "binary" if b"\0" in handle.read(4096) else "text"
    except OSError:
        return "binary"


def _count_lines(path: Path) -> int:
    """Count the lines of a file quickly, reading it in binary chunks."""
    count, last = 0, b"\n"
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            count += chunk.count(b"\n")
            last = chunk[-1:]
    return count + (0 if last == b"\n" else 1)


def _number(value: object) -> float | None:
    """Return value as a float when it is numeric, else None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sort_key(value: object) -> tuple:
    """Order numbers numerically before text, and missing values last."""
    number = _number(value)
    if number is not None:
        return (0, number, "")
    if value is None or str(value).strip() == "":
        return (2, 0.0, "")
    return (1, 0.0, str(value).casefold())


def _check_filters(filters: list[dict], columns: list[str]) -> list[tuple[str, str, object]]:
    """Validate filters of the form {"column": ..., "op": ..., "value": ...} against the table's columns."""
    checked = []
    for item in filters or []:
        if not isinstance(item, dict) or item.get("op") not in FILTER_OPERATORS or item.get("column") not in columns:
            raise AgentError("INVALID_FILTER", f"Use filters like {{'column': 'loading_percent', 'op': '>', 'value': 100}} with op in {', '.join(FILTER_OPERATORS)} and a column from: {', '.join(columns[:200])}.")
        if item["op"] == "in" and not isinstance(item.get("value"), list):
            raise AgentError("INVALID_FILTER", "The 'in' operator needs a list value.")
        checked.append((item["column"], item["op"], item.get("value")))
    return checked


def _passes(cell: object, operator: str, value: object) -> bool:
    """Apply one filter to one cell: numeric when both sides are numbers, otherwise case-insensitive text."""
    if operator == "in":
        return any(_passes(cell, "==", item) for item in value)
    left, right = _number(cell), _number(value)
    if left is not None and right is not None and operator not in ("contains", "startswith"):
        return {"==": left == right, "!=": left != right, "<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[operator]
    text, wanted = str("" if cell is None else cell).strip().casefold(), str("" if value is None else value).strip().casefold()
    if operator == "contains":
        return wanted in text
    if operator == "startswith":
        return text.startswith(wanted)
    return {"==": text == wanted, "!=": text != wanted, "<": text < wanted, "<=": text <= wanted, ">": text > wanted, ">=": text >= wanted}[operator]


def _matches(row: dict, filters: list[tuple[str, str, object]]) -> bool:
    """Return whether a row passes every filter."""
    return all(_passes(row.get(column), operator, value) for column, operator, value in filters)


class _Counted:
    """Iterate over rows while counting how many went by."""

    def __init__(self, rows: Iterable[dict]) -> None:
        self.rows = iter(rows)
        self.count = 0

    def __iter__(self) -> "_Counted":
        return self

    def __next__(self) -> dict:
        row = next(self.rows)
        self.count += 1
        return row


def _guarded(rows: Iterable[dict]) -> list[dict]:
    """Collect rows into a list, refusing to hold more than MAX_ROWS_IN_MEMORY of them."""
    collected = []
    for row in rows:
        collected.append(row)
        if len(collected) > MAX_ROWS_IN_MEMORY:
            raise AgentError("QUERY_TOO_LARGE", f"This request would hold more than {MAX_ROWS_IN_MEMORY:,} rows in memory at once. Add filters, request pages with offset and limit, or process the file with your own code.")
    return collected


def select_rows(rows: Iterable[dict], filters: list[tuple[str, str, object]], sort_by: str, descending: bool, offset: int, limit: int) -> tuple[list[dict], int]:
    """Return one page of the rows that pass the filters, and how many rows passed, reading rows once.

    Without sort_by the rows keep their file order and only the page is held. With sort_by and a limit,
    only the best offset+limit rows are held; sorting every row with limit=0 holds all matching rows.
    """
    matching = _Counted(row for row in rows if _matches(row, filters))
    if not sort_by:
        page = _guarded(islice(matching, offset, offset + limit if limit else None))
        for _ in matching:
            pass
        return page, matching.count

    def key(row: dict) -> tuple:
        """Order rows by the sort column."""
        return _sort_key(row.get(sort_by))

    if limit:
        pick = heapq.nlargest if descending else heapq.nsmallest
        best = pick(offset + limit, matching, key=key)
        return best[offset:], matching.count
    everything = _guarded(matching)
    everything.sort(key=key, reverse=descending)
    return everything[offset:], matching.count


@contextmanager
def open_table(path: Path, kind: str, table: str = "") -> Iterator[tuple[list[str], Iterable[dict]]]:
    """Yield a table's columns and an iterator over its rows, streaming the file where the format allows."""
    if kind == "csv":
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
            yield list(reader.fieldnames or []), reader
    elif kind == "gridpack_table":
        columns = list(TABLE_SCHEMAS[GRIDPACK_TABLE_FILES[path.name]]["columns"])
        with path.open(encoding="utf-8", errors="replace") as handle:
            yield columns, (dict(zip(columns, line.split())) for line in handle if len(line.split()) == len(columns))
    elif kind == "raw_case":
        _, sections = read_raw_sections(path)
        try:
            section = find_section(sections, table)
        except KeyError as exc:
            names = ", ".join(item.name for item in sections)
            raise AgentError("RAW_SECTION_REQUIRED", f"Name a RAW section in table, one of: {names}.") from exc
        yield section.columns, iter(section.rows)
    elif kind == "parquet":
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise AgentError("PARQUET_UNAVAILABLE", "Reading Parquet needs the GridLens analysis extra (pyarrow).") from exc
        source = parquet.ParquetFile(path)
        yield list(source.schema_arrow.names), (row for batch in source.iter_batches(batch_size=65536) for row in batch.to_pylist())
    else:
        raise AgentError("NOT_A_TABLE", "This file is not a table. Use read_text_file or read_document for it.")


def _json_fields(value: object, path: str = "$") -> Iterator[dict]:
    """Yield one row per leaf of a JSON value, with a path such as $.input_files[0].sha256."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _json_fields(item, f"{path}.{key}")
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _json_fields(item, f"{path}[{index}]")
    else:
        yield {"path": path, "value": value}


def _xml_fields(element: ET.Element, path: str) -> Iterator[dict]:
    """Yield one row per attribute and text value of an XML element and its children.

    Paths look like Configuration/Powerflow/tolerance; repeated sibling tags are numbered, as in item[2].
    """
    for name, value in element.attrib.items():
        yield {"path": f"{path}/@{name}", "value": value}
    children = list(element)
    text = (element.text or "").strip()
    if text or not children:
        yield {"path": path, "value": text}
    totals, seen = Counter(child.tag for child in children), Counter()
    for child in children:
        seen[child.tag] += 1
        name = f"{child.tag}[{seen[child.tag]}]" if totals[child.tag] > 1 else child.tag
        yield from _xml_fields(child, f"{path}/{name}")


def document_fields(path: Path, kind: str) -> Iterator[dict]:
    """Yield the fields of a JSON or XML document as rows of path and value."""
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise AgentError("DOCUMENT_TOO_LARGE", "This document is too large to parse whole. Use read_text_file to page through it, or your own code.")
    if kind == "json":
        yield from _json_fields(json.loads(path.read_text(encoding="utf-8", errors="replace")))
    elif kind == "xml":
        root = ET.parse(path).getroot()
        yield from _xml_fields(root, root.tag)
    else:
        raise AgentError("NOT_A_DOCUMENT", "read_document reads JSON and XML files. Use query_table or read_text_file for this one.")


class FileTools(ToolBase):
    """The file tools, bound to one session."""

    def _file_root(self, candidate: Path) -> Path:
        """Return this session's folder or the GridLens project folder that contains candidate."""
        session = self.context.directory
        if candidate == session or session in candidate.parents:
            return session
        for folder in candidate.parents:
            if (folder / PROJECT_FILE).is_file():
                return folder
        raise AgentError("PATH_OUTSIDE_PROJECTS", "GridLens file tools read files inside GridLens project folders and this session's folder. Use list_files to find a project's files.")

    def _file(self, path: str, project: str = "") -> Path:
        """Resolve a path argument to a regular file, check that it stays in its folder, and record it as a source."""
        text = str(path or "").strip()
        if not text:
            raise AgentError("INVALID_PATH", "Give a file path, absolute or relative to the project.")
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = self._project(project) / candidate
        # Normalize the spelling only; scoped_path still refuses symlinks along the way.
        candidate = Path(os.path.normpath(candidate))
        root = self._file_root(candidate)
        resolved = scoped_path(root, candidate.relative_to(root))
        if not resolved.is_file():
            raise AgentError("FILE_NOT_FOUND", f"No file at {resolved}. Use list_files to find the project's files.")
        return self._source(resolved, root)

    @tool
    def list_files(self, project: str = "", folder: str = "", pattern: str = "*", offset: int = 0, limit: int = 500) -> dict:
        """List a project's files under folder (relative, blank for all) matching a glob pattern, with size, date, and kind. Agent session files are listed only when folder starts with agent."""
        root = self._project(project)
        base = scoped_path(root, folder, directory=True) if folder.strip() else root
        if not base.is_dir():
            raise AgentError("FOLDER_NOT_FOUND", "No such folder in the project. List the project root first.")
        include_agent = folder.strip().startswith("agent")
        rows = []
        for path in sorted(base.rglob(pattern or "*")):
            relative = path.relative_to(root)
            if not include_agent and relative.parts[:1] == ("agent",):
                continue
            try:
                scoped_path(root, relative)
            except AgentError:
                continue
            if not path.is_file():
                continue
            info = path.stat()
            modified = datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(timespec="seconds")
            rows.append({"path": str(relative), "absolute_path": str(path), "size_bytes": info.st_size, "modified": modified, "kind": file_kind(path)})
        return {"rows": rows, "project": str(root)}

    @tool
    def describe_file(self, path: str, project: str = "") -> dict:
        """Describe one file: its kind and size; for tables its columns, row count, and first rows; for a RAW case its sections and fields; for XML or JSON its field count and first fields."""
        file = self._file(path, project)
        kind = file_kind(file)
        info = {"file": str(file), "kind": kind, "size_bytes": file.stat().st_size}
        if kind in ("csv", "gridpack_table", "parquet"):
            with open_table(file, kind) as (columns, rows):
                sample = list(islice(rows, SAMPLE_ROWS))
            if kind == "parquet":
                import pyarrow.parquet as parquet

                count = parquet.ParquetFile(file).metadata.num_rows
            else:
                count = max(_count_lines(file) - (1 if kind == "csv" else 0), 0)
            return {"rows": sample, **info, "columns": columns, "row_count": count}
        if kind == "raw_case":
            header, sections = read_raw_sections(file)
            listing = [{"name": section.name, "record_count": len(section.rows), "columns": section.columns} for section in sections]
            return {"rows": [], **info, "header": header, "sections": listing}
        if kind in ("json", "xml"):
            fields = list(document_fields(file, kind))
            return {"rows": fields[:SAMPLE_ROWS], **info, "field_count": len(fields)}
        if kind == "text":
            with file.open(encoding="utf-8", errors="replace") as handle:
                sample = [{"line": number, "text": line.rstrip("\r\n")} for number, line in enumerate(islice(handle, SAMPLE_ROWS), 1)]
            return {"rows": sample, **info, "line_count": _count_lines(file)}
        return {"rows": [], **info}

    @tool
    def query_table(self, path: str, project: str = "", table: str = "", columns: list[str] | None = None, filters: list[dict] | None = None, sort_by: str = "", descending: bool = False, offset: int = 0, limit: int = 100) -> dict:
        """Read rows of a table file (CSV, GridPACK text table, Parquet, or one section of a RAW case named in table), with optional column selection, filters such as {"column": "loading_percent", "op": ">", "value": 100}, and sorting. limit=0 returns every matching row."""
        file = self._file(path, project)
        kind = file_kind(file)
        with open_table(file, kind, table) as (available, rows):
            checked = _check_filters(filters or [], available)
            wanted = list(columns or [])
            for name in [*wanted, *([sort_by] if sort_by else [])]:
                if name not in available:
                    raise AgentError("UNKNOWN_COLUMN", f"No column '{str(name)[:200]}'. Columns: {', '.join(available[:200])}.")
            page, total = select_rows(rows, checked, sort_by, descending, offset, limit)
        if wanted:
            page = [{name: row.get(name) for name in wanted} for row in page]
        return {**page_result(page, total, offset, limit), "file": str(file), "kind": kind, "table": table, "columns": wanted or available}

    @tool
    def read_text_file(self, path: str, project: str = "", offset: int = 0, limit: int = 500) -> dict:
        """Read numbered lines of any text file, such as a log, XML, RAW, or GridPACK output; offset skips lines and limit=0 reads to the end."""
        file = self._file(path, project)
        page, total = [], 0
        with file.open(encoding="utf-8", errors="replace", newline="") as handle:
            for total, line in enumerate(handle, 1):
                if total > offset and (limit == 0 or len(page) < limit):
                    page.append({"line": total, "text": line.rstrip("\r\n")})
                    if len(page) > MAX_ROWS_IN_MEMORY:
                        raise AgentError("QUERY_TOO_LARGE", f"Read at most {MAX_ROWS_IN_MEMORY:,} lines per call; page with offset and limit, or process the file with your own code.")
        return {**page_result(page, total, offset, limit), "file": str(file)}

    @tool
    def read_document(self, path: str, project: str = "", offset: int = 0, limit: int = 0) -> dict:
        """Read every field of a JSON or XML file, such as input.xml, manifest.json, or project.json, as rows of path and value."""
        file = self._file(path, project)
        kind = file_kind(file)
        return {"rows": _guarded(document_fields(file, kind)), "file": str(file), "kind": kind}
