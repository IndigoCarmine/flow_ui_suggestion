# Flow UI Framework (仮称) 仕様書

## 1. 概要
Flow UI Frameworkは、アプリケーションの振る舞いを「状態（State）」と「遷移（Interaction）」からなるグラフ（Graph）として定義するUIフレームワークである。開発者はユーザーがどのような情報を得て、どのような操作を行うかという「論理的なフロー」の記述に専念し、具体的なUIの構成やレンダリングは実行環境（Runtime）が完全に制御する。

これにより、同一のコードベースでGUI、CUI、あるいは異なる画面サイズのデバイスに対して、環境に最適化されたユーザー体験を提供することを目指す。

## 2. 設計思想
- **論理と表現の分離**: コードでは「何を表示し、何を入力させるか」のみを定義し、位置やサイズ、コントロールの種類といった「どう表示するか」はRuntimeが決定する。
- **グラフベースの制御フロー**: ユーザー体験を一連の連続した状態遷移として捉え、循環や分岐を含む柔軟なフローを構築可能とする。
- **環境適応性**: Runtimeは、実行環境の制約（解像度、入力デバイス、文字ベースか画像ベースか等）に基づき、最適なレイアウトを動的に生成する。

## 3. 基本コンポーネント

### 3.1 State（状態）
アプリケーションの特定の時点を表すノード。
- **Start**: アプリケーションの開始点。
- **End**: アプリケーションの終了点。
- **Custom State**: ユーザー定義の状態。
- **同一性**: 名前付きのStateは（型, 名前）で等価・ハッシュを決める（`State("home") == State("home")`、`LoggedIn("home") != State("home")`）。名前の無い `State()` は自分自身とだけ等しい。`Start` と `End` はそれぞれ1つだけのインスタンスで（`Start() is Start("x")`）、表示名は "Start" / "End" に固定（引数の名前は無視し、共有インスタンスの名前を書き換えない）。`Return()` はStateではなく、どのStateとも等しくない。

### 3.2 MiniFlow（インターフェース/遷移）
あるStateから別のStateへの遷移を定義し、その過程で発生するユーザーインタラクションを保持する。
- **生成**: 最初の位置引数は内容（Read/Writeは文、Choiceは選択肢、Combine/LinearCombineは子のリスト）で、`name` などはキーワード（例: `Write("年齢", name="Age")`）。最初の位置引数がState・Stateの型・Noneなら旧来の `(begin, end, 内容, name)` の形として扱う。`name` を省略すると文（無ければクラス名）を名前にする。
- **純粋なデータ**: MiniFlowは実行中の進行状態を持たない（完了待ちはRunnerが管理する）。同じMiniFlowを何度でも、複数のRunnerで使える。
- **属性**:
  - `name`: 遷移の識別子。
  - `begin_state`: 遷移の開始。`begin(state_or_type)` / `begin_end(begin, end)` でも設定できる。
  - `end_state`: 遷移の終了。State、`Branch`、`Return()`、または省略（`None`）。
- **2種類のフロー**:
  - **明示的なフロー**: `begin_state` が特定のStateインスタンス。その状態にいるときだけ候補になる。
  - **コマンドフロー**: `begin_state` がStateの型（サブクラス、例: `class LoggedIn(State)`）。現在の状態がその型のインスタンスであれば、どの状態からでも候補になる（シェルのコマンドのようなもの）。`End` 状態では提示しない。
- **終了の扱い**:
  - `end_state` を省略、または `Return()` の場合: フローを始めた状態（実行開始時の現在状態）へ戻る。戻るのは1段だけで、呼び出しスタックやコマンドの入れ子は持たない。
  - Stateを指定した場合: その状態へ進む（例: ログアウトは `begin_end(LoggedIn, start)`）。
