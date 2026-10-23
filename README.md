# Flow UI Framework (System Proposal)
uvを使います
## 1. プロジェクトの概要
Flow UI Frameworkは、アプリケーションのUIをプログラムするのではなく、Userが何をするのかについてプログラムできれば、LLMのコード生成で都合が良いのではないかと考えから作成しました。実用というより提案のためのコードです。

従来のUI開発では、開発者が目標とするUserの作業を考えながら、画面のレイアウトとデータ構造を構築するという流れでした。そこで、各ステート間での一連作業（MiniFlow）を組み立て、それをNodeGraphで管理する形のみを記述させるようにしました。具体的な描画やインタラクションの詳細は、実行環境（Runtime）に完全に委譲されます。

今のところUserが何をするかを基準にClass名を決めています。
例えば以下のように記述できます（実際に動くものは `login_example.py`。`uv run python login_example.py` でCUI、`uv run python login_example.py gui` でGUI）。

```python
import base, cui

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

runner = cui.CuiRunner(data)
for flow in [login, profile, logout, quit_app]:
    runner.add_miniflow(flow)
runner.run()
```

## 2. 設計思想：Logic-First, Rendering-Last
本フレームワークの根底には、以下の思想があります。

- **グラフによるフロー定義**: アプリケーション全体をステートマシンとして捉え、ノード（状態）とエッジ（ユーザーとの対話）で構造化します。これにより、複雑な分岐やループを直感的に記述できます。
- **レンダリングの完全委譲**: 開発者は「名前を入力させる」「情報を表示する」といった**意図（Intent）**のみを定義します。それをGUI（PySide6）のウィンドウで表示するか、CUI（Terminal）の対話として実行するかはRuntimeの種類で決定します。
- **環境適応型UI**: Windowサイズや入出力デバイスの制約に応じて、Runtimeが最適なレイアウトを動的に生成します。

## 3. コアコンポーネント

- **State (状態)**: アプリケーションの特定の瞬間を表すチェックポイントです（Start, Endなど）。
- **MiniFlow (インタラクション)**: 状態間の遷移（エッジ）であり、ユーザーとの対話を定義します。`begin` にStateのインスタンスを渡すと明示的なフロー、Stateの型（サブクラス）を渡すとその型の状態ならどこでも選べるコマンドフローになります。`end` を省略（または `Return()`）すると、フローを始めた状態へ戻ります。
    - `Read`: ユーザーが読む＝ユーザーへの情報提示を行います。
    - `Write`: ユーザーが書く＝ユーザーからの情報入力を要求します。
    - `Choice`: 選択肢を提示します。
    - `LinearCombine`: 複数の対話を一続きのシーケンスとして実行します。
- **Branch (分岐)**: `Branch(check, candidates)` をフローの `end` に置くと、`check(data)` が返したStateへ進みます。返り値は `candidates` のどれか（`Return()` も可）でなければエラーになります。
- **DataContext**: 状態間で共有されるデータコンテキストです。`data_update`（書き込み）と `context_build`（読み出し・構築）を通じて、型安全にデータを扱えます。

## 4. アーキテクチャ
プロジェクトは以下の3つのレイヤーで構成されています。

1.  **Core (`base.py`)**: State・MiniFlow（`Read`, `Write`, `Choice`, `Combine`, `LinearCombine`）とデータ管理ロジックを保持します。MiniFlowは描画方法を持たない純粋なデータです。Runner基底クラス（`ApplicationRunnerBase`）がステートマシンのループを回し、各MiniFlowを種類ごとの描画メソッド（`show_read`, `show_write`, ...）に振り分けます。特定のプラットフォームには依存しません。
2.  **Backends (`gui.py`, `cui.py`)**: Runner（`GuiRunner`, `CuiRunner`）だけを提供し、描画メソッドを具体的なUI部品（QWidgetやprint/input）で実装します。`Combine`の子をまとめて表示する処理もRunnerが担当します。
3.  **App Logic (`main.py`)**: 開発者が`base`のクラスだけでフローを記述するエントリポイントです。どのRunnerを生成するかを切り替えるだけで、同一のロジックを異なる環境で動作させることができます。
