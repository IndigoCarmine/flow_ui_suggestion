import abc
import inspect
from typing import Any, Callable, Optional, Union


class State:
    def __init__(self, name: str = None):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name if self.name else ''})"


class Start(State):
    pass


class End(State):
    pass


class Return:
    """End marker: go back to the state the flow started from. `Return()` is always the same object."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "Return()"


class Branch:
    """End of a flow that splits: `check(data)` returns one of the declared `candidates`."""

    def __init__(self, check: Callable[..., Any], candidates: list[Any]):
        self.check = check
        self.candidates = candidates

    def resolve(self, data: Any):
        result = _call_with_data(self.check, data)
        if not any(result is c for c in self.candidates):
            raise ValueError(
                f"Branch check returned {result!r}, which is not one of its candidates {self.candidates!r}"
            )
        return result


def _call_with_data(func: Callable, data: Any):
    if len(inspect.signature(func).parameters) == 0:
        return func()
    return func(data)


class MiniFlow:
    """Backend-independent step. It only holds data; the runner decides how to render it.

    begin_state: a State instance (explicit flow) or a State subclass (command flow,
    offered at every state that is an instance of it).
    end_state: a State, a Branch, Return(), or None (None means the same as Return()).
    """

    def __init__(
        self,
        begin_state: Union[State, type, None] = None,
        end_state: Union[State, Branch, Return, None] = None,
        message: str = "",
        name: str = "",
    ):
        self.name = name
        self.begin_state = begin_state
        self.end_state = end_state
        self.message = message
        self.is_complete = False

        # Data handling
        self._data_update_func: Optional[Union[Callable, str]] = None
        self._context_build_func: Optional[Union[Callable, str]] = None

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

        if isinstance(self._context_build_func, str):
            if data is not None:
                try:
                    d_dict = data.__dict__ if hasattr(data, "__dict__") else data
                    return self._context_build_func.format(**d_dict)
                except (KeyError, AttributeError):
                    return getattr(data, self._context_build_func, self.message)
            return self.message

        return _call_with_data(self._context_build_func, data)

    def apply_update(self, data: Any, value: Any):
        if not self._data_update_func:
            return

        if isinstance(self._data_update_func, str):
            if data is not None:
                setattr(data, self._data_update_func, value)
            return

        sig = inspect.signature(self._data_update_func)
        if len(sig.parameters) == 1:
            self._data_update_func(value)
        else:
            self._data_update_func(data, value)

    def complete(self):
        self.is_complete = True


class ApplicationRunnerBase(abc.ABC):
    def __init__(self, data: Any = None):
        self.flows: list[MiniFlow] = []
        self.start_state: Optional[Start] = None
        self.current_state: Optional[State] = None
        self.data = data

    def add_miniflow(self, flow: MiniFlow):
        self.flows.append(flow)
        if isinstance(flow.begin_state, Start):
            self.start_state = flow.begin_state

    def run(self):
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
            self.render(selected_flow)
            self.current_state = self.resolve_end(selected_flow.end_state, origin)

    def flows_for(self, state: State) -> tuple[list[MiniFlow], list[MiniFlow]]:
        """Explicit flows that begin at this state, and command flows whose type matches it."""
        flows = [f for f in self.flows if not f.is_command and f.begin_state is state]
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

    def render(self, flow: MiniFlow):
        flow.is_complete = False
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
        flow.complete()

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


class Read(MiniFlow):
    """The user reads: the app displays information."""


class Write(MiniFlow):
    """The user writes: the app takes input."""


class Choice(MiniFlow):
    def __init__(self, begin_state=None, end_state=None, choices=(), name=""):
        super().__init__(begin_state, end_state, "", name)
        self.choices = choices


class Combine(MiniFlow):
    def __init__(self, begin_state=None, end_state=None, flows=(), name=""):
        super().__init__(begin_state, end_state, "", name)
        self.flows = flows


class LinearCombine(MiniFlow):
    def __init__(self, begin_state=None, end_state=None, flows=(), name=""):
        super().__init__(begin_state, end_state, "", name)
        self.flows = flows
