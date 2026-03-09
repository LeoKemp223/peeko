from prompt_toolkit.completion import Completer, Completion


SLASH_COMMANDS = [
    "/help", "/quit", "/exit", "/ports", "/status",
    "/open", "/close", "/create", "/load", "/get", "/set",
]


class PeekoCompleter(Completer):
    """Tab-completion for REPL: slash commands and variable names."""

    def __init__(self, session):
        self._session = session

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)

        # Slash commands
        if text.startswith("/"):
            for cmd in SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))
            return

        # Variable name completion
        if not self._session.resolver:
            return

        # Find the part after the last comma (for multi-var input)
        if "," in text:
            last_part = text.rsplit(",", 1)[1].strip()
        else:
            last_part = text.strip()

        # If writing (has =), don't complete after =
        if "=" in last_part:
            return

        # Get the prefix to match
        prefix = last_part

        # Dot-separated: complete struct members
        if "." in prefix:
            base, partial = prefix.rsplit(".", 1)
            members = self._get_members(base)
            for name in members:
                if name.lower().startswith(partial.lower()):
                    full = f"{base}.{name}"
                    yield Completion(full, start_position=-len(prefix))
        else:
            # Top-level symbol names
            for name in self._session.resolver.list_symbols():
                if name.lower().startswith(prefix.lower()):
                    yield Completion(name, start_position=-len(prefix))

    def _get_members(self, base_path: str) -> list:
        """Get member names for a given base path like 'sensor' or 'sensor.config'."""
        if not self._session.resolver:
            return []

        parts = base_path.split(".")
        root = parts[0]

        symbols = self._session.resolver.get_all_symbols()
        candidates = [s for s in symbols if s.get("name") == root]
        if not candidates:
            return []

        sym = candidates[0]
        for part in parts[1:]:
            members = sym.get("members", [])
            found = None
            for m in members:
                if m.get("name") == part:
                    found = m
                    break
            if found is None:
                return []
            sym = found

        members = sym.get("members", [])
        return [m.get("name", "") for m in members if m.get("name")]
