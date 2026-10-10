"""Small durable V-0 state store: atomic JSON records and cross-process locks."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class StoreError(RuntimeError):
    pass


def _safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise StoreError("unsafe object identifier")
    return value


class JsonStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, object_id: str) -> Path:
        return self.root / _safe_id(kind) / (_safe_id(object_id) + ".json")

    @contextmanager
    def _lock(self, path: Path, timeout: float = 10.0) -> Iterator[None]:
        lock = path.with_suffix(path.suffix + ".lock")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise StoreError(f"timed out waiting for {path.name} lock")
                time.sleep(0.025)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    @staticmethod
    def _write_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".career-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, kind: str, object_id: str) -> dict[str, Any] | None:
        path = self._path(kind, object_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"corrupt state: {kind}/{object_id}") from exc
        if not isinstance(value, dict):
            raise StoreError(f"corrupt state object: {kind}/{object_id}")
        return value

    def put_new(self, kind: str, object_id: str, value: dict[str, Any]) -> dict[str, Any]:
        path = self._path(kind, object_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(path):
            if path.exists():
                raise StoreError(f"state already exists: {kind}/{object_id}")
            self._write_atomic(path, value)
        return value

    def replace(self, kind: str, object_id: str, value: dict[str, Any], *, expected_revision: int) -> dict[str, Any]:
        path = self._path(kind, object_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(path):
            current = self.get(kind, object_id)
            if current is None or current.get("revision") != expected_revision:
                raise StoreError(f"stale state: {kind}/{object_id}")
            if value.get("revision") != expected_revision + 1:
                raise StoreError("replacement must increase revision by one")
            previous = {key: item for key, item in current.items() if key != "_history"}
            next_value = {**value, "_history": [*current.get("_history", []), previous]}
            self._write_atomic(path, next_value)
        return next_value

    def get_revision(self, kind: str, object_id: str, revision: int) -> dict[str, Any] | None:
        current = self.get(kind, object_id)
        if current is None:
            return None
        if current.get("revision") == revision:
            return {key: value for key, value in current.items() if key != "_history"}
        for previous in current.get("_history", []):
            if previous.get("revision") == revision:
                return previous
        return None

    def list_records(self, kind: str) -> list[dict[str, Any]]:
        folder = self.root / _safe_id(kind)
        if not folder.exists():
            return []
        return [self.get(kind, path.stem) for path in sorted(folder.glob("*.json"))]
