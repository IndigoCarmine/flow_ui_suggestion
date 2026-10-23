"""Headless backend: answers come from a list, and everything shown is recorded in a transcript."""

from typing import Any, Iterable

import base


class ScriptExhausted(RuntimeError):
    """The app asked for more answers than the script has."""


class ScriptedRunner(base.ApplicationRunnerBase):
    """Runs an app without a user.

    answers: consumed in order. A Write takes what the user would enter (text, or an already typed value
    such as 30 or True; it is converted and validated by the Write's kind and validate, and a rejected
    answer raises base.InvalidInput with the message), a Choice takes one of its choice values, and a
    selection (several flows/commands available) takes the flow or command name.
    transcript: list of (kind, name, value) tuples, kind is "read", "write", "choice", "select" or "warning".
    For "write" the value is the converted one (e.g. an int for Number).
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
        self.transcript.append(("read", flow.name, flow.resolve_content(self.data)))

    def show_write(self, flow):
        prompt = flow.resolve_content(self.data)
        answer = self._next(f"Write '{flow.name}' ({prompt})")
        try:
            value = flow.accept(answer, self.data)
        except base.InvalidInput as e:
            raise base.InvalidInput(f"scripted answer {answer!r} for Write '{flow.name}' was rejected: {e}") from None
        self.transcript.append(("write", flow.name, value))
        flow.apply_update(self.data, value)

    def show_choice(self, flow):
        choices = list(flow.resolve_content(self.data) or flow.choices)
        answer = self._next(f"Choice '{flow.name}' {choices!r}")
        if answer not in choices:
            raise ValueError(f"scripted answer {answer!r} is not one of the choices {choices!r} of '{flow.name}'")
        self.transcript.append(("choice", flow.name, answer))
        flow.apply_update(self.data, answer)

    def show_combine(self, flow):
        # Without a screen, "shown together" is the same as one after another.
        for child in flow.flows:
            self.render(child)

    def select_flow(self, flows, commands):
        names = [f.name for f in flows] + [c.name for c in commands]
        answer = self._next(f"selecting one of {names!r}")
        for f in list(flows) + list(commands):
            if f.name == answer:
                self.transcript.append(("select", str(self.current_state), answer))
                return f
        raise ValueError(f"scripted answer {answer!r} is not an available flow or command at {self.current_state!r}: {names!r}")
