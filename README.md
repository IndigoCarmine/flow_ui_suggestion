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

start, home, end = base.Start(), LoggedIn("home"), base.End()
data = LoginData()

def check(data):
    return home if is_exist_user(data) else None  # None = null

# 明示的なフロー: startから始まり、Branchで home に進む。
# checkがNoneを返したら .q(...) で「?」: メッセージを出して開始点へ戻る（入力も無かったことになる）
# kind で「どんな値が欲しいか」だけを書く（Password なら伏せ字入力、などはRuntimeが決める）
login = base.LinearCombine(
    [
        base.Write("username", name="Username").data_update("username"),  # 明示的なフローの既定は「!」
        base.Write("password", name="Password", kind=base.Password()).data_update("password"),
    ],
    name="login",
).begin_end(start, base.Branch(check, [home]).q("パスワードが違います"))

# コマンドフロー: 型(LoggedIn)から始まり、LoggedInのどの状態からでも選べる。
# endを省略すると、実行前の状態へ戻る。既定は「?」（空の入力・:q・Escで抜ける）
profile = base.Read(name="profile").context_build("user: {username}").begin(LoggedIn)
edit_name = (
    base.Write("new name", name="EditName").data_update("display_name")
    .begin(LoggedIn).q("名前は変更していません")
)
age = base.Write("age", kind=base.Number(min=0)).data_update("age").opt()  # 空ならNoneのまま続ける
logout = base.Read("logged out", name="logout").begin_end(LoggedIn, start)
quit_app = base.Read("bye", name="quit").begin_end(LoggedIn, end)

def build_app(runner):
    for flow in [login, profile, edit_name, logout, quit_app]:
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

- **State (状態)**: アプリケーションの特定の瞬間を表すチェックポイントです（Start, Endなど）。名前付きのStateは（型, 名前）で比較されるので、`State("home")` を2回書いても同じ状態です。`Start()` と `End()` は常に同じ1つのインスタンスで、表示名は "Start" / "End" に固定です（`Start("x")` の名前は無視されます）。
- **MiniFlow (インタラクション)**: 状態間の遷移（エッジ）であり、ユーザーとの対話を定義します。`begin` にStateのインスタンスを渡すと明示的なフロー、Stateの型（サブクラス）を渡すとその型の状態ならどこでも選べるコマンドフローになります。`end` を省略（または `Return()`）すると、フローを始めた状態へ戻ります。
    - `Read`: ユーザーが読む＝ユーザーへの情報提示を行います。`Read("表示する文", name=...)`
    - `Write`: ユーザーが書く＝ユーザーからの情報入力を要求します。`Write("質問", name=..., kind=..., validate=...)`
    - `Choice`: 選択肢を提示します。`Choice(["a", "b"], name=...)`
    - `Combine`: 複数の対話を同時に（GUIでは1画面に）提示します。`Combine([...])`
    - `LinearCombine`: 複数の対話を一続きのシーケンスとして実行します。`LinearCombine([...])`
    - `Combine` / `LinearCombine` の子にはどのステップ（入れ子のCombineも）でも置けます。
    - 最初の位置引数は内容（文・選択肢・子のリスト）です。`name` を省略すると文が名前になります。旧来の `Read(begin, end, "文", "name")` の形（最初の引数がState・Stateの型・None）もそのまま使えます。
    - ステップは純粋なデータで、実行中の進行状態（完了したか等）はRunnerが持ちます。同じステップを何度実行しても構いません。
- **入力の種類 (kind)**: `Write` にはウィジェットではなく「どんな値が欲しいか」を書きます。`data_update` には変換済みの値が渡ります。

    | kind | 値 | CUI | GUI |
    |---|---|---|---|
    | `Text()`（既定） | str | `input` | QLineEdit |
    | `Password()` | str | `getpass`（stdinが端末でないときは `input`） | QLineEdit（伏せ字） |
    | `Number(min=0, max=150)` / `Number(decimals=1)` | int / float | 範囲を表示して入力 | QLineEdit（数字だけ受け付ける。空にできる） |
    | `YesNo()` | bool | `[y/n]` | QCheckBox |

    空の入力（空白だけを含む）は値ではなく **null** です（下の「nullの扱い」）。`Text(required=True)` は `.must()` と同じ意味です。

