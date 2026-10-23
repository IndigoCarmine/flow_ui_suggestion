import sys
from dataclasses import dataclass

import base
import cui

USERS = {"alice": "secret"}


@dataclass
class LoginData:
    username: str = ""
    password: str = ""
    display_name: str = "(not set)"


class LoggedIn(base.State):
    """Every state where the user is logged in. Command flows that begin at this type run here."""


def build_app(runner: base.ApplicationRunnerBase) -> base.ApplicationRunnerBase:
    start = base.Start("start")
    home = LoggedIn("home")
    end = base.End("end")

    def check(data: LoginData) -> base.State:
        if USERS.get(data.username) == data.password:
            return home
        return base.Return()  # 失敗したらログインフローの開始点(start)へ戻る

    login = base.LinearCombine(
        flows=[
            base.Write(message="username", name="Username").data_update("username"),
            base.Write(message="password", name="Password").data_update("password"),
        ],
        name="login",
    ).begin_end(start, base.Branch(check, [home, base.Return()]))

    # LoggedIn型から始まるコマンドフロー。endを省略すると呼び出し元の状態へ戻る。
    profile = (
        base.Read(name="profile")
        .context_build("user: {username}, name: {display_name}")
        .begin(LoggedIn)
    )
    edit_name = base.LinearCombine(
        flows=[
            base.Write(message="new name", name="EditName").data_update("display_name"),
            base.Read(name="Changed").context_build("name changed to {display_name}"),
        ],
        name="edit-name",
    ).begin(LoggedIn)
    logout = base.Read(message="logged out", name="logout").begin_end(LoggedIn, start)
    quit_app = base.Read(message="bye", name="quit").begin_end(LoggedIn, end)

    for flow in [login, profile, edit_name, logout, quit_app]:
        runner.add_miniflow(flow)
    return runner


def main() -> None:
    data = LoginData()
    if "gui" in sys.argv[1:]:
        import gui

        runner = gui.GuiRunner(data)
    else:
        runner = cui.CuiRunner(data)
    build_app(runner).run()


if __name__ == "__main__":
    main()
