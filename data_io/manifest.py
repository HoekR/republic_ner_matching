"""Load data_manifest.toml and resolve logical dataset paths."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TierUnavailableError(FileNotFoundError):
    """Raised when a tier's mount_check path is missing (drive unplugged)."""


class DatasetNotFoundError(KeyError):
    """Raised when a logical dataset name is absent from the manifest."""


@dataclass(frozen=True)
class TierConfig:
    root: Path
    mount_check: Path | None


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    tier: str
    path: Path
    phase: str = "explore"
    description: str = ""
    parent: str | None = None


def _expand_path(value: str | None) -> Path | None:
    if value is None or value == "":
        return None
    return Path(value).expanduser()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def find_manifest_path(start: Path | None = None) -> Path:
    env_path = os.environ.get("DATA_MANIFEST")
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path.resolve()

    candidates: list[Path] = []
    if start:
        candidates.append(start)
    candidates.append(Path.cwd())
    for directory in candidates:
        for _ in range(8):
            manifest = directory / "data_manifest.toml"
            if manifest.is_file():
                return manifest.resolve()
            if directory.parent == directory:
                break
            directory = directory.parent
    raise FileNotFoundError(
        "data_manifest.toml not found. Set DATA_MANIFEST or run from the project root."
    )


def load_manifest_dict(manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or find_manifest_path()
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    local_path = path.with_name("data_manifest.local.toml")
    if local_path.is_file():
        with local_path.open("rb") as handle:
            local_data = tomllib.load(handle)
        data = _deep_merge(data, local_data)

    override_path = os.environ.get("DATA_MANIFEST_OVERRIDE")
    if override_path:
        with Path(override_path).expanduser().open("rb") as handle:
            override_data = tomllib.load(handle)
        data = _deep_merge(data, override_data)

    return data


class DataManager:
    def __init__(self, manifest_path: Path | None = None) -> None:
        self.manifest_path = manifest_path or find_manifest_path()
        self._raw = load_manifest_dict(self.manifest_path)
        self.tiers = self._parse_tiers(self._raw.get("tiers", {}))
        self.datasets = self._parse_datasets(self._raw.get("datasets", {}))

    @staticmethod
    def _parse_tiers(raw: dict[str, Any]) -> dict[str, TierConfig]:
        tiers: dict[str, TierConfig] = {}
        for name, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            mount_check = _expand_path(cfg.get("mount_check"))
            root = _expand_path(cfg.get("root"))
            if root is None:
                raise ValueError(f"Tier {name!r} is missing root")
            tiers[name] = TierConfig(root=root, mount_check=mount_check)
        return tiers

    @staticmethod
    def _parse_datasets(raw: dict[str, Any]) -> dict[str, DatasetConfig]:
        datasets: dict[str, DatasetConfig] = {}
        for name, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            rel_path = cfg.get("path")
            if rel_path is None:
                raise ValueError(f"Dataset {name!r} is missing path")
            datasets[name] = DatasetConfig(
                name=name,
                tier=str(cfg.get("tier", "hot")),
                path=Path(rel_path),
                phase=str(cfg.get("phase", "explore")),
                description=str(cfg.get("description", "")),
                parent=cfg.get("parent") or None,
            )
        return datasets

    def tier_available(self, tier_name: str) -> bool:
        tier = self.tiers.get(tier_name)
        if tier is None:
            return False
        if tier.mount_check is None:
            return True
        return tier.mount_check.exists()

    def resolve(self, logical_name: str) -> Path:
        dataset = self.datasets.get(logical_name)
        if dataset is None:
            raise DatasetNotFoundError(f"Unknown dataset: {logical_name}")

        tier = self.tiers.get(dataset.tier)
        if tier is None:
            raise KeyError(f"Unknown tier {dataset.tier!r} for dataset {logical_name!r}")

        if tier.mount_check is not None and not tier.mount_check.exists():
            raise TierUnavailableError(
                f"Tier {dataset.tier!r} is unavailable (mount check missing: {tier.mount_check}). "
                f"Plug in the drive or set data_manifest.local.toml."
            )

        if dataset.path.is_absolute():
            return dataset.path
        return (tier.root / dataset.path).resolve()

    def dataset(self, logical_name: str) -> DatasetConfig:
        dataset = self.datasets.get(logical_name)
        if dataset is None:
            raise DatasetNotFoundError(f"Unknown dataset: {logical_name}")
        return dataset


_default_manager: DataManager | None = None


def get_manager() -> DataManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = DataManager()
    return _default_manager


def resolve(logical_name: str) -> Path:
    return get_manager().resolve(logical_name)