- **入力の検証 (validate)**: `Write(..., validate=f)`。`f(value)` または `f(data, value)` がエラーメッセージ（またはNone）を返します。kindの検査（数値の範囲）の後に呼ばれ、空の入力（null）では呼ばれません。拒否されるとRuntimeがメッセージを見せて聞き直します（CUIは再表示、GUIは画面を保ったまま入力欄の下に表示、ScriptedRunnerはメッセージ付きの `base.InvalidInput` を送出）。拒否された値は `data_update` に渡りません。
- **nullの扱い（`?` / `!` / `opt`）**: 「ユーザーが値をくれなかった」ことを **null** と呼び、各ステップに短いメソッドで書きます（Rustの `?`、Kotlinの `!!` から。Pythonには後置の `?` `!` が無いため）。
    null になるのは: キャンセル（CUIの `:q` / Ctrl-D、GUIのEsc / Cancel、ScriptedRunnerの `base.CANCEL`）、空の入力（Text・Password・Number・YesNoの文字入力、Choiceの空入力）、`Branch` の `check` がNoneを返したとき。

    | 書き方 | 記号 | nullのとき |
    |---|---|---|
    | `.q()` / `.q("メッセージ")` | `?` | 実行中のトップレベルのフローを抜けて、フローを始めた状態へ戻る。**何も起きなかったことになる**（dataはフロー開始時に戻る）。メッセージがあれば全てのRuntimeが通知として表示 |
    | `.must()` | `!` | nullを許さない。空なら「a value is required」で聞き直し、キャンセルはヒントを出して断る（`Text(required=True)` と同じ） |
    | `.opt()` | `opt` | nullを受け入れる。`data_update` にNoneを渡して続ける |

    - どのステップ（`Read`, `Write`, `Choice`, `Combine`, `LinearCombine`, `Branch`）にも付けられ、自分自身を返すので `.data_update(...).opt()` のように繋げられます。
    - 印の無いステップは、一番近い印の付いた `Combine` / `LinearCombine` に従います。トップレベルの既定は、コマンドフローなら `?`、それ以外は `!` です。
    - `Branch(check, [home]).q("パスワードが違います")`: `check` がNoneを返すと通知を出して開始点へ戻ります。印の無いBranchがNoneを返すのは、これまで通り分かりやすいエラーです（`.opt()` なら通知もロールバックも無しで開始点へ戻る）。候補に `Return()` を入れる書き方もそのまま使えます。
    - **ロールバック**: Runnerはフローを始めるときに `copy.deepcopy(data)` を取り、`?` で抜けたらその内容を **同じdataオブジェクトに** 書き戻します（dict、`slots=True` を含むdataclass、普通のオブジェクト、list）。アプリが持っているdataの参照はそのまま使えます（中の値はコピーに置き換わる）。CUIでもGUIでも、抜けたフローで入力済みの欄は残りません。コピーできないdata（ロックなどを持つ）では警告を出し、ロールバックしません。
    - 通知: CUIは `[!] メッセージ` を表示、GUIは次の画面の上部とステータスバーに表示、ScriptedRunnerは `("notice", フロー名, メッセージ)` を `transcript` に記録します。
    - CUI: `?` のステップで初めて入力を求めるときに1回だけヒントを表示。`opt` の入力欄には `(optional)` と表示。GUI: `?` の画面にはCancelボタン、`opt` の画面にはSkipボタン（どちらもEscと同じ）、`!` の画面ではEscはステータスバーにヒント。`opt` の入力欄はプレースホルダに `optional`。
- **終了**: `run()` は最後の状態を返します（`runner.result` にも残ります）。`End()` に着いたら `End()`、ユーザーがアプリをやめたら `base.QUIT`（そのときの状態は `current_state`）。終了時のコールバックは要りません。GUIはウィンドウを閉じると、CUIは Ctrl-C、選択プロンプトや `!` のステップでのEOFで、短いメッセージを出してトレースバック無しに `run()` を抜けます（EOFが2回続いた場合も。パイプ入力が尽きたときに同じフローを繰り返さないため）。ScriptedRunnerは答え `base.QUIT`。`runtime.run()` はこれまで通りRunnerを返します。
- **グローバルコマンド**: `begin(base.State)`（基底クラス）のコマンドは `End` 以外の全ての状態（`Start` を含む）で選べます。例: `base.Read("bye", name="quit").begin_end(base.State, base.End())`。ただし `Start` にコマンドがあると、Startのフローは自動実行されず選択になります。
- **コマンドの別名 (command)**: `Read(..., name="edit-name", command="e")` のように短い名前を付けられます（既定は `name`）。CUIは別名・名前・一意な前方一致（`pro` → profile）を受け付け、選択肢には別名を表示します。ScriptedRunnerは名前か別名。GUIのボタンは名前（別名はツールチップ）。
- **環境適応レイアウト**: レイアウトはアプリでは指定しません。GUIは各画面を「ラベル｜入力欄」の行で並べ、ウィンドウ幅が720px以上で行が2つ以上なら2列に組み替えます（リサイズで切り替わる）。Enterは次の欄へ、最後の欄（またはNextボタン）では「次へ」。CUIはReadの文を端末幅で折り返し、Combineの入力欄に `[1]` `[2]` と番号を付けます。
- **Branch (分岐)**: `Branch(check, candidates)` をフローの `end` に置くと、`check(data)` が返したStateへ進みます。返り値は `candidates` のどれか（`Return()` も可）でなければエラーになります。
- **DataContext**: 状態間で共有されるデータコンテキストです。`data_update`（書き込み）と `context_build`（読み出し・構築）を通じて、型安全にデータを扱えます。`context_build` の文字列は `{name}` を含めばテンプレート、含まなければ「dataの属性/キー名ならその値、そうでなければそのままの文」です。

