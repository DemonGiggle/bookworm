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

    def clear(self) -> None:
        raise NotImplementedError


class NoOpProgressReporter(ProgressReporter):
    def update(self, message: str) -> None:
        return None

    def persist(self, message: str) -> None:
        return None

    def clear(self) -> None:
        return None


class ConsoleProgressReporter(ProgressReporter):
    def __init__(self, stream: Optional[TextIO] = None) -> None:
        self.stream = stream or sys.stderr
        self._last_line_length = 0

    def _clear_line(self) -> None:
        if self._last_line_length:
            self.stream.write("\r" + (" " * self._last_line_length) + "\r")
            self.stream.flush()
            self._last_line_length = 0

    def update(self, message: str) -> None:
        rendered = message.strip()
        self.stream.write("\r" + rendered)
        if self._last_line_length > len(rendered):
            self.stream.write(" " * (self._last_line_length - len(rendered)))
        self.stream.flush()
        self._last_line_length = len(rendered)

    def persist(self, message: str) -> None:
        self._clear_line()
        self.stream.write(message.strip() + "\n")
        self.stream.flush()

    def clear(self) -> None:
        self._clear_line()
