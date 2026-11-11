"""GitPython adapter that clones or updates each user's private Obsidian vault.

Round 2 / Q13: the personal access token is never written into the vault's
``.git/config``. It is handed to the single git process through environment
variables (``GIT_CONFIG_COUNT``/``GIT_CONFIG_KEY_0``/``GIT_CONFIG_VALUE_0`` →
an ``http.extraHeader`` with HTTP Basic auth, git >= 2.31), so it lives only in
that process' memory. The remote URL is always (re)set to the plain URL, which
also removes tokens that older versions stored in the URL — also on errors.
"""
import base64
import os

from urllib.parse import urlsplit
import logging
from git import Repo

logger = logging.getLogger(__name__)


def auth_env(token, repo_url):
    """Environment for one git call: token as an HTTP header, never as config/URL.

    The header is scoped to the repository's host (http.<https://host/>.extraHeader),
    so git never sends it to another server (e.g. a submodule elsewhere).
    """
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if token and repo_url.startswith("https://"):
        basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        host = urlsplit(repo_url).netloc.rsplit("@", 1)[-1]
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        })
    return env


def _strip_credentials(local_dir, repo_url):
    """Make sure origin points to the plain URL (no token) after any operation."""
    try:
        if os.path.exists(os.path.join(local_dir, '.git')):
            repo = Repo(local_dir)
            if 'origin' in [remote.name for remote in repo.remotes]:
                repo.remotes.origin.set_url(repo_url)
    except Exception as error:
        logger.warning("Could not reset remote URL: %s.", type(error).__name__)


def sync_obsidian_repo(repo_url, token, local_dir):
    """
    Synchronize a user's remote vault into the account-specific local directory.

    Args:
        repo_url: GitHub clone URL stored in the user's settings.
        token: Optional personal access token for private repositories.
        local_dir: Isolated filesystem directory assigned to this user.

    Returns:
        True when a clone or pull completes; False when configuration or Git I/O fails.
    """
    if not repo_url:
        logger.warning("Repository sync skipped: repository URL is not configured.")
        return False

    env = auth_env(token, repo_url)
    logger.info("Repository sync started.")
    from .vault_writer import VaultError, vault_lock
    try:
        with vault_lock(local_dir):
            return _sync_locked(repo_url, local_dir, env)
    except VaultError as error:
        logger.warning("Repository sync skipped: %s.", error.kind)
        return False


def _sync_locked(repo_url, local_dir, env):
    try:
        # Existing Git metadata means this directory is a clone that can be pulled.
        if os.path.exists(local_dir) and os.path.exists(os.path.join(local_dir, '.git')):
            logger.info("Repository clone found; pulling updates.")
            repo = Repo(local_dir)
            # Plain URL first: clears a token left in the URL by older versions.
            repo.remotes.origin.set_url(repo_url)
            with repo.git.custom_environment(**env):
                repo.remotes.origin.pull()
            logger.info("Repository pull completed.")
            return True

        logger.info("Repository clone missing; cloning repository.")
        # Remove an incomplete prior clone before retrying.
        if os.path.exists(local_dir):
            # Read-only git objects (Windows) made plain rmtree fail (B-32).
            from .vault_writer import remove_tree
            remove_tree(local_dir)
        parent_dir = os.path.dirname(local_dir)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        Repo.clone_from(repo_url, local_dir, env=env)
        logger.info("Repository clone completed.")
        return True

    except Exception as error:
        logger.error("Repository sync failed: %s.", type(error).__name__)
        return False
    finally:
        _strip_credentials(local_dir, repo_url)
