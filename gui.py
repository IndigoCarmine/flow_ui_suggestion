import sys
from typing import Any, Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

import base

_INT_LIMIT = 2_147_483_647

TWO_COLUMN_WIDTH = 720
"""A screen at least this wide shows its label/field rows in two columns."""


class _Window(QtWidgets.QMainWindow):
    """Main window that remembers it was closed, so the runner can end `run()` (= the user quit)."""

    def __init__(self):
        super().__init__()
        self.closed = False

    def closeEvent(self, event):
        self.closed = True
        super().closeEvent(event)


class ReflowForm(QtWidgets.QWidget):
    """Label/field rows that reflow with the width: one column of rows when narrow, two side by side when
    the form is at least `threshold` wide (and has more than one row). Full-width items (text) span all
    columns. The app never specifies any of this."""

    def __init__(self, threshold: int = TWO_COLUMN_WIDTH):
        super().__init__()
        self.threshold = threshold
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.items: list[tuple[Optional[QtWidgets.QWidget], QtWidgets.QWidget]] = []
        self.columns = 0

    def add_full(self, widget: QtWidgets.QWidget):
        self.items.append((None, widget))

    def add_row(self, label: QtWidgets.QWidget, field: QtWidgets.QWidget):
        self.items.append((label, field))

    def columns_for(self, width: int) -> int:
        rows = sum(1 for label, _ in self.items if label is not None)
        return 2 if width >= self.threshold and rows > 1 else 1

    def reflow(self, width: int):
        columns = self.columns_for(width)
        if columns == self.columns:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)  # the widgets stay children of this form
        row, col = 0, 0
        for label, field in self.items:
            if label is None:
                if col:
                    row, col = row + 1, 0
                self.grid.addWidget(field, row, 0, 1, 2 * columns)
                row += 1
                continue
            self.grid.addWidget(label, row, 2 * col, QtCore.Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(field, row, 2 * col + 1)
            col += 1
            if col == columns:
                row, col = row + 1, 0
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c % 2 and c < 2 * columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow(event.size().width())


class _EnterKeys(QtCore.QObject):
    """Return/Enter in a field moves to the next field; in the last one (or on the button) it presses Next."""

    def __init__(self, parent: QtCore.QObject, on_last: Callable[[], None]):
        super().__init__(parent)
        self.order: list[QtWidgets.QWidget] = []
        self.on_last = on_last

    def watch(self, widget: QtWidgets.QWidget):
        self.order.append(widget)
        for target in [widget, *widget.findChildren(QtWidgets.QLineEdit)]:
            target.installEventFilter(self)

    def _owner(self, obj) -> Optional[QtWidgets.QWidget]:
        for widget in self.order:
            if obj is widget or widget.isAncestorOf(obj):
                return widget
        return None

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress and event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
        ):
            owner = self._owner(obj)
            if owner is not None:
                idx = self.order.index(owner)
                if idx + 1 < len(self.order) and not isinstance(self.order[idx + 1], QtWidgets.QPushButton):
                    self.order[idx + 1].setFocus()
                else:
                    self.on_last()
                return True
        return False


