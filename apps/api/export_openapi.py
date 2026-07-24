"""Writes apps/api's OpenAPI schema to stdout as JSON.

Used by apps/web's `npm run generate:api-types` (openapi-typescript) so the
frontend's generated types can be regenerated without a running API server —
importing apps.api.main has no side effects that need a live Postgres
(SQLAlchemy engines connect lazily).

Run with: python -m apps.api.export_openapi
"""

import json

from apps.api.main import app


def main() -> None:
    print(json.dumps(app.openapi()))


if __name__ == "__main__":
    main()
