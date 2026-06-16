from __future__ import annotations


def get_pandas():
    """Return pandas after enabling cuDF's pandas accelerator when available."""
    try:
        import cudf.pandas

        cudf.pandas.install()
    except ModuleNotFoundError:
        pass

    import pandas as pd

    return pd
