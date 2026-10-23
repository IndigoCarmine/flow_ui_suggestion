import sys
from typing import Any, Callable, Optional

from PySide6 import QtCore, QtWidgets

import base

_INT_LIMIT = 2_147_483_647


class GuiRunner(base.ApplicationRunnerBase):
    """Each step is one screen with a Next button. A Combine puts all its children (any step type,
    nested Combine/LinearCombine flattened) on one screen. Input is converted and validated when Next is
    pressed; if anything is rejected, the messages are shown under the fields and the screen stays."""

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
        self._show_screen(flow)

    def show_write(self, flow):
        self._show_screen(flow)

    def show_choice(self, flow):
        self._show_screen(flow)

    def show_combine(self, flow):
        self._show_screen(flow)

    # --- building one screen ---------------------------------------------------------------------

    def _add_step(self, flow, fields: list, parent_name: Optional[str] = None):
        """Add the widgets of `flow` to the layout. Every input step appends (flow, read_value, error_label)."""
        if isinstance(flow, base.Read):
            self.layout.addWidget(QtWidgets.QLabel(str(flow.resolve_content(self.data))))
        elif isinstance(flow, base.Write):
            read_value = self._add_input(flow)
            fields.append((flow, read_value, self._error_label()))
        elif isinstance(flow, base.Choice):
            choices = list(flow.resolve_content(self.data) or flow.choices)
            combo = QtWidgets.QComboBox()
            combo.addItems([str(c) for c in choices])
            self.layout.addWidget(combo)

            def read_choice(choices=choices, combo=combo):
                idx = combo.currentIndex()
                if not 0 <= idx < len(choices):
                    raise base.InvalidInput("nothing to choose")
                return choices[idx]

            fields.append((flow, read_choice, self._error_label()))
        elif isinstance(flow, (base.Combine, base.LinearCombine)):
            for child in flow.flows:
                self._add_step(child, fields, flow.name)
        else:
            where = f" inside '{parent_name}'" if parent_name else ""
            raise TypeError(f"GuiRunner cannot show {type(flow).__name__} '{flow.name}'{where}")

    def _add_input(self, flow: base.Write) -> Callable[[], Any]:
        """Add a widget that fits flow.kind and return a function giving the accepted value."""
        prompt = str(flow.resolve_content(self.data))
        kind = flow.kind
        if isinstance(kind, base.YesNo):
            box = QtWidgets.QCheckBox(prompt)
            self.layout.addWidget(box)
            return lambda: flow.accept(box.isChecked(), self.data)

        self.layout.addWidget(QtWidgets.QLabel(prompt))
        if isinstance(kind, base.Number):
            spin = QtWidgets.QSpinBox() if kind.decimals == 0 else QtWidgets.QDoubleSpinBox()
            if isinstance(spin, QtWidgets.QDoubleSpinBox):
                spin.setDecimals(kind.decimals)
            low = -_INT_LIMIT if kind.min is None else kind.min
            high = _INT_LIMIT if kind.max is None else kind.max
            spin.setRange(int(low) if kind.decimals == 0 else low, int(high) if kind.decimals == 0 else high)
            spin.setValue(min(max(0, spin.minimum()), spin.maximum()))
            self.layout.addWidget(spin)
            return lambda: flow.accept(spin.value(), self.data)

        line_edit = QtWidgets.QLineEdit()
        if isinstance(kind, base.Password):
            line_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.layout.addWidget(line_edit)
        return lambda: flow.accept(line_edit.text(), self.data)

    def _error_label(self) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setObjectName("error")
        label.setStyleSheet("color: #c62828;")
        label.hide()
        self.layout.addWidget(label)
        return label

    def _clear(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _show_screen(self, flow):
        self._clear()
        fields: list = []
        self._add_step(flow, fields)
        done = [False]

        def on_next():
            values = []
            for step, read_value, error_label in fields:
                try:
                    values.append((step, read_value()))
                    error_label.hide()
                except base.InvalidInput as e:
                    error_label.setText(str(e))
                    error_label.show()
            if len(values) == len(fields):
                for step, value in values:
                    step.apply_update(self.data, value)
                done[0] = True

        next_button = QtWidgets.QPushButton("Next")
        next_button.clicked.connect(on_next)
        self.layout.addWidget(next_button)
        self._wait(lambda: done[0])

    def _wait(self, finished: Callable[[], bool]):
        """Run the Qt event loop until `finished()` is true. Progress lives here, not on the step."""
        self.central_widget.update()
        self.app.processEvents()
        while not finished():
            self.app.processEvents()
            QtCore.QThread.msleep(10)

    def select_flow(self, flows, commands):
        selected = [None]

        def set_selected(f):
            selected[0] = f

        self._clear()
        self.layout.addWidget(QtWidgets.QLabel(str(self.current_state)))
        for f in flows:
            btn = QtWidgets.QPushButton(f.name)
            btn.clicked.connect(lambda _, f_val=f: set_selected(f_val))
            self.layout.addWidget(btn)

        if commands:
            # Commands go in their own row so they read as "always available here".
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.addWidget(QtWidgets.QLabel("Commands:"))
            for c in commands:
                btn = QtWidgets.QPushButton(c.name)
                btn.clicked.connect(lambda _, c_val=c: set_selected(c_val))
                row_layout.addWidget(btn)
            self.layout.addWidget(row)

        self._wait(lambda: selected[0] is not None)
        return selected[0]

    def run(self):
        super().run()
        self.main_window.close()
