"""Store interface: a single-table key/document model (spec §8)."""

from abc import ABC, abstractmethod
from typing import Any

Item = dict[str, Any]
"""A stored document. Always carries ``pk`` and ``sk``."""


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


class Store(ABC):
    @abstractmethod
    def get(self, pk: str, sk: str) -> Item | None: ...

    @abstractmethod
    def put(self, pk: str, sk: str, doc: dict[str, Any], *, ttl: int | None = None) -> Item:
        """Create or replace an item. ``ttl`` is epoch seconds after which the item is gone."""

    @abstractmethod
    def query(self, pk: str, prefix: str = "") -> list[Item]:
        """Items in ``pk`` whose ``sk`` starts with ``prefix``, ordered by ``sk``."""

    @abstractmethod
    def delete(self, pk: str, sk: str) -> None: ...

    @abstractmethod
    def delete_partition(self, pk: str) -> int:
        """Delete every item in ``pk``; returns how many were deleted."""
