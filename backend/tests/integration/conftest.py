from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from docforge.cli import InlinePipeline
from docforge.config import Settings
from docforge.container import Container, build_container

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    built = build_container(settings)
    yield built
    await built.close()


@pytest.fixture
def inline(container: Container) -> InlinePipeline:
    return InlinePipeline(container)
