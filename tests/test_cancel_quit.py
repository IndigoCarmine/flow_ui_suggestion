import io
import os
import unittest
from unittest import mock

import base
import cui
import login_example
from scripted import ScriptedRunner


class Area(base.State):
    pass


def login(answers, **kw):
    runner = login_example.build_app(ScriptedRunner(login_example.LoginData(), answers, **kw))
    return runner, runner.run()


def kinds(runner, kind):
    return [entry for entry in runner.transcript if entry[0] == kind]


class CancelScriptedTest(unittest.TestCase):
    def test_cancel_command_returns_to_origin(self):
        runner, result = login(["alice", "secret", "edit-name", base.CANCEL, "profile", "quit"])
        self.assertIs(result, base.End())
        self.assertEqual(runner.data.display_name, "(not set)")
        self.assertEqual(kinds(runner, "cancel"), [("cancel", "edit-name", "EditName")])
        self.assertIn(("profile", "user: alice, name: (not set)"), [(n, t) for k, n, t in runner.transcript if k == "read"])

    def test_finished_steps_stay_and_end_is_not_evaluated(self):
        checked = []
        runner = ScriptedRunner({}, ["go", "a", base.CANCEL, "leave"])
        runner.add_miniflow(base.Read("in", name="enter").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(
            base.LinearCombine(
                [base.Write("one").data_update("one"), base.Write("two").data_update("two")], name="go"
            ).begin_end(Area, base.Branch(lambda: checked.append(1) or base.End(), [base.End()]))
        )
        runner.add_miniflow(base.Read("bye", name="leave").begin_end(Area, base.End()))
        self.assertIs(runner.run(), base.End())
        self.assertEqual(runner.data, {"one": "a"})  # "one" finished before the cancel; "two" never ran
        self.assertEqual(checked, [])
        self.assertEqual([t for k, _, t in runner.transcript if k == "select"], ["go", "leave"])

    def test_explicit_flow_is_not_cancellable_by_default(self):
        with self.assertRaises(ValueError) as ctx:
            login([base.CANCEL])
        self.assertIn("'login' cannot be cancelled", str(ctx.exception))

    def test_cancellable_override(self):
        runner = login_example.build_app(ScriptedRunner(login_example.LoginData(), ["alice", base.CANCEL, "alice", "secret", "quit"]))
        runner.flows[0].cancellable = True  # the login flow
        self.assertIs(runner.run(), base.End())
        self.assertEqual(kinds(runner, "cancel"), [("cancel", "login", "Password")])
        step = base.Read("x", cancellable=False).begin(Area)
        self.assertFalse(step.cancellable)
        self.assertTrue(base.Read("x").begin(Area).cancellable)
        self.assertFalse(base.Read("x").begin(base.Start()).cancellable)
        self.assertTrue(base.Write("x", cancellable=True).cancellable)
        self.assertTrue(base.Combine([], cancellable=True).cancellable)

    def test_non_cancellable_command(self):
        runner = ScriptedRunner({}, ["ask", base.CANCEL])
        runner.add_miniflow(base.Read("in").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(base.Write("q", name="ask", cancellable=False).begin(Area))
        runner.add_miniflow(base.Read("bye", name="leave").begin_end(Area, base.End()))
        with self.assertRaises(ValueError):
            runner.run()

    def test_cancel_at_selection_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:
            login(["alice", "secret", base.CANCEL])
        self.assertIn("no flow cannot be cancelled", str(ctx.exception))


class QuitTest(unittest.TestCase):
    def test_quit_answer(self):
        runner, result = login(["alice", "secret", base.QUIT])
        self.assertIs(result, base.QUIT)
        self.assertIs(runner.result, base.QUIT)
        self.assertEqual(runner.current_state, login_example.LoggedIn("home"))
        self.assertIs(base.Quit(), base.QUIT)

    def test_run_returns_end(self):
        runner, result = login(["alice", "secret", "quit"])
        self.assertIs(result, base.End())
        self.assertIs(runner.result, base.End())


class OnRejectTest(unittest.TestCase):
    def test_next_records_and_reasks(self):
        runner, result = login(["alice", "secret", "edit-name", "   ", "Bob", "quit"], on_reject="next")
        self.assertIs(result, base.End())
        self.assertEqual(runner.data.display_name, "Bob")
        self.assertEqual(kinds(runner, "rejected"), [("rejected", "EditName", "name must not be blank")])

    def test_choice_rejection(self):
        runner = ScriptedRunner({}, ["green", "red"], on_reject="next")
        runner.add_miniflow(base.Choice(["red"], name="c").data_update("c").begin_end(base.Start(), base.End()))
        runner.run()
        self.assertEqual(runner.data, {"c": "red"})
        self.assertEqual(len(kinds(runner, "rejected")), 1)
        strict = ScriptedRunner({}, ["green"])  # default on_reject="raise"
        strict.add_miniflow(base.Choice(["red"], name="c").begin_end(base.Start(), base.End()))
        with self.assertRaises(ValueError):
            strict.run()

    def test_bad_option(self):
        with self.assertRaises(ValueError):
            ScriptedRunner(on_reject="skip")


class GlobalCommandTest(unittest.TestCase):
    def build(self, answers):
        runner = ScriptedRunner({}, answers)
        runner.add_miniflow(base.Read("in", name="enter").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(base.Read("bye", name="leave").begin_end(Area("room"), base.End()))
        runner.add_miniflow(base.Read("help text", name="help").begin(base.State))
        runner.add_miniflow(base.Read("bye", name="quit", command="q").begin_end(base.State, base.End()))
        return runner

    def test_available_everywhere_but_end(self):
        runner = self.build(["help", "enter", "help", "q"])
        self.assertEqual(runner.validate(), [])
        for st in (base.Start(), Area("room"), base.State("x")):
            self.assertEqual([c.name for c in runner.flows_for(st)[1]], ["help", "quit"])
        self.assertEqual(runner.flows_for(base.End())[1], [])
        self.assertIs(runner.run(), base.End())
        self.assertEqual([t for k, _, t in runner.transcript if k == "select"], ["help", "enter", "help", "quit"])
        self.assertIn("help: any State -> Return", runner.describe())

    def test_quit_from_start(self):
        runner = self.build(["quit"])  # the flow name works as well as the alias
        self.assertIs(runner.run(), base.End())


class CommandAliasTest(unittest.TestCase):
    def test_default_and_alias(self):
        self.assertEqual(base.Read(name="profile").command, "profile")
        self.assertEqual(base.Read(name="profile", command="p").command, "p")
        with self.assertRaises(TypeError):
            base.Read(name="x", command="two words")

    def test_duplicate_alias_is_reported(self):
        runner = ScriptedRunner({})
        runner.add_miniflow(base.Read("in").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(base.Read(name="list", command="l").begin(Area))
        runner.add_miniflow(base.Read(name="leave", command="l").begin_end(Area, base.End()))
        self.assertEqual(runner.validate(), ["commands 'list' and 'leave' are both typed as 'l' at Area(room)"])

    def test_describe_shows_alias_kinds_and_cancellable(self):
        runner = login_example.build_app(ScriptedRunner(login_example.LoginData()))
        runner.flows[2]._command = "e"  # edit-name
        text = runner.describe()
        self.assertIn("LoggedIn(home)  commands: profile, e (edit-name), logout, quit", text)
        self.assertIn("e (edit-name): any LoggedIn -> Return (back to where it began)  [cancellable]", text)
        self.assertIn("login: Start() -> Branch[LoggedIn(home), Return()]\n", text)  # not cancellable: no mark
        self.assertIn("    Write 'Username': Text(required=True)", text)
        self.assertIn("    Write 'Password': Password(required=False)", text)
        self.assertIn("    Write 'EditName': Text(required=False)", text)


# --- CUI ------------------------------------------------------------------------------------------


def run_cui(build, data, lines, columns=80):
    out = io.StringIO()
    size = os.terminal_size((columns, 24))
    with (
        mock.patch("builtins.input", side_effect=lines) as fake,
        mock.patch("sys.stdout", out),
        mock.patch("sys.stdin", io.StringIO()),
        mock.patch("shutil.get_terminal_size", return_value=size),
    ):
        runner = build(cui.CuiRunner(data))
        result = runner.run()
    return runner, result, out.getvalue(), [c.args[0] for c in fake.call_args_list]


class CuiCancelQuitTest(unittest.TestCase):
    def test_colon_q_cancels_and_hint_is_shown_once(self):
        data = login_example.LoginData()
        _, result, out, _ = run_cui(
            login_example.build_app, data, ["alice", "secret", "edit-name", ":q", "edit-name", ":q", "quit", ""]
        )
        self.assertIs(result, base.End())
        self.assertEqual(data.display_name, "(not set)")
        self.assertEqual(out.count("(type :q or press Ctrl-D to cancel"), 1)
        self.assertEqual(out.count("(cancelled 'edit-name')"), 2)

    def test_eof_cancels_then_eof_at_prompt_quits(self):
        data = login_example.LoginData()
        runner, result, out, _ = run_cui(
            login_example.build_app, data, ["alice", "secret", "edit-name", EOFError(), EOFError()]
        )
        self.assertIs(result, base.QUIT)
        self.assertIn("(cancelled 'edit-name')", out)
        self.assertIn("End of input; exiting.", out)
        self.assertEqual(runner.current_state, login_example.LoggedIn("home"))

    def test_eof_at_home_prompt_quits(self):
        _, result, out, _ = run_cui(login_example.build_app, login_example.LoginData(), ["alice", "secret", EOFError()])
        self.assertIs(result, base.QUIT)
        self.assertTrue(out.rstrip().endswith("End of input; exiting."))

    def test_ctrl_c_in_non_cancellable_step(self):
        _, result, out, _ = run_cui(login_example.build_app, login_example.LoginData(), [KeyboardInterrupt()])
        self.assertIs(result, base.QUIT)
        self.assertIn("Interrupted; exiting.", out)

    def test_eof_in_non_cancellable_step_quits(self):
        _, result, _, _ = run_cui(login_example.build_app, login_example.LoginData(), ["alice", EOFError()])
        self.assertIs(result, base.QUIT)

    def test_colon_q_where_nothing_can_be_cancelled(self):
        data = login_example.LoginData()
        _, result, out, prompts = run_cui(
            login_example.build_app, data, [":q", "alice", "secret", ":q", "quit", ""]
        )
        self.assertIs(result, base.End())
        self.assertIn("  ! 'login' cannot be cancelled", out)
        self.assertIn("  ! nothing to cancel here", out)
        self.assertEqual(prompts.count("username: "), 2)
        self.assertEqual(data.username, "alice")

    def test_repeated_eof_does_not_loop(self):
        def build(runner):
            runner.add_miniflow(base.Write("x", cancellable=True).begin_end(base.Start(), base.End()))
            return runner

        _, result, out, _ = run_cui(build, {}, [EOFError()] * 3)
        self.assertIs(result, base.QUIT)
        self.assertEqual(out.count("(cancelled 'x')"), 1)


class CuiCommandTest(unittest.TestCase):
    def build(self, runner):
        runner.add_miniflow(base.Read("in", name="enter").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(base.Read("listing", name="list").begin(Area))
        runner.add_miniflow(base.Read("bye", name="leave", command="x").begin_end(Area, base.End()))
        return runner

    def test_prefix_alias_and_ambiguity(self):
        runner, result, out, _ = run_cui(self.build, {}, ["", "l", "li", "", "x", ""])
        self.assertIs(result, base.End())
        self.assertIn("Commands: list  x", out)
        self.assertIn("  ! 'l' could be: list, x", out)  # "l" is a prefix of "list" and of the name "leave"
        self.assertIn("listing", out)

    def test_name_and_unique_prefix(self):
        _, result, _, _ = run_cui(self.build, {}, ["", "leave", ""])
        self.assertIs(result, base.End())
        _, result, _, _ = run_cui(self.build, {}, ["", "lea", ""])
        self.assertIs(result, base.End())


class CuiLayoutTest(unittest.TestCase):
    def test_read_wraps_to_terminal_width(self):
        text = "word " * 30 + "\n\nsecond paragraph"

        def build(runner):
            runner.add_miniflow(base.Read(text, name="long").begin_end(base.Start(), base.End()))
            return runner

        _, _, out, _ = run_cui(build, {}, [""], columns=30)
        body = out.split("--- long ---\n", 1)[1].splitlines()
        self.assertTrue(all(len(line) <= 29 for line in body))
        self.assertGreater(len(body), 5)
        self.assertIn("", body)  # blank line kept
        self.assertIn("second paragraph", body)
        self.assertEqual(cui.wrap("a b", 80), "a b")

    def test_combine_numbers_fields(self):
        def build(runner):
            runner.add_miniflow(
                base.Combine(
                    [
                        base.Read("Order"),
                        base.Write("name").data_update("name"),
                        base.Choice(["tea", "coffee"], name="drink").data_update("drink"),
                        base.Combine([base.Write("sugar", kind=base.YesNo()).data_update("sugar")]),
                    ],
                    name="order",
                ).begin_end(base.Start(), base.End())
            )
            return runner

        data = {}
        _, _, out, prompts = run_cui(build, data, ["Ann", "0", "n"])
        self.assertEqual(data, {"name": "Ann", "drink": "tea", "sugar": False})
        self.assertIn("[1] name: ", prompts)
        self.assertIn("[2] drink", out)
        self.assertIn("[3] sugar [y/n]: ", prompts)


# --- GUI (offscreen) --------------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest

    import gui
except ImportError:  # pragma: no cover - PySide6 missing
    gui = None


def drive(runner, steps):
    """Run each step (returns True once it acted) from a timer while runner.run() waits for the user."""
    todo = list(steps)

    def tick():
        if todo and todo[0]():
            todo.pop(0)

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(10)
    try:
        return runner.run(), todo
    finally:
        timer.stop()


def visible_button(runner, text):
    for b in runner.central_widget.findChildren(QtWidgets.QPushButton):
        if b.text() == text and b.isVisible():
            return b
    return None


def click(runner, text):
    def step():
        b = visible_button(runner, text)
        if b is None:
            return False
        b.click()
        return True

    step.__name__ = f"click {text}"
    return step


@unittest.skipIf(gui is None, "PySide6 is not available")
class GuiTest(unittest.TestCase):
    def build(self, data):
        runner = gui.GuiRunner(data)
        runner.add_miniflow(base.Read("in", name="enter").begin_end(base.Start(), Area("room")))
        runner.add_miniflow(
            base.Combine(
                [
                    base.Write("first").data_update("first"),
                    base.Write("last").data_update("last"),
                    base.Write("age", kind=base.Number(min=0, max=150)).data_update("age"),
                ],
                name="form",
            ).begin(Area)
        )
        runner.add_miniflow(base.Read("bye", name="leave").begin_end(Area, base.End()))
        return runner

    def test_reflow_form_columns(self):
        form = gui.ReflowForm(threshold=700)
        for i in range(3):
            form.add_row(QtWidgets.QLabel(f"l{i}"), QtWidgets.QLineEdit())
        form.add_full(QtWidgets.QLabel("text"))
        form.reflow(400)
        self.assertEqual(form.columns, 1)
        form.reflow(900)
        self.assertEqual(form.columns, 2)
        self.assertEqual(form.grid.columnCount(), 4)
        single = gui.ReflowForm(threshold=700)
        single.add_row(QtWidgets.QLabel("only"), QtWidgets.QLineEdit())
        single.reflow(900)
        self.assertEqual(single.columns, 1)  # one row: nothing to put side by side

    def test_resize_cancel_enter_and_close(self):
        data = {}
        runner = self.build(data)
        seen = {}

        def resize_then_cancel():
            if runner.form is None or visible_button(runner, "Cancel") is None:
                return False
            runner.main_window.resize(1000, 400)
            QtWidgets.QApplication.processEvents()
            seen["wide"] = runner.form.columns
            runner.main_window.resize(400, 400)
            QtWidgets.QApplication.processEvents()
            seen["narrow"] = runner.form.columns
            runner.form.findChildren(QtWidgets.QLineEdit)[0].setText("Zed")
            visible_button(runner, "Cancel").click()
            return True

        def fill_and_enter():
            if runner.form is None or visible_button(runner, "form") is not None:
                return False
            seen["after_cancel"] = dict(data)
            edits = [e for e in runner.form.findChildren(QtWidgets.QLineEdit) if not isinstance(e.parent(), QtWidgets.QAbstractSpinBox)]
            edits[0].setText("Ann")
            edits[1].setText("Lee")
            spin = runner.form.findChildren(QtWidgets.QSpinBox)[0]
            spin.setValue(7)
            QTest.keyClick(spin, QtCore.Qt.Key.Key_Return)  # Enter in the last field = Next
            return True

        def close():
            if visible_button(runner, "leave") is None or "first" not in data:
                return False
            runner.main_window.close()
            return True

        result, left = drive(runner, [click(runner, "Next"), click(runner, "form"), resize_then_cancel,
                                      click(runner, "form"), fill_and_enter, close])
        self.assertEqual(left, [])
        self.assertEqual((seen["wide"], seen["narrow"]), (2, 1))
        self.assertEqual(seen["after_cancel"], {})
        self.assertEqual(data, {"first": "Ann", "last": "Lee", "age": 7})
        self.assertIs(result, base.QUIT)
        self.assertEqual(runner.current_state, Area("room"))

    def test_escape_key_cancels(self):
        data = {}
        runner = self.build(data)

        def escape():
            if visible_button(runner, "Cancel") is None:
                return False
            runner.main_window.activateWindow()
            QTest.keyClick(QtWidgets.QApplication.focusWidget() or runner.main_window, QtCore.Qt.Key.Key_Escape)
            return True

        result, left = drive(runner, [click(runner, "Next"), click(runner, "form"), escape, click(runner, "leave"),
                                      click(runner, "Next")])
        self.assertEqual(left, [])
        self.assertIs(result, base.End())
        self.assertEqual(data, {})

    def test_escape_hint_when_not_cancellable(self):
        runner = gui.GuiRunner({})
        runner.add_miniflow(base.Write("x", name="x").data_update("x").begin_end(base.Start(), base.End()))
        seen = {}

        def press_escape():
            if runner.form is None:
                return False
            seen["cancel"] = visible_button(runner, "Cancel")
            runner.press_escape()
            seen["status"] = runner.main_window.statusBar().currentMessage()
            runner.form.findChildren(QtWidgets.QLineEdit)[0].setText("v")
            visible_button(runner, "Next").click()
            return True

        result, _ = drive(runner, [press_escape])
        self.assertIs(result, base.End())
        self.assertIsNone(seen["cancel"])
        self.assertEqual(seen["status"], "'x' cannot be cancelled")


if __name__ == "__main__":
    unittest.main()
