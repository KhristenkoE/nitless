from nitless.config import Settings
from nitless.scm.base import ScmProvider


def make_provider(settings: Settings) -> ScmProvider:
    if settings.local_repo:
        from nitless.scm.local import LocalProvider

        return LocalProvider(settings.local_repo, settings.base_ref or "", settings.head_ref)

    from nitless.scm.github import GitHubProvider, is_pr_url, parse_pr_url

    if is_pr_url(settings.mr_url):
        token = settings.github_token.get_secret_value() if settings.github_token else None
        return GitHubProvider(parse_pr_url(settings.mr_url or ""), token=token, clone_url=settings.repo_url)

    from nitless.scm.gitlab import GitLabProvider, parse_mr_url

    token = settings.gitlab_token.get_secret_value() if settings.gitlab_token else None
    return GitLabProvider(parse_mr_url(settings.mr_url or ""), token=token, clone_url=settings.repo_url)


__all__ = ["ScmProvider", "make_provider"]
