"""Headless backend: answers come from a list, and everything shown is recorded in a transcript."""

from typing import Any, Iterable

import base


class ScriptExhausted(RuntimeError):
    """The app asked for more answers than the script has."""


class ScriptedRunner(base.ApplicationRunnerBase):
    """Runs an app without a user.

    answers: consumed in order. A Write takes what the user would enter (text, or an already typed value
    such as 30 or True; it is converted and validated by the Write's kind and validate), a Choice takes one
    of its choice values, and a selection (several flows/commands available) takes the flow name or the
    command's `command` alias.
    Two sentinels stand for user actions: `base.CANCEL` (at a Write or Choice) cancels the running flow
    (a ValueError if that flow is not cancellable), and `base.QUIT` (anywhere) quits, so `run()` returns QUIT.
    on_reject: what a rejected Write/Choice answer does. "raise" (default) raises base.InvalidInput /
    ValueError with the message; "next" records ("rejected", name, message) and uses the next answer,
    like a user who is asked again.
    transcript: list of (kind, name, value) tuples, kind is "read", "write", "choice", "select", "rejected",
    "cancel", "quit" or "warning". For "write" the value is the converted one (e.g. an int for Number).
    """

    ON_REJECT = ("raise", "next")

    def __init__(self, data: Any = None, answers: Iterable[Any] = (), on_reject: str = "raise"):
        super().__init__(data)
        if on_reject not in self.ON_REJECT:
            raise ValueError(f"on_reject must be one of {self.ON_REJECT!r}, not {on_reject!r}")
        self.answers = list(answers)
        self.on_reject = on_reject
        self.transcript: list[tuple[str, str, Any]] = []

    @property
    def remaining_answers(self) -> list[Any]:
        return list(self.answers)

    def _next(self, what: str, step: str):
        if not self.answers:
            raise ScriptExhausted(
                f"no scripted answer left for {what} (state {self.current_state!r}); "
                f"last transcript entries: {self.transcript[-3:]!r}"
            )
        answer = self.answers.pop(0)
        if answer is base.QUIT:
            self.transcript.append(("quit", step, None))
            raise base.UserQuit()
        if answer is base.CANCEL:
            if not self.can_cancel:
                running = f"flow '{self.active_flow.name}'" if self.active_flow else "no flow"
                raise ValueError(f"scripted answer CANCEL at {what}, but {running} cannot be cancelled")
            self.transcript.append(("cancel", self.active_flow.name, step))
            raise base.Cancelled()
        return answer

    def _rejected(self, step: str, error: Exception) -> None:
        """Record a rejection when on_reject="next"; otherwise raise `error`."""
        if self.on_reject == "raise":
            raise error
        self.transcript.append(("rejected", step, str(error)))

    def warn(self, problems):
        for problem in problems:
            self.transcript.append(("warning", "", problem))

    def show_read(self, flow):
        self.transcript.append(("read", flow.name, flow.resolve_content(self.data)))

    def show_write(self, flow):
        prompt = flow.resolve_content(self.data)
        while True:
            answer = self._next(f"Write '{flow.name}' ({prompt})", flow.name)
            try:
                value = flow.accept(answer, self.data)
            except base.InvalidInput as e:
                if self.on_reject == "next":
                    self._rejected(flow.name, e)
                    continue
                raise base.InvalidInput(f"scripted answer {answer!r} for Write '{flow.name}' was rejected: {e}") from None
            self.transcript.append(("write", flow.name, value))
            flow.apply_update(self.data, value)
            return

    def show_choice(self, flow):
        choices = list(flow.resolve_content(self.data) or flow.choices)
        while True:
            answer = self._next(f"Choice '{flow.name}' {choices!r}", flow.name)
            if answer in choices:
                break
            self._rejected(
                flow.name,
                ValueError(f"scripted answer {answer!r} is not one of the choices {choices!r} of '{flow.name}'"),
            )
        self.transcript.append(("choice", flow.name, answer))
        flow.apply_update(self.data, answer)

    def show_combine(self, flow):
        # Without a screen, "shown together" is the same as one after another.
        for child in flow.flows:
            self.render(child)

    def select_flow(self, flows, commands):
        names = [f.name for f in flows] + [c.command for c in commands]
        answer = self._next(f"selecting one of {names!r}", str(self.current_state))
        for f in list(flows) + list(commands):
            if f.name == answer or (f.is_command and f.command == answer):
                self.transcript.append(("select", str(self.current_state), f.name))
                return f
        raise ValueError(f"scripted answer {answer!r} is not an available flow or command at {self.current_state!r}: {names!r}")
