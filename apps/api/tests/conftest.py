import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_ENV", "test")

# the suite owns its own database — sharing the dev DB with a running server
# made results depend on whatever had happened outside the tests
_TEST_DB = Path(__file__).resolve().parents[3] / "data" / "discover-test.db"
_TEST_DB.parent.mkdir(exist_ok=True)
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    from app.seed import run
    run()
    return TestClient(app)
