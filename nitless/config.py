"""Runtime configuration.

Precedence: CLI flags > environment variables > .env file > defaults.
Secrets are SecretStr so they never end up in logs or reprs.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from nitless.errors import ConfigError
from nitless.llm.pricing import parse_prices
from nitless.llm.providers import AUTODETECT, PROVIDERS
from nitless.models import Severity

DEFAULT_EXCLUDES = [
    # lockfiles
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Pipfile.lock",
    "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock", "*.lock",
    # build output, vendored and generated code
    "node_modules/", "vendor/", "dist/", "build/", "target/", "out/", ".venv/",
    "*.min.js", "*.min.css", "*.map", "*_pb2.py", "*_pb2_grpc.py", "*.pb.go", "*.generated.*",
    "__snapshots__/", "*.snap",
]

CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # --- target -----------------------------------------------------------
    mr_url: str | None = None
    repo_url: str | None = None
    local_repo: Path | None = None
    base_ref: str | None = None
    head_ref: str = "HEAD"
    task_source: str | None = None  # path (json/yaml/md/txt) or http(s) URL, e.g. a GitLab issue; see intent.py

    # --- credentials ------------------------------------------------------
    gitlab_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GITLAB_TOKEN", "GIT_TOKEN", "gitlab_token")
    )
    github_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GITHUB_TOKEN", "GH_TOKEN", "github_token")
    )
    llm_api_key: SecretStr | None = None  # overrides the provider's own variable below
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key")
    )
    openrouter_api_key: SecretStr | None = None

    # --- LLM --------------------------------------------------------------
    llm_provider: str | None = None  # anthropic|openai|gemini|github|openrouter|ollama|openai_compat; unset: by key
    llm_base_url: str | None = None  # a proxy, a self-hosted server, or the endpoint for openai_compat
    model_strong: str | None = None  # review and the requirements check; required
    model_fast: str | None = None  # intent, conventions, restating the summary; unset: MODEL_STRONG
    model_verifier: str | None = None  # the adversarial check of every finding; unset: MODEL_STRONG
    model_prices: CommaList = Field(default_factory=list)  # model=input/output USD per 1M tokens, for the cost line
    llm_timeout_s: float = 300
    llm_max_retries: int = 5
    llm_rate_limit_wait_s: float = 300
    llm_max_output_tokens: int = 16000

    # --- review tuning ----------------------------------------------------
    severity_floor: Severity = "minor"
    max_diff_lines: int = 3000
    context_budget_tokens: int = 12000
    related_budget_tokens: int = 24000
    conventions: bool = True  # CONVENTIONS=on|off: the fast-model conventions card
    verify: bool = True  # VERIFY=on|off: the adversarial verifier on every candidate finding
    min_confidence: float = Field(default=0.6, ge=0, le=1)  # verified findings below this are not posted (A/B, Opus)
    max_findings: int | None = Field(default=None, ge=0)  # per-MR cap; unset: scaled by diff size, 0: no cap
    on_oversize: Literal["fail", "partial"] = "partial"
    unit_budget_tokens: int = Field(default=12000, ge=1000)  # diff tokens per reviewer call; larger MRs are split
    max_units: int = Field(default=6, ge=1)  # reviewer calls per MR; 1 = always one call over the whole diff
    tools: bool = False  # TOOLS=on|off: read-only repository tools for the reviewer and the verifier
    max_tool_calls: int = Field(default=8, ge=1)  # per reviewer call (the verifier gets half)
    path_excludes: CommaList = Field(default_factory=list)

    # --- output -----------------------------------------------------------
    output_adapter: CommaList = Field(default_factory=lambda: ["json"])
    output_file: Path | None = None  # json adapter; stdout when unset
    markdown_file: Path | None = None  # markdown adapter; stdout when unset
    gitlab_dry_run: bool = False  # GITLAB_DRY_RUN=on|off: the gitlab adapter writes its requests to a file instead
    github_dry_run: bool = False  # GITHUB_DRY_RUN=on|off: the same for the github adapter
    # inline comments of earlier runs that this run no longer reports: resolve them, delete them, or leave them
    stale_comments: Literal["resolve", "delete", "keep"] = "resolve"

    # --- runtime ----------------------------------------------------------
    workdir: Path | None = None
    log_level: str = "INFO"

    @field_validator("output_adapter", "path_excludes", "model_prices", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _check_target(self) -> "Settings":
        if bool(self.mr_url) == bool(self.local_repo):
            raise ValueError("set exactly one of MR_URL (GitLab MR or GitHub PR) or LOCAL_REPO (local git repository)")
        if self.local_repo and not self.base_ref:
            raise ValueError("BASE_REF is required with LOCAL_REPO")
        self._resolve_llm()
        return self

    def _resolve_llm(self) -> None:
        if self.llm_provider is None:
            self.llm_provider = next((p for p in AUTODETECT if getattr(self, PROVIDERS[p].key_field)), None)
            if self.llm_provider is None:
                raise ValueError("no LLM configured: set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GEMINI_API_KEY, "
                                 "OPENROUTER_API_KEY), or LLM_PROVIDER with LLM_API_KEY")
        preset = PROVIDERS.get(self.llm_provider)
        if preset is None:
            raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, not {self.llm_provider!r}")
        if self.llm_provider == "openai_compat" and not self.llm_base_url:
            raise ValueError("LLM_BASE_URL is required with LLM_PROVIDER=openai_compat")
        if self.llm_api_key is None and preset.key_field:
            self.llm_api_key = getattr(self, preset.key_field)
        if preset.needs_key and self.llm_api_key is None:
            names = " or ".join(["LLM_API_KEY", *([preset.key_field.upper()] if preset.key_field else [])])
            raise ValueError(f"{names} is required with LLM_PROVIDER={self.llm_provider}")
        if not self.model_strong:
            raise ValueError("MODEL_STRONG is required (MODEL_FAST and MODEL_VERIFIER default to it)")
        self.model_fast = self.model_fast or self.model_strong
        self.model_verifier = self.model_verifier or self.model_strong
        try:
            parse_prices(self.model_prices)
        except ValueError:
            raise ValueError("MODEL_PRICES entries look like model=input/output, e.g. my-model=1.25/10") from None

    @property
    def llm_key(self) -> str:
        return self.llm_api_key.get_secret_value() if self.llm_api_key else ""

    @property
    def excludes(self) -> list[str]:
        return DEFAULT_EXCLUDES + self.path_excludes

    @property
    def models(self) -> list[str]:
        """Every model this configuration calls, for the preflight check."""
        return [self.model_strong, self.model_fast, *([self.model_verifier] if self.verify else [])]


def load_settings(**overrides: object) -> Settings:
    """Build settings, turning pydantic's validation output into one readable ConfigError."""
    try:
        return Settings(**{k: v for k, v in overrides.items() if v is not None})
    except ValidationError as e:
        problems = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]).upper()
            problems.append(f"  - {loc + ': ' if loc else ''}{err['msg'].removeprefix('Value error, ')}")
        raise ConfigError("invalid configuration:\n" + "\n".join(problems)) from None
