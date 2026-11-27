import pytest
from fastapi.testclient import TestClient

from commerceops.api.app import create_app
from commerceops.context import DEMO_WORKSPACE, bind_workspace, reset_workspace
from commerceops.db import session_factory_for
from commerceops.identity import issue_identity
from commerceops.seed import seed_demo_data

TEST_SECRET = "test-signing-secret-32chars"


@pytest.fixture(autouse=True)
def _trusted_context(monkeypatch):
    monkeypatch.setenv("COMMERCEOPS_SIGNING_SECRET", TEST_SECRET)
    monkeypatch.setenv("COMMERCEOPS_WORKSPACE_ID", DEMO_WORKSPACE)
    token = bind_workspace(DEMO_WORKSPACE)
    yield
    reset_workspace(token)


def approver_token(workspace_id: str = DEMO_WORKSPACE, *, can_approve: bool = True, username: str = "owner") -> str:
    return issue_identity(
        user_id=f"user-{username}",
        username=username,
        workspace_id=workspace_id,
        can_approve=can_approve,
        ttl_seconds=3600,
    )


class SignedClient(TestClient):
    def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        headers = dict(kwargs.pop("headers", None) or {})
        if not any(key.lower() == "x-commerceops-identity" for key in headers):
            headers["x-commerceops-identity"] = approver_token()
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


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
    with SignedClient(application) as test_client:
        yield test_client
