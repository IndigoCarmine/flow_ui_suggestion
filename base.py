import abc
import inspect
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, Callable, Optional, Union


class State:
    """A node of the flow graph.

    Named states compare by (class, name): two `State("home")` are the same node.
    An unnamed `State()` is only equal to itself.
    """

    def __init__(self, name: Optional[str] = None):
        self.name = name

    def _key(self):
        return None if self.name is None else (type(self), self.name)

    def __eq__(self, other):
        if not isinstance(other, State):
            return NotImplemented
        key = self._key()
        if key is None:
            return self is other
        return key == other._key()

    def __hash__(self):
        key = self._key()
        return object.__hash__(self) if key is None else hash(key)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name if self.name else ''})"


class _UniqueState(State):
    """A state with exactly one instance per class. Its display name is the class name ("Start"/"End").

    A name argument is accepted for compatibility but ignored, so one call can't rename the shared instance.
    """

    def __new__(cls, name: Optional[str] = None):
        instance = cls.__dict__.get("_instance")
        if instance is None:
            instance = super().__new__(cls)
            instance.name = cls.__name__
            cls._instance = instance
        return instance

    def __init__(self, name: Optional[str] = None):
        pass

    def _key(self):
        return (type(self),)

    def __repr__(self):
        return f"{self.__class__.__name__}()"


class Start(_UniqueState):
    """The start of the app. `Start()` and `Start("name")` are always the same object, named "Start"."""


class End(_UniqueState):
    """The end of the app. `End()` and `End("name")` are always the same object, named "End"."""


class Return:
    """End marker: go back to the state the flow started from. `Return()` is always the same object."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "Return()"


class Quit:
    """What `run()` returns when the user quit the app (closed the window, Ctrl-C, EOF where nothing could be
    cancelled). `Quit()` is always the same object, also available as `QUIT`. It is not a State."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "Quit()"


QUIT = Quit()


class _Sentinel:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name


CANCEL: Any = _Sentinel("CANCEL")
"""ScriptedRunner answer meaning "the user cancels the running flow here"."""


class Cancelled(Exception):
    """Raised by a runner while a cancellable flow runs: the user abandoned it. `run()` catches it and goes
    back to the state the flow began at, without evaluating its end."""


class UserQuit(Exception):
    """Raised by a runner when the user quits the app. `run()` catches it and returns `QUIT`."""


class Branch:
    """End of a flow that splits: `check(data)` returns one of the declared `candidates`."""

    def __init__(self, check: Callable[..., Any], candidates: list[Any]):
        self.check = check
        self.candidates = candidates

    def resolve(self, data: Any):
        result = _call_with_data(self.check, data)
        if not any(result == c for c in self.candidates):
            raise ValueError(
                f"Branch check returned {result!r}, which is not one of its candidates {self.candidates!r}"
            )
        return result


def _call_with_data(func: Callable, data: Any):
    if len(inspect.signature(func).parameters) == 0:
        return func()
    return func(data)


# --- input kinds: what kind of value a Write asks for (the runner picks the widget) ---------------


class InvalidInput(ValueError):
    """What the user entered was rejected. The message is meant to be shown to the user."""


class Kind:
    """What kind of value a Write asks for. Runners choose how to ask; the kind converts and checks.

    convert(raw): turn what was entered (text, or an already typed value from a widget) into the value;
    raise ValueError(message) if it can't. check(value): built-in validation, an error message or None.
    """

    def convert(self, raw: Any) -> Any:
        return raw

    def check(self, value: Any) -> Optional[str]:
        return None

    def __repr__(self):
        args = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"{self.__class__.__name__}({args})"


class Text(Kind):
    """Free text (the default). `required=True` rejects empty or blank input."""

    def __init__(self, required: bool = False):
        self.required = required

    def convert(self, raw: Any) -> str:
        return "" if raw is None else str(raw)

    def check(self, value: str) -> Optional[str]:
        if self.required and not value.strip():
            return "a value is required"
        return None


class Password(Text):
    """Text that should not be shown while it is entered."""


