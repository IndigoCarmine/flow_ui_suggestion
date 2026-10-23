import io
import os
import unittest
from contextlib import redirect_stderr
from dataclasses import dataclass
from unittest import mock

import base
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
        self.assertEqual((data.name, data.age_text), ("Bob", "30"))
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
        self.assertIn("login: Start(start) -> Branch[LoggedIn(home), Return()]", text)
        self.assertIn("LoggedIn(home)  commands: profile, edit-name, logout, quit", text)


class StateIdentityTest(unittest.TestCase):
    def test_start_end_shared(self):
        self.assertIs(base.Start(), base.Start("other name"))
        self.assertIs(base.End("a"), base.End())
        self.assertNotEqual(base.Start(), base.End())

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


class ValidateTest(unittest.TestCase):
    def test_dead_end_and_unreachable(self):
        runner = ScriptedRunner(None)
        runner.add_miniflow(base.Read(base.Start(), base.State("stuck"), "", "go"))
        runner.add_miniflow(base.Read(base.State("island"), base.End(), "", "never"))
        problems = runner.validate()
        self.assertIn("dead end: no flow begins at State(stuck)", problems)
        self.assertIn("unreachable from Start: State(island)", problems)
        # End is shared, so its cosmetic name is whatever was given last
        self.assertTrue(any(p.startswith("unreachable from Start: End(") for p in problems))
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
        self.assertEqual(self.choose({}), "cui")

    def test_unknown(self):
        with self.assertRaises(ValueError):
            self.choose({"FLOW_UI_BACKEND": "web"})


if __name__ == "__main__":
    unittest.main()
