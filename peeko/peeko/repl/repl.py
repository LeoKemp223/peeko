import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from peeko.config import STATE_DIR, HISTORY_FILE
from peeko.repl.session import Session
from peeko.repl.commands import handle_command
from peeko.repl.completer import PeekoCompleter


def start_repl():
    """Main REPL entry point."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    session = Session()

    print("Peeko Interactive Mode")
    print("Type /help for available commands, /quit to exit")
    print()

    prompt_session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=PeekoCompleter(session),
    )

    while True:
        try:
            line = prompt_session.prompt(session.prompt)
        except KeyboardInterrupt:
            continue
        except EOFError:
            # Ctrl+D → quit with state preserved
            session.save_state()
            print("Goodbye! (state preserved for next session)")
            break

        line = line.strip()
        if not line:
            continue

        result = handle_command(session, line)

        if result == "__QUIT__":
            print("Goodbye! (state preserved for next session)")
            break
        elif result == "__QUIT_FORCE__":
            print("Goodbye! (state cleared)")
            break
        elif result:
            print(result)
