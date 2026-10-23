"""Headless backend: answers come from a list, and everything shown is recorded in a transcript."""

from typing import Any, Iterable

import base


class ScriptExhausted(RuntimeError):
    """The app asked for more answers than the script has."""


class ScriptedRunner(base.ApplicationRunnerBase):
    """Runs an app without a user.

    answers: consumed in order. A Write takes the text to enter, a Choice takes one of its choice
    values, and a selection (several flows/commands available) takes the flow or command name.
    transcript: list of (kind, name, text) tuples, kind is "read", "write", "choice", "select" or "warning".
    """

    def __init__(self, data: Any = None, answers: Iterable[Any] = ()):
        super().__init__(data)
        self.answers = list(answers)
        self.transcript: list[tuple[str, str, Any]] = []

    @property
    def remaining_answers(self) -> list[Any]:
        return list(self.answers)

    def _next(self, what: str):
        if not self.answers:
            raise ScriptExhausted(
                f"no scripted answer left for {what} (state {self.current_state!r}); "
                f"last transcript entries: {self.transcript[-3:]!r}"
            )
        return self.answers.pop(0)

    def warn(self, problems):
        for problem in problems:
            self.transcript.append(("warning", "", problem))

    def show_read(self, flow):
        self._read(flow)
        flow.complete()

    def show_write(self, flow):
        self._write(flow)
        flow.complete()

    def show_choice(self, flow):
        choices = list(flow.resolve_content(self.data) or flow.choices)
        answer = self._next(f"Choice '{flow.name}' {choices!r}")
        if answer not in choices:
            raise ValueError(f"scripted answer {answer!r} is not one of the choices {choices!r} of '{flow.name}'")
        self.transcript.append(("choice", flow.name, answer))
        flow.apply_update(self.data, answer)
        flow.complete()

    def show_combine(self, flow):
        for child in flow.flows:
            if isinstance(child, base.Read):
                self._read(child)
            elif isinstance(child, base.Write):
                self._write(child)
        flow.complete()

    def _read(self, flow):
        self.transcript.append(("read", flow.name, flow.resolve_content(self.data)))

    def _write(self, flow):
        prompt = flow.resolve_content(self.data)
        value = self._next(f"Write '{flow.name}' ({prompt})")
        self.transcript.append(("write", flow.name, value))
        flow.apply_update(self.data, value)

    def select_flow(self, flows, commands):
        names = [f.name for f in flows] + [c.name for c in commands]
        answer = self._next(f"selecting one of {names!r}")
        for f in list(flows) + list(commands):
            if f.name == answer:
                self.transcript.append(("select", str(self.current_state), answer))
                return f
        raise ValueError(f"scripted answer {answer!r} is not an available flow or command at {self.current_state!r}: {names!r}")
