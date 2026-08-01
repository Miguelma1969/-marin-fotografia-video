from fastapi.testclient import TestClient
from app.main import app

PATHS = ["/", "/health", "/privacy", "/terms", "/biometric-consent", "/api/events"]

with TestClient(app) as client:
    failures = []
    for path in PATHS:
        response = client.get(path)
        print(f"{path}: {response.status_code}")
        if response.status_code != 200:
            failures.append((path, response.status_code))
    if failures:
        raise SystemExit(f"Smoke test failed: {failures}")
print("All smoke tests passed.")