- **nullの扱い**: 下の 3.3 を参照。
- **コマンドの別名**: `command="e"`（空白を含まない短い名前、既定は `name`）。CUIは別名・名前の完全一致、なければ別名・名前の一意な前方一致で選ぶ（複数当てはまれば候補を示して聞き直す）。ScriptedRunnerは名前か別名の完全一致。
- **グローバルコマンド**: `begin_state` に `State` そのものを渡すと、`End` 以外の全ての状態（`Start` を含む）で候補になる。
- **Branch（分岐）**: `Branch(check, candidates)`。`check(data)` がStateを返し、そこへ進む。分岐先は `candidates` として宣言するのでグラフを静的に列挙できる。返り値が候補のどれでもない場合（Stateの等価性で比較。`Return()` は候補に含めたときのみ可）は実行時エラーとする。ただし `check` がNoneを返し、Branchに `.q(...)` か `.opt()` が付いている場合は 3.3 に従う。

### 3.3 nullの扱い（`?` / `!` / `opt`）
「ユーザーが値をくれなかった」ことを **null** と呼ぶ。nullになるのは次の場合:
- キャンセル: CUIの `:q` 単独の入力またはEOF（Ctrl-D）、GUIのEsc / Cancel（Skip）ボタン、ScriptedRunnerの答え `base.CANCEL`。
- 空の入力: `Kind.is_empty(raw)`（既定: Noneか、空・空白だけの文字列）。Text・Password・Number・YesNoの文字入力。Choiceは空の入力（CUI）・`None`/`""`（ScriptedRunner。選択肢そのものでない場合）・`opt` のときだけ現れる「(none)」項目（GUI）。GUIのYesNo（チェックボックス）はキャンセル以外でnullにならない。
- `Branch` の `check` がNoneを返したとき。

nullのときの振る舞い（null policy, `base.NullPolicy`）はステップに流れるような（自分を返す）メソッドで書く。PythonにはRustの `?` やKotlinの `!!` のような後置演算子が無いため、短いメソッド名にした。
- `.q(message=None)`（`?`）: 実行中のトップレベルのフローを抜け、フローを始めた状態へ戻る。`end_state`（Branchの `check`）は評価しない。**dataはフロー開始時のスナップショットに戻す**（何も起きなかったことにする）。`message` があれば、戻った後に `show_notice(message)` で表示する。
- `.must()`（`!`）: nullを許さない。空の入力は「a value is required」を示して聞き直し、キャンセルはヒントを出して断る（ScriptedRunnerは空の答えを拒否として扱い、`CANCEL` は `ValueError`）。`Text(required=True)`（`Password` も）は、そのWriteに `.must()` を付けたのと同じ。
- `.opt()`: nullを受け入れ、`data_update` にNoneを渡して続ける（GUIの画面全体のSkipでは、その画面の全ての入力ステップにNone）。Readでのキャンセルは単に先へ進む。

**実際に効く扱い**（`runner.policy_for(step, inherited)`）: ステップ自身の印 → 一番近い印の付いた（または実際に効く扱いを持つ）外側の `Combine` / `LinearCombine` → トップレベルの既定（コマンドフローなら `?`、明示的なフローは `!`）。Runnerは表示中のステップの扱いを `current_policy` として持つ（`render()` が `entering(step)` で積む。1画面にまとめて表示するBackendは子ごとに `policy_for` / `entering` を使う）。Backendはnullを受けたら `null_given(step)` を呼ぶ: `?` なら `Cancelled` を送出、`opt` ならTrue（Noneを保存）、`!` ならFalse（聞き直し・断る）。

**Branch**: Branchの印はBranch自身のものだけで、フローからは継承しない。`check` がNoneを返したとき、`.q(message)` なら上の `?` と同じ（ロールバックと通知）、`.opt()` ならロールバックも通知も無しでフローを始めた状態へ戻る、印が無いか `.must()` なら候補外としてエラー。

