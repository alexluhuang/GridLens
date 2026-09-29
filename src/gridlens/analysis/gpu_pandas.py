from __future__ import annotations

import warnings

from gridlens.analysis import gpu


def get_pandas():
    """Return pandas, accelerated by cuDF's pandas mode when a GPU can run."""
    if gpu.cuda_device_available():
        try:
            import cudf.pandas

            cudf.pandas.install()
        except Exception as exc:
            # Plain pandas gives the same results, only more slowly.
            warnings.warn(
                f"cuDF's pandas accelerator is unavailable: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    import pandas as pd

    return pd
