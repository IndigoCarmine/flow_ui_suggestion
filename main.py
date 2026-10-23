from dataclasses import dataclass
from typing import Optional

import base
import runtime


@dataclass(slots=True)
class UserData:
    name: str = ""
    age: Optional[int] = None


def update_name(data: UserData, value: str) -> None:
    data.name = value


def update_age(data: UserData, value: Optional[int]) -> None:
    data.age = value  # Number() なので変換済みのint。.opt() なので空ならNone


def build_greeting(data: UserData) -> str:
    age_label = data.age if data.age is not None else "unknown"
    return f"Hello {data.name} ({age_label} years old)!"


def build_registration_steps() -> list[base.MiniFlow]:
    # 何を入力させたいか(kind)だけを書く。ウィジェットや再入力の方法はRunnerが決める
    return [
        # 明示的なフローの既定は .must()（!）なので、名前は空だと聞き直す
        base.Write("Enter your name", name="Name").data_update(update_name),
        # .opt(): 空のままでもよい（data_updateにNoneが渡る）
        base.Write("Enter your age", name="Age", kind=base.Number(min=0, max=150)).data_update(update_age).opt(),
        base.Read("Thank you!", name="Thanks").context_build(build_greeting),
    ]


def build_app(runner: base.ApplicationRunnerBase) -> base.ApplicationRunnerBase:
    start = base.Start()
    middle = base.State("MiddleState")
    end = base.End()

    flows: list[base.MiniFlow] = [
        # 旧来の位置引数 (begin, end, 内容, name) の形も使える
        base.LinearCombine(start, middle, build_registration_steps(), "RegistrationProcess"),
        # テンプレート文字列はslots=Trueのdataclassでも使える
        base.Read("Process Complete", name="EndMessage")
        .context_build(lambda d: f"Registered: {d.name}, age {d.age if d.age is not None else 'unknown'}")
        .begin_end(middle, end),
    ]

    for flow in flows:
        runner.add_miniflow(flow)
    return runner


def main() -> None:
    # バックエンドは --cui/--gui、環境変数 FLOW_UI_BACKEND、または自動判定で決まる
    runtime.run(build_app, UserData())


if __name__ == "__main__":
    main()
