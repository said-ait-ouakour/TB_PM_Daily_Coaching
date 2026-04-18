"""In-memory Supabase-style client for unit tests (no network)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple


def _compare_gte(cell: Any, bound: Any) -> bool:
    if cell is None:
        return False
    try:
        return cell >= bound
    except Exception:
        return str(cell) >= str(bound)


def _compare_lt(cell: Any, bound: Any) -> bool:
    if cell is None:
        return False
    try:
        return cell < bound
    except Exception:
        return str(cell) < str(bound)


@dataclass
class FakeTableQuery:
    """Minimal chain: select().eq().gte().lt()...execute()."""

    _rows: List[Dict[str, Any]]
    _filters: List[Tuple[str, Any]] = field(default_factory=list)
    _gte_filters: List[Tuple[str, Any]] = field(default_factory=list)
    _lt_filters: List[Tuple[str, Any]] = field(default_factory=list)
    _order_desc: bool = False
    _order_col: Optional[str] = None
    _limit: Optional[int] = None
    _count_exact: Optional[str] = None

    def select(self, *_cols: Any, count: Optional[str] = None, **kw: Any) -> "FakeTableQuery":
        if count == "exact":
            self._count_exact = "exact"
        return self

    def eq(self, col: str, val: Any) -> "FakeTableQuery":
        self._filters.append((col, val))
        return self

    def gte(self, col: str, val: Any) -> "FakeTableQuery":
        self._gte_filters.append((col, val))
        return self

    def lt(self, col: str, val: Any) -> "FakeTableQuery":
        self._lt_filters.append((col, val))
        return self

    def order(self, col: str, *, desc: bool = False) -> "FakeTableQuery":
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "FakeTableQuery":
        self._limit = n
        return self

    def insert(self, *_a: Any, **_k: Any) -> "FakeTableQuery":
        return self

    def update(self, *_a: Any, **_k: Any) -> "FakeTableQuery":
        return self

    def execute(self) -> SimpleNamespace:
        def _match(row: Dict[str, Any]) -> bool:
            if not all(row.get(c) == v for c, v in self._filters):
                return False
            if not all(_compare_gte(row.get(c), v) for c, v in self._gte_filters):
                return False
            if not all(_compare_lt(row.get(c), v) for c, v in self._lt_filters):
                return False
            return True

        data = [dict(r) for r in self._rows if _match(r)]
        if self._order_col and data:
            reverse = bool(self._order_desc)
            data.sort(key=lambda r: r.get(self._order_col) or "", reverse=reverse)
        if self._limit is not None:
            data = data[: self._limit]
        cnt = len(data) if self._count_exact else None
        return SimpleNamespace(data=data, count=cnt)


@dataclass
class FakeSupabaseClient:
    tables: Dict[str, List[Dict[str, Any]]]

    def table(self, name: str) -> FakeTableQuery:
        rows = list(self.tables.get(name, []))
        return FakeTableQuery(rows)
