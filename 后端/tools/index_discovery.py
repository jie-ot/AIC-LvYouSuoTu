"""Optional warm-up; the API also refreshes this cache in the background."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models.tables  # noqa: E402,F401
from app.core.config import settings  # noqa: E402
from app.services.discovery.semantic_index import refresh_user_index  # noqa: E402

if __name__ == "__main__":
    result = refresh_user_index(settings.DEFAULT_USER_ID)
    print(json.dumps(result))
    sys.exit(0 if result["status"] in {"ready", "disabled"} else 1)
