"""Private files keep their bytes, refuse symlinks, and lock across processes.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from gridlens.system import files


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, or skip where this account may not create one."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"This account cannot create symlinks: {exc}")


def test_text_files_keep_the_line_endings_they_are_given(tmp_path) -> None:
    path = tmp_path / "record.jsonl"
    text = 'first\nsecond\r\nthird\n'

    with files.open_private(path, "x") as handle:
        handle.write(text)

    assert path.read_bytes() == text.encode("utf-8")


def test_binary_files_keep_every_byte(tmp_path) -> None:
    path = tmp_path / "output.txt"
    data = bytes(range(256))

    with files.open_private(path, "x", binary=True) as handle:
        handle.write(data)

    assert path.read_bytes() == data


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX modes")
def test_private_files_are_readable_by_their_owner_only(tmp_path) -> None:
    path = tmp_path / "context.json"

    with files.open_private(path, "x") as handle:
        handle.write("{}")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_new_files_refuse_to_overwrite(tmp_path) -> None:
    path = tmp_path / "job.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        files.open_private(path, "x")


def test_append_and_read_share_one_file(tmp_path) -> None:
    path = tmp_path / "tool_calls.jsonl"
    for line in ("one\n", "two\n"):
        with files.open_private(path, "a") as handle:
            handle.write(line)

    with files.open_private(path, "a+") as handle:
        handle.seek(0)
        assert handle.read() == "one\ntwo\n"


@pytest.mark.parametrize("mode", ["w", "a", "a+"])
def test_private_files_refuse_a_symlink(tmp_path, mode) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = tmp_path / "planted.json"
    _symlink_or_skip(link, outside)

    with pytest.raises(OSError):
        files.open_private(link, mode)

    assert outside.read_text(encoding="utf-8") == "keep"


def test_is_link_tells_links_from_files(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "link.txt"
    _symlink_or_skip(link, target)

    assert files.is_link(link)
    assert not files.is_link(target)
    assert not files.is_link(tmp_path / "missing.txt")


def test_replace_retries_while_a_reader_holds_the_target(
        tmp_path, monkeypatch) -> None:
    source = tmp_path / "job.json.tmp"
    target = tmp_path / "job.json"
    source.write_text("new", encoding="utf-8")
    real_replace = os.replace
    failures = [PermissionError("in use"), PermissionError("in use")]

    def busy_replace(*arguments):
        if failures:
            raise failures.pop()
        real_replace(*arguments)

    monkeypatch.setattr(files, "_REPLACE_ATTEMPTS", 3)
    monkeypatch.setattr(files.os, "replace", busy_replace)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)

    files.replace(source, target)

    assert target.read_text(encoding="utf-8") == "new"


def test_replace_gives_up_after_its_attempts(tmp_path, monkeypatch) -> None:
    calls = []

    def busy_replace(*arguments):
        calls.append(arguments)
        raise PermissionError("in use")

    monkeypatch.setattr(files, "_REPLACE_ATTEMPTS", 3)
    monkeypatch.setattr(files.os, "replace", busy_replace)
    monkeypatch.setattr(files.time, "sleep", lambda seconds: None)

    with pytest.raises(PermissionError):
        files.replace(tmp_path / "a", tmp_path / "b")

    assert len(calls) == 3


def test_a_held_lock_refuses_a_second_holder(tmp_path) -> None:
    path = tmp_path / "build.lock"
    first = files.FileLock(path)
    second = files.FileLock(path)

    assert first.acquire(blocking=False)
    try:
        assert not second.acquire(blocking=False)
    finally:
        first.release()
    assert second.acquire(blocking=False)
    second.release()


def test_a_lock_is_shared_with_other_processes(tmp_path) -> None:
    path = tmp_path / "build.lock"
    code = (
        "import sys; from gridlens.system import files; "
        "print(files.FileLock(sys.argv[1]).acquire(blocking=False))"
    )

    def other_process_gets_it() -> bool:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(path)], capture_output=True,
            text=True, timeout=60, check=True)
        return completed.stdout.strip() == "True"

    with files.FileLock(path):
        assert not other_process_gets_it()
    assert other_process_gets_it()
