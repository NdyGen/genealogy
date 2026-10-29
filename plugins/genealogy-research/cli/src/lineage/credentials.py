"""Credential files outside the repository, in ~/.config/lineage/, still falling back to the pre-rename
~/.config/ndygen/ files and NDYGEN_* keys and environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

from lineage.i18n import t

CONFIG_DIR = "~/.config/lineage"
LEGACY_CONFIG_DIR = "~/.config/ndygen"
LEGACY_PREFIX = "NDYGEN_"
PREFIX = "LINEAGE_"


def config_path(file: str, prefix: str) -> Path:
    legacy_prefix = LEGACY_PREFIX + prefix.removeprefix(PREFIX)
    explicit = os.environ.get(f"{prefix}CONFIG") or os.environ.get(f"{legacy_prefix}CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    path = Path(CONFIG_DIR, file).expanduser()
    legacy = Path(LEGACY_CONFIG_DIR, file).expanduser()
    return legacy if not path.exists() and legacy.exists() else path


def load(
    file: str,
    prefix: str,
    required: tuple[str, ...],
    error: type[Exception],
    renamed: dict[str, str] | None = None,
) -> dict[str, str]:
    """Key=value file plus environment, keyed by the LINEAGE_ names; `renamed` maps old key suffixes
    (after NDYGEN_<NAME>_) to new ones. A new key wins over its old spelling."""
    legacy_prefix = LEGACY_PREFIX + prefix.removeprefix(PREFIX)
    path = config_path(file, prefix)
    raw: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() and not key.lstrip().startswith("#"):
                raw[key.strip()] = value.strip()
    raw.update({k: v for k, v in os.environ.items() if k.startswith((prefix, legacy_prefix))})
    values: dict[str, str] = {}
    for key, value in raw.items():
        name = key
        if key.startswith(legacy_prefix):
            suffix = key.removeprefix(legacy_prefix)
            name = prefix + (renamed or {}).get(suffix, suffix)
        if key == name or name not in raw:
            values[name] = value
    for name in required:
        if not values.get(name):
            raise error(t("{name} is missing in {path}", name=name, path=path))
    return values
