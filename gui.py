import sys

from PySide6 import QtCore, QtWidgets

import base


class Read(base.Read):
    def run_interaction(self, runner):
        prompt = self.resolve_content(runner.data)
        label = QtWidgets.QLabel(str(prompt))
        line_edit = QtWidgets.QLineEdit()
        line_edit.textChanged.connect(lambda text: self.apply_update(runner.data, text))
        runner.display_widgets([label, line_edit], self)


class Write(base.Write):
    def run_interaction(self, runner):
        content = self.resolve_content(runner.data)
        label = QtWidgets.QLabel(str(content))
        runner.display_widgets([label], self)


class Choice(base.Choice):
    def run_interaction(self, runner):
        choices = self.resolve_content(runner.data) or self.choices
        combo = QtWidgets.QComboBox()
        combo.addItems(choices)
        combo.currentIndexChanged.connect(
            lambda idx: self.apply_update(runner.data, choices[idx])
        )
        runner.display_widgets([combo], self)


class Combine(base.Combine):
    def run_interaction(self, runner):
        widgets = []
        for flow in self.flows:
            if isinstance(flow, base.Read):
                p = flow.resolve_content(runner.data)
                widgets.append(QtWidgets.QLabel(str(p)))
                le = QtWidgets.QLineEdit()
                le.textChanged.connect(lambda t, f=flow: f.apply_update(runner.data, t))
                widgets.append(le)
            elif isinstance(flow, base.Write):
                c = flow.resolve_content(runner.data)
                widgets.append(QtWidgets.QLabel(str(c)))
        runner.display_widgets(widgets, self)


class LinearCombine(base.LinearCombine):
    def run_interaction(self, runner):
        for flow in self.flows:
            flow.is_complete = False
            # Ensure internal flows use the backend implementation logic
            # By wrapping them in the appropriate backend class if needed,
            # but since we create them from the backend module in main.py, it's fine.
            flow.run_interaction(runner)
        self.complete()


class Start(base.Start):
    pass


class End(base.End):
    pass


class ApplicationRunner(base.ApplicationRunnerBase):
    def __init__(self, data=None):
        super().__init__(data)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.main_window = QtWidgets.QMainWindow()
        self.main_window.setWindowTitle("Flow UI")
        self.central_widget = QtWidgets.QWidget()
        self.main_window.setCentralWidget(self.central_widget)
        self.layout = QtWidgets.QVBoxLayout(self.central_widget)
        self.main_window.resize(400, 300)
        self.main_window.show()

    def display_widgets(self, widgets, flow):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for w in widgets:
            self.layout.addWidget(w)

        next_button = QtWidgets.QPushButton("Next")
        next_button.clicked.connect(flow.complete)
        self.layout.addWidget(next_button)

        self.central_widget.update()
        self.app.processEvents()

        while not flow.is_complete:
            self.app.processEvents()
            QtCore.QThread.msleep(10)

    def select_flow(self, flows):
        selected = [None]

        def set_selected(f):
            selected[0] = f

        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for f in flows:
            btn = QtWidgets.QPushButton(f.name)
            btn.clicked.connect(lambda _, f_val=f: set_selected(f_val))
            self.layout.addWidget(btn)

        self.central_widget.update()
        self.app.processEvents()

        while selected[0] is None:
            self.app.processEvents()
            QtCore.QThread.msleep(10)

        return selected[0]

    def run(self):
        super().run()
        self.main_window.close()
