import os

os.environ["DATABASE_URL"] = "sqlite:///./test_procura.db"
os.environ["LLM_PROVIDER"] = "local"
os.environ["APP_ENV"] = "test"
os.environ["LANGGRAPH_CHECKPOINT_PATH"] = "./test_procura_graph.db"

import pytest
from app.config import get_settings
from app.main import app
from app.models.database import Base, engine
from app.services.auth import auth_limiter, seed_local_accounts
from app.services.seed import seed_supplier_database
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    seed_supplier_database(); seed_local_accounts(get_settings())
    auth_limiter.attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
