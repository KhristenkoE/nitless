"""Thin wrapper around the git CLI that never leaks credentials into errors."""

import base64
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class GitError(Exception):
    pass


def auth_env(token: str | None, user: str = "oauth2") -> dict[str, str]:
    """Pass HTTP credentials through git's env-based config so they stay out of argv and .git/config.

    `user` is the basic-auth user the host expects next to the token: `oauth2` (GitLab), `x-access-token` (GitHub).
    """
    if not token:
        return {}
    basic = base64.b64encode(f"{user}:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def run_git(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None,
            secrets: tuple[str, ...] = ()) -> str:
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    proc = subprocess.run(["git", *args], cwd=cwd, env=full_env, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        for secret in secrets:
            if secret:
                stderr = stderr.replace(secret, "***")
        raise GitError(f"git {args[0]} failed: {stderr}")
    return proc.stdout
