"""Operator commands. Run inside the container, e.g.:

    docker compose exec app python -m app.tools models
    docker compose exec app python -m app.tools ai-status
    docker compose exec app python -m app.tools reset-ai-budget --i-understand-this-reauthorises-spend

They read the same environment as the app and never print the API key.
"""

from __future__ import annotations

import json
import sys

from app.budget import Budget
from app.config import Settings
from app.db import init_db
from app.llm import LLMError, get_llm


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    s = Settings.from_env()
    if cmd == "models":
        try:
            data = get_llm(s).models()
        except LLMError as exc:
            print(f"error: {exc.public_message}", file=sys.stderr)
            return 1
        for m in data.get("data", []):
            print(m["id"])
        print("\nSet one of these ids as LLM_MODEL in .env, then restart the app.", file=sys.stderr)
        return 0
    if cmd == "ai-status":
        init_db(s.db_path)
        print(
            json.dumps(
                {"mode": s.ai_mode, "model": s.model or None, "budget": Budget(s).usage()}, indent=2
            )
        )
        return 0
    if cmd == "reset-ai-budget":
        if "--i-understand-this-reauthorises-spend" not in argv:
            print("Refusing: this clears the LIFETIME spending counter. Re-run with "
                  "--i-understand-this-reauthorises-spend only if you have approved more spend.",
                  file=sys.stderr)  # fmt: skip
            return 2
        init_db(s.db_path)
        Budget(s).reset()
        print(
            "Lifetime AI counters and per-client throttles were cleared (the attempt log is kept)."
        )
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
