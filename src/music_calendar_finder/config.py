from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml


@dataclass
class AppSettings:
    root_dir: Path
    config: dict[str, Any]
    database_path: Path
    import_xlsx_path: Path
    export_dir: Path
    log_level: str

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root_dir / path


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(
    config_path: str | Path = "config/default.yaml",
    env_path: str | Path = ".env",
) -> AppSettings:
    root_dir = Path.cwd()
    load_dotenv(root_dir / env_path)
    resolved_config = root_dir / config_path
    with resolved_config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    app_config = config.setdefault("app", {})
    app_config["env"] = os.getenv("APP_ENV", app_config.get("env", "local"))
    app_config["database_path"] = os.getenv(
        "DATABASE_PATH", app_config.get("database_path", "data/music_calendar_finder.sqlite")
    )
    app_config["import_xlsx_path"] = os.getenv(
        "IMPORT_XLSX_PATH", app_config.get("import_xlsx_path", "imports/cities.xlsx")
    )
    app_config["export_dir"] = os.getenv("EXPORT_DIR", app_config.get("export_dir", "exports"))
    app_config["log_level"] = os.getenv("LOG_LEVEL", app_config.get("log_level", "INFO"))

    settings = AppSettings(
        root_dir=root_dir,
        config=config,
        database_path=_resolve(root_dir, app_config["database_path"]),
        import_xlsx_path=_resolve(root_dir, app_config["import_xlsx_path"]),
        export_dir=_resolve(root_dir, app_config["export_dir"]),
        log_level=app_config["log_level"],
    )
    return settings


def _resolve(root_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root_dir / path