**ロールバック**: 基底の `run()` はフローを選んだ直後（`render` の前）に `copy.deepcopy(data)` を取り、`?` で抜けたら `restore_in_place(data, snapshot)` で **同じオブジェクトのまま** 中身を書き戻す。対応: `MutableMapping`（clear + update）、`MutableSequence`（全体を置換）、`__slots__`（`dataclass(slots=True)` を含む。継承した全てのslotを書き戻し、スナップショットに無いslotは消す）、`__dict__`（clear + update）。それ以外（Noneや不変の値）は何もしない。書き戻した値はスナップショット側のコピーなので、トップレベルのdataオブジェクトの同一性だけが保たれる（中のlistなどは別オブジェクトになる）。`deepcopy` に失敗した場合は `warn()` で警告し、そのフローはロールバックしない。これによりCUIとGUIは同じ結果になる（以前はCUIだけが抜ける前に入力済みの欄を残していた）。

**通知**（`show_notice(text)`、Backendが実装する抽象メソッド）: CUIは `[!] text` を表示。GUIは次に表示する画面の上部（objectName `notice` のラベル）とステータスバーに表示。ScriptedRunnerは `("notice", フロー名, text)` を `transcript` に記録する。抜けたことは `exited(flow, step)` フックでも通知される（CUIは `(cancelled 'フロー名')` を表示、ScriptedRunnerは `("cancel", フロー名, ステップ名)` を記録。Branchのときステップ名は `"Branch"`）。

**各Runtimeの表示**:
- CUI: `?` のステップで初めて入力を求めるときに1回だけ「`:q`、空のまま、Ctrl-Dでキャンセル」のヒントを表示。`opt` の入力欄は `(optional)` を付ける。`!` での `:q` は `'フロー名' cannot be cancelled here` を表示して聞き直す。`:q` をフローの外（選択プロンプト）で使うと「nothing to cancel here」。
- GUI: 画面の扱いが `?` ならCancelボタン、`opt` ならSkipボタン（どちらもEscと同じ）。`!` ならボタンは無く、Escはステータスバーにヒント。入力欄ごとの扱いはNextを押したときに判定し、空の `?` 欄があればフローを抜け、空の `!` 欄には「a value is required」を表示する。
- 自動実行されるフロー（明示的なフローが1つでコマンド無し）に `?` を付けると、戻った状態で再び自動実行される。

## 4. プリミティブ・インタラクション
MiniFlowの具体的な実装として、以下の基本インタラクションを定義する。

- **Read (出力)**: ユーザーに情報を提示する（例：テキスト表示、画像表示）。
- **Write (入力)**: ユーザーから情報を受け取る（例：テキスト入力、数値入力）。
- **Choice (選択)**: 提示された選択肢から一つを選択させる。
- **Combine (複合)**: 複数のインタラクションを一つのMiniFlowとしてまとめ、同時に（`Combine`）、あるいは順次（`LinearCombine`）提示する。子にはどのインタラクション（入れ子のCombineを含む）も置ける。Runnerが扱えない子は黙って飛ばさず、エラーにする。

### 4.1 入力の種類（kind）
`Write(..., kind=...)` は「どんな値が欲しいか」という意図であり、ウィジェットの指定ではない。Runnerが入力方法を決め、`data_update` には変換済みの値を渡す。
- `Text(required=False)`（既定）: str。空・空白だけの入力はnull（3.3）。`required=True` は `.must()` の別名。
- `Password(required=False)`: 入力中に表示しないstr（CUIは `getpass`、ただしstdinが端末でなければ通常の入力。GUIは伏せ字の入力欄）。
- `Number(min=None, max=None, decimals=0)`: `decimals=0` ならint、それ以外はfloat。範囲外・数でない入力を拒否する。空の入力はnull（`.opt()` ならNone）。GUIは空にできるよう、スピンボックスではなく数字だけを受け付けるQLineEdit（範囲はプレースホルダに表示）。
- `YesNo()`: bool。文字列なら y/yes/true/1 と n/no/false/0、空はnull（GUIはチェックボックス）。
- 独自のkindは `Kind` を継承し、`convert(raw)`（失敗時は `ValueError(メッセージ)`）と `check(value)`（エラーメッセージかNone）を実装する。何をnullとみなすかは `is_empty(raw)` で変えられる。

