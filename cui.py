import getpass
import shutil
import sys
import textwrap
from typing import Optional

import base

CANCEL_TEXT = ":q"
"""Typed alone at a prompt inside a flow: the user gives no value (cancel)."""


class CuiRunner(base.ApplicationRunnerBase):
    """Terminal backend.

    Null (no value): inside a flow, `:q` or EOF (Ctrl-D) at any prompt, or an empty answer to a Write or
    Choice. It follows the step's null policy: `?` exits the flow (data restored, the `.q()` message is
    printed), `opt` stores None (the prompt says "(optional)"), `!` asks again ("a value is required") or
    says that cancelling is not possible here. Quit: Ctrl-C anywhere, or EOF at the selection prompt or at a
    `!` step, ends `run()` with a short message (it returns base.QUIT). A second EOF in a row also quits, so
    piped input that has run out cannot loop. Read text is wrapped to the terminal width; Combine fields
    are numbered.
    """

    def __init__(self, data=None):
        super().__init__(data)
        self._eof_seen = False
        self._cancel_hint_shown = False

    def show_read(self, flow):
        print(f"\n--- {flow.name} ---")
        self._print(flow)
        self._pause()

    def show_write(self, flow):
        print(f"\n--- {flow.name} ---")
        self._ask(flow)

    def show_choice(self, flow):
        print(f"\n--- {flow.name} ---")
        self._choose(flow)

    def show_combine(self, flow):
        print(f"\n--- {flow.name} (Combined) ---")
        if not self._inline(flow, [0]):
            self._pause()

    def show_notice(self, text):
        print(f"\n[!] {text}")

    def exited(self, flow, step):
        if step != "Branch":
            print(f"(cancelled '{flow.name}')")

    def _pause(self):
        while True:
            text = self._read("[Press Enter to continue]")
            if text is None:
                continue
            if text is base.CANCEL and not self._refuse(base.CANCEL):
                continue
            return

    def _inline(self, flow, counter: list) -> bool:
        """Show the children of a Combine one below the other, numbering the input fields.
        Returns whether any input was taken."""
        asked = False
        for child in flow.flows:
            with self.entering(child):
                if isinstance(child, base.Read):
                    self._print(child)
                elif isinstance(child, (base.Write, base.Choice)):
                    counter[0] += 1
                    label = f"[{counter[0]}] "
                    if isinstance(child, base.Write):
                        self._ask(child, label)
                    else:
                        self._choose(child, label)
                    asked = True
                elif isinstance(child, (base.Combine, base.LinearCombine)):
                    asked = self._inline(child, counter) or asked
                else:
                    raise TypeError(f"CuiRunner cannot show {type(child).__name__} '{child.name}' inside Combine '{flow.name}'")
        return asked

    def _print(self, flow: base.Read):
        print(wrap(str(flow.resolve_content(self.data))))

    # --- reading a line: null / quit handling -----------------------------------------------------

    def _read(self, prompt: str, secret: bool = False, asks_value: bool = False):
        """One line from the user, `base.CANCEL` for `:q`/EOF inside a flow, or None ("ask again": a `:q`
        outside any flow). Raises base.UserQuit for the quit actions described in the class docstring."""
        policy = self.current_policy
        if self.active_flow is not None and policy.kind == "q" and not self._cancel_hint_shown:
            empty = ", leave it empty" if asks_value else ""
            print(f"  (type {CANCEL_TEXT}{empty} or press Ctrl-D to cancel '{self.active_flow.name}')")
            self._cancel_hint_shown = True
        try:
            text = _read_secret(prompt) if secret else input(prompt)
        except KeyboardInterrupt:
            print("\nInterrupted; exiting.")
            raise base.UserQuit() from None
        except EOFError:
            print()
            if self.active_flow is not None and policy.kind != "must" and not self._eof_seen:
                self._eof_seen = True
                return base.CANCEL
            print("End of input; exiting.")
            raise base.UserQuit() from None
        self._eof_seen = False
        if text.strip() == CANCEL_TEXT:
            if self.active_flow is None:
                print("  ! nothing to cancel here (Ctrl-D or Ctrl-C quits)")
                return None
            return base.CANCEL
        return text

    def _refuse(self, answer) -> bool:
        """Apply the null policy to a null answer: raises for `?`, True for `opt` (store None), False for
        `!` after telling the user why (the caller asks again)."""
        if self.null_given():
            return True
        if answer is base.CANCEL:
            print(f"  ! '{self.active_flow.name}' cannot be cancelled here")
        else:
            print(f"  ! {base.EMPTY_MESSAGE}")
        return False

    def _ask(self, flow: base.Write, label: str = ""):
        optional = " (optional)" if self.current_policy.kind == "opt" else ""
        prompt = f"{label}{flow.resolve_content(self.data)}{_hint(flow.kind)}{optional}: "
        while True:
            raw = self._read(prompt, secret=isinstance(flow.kind, base.Password), asks_value=True)
            if raw is None:
                continue
            if raw is base.CANCEL or flow.is_empty(raw):
                if self._refuse(raw):
                    flow.apply_update(self.data, None)
                    return
                continue
            try:
                value = flow.accept(raw, self.data)
            except base.InvalidInput as e:
                print(f"  ! {e}")
                continue
            flow.apply_update(self.data, value)
            return

    def _choose(self, flow: base.Choice, label: str = ""):
        choices = list(flow.resolve_content(self.data) or flow.choices)
        optional = " (optional)" if self.current_policy.kind == "opt" else ""
        if label:
            print(f"{label}{flow.name}")
        for i, choice in enumerate(choices):
            print(f"{i}: {choice}")
        while True:
            text = self._read(f"Select option{optional}: ", asks_value=True)
            if text is None:
                continue
            if text is base.CANCEL or not text.strip():
                if self._refuse(text):
                    flow.apply_update(self.data, None)
                    return
                continue
            try:
                idx = int(text)
            except ValueError:
                idx = -1
            if 0 <= idx < len(choices):
                flow.apply_update(self.data, choices[idx])
                return
            print(f"  ! enter a number from 0 to {len(choices) - 1}")

    def select_flow(self, flows, commands):
        print(f"\n[{self.current_state}]")
        for i, f in enumerate(flows):
            print(f"{i}: {f.name}")
        if commands:
            print("Commands: " + "  ".join(c.command for c in commands))
        while True:
            text = self._read(f"{self.current_state.name or ''}> ")
            if text is None:
                continue
            text = text.strip()
            try:
                idx = int(text)
                if 0 <= idx < len(flows):
                    return flows[idx]
            except ValueError:
                pass
            matches = match_command(text, commands)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print(f"  ! '{text}' could be: {', '.join(c.command for c in matches)}")
                continue
            print("Enter a flow number or a command name.")


def match_command(text: str, commands: list) -> list:
    """Commands typed as `text`: an exact command alias or name, else every command it is a prefix of."""
    if not text:
        return []
    exact = [c for c in commands if text in (c.command, c.name)]
    if exact:
        return exact[:1]
    return [c for c in commands if c.command.startswith(text) or c.name.startswith(text)]


def wrap(text: str, width: Optional[int] = None) -> str:
    """Wrap each line of `text` to the terminal width (keeps blank lines and line breaks)."""
    width = width or shutil.get_terminal_size().columns
    width = max(width - 1, 20)
    return "\n".join(textwrap.fill(line, width) if line.strip() else line for line in text.splitlines()) if text else text


def _read_secret(prompt: str) -> str:
    """getpass reads from the terminal (/dev/tty), not from stdin. When stdin is piped, read stdin instead."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def _hint(kind: base.Kind) -> str:
    if isinstance(kind, base.YesNo):
        return " [y/n]"
    if isinstance(kind, base.Number):
        if kind.min is not None and kind.max is not None:
            return f" ({kind.min}-{kind.max})"
        if kind.min is not None:
            return f" (>= {kind.min})"
        if kind.max is not None:
            return f" (<= {kind.max})"
    return ""
