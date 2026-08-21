"""Test helper, deliberately NOT in conftest: importing conftest under a second
module name re-runs its module-level setup, which deletes the live test
database mid-run. This module has no import side effects."""
import uuid


def claim(client, sid):
    """The workspace requires an owner now — the journey is free, the audit is
    someone's. Tests attach a throwaway account before crossing that line."""
    email = f"t-{uuid.uuid4().hex[:10]}@test.local"
    r = client.post("/v1/auth/signup", json={"name": "Test Person", "email": email,
                                             "password": "test-pass-123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r2 = client.post("/v1/auth/claim", json={"sessionId": sid},
                     headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    return token
