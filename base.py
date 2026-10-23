import abc
import contextlib
import copy
import inspect
import sys
from collections.abc import Mapping, MutableMapping, MutableSequence
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
"""ScriptedRunner answer meaning "the user cancels here" (one way of giving no value, i.e. null)."""


# --- null handling: what a step does when the user gives no value ---------------------------------


class NullPolicy:
    """What happens when a step yields null (the user cancelled, left an optional field empty, or a Branch
    check returned None). Set on a step with `.q(message)` (Rust `?`), `.must()` (Kotlin `!!`) or `.opt()`.

    kind: "q" (exit the running top-level flow; data goes back to how it was when the flow started),
    "must" (null is refused: ask again / refuse cancel) or "opt" (store None and continue).
    message: only for "q", a notice the runner shows after going back.
    """

    KINDS = ("q", "must", "opt")

    def __init__(self, kind: str, message: Optional[str] = None):
        if kind not in self.KINDS:
            raise ValueError(f"null policy must be one of {self.KINDS!r}, not {kind!r}")
        if message is not None and kind != "q":
            raise ValueError("only .q() takes a message")
        self.kind = kind
        self.message = message

    @property
    def label(self) -> str:
        """`?`, `? "message"`, `!` or `opt` (used by describe())."""
        if self.kind == "q":
            return "?" if self.message is None else f"? {self.message!r}"
        return "!" if self.kind == "must" else "opt"

    def __eq__(self, other):
        return isinstance(other, NullPolicy) and (self.kind, self.message) == (other.kind, other.message)

    def __hash__(self):
        return hash((self.kind, self.message))

    def __repr__(self):
        if self.kind == "q":
            return "NullPolicy('q')" if self.message is None else f"NullPolicy('q', {self.message!r})"
        return f"NullPolicy({self.kind!r})"


Q = NullPolicy("q")
MUST = NullPolicy("must")
OPT = NullPolicy("opt")


class _NullMarks:
    """Mixin for the fluent null-policy methods. `null_policy` is the step's own mark (None: inherit)."""

    null_policy: Optional[NullPolicy] = None

    def q(self, message: Optional[str] = None):
        """`?`: if this step yields null, exit the running top-level flow and go back to where it began, as if
        nothing happened (data is restored). `message` is shown to the user as a notice."""
        self.null_policy = NullPolicy("q", message)
        return self

    def must(self):
        """`!`: null is not allowed. An empty answer is asked again; cancel is refused with a hint."""
        self.null_policy = MUST
        return self

    def opt(self):
        """Null is accepted: `data_update` receives None and the flow continues."""
        self.null_policy = OPT
        return self


class Cancelled(Exception):
    """Internal: raised (by a runner, or by a Branch marked `.q()`) when a step with the `?` policy yields
    null. `run()` catches it, restores the data snapshot taken when the flow began, goes back to the state
    the flow began at (without evaluating its end), and shows `message` as a notice if it is set."""

    def __init__(self, message: Optional[str] = None, step: Optional[str] = None):
        super().__init__(message or "")
        self.message = message
        self.step = step


class UserQuit(Exception):
    """Raised by a runner when the user quits the app. `run()` catches it and returns `QUIT`."""


class Branch(_NullMarks):
    """End of a flow that splits: `check(data)` returns one of the declared `candidates`.

    `check` may return None (null). With `.q(message)` that exits the flow like a cancel (data restored,
    back to where the flow began, `message` shown). With `.opt()` it means "go back to where the flow began"
    and keeps the data. Without a mark (or with `.must()`) None is an error like any other non-candidate.
    Branch marks are its own; they are not inherited from the flow.
    """

    def __init__(self, check: Callable[..., Any], candidates: list[Any]):
        self.check = check
        self.candidates = candidates

    def resolve(self, data: Any):
        result = _call_with_data(self.check, data)
        if result is None and self.null_policy is not None and self.null_policy.kind != "must":
            if self.null_policy.kind == "q":
                raise Cancelled(self.null_policy.message, step="Branch")
            return Return()
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

    def is_empty(self, raw: Any) -> bool:
        """Whether `raw` means "no value" (null): None, or text that is empty or only blanks."""
        return _is_blank(raw)

    def __repr__(self):
        args = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"{self.__class__.__name__}({args})"


