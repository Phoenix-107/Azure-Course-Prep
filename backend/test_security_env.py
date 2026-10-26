"""
Security verification tests for production lockdown:
1. Validates that docs_url, redoc_url, and openapi_url are None in production.
2. Validates that /api/dev/* routes are completely omitted in production.
3. Validates that docs_url and dev routes are active in development.
4. Validates administrative authentication dependency for staging/prod when dev endpoints are guarded.
"""

import importlib
import pytest
from fastapi import HTTPException


def get_all_route_paths(app) -> set:
    """Helper to collect all route paths across root and included routers."""
    paths = set()
    for r in app.routes:
        if getattr(r, "path", None):
            paths.add(r.path)
        if hasattr(r, "original_router"):
            for sub_r in r.original_router.routes:
                if getattr(sub_r, "path", None):
                    paths.add(sub_r.path)
    return paths


@pytest.fixture(autouse=True)
def restore_environment(monkeypatch):
    """Ensure tests run in clean environment and reload backend.main on teardown."""
    yield
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENABLE_DEV_ENDPOINTS", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    import backend.main
    importlib.reload(backend.main)


def test_production_environment_locks_down_endpoints(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ENABLE_DEV_ENDPOINTS", raising=False)

    import backend.main
    importlib.reload(backend.main)
    app = backend.main.app

    # Swagger, ReDoc, and OpenAPI schema must be disabled
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    # Dev endpoints must NOT be in the registered routes
    paths = get_all_route_paths(app)
    assert "/api/dev/advance-days" not in paths
    assert "/api/dev/reset-cards" not in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


def test_development_environment_enables_docs_and_dev_endpoints(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("ENABLE_DEV_ENDPOINTS", raising=False)

    import backend.main
    importlib.reload(backend.main)
    app = backend.main.app

    # Docs and OpenAPI schema must be enabled for local development
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"

    # Dev endpoints must be registered in the application routes
    paths = get_all_route_paths(app)
    assert "/api/dev/advance-days" in paths
    assert "/api/dev/reset-cards" in paths


def test_staging_with_admin_auth(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "super-secret-key-123")

    import backend.main
    importlib.reload(backend.main)
    app = backend.main.app

    # Docs remain disabled in production mode
    assert app.docs_url is None
    assert app.openapi_url is None

    # Dev endpoints are mounted
    paths = get_all_route_paths(app)
    assert "/api/dev/advance-days" in paths
    assert "/api/dev/reset-cards" in paths

    from backend.dev_router import verify_admin_secret

    # Missing / invalid key raises 401
    with pytest.raises(HTTPException) as exc_info:
        verify_admin_secret(api_key=None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        verify_admin_secret(api_key="wrong-key")
    assert exc_info.value.status_code == 401

    # Valid key passes
    assert verify_admin_secret(api_key="super-secret-key-123") is True
