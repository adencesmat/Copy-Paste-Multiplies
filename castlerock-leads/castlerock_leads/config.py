"""Configuration loading and light validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    raw: dict

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    # --- convenience accessors -------------------------------------------
    @property
    def city(self) -> str:
        return self.raw["geography"]["city"].upper()

    @property
    def zip_codes(self) -> list[str]:
        return [str(z) for z in self.raw["geography"].get("zip_codes", [])]

    def in_area(self, address: str | None, zip_code: str | None = None) -> bool:
        """True if an address/zip belongs to the configured Castle Rock area."""
        hay = f"{address or ''} {zip_code or ''}".upper()
        if self.city in hay:
            return True
        return any(z in hay for z in self.zip_codes)


def load_config(path: str | Path | None = None) -> Config:
    """Load config.yaml, falling back to config.example.yaml.

    Environment variables of the form ``CRL_<SECTION>_<KEY>`` are not expanded
    here; secrets (SMTP creds) are read directly from the environment in the
    notify module so they never touch disk.
    """
    if path is None:
        here = Path(__file__).resolve().parent.parent
        candidate = here / "config.yaml"
        path = candidate if candidate.exists() else here / "config.example.yaml"
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Config(raw=raw)
