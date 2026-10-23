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


class MiniFlow:
    """Backend-independent step. It only holds data; the runner decides how to render it."""

    def __init__(self, begin_state: State, end_state: State, message: str, name: str):
        self.name = name
        self.begin_state = begin_state
        self.end_state = end_state
        self.message = message
        self.is_complete = False

        # Data handling
        self._data_update_func: Optional[Union[Callable, str]] = None
        self._context_build_func: Optional[Union[Callable, str]] = None

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

        sig = inspect.signature(self._context_build_func)
        if len(sig.parameters) == 0:
            return self._context_build_func()
        return self._context_build_func(data)

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
            available_flows = [
                f for f in self.flows if f.begin_state == self.current_state
            ]

            if not available_flows:
                print(f"DEBUG: No transitions from {self.current_state}")
                break

            selected_flow = available_flows[0]
            if len(available_flows) > 1:
                selected_flow = self.select_flow(available_flows)

            self.render(selected_flow)
            self.current_state = selected_flow.end_state

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
    def select_flow(self, flows: list[MiniFlow]) -> MiniFlow:
        pass


class Read(MiniFlow):
    """The user reads: the app displays information."""


class Write(MiniFlow):
    """The user writes: the app takes input."""


class Choice(MiniFlow):
    def __init__(self, begin_state, end_state, choices, name):
        super().__init__(begin_state, end_state, "", name)
        self.choices = choices


class Combine(MiniFlow):
    def __init__(self, begin_state, end_state, flows, name):
        super().__init__(begin_state, end_state, "", name)
        self.flows = flows


class LinearCombine(MiniFlow):
    def __init__(self, begin_state, end_state, flows, name):
        super().__init__(begin_state, end_state, "", name)
        self.flows = flows
