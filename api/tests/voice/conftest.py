import pytest
from voice_fakes import FakeRunService


@pytest.fixture
def service() -> FakeRunService:
    return FakeRunService()
