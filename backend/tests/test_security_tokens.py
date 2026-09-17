"""Encrypted secrets at rest, and OAuth state that cannot double as a login."""
import jwt
import pytest

from app.core.crypto import TokenDecryptionError, decrypt_secret, encrypt_secret
from app.core.security import create_oauth_state, verify_oauth_state


def test_secret_round_trip_never_stores_plaintext():
    ciphertext = encrypt_secret("1//refresh-token-value")
    assert "refresh-token-value" not in ciphertext
    assert decrypt_secret(ciphertext) == "1//refresh-token-value"


def test_tampered_ciphertext_is_rejected():
    ciphertext = encrypt_secret("secret")
    tampered = ciphertext[:-6] + ("AAAAAA" if not ciphertext.endswith("AAAAAA") else "BBBBBB")
    with pytest.raises(TokenDecryptionError):
        decrypt_secret(tampered)


def test_oauth_state_round_trip():
    state = create_oauth_state(organization_id="org1", user_id="user1", provider="gmail")
    claims = verify_oauth_state(state, provider="gmail")
    assert claims["org"] == "org1"
    assert claims["sub"] == "user1"


def test_state_issued_for_another_provider_is_rejected():
    state = create_oauth_state(organization_id="org1", user_id="user1", provider="gmail")
    with pytest.raises(jwt.InvalidTokenError):
        verify_oauth_state(state, provider="whatsapp")


def test_expired_state_is_rejected():
    state = create_oauth_state(
        organization_id="org1", user_id="user1", provider="gmail", ttl_minutes=-1
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_oauth_state(state, provider="gmail")


def test_a_session_token_is_not_a_valid_state(org_a):
    from app.core.security import create_access_token

    token = create_access_token(org_a["user_id"], {"org": org_a["org_id"]})
    with pytest.raises(jwt.InvalidTokenError):
        verify_oauth_state(token, provider="gmail")


async def test_oauth_state_cannot_be_used_as_a_session(api, org_a):
    """A state travels through browser URLs; it must never authenticate API calls."""
    state = create_oauth_state(
        organization_id=org_a["org_id"], user_id=org_a["user_id"], provider="gmail"
    )
    response = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {state}"})
    assert response.status_code == 401
