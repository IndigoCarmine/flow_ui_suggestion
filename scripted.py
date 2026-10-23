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
    Null (no value): `base.CANCEL`, None or "" (blank text) at a Write or Choice (for a Choice, only when it
    is not one of the choices). What happens follows the step's null policy: `?` exits the flow (recorded as
    ("cancel", flow name, step name)), `opt` stores None (recorded as a "write"/"choice" of None), `!` is a
    rejection ("a value is required", see on_reject) for an empty answer and a ValueError for CANCEL.
    `base.QUIT` (anywhere) quits, so `run()` returns QUIT.
    on_reject: what a rejected Write/Choice answer does. "raise" (default) raises base.InvalidInput /
    ValueError with the message; "next" records ("rejected", name, message) and uses the next answer,
    like a user who is asked again.
    transcript: list of (kind, name, value) tuples, kind is "read", "write", "choice", "select", "rejected",
    "cancel", "notice" (name: the flow, value: the text), "quit" or "warning". For "write" the value is the
    converted one (e.g. an int for Number).
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
        if answer is base.CANCEL and self.active_flow is None:
            raise ValueError(f"scripted answer CANCEL at {what}, but no flow is running (nothing to cancel)")
        return answer

    def _null(self, what: str, step: str, answer: Any) -> bool:
        """Apply the null policy to a null answer. True: store None. False: refused (empty answer, `!`)."""
        if self.null_given(step):
            return True
        if answer is base.CANCEL:
            raise ValueError(f"scripted answer CANCEL at {what}, but it cannot be cancelled ('!' policy)")
        return False

    def exited(self, flow, step):
        self.transcript.append(("cancel", flow.name, step))

    def show_notice(self, text):
        self.transcript.append(("notice", self.active_flow.name if self.active_flow else "", text))

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
            what = f"Write '{flow.name}' ({prompt})"
            answer = self._next(what, flow.name)
            if answer is base.CANCEL or flow.is_empty(answer):
                if self._null(what, flow.name, answer):
                    self.transcript.append(("write", flow.name, None))
                    flow.apply_update(self.data, None)
                    return
                error = base.InvalidInput(f"scripted answer {answer!r} for Write '{flow.name}' was rejected: {base.EMPTY_MESSAGE}")
                self._rejected(flow.name, base.InvalidInput(base.EMPTY_MESSAGE) if self.on_reject == "next" else error)
                continue
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
            what = f"Choice '{flow.name}' {choices!r}"
            answer = self._next(what, flow.name)
            if answer is not base.CANCEL and answer in choices:
                break
            if answer is base.CANCEL or flow.is_empty(answer):
                if self._null(what, flow.name, answer):
                    answer = None
                    break
                self._rejected(flow.name, ValueError(f"no choice given for '{flow.name}': choose one of {choices!r}"))
                continue
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
