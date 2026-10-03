"""A base..head range in a local git repository. Used for offline evaluation and development."""

from pathlib import Path

from nitless.errors import ChangeNotFoundError, RepoAccessError
from nitless.git import GitError, run_git
from nitless.models import ChangeRequest
from nitless.scm.base import ScmProvider


class LocalProvider(ScmProvider):
    name = "local"

    def __init__(self, repo: Path, base_ref: str, head_ref: str = "HEAD"):
        self.repo = repo.expanduser().resolve()
        self.base_ref = base_ref
        self.head_ref = head_ref

    def _git(self, *args: str) -> str:
        return run_git(list(args), cwd=self.repo).strip()

    def fetch_change(self) -> ChangeRequest:
        if not (self.repo / ".git").exists():
            raise RepoAccessError(f"LOCAL_REPO is not a git repository: {self.repo}")
        try:
            head = self._git("rev-parse", "--verify", f"{self.head_ref}^{{commit}}")
            target = self._git("rev-parse", "--verify", f"{self.base_ref}^{{commit}}")
            base = self._git("merge-base", target, head)
            subjects = self._git("log", "--reverse", "--format=%s", f"{base}..{head}").splitlines()
            bodies = self._git("log", "--reverse", "--format=%B", f"{base}..{head}")
        except GitError as e:
            raise ChangeNotFoundError(f"cannot resolve {self.base_ref}..{self.head_ref} in {self.repo}: {e}") from None
        if base == head:
            raise ChangeNotFoundError(f"{self.head_ref} has no commits on top of {self.base_ref}")
        return ChangeRequest(
            provider=self.name,
            repo=str(self.repo),
            ref=f"{self.base_ref}..{self.head_ref}",
            title=subjects[0] if len(subjects) == 1 else f"{len(subjects)} commits on top of {self.base_ref}",
            description=bodies.strip(),
            source_branch=self.head_ref,
            target_branch=self.base_ref,
            base_sha=base,
            start_sha=target,
            head_sha=head,
        )

    def checkout(self, change: ChangeRequest, dest: Path) -> Path:
        # A local clone keeps the user's working tree untouched.
        try:
            run_git(["clone", "-q", "--no-hardlinks", "--no-checkout", str(self.repo), str(dest)])
            run_git(["checkout", "-q", "--detach", change.head_sha], cwd=dest)
        except GitError as e:
            raise RepoAccessError(f"cannot check out {change.head_sha[:12]}: {e}") from None
        return dest
