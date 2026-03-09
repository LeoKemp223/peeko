import json
from peeko.config import STATE_DIR, STATE_FILE


class StateManager:
    """Persists connection state to ~/.peeko/state.json between CLI invocations."""

    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def save_state(self, port: str, baud: int, endian: str = "little",
                   symbols_path: str = ""):
        state = {
            "port": port,
            "baud": baud,
            "endian": endian,
            "symbols_path": symbols_path,
            "connected": True,
        }
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load_state(self) -> dict:
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def update_state(self, **kwargs):
        state = self.load_state()
        state.update(kwargs)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def clear_state(self):
        if STATE_FILE.exists():
            STATE_FILE.unlink()
