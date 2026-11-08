"""Errors that map directly to HTTP responses."""

from __future__ import annotations


class DeskError(Exception):
    def __init__(self, status: int, message: str, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