class GuiRunner(base.ApplicationRunnerBase):
    """Each step is one screen with a Next button. A Combine puts all its children (any step type,
    nested Combine/LinearCombine flattened) on one screen, as label/field rows that reflow into two
    columns when the window is wide. Input is converted and validated when Next is pressed (or Enter in the
    last field); if anything is rejected, the messages are shown under the fields and the screen stays.
    In a cancellable flow a Cancel button (and Esc) cancels; elsewhere Esc only shows a hint in the status
    bar. Closing the window ends `run()` (it returns base.QUIT)."""

    def __init__(self, data=None):
        super().__init__(data)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.main_window = _Window()
        self.main_window.setWindowTitle("Flow UI")
        self.central_widget = QtWidgets.QWidget()
        self.main_window.setCentralWidget(self.central_widget)
        self.layout = QtWidgets.QVBoxLayout(self.central_widget)
        self.form: Optional[ReflowForm] = None
        self._escape: Optional[Callable[[], None]] = None
        escape = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape), self.main_window)
        escape.activated.connect(self.press_escape)
        self.main_window.resize(400, 300)
        self.main_window.show()

    def press_escape(self):
        """Esc: cancel the running flow if it may be cancelled, otherwise explain why nothing happens."""
        if self._escape is not None:
            self._escape()
        elif self.active_flow is not None:
            self.main_window.statusBar().showMessage(f"'{self.active_flow.name}' cannot be cancelled", 4000)

    def show_read(self, flow):
        self._show_screen(flow)

    def show_write(self, flow):
        self._show_screen(flow)

    def show_choice(self, flow):
        self._show_screen(flow)

    def show_combine(self, flow):
        self._show_screen(flow)

    # --- building one screen ---------------------------------------------------------------------

    def _add_step(self, flow, form: ReflowForm, fields: list, parent_name: Optional[str] = None):
        """Add the widgets of `flow` to the form. Every input step appends (flow, read_value, widget)."""
        if isinstance(flow, base.Read):
            label = QtWidgets.QLabel(str(flow.resolve_content(self.data)))
            label.setWordWrap(True)
            form.add_full(label)
        elif isinstance(flow, base.Write):
            prompt = str(flow.resolve_content(self.data))
            widget, read_value = self._input_widget(flow)
            self._add_row(form, prompt, widget, flow, read_value, fields)
        elif isinstance(flow, base.Choice):
            choices = list(flow.resolve_content(self.data) or flow.choices)
            combo = QtWidgets.QComboBox()
            combo.addItems([str(c) for c in choices])

            def read_choice(choices=choices, combo=combo):
                idx = combo.currentIndex()
                if not 0 <= idx < len(choices):
                    raise base.InvalidInput("nothing to choose")
                return choices[idx]

            label = "" if flow.name == type(flow).__name__ else flow.name
            self._add_row(form, label, combo, flow, read_choice, fields)
        elif isinstance(flow, (base.Combine, base.LinearCombine)):
            for child in flow.flows:
                self._add_step(child, form, fields, flow.name)
        else:
            where = f" inside '{parent_name}'" if parent_name else ""
            raise TypeError(f"GuiRunner cannot show {type(flow).__name__} '{flow.name}'{where}")

    def _add_row(self, form: ReflowForm, prompt: str, widget, flow, read_value, fields: list):
        label = QtWidgets.QLabel(prompt)
        label.setWordWrap(True)
        label.setBuddy(widget)
        cell = QtWidgets.QWidget()
        cell_layout = QtWidgets.QVBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.addWidget(widget)
        error = self._error_label()
        cell_layout.addWidget(error)
        form.add_row(label, cell)
        fields.append((flow, read_value, error, widget))

    def _input_widget(self, flow: base.Write) -> tuple[QtWidgets.QWidget, Callable[[], Any]]:
        """A widget that fits flow.kind and a function giving the accepted value."""
        kind = flow.kind
        if isinstance(kind, base.YesNo):
            box = QtWidgets.QCheckBox()
            return box, lambda: flow.accept(box.isChecked(), self.data)

        if isinstance(kind, base.Number):
            spin = QtWidgets.QSpinBox() if kind.decimals == 0 else QtWidgets.QDoubleSpinBox()
            if isinstance(spin, QtWidgets.QDoubleSpinBox):
                spin.setDecimals(kind.decimals)
            low = -_INT_LIMIT if kind.min is None else kind.min
            high = _INT_LIMIT if kind.max is None else kind.max
            spin.setRange(int(low) if kind.decimals == 0 else low, int(high) if kind.decimals == 0 else high)
            spin.setValue(min(max(0, spin.minimum()), spin.maximum()))

            def read_number():
                spin.interpretText()
                return flow.accept(spin.value(), self.data)

            return spin, read_number

        line_edit = QtWidgets.QLineEdit()
        if isinstance(kind, base.Password):
            line_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        return line_edit, lambda: flow.accept(line_edit.text(), self.data)

    def _error_label(self) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setObjectName("error")
        label.setStyleSheet("color: #c62828;")
        label.hide()
        return label

    def _clear(self):
        self.form = None
        self._escape = None
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _show_screen(self, flow):
        self._clear()
        form = ReflowForm()
        fields: list = []
        self._add_step(flow, form, fields)
        outcome: list[Optional[str]] = [None]

        def on_next():
            values = []
            for step, read_value, error_label, _ in fields:
                try:
                    values.append((step, read_value()))
                    error_label.hide()
                except base.InvalidInput as e:
                    error_label.setText(str(e))
                    error_label.show()
            if len(values) == len(fields):
                for step, value in values:
                    step.apply_update(self.data, value)
                outcome[0] = "next"

        def on_cancel():
            outcome[0] = "cancel"

        self.layout.addWidget(form)
        self.layout.addStretch(1)
        button_row = QtWidgets.QWidget()
        buttons = QtWidgets.QHBoxLayout(button_row)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        if self.can_cancel:
            cancel_button = QtWidgets.QPushButton("Cancel")
            cancel_button.setToolTip("Leave this without finishing it (Esc)")
            cancel_button.clicked.connect(on_cancel)
            buttons.addWidget(cancel_button)
            self._escape = on_cancel
        next_button = QtWidgets.QPushButton("Next")
        next_button.clicked.connect(on_next)
        buttons.addWidget(next_button)
        self.layout.addWidget(button_row)

        enter = _EnterKeys(form, on_next)
        for _, _, _, widget in fields:
            enter.watch(widget)
        enter.watch(next_button)
        form.reflow(max(self.central_widget.width(), 1))
        self.form = form
        (fields[0][3] if fields else next_button).setFocus()

        self._wait(lambda: outcome[0] is not None)
        if outcome[0] == "cancel":
            raise base.Cancelled()

    def _wait(self, finished: Callable[[], bool]):
        """Run the Qt event loop until `finished()` is true. Progress lives here, not on the step.
        Raises base.UserQuit if the window gets closed meanwhile."""
        self.central_widget.update()
        self.app.processEvents()
        while not finished():
            if self.main_window.closed:
                raise base.UserQuit()
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
                if c.command != c.name:
                    btn.setToolTip(c.command)
                btn.clicked.connect(lambda _, c_val=c: set_selected(c_val))
                row_layout.addWidget(btn)
            self.layout.addWidget(row)
        self.layout.addStretch(1)

        self._wait(lambda: selected[0] is not None)
        return selected[0]

    def run(self):
        self.main_window.closed = False
        self.main_window.show()
        try:
            return super().run()
        finally:
            self.main_window.close()
