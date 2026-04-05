"""Structured logging helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def log_info(message: str, **fields: Dict[str, Any]) -> None:
    _log(logging.INFO, message, fields)


def log_warning(message: str, **fields: Dict[str, Any]) -> None:
    _log(logging.WARNING, message, fields)


def log_error(message: str, **fields: Dict[str, Any]) -> None:
    _log(logging.ERROR, message, fields)


def _log(level: int, message: str, fields: Dict[str, Any]) -> None:
    payload = {"message": message, **fields} if fields else {"message": message}
    logging.log(level, json.dumps(payload))

