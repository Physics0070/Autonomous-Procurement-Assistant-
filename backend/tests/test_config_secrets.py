"""Outside development the app must refuse any JWT secret an attacker could know."""
import pytest

from app.core.config import Settings


@pytest.mark.parametrize("secret", [
    "CHANGE_ME_IN_PRODUCTION",
    "change-me-generate-a-real-secret",   # the value shipped in backend/.env.example
    "changeme",
    "short",                              # too short to resist guessing
])
def test_placeholder_or_weak_secrets_are_refused_outside_development(secret):
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY=secret, _env_file=None)


def test_a_real_secret_is_accepted_in_production():
    Settings(ENVIRONMENT="production", JWT_SECRET_KEY="k9Qz3vX7pL2mN8rT4wY6bH1jF5sD0aGc", _env_file=None)


def test_development_tolerates_the_placeholder():
    Settings(ENVIRONMENT="development", JWT_SECRET_KEY="change-me-generate-a-real-secret", _env_file=None)
