"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_io_manager():
    """Stop one test's manifest from leaking into the next.

    `data_io.manifest.get_manager()` memoises a module-level `_default_manager`, and
    `DataManager()` finds its manifest by walking up from the current working directory. A
    test that builds a temporary manifest and writes through a logical name therefore caches
    a manager pointing at that temp manifest, and every later test resolving a real dataset
    gets the fixture's two-entry manifest instead -- failing with
    `DatasetNotFoundError: Unknown dataset: paragraph_axis_1626_1630` only when run as part
    of the suite, never in isolation.
    """
    import data_io.manifest as manifest_module

    saved = manifest_module._default_manager
    try:
        yield
    finally:
        manifest_module._default_manager = saved
