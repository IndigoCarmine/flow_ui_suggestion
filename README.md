# Flow UI Framework (System Proposal)

## 1. プロジェクトの概要
Flow UI Frameworkは、アプリケーションのUIをプログラムするのではなく、Userが何をするのかについてプログラムできれば、LLMのコード生成で都合が良いのではないかと考えから作成しました。実用というより提案のためのコードです。

従来のUI開発では、開発者が目標とするUserの作業を考えながら、画面のレイアウトとデータ構造を構築するという流れでした。そこで、各ステート間での一連作業（MiniFlow）を組み立て、それをNodeGraphで管理する形のみを記述させるようにしました。具体的な描画やインタラクションの詳細は、実行環境（Runtime）に完全に委譲されます。

今のところUserが何をするかを基準にClass名を決めています。
例えば以下のように記述できるべきです。

```python
data = UseData()
check_state = State("check")
login_state = State("login")
login = Combine(Write("write your username",data.name), Write("write your password",data.password).begin_end(Start(), check_state)

def check()->State:
    if is_exist_user(data):
        return login_state
    else:
        return Start()
auth = Wait(lambda: check_user)

service = Read("seacret infomation").begin_end(login_state, login_state)
exit = Read("app stopping").begin_end(login_state,End())

runner = ApplicationRunner()
runner.add_miniflow(login)
runner.add_miniflow(auth)
runner.add_miniflow(service)
runner.add_miniflow(exit)

runner.run()
```





## 2. 設計思想：Logic-First, Rendering-Last
本フレームワークの根底には、以下の思想があります。

- **グラフによるフロー定義**: アプリケーション全体をステートマシンとして捉え、ノード（状態）とエッジ（ユーザーとの対話）で構造化します。これにより、複雑な分岐やループを直感的に記述できます。
- **レンダリングの完全委譲**: 開発者は「名前を入力させる」「情報を表示する」といった**意図（Intent）**のみを定義します。それをGUI（PySide6）のウィンドウで表示するか、CUI（Terminal）の対話として実行するかはRuntimeの種類で決定します。
- **環境適応型UI**: Windowサイズや入出力デバイスの制約に応じて、Runtimeが最適なレイアウトを動的に生成します。

## 3. コアコンポーネント

- **State (状態)**: アプリケーションの特定の瞬間を表すチェックポイントです（Start, Endなど）。
- **MiniFlow (インタラクション)**: 状態間の遷移（エッジ）であり、ユーザーとの対話を定義します。
    - `Read`: ユーザーからの情報入力を要求します。
    - `Write`: ユーザーへの情報提示を行います。
    - `Choice`: 選択肢を提示します。
    - `LinearCombine`: 複数の対話を一続きのシーケンスとして実行します。
- **DataContext**: 状態間で共有されるデータコンテキストです。`data_update`（書き込み）と `context_build`（読み出し・構築）を通じて、型安全にデータを扱えます。

## 4. アーキテクチャ
プロジェクトは以下の3つのレイヤーで構成されています。

1.  **Core (`base.py`)**: グラフ構造、インタラクションの抽象定義、データ管理ロジックを保持します。特定のプラットフォームには依存しません。
2.  **Backends (`gui.py`, `cui.py`)**: 抽象的なインタラクションを、具体的なUI部品（QWidgetやprint/input）に変換します。
3.  **App Logic (`main.py`)**: 開発者がフローを記述するエントリポイントです。バックエンドのインポートを切り替えるだけで、同一のロジックを異なる環境で動作させることができます。
