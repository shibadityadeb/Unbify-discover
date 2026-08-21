"""Accounts: the journey is free, the audit belongs to someone. Signup and
login issue bearer tokens; a session is claimed once and cannot be quietly
re-owned; the workspace door is closed to unclaimed sessions."""
import uuid


def _email():
    return f"a-{uuid.uuid4().hex[:10]}@test.local"


def _signup(client, name="Kam Tester", password="a-long-password"):
    email = _email()
    r = client.post("/v1/auth/signup", json={"name": name, "email": email, "password": password})
    assert r.status_code == 200, r.text
    out = r.json()
    return email, out["token"], out["user"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_login_me_roundtrip(client):
    email, token, user = _signup(client)
    assert user["name"] == "Kam Tester" and user["email"] == email

    me = client.get("/v1/auth/me", headers=_auth(token)).json()
    assert me["user"]["email"] == email
    assert me["auditSessionId"] is None    # no finished journey yet

    r = client.post("/v1/auth/login", json={"email": email, "password": "a-long-password"})
    assert r.status_code == 200 and r.json()["user"]["email"] == email


def test_wrong_password_and_duplicate_email_are_refused(client):
    email, token, _ = _signup(client)
    assert client.post("/v1/auth/login",
                       json={"email": email, "password": "not-the-password"}).status_code == 401
    r = client.post("/v1/auth/signup",
                    json={"name": "Other", "email": email, "password": "whatever-else"})
    assert r.status_code == 409


def test_me_requires_a_real_token(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=_auth("f" * 64)).status_code == 401


def test_claim_attaches_and_protects_a_session(client):
    sid = client.post("/v1/discover/sessions", json={}).json()["sessionId"]
    _, token, _ = _signup(client)
    r = client.post("/v1/auth/claim", json={"sessionId": sid}, headers=_auth(token))
    assert r.status_code == 200
    # idempotent for the same owner
    assert client.post("/v1/auth/claim", json={"sessionId": sid},
                       headers=_auth(token)).status_code == 200
    # a different account cannot take it over
    _, other, _ = _signup(client)
    r = client.post("/v1/auth/claim", json={"sessionId": sid}, headers=_auth(other))
    assert r.status_code == 409
    # claiming requires being signed in at all
    assert client.post("/v1/auth/claim", json={"sessionId": sid}).status_code == 401


def test_google_auth_refused_when_unconfigured(client):
    # No GOOGLE_CLIENT_ID in the test environment: the endpoint must refuse
    # rather than trust the client's credential blob.
    r = client.post("/v1/auth/google", json={"credential": "x" * 40})
    assert r.status_code == 401


def test_auth_config_shape(client):
    cfg = client.get("/v1/auth/config").json()
    assert "googleClientId" in cfg


def test_workspace_advance_requires_an_owner(client):
    """The full journey stays free and anonymous; only the door into the
    persistent workspace asks for a name. 401 — and the state is unchanged,
    so signing in and advancing again succeeds."""
    from tests.test_journey import drive_response
    data = client.post("/v1/discover/sessions", json={}).json()
    sid = data["sessionId"]
    for _ in range(80):
        it = data["interaction"]
        if it["type"] == "materialization":
            break
        if it["type"] in ("chapter_transition", "chapter_closing", "story_close"):
            data = client.post(f"/v1/discover/sessions/{sid}/advance",
                               json={"to": it["next"]}).json()
            continue
        data = client.post(f"/v1/discover/sessions/{sid}/responses",
                           json={"interactionId": it["id"], "response": drive_response(it),
                                 "elapsedMs": 2000}).json()
    assert data["interaction"]["type"] == "materialization"

    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"})
    assert r.status_code == 401
    assert client.get(f"/v1/discover/sessions/{sid}").json()["state"] == "MATERIALIZATION"

    _, token, _ = _signup(client)
    assert client.post("/v1/auth/claim", json={"sessionId": sid},
                       headers=_auth(token)).status_code == 200
    r = client.post(f"/v1/discover/sessions/{sid}/advance", json={"to": "DISCOVER_WORKSPACE"})
    assert r.status_code == 200 and r.json()["state"] == "DISCOVER_WORKSPACE"

    # and the finished audit is now reachable from the account
    me = client.get("/v1/auth/me", headers=_auth(token)).json()
    assert me["auditSessionId"] == sid
