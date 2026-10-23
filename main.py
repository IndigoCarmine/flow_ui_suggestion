from dataclasses import dataclass

import base
import runtime


@dataclass(slots=True)
class UserData:
    name: str = ""
    age_text: str = ""


def update_name(data: UserData, value: str) -> None:
    data.name = value


def update_age_text(data: UserData, value: str) -> None:
    data.age_text = value


def build_greeting(data: UserData) -> str:
    age_label = data.age_text if data.age_text else "unknown"
    return f"Hello {data.name} ({age_label} years old)!"


def build_registration_steps() -> list[base.MiniFlow]:
    return [
        base.Write(None, None, "Enter your name", "Name").data_update(update_name),
        base.Write(None, None, "Enter your age", "Age").data_update(update_age_text),
        base.Read(None, None, "Thank you!", "Thanks").context_build(build_greeting),
    ]


def build_app(runner: base.ApplicationRunnerBase) -> base.ApplicationRunnerBase:
    start = base.Start("MainStart")
    middle = base.State("MiddleState")
    end = base.End("MainEnd")

    flows: list[base.MiniFlow] = [
        base.LinearCombine(start, middle, build_registration_steps(), "RegistrationProcess"),
        # テンプレート文字列はslots=Trueのdataclassでも使える
        base.Read(middle, end, "Process Complete", "EndMessage").context_build(
            "Registered: {name}, age {age_text}"
        ),
    ]

    for flow in flows:
        runner.add_miniflow(flow)
    return runner


def main() -> None:
    # バックエンドは --cui/--gui、環境変数 FLOW_UI_BACKEND、または自動判定で決まる
    runtime.run(build_app, UserData())


if __name__ == "__main__":
    main()
