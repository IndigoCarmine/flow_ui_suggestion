import base


class Read(base.Read):
    def run_interaction(self, runner):
        prompt = self.resolve_content(runner.data)
        print(f"\n--- {self.name} ---")
        val = input(f"{prompt}: ")
        self.apply_update(runner.data, val)
        self.complete()


class Write(base.Write):
    def run_interaction(self, runner):
        content = self.resolve_content(runner.data)
        print(f"\n--- {self.name} ---")
        print(content)
        input("[Press Enter to continue]")
        self.complete()


class Choice(base.Choice):
    def run_interaction(self, runner):
        choices = self.resolve_content(runner.data) or self.choices
        print(f"\n--- {self.name} ---")
        for i, choice in enumerate(choices):
            print(f"{i}: {choice}")
        while True:
            try:
                idx = int(input("Select option: "))
                if 0 <= idx < len(choices):
                    self.apply_update(runner.data, choices[idx])
                    self.complete()
                    break
            except ValueError:
                pass


class Combine(base.Combine):
    def run_interaction(self, runner):
        print(f"\n--- {self.name} (Combined) ---")
        for flow in self.flows:
            if isinstance(flow, base.Read):
                p = flow.resolve_content(runner.data)
                val = input(f"{p}: ")
                flow.apply_update(runner.data, val)
            elif isinstance(flow, base.Write):
                c = flow.resolve_content(runner.data)
                print(c)
        input("[Press Enter to continue]")
        self.complete()


class LinearCombine(base.LinearCombine):
    def run_interaction(self, runner):
        for flow in self.flows:
            flow.is_complete = False
            flow.run_interaction(runner)
        self.complete()


class Start(base.Start):
    pass


class End(base.End):
    pass


class ApplicationRunner(base.ApplicationRunnerBase):
    def select_flow(self, flows):
        print("\nMultiple flows available. Select one:")
        for i, f in enumerate(flows):
            print(f"{i}: {f.name}")
        while True:
            try:
                idx = int(input("Select flow: "))
                if 0 <= idx < len(flows):
                    return flows[idx]
            except ValueError:
                pass
