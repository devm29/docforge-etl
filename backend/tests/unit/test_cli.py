from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command

from docforge.cli import migrate
from docforge.config import BACKEND_ROOT, Settings


def test_alembic_config_defaults_to_the_source_tree() -> None:
    assert Settings().alembic_config == BACKEND_ROOT / "alembic.ini"


def test_migrate_uses_the_configured_alembic_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ini = tmp_path / "alembic.ini"
    ini.write_text("[alembic]\nscript_location = %(here)s/alembic\n")
    seen: dict[str, Any] = {}

    def fake_upgrade(config: Any, revision: str) -> None:
        seen.update(file=config.config_file_name, url=config.get_main_option("sqlalchemy.url"), rev=revision)

    monkeypatch.setattr(command, "upgrade", fake_upgrade)
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ini))
    migrate(Settings(database_url="postgresql+asyncpg://u@db/x"))

    assert seen == {"file": str(ini), "url": "postgresql+asyncpg://u@db/x", "rev": "head"}