class Number(Kind):
    """A number between `min` and `max` (both optional). `decimals=0` (default) gives an int, otherwise a float."""

    def __init__(self, min: Optional[float] = None, max: Optional[float] = None, decimals: int = 0):
        self.min = min
        self.max = max
        self.decimals = decimals

    def convert(self, raw: Any) -> Union[int, float]:
        whole = self.decimals == 0
        if isinstance(raw, bool):
            raise ValueError("enter a number")
        if isinstance(raw, (int, float)):
            value = raw
        else:
            text = "" if raw is None else str(raw).strip()
            try:
                value = int(text) if whole else float(text)
            except ValueError:
                raise ValueError("enter a whole number" if whole else "enter a number") from None
        if whole:
            if not float(value).is_integer():
                raise ValueError("enter a whole number")
            return int(value)
        return float(value)

    def check(self, value: Union[int, float]) -> Optional[str]:
        low_ok = self.min is None or value >= self.min
        high_ok = self.max is None or value <= self.max
        if low_ok and high_ok:
            return None
        if self.min is not None and self.max is not None:
            return f"enter a number from {self.min} to {self.max}"
        if not low_ok:
            return f"enter a number of at least {self.min}"
        return f"enter a number of at most {self.max}"


class YesNo(Kind):
    """A yes/no answer, converted to bool. Text answers: y/yes/true/1 and n/no/false/0 (any case)."""

    YES = ("y", "yes", "true", "1")
    NO = ("n", "no", "false", "0")

    def convert(self, raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        text = "" if raw is None else str(raw).strip().lower()
        if text in self.YES:
            return True
        if text in self.NO:
            return False
        raise ValueError("answer yes or no (y/n)")


def _as_kind(kind: Union[Kind, type, None]) -> Kind:
    if kind is None:
        return Text()
    if isinstance(kind, type) and issubclass(kind, Kind):
        return kind()
    if not isinstance(kind, Kind):
        raise TypeError(f"kind must be a Kind such as Text(), Password(), Number() or YesNo(), not {kind!r}")
    return kind


# --- constructor arguments ------------------------------------------------------------------------

_UNSET: Any = object()


def _is_begin(arg: Any) -> bool:
    return arg is None or isinstance(arg, State) or (isinstance(arg, type) and issubclass(arg, State))


def _bind_args(cls_name: str, content_key: str, args: tuple, given: dict) -> dict:
    """Accept both `Step(content, name=...)` and the old `Step(begin, end, content, name)` positional form.

    The old form is detected by a State, a State subclass or None as the first positional argument.
    """
    if args:
        if _is_begin(args[0]):
            keys = ["begin_state", "end_state", content_key, "name"]
        else:
            keys = [content_key]
        if len(args) > len(keys):
            form = "(begin, end, " + content_key + ", name)" if len(keys) > 1 else f"({content_key}, name=...)"
            raise TypeError(f"{cls_name}{form} takes at most {len(keys)} positional argument{"s" if len(keys) > 1 else ""} ({len(args)} given)")
        for key, value in zip(keys, args):
            if given[key] is not _UNSET:
                raise TypeError(f"{cls_name}() got multiple values for '{key}'")
            given[key] = value
    return given


def _lookup(data: Any, key: str) -> tuple[bool, Any]:
    if isinstance(data, Mapping):
        return (key in data, data.get(key))
    try:
        return (True, getattr(data, key))
    except AttributeError:
        return (False, None)


class _Fields:
    """Lets `str.format_map` read fields from a dict, a dataclass (also with slots=True) or any object."""

    def __init__(self, data: Any):
        self.data = data

    def __getitem__(self, key: str):
        if isinstance(self.data, Mapping):
            return self.data[key]
        try:
            return getattr(self.data, key)
        except AttributeError:
            raise KeyError(key) from None


class MiniFlow:
    """Backend-independent step. It only holds data; the runner decides how to render it.

    begin_state: a State instance (explicit flow) or a State subclass (command flow,
    offered at every state that is an instance of it).
    end_state: a State, a Branch, Return(), or None (None means the same as Return()).

    Constructor: `Read("message", name=...)` (begin/end set later with `begin`/`begin_end` or as keywords),
    or the old positional form `Read(begin, end, "message", "name")`. Without a name, the message is used.
    cancellable: whether the user may abandon the flow midway (default: True for command flows only).
    command: optional short name for a command flow (default: `name`).
    """

    def __init__(
        self,
        *args: Any,
        begin_state: Union[State, type, None] = _UNSET,
        end_state: Union[State, Branch, Return, None] = _UNSET,
        message: str = _UNSET,
        name: Optional[str] = _UNSET,
        cancellable: Optional[bool] = None,
        command: Optional[str] = None,
    ):
        self.message = self._setup(args, begin_state, end_state, name, "message", message, "", cancellable, command)

    def _setup(
        self, args, begin_state, end_state, name, content_key: str, content, default, cancellable=None, command=None
    ):
        """Bind positional arguments (short or old form) and set the common attributes. Returns the content."""
        given = _bind_args(
            type(self).__name__,
            content_key,
            args,
            {"begin_state": begin_state, "end_state": end_state, content_key: content, "name": name},
        )
        self.begin_state = None if given["begin_state"] is _UNSET else given["begin_state"]
        self.end_state = None if given["end_state"] is _UNSET else given["end_state"]
        content = default if given[content_key] is _UNSET else given[content_key]
        message = content if content_key == "message" else ""
        name = None if given["name"] is _UNSET else given["name"]
        self.name = name or (message if isinstance(message, str) else "") or type(self).__name__
        self.message = message
        self.cancellable = cancellable
        if command is not None and (not isinstance(command, str) or not command.strip() or " " in command.strip()):
            raise TypeError(f"command must be a short name without spaces, not {command!r}")
        self._command = None if command is None else command.strip()

        # Data handling
        self._data_update_func: Optional[Union[Callable, str]] = None
        self._context_build_func: Optional[Union[Callable, str]] = None
        return content

    def begin(self, state_or_type: Union[State, type]):
        self.begin_state = state_or_type
        return self

    def begin_end(
        self,
        begin: Union[State, type],
        end: Union[State, Branch, Return, None],
    ):
        self.begin_state = begin
        self.end_state = end
        return self

    @property
    def is_command(self) -> bool:
        return isinstance(self.begin_state, type)

    @property
    def cancellable(self) -> bool:
        """Whether the user may abandon this flow midway. Default: True for command flows, False otherwise.
        Set with `cancellable=` in the constructor (or assign the attribute); None restores the default."""
        if self._cancellable is None:
            return self.is_command
        return self._cancellable

    @cancellable.setter
    def cancellable(self, value: Optional[bool]):
        self._cancellable = None if value is None else bool(value)

    @property
    def command(self) -> str:
        """The short name typed (CUI) or matched (ScriptedRunner) to pick this command flow. Default: `name`."""
        return self._command or self.name

    def data_update(
        self,
        func_or_attr: Union[Callable[[Any, Any], None], Callable[[Any], None], str],
    ):
        self._data_update_func = func_or_attr
        return self

    def context_build(
        self, func_or_tmpl: Union[Callable[[Any], Any], Callable[[], Any], str]
    ):
        self._context_build_func = func_or_tmpl
        return self

    def resolve_content(self, data: Any):
        if not self._context_build_func:
            return self.message

        tmpl = self._context_build_func
        if isinstance(tmpl, str):
            if "{" not in tmpl and "}" not in tmpl:
                # A bare name of an attribute/key of data gives that value; any other text is literal.
                found, value = _lookup(data, tmpl) if data is not None else (False, None)
                return value if found else tmpl
            if data is not None:
                try:
                    return tmpl.format_map(_Fields(data))
                except (KeyError, AttributeError):
                    pass
            return self.message

        return _call_with_data(self._context_build_func, data)

    def apply_update(self, data: Any, value: Any):
        if not self._data_update_func:
            return

        if isinstance(self._data_update_func, str):
            if isinstance(data, MutableMapping):
                data[self._data_update_func] = value
            elif data is not None:
                setattr(data, self._data_update_func, value)
            return

        sig = inspect.signature(self._data_update_func)
        if len(sig.parameters) == 1:
            self._data_update_func(value)
        else:
            self._data_update_func(data, value)


class ApplicationRunnerBase(abc.ABC):
    def __init__(self, data: Any = None):
        self.flows: list[MiniFlow] = []
        self.start_state: Optional[Start] = None
        self.current_state: Optional[State] = None
        self.data = data
        self.active_flow: Optional[MiniFlow] = None
        self.result: Any = None

    def add_miniflow(self, flow: MiniFlow):
        self.flows.append(flow)
        if isinstance(flow.begin_state, Start):
            self.start_state = flow.begin_state

    def run(self) -> Any:
        """Run the app from Start. Returns the final state: `End()` when the app reached End, `QUIT` when the
        user quit (the state they were at stays in `current_state`), or the state that had no flow to run.
        The value is also kept in `self.result`."""
        try:
            self._loop()
        except UserQuit:
            self.result = QUIT
        else:
            self.result = self.current_state
        finally:
            self.active_flow = None
        return self.result

    @property
    def can_cancel(self) -> bool:
        """Whether the flow that is running now (the one chosen at the current state) may be cancelled."""
        return self.active_flow is not None and self.active_flow.cancellable

    def cancelled(self, flow: "MiniFlow"):
        """Called after the user cancelled `flow` (the state is back at where it began). Backends may override."""

    def _loop(self):
        problems = self.validate()
        if problems:
            self.warn(problems)

        if not self.start_state:
            for f in self.flows:
                if isinstance(f.begin_state, Start):
                    self.start_state = f.begin_state
                    break

        self.current_state = self.start_state

        while not isinstance(self.current_state, End):
            flows, commands = self.flows_for(self.current_state)

            if not flows and not commands:
                print(f"DEBUG: No transitions from {self.current_state}")
                break

            if len(flows) == 1 and not commands:
                selected_flow = flows[0]
            else:
                selected_flow = self.select_flow(flows, commands)

            origin = self.current_state
            self.active_flow = selected_flow
            try:
                self.render(selected_flow)
            except Cancelled:
                # Updates of steps that already finished stay; the end (Branch etc.) is not evaluated.
                self.current_state = origin
                self.cancelled(selected_flow)
                continue
            finally:
                self.active_flow = None
            self.current_state = self.resolve_end(selected_flow.end_state, origin)

    def flows_for(self, state: State) -> tuple[list[MiniFlow], list[MiniFlow]]:
        """Explicit flows that begin at this state, and command flows whose type matches it."""
        flows = [f for f in self.flows if not f.is_command and f.begin_state == state]
        commands = []
        if not isinstance(state, End):
            commands = [
                f for f in self.flows if f.is_command and isinstance(state, f.begin_state)
            ]
        return flows, commands

    def resolve_end(self, end, origin: State) -> State:
        if isinstance(end, Branch):
            end = end.resolve(self.data)
        if end is None or end is Return():
            return origin
        return end

    def warn(self, problems: list[str]):
        """Report problems found by `validate()`. Backends may override this."""
        for problem in problems:
            print(f"WARNING: {problem}", file=sys.stderr)

    # --- static graph check -------------------------------------------------

    def states(self) -> list[State]:
        """Every State mentioned by a flow (begin, end or Branch candidate), in order of appearance."""
        found: dict[State, None] = {}
        for f in self.flows:
            if isinstance(f.begin_state, State):
                found.setdefault(f.begin_state)
            for target in _end_targets(f.end_state):
                if isinstance(target, State):
                    found.setdefault(target)
        return list(found)

    def successors(self, state: State) -> list[State]:
        """States reachable from `state` in one flow (Return/None means `state` itself)."""
        flows, commands = self.flows_for(state)
        result: dict[State, None] = {}
        for f in flows + commands:
            for target in _end_targets(f.end_state):
                if target is None or target is Return():
                    result.setdefault(state)
                elif isinstance(target, State):
                    result.setdefault(target)
        return list(result)

    def describe(self) -> str:
        """Text listing of the graph: states, explicit flows, Branch candidates and commands.

        Commands with a `command` alias are shown as `alias (name)`. A flow the user may cancel is marked
        `[cancellable]`. Under each flow, every Write it contains is listed with its kind.
        """
        lines = ["States:"]
        for st in self.states():
            flows, commands = self.flows_for(st)
            extra = f"  commands: {', '.join(_command_label(c) for c in commands)}" if commands else ""
            lines.append(f"  {st!r}{extra}")
        lines.append("Flows:")
        for f in self.flows:
            if not f.is_command:
                lines.append(f"  {f.name}: {f.begin_state!r} -> {_describe_end(f.end_state)}{_flags(f)}")
                lines.extend(_describe_writes(f))
        commands = [f for f in self.flows if f.is_command]
        if commands:
            lines.append("Commands:")
            for c in commands:
                lines.append(
                    f"  {_command_label(c)}: any {c.begin_state.__name__} -> {_describe_end(c.end_state)}{_flags(c)}"
                )
                lines.extend(_describe_writes(c))
        return "\n".join(lines)

    def validate(self) -> list[str]:
        """Check the graph without running it. Returns a list of problems (empty if none found)."""
        problems: list[str] = []
        states = self.states()

        starts = [f for f in self.flows if isinstance(f.begin_state, Start)]
        if not starts:
            problems.append("no flow begins at Start")

        branch_targets: dict[State, str] = {}
        for f in self.flows:
            if not isinstance(f.end_state, Branch):
                continue
            if not f.end_state.candidates:
                problems.append(f"Branch of flow '{f.name}' has no candidates")
            for c in f.end_state.candidates:
                if not isinstance(c, (State, Return)):
                    problems.append(f"Branch of flow '{f.name}' has candidate {c!r}, which is not a State or Return()")
                elif isinstance(c, State):
                    branch_targets.setdefault(c, f.name)

        for c in self.flows:
            if c.is_command and not any(isinstance(st, c.begin_state) for st in states):
                problems.append(f"command '{c.name}' begins at {c.begin_state.__name__}, but no state is of that type")

        for st in states:
            if isinstance(st, End):
                continue
            flows, commands = self.flows_for(st)
            seen_commands: dict[str, str] = {}
            for c in commands:
                if c.command in seen_commands:
                    problems.append(
                        f"commands '{seen_commands[c.command]}' and '{c.name}' are both typed as '{c.command}' at {st!r}"
                    )
                seen_commands.setdefault(c.command, c.name)
            if flows or commands:
                continue
            if st in branch_targets:
                problems.append(f"Branch candidate {st!r} of flow '{branch_targets[st]}' leads nowhere (no flow begins there)")
            else:
                problems.append(f"dead end: no flow begins at {st!r}")

        if starts:
            seen = {starts[0].begin_state}
            todo = [starts[0].begin_state]
            while todo:
                for nxt in self.successors(todo.pop()):
                    if nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            for st in states:
                if st not in seen:
                    problems.append(f"unreachable from Start: {st!r}")

        return problems

    def render(self, flow: MiniFlow):
        if isinstance(flow, Read):
            self.show_read(flow)
        elif isinstance(flow, Write):
            self.show_write(flow)
        elif isinstance(flow, Choice):
            self.show_choice(flow)
        elif isinstance(flow, Combine):
            self.show_combine(flow)
        elif isinstance(flow, LinearCombine):
            self.show_linear_combine(flow)
        else:
            raise TypeError(f"Unknown flow type: {type(flow).__name__}")

    def show_linear_combine(self, flow: "LinearCombine"):
        for child in flow.flows:
            self.render(child)

    @abc.abstractmethod
    def show_read(self, flow: "Read"):
        """Display information to the user."""

    @abc.abstractmethod
    def show_write(self, flow: "Write"):
        """Take input from the user."""

    @abc.abstractmethod
    def show_choice(self, flow: "Choice"):
        pass

    @abc.abstractmethod
    def show_combine(self, flow: "Combine"):
        """Show all child flows together."""

    @abc.abstractmethod
    def select_flow(self, flows: list[MiniFlow], commands: list[MiniFlow]) -> MiniFlow:
        """Let the user pick one of the explicit flows or commands available at the current state."""


def _end_targets(end) -> list:
    if isinstance(end, Branch):
        return list(end.candidates)
    return [end]


def _command_label(flow: "MiniFlow") -> str:
    return flow.name if flow.command == flow.name else f"{flow.command} ({flow.name})"


def _flags(flow: "MiniFlow") -> str:
    return "  [cancellable]" if flow.cancellable else ""


def _describe_writes(flow: "MiniFlow", depth: int = 2) -> list[str]:
    """One line per Write inside `flow` (itself included): `Write 'name': kind`."""
    if isinstance(flow, Write):
        return [f"{'  ' * depth}Write '{flow.name}': {flow.kind!r}"]
    lines: list[str] = []
    if isinstance(flow, (Combine, LinearCombine)):
        for child in flow.flows:
            lines.extend(_describe_writes(child, depth))
    return lines


def _describe_end(end) -> str:
    if end is None or end is Return():
        return "Return (back to where it began)"
    if isinstance(end, Branch):
        return "Branch[" + ", ".join(repr(c) for c in end.candidates) + "]"
    return repr(end)


class Read(MiniFlow):
    """The user reads: the app displays information. `Read("text", name=...)`."""


class Write(MiniFlow):
    """The user writes: the app takes input. `Write("prompt", name=..., kind=Number(min=0), validate=...)`.

    kind: what kind of value is wanted (Text() by default, Password(), Number(...), YesNo()); the runner
    picks the widget and `data_update` receives the converted value (str, int/float, bool).
    validate: optional `validate(value)` or `validate(data, value)` returning an error message or None.
    Runners ask again (showing the message) until the value is accepted.
    """

    def __init__(
        self,
        *args: Any,
        begin_state: Union[State, type, None] = _UNSET,
        end_state: Union[State, Branch, Return, None] = _UNSET,
        message: str = _UNSET,
        name: Optional[str] = _UNSET,
        kind: Union[Kind, type, None] = None,
        validate: Optional[Callable[..., Optional[str]]] = None,
        cancellable: Optional[bool] = None,
        command: Optional[str] = None,
    ):
        super().__init__(
            *args, begin_state=begin_state, end_state=end_state, message=message, name=name,
            cancellable=cancellable, command=command,
        )
        self.kind = _as_kind(kind)
        self.validator = validate

    def accept(self, raw: Any, data: Any = None) -> Any:
        """Convert and validate what the user entered. Returns the value or raises InvalidInput(message)."""
        try:
            value = self.kind.convert(raw)
        except ValueError as e:
            raise InvalidInput(str(e)) from None
        error = self.kind.check(value)
        if error is None and self.validator is not None:
            if len(inspect.signature(self.validator).parameters) >= 2:
                error = self.validator(data, value)
            else:
                error = self.validator(value)
        if error:
            raise InvalidInput(str(error))
        return value


class Choice(MiniFlow):
    """The user picks one of `choices`. `Choice(["a", "b"], name=...)`; old form `Choice(begin, end, choices, name)`."""

    def __init__(
        self, *args: Any, begin_state=_UNSET, end_state=_UNSET, choices=_UNSET, name=_UNSET, cancellable=None, command=None
    ):
        self.choices = self._setup(args, begin_state, end_state, name, "choices", choices, (), cancellable, command)


class Combine(MiniFlow):
    """Child steps shown together (one screen in a GUI). `Combine([...], name=...)`. Children may be any step."""

    def __init__(
        self, *args: Any, begin_state=_UNSET, end_state=_UNSET, flows=_UNSET, name=_UNSET, cancellable=None, command=None
    ):
        self.flows = self._setup(args, begin_state, end_state, name, "flows", flows, (), cancellable, command)


class LinearCombine(MiniFlow):
    """Child steps run one after another. `LinearCombine([...], name=...)`. Children may be any step."""

    def __init__(
        self, *args: Any, begin_state=_UNSET, end_state=_UNSET, flows=_UNSET, name=_UNSET, cancellable=None, command=None
    ):
        self.flows = self._setup(args, begin_state, end_state, name, "flows", flows, (), cancellable, command)
