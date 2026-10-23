import getpass
import sys

import base


class CuiRunner(base.ApplicationRunnerBase):
    def show_read(self, flow):
        print(f"\n--- {flow.name} ---")
        self._print(flow)
        input("[Press Enter to continue]")

    def show_write(self, flow):
        print(f"\n--- {flow.name} ---")
        self._ask(flow)

    def show_choice(self, flow):
        print(f"\n--- {flow.name} ---")
        self._choose(flow)

    def show_combine(self, flow):
        print(f"\n--- {flow.name} (Combined) ---")
        if not self._inline(flow):
            input("[Press Enter to continue]")

    def _inline(self, flow) -> bool:
        """Show the children of a Combine one below the other. Returns whether any input was taken."""
        asked = False
        for child in flow.flows:
            if isinstance(child, base.Read):
                self._print(child)
            elif isinstance(child, base.Write):
                self._ask(child)
                asked = True
            elif isinstance(child, base.Choice):
                self._choose(child)
                asked = True
            elif isinstance(child, (base.Combine, base.LinearCombine)):
                asked = self._inline(child) or asked
            else:
                raise TypeError(f"CuiRunner cannot show {type(child).__name__} '{child.name}' inside Combine '{flow.name}'")
        return asked

    def _print(self, flow: base.Read):
        print(flow.resolve_content(self.data))

    def _ask(self, flow: base.Write):
        prompt = f"{flow.resolve_content(self.data)}{_hint(flow.kind)}: "
        while True:
            if isinstance(flow.kind, base.Password):
                raw = _read_secret(prompt)
            else:
                raw = input(prompt)
            try:
                value = flow.accept(raw, self.data)
            except base.InvalidInput as e:
                print(f"  ! {e}")
                continue
            flow.apply_update(self.data, value)
            return

    def _choose(self, flow: base.Choice):
        choices = list(flow.resolve_content(self.data) or flow.choices)
        for i, choice in enumerate(choices):
            print(f"{i}: {choice}")
        while True:
            text = input("Select option: ")
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
            print("Commands: " + "  ".join(c.name for c in commands))
        by_name = {c.name: c for c in commands}
        while True:
            text = input(f"{self.current_state.name or ''}> ").strip()
            if text in by_name:
                return by_name[text]
            try:
                idx = int(text)
                if 0 <= idx < len(flows):
                    return flows[idx]
            except ValueError:
                pass
            print("Enter a flow number or a command name.")


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
