from __future__ import annotations

from gridpack_workbench.analysis.table_schemas import TABLE_SCHEMAS


def test_table_schemas_have_required_fields_and_declared_columns() -> None:
    assert TABLE_SCHEMAS

    for table_name, schema in TABLE_SCHEMAS.items():
        assert schema["file"].endswith(".txt"), table_name
        assert schema["columns"], table_name
        assert schema["ints"].issubset(set(schema["columns"])), table_name
        assert schema["strings"].issubset(set(schema["columns"])), table_name


def test_gridpack_table_source_files_are_unique() -> None:
    source_files = [schema["file"] for schema in TABLE_SCHEMAS.values()]

    assert len(source_files) == len(set(source_files))