### 4.2 入力の検証（validate）
- `Write(..., validate=f)`: `f(value)` または `f(data, value)` がエラーメッセージ（またはNone）を返す。
- 順序: nullの判定（`is_empty`。nullなら 3.3 に従い、以降は行わない） → kindの変換 → kindの検査 → `validate`。`Write.accept(raw, data)` が値を返すか `InvalidInput(メッセージ)` を送出する（空の値を直接渡すと「a value is required」）。
- 拒否された場合、Runnerはメッセージを示して聞き直す（CUIはメッセージを表示して再入力、GUIは画面を保ったまま入力欄の下に表示、ScriptedRunnerはメッセージ付きの `InvalidInput` を送出）。拒否された値は `data_update` に渡さない。GUIのCombineでは、全ての入力が受け入れられたときだけまとめて `data_update` する。

## 5. Runtime（実行時エンジン）の役割

Runtimeは、定義されたグラフを解釈し、実際のプラットフォーム（PySide6, Web, Terminal等）へのマッピングを行う。

1. **状態管理**: 現在のStateを追跡し、次に遷移可能なMiniFlowを特定する。
2. **フロー選択**: 複数の遷移先候補がある場合、ユーザーに選択させるインターフェースを自動生成する。
3. **UI生成とレイアウト**:
   - 各MiniFlowが要求するインタラクションに基づき、最適なウィジェット（ボタン、ラベル、入力フィールド等）を選択する。
   - 画面の物理的な制約に合わせて、ウィジェットの配置（Vertical, Horizontal, Grid等）を決定する。アプリはレイアウトを指定しない。
   - GUI（現在の実装）: 画面は「ラベル｜入力欄」の行（エラーは入力欄の下）。幅が `gui.TWO_COLUMN_WIDTH`（720px）以上で行が2つ以上なら2列に並べ、`resizeEvent` で1列/2列を切り替える。Readの文は全幅。Enterは次の入力欄へ移り、最後の欄とNextボタンでは「次へ」。
   - CUI（現在の実装）: Readの文を `shutil.get_terminal_size()` の幅で折り返す（改行・空行は保つ）。Combineの入力欄（Write・Choice）に `[1]` から番号を付ける。
4. **イベントループ**: ユーザー操作を監視し、インタラクションの完了を検知して状態遷移を実行する。

## 6. 制御フローの実行モデル
1. `Start` 状態から開始する。
2. 現在の状態について、明示的なフロー（`begin_state` がこの状態）とコマンドフロー（`begin_state` がこの状態の型）をそれぞれ集める。
   - 明示的なフローが1つでコマンドが無い場合：その `MiniFlow` を自動で実行する。
   - それ以外で候補がある場合：Runnerの `select_flow(flows, commands)` でユーザーに選ばせる。コマンドは必ずユーザーが選ぶ（自動実行すると同じコマンドが繰り返されるため）。BackendはコマンドをCUIならプロンプト、GUIなら別のボタン列のように通常のフローと区別して表示してよい。
   - 候補が無い場合：停止する。
3. `MiniFlow` のインタラクション（表示・入力）が完了するまで待機する（入力は受け入れられるまで聞き直す）。
4. インタラクション完了後、`end_state` から次の状態を決める（`Branch` なら `check` を評価し、`None`/`Return()` ならフローを始めた状態に戻る。`check` がNoneを返したときは 3.3）。途中で `?` のnullが起きたら、dataをフロー開始時に戻し、フローを始めた状態に戻って通知を出す。
5. 現在の状態が `End` に達するまで 2-4 を繰り返す。
6. `run()` は最後の状態を返し、`runner.result` にも保持する: `End()`、ユーザーが終了したら `base.QUIT`（`Quit()` の唯一のインスタンス。Stateではない。終了時の状態は `current_state` に残る）、候補が無く停止したらその状態。

