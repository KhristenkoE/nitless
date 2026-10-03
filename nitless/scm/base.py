from abc import ABC, abstractmethod
from pathlib import Path

from nitless.models import ChangeRequest


class ScmProvider(ABC):
    """Source of the change under review: resolves it to commits and materialises the head tree."""

    name: str

    @abstractmethod
    def fetch_change(self) -> ChangeRequest:
        """Resolve the change to base/head commits plus its title and description."""

    @abstractmethod
    def checkout(self, change: ChangeRequest, dest: Path) -> Path:
        """Create a working tree at the change's head commit in `dest`, return its path.

        The base commit must also be available in that repository so it can be diffed.
        """