def _is_blank(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


EMPTY_MESSAGE = "a value is required"
"""What runners show when a `.must()` step gets an empty answer."""


class Text(Kind):
    """Free text (the default). Empty or blank input is null (see `.q()` / `.must()` / `.opt()` on the step).
    `required=True` is a synonym for marking the Write `.must()`."""

    def __init__(self, required: bool = False):
        self.required = required

    def convert(self, raw: Any) -> str:
        return "" if raw is None else str(raw)

    def check(self, value: str) -> Optional[str]:
        if self.required and not value.strip():
            return EMPTY_MESSAGE
        return None


class Password(Text):
    """Text that should not be shown while it is entered."""


class Number(Kind):
    """A number between `min` and `max` (both optional). `decimals=0` (default) gives an int, otherwise a float.
    Empty input is null (None with `.opt()`)."""

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
    """A yes/no answer, converted to bool. Text answers: y/yes/true/1 and n/no/false/0 (any case); an empty
    text answer is null (a GUI check box always has a value)."""

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


class MiniFlow(_NullMarks):
    """Backend-independent step. It only holds data; the runner decides how to render it.

    begin_state: a State instance (explicit flow) or a State subclass (command flow,
    offered at every state that is an instance of it).
    end_state: a State, a Branch, Return(), or None (None means the same as Return()).

    Constructor: `Read("message", name=...)` (begin/end set later with `begin`/`begin_end` or as keywords),
    or the old positional form `Read(begin, end, "message", "name")`. Without a name, the message is used.
    command: optional short name for a command flow (default: `name`).
    Null handling: `.q(message)` / `.must()` / `.opt()` (see `NullPolicy`); unmarked steps inherit from the
    nearest marked enclosing Combine/LinearCombine, and a top-level flow defaults to `?` for command flows
    and `!` otherwise.
    """

    def __init__(
        self,
        *args: Any,
        begin_state: Union[State, type, None] = _UNSET,
        end_state: Union[State, Branch, Return, None] = _UNSET,
        message: str = _UNSET,
        name: Optional[str] = _UNSET,
        command: Optional[str] = None,
    ):
        self.message = self._setup(args, begin_state, end_state, name, "message", message, "", command)

    def _setup(self, args, begin_state, end_state, name, content_key: str, content, default, command=None):
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
        self.null_policy: Optional[NullPolicy] = None
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

    def own_policy(self) -> Optional[NullPolicy]:
        """The null policy written on this step itself (None: inherit). `Text(required=True)` counts as `.must()`."""
        return self.null_policy

    def is_empty(self, raw: Any) -> bool:
        """Whether an answer means "no value" (null). Default: None or blank text."""
        return _is_blank(raw)

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
        self._policies: list[NullPolicy] = []

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
            self._policies = []
        return self.result

    # --- null policies ------------------------------------------------------------------------------

    @staticmethod
    def default_policy(flow: "MiniFlow") -> NullPolicy:
        """What an unmarked top-level flow does on null: `?` for command flows, `!` for the others."""
        return Q if flow.is_command else MUST

    def policy_for(self, step: "MiniFlow", inherited: Optional[NullPolicy] = None) -> NullPolicy:
        """The effective policy of `step`: its own mark, else `inherited` (the enclosing step's effective
        policy), else the top-level default of the running flow (or of `step` itself)."""
        own = step.own_policy()
        if own is not None:
            return own
        if inherited is not None:
            return inherited
        return self.default_policy(self.active_flow or step)

    @property
    def current_policy(self) -> NullPolicy:
        """The effective policy of the step being shown now (MUST when no flow is running)."""
        if self._policies:
            return self._policies[-1]
        return self.default_policy(self.active_flow) if self.active_flow is not None else MUST

    @contextlib.contextmanager
    def entering(self, step: "MiniFlow"):
        """Make `step`'s effective policy the current one while it is shown. `render()` does this for every
        step; backends that show children themselves (a Combine on one screen) use it per child."""
        self._policies.append(self.policy_for(step, self._policies[-1] if self._policies else None))
        try:
            yield self._policies[-1]
        finally:
            self._policies.pop()

    def null_given(self, step: Optional[str] = None, policy: Optional[NullPolicy] = None) -> bool:
        """A step yielded null (cancel or empty answer). Applies `policy` (default: the current one):
        `?` raises Cancelled (the flow exits), `opt` returns True (store None and go on), `!` returns False
        (the backend refuses: ask again, or say that cancelling is not possible here)."""
        policy = policy or self.current_policy
        if policy.kind == "q":
            raise Cancelled(policy.message, step=step)
        return policy.kind == "opt"

    def exited(self, flow: "MiniFlow", step: Optional[str]):
        """Called after `flow` exited through `?` (data restored, state back where it began), before the
        notice is shown. `step` names where the null came from ("Branch" for a Branch). Backends may override."""

    @abc.abstractmethod
    def show_notice(self, text: str):
        """Show a short message to the user (the message of a `.q(message)` exit)."""

    # --- data snapshot --------------------------------------------------------------------------------

    def snapshot(self) -> Any:
        """A deep copy of `data`, taken when a flow starts (None if it cannot be copied)."""
        try:
            return copy.deepcopy(self.data)
        except Exception as e:  # e.g. data holding a lock or an open file
            self.warn([f"data could not be copied ({e}); a flow that exits with ? cannot restore it"])
            return None

    def restore(self, snapshot: Any):
        """Put `data` back to `snapshot` in place, so the app's data object stays the same object."""
        if snapshot is not None:
            restore_in_place(self.data, snapshot)

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
            before = self.snapshot()
            self.active_flow = selected_flow
            try:
                self.render(selected_flow)
                following = self.resolve_end(selected_flow.end_state, origin)
            except Cancelled as exit_:
                # `?`: nothing happened. Data goes back to how it was when the flow began.
                self.restore(before)
                self.current_state = origin
                self.exited(selected_flow, exit_.step)
                if exit_.message:
                    self.show_notice(exit_.message)
                continue
            finally:
                self.active_flow = None
                self._policies = []
            self.current_state = following

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

        Commands with a `command` alias are shown as `alias (name)`. Every flow shows its effective null
        policy (`[?]`, `[? 'message']`, `[!]` or `[opt]`), a Branch marked `.q()`/`.opt()` shows what None
        does, and under each flow its steps are listed (Writes with their kind) with their effective policy.
        """
        lines = ["States:"]
        for st in self.states():
            flows, commands = self.flows_for(st)
            extra = f"  commands: {', '.join(_command_label(c) for c in commands)}" if commands else ""
            lines.append(f"  {st!r}{extra}")
        lines.append("Flows:")
        for f in self.flows:
            if not f.is_command:
                lines.append(f"  {f.name}: {f.begin_state!r} -> {_describe_end(f.end_state)}{self._flags(f)}")
                lines.extend(self._describe_steps(f))
        commands = [f for f in self.flows if f.is_command]
        if commands:
            lines.append("Commands:")
            for c in commands:
                lines.append(
                    f"  {_command_label(c)}: any {c.begin_state.__name__} -> {_describe_end(c.end_state)}{self._flags(c)}"
                )
                lines.extend(self._describe_steps(c))
        return "\n".join(lines)

    def _flags(self, flow: "MiniFlow") -> str:
        return f"  [{self.policy_for(flow, self.default_policy(flow)).label}]"

    def _describe_steps(self, flow: "MiniFlow") -> list[str]:
        """The steps inside `flow` with their effective policy. A single Write flow lists its kind."""
        policy = self.policy_for(flow, self.default_policy(flow))
        if isinstance(flow, Write):
            return [f"    Write '{flow.name}': {flow.kind!r}"]
        lines: list[str] = []
        if isinstance(flow, (Combine, LinearCombine)):
            for child in flow.flows:
                lines.extend(self._describe_child(child, policy, 2))
        return lines

    def _describe_child(self, step: "MiniFlow", inherited: NullPolicy, depth: int) -> list[str]:
        policy = self.policy_for(step, inherited)
        what = f"Write '{step.name}': {step.kind!r}" if isinstance(step, Write) else f"{type(step).__name__} '{step.name}'"
        lines = [f"{'  ' * depth}{what}  [{policy.label}]"]
        if isinstance(step, (Combine, LinearCombine)):
            for child in step.flows:
                lines.extend(self._describe_child(child, policy, depth + 1))
        return lines

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

        for f in self.flows:
            for step in _all_steps(f):
                if isinstance(step, Read) and step.null_policy == MUST:
                    problems.append(
                        f"Read '{step.name}' in flow '{f.name}' is marked .must(), but a Read yields no value "
                        "(it only refuses cancel); mark the enclosing step instead"
                    )
                if (
                    isinstance(step, Write)
                    and getattr(step.kind, "required", False)
                    and step.null_policy not in (None, MUST)
                ):
                    problems.append(
                        f"Write '{step.name}' in flow '{f.name}' has required=True (= .must()) but is marked "
                        f".{step.null_policy.kind}(); the mark wins"
                    )

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
        """Show one step (its effective null policy is `current_policy` meanwhile)."""
        with self.entering(flow):
            self._dispatch(flow)

    def _dispatch(self, flow: MiniFlow):
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


def _all_steps(flow: "MiniFlow") -> list["MiniFlow"]:
    steps = [flow]
    for child in getattr(flow, "flows", ()) if isinstance(flow, (Combine, LinearCombine)) else ():
        steps.extend(_all_steps(child))
    return steps


def _describe_end(end) -> str:
    if end is None or end is Return():
        return "Return (back to where it began)"
    if isinstance(end, Branch):
        text = "Branch[" + ", ".join(repr(c) for c in end.candidates) + "]"
        if end.null_policy is not None and end.null_policy.kind != "must":
            text += f" (None: {end.null_policy.label})"
        return text
    return repr(end)


def _slot_names(cls: type) -> list[str]:
    names: list[str] = []
    for klass in cls.__mro__:
        slots = klass.__dict__.get("__slots__", ())
        for name in [slots] if isinstance(slots, str) else slots:
            if name not in ("__dict__", "__weakref__") and name not in names:
                names.append(name)
    return names


def restore_in_place(target: Any, snapshot: Any) -> None:
    """Make `target` equal to `snapshot` (a deep copy of an earlier `target`) without replacing it:
    dicts and other mappings, lists, and objects with `__dict__` and/or `__slots__` (dataclasses, also
    `slots=True`). Values inside are the snapshot's copies, so only the top-level object keeps its identity.
    Other values (None, immutable ones) are left alone."""
    if isinstance(target, MutableMapping):
        target.clear()
        target.update(snapshot)
        return
    if isinstance(target, MutableSequence):
        target[:] = snapshot
        return
    for name in _slot_names(type(target)):
        if hasattr(snapshot, name):
            object.__setattr__(target, name, getattr(snapshot, name))
        elif hasattr(target, name):
            object.__delattr__(target, name)
    if hasattr(target, "__dict__") and hasattr(snapshot, "__dict__"):
        target.__dict__.clear()
        target.__dict__.update(snapshot.__dict__)


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
        command: Optional[str] = None,
    ):
        super().__init__(
            *args, begin_state=begin_state, end_state=end_state, message=message, name=name, command=command
        )
        self.kind = _as_kind(kind)
        self.validator = validate

    def own_policy(self) -> Optional[NullPolicy]:
        if self.null_policy is None and getattr(self.kind, "required", False):
            return MUST
        return self.null_policy

    def is_empty(self, raw: Any) -> bool:
        return self.kind.is_empty(raw)

    def accept(self, raw: Any, data: Any = None) -> Any:
        """Convert and validate a (non-empty) answer. Returns the value or raises InvalidInput(message).
        An empty answer is null; runners check `is_empty` first and apply the null policy. Passed here
        anyway, it is rejected with "a value is required"."""
        if self.is_empty(raw):
            raise InvalidInput(EMPTY_MESSAGE)
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

    def __init__(self, *args: Any, begin_state=_UNSET, end_state=_UNSET, choices=_UNSET, name=_UNSET, command=None):
        self.choices = self._setup(args, begin_state, end_state, name, "choices", choices, (), command)


class Combine(MiniFlow):
    """Child steps shown together (one screen in a GUI). `Combine([...], name=...)`. Children may be any step."""

    def __init__(self, *args: Any, begin_state=_UNSET, end_state=_UNSET, flows=_UNSET, name=_UNSET, command=None):
        self.flows = self._setup(args, begin_state, end_state, name, "flows", flows, (), command)


class LinearCombine(MiniFlow):
    """Child steps run one after another. `LinearCombine([...], name=...)`. Children may be any step."""

    def __init__(self, *args: Any, begin_state=_UNSET, end_state=_UNSET, flows=_UNSET, name=_UNSET, command=None):
        self.flows = self._setup(args, begin_state, end_state, name, "flows", flows, (), command)
