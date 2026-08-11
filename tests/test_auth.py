import pytest
from fastapi import HTTPException

from company_agent.common.auth import validate_internal_api_key


def test_validate_internal_api_key_accepts_matching_key() -> None:
    validate_internal_api_key(expected_key="secret", received_key="secret")


def test_validate_internal_api_key_rejects_wrong_key() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_internal_api_key(expected_key="secret", received_key="wrong")

    assert exc_info.value.status_code == 401


def test_validate_internal_api_key_requires_configuration() -> None:
    with pytest.raises(RuntimeError):
        validate_internal_api_key(expected_key="", received_key="secret")


def test_validate_internal_api_key_rejects_missing_header() -> None:
    """A missing X-Internal-API-Key must 401, not crash on None."""
    with pytest.raises(HTTPException) as exc_info:
        validate_internal_api_key(expected_key="secret", received_key=None)

    assert exc_info.value.status_code == 401


def test_validate_internal_api_key_rejects_empty_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_internal_api_key(expected_key="secret", received_key="")

    assert exc_info.value.status_code == 401


def test_validate_internal_api_key_rejects_prefix_of_the_real_key() -> None:
    """
    Guards the constant-time compare: a prefix must be as rejected as any other
    wrong value, and comparison must not short-circuit on first difference.
    """
    with pytest.raises(HTTPException):
        validate_internal_api_key(expected_key="secret", received_key="secre")

    with pytest.raises(HTTPException):
        validate_internal_api_key(expected_key="secret", received_key="secretx")


def test_validate_internal_api_key_handles_non_ascii_header() -> None:
    """hmac.compare_digest raises TypeError on non-ASCII str; we must 401 instead."""
    with pytest.raises(HTTPException) as exc_info:
        validate_internal_api_key(expected_key="secret", received_key="clavé-ñ")

    assert exc_info.value.status_code == 401
