import sys

from PySide6 import QtCore, QtWidgets

import base


class GuiRunner(base.ApplicationRunnerBase):
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

    def show_read(self, flow):
        self.display_widgets(self._read_widgets(flow), flow)

    def show_write(self, flow):
        self.display_widgets(self._write_widgets(flow), flow)

    def show_choice(self, flow):
        choices = flow.resolve_content(self.data) or flow.choices
        combo = QtWidgets.QComboBox()
        combo.addItems(choices)
        combo.currentIndexChanged.connect(
            lambda idx: flow.apply_update(self.data, choices[idx])
        )
        self.display_widgets([combo], flow)

    def show_combine(self, flow):
        widgets = []
        for child in flow.flows:
            if isinstance(child, base.Read):
                widgets += self._read_widgets(child)
            elif isinstance(child, base.Write):
                widgets += self._write_widgets(child)
        self.display_widgets(widgets, flow)

    def _read_widgets(self, flow: base.Read) -> list[QtWidgets.QWidget]:
        content = flow.resolve_content(self.data)
        return [QtWidgets.QLabel(str(content))]

    def _write_widgets(self, flow: base.Write) -> list[QtWidgets.QWidget]:
        prompt = flow.resolve_content(self.data)
        line_edit = QtWidgets.QLineEdit()
        line_edit.textChanged.connect(lambda text: flow.apply_update(self.data, text))
        return [QtWidgets.QLabel(str(prompt)), line_edit]

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
