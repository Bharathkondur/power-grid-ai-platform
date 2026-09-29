"""Generate local demo secrets without printing them or overwriting existing configuration."""

import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; existing settings preserved")
path.write_text(
    f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nGRAFANA_PASSWORD={secrets.token_hex(24)}\n"
)
print("Created ignored .env with random local credentials")
