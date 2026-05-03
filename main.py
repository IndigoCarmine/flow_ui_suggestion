from dataclasses import dataclass

import base

# GUIを使う場合はこちら
import gui as ui

# CUIを使う場合はこちら
# import cui as ui


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
        ui.Read(None, None, "Enter your name", "Name").data_update(update_name),
        ui.Read(None, None, "Enter your age", "Age").data_update(update_age_text),
        ui.Write(None, None, "Thank you!", "Thanks").context_build(build_greeting),
    ]


def build_app(data: UserData) -> ui.ApplicationRunner:
    start = ui.Start("MainStart")
    middle = base.State("MiddleState")
    end = ui.End("MainEnd")

    flows: list[base.MiniFlow] = [
        ui.LinearCombine(start, middle, build_registration_steps(), "RegistrationProcess"),
        ui.Write(middle, end, "Process Complete", "EndMessage"),
    ]

    app = ui.ApplicationRunner(data=data)
    for flow in flows:
        app.add_miniflow(flow)
    return app


def main() -> None:
    app = build_app(UserData())
    app.run()


if __name__ == "__main__":
    main()
