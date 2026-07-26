"""Safe, atomic cache serialization helpers.

Runtime caches are treated as untrusted input.  JSON avoids the arbitrary code
execution risk of pickle while the temporary-file swap prevents readers from
observing partially written cache entries.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


_FORMAT = "contesttrade-cache-v1"


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"Unsupported cache value: {type(value).__name__}")


def write_cache(path: Path, value: Any) -> None:
    """Serialize a DataFrame or JSON-compatible value using an atomic replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, pd.DataFrame):
        payload = {
            "format": _FORMAT,
            "kind": "dataframe",
            "data": value.to_json(
                orient="table", date_format="iso", date_unit="ms", force_ascii=False
            ),
        }
    else:
        payload = {"format": _FORMAT, "kind": "json", "data": value}

    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, default=_json_default)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_cache(path: Path) -> Any:
    """Read a cache entry written by :func:`write_cache`."""
    with gzip.open(Path(path), "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("format") != _FORMAT:
        raise ValueError("Unsupported ContestTrade cache format")
    if payload.get("kind") == "dataframe":
        return pd.read_json(io.StringIO(payload["data"]), orient="table")
    if payload.get("kind") == "json":
        return payload.get("data")
    raise ValueError(f"Unsupported ContestTrade cache kind: {payload.get('kind')}")
