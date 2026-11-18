"""Let offline tests import Settings without creating a production default secret."""

from __future__ import annotations

import os

os.environ.setdefault("ADMIN_PASSWORD", "unit-test-admin-password")
os.environ.setdefault("JWT_SECRET_KEY", "unit-test-jwt-secret")
