import sys

from nitless.models import ChangeRequest, ReviewResult
from nitless.output.base import OutputAdapter


class JsonAdapter(OutputAdapter):
    """Machine-readable result to OUTPUT_FILE, or stdout (logs go to stderr, so stdout stays pure JSON)."""

    name = "json"

    def publish(self, result: ReviewResult, change: ChangeRequest | None) -> None:
        payload = result.model_dump_json(indent=2) + "\n"
        path = self.settings.output_file
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload)
        else:
            sys.stdout.write(payload)
            sys.stdout.flush()
