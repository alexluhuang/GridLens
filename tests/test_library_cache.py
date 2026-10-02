"""The private cache in a Reference documents folder."""
from __future__ import annotations

import hashlib
import stat

import pytest

from gridlens.agent.library import cache
from gridlens.agent.policy import AgentError


def test_the_cache_folder_is_private_and_never_a_symbolic_link(tmp_path):
    index = cache.index_folder(tmp_path)
    assert index == tmp_path / cache.INDEX_FOLDER
    assert stat.S_IMODE(index.stat().st_mode) == 0o700
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / cache.INDEX_FOLDER).symlink_to(index)
    with pytest.raises(AgentError) as refused:
        cache.index_folder(linked)
    assert refused.value.code == "UNSAFE_PATH"


def test_cached_text_is_private_whole_and_read_back_as_written(tmp_path):
    index = cache.index_folder(tmp_path)
    record = {"title": "Criteria", "pages": [[1, "i", "Rate B applies."]]}
    cache.save_text(index, "abc123", record)
    assert cache.load_text(index, "abc123") == record
    assert stat.S_IMODE((index / "abc123.json").stat().st_mode) == 0o600
    assert list(index.glob("*.tmp")) == []


def test_missing_or_invalid_cached_text_counts_as_not_cached(tmp_path):
    index = cache.index_folder(tmp_path)
    (index / "broken.json").write_text("{", encoding="utf-8")
    assert cache.load_text(index, "broken") is None
    assert cache.load_text(index, "missing") is None


def test_a_files_sha256_is_read_in_blocks_of_its_whole_contents(tmp_path):
    path = tmp_path / "large.pdf"
    data = bytes(range(256)) * 9000
    path.write_bytes(data)
    assert cache.file_sha256(path) == hashlib.sha256(data).hexdigest()
