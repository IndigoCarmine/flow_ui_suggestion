# Flow UI Framework (System Proposal)
uvを使います
## 1. プロジェクトの概要
Flow UI Frameworkは、アプリケーションのUIをプログラムするのではなく、Userが何をするのかについてプログラムできれば、LLMのコード生成で都合が良いのではないかと考えから作成しました。実用というより提案のためのコードです。

従来のUI開発では、開発者が目標とするUserの作業を考えながら、画面のレイアウトとデータ構造を構築するという流れでした。そこで、各ステート間での一連作業（MiniFlow）を組み立て、それをNodeGraphで管理する形のみを記述させるようにしました。具体的な描画やインタラクションの詳細は、実行環境（Runtime）に完全に委譲されます。

今のところUserが何をするかを基準にClass名を決めています。
例えば以下のように記述できます（実際に動くものは `login_example.py`。`uv run python login_example.py` で実行環境に合わせて自動選択、`--cui` / `--gui` で指定）。

```python
import base, runtime

class LoggedIn(base.State):  # 「ログイン中」という種類の状態
    pass

start, home, end = base.Start("start"), LoggedIn("home"), base.End("end")
data = LoginData()

def check(data) -> base.State:
    return home if is_exist_user(data) else base.Return()  # 失敗したら開始点へ戻る

# 明示的なフロー: startから始まり、Branchで home か Return() に分岐する
login = base.LinearCombine(
    flows=[
        base.Write(message="username", name="Username").data_update("username"),
        base.Write(message="password", name="Password").data_update("password"),
    ],
    name="login",
).begin_end(start, base.Branch(check, [home, base.Return()]))

# コマンドフロー: 型(LoggedIn)から始まり、LoggedInのどの状態からでも選べる。
# endを省略すると、実行前の状態へ戻る。
profile = base.Read(name="profile").context_build("user: {username}").begin(LoggedIn)
logout = base.Read(message="logged out", name="logout").begin_end(LoggedIn, start)
quit_app = base.Read(message="bye", name="quit").begin_end(LoggedIn, end)

def build_app(runner):
    for flow in [login, profile, logout, quit_app]:
        runner.add_miniflow(flow)
    return runner

runtime.run(build_app, data)  # CUI/GUIはアプリのコードでは選ばない
```

## 2. 設計思想：Logic-First, Rendering-Last
本フレームワークの根底には、以下の思想があります。

- **グラフによるフロー定義**: アプリケーション全体をステートマシンとして捉え、ノード（状態）とエッジ（ユーザーとの対話）で構造化します。これにより、複雑な分岐やループを直感的に記述できます。
- **レンダリングの完全委譲**: 開発者は「名前を入力させる」「情報を表示する」といった**意図（Intent）**のみを定義します。それをGUI（PySide6）のウィンドウで表示するか、CUI（Terminal）の対話として実行するかはRuntimeの種類で決定します。
- **環境適応型UI**: Windowサイズや入出力デバイスの制約に応じて、Runtimeが最適なレイアウトを動的に生成します。

## 3. コアコンポーネント

- **State (状態)**: アプリケーションの特定の瞬間を表すチェックポイントです（Start, Endなど）。名前付きのStateは（型, 名前）で比較されるので、`State("home")` を2回書いても同じ状態です。`Start()` と `End()` は常に同じ1つのインスタンスで、名前は表示用です。
- **MiniFlow (インタラクション)**: 状態間の遷移（エッジ）であり、ユーザーとの対話を定義します。`begin` にStateのインスタンスを渡すと明示的なフロー、Stateの型（サブクラス）を渡すとその型の状態ならどこでも選べるコマンドフローになります。`end` を省略（または `Return()`）すると、フローを始めた状態へ戻ります。
    - `Read`: ユーザーが読む＝ユーザーへの情報提示を行います。
    - `Write`: ユーザーが書く＝ユーザーからの情報入力を要求します。
    - `Choice`: 選択肢を提示します。
    - `LinearCombine`: 複数の対話を一続きのシーケンスとして実行します。
- **Branch (分岐)**: `Branch(check, candidates)` をフローの `end` に置くと、`check(data)` が返したStateへ進みます。返り値は `candidates` のどれか（`Return()` も可）でなければエラーになります。
- **DataContext**: 状態間で共有されるデータコンテキストです。`data_update`（書き込み）と `context_build`（読み出し・構築）を通じて、型安全にデータを扱えます。

## 4. アーキテクチャ
プロジェクトは以下のレイヤーで構成されています。

1.  **Core (`base.py`)**: State・MiniFlow（`Read`, `Write`, `Choice`, `Combine`, `LinearCombine`）とデータ管理ロジックを保持します。MiniFlowは描画方法を持たない純粋なデータです。Runner基底クラス（`ApplicationRunnerBase`）がステートマシンのループを回し、各MiniFlowを種類ごとの描画メソッド（`show_read`, `show_write`, ...）に振り分けます。特定のプラットフォームには依存しません。
    - `runner.describe()`: 状態・明示的なフロー・Branchの分岐先・状態ごとのコマンドを文字列で一覧にします。
    - `runner.validate()`: 実行せずにグラフを検査し、問題のリストを返します（Startから始まるフローが無い、行き止まりの状態、Startから到達できない状態、行き先の無いBranch候補、どの状態にも当てはまらないコマンド）。コマンドもその型の状態からの出口として数えます。`run()` は最初に `validate()` を呼び、問題があれば警告を出して（止めずに）実行します。
2.  **Backends (`gui.py`, `cui.py`, `scripted.py`)**: Runner（`GuiRunner`, `CuiRunner`, `ScriptedRunner`）だけを提供し、描画メソッドを具体的なUI部品（QWidgetやprint/input）で実装します。`Combine`の子をまとめて表示する処理もRunnerが担当します。
    - `ScriptedRunner(data, answers)`: 画面を持たないRunnerです。`answers` を先頭から順に使い（Writeには入力文字列、Choiceには選択肢の値、選択にはフロー名/コマンド名）、表示された内容を `transcript` に記録します。答えが足りなくなると `ScriptExhausted` を送出します。テスト（`tests/`）で使っています。
3.  **Runtime選択 (`runtime.py`)**: `runtime.run(build_app, data)` がRunnerを選んで実行します。優先順位は 引数 `backend` > コマンドライン `--cui` / `--gui` > 環境変数 `FLOW_UI_BACKEND`（`cui` / `gui`） > 自動判定（PySide6が読み込めて画面がある場合はGUI、Linuxでは `DISPLAY` か `WAYLAND_DISPLAY` が必要。それ以外はCUI）。PySide6はGUIを選んだときだけ読み込みます。
4.  **App Logic (`main.py`, `login_example.py`)**: 開発者が`base`のクラスだけでフローを記述し、`build_app(runner)` でRunnerにフローを登録します。アプリのコードは `cui` / `gui` を直接importしないので、同一のロジックを異なる環境で動作させることができます。

```bash
FLOW_UI_BACKEND=cui uv run python login_example.py
uv run python -m unittest discover -s tests -t .
```
