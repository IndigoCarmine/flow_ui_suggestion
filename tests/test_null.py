"""Null handling: `.q(message)` (`?`), `.must()` (`!`) and `.opt()`, inheritance, defaults, Branch None,
notices in every runtime, and the data snapshot that a `?` exit restores."""

import os
import unittest
from dataclasses import dataclass, field

import base
import login_example
import main
from scripted import ScriptedRunner
from tests.test_cancel_quit import click, drive, gui, run_cui, visible_button


class Area(base.State):
    pass


def kinds(runner, kind):
    return [entry for entry in runner.transcript if entry[0] == kind]


def room_app(runner, *commands, enter=None):
    """Start -(enter)-> Area("room"); the given flows as commands of Area; "leave" goes to End."""
    runner.add_miniflow(enter or base.Read("in", name="enter").begin_end(base.Start(), Area("room")))
    for c in commands:
        runner.add_miniflow(c.begin(Area))
    runner.add_miniflow(base.Read("bye", name="leave").begin_end(Area, base.End()))
    return runner


@dataclass(slots=True)
class Slotted:
    name: str = "Ann"
    tags: list = field(default_factory=lambda: ["a"])


class Plain:
    def __init__(self):
        self.name = "Ben"


class PolicyMarksTest(unittest.TestCase):
    def test_methods_return_self_and_set_policy(self):
        step = base.Write("x")
        self.assertIs(step.q("msg"), step)
        self.assertEqual(step.null_policy, base.NullPolicy("q", "msg"))
        self.assertIs(step.must().null_policy, base.MUST)
        self.assertIs(step.opt().null_policy, base.OPT)
        branch = base.Branch(lambda: None, [base.End()])
        self.assertIs(branch.q(), branch)
        for cls in (base.Read, base.Choice, base.Combine, base.LinearCombine):
            self.assertIs(cls().opt().null_policy, base.OPT)
        self.assertEqual([base.Q.label, base.NullPolicy("q", "m").label, base.MUST.label, base.OPT.label],
                         ["?", "? 'm'", "!", "opt"])
        with self.assertRaises(ValueError):
            base.NullPolicy("maybe")
        with self.assertRaises(ValueError):
            base.NullPolicy("opt", "message")
        with self.assertRaises(TypeError):
            base.Read("x", cancellable=True)  # replaced by .q() / .must()

    def test_required_is_must(self):
        self.assertIs(base.Write("x", kind=base.Text(required=True)).own_policy(), base.MUST)
        self.assertIsNone(base.Write("x").own_policy())
        self.assertIs(base.Write("x", kind=base.Text(required=True)).opt().own_policy(), base.OPT)

    def test_effective_policy_inheritance_and_defaults(self):
        runner = ScriptedRunner({})
        inner = base.Write("inner")
        marked = base.Write("marked").must()
        nested = base.Combine([inner])
        flow = base.LinearCombine([nested, marked]).opt()
        self.assertIs(runner.policy_for(flow), base.OPT)
        self.assertIs(runner.policy_for(nested, base.OPT), base.OPT)
        self.assertIs(runner.policy_for(inner, runner.policy_for(nested, base.OPT)), base.OPT)
        self.assertIs(runner.policy_for(marked, base.OPT), base.MUST)
        self.assertIs(runner.policy_for(base.Write("x").begin(Area)), base.Q)  # command default
        self.assertIs(runner.policy_for(base.Write("x").begin(base.Start())), base.MUST)  # explicit default


class ScriptedPolicyTest(unittest.TestCase):
    def test_q_exits_restores_and_shows_notice(self):
        data = {"kept": 1}
        flow = base.LinearCombine([base.Write("a").data_update("a"), base.Write("b").data_update("b")], name="ab").q("gave up")
        runner = room_app(ScriptedRunner(data, ["ab", "first", "", "leave"]), flow)
        self.assertIs(runner.run(), base.End())
        self.assertEqual(data, {"kept": 1})
        self.assertEqual(kinds(runner, "cancel"), [("cancel", "ab", "b")])
        self.assertEqual(kinds(runner, "notice"), [("notice", "ab", "gave up")])

    def test_opt_stores_none_and_continues(self):
        data = {}
        flow = base.LinearCombine(
            [base.Write("a").data_update("a").opt(), base.Write("b").data_update("b").opt(), base.Write("c").data_update("c")],
            name="abc",
        )
        runner = room_app(ScriptedRunner(data, ["abc", "", base.CANCEL, "x", "leave"]), flow)
        self.assertIs(runner.run(), base.End())
        self.assertEqual(data, {"a": None, "b": None, "c": "x"})
        self.assertEqual(kinds(runner, "write"), [("write", "a", None), ("write", "b", None), ("write", "c", "x")])

    def test_must_reasks_empty_and_refuses_cancel(self):
        data = {}
        flow = base.Write("a", name="ask").data_update("a").must()
        runner = room_app(ScriptedRunner(data, ["ask", "", "  ", "v", "leave"], on_reject="next"), flow)
        runner.run()
        self.assertEqual(data, {"a": "v"})
        self.assertEqual(len(kinds(runner, "rejected")), 2)
        strict = room_app(ScriptedRunner({}, ["ask", base.CANCEL]), base.Write("a", name="ask").must())
        with self.assertRaises(ValueError):
            strict.run()

    def test_defaults(self):
        # explicit flow: `!` (empty is asked again)
        explicit = ScriptedRunner({}, ["", "v"], on_reject="next")
        explicit.add_miniflow(base.Write("a").data_update("a").begin_end(base.Start(), base.End()))
        explicit.run()
        self.assertEqual(explicit.data, {"a": "v"})
        # command flow: `?` (empty exits, without a notice)
        command = room_app(ScriptedRunner({}, ["ask", "", "leave"]), base.Write("a", name="ask").data_update("a"))
        self.assertIs(command.run(), base.End())
        self.assertEqual(command.data, {})
        self.assertEqual(kinds(command, "notice"), [])
        # required=True inside a command flow is `!`
        required = room_app(
            ScriptedRunner({}, ["ask", "", "v", "leave"], on_reject="next"),
            base.Write("a", name="ask", kind=base.Text(required=True)).data_update("a"),
        )
        required.run()
        self.assertEqual(required.data, {"a": "v"})

    def test_inherited_from_combine(self):
        data = {}
        flow = base.LinearCombine(
            [
                base.Combine([base.Write("a").data_update("a")]),  # inherits opt through the Combine
                base.Write("b").data_update("b").q("b missing"),  # its own mark wins
            ],
            name="f",
        ).opt()
        runner = room_app(ScriptedRunner(data, ["f", "", "", "leave"]), flow)
        runner.run()
        self.assertEqual(data, {})  # a=None was stored, then b's `?` rolled it back
        self.assertEqual(kinds(runner, "notice"), [("notice", "f", "b missing")])
        self.assertEqual(kinds(runner, "write"), [("write", "a", None)])

    def test_choice_null(self):
        data = {}
        flow = base.LinearCombine(
            [base.Choice(["x", "y"], name="c1").data_update("c1").opt(), base.Choice(["x", "y"], name="c2").data_update("c2")],
            name="pick",
        ).begin_end(base.Start(), base.End())
        runner = ScriptedRunner(data, [base.CANCEL, "", "y"], on_reject="next")
        runner.add_miniflow(flow)
        runner.run()
        self.assertEqual(data, {"c1": None, "c2": "y"})
        self.assertEqual([n for _, n, _ in kinds(runner, "rejected")], ["c2"])
        allowed = ScriptedRunner({}, [""])  # "" is a real choice here, not null
        allowed.add_miniflow(base.Choice(["", "x"], name="c").data_update("c").begin_end(base.Start(), base.End()))
        allowed.run()
        self.assertEqual(allowed.data, {"c": ""})

    def test_empty_number_with_opt(self):
        data = main.UserData()
        runner = main.build_app(ScriptedRunner(data, ["Bob", ""]))
        runner.run()
        self.assertEqual((data.name, data.age), ("Bob", None))
        self.assertIn(("EndMessage", "Registered: Bob, age unknown"), [(n, t) for k, n, t in runner.transcript if k == "read"])
        self.assertIn(("Thanks", "Hello Bob (unknown years old)!"), [(n, t) for k, n, t in runner.transcript if k == "read"])
        with self.assertRaises(base.InvalidInput):  # Name is `!`
            main.build_app(ScriptedRunner(main.UserData(), [""])).run()


class BranchNullTest(unittest.TestCase):
    def build(self, branch, answers, data=None):
        runner = ScriptedRunner({} if data is None else data, answers)
        runner.add_miniflow(base.Write("v").data_update("v").begin_end(base.Start(), branch))
        return runner

    def test_q_shows_notice_restores_and_goes_back(self):
        data = {}
        branch = base.Branch(lambda d: base.End() if d["v"] == "ok" else None, [base.End()]).q("try again")
        runner = self.build(branch, ["bad", "ok"], data)
        self.assertIs(runner.run(), base.End())
        self.assertEqual(kinds(runner, "notice"), [("notice", "v", "try again")])
        self.assertEqual(kinds(runner, "cancel"), [("cancel", "v", "Branch")])
        self.assertEqual(data, {"v": "ok"})

    def test_none_without_q_is_an_error(self):
        runner = self.build(base.Branch(lambda: None, [base.End()]), ["x"])
        with self.assertRaises(ValueError) as ctx:
            runner.run()
        self.assertIn("not one of its candidates", str(ctx.exception))
        must = self.build(base.Branch(lambda: None, [base.End()]).must(), ["x"])
        with self.assertRaises(ValueError):
            must.run()

    def test_opt_goes_back_keeping_data(self):
        calls = []

        def check(data):
            calls.append(dict(data))
            return base.End() if len(calls) > 1 else None

        data = {}
        runner = self.build(base.Branch(check, [base.End()]).opt(), ["a", "b"], data)
        self.assertIs(runner.run(), base.End())
        self.assertEqual(calls, [{"v": "a"}, {"v": "b"}])
        self.assertEqual(kinds(runner, "notice"), [])

    def test_return_candidate_still_works(self):
        answers = iter([base.Return(), base.End()])
        runner = self.build(base.Branch(lambda: next(answers), [base.End(), base.Return()]).q("x"), ["a", "b"])
        self.assertIs(runner.run(), base.End())
        self.assertEqual(kinds(runner, "notice"), [])

    def test_login_failure_shows_message(self):
        runner = login_example.build_app(ScriptedRunner(login_example.LoginData(), ["alice", "nope", "alice", "secret", "quit"]))
        self.assertIs(runner.run(), base.End())
        self.assertEqual(kinds(runner, "notice"), [("notice", "login", "パスワードが違います")])


class SnapshotTest(unittest.TestCase):
    def test_restore_in_place(self):
        slotted = Slotted()
        before = __import__("copy").deepcopy(slotted)
        slotted.name, slotted.tags = "Zed", ["changed"]
        base.restore_in_place(slotted, before)
        self.assertEqual((slotted.name, slotted.tags), ("Ann", ["a"]))
        plain = Plain()
        before = __import__("copy").deepcopy(plain)
        plain.name, plain.extra = "Zed", 1
        base.restore_in_place(plain, before)
        self.assertEqual(vars(plain), {"name": "Ben"})
        d = {"a": 1}
        before = dict(d)
        d.update(a=2, b=3)
        base.restore_in_place(d, before)
        self.assertEqual(d, {"a": 1})
        items = [1]
        base.restore_in_place(items, [])
        self.assertEqual(items, [])

    def test_rollback_keeps_identity_of_slots_dataclass(self):
        data = Slotted()
        flow = base.LinearCombine(
            [base.Write("n").data_update("name"), base.Write("t").data_update(lambda d, v: d.tags.append(v))], name="f"
        )
        tags = data.tags
        # the first "f" finishes; the second is cancelled after "Bob" and rolled back to the first one's result
        runner = room_app(ScriptedRunner(data, ["f", "Zed", "tag", "f", "Bob", base.CANCEL, "leave"]), flow)
        runner.run()
        self.assertIs(runner.data, data)
        self.assertEqual((data.name, data.tags), ("Zed", ["a", "tag"]))
        self.assertIsNot(data.tags, tags)  # values inside are the snapshot's copies

    def test_rollback_dict_identity(self):
        data = {"a": 0}
        flow = base.LinearCombine([base.Write("a").data_update("a"), base.Write("b").data_update("b")], name="f")
        runner = room_app(ScriptedRunner(data, ["f", "1", base.CANCEL, "leave"]), flow)
        runner.run()
        self.assertIs(runner.data, data)
        self.assertEqual(data, {"a": 0})

    def test_uncopyable_data_warns(self):
        import threading

        data = {"lock": threading.Lock()}
        runner = room_app(ScriptedRunner(data, ["ask", "", "leave"]), base.Write("a", name="ask").data_update("a"))
        runner.run()
        self.assertTrue(any("could not be copied" in p for _, _, p in kinds(runner, "warning")))


class DescribeValidateTest(unittest.TestCase):
    def test_describe_nested_policies(self):
        runner = ScriptedRunner({})
        runner.add_miniflow(
            base.LinearCombine(
                [base.Combine([base.Write("a"), base.Read("r")]).opt(), base.Write("b")], name="f"
            ).begin_end(base.Start(), base.End())
        )
        text = runner.describe()
        self.assertIn("  f: Start() -> End()  [!]\n", text)
        self.assertIn("    Combine 'Combine'  [opt]\n      Write 'a': Text(required=False)  [opt]\n      Read 'r'  [opt]", text)
        self.assertIn("    Write 'b': Text(required=False)  [!]", text)

    def test_validate_flags_must_on_read_and_conflicts(self):
        runner = ScriptedRunner({})
        runner.add_miniflow(
            base.LinearCombine(
                [base.Read("r").must(), base.Write("w", kind=base.Text(required=True)).opt()], name="f"
            ).begin_end(base.Start(), base.End())
        )
        problems = runner.validate()
        self.assertEqual(len(problems), 2)
        self.assertIn("Read 'r' in flow 'f' is marked .must()", problems[0])
        self.assertIn("Write 'w' in flow 'f' has required=True", problems[1])
        self.assertEqual(login_example.build_app(ScriptedRunner(login_example.LoginData())).validate(), [])


class CuiNullTest(unittest.TestCase):
    def test_login_failure_then_login_again(self):
        data = login_example.LoginData()
        _, result, out, prompts = run_cui(login_example.build_app, data, ["alice", "nope", "alice", "secret", "quit", ""])
        self.assertIs(result, base.End())
        self.assertEqual(out.count("[!] パスワードが違います"), 1)
        self.assertEqual(prompts.count("username: "), 2)
        self.assertNotIn("(cancelled", out)

    def test_edit_name_empty_leaves_data_unchanged(self):
        data = login_example.LoginData()
        _, result, out, _ = run_cui(login_example.build_app, data, ["alice", "secret", "edit-name", "", "quit", ""])
        self.assertIs(result, base.End())
        self.assertEqual(data.display_name, "(not set)")
        self.assertIn("(cancelled 'edit-name')", out)
        self.assertIn("[!] 名前は変更していません", out)

    def test_optional_number_and_must_name(self):
        data = main.UserData()
        _, _, out, prompts = run_cui(main.build_app, data, ["", "Bob", "", "", ""])
        self.assertEqual((data.name, data.age), ("Bob", None))
        self.assertIn("Enter your age (0-150) (optional): ", prompts)
        self.assertIn("  ! a value is required", out)
        self.assertIn("Registered: Bob, age unknown", out)

    def test_rollback_matches_gui(self):
        data = {}
        flow = base.LinearCombine([base.Write("a").data_update("a"), base.Write("b").data_update("b")], name="f")
        _, result, out, _ = run_cui(lambda r: room_app(r, flow), data, ["", "f", "typed", ":q", "leave", ""])
        self.assertIs(result, base.End())
        self.assertEqual(data, {})  # before: "a" stayed in the CUI

    def test_must_read_refuses_cancel_and_opt_read_continues(self):
        def build(runner):
            runner.add_miniflow(
                base.LinearCombine([base.Read("one").opt(), base.Write("w").data_update("w")], name="f").begin_end(
                    base.Start(), base.End()
                )
            )
            return runner

        data = {}
        _, result, out, _ = run_cui(build, data, [":q", ":q", "v"])
        self.assertIs(result, base.End())
        self.assertEqual(data, {"w": "v"})
        self.assertIn("  ! 'f' cannot be cancelled here", out)  # the Write is `!` (explicit default)


@unittest.skipIf(gui is None, "PySide6 is not available")
class GuiNullTest(unittest.TestCase):
    def notice_text(self, runner):
        from PySide6 import QtWidgets

        label = runner.central_widget.findChild(QtWidgets.QLabel, "notice")
        return label.text() if label is not None and label.isVisible() else None

    def test_login_failure_notice(self):
        from PySide6 import QtWidgets

        runner = login_example.build_app(gui.GuiRunner(login_example.LoginData()))
        seen = {}
        typed = iter(["alice", "nope", "alice", "secret"])

        def type_and_next():
            if runner.form is None or not runner.form.findChildren(QtWidgets.QLineEdit):
                return False
            runner.form.findChildren(QtWidgets.QLineEdit)[0].setText(next(typed))
            if self.notice_text(runner):
                seen.setdefault("notice", self.notice_text(runner))
                seen.setdefault("status", runner.main_window.statusBar().currentMessage())
            visible_button(runner, "Next").click()
            return True

        def close():
            if visible_button(runner, "quit") is None:
                return False
            runner.main_window.close()
            return True

        result, left = drive(runner, [type_and_next] * 4 + [close])
        self.assertEqual(left, [])
        self.assertEqual(seen, {"notice": "パスワードが違います", "status": "パスワードが違います"})
        self.assertEqual(runner.data.username, "alice")

    def test_linear_rollback_skip_and_empty_fields(self):
        from PySide6 import QtWidgets

        data = {}
        runner = gui.GuiRunner(data)
        room_app(
            runner,
            base.LinearCombine([base.Write("a").data_update("a"), base.Write("b").data_update("b")], name="ab").q("left ab"),
            base.Combine(
                [base.Write("n", kind=base.Number(min=0)).data_update("n").opt(), base.Write("m").data_update("m").must()],
                name="form",
            ),
            base.Write("s", name="skip").data_update("s").opt(),
        )
        seen = {}

        def edits():
            return runner.form.findChildren(QtWidgets.QLineEdit) if runner.form is not None else []

        def fill_a():
            if not edits() or visible_button(runner, "Cancel") is None:
                return False
            edits()[0].setText("typed")
            visible_button(runner, "Next").click()  # a is stored ...
            return True

        def cancel_b():
            if not edits() or "a" not in data:
                return False
            seen["mid"] = dict(data)
            visible_button(runner, "Cancel").click()  # ... and rolled back here
            return True

        def empty_must():
            if len(edits()) != 2:
                return False
            seen["notice"] = self.notice_text(runner)
            seen["after_exit"] = dict(data)
            seen["placeholder"] = edits()[0].placeholderText()
            seen["cancel_button"] = visible_button(runner, "Cancel")
            visible_button(runner, "Next").click()
            errors = [e.text() for e in runner.form.findChildren(QtWidgets.QLabel, "error") if e.isVisible()]
            seen["errors"] = errors
            edits()[1].setText("M")
            visible_button(runner, "Next").click()
            return True

        def skip():
            if visible_button(runner, "Skip") is None:
                return False
            visible_button(runner, "Skip").click()
            return True

        def close():
            if "s" not in data:
                return False
            runner.main_window.close()
            return True

        result, left = drive(
            runner,
            [click(runner, "Next"), click(runner, "ab"), fill_a, cancel_b, click(runner, "form"), empty_must,
             click(runner, "skip"), skip, close],
        )
        self.assertEqual(left, [])
        self.assertEqual(seen["mid"], {"a": "typed"})
        self.assertEqual(seen["after_exit"], {})
        self.assertEqual(seen["notice"], None)  # the notice was on the selection screen, now gone
        self.assertEqual(seen["placeholder"], ">= 0, optional")
        self.assertIsNotNone(seen["cancel_button"])  # the screen (a command flow) is `?`
        self.assertEqual(seen["errors"], ["a value is required"])
        self.assertEqual(data, {"n": None, "m": "M", "s": None})
        self.assertIs(result, base.QUIT)


if __name__ == "__main__":
    unittest.main()
