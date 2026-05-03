from dataclasses import dataclass

# GUIを使う場合はこちら
import gui as w

# CUIを使う場合はこちら
# import cui as w


@dataclass
class UserData:
    name: str = ""
    age: str = ""


if __name__ == "__main__":
    start = w.Start("MainStart")
    end = w.End("MainEnd")
    mid = w.base.State("MiddleState")

    data = UserData()

    # ひとつづきの処理をリストから作成
    # 各ステップは内部で順次実行される
    steps = [
        w.Read(None, None, "Enter your name", "Name").data_update("name"),
        w.Read(None, None, "Enter your age", "Age").data_update("age"),
        w.Write(None, None, "Thank you!", "Thanks").context_build(
            lambda d: f"Hello {d.name} ({d.age} years old)!"
        ),
    ]

    # LinearCombineとして一つのMiniFlowにまとめる
    flow1 = w.LinearCombine(start, mid, steps, "RegistrationProcess")

    # 登録後の確認メッセージ
    flow2 = w.Write(mid, end, "Process Complete", "EndMessage")

    app = w.ApplicationRunner(data=data)
    app.add_miniflow(flow1)
    app.add_miniflow(flow2)

    app.run()
