"""The UX-invariant framework's shared machinery.

Three pieces:

* ``ConsoleClient`` — drives the API exactly the way ``console/src/api/client.ts``
  does (Bearer access token + ``X-Workspace-ID`` header), so journey tests read
  like a user session, not like endpoint pokes.

* ``load_fixture`` / ``assert_same_shape`` — the golden contract fixtures in
  ``fixtures/*.json`` are the single wire-format source of truth shared with the
  frontend: ``test_contract_fixtures.py`` proves the live API matches them
  key-for-key, and ``console/src/api/contracts.test.ts`` proves ``types.ts``
  matches the very same files. A shape change therefore fails one side until
  BOTH are updated together, deliberately.

* Semantic assertion helpers (``assert_field_error``, ``assert_honest_alert``)
  for the invariants that aren't about shape but about meaning.
"""
import json
from pathlib import Path

from rest_framework.test import APIClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def assert_same_shape(actual, expected, path="$"):
    """Recursive key-set comparison: ``actual`` must have exactly the keys the
    fixture has, at every nesting level. Values are compared structurally only
    (a fixture list pins the shape of its first element when it's an object) —
    the point is the contract, not the numbers."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {type(actual).__name__}"
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        assert not missing and not extra, (
            f"{path}: contract drift — missing keys {sorted(missing)}, "
            f"unexpected keys {sorted(extra)}. Update fixtures/*.json AND "
            f"console/src/api/types.ts (+ contracts.test.ts) together."
        )
        for key, value in expected.items():
            if isinstance(value, (dict, list)):
                assert_same_shape(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected array, got {type(actual).__name__}"
        if expected and actual and isinstance(expected[0], dict) and isinstance(actual[0], dict):
            assert_same_shape(actual[0], expected[0], f"{path}[0]")


def assert_field_error(resp, field: str):
    """Guardrail invariant: bad input is a 400 whose body names the offending
    field — the console's ``extractError`` renders exactly that."""
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.content!r}"
    assert field in resp.data, f"error body must name {field!r}: {resp.data!r}"


def assert_honest_alert(alert: dict):
    """Data-honesty invariants every alert must satisfy, forever:

    * synthetic data is always disclosed, in the flag AND the message;
    * when the AI layer did not run, nothing is fabricated — the confidence
      is NULL, never a made-up number.
    """
    if alert["data_synthetic"]:
        assert alert["message"].startswith("[SYNTHETIC DATA]"), alert["message"]
    if not alert["ai_used"]:
        assert alert["ai_confidence"] is None, alert["ai_confidence"]


class ConsoleClient:
    """A user session, driven the way the real console drives the API."""

    def __init__(self):
        self.api = APIClient()
        self.access = None
        self.refresh = None
        self.workspace_id = None

    # -- auth flow (mirrors store/auth.ts) --------------------------------
    def register(self, username, email, password):
        return self.api.post("/api/v1/auth/register/", {
            "username": username, "email": email, "password": password,
        }, format="json")

    def login(self, username, password):
        resp = self.api.post("/api/v1/auth/token/", {
            "username": username, "password": password,
        }, format="json")
        if resp.status_code == 200:
            self.access, self.refresh = resp.data["access"], resp.data["refresh"]
            self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        return resp

    def select_workspace(self, workspace_id=None):
        """Pick the first (default) workspace unless one is given — the same
        auto-select loadWorkspaces() performs after login."""
        if workspace_id is None:
            workspace_id = self.api.get("/api/v1/workspaces/").data["results"][0]["id"]
        self.workspace_id = str(workspace_id)
        self.api.defaults["HTTP_X_WORKSPACE_ID"] = self.workspace_id
        return self.workspace_id

    def logout(self):
        resp = self.api.post("/api/v1/auth/logout/", {"refresh": self.refresh},
                             format="json")
        self.api.credentials()
        self.api.defaults.pop("HTTP_X_WORKSPACE_ID", None)
        return resp

    # -- thin verb delegates ----------------------------------------------
    def get(self, path, **kw):
        return self.api.get(f"/api/v1{path}", **kw)

    def post(self, path, data=None, **kw):
        return self.api.post(f"/api/v1{path}", data, format="json", **kw)

    def patch(self, path, data=None, **kw):
        return self.api.patch(f"/api/v1{path}", data, format="json", **kw)

    def delete(self, path, **kw):
        return self.api.delete(f"/api/v1{path}", **kw)


def signup(username: str) -> ConsoleClient:
    """Register + login + select the default workspace — the standard opening
    move of every journey."""
    client = ConsoleClient()
    resp = client.register(username, f"{username}@example.com", f"{username}-sturdy-pass-9")
    assert resp.status_code == 201, resp.content
    assert client.login(username, f"{username}-sturdy-pass-9").status_code == 200
    client.select_workspace()
    return client
