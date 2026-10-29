from pathlib import Path

import pytest

from lineage import settings
from lineage.gedcom import Tree, load

FIXTURE = Path(__file__).parent / "fixtures" / "family.ged"


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    """Every test reads the settings again from its own working directory, never from the developer's."""
    monkeypatch.delenv("LINEAGE_CONFIG", raising=False)
    settings.use(None)
    yield
    settings.use(None)


def project(root: Path, **values) -> settings.Config:
    config = settings.Config(root=root, **values)
    settings.use(config)
    return config


@pytest.fixture
def tree() -> Tree:
    return load(FIXTURE)


def ged(*records: str) -> str:
    return "\n".join(["0 HEAD", *records, "0 TRLR"])