### 6.1 アプリの終了
- Runnerはユーザーの終了を `base.UserQuit` として送出し、`run()` がそれを受けて `QUIT` を返す。アプリ側の終了コールバックは設けない。
- GUI: 入力待ちの間にウィンドウが閉じられたら終了。
- CUI: Ctrl-C（どこでも）、選択プロンプトや `!` のステップでのEOFで、短いメッセージを出して終了（トレースバックを出さない）。`?` / `opt` のステップでのEOFはnull（キャンセル）だが、入力の無いままEOFが続いた2回目は終了とする（パイプ入力が尽きたときの無限ループ防止）。
- ScriptedRunner: 答え `base.QUIT`。

- `context_build` の文字列: `{...}` を含めばdataの属性/キーで埋めるテンプレート（欠けていれば `message`）。含まなければ、dataの属性/キー名ならその値、そうでなければそのままの文として表示する。

## 7. 静的検査
Runnerは実行前にグラフを検査できる。
- `describe()`: 状態、明示的なフロー、Branchの候補、状態ごとに使えるコマンド（別名は `別名 (名前)`）を文字列で返す。各フローの行の末尾に実際に効くnullの扱い（`[?]`, `[? 'メッセージ']`, `[!]`, `[opt]`）、印の付いたBranchには `(None: ? 'メッセージ')` を付ける。Combine/LinearCombineの下には子のステップを入れ子で並べ、それぞれの扱いとWriteのkind（例: `Write 'Age': Number(min=0, max=150, decimals=0)  [opt]`）を示す。Write単独のフローはそのkindを示す。
- `validate()`: 問題の一覧（文字列のリスト）を返す。検出するもの: `Start` から始まるフローが無い／出口の無い状態（`End` 以外。その型に当てはまるコマンドも出口に数える）／`Start` から到達できない状態／行き先の無い、またはState・`Return()` 以外のBranch候補／どの状態の型にも当てはまらないコマンド／同じ状態で同じ別名（`command`）になるコマンド／`.must()` を付けた `Read`（値を返さないので、キャンセルを断る以外の意味が無い）／`required=True` なのに `.q()` / `.opt()` を付けたWrite（印が優先される）。`?` は全てのフローに戻り先（フローを始めた状態）があるので検査しない。
- `run()` は開始時に `validate()` を呼び、問題があれば `warn()`（既定では標準エラー出力）で警告して実行を続ける。

## 8. Runtimeの選択
- `runtime.run(build_app, data, backend=None)` / `runtime.make_runner(data, backend=None)`。
- 優先順位: 引数 `backend` > コマンドライン `--cui` / `--gui` > 環境変数 `FLOW_UI_BACKEND` > 自動判定。
- 自動判定: 画面があり（Linux等では `DISPLAY` か `WAYLAND_DISPLAY`、macOS/Windowsは常にあるとみなす）、PySide6が読み込めればGUI、そうでなければCUI。画面があるのにPySide6の読み込みに失敗した場合は、理由を標準エラー出力に1行出す。GUIモジュールは選ばれたときだけ読み込む。
- アプリのコードは `base` と `runtime` だけを使い、Backendを直接importしない。
- `scripted.ScriptedRunner(data, answers)` は画面を持たないBackendで、決められた答えで実行し、表示内容を `transcript` に記録する（テスト用）。答えが尽きると `ScriptExhausted`。Writeの答えはkind・validateで変換・検査し、拒否されれば `InvalidInput`（Choiceの範囲外は `ValueError`）。`on_reject="next"` なら拒否を `("rejected", 名前, メッセージ)` として `transcript` に記録し、次の答えを使う。`base.CANCEL`・`None`・`""` はnull（3.3）、`base.QUIT` は終了の操作を表す。通知は `("notice", フロー名, 文)`。
