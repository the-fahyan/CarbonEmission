import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 't.db').as_posix()}", start_worker=False)
    with TestClient(app) as c:
        yield c


def slots_payload(start, values, minutes=15):
    from datetime import timedelta
    return {"slots": [{"start_time": (start + timedelta(minutes=minutes * i)).isoformat() + "Z",
                       "duration_minutes": minutes, "intensity_g_per_kwh": v} for i, v in enumerate(values)]}
