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


def short_enough(value: str):
    """validate: エラーメッセージかNoneを返す。Runnerがメッセージを見せて聞き直す。
    （空の入力はvalidateの前に「null」として扱われるので、ここでは空を気にしなくてよい）"""
    if len(value) > 20:
        return "name must be at most 20 characters"
    return None


def build_app(runner: base.ApplicationRunnerBase) -> base.ApplicationRunnerBase:
    start = base.Start()
    home = LoggedIn("home")
    end = base.End()

    def check(data: LoginData):
        if USERS.get(data.username) == data.password:
            return home
        return None  # null: .q(...) なので、メッセージを出して開始点(start)へ戻る（入力も無かったことになる）

    # 明示的なフローの既定は .must()（!）: 空の入力は聞き直し、キャンセルは断る
    login = base.LinearCombine(
        [
            base.Write("username", name="Username").data_update("username"),
            base.Write("password", name="Password", kind=base.Password()).data_update("password"),
        ],
        name="login",
    ).begin_end(start, base.Branch(check, [home]).q("パスワードが違います"))

    # LoggedIn型から始まるコマンドフロー。endを省略すると呼び出し元の状態へ戻る。
    # コマンドフローの既定は .q()（?）: 空の入力・:q・Esc でフローを抜け、dataは開始時に戻る。
    profile = (
        base.Read(name="profile")
        .context_build("user: {username}, name: {display_name}")
        .begin(LoggedIn)
    )
    edit_name = base.LinearCombine(
        [
            base.Write("new name", name="EditName", validate=short_enough).data_update("display_name"),
            base.Read(name="Changed").context_build("name changed to {display_name}"),
        ],
        name="edit-name",
    ).begin(LoggedIn).q("名前は変更していません")
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