## 4. アーキテクチャ
プロジェクトは以下のレイヤーで構成されています。

1.  **Core (`base.py`)**: State・MiniFlow（`Read`, `Write`, `Choice`, `Combine`, `LinearCombine`）とデータ管理ロジックを保持します。MiniFlowは描画方法を持たない純粋なデータです。Runner基底クラス（`ApplicationRunnerBase`）がステートマシンのループを回し、各MiniFlowを種類ごとの描画メソッド（`show_read`, `show_write`, ...）に振り分けます。nullの扱い（実際に効く扱いの計算、スナップショットとロールバック）も基底クラスが持ち、Backendは `show_notice` で通知を表示するだけです。特定のプラットフォームには依存しません。
    - `runner.describe()`: 状態・明示的なフロー・Branchの分岐先・状態ごとのコマンド（別名があれば `別名 (名前)`）、各フローとその中の各ステップの実際に効くnullの扱い（`[?]`, `[? 'メッセージ']`, `[!]`, `[opt]`。Branchは `(None: ? 'メッセージ')`）、Writeのkindを文字列で一覧にします。
    - `runner.validate()`: 実行せずにグラフを検査し、問題のリストを返します（Startから始まるフローが無い、行き止まりの状態、Startから到達できない状態、行き先の無いBranch候補、どの状態にも当てはまらないコマンド、同じ状態で同じ別名のコマンド、`Read` に付けた `.must()`（値を返さないので意味が無い）、`required=True` なのに `.q()` / `.opt()` を付けたWrite）。コマンドもその型の状態からの出口として数えます。`run()` は最初に `validate()` を呼び、問題があれば警告を出して（止めずに）実行します。
2.  **Backends (`gui.py`, `cui.py`, `scripted.py`)**: Runner（`GuiRunner`, `CuiRunner`, `ScriptedRunner`）だけを提供し、描画メソッドを具体的なUI部品（QWidgetやprint/input）で実装します。`Combine`の子をまとめて表示する処理と、kindに合ったウィジェットの選択・入力の変換と再入力もRunnerが担当します。
    - `ScriptedRunner(data, answers)`: 画面を持たないRunnerです。`answers` を先頭から順に使い（Writeには入力文字列または `30` / `True` のような値、Choiceには選択肢の値、選択にはフロー名/コマンド名。`base.CANCEL`・`None`・`""` はnull）、表示された内容を `transcript` に記録します。Writeの答えはkindとvalidateで変換・検査され、拒否されると `base.InvalidInput` を送出します。答えが足りなくなると `ScriptExhausted` を送出します。`on_reject="next"` にすると、拒否された答えは `("rejected", 名前, メッセージ)` として記録し、次の答えを使います（聞き直しの経路をテストできる。既定は `"raise"`）。テスト（`tests/`）で使っています。
3.  **Runtime選択 (`runtime.py`)**: `runtime.run(build_app, data)` がRunnerを選んで実行します。優先順位は 引数 `backend` > コマンドライン `--cui` / `--gui` > 環境変数 `FLOW_UI_BACKEND`（`cui` / `gui`） > 自動判定（PySide6が読み込めて画面がある場合はGUI、Linuxでは `DISPLAY` か `WAYLAND_DISPLAY` が必要。それ以外はCUI。画面はあるのにPySide6が読み込めなかったときは、理由を標準エラー出力に1行出してCUIにします）。PySide6はGUIを選んだときだけ読み込みます。
4.  **App Logic (`main.py`, `login_example.py`)**: 開発者が`base`のクラスだけでフローを記述し、`build_app(runner)` でRunnerにフローを登録します。アプリのコードは `cui` / `gui` を直接importしないので、同一のロジックを異なる環境で動作させることができます。

```bash
FLOW_UI_BACKEND=cui uv run python login_example.py
uv run python -m unittest discover -s tests -t .
```
