"""Failure taxonomy.

Every expected failure is a ReviewerError with its own exit code, so callers
can tell an unreachable repo from an LLM outage without parsing text.
"""


class ReviewerError(Exception):
    exit_code = 1
    kind = "internal"


class ConfigError(ReviewerError):
    exit_code = 2
    kind = "config"


class RepoAccessError(ReviewerError):
    exit_code = 3
    kind = "repo_access"


class ChangeNotFoundError(ReviewerError):
    exit_code = 4
    kind = "change_not_found"


class TaskSourceError(ReviewerError):
    exit_code = 5
    kind = "task_source"


class DiffTooLargeError(ReviewerError):
    exit_code = 6
    kind = "diff_too_large"


class LLMError(ReviewerError):
    exit_code = 7
    kind = "llm"


class QuotaExhaustedError(LLMError):
    """The provider's quota, credit or daily cap is spent: not transient, so no stage degrades around it."""


class PublishError(ReviewerError):
    exit_code = 8
    kind = "publish"
