import base


class CuiRunner(base.ApplicationRunnerBase):
    def show_read(self, flow):
        print(f"\n--- {flow.name} ---")
        self._print(flow)
        input("[Press Enter to continue]")
        flow.complete()

    def show_write(self, flow):
        print(f"\n--- {flow.name} ---")
        self._ask(flow)
        flow.complete()

    def show_choice(self, flow):
        choices = flow.resolve_content(self.data) or flow.choices
        print(f"\n--- {flow.name} ---")
        for i, choice in enumerate(choices):
            print(f"{i}: {choice}")
        while True:
            try:
                idx = int(input("Select option: "))
                if 0 <= idx < len(choices):
                    flow.apply_update(self.data, choices[idx])
                    flow.complete()
                    break
            except ValueError:
                pass

    def show_combine(self, flow):
        print(f"\n--- {flow.name} (Combined) ---")
        for child in flow.flows:
            if isinstance(child, base.Read):
                self._print(child)
            elif isinstance(child, base.Write):
                self._ask(child)
        input("[Press Enter to continue]")
        flow.complete()

    def _print(self, flow: base.Read):
        print(flow.resolve_content(self.data))

    def _ask(self, flow: base.Write):
        prompt = flow.resolve_content(self.data)
        val = input(f"{prompt}: ")
        flow.apply_update(self.data, val)

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
