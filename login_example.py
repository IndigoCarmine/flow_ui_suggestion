from dataclasses import dataclass

import base
import runtime

USERS = {"alice": "secret"}


@dataclass
class LoginData:
    username: str = ""
    password: str = ""
    display_name: str = "(not set)"


class LoggedIn(base.State):
    """Every state where the user is logged in. Command flows that begin at this type run here."""


def not_blank(value: str):
    """validate: エラーメッセージかNoneを返す。Runnerがメッセージを見せて聞き直す。"""
    if not value.strip():
        return "name must not be blank"
    return None


def build_app(runner: base.ApplicationRunnerBase) -> base.ApplicationRunnerBase:
    start = base.Start()
    home = LoggedIn("home")
    end = base.End()

    def check(data: LoginData) -> base.State:
        if USERS.get(data.username) == data.password:
            return home
        return base.Return()  # 失敗したらログインフローの開始点(start)へ戻る

    login = base.LinearCombine(
        [
            base.Write("username", name="Username", kind=base.Text(required=True)).data_update("username"),
            base.Write("password", name="Password", kind=base.Password()).data_update("password"),
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
        [
            base.Write("new name", name="EditName", validate=not_blank).data_update("display_name"),
            base.Read(name="Changed").context_build("name changed to {display_name}"),
        ],
        name="edit-name",
    ).begin(LoggedIn)
    logout = base.Read("logged out", name="logout").begin_end(LoggedIn, start)
    quit_app = base.Read("bye", name="quit").begin_end(LoggedIn, end)

    for flow in [login, profile, edit_name, logout, quit_app]:
        runner.add_miniflow(flow)
    return runner


def main() -> None:
    # バックエンドは --cui/--gui、環境変数 FLOW_UI_BACKEND、または自動判定で決まる
    runtime.run(build_app, LoginData())


if __name__ == "__main__":
    main()
