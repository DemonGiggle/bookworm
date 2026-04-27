from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TextIO, Union


def file_label(path: Union[str, Path]) -> str:
    return Path(path).name or str(path)


class ProgressReporter:
    def update(self, message: str) -> None:
        raise NotImplementedError

    def persist(self, message: str) -> None:
        raise NotImplementedError

    def verbose(self, message: str) -> None:
        raise NotImplementedError

    def verbosity(self) -> int:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class NoOpProgressReporter(ProgressReporter):
    def update(self, message: str) -> None:
        return None

    def persist(self, message: str) -> None:
        return None

    def verbose(self, message: str) -> None:
        return None

    def verbosity(self) -> int:
        return 0

    def clear(self) -> None:
        return None


class ConsoleProgressReporter(ProgressReporter):
    def __init__(
        self,
        stream: Optional[TextIO] = None,
        verbose_level: int = 0,
        rewrite_updates: bool = True,
    ) -> None:
        self.stream = stream or sys.stderr
        self.verbose_level = verbose_level
        self.rewrite_updates = rewrite_updates
        self._last_line_length = 0

    def _clear_line(self) -> None:
        if self._last_line_length:
            self.stream.write("\r" + (" " * self._last_line_length) + "\r")
            self.stream.flush()
            self._last_line_length = 0

    def update(self, message: str) -> None:
        rendered = message.strip()
        if not self.rewrite_updates:
            self.persist(rendered)
            return None
        self.stream.write("\r" + rendered)
        if self._last_line_length > len(rendered):
            self.stream.write(" " * (self._last_line_length - len(rendered)))
        self.stream.flush()
        self._last_line_length = len(rendered)

    def persist(self, message: str) -> None:
        self._clear_line()
        self.stream.write(message.strip() + "\n")
        self.stream.flush()

    def verbose(self, message: str) -> None:
        if self.verbose_level <= 0:
            return None
        self.persist(message)

    def verbosity(self) -> int:
        return self.verbose_level

    def clear(self) -> None:
        self._clear_line()
