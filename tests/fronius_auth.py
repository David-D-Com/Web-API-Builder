"""Shared Fronius credential helpers.

On Windows this can use Credential Manager through ``keyring``. Otherwise it
falls back to ``FRONIUS_USERNAME`` / ``FRONIUS_PASSWORD``.
"""

from __future__ import annotations

import getpass
import os
from typing import Any

from local_secrets import get_secret


KEYRING_SERVICE = "web-api-builder/fronius"
KEYRING_USERNAME_KEY = "__fronius_username__"


def _load_keyring() -> Any:
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The `keyring` package is required for Windows Credential Manager support."
        ) from exc
    return keyring


def save_credentials(username: str, password: str) -> None:
    keyring = _load_keyring()
    keyring.set_password(KEYRING_SERVICE, username, password)
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY, username)


def delete_credentials() -> None:
    keyring = _load_keyring()
    username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
    if username:
        try:
            keyring.delete_password(KEYRING_SERVICE, username)
        except Exception:
            pass
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
    except Exception:
        pass


def load_credentials() -> tuple[str | None, str | None]:
    username = get_secret("FRONIUS_USERNAME")
    password = get_secret("FRONIUS_PASSWORD")
    if username and password:
        return username, password

    if os.name == "nt":
        try:
            keyring = _load_keyring()
        except RuntimeError:
            keyring = None
        if keyring is not None:
            username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_KEY)
            if username:
                password = keyring.get_password(KEYRING_SERVICE, username)
                if password:
                    return username, password

    return None, None


def prompt_and_save_credentials() -> None:
    username = input("Fronius username/email: ").strip()
    password = getpass.getpass("Fronius password: ")
    if not username or not password:
        raise RuntimeError("Username and password are required.")
    save_credentials(username, password)
