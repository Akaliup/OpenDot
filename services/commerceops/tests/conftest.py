import pytest
from fastapi.testclient import TestClient

from commerceops.api.app import create_app
from commerceops.db import session_factory_for
from commerceops.seed import seed_demo_data


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{tmp_path}/commerceops.db"


@pytest.fixture
def session(database_url):
    factory = session_factory_for(database_url)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded(session):
    seed_demo_data(session)
    return session


@pytest.fixture
def client(database_url):
    application = create_app(database_url)
    with TestClient(application) as test_client:
        yield test_client
