"""Qt-backed observable primitives — no UI coupling."""

from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import (
    QObject,
    Signal,
)


class Observable(QObject):
    changed = Signal(object)

    def __init__(
        self,
        value: Any = None,
    ) -> None:
        super().__init__()
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(
        self,
        value: Any,
    ) -> None:
        raise NotImplementedError(
            "Subclasses must implement set()"
        )


class ObservableStr(Observable):
    changed = Signal(str)

    def __init__(
        self,
        value: str = "",
    ) -> None:
        super().__init__(value)

    def get(self) -> str:
        return self._value

    def set(
        self,
        value: str,
    ) -> None:
        if value == self._value:
            return

        self._value = value
        self.changed.emit(value)


class ObservableBool(Observable):
    changed = Signal(bool)

    def __init__(
        self,
        value: bool = False,
    ) -> None:
        super().__init__(value)

    def get(self) -> bool:
        return self._value

    def set(
        self,
        value: bool,
    ) -> None:
        if value == self._value:
            return

        self._value = value
        self.changed.emit(value)


class ObservableInt(Observable):
    changed = Signal(int)

    def __init__(
        self,
        value: int = 0,
    ) -> None:
        super().__init__(value)

    def get(self) -> int:
        return self._value

    def set(
        self,
        value: int,
    ) -> None:
        if value == self._value:
            return

        self._value = value
        self.changed.emit(value)


class ObservableList(Observable):
    """A list wrapper that emits when replaced."""

    changed = Signal(list)

    def __init__(
        self,
        value: Optional[
            List[Any]
        ] = None,
    ) -> None:
        super().__init__(
            list(
                value or []
            )
        )

    def get(self) -> List[Any]:
        return list(
            self._value
        )

    def set(
        self,
        value: List[Any],
    ) -> None:
        new_list = list(value)

        if new_list == self._value:
            return

        self._value = new_list
        self.changed.emit(
            new_list
        )