import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from dataclasses import dataclass
from unittest import mock

import base
import cui
import login_example
import main
import runtime
from scripted import ScriptedRunner, ScriptExhausted


def reads(runner):
    return [(name, text) for kind, name, text in runner.transcript if kind == "read"]


class MainFlowTest(unittest.TestCase):
    def test_registration(self):
        data = main.UserData()
        runner = main.build_app(ScriptedRunner(data, ["Bob", "30"]))
        runner.run()
        self.assertEqual((data.name, data.age), ("Bob", 30))
        self.assertEqual(
            reads(runner),
            [("Thanks", "Hello Bob (30 years old)!"), ("EndMessage", "Registered: Bob, age 30")],
        )
        self.assertIsInstance(runner.current_state, base.End)
        self.assertEqual(runner.remaining_answers, [])
        self.assertEqual(runner.validate(), [])

    def test_answers_run_out(self):
        runner = main.build_app(ScriptedRunner(main.UserData(), ["Bob"]))
        with self.assertRaises(ScriptExhausted) as ctx:
            runner.run()
        self.assertIn("Age", str(ctx.exception))


class LoginExampleTest(unittest.TestCase):
    def test_full_session(self):
        data = login_example.LoginData()
        answers = [
            "alice", "wrong",      # wrong password -> Return() -> back to start, login again
            "alice", "secret",     # -> home
            "edit-name", "Bob",
            "profile",
            "quit",
        ]
        runner = login_example.build_app(ScriptedRunner(data, answers))
        runner.run()
        self.assertEqual(runner.remaining_answers, [])
        self.assertEqual(data.display_name, "Bob")
        self.assertEqual(
            reads(runner),
            [
                ("Changed", "name changed to Bob"),
                ("profile", "user: alice, name: Bob"),
                ("quit", "bye"),
            ],
        )
        writes = [text for kind, _, text in runner.transcript if kind == "write"]
        self.assertEqual(writes, ["alice", "wrong", "alice", "secret", "Bob"])
        self.assertIsInstance(runner.current_state, base.End)
        self.assertEqual(runner.validate(), [])

    def test_logout_returns_to_start(self):
        runner = login_example.build_app(
            ScriptedRunner(login_example.LoginData(), ["alice", "secret", "logout", "alice", "secret", "quit"])
        )
        runner.run()
        self.assertEqual([t for k, _, t in runner.transcript if k == "select"], ["logout", "quit"])

    def test_unknown_selection(self):
        runner = login_example.build_app(ScriptedRunner(login_example.LoginData(), ["alice", "secret", "nope"]))
        with self.assertRaises(ValueError):
            runner.run()

    def test_describe(self):
        text = login_example.build_app(ScriptedRunner(login_example.LoginData())).describe()
        self.assertIn("login: Start() -> Branch[LoggedIn(home), Return()]", text)
        self.assertIn("LoggedIn(home)  commands: profile, edit-name, logout, quit", text)


class StateIdentityTest(unittest.TestCase):
    def test_start_end_shared(self):
        self.assertIs(base.Start(), base.Start("other name"))
        self.assertIs(base.End("a"), base.End())
        self.assertNotEqual(base.Start(), base.End())

    def test_start_end_names_fixed(self):
        base.Start("renamed")
        base.End("renamed")
        self.assertEqual((base.Start().name, base.End().name), ("Start", "End"))
        self.assertEqual((repr(base.Start()), repr(base.End())), ("Start()", "End()"))

    def test_named_states_equal(self):
        self.assertEqual(base.State("home"), base.State("home"))
        self.assertEqual(hash(base.State("home")), hash(base.State("home")))
        self.assertNotEqual(base.State("home"), base.State("away"))
        self.assertNotEqual(login_example.LoggedIn("home"), base.State("home"))
        self.assertNotEqual(base.State(), base.State())  # unnamed: identity only

    def test_return_distinct(self):
        self.assertIs(base.Return(), base.Return())
        self.assertNotEqual(base.Return(), base.State("home"))
        self.assertNotEqual(base.State("home"), base.Return())
        self.assertNotEqual(base.Return(), base.Start())

    def test_fresh_instances_connect(self):
        runner = ScriptedRunner(None)
        runner.add_miniflow(base.Read(base.Start(), base.State("mid"), "one", "first"))
        runner.add_miniflow(
            base.Read(base.State("mid"), base.Branch(lambda: base.State("last"), [base.State("last")]), "two", "second")
        )
        runner.add_miniflow(base.Read(base.State("last"), base.End(), "three", "third"))
        self.assertEqual(runner.validate(), [])
        runner.run()
        self.assertEqual([n for n, _ in reads(runner)], ["first", "second", "third"])


@dataclass(slots=True)
class Slotted:
    name: str = "Ann"


class Plain:
    def __init__(self):
        self.name = "Ben"


class TemplateTest(unittest.TestCase):
    def test_sources(self):
        flow = base.Read(name="r").context_build("hi {name}")
        self.assertEqual(flow.resolve_content(Slotted()), "hi Ann")
        self.assertEqual(flow.resolve_content(Plain()), "hi Ben")
        self.assertEqual(flow.resolve_content({"name": "Cat"}), "hi Cat")

    def test_missing_field_falls_back(self):
        flow = base.Read(message="fallback", name="r").context_build("hi {missing}")
        self.assertEqual(flow.resolve_content(Slotted()), "fallback")

    def test_bare_attribute_name_gives_value(self):
        flow = base.Read("fallback").context_build("name")
        self.assertEqual(flow.resolve_content(Slotted()), "Ann")
        self.assertEqual(flow.resolve_content({"name": "Cat"}), "Cat")
        options = base.Choice(name="c").context_build("options")
        self.assertEqual(options.resolve_content({"options": ["x", "y"]}), ["x", "y"])

    def test_bare_text_is_literal(self):
        flow = base.Read("fallback").context_build("Welcome back")
        self.assertEqual(flow.resolve_content(Slotted()), "Welcome back")
        self.assertEqual(flow.resolve_content(None), "Welcome back")
        self.assertEqual(base.Read().context_build("name").resolve_content(None), "name")


class ValidateTest(unittest.TestCase):
    def test_dead_end_and_unreachable(self):
        runner = ScriptedRunner(None)
        runner.add_miniflow(base.Read(base.Start(), base.State("stuck"), "", "go"))
        runner.add_miniflow(base.Read(base.State("island"), base.End(), "", "never"))
        problems = runner.validate()
        self.assertIn("dead end: no flow begins at State(stuck)", problems)
        self.assertIn("unreachable from Start: State(island)", problems)
        self.assertIn("unreachable from Start: End()", problems)
        self.assertEqual(len(problems), 3)

    def test_no_start_and_branch_nowhere(self):
        runner = ScriptedRunner(None)
        runner.add_miniflow(base.Read(base.State("a"), base.Branch(lambda: None, [base.State("b"), "x"]), "", "f"))
        problems = runner.validate()
        self.assertIn("no flow begins at Start", problems)
        self.assertTrue(any("Branch candidate State(b)" in p and "leads nowhere" in p for p in problems))
        self.assertTrue(any("candidate 'x'" in p for p in problems))

    def test_command_counts_as_outgoing(self):
        class Area(base.State):
            pass

        runner = ScriptedRunner(None, ["leave"])
        runner.add_miniflow(base.Read(base.Start(), Area("room"), "", "enter"))
        runner.add_miniflow(base.Read(name="leave").begin_end(Area, base.End()))
        self.assertEqual(runner.validate(), [])

    def test_run_reports_but_continues(self):
        runner = ScriptedRunner(None)
        runner.add_miniflow(base.Read(base.Start(), base.State("stuck"), "", "go"))
        with redirect_stderr(io.StringIO()), mock.patch("builtins.print"):
            runner.run()
        self.assertTrue(any(k == "warning" for k, _, _ in runner.transcript))
        self.assertEqual(reads(runner), [("go", "")])


class BackendChoiceTest(unittest.TestCase):
    def choose(self, env, backend=None, argv=()):
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(runtime.sys, "platform", "linux"):
            return runtime.choose_backend(backend, list(argv))

    def test_order(self):
        self.assertEqual(self.choose({"FLOW_UI_BACKEND": "gui"}, backend="cui"), "cui")
        self.assertEqual(self.choose({"FLOW_UI_BACKEND": "gui"}, argv=["--cui"]), "cui")
        self.assertEqual(self.choose({"FLOW_UI_BACKEND": "cui", "DISPLAY": ":0"}), "cui")
        self.assertEqual(self.choose({"FLOW_UI_BACKEND": "GUI"}), "gui")

    def test_auto_without_display_is_cui(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.choose({}), "cui")
        self.assertEqual(err.getvalue(), "")  # no display: nothing to explain

    def test_display_but_no_pyside_says_why(self):
        err = io.StringIO()
        blocked = {"PySide6": None, "PySide6.QtWidgets": None}  # makes the import raise ImportError
        with mock.patch.dict(sys.modules, blocked), redirect_stderr(err):
            self.assertEqual(self.choose({"DISPLAY": ":0"}), "cui")
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("PySide6 could not be imported", lines[0])
        self.assertIn("using CUI", lines[0])

    def test_unknown(self):
        with self.assertRaises(ValueError):
            self.choose({"FLOW_UI_BACKEND": "web"})



class ConstructorTest(unittest.TestCase):
    def test_short_forms(self):
        self.assertEqual((base.Read("hello", name="r").message, base.Read("hello", name="r").name), ("hello", "r"))
        w = base.Write("Enter age", name="Age")
        self.assertEqual((w.message, w.name, w.begin_state, w.end_state), ("Enter age", "Age", None, None))
        self.assertIsInstance(w.kind, base.Text)
        self.assertEqual(base.Choice(["a", "b"], name="c").choices, ["a", "b"])
        child = base.Read("x")
        self.assertEqual(base.Combine([child]).flows, [child])
        self.assertEqual(base.LinearCombine([child], name="seq").flows, [child])

    def test_default_names(self):
        self.assertEqual(base.Read("hello").name, "hello")
        self.assertEqual(base.Write("Enter age").name, "Enter age")
        self.assertEqual(base.Read().name, "Read")
        self.assertEqual(base.Choice(["a"]).name, "Choice")
        self.assertEqual(base.Combine([]).name, "Combine")

    def test_old_positional_form(self):
        home = base.State("home")
        r = base.Read(base.Start(), home, "msg", "n")
        self.assertEqual((r.begin_state, r.end_state, r.message, r.name), (base.Start(), home, "msg", "n"))
        w = base.Write(None, None, "Enter your name", "Name")
        self.assertEqual((w.message, w.name), ("Enter your name", "Name"))
        c = base.Choice(home, None, ["a"], "pick")
        self.assertEqual((c.begin_state, c.choices, c.name), (home, ["a"], "pick"))
        lc = base.LinearCombine(home, base.End(), [r], "seq")
        self.assertEqual((lc.flows, lc.end_state, lc.name), ([r], base.End(), "seq"))
        cmd = base.Read(login_example.LoggedIn, None, "m", "cmd")
        self.assertTrue(cmd.is_command)

    def test_keywords_still_work(self):
        r = base.Read(message="m", name="n", begin_state=base.Start(), end_state=base.End())
        self.assertEqual((r.message, r.name, r.begin_state, r.end_state), ("m", "n", base.Start(), base.End()))
        self.assertEqual(base.Combine(flows=[r], name="c").flows, [r])

    def test_bad_arguments(self):
        with self.assertRaises(TypeError):
            base.Read("a", "b")  # short form: name is keyword-only
        with self.assertRaises(TypeError):
            base.Read("a", message="b")
        with self.assertRaises(TypeError):
            base.Read(None, None, "m", "n", "extra")
        with self.assertRaises(TypeError):
            base.Write("x", kind="number")

    def test_steps_hold_no_progress_state(self):
        step = base.Read("hi", name="r")
        self.assertFalse(hasattr(step, "is_complete"))
        self.assertFalse(hasattr(step, "complete"))
        runner = ScriptedRunner(None)
        runner.add_miniflow(step.begin_end(base.Start(), base.State("again")))
        runner.add_miniflow(base.Read("hi", name="r2").begin_end(base.State("again"), base.End()))
        runner.run()
        runner.run()  # the same step objects run again
        self.assertEqual([n for n, _ in reads(runner)], ["r", "r2", "r", "r2"])


def run_writes(steps, answers, data=None):
    """Run `steps` as one LinearCombine from Start to End with a ScriptedRunner."""
    runner = ScriptedRunner({} if data is None else data, answers)
    runner.add_miniflow(base.LinearCombine(steps, name="all").begin_end(base.Start(), base.End()))
    runner.run()
    return runner


class KindTest(unittest.TestCase):
    def test_conversion(self):
        steps = [
            base.Write("name").data_update("name"),
            base.Write("age", kind=base.Number(min=0, max=150)).data_update("age"),
            base.Write("height", kind=base.Number(decimals=1)).data_update("height"),
            base.Write("agree", kind=base.YesNo()).data_update("agree"),
            base.Write("newsletter", kind=base.YesNo).data_update("newsletter"),  # a kind class also works
            base.Write("pw", kind=base.Password()).data_update("pw"),
        ]
        runner = run_writes(steps, ["Ann", " 42 ", "1.5", "Yes", False, "s3cret"])
        self.assertEqual(
            runner.data,
            {"name": "Ann", "age": 42, "height": 1.5, "agree": True, "newsletter": False, "pw": "s3cret"},
        )
        self.assertIsInstance(runner.data["age"], int)
        self.assertEqual([v for k, _, v in runner.transcript if k == "write"][1], 42)

    def test_typed_answers(self):
        runner = run_writes([base.Write("n", kind=base.Number()).data_update("n")], [7.0])
        self.assertEqual(runner.data, {"n": 7})
        self.assertIsInstance(runner.data["n"], int)

    def assertRejected(self, step, answer, message):
        with self.assertRaises(base.InvalidInput) as ctx:
            run_writes([step], [answer])
        self.assertIn(message, str(ctx.exception))
        self.assertIn(repr(answer), str(ctx.exception))
        self.assertIn(step.name, str(ctx.exception))

    def test_invalid_answers(self):
        age = base.Write("age", kind=base.Number(min=0, max=150))
        self.assertRejected(age, "abc", "enter a whole number")
        self.assertRejected(age, "2.5", "enter a whole number")
        self.assertRejected(age, "200", "enter a number from 0 to 150")
        self.assertRejected(age, -1, "enter a number from 0 to 150")
        self.assertRejected(base.Write("n", kind=base.Number(min=1)), "0", "at least 1")
        self.assertRejected(base.Write("n", kind=base.Number(max=1)), "2", "at most 1")
        self.assertRejected(base.Write("n", kind=base.Number(decimals=2)), "x", "enter a number")
        self.assertRejected(base.Write("ok", kind=base.YesNo()), "maybe", "answer yes or no")
        self.assertRejected(base.Write("name", kind=base.Text(required=True)), "  ", "a value is required")
        self.assertRejected(base.Write("pw", kind=base.Password(required=True)), "", "a value is required")

    def test_accept_directly(self):
        w = base.Write("age", kind=base.Number(min=0))
        self.assertEqual(w.accept("5"), 5)
        with self.assertRaises(base.InvalidInput):
            w.accept("-5")


class ValidationTest(unittest.TestCase):
    def test_validate_message(self):
        def even(value):
            return None if value % 2 == 0 else "must be even"

        step = base.Write("n", kind=base.Number(), validate=even).data_update("n")
        self.assertEqual(run_writes([step], ["4"]).data, {"n": 4})
        with self.assertRaises(base.InvalidInput) as ctx:
            run_writes([step], ["3"])
        self.assertIn("must be even", str(ctx.exception))

    def test_validate_with_data(self):
        def same_as_first(data, value):
            return None if value == data["pw"] else "passwords do not match"

        steps = [
            base.Write("password", kind=base.Password()).data_update("pw"),
            base.Write("again", kind=base.Password(), validate=same_as_first).data_update("pw2"),
        ]
        self.assertEqual(run_writes(steps, ["a", "a"]).data, {"pw": "a", "pw2": "a"})
        with self.assertRaises(base.InvalidInput) as ctx:
            run_writes(steps, ["a", "b"])
        self.assertIn("passwords do not match", str(ctx.exception))

    def test_kind_check_runs_before_validate(self):
        calls = []
        step = base.Write("n", kind=base.Number(max=10), validate=lambda v: calls.append(v))
        with self.assertRaises(base.InvalidInput):
            run_writes([step], ["11"])
        self.assertEqual(calls, [])

    def test_rejected_value_is_not_stored(self):
        step = base.Write("n", kind=base.Number(max=10)).data_update("n")
        data = {}
        with self.assertRaises(base.InvalidInput):
            run_writes([step], ["11"], data)
        self.assertEqual(data, {})

    def test_login_blank_name(self):
        answers = ["alice", "secret", "edit-name", "   "]
        runner = login_example.build_app(ScriptedRunner(login_example.LoginData(), answers))
        with self.assertRaises(base.InvalidInput) as ctx:
            runner.run()
        self.assertIn("name must not be blank", str(ctx.exception))


class CombineTest(unittest.TestCase):
    def test_every_step_type(self):
        inner = base.LinearCombine(
            [base.Write("city").data_update("city"), base.Read(name="r2").context_build("{city}!")], name="inner"
        )
        nested = base.Combine([base.Write("zip", kind=base.Number()).data_update("zip")], name="nested")
        combine = base.Combine(
            [
                base.Read("intro", name="r1"),
                base.Choice(["red", "blue"], name="color").data_update("color"),
                inner,
                nested,
            ],
            name="form",
        )
        runner = ScriptedRunner({}, ["blue", "Oslo", "123"])
        runner.add_miniflow(combine.begin_end(base.Start(), base.End()))
        runner.run()
        self.assertEqual(runner.data, {"color": "blue", "city": "Oslo", "zip": 123})
        self.assertEqual(
            [(k, n) for k, n, _ in runner.transcript],
            [("read", "r1"), ("choice", "color"), ("write", "city"), ("read", "r2"), ("write", "zip")],
        )
        self.assertEqual(reads(runner)[1], ("r2", "Oslo!"))

    def test_unknown_child_is_an_error(self):
        class Strange(base.MiniFlow):
            pass

        runner = ScriptedRunner({})
        runner.add_miniflow(base.Combine([Strange("?")], name="c").begin_end(base.Start(), base.End()))
        with self.assertRaises(TypeError) as ctx:
            runner.run()
        self.assertIn("Strange", str(ctx.exception))



class CuiTest(unittest.TestCase):
    def run_cui(self, build, data, lines):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=lines) as fake, mock.patch("sys.stdout", out):
            runner = build(cui.CuiRunner(data))
            runner.run()
        return runner, out.getvalue(), [c.args[0] for c in fake.call_args_list]

    def test_bad_age_is_asked_again(self):
        data = main.UserData()
        _, out, prompts = self.run_cui(main.build_app, data, ["", "Bob", "abc", "200", "30", "", ""])
        self.assertEqual((data.name, data.age), ("Bob", 30))
        self.assertIn("  ! a value is required", out)
        self.assertIn("  ! enter a whole number", out)
        self.assertIn("  ! enter a number from 0 to 150", out)
        self.assertEqual(prompts.count("Enter your age (0-150): "), 3)

    def test_password_uses_input_when_stdin_is_not_a_tty(self):
        data = login_example.LoginData()
        with mock.patch("sys.stdin", io.StringIO()), mock.patch("getpass.getpass") as gp:
            self.run_cui(login_example.build_app, data, ["alice", "secret", "quit", ""])
        gp.assert_not_called()
        self.assertEqual(data.password, "secret")

    def test_password_uses_getpass_on_a_tty(self):
        tty = mock.Mock()
        tty.isatty.return_value = True
        data = login_example.LoginData()
        with mock.patch("sys.stdin", tty), mock.patch("getpass.getpass", return_value="secret") as gp:
            self.run_cui(login_example.build_app, data, ["alice", "quit", ""])
        gp.assert_called_once_with("password: ")

    def test_combine_with_choice_and_nested(self):
        def build(runner):
            runner.add_miniflow(
                base.Combine(
                    [
                        base.Read("Order"),
                        base.Choice(["tea", "coffee"], name="drink").data_update("drink"),
                        base.LinearCombine([base.Write("sugar", kind=base.YesNo()).data_update("sugar")]),
                    ],
                    name="order",
                ).begin_end(base.Start(), base.End())
            )
            return runner

        data = {}
        _, out, prompts = self.run_cui(build, data, ["5", "1", "maybe", "y"])
        self.assertEqual(data, {"drink": "coffee", "sugar": True})
        self.assertIn("  ! enter a number from 0 to 1", out)
        self.assertIn("  ! answer yes or no (y/n)", out)
        self.assertNotIn("[Press Enter to continue]", prompts)  # input was taken, no extra Enter


if __name__ == "__main__":
    unittest.main()
