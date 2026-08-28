# scripts/bait_manager.py
from __future__ import annotations

from typing import List, Optional
from PySide6.QtCore import QObject, Signal

from config import get_baits


class BaitManager(QObject):
    """Manages bait list, availability, priority order, and current selection.
       Emits signals when state changes."""

    bait_list_changed = Signal()            # when baits reloaded
    current_index_changed = Signal(int)     # when equipped bait changes
    availability_changed = Signal(int, bool) # index, available

    def __init__(self) -> None:
        super().__init__()
        self._baits = list(get_baits())
        self._priority: List[int] = list(range(len(self._baits)))
        self._current_index: int = 0
        self._available: List[bool] = [False] * len(self._baits)

    def set_priority(self, order: List[int]) -> None:
        """Set the priority order for bait switching."""
        valid = set(range(len(self._baits)))
        normalized: List[int] = []
        seen = set()
        for idx in order:
            if idx in valid and idx not in seen:
                normalized.append(idx)
                seen.add(idx)
        for idx in valid:
            if idx not in seen:
                normalized.append(idx)
        self._priority = normalized
        self.bait_list_changed.emit()

    def get_next_available(self) -> Optional[int]:
        """Return the next bait index in priority order, skipping current."""
        for idx in self._priority:
            if idx != self._current_index and self._available[idx]:
                return idx
        return None

    def get_bait_name(self, idx: int) -> str:
        if 0 <= idx < len(self._baits):
            return self._baits[idx]["name"]
        return "Unknown"

    def set_available(self, idx: int, available: bool) -> None:
        if 0 <= idx < len(self._available) and self._available[idx] != available:
            self._available[idx] = available
            self.availability_changed.emit(idx, available)

    def is_available(self, idx: int) -> bool:
        return 0 <= idx < len(self._available) and self._available[idx]

    def get_available_indices(self) -> List[int]:
        return [i for i, avail in enumerate(self._available) if avail]

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        if 0 <= value < len(self._baits) and value != self._current_index:
            self._current_index = value
            self.current_index_changed.emit(value)

    @property
    def baits(self) -> List[dict]:
        return self._baits

    def reload_baits(self) -> None:
        """Reload from config (e.g., after file change)."""
        self._baits = list(get_baits())
        self._available = [False] * len(self._baits)
        self._priority = list(range(len(self._baits)))
        if self._current_index >= len(self._baits):
            self._current_index = 0
        self.bait_list_changed.emit()