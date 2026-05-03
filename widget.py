import abc
import sys

import PySide6
from PySide6 import QtCore, QtWidgets


class State(abc.ABC):
    def __init__(self):
        pass


class Start(State):
    def __init__(self):
        super().__init__()


class End(State):
    def __init__(self):
        super().__init__()


class MiniFlow(abc.ABC):
    def __init__(self, name, begin_state, end_state):
        self.name = name
        self.begin_state = begin_state
        self.end_state = end_state
        self.is_complete = False

    @abc.abstractmethod
    def generateUI(self) -> list[QtWidgets.QWidget]:
        pass

    def complete(self):
        self.is_complete = True

    def generateWaitingUI(self) -> list[QtWidgets.QWidget]:
        button = QtWidgets.QPushButton("Next")
        button.clicked.connect(self.complete)
        ui = self.generateUI()
        ui.append(button)
        return ui


class ApplicationRunner:
    def __init__(self):
        self.app = QtWidgets.QApplication()
        self.main_window = QtWidgets.QMainWindow()
        self.main_window.show()
        self.states = [Start(), End()]
        self.flows = []
        self.now = self.states[0]

    def add_state(self, state):
        self.states.append(state)

    def add_miniflow(self, flow, begin_state, end_state):
        self.flows.append(flow)

    def state_update(self, state):
        self.now = state
        if type(self.now) is End:
            self.app.quit()

    def show_flow_selection(self, available_flows) -> MiniFlow:
        names = [flow.name for flow in available_flows]
        layout = QtWidgets.QVBoxLayout()
        for name in names:
            button = QtWidgets.QPushButton(name)

            layout.addWidget(button)
        self.main_window.setLayout(layout)

    def single_step(self):
        state = self.now
        available_flows = [flow for flow in self.flows if flow.begin_state == state]
        if not available_flows:
            return
        selected_flow = available_flows[0]
        if len(available_flows) != 1:
            selected_flow = self.show_flow_selection(available_flows)
        ui = selected_flow.generateWaitingUI()
        layout = QtWidgets.QVBoxLayout()
        for widget in ui:
            layout.addWidget(widget)
        self.main_window.setLayout(layout)
        while not selected_flow.is_complete:
            self.app.processEvents()

        self.state_update(selected_flow.end_state)

    def run(self):
        while not isinstance(self.now, End):
            self.single_step()


class Read(MiniFlow):
    def __init__(self, begin_state, end_state, message, name):
        super().__init__(begin_state, end_state, name)
        self.message = message

    def generateUI(self) -> list[QtWidgets.QWidget]:
        return [QtWidgets.QLabel(self.message)]


class Write(MiniFlow):
    def __init__(self, begin_state, end_state, message: str, name):
        super().__init__(begin_state, end_state, name)
        self.message = message

    def set_message(self, message: str):
        self.message = message
        self.end_state.emit()

    def generateUI(self) -> list[QtWidgets.QWidget]:
        inputbox = QtWidgets.QLineEdit()
        # sync inputbox text with self.message if update, emit signal on change
        inputbox.setText(self.message)
        inputbox.textChanged.connect(self.set_message)

        return [inputbox]


class Choice(MiniFlow):
    def __init__(self, begin_state, end_state, choices: list[str], name):
        super().__init__(begin_state, end_state, name)
        self.choices = choices

    def set_choices(self, choices: list[str]):
        self.choices = choices
        self.end_state.emit()

    def generateUI(self) -> list[QtWidgets.QWidget]:
        combo = QtWidgets.QComboBox()
        combo.addItems(self.choices)
        # sync selected index with self.end_state if update, emit signal on change
        combo.currentIndexChanged.connect(self.end_state.emit)
        return [combo]


class Combine(MiniFlow):
    def __init__(self, begin_state, end_state, flows: list[MiniFlow], name):
        super().__init__(begin_state, end_state, name)
        self.flows = flows

    def generateUI(self) -> list[QtWidgets.QWidget]:
        ui = []
        for flow in self.flows:
            ui.extend(flow.generateUI())
        return ui


if __name__ == "__main__":
    flow = Read(Start(), End(), "Hello", "Initial")
    app = ApplicationRunner()
    app.add_miniflow(flow, Start(), End())
    app.run()
