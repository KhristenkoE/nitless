from abc import ABC, abstractmethod
from typing import ClassVar

from nitless.config import Settings
from nitless.models import ChangeRequest, ReviewResult


class OutputAdapter(ABC):
    """Publishes a review result somewhere. Implement `publish` and register the class.

    `change` is None when the run failed before the change could be resolved.
    """

    name: ClassVar[str]
    # Whether this adapter should also receive failed runs (status == "error").
    publishes_errors: ClassVar[bool] = True

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self) -> None:  # noqa: B027  (optional hook)
        """Fail fast on missing adapter config before any review work is done."""

    @abstractmethod
    def publish(self, result: ReviewResult, change: ChangeRequest | None) -> None: ...
