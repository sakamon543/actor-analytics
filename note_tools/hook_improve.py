#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フック分析＋次バッチ自動生成（2段階処理版）
==========================================
3日サイクルの analyze 後に実行。

Phase 1: posts_db.json + hook_archive.json + 恋愛系フックスキル
         から「フック30本（1行目のみ）」を1回の呼び出しで生成
Phase 2: フック1本ずつ、恋愛系ポスト作成スキル本体に従って本文生成
         （30回シーケンシャル・並列はしない）

設計の核（必読）:
- フックを当てて、そのフックで恋愛系ポスト作成スキルを起動する仕組みを
  自動化したもの。リライトモードの自動版。
- アカウント情報総合管理.md は商品情報＋演者の事実だけの参照。テンプレ強制しない。
- evaluation_criteria は内部チェックのみ。本文に書き込まない。
- target_research はターゲット素材として参考に。セクション番号を本文に引用しない。
- 「読者をプレイヤー（当事者）として扱う」「同じ語彙の連発禁止」を最優先ルールとして明記。
- 蓄積は hook_archive.json（フック単位の投稿履歴）で行う＝再投稿の追跡。

使い方:
    python note_tools/hook_improve.py <演者名>
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))

SCHEDULE_TEMPLATE = [
    (11, 8), (13, 17), (14, 42),
    (18, 3), (19, 17), (19, 52),
    (20, 28), (21, 3), (22, 17), (22, 48),
]

# Phase 1（フック生成）で読み込むスキル本体＋素材プール
# 「変数選定の3段階フロー」（Step1 素材実例集 → Step2 観察ワード → Step3 新規生成）の
# Step1/2 を実行するために素材ファイル群を必ず渡す。AIの想像で変数を埋めるのは禁止。
HOOK_SKILL_FILES = [
    "skills/思考スキル_フック作成.md",
    "skills/パターン集_フック細分化v2.md",
    "materials/素材実例集_CSV由来.md",
    "materials/恋愛ダスト_分析用.csv",
]

# Phase 2（本文生成）で読み込むスキル本体（恋愛系特化）
BODY_SKILL_FILES = [
    "skills/スキル_恋愛ポスト作成AI.md",
    "skills/判断軸_恋愛ポスト作成.md",
    "skills/思考スキル_本文作成.md",
    "skills/思考スキル_統括_売れる教育ポスト.md",
    "skills/口調文体ルール_一般人感.md",
]


# ============== I/O ヘルパー ==============

def load_text(path, optional=False):
    if not os.path.exists(path):
        if optional:
            return ""
        raise FileNotFoundError(path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default if default is not None else {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def fookid(text):
    """フック1行目から安定ID生成。同一フックは同一IDになる。"""
    norm = re.sub(r'\s+', '', (text or ""))[:80]
    return "fookid_" + hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]


# ============== スケジュール ==============

def find_next_start_date(posts_db, prev_batch_path=None):
    tomorrow = datetime.now(tz=JST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    candidates = [tomorrow]

    latest_posted = None
    for p in posts_db.get("posts", {}).values():
        try:
            dt = datetime.fromisoformat(p["posted_at"]).astimezone(JST)
            if latest_posted is None or dt > latest_posted:
                latest_posted = dt
        except (ValueError, KeyError):
            continue
    if latest_posted:
        candidates.append((latest_posted + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))

    if prev_batch_path and os.path.exists(prev_batch_path):
        try:
            with open(prev_batch_path, encoding='utf-8') as f:
                prev = json.load(f)
            latest_scheduled = None
            for p in prev.get("posts", []):
                sa = p.get("scheduled_at")
                if not sa:
                    continue
                dt = datetime.fromisoformat(sa).astimezone(JST)
                if latest_scheduled is None or dt > latest_scheduled:
                    latest_scheduled = dt
            if latest_scheduled:
                candidates.append((latest_scheduled + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        except (json.JSONDecodeError, ValueError):
            pass

    return max(candidates)


def generate_schedule(start_date, days=3, per_day=10):
    slots = []
    for d in range(days):
        day = start_date + timedelta(days=d)
        for i, (h, m) in enumerate(SCHEDULE_TEMPLATE[:per_day]):
            dt = day.replace(hour=h, minute=m, second=0, microsecond=0)
            slots.append(dt.isoformat())
    return slots


# ============== 実績データ抽出 ==============

def extract_performance_data(posts_db, hook_archive, top_n=15, bottom_n=10):
    """
    実績データから「伸びたフック」「伸びなかったフック」「再現性確認済みフック」を抽出する。
    PDCAのインプット。
    """
    posts = posts_db.get("posts", {})
    items = []
    for key, p in posts.items():
        first_line = (p.get("text", "") or "").split("\n")[0]
        items.append({
            "hook": first_line,
            "views": p.get("views", 0),
            "posted_at": p.get("posted_at", ""),
        })
    items.sort(key=lambda x: x["views"], reverse=True)
    top_hooks = items[:top_n]
    bottom_hooks = items[-bottom_n:] if len(items) >= bottom_n else []

    # hook_archive から「2回以上投稿していて、平均が一定以上のフック」を抽出（再現性確認済み）
    proven_hooks = []
    for hid, entry in hook_archive.get("hooks", {}).items():
        history = [h for h in entry.get("history", []) if h.get("views") is not None]
        if len(history) >= 2:
            views_list = [h["views"] for h in history]
            avg = sum(views_list) / len(views_list)
            if avg >= 1500:
                proven_hooks.append({
                    "hook": entry["text"],
                    "rounds": len(history),
                    "avg_views": avg,
                    "structure": entry.get("structure_label", "unknown"),
                })
    proven_hooks.sort(key=lambda x: x["avg_views"], reverse=True)

    return top_hooks, bottom_hooks, proven_hooks


# ============== Claude Code 呼び出し ==============

def call_claude_code(full_prompt, timeout=600):
    process = subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=full_prompt,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=timeout,
    )
    if process.returncode != 0:
        err = f"returncode={process.returncode}\nstderr: {process.stderr[:1500]}\nstdout: {process.stdout[:1500]}"
        return None, err
    try:
        cc_output = json.loads(process.stdout)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}\nstdout先頭: {process.stdout[:1500]}"
    if cc_output.get("is_error"):
        return None, f"Claude Code error: {cc_output.get('result', '')[:1500]}"
    return cc_output, None


def extract_json_from_text(text):
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    raise ValueError("JSON extraction failed")


# ============== Phase 1: フック30本生成 ==============

def build_phase1_prompt(actor, account_info, target_research, eval_criteria,
                          hook_skill_text, top_hooks, bottom_hooks, proven_hooks,
                          schedule_slots):
    top_text = "\n".join([f"- [{h['views']}views] {h['hook']}" for h in top_hooks])
    bottom_text = "\n".join([f"- [{h['views']}views] {h['hook']}" for h in bottom_hooks])
    proven_text = "\n".join([f"- {h['hook']} (平均{int(h['avg_views'])}views・{h['rounds']}回投稿)" for h in proven_hooks]) or "（まだ無し）"

    sys_prompt = f"""あなたは {actor} のフック生成ロボットです。

# 役割
30本のフック（ポストの1行目だけ）を生成する。本文は作らない。
1行目で **ターゲットの問に対する明確な主張** を出して、読者を止めることに集中する。

# 最優先ルール（守らないと不合格・添削で指摘された落とし穴を全部潰す版）

## A. 冒頭は「ターゲットの問への主張」型を最優先
ターゲット（復縁したい女性）が抱える疑問に対して明確な主張で開く。
良い例：
- 「友達からやり直すのが安全」は嘘
- 復縁の成功確率0%があるとしたら、それは「諦めてる」ことくらい
- 復縁するために外見磨きは必要ない
- 男性は気持ちが冷めた相手にはそもそも迷いなく距離を置く

主張になってない悪い例：
- 「あの頃の私に教えたい」← 自分語り start・読者と関係ない
- 「別れて4日目、彼から〜のLINEが来た」← 自分語り start
- 「察してちゃんを治す必要なんてない」← オリジナル造語が読者にピンとこない
- 「復縁した女性が共通してやめたのは〜」← 教訓系・読者の状況に即接続しない

## B. オリジナル造語禁止（最重要・添削で指摘）
「察してちゃん」「○○タイプ」「○○ちゃんラベル」「○○モード」みたいな
**AI造語・ターゲットが日常で使ってない語彙は冒頭で使わない**。
ターゲットの「これ私のこと」即時一致が崩れる。

## C. 自分語り start 禁止（添削で指摘）
「あの頃の私」「別れて4日目」「私も〜だった」みたいな個人エピソード冒頭は NG。
**バックストーリー素材は thread 内（中盤の根拠）でだけ使う**。冒頭1行目では使わない。

## D. 既存スキル本体の継続ルール
- 読者を観客じゃなく **プレイヤー（当事者）** として扱う
- 第三者語り（「振った男は」「相談者で」だけで始める文体）は禁止
- 同じ語彙・構造の連発禁止
- 演者キャラの定型フレーズ（「臨床心理士として」「1000人見てきて」「相談者で」等）を連発しない
- evaluation_criteria の5問は内部チェックのみ。出力JSONに書き込まない
- target_research のセクション番号を引用しない

# 変数選定の3段階フロー（必須・スキル本体の核）
**AIの想像で変数を埋めるのは禁止**。必ず以下の順で素材を選ぶ：

```
Step1：素材実例集_CSV由来.md の Part 1（CSV直接実例）／恋愛ダスト_分析用.csv を見る
       → 該当サブパターンに直接実例があれば、それを最優先で参考にする
       → CSV48本の id（例：F-7-a, A-3-a 等）を引用元として記録する

Step2：Step1に無ければ Part 2（観察ワード集）から変数を組合せる

Step3：Step1/2 にも無ければ、4テスト合格を条件に新規生成
       □ イメージテスト：読んで具体シーン／動作が浮かぶか
       □ 圧縮テスト：1〜2語で観察を圧縮してるか
       □ 造語感テスト：オリジナル造語じゃないか（「察してちゃん」級は NG）
       □ 観察由来テスト：「なんで思い付いた？」に「実生活で見た」と答えられるか
```

# CSV実例参照時の思考フロー（フック1本ごとに必ず通す）

CSV実例の Part 1 から1本選んだら、以下を順に自問する。

Q1. CSVの語り手部分（例：「うちが見てきた」「うちの店に来た」「私の経験上」）は、本演者の立場・職業・性別と整合しているか？
  → 整合：そのまま使う。
  → 不整合：Q2へ。

Q2. 演者のプロフィール（職業・経験・立場）から見て、CSVの語り手部分を自然な表現に置き換えられるか？
  → 置き換え可能：人称・冠詞・口調だけ置き換える。構造（主張内容・男の本音セリフ・展開順）は完全に保つ。
  → 置き換え不能：このCSVは捨てて別のCSVを選ぶ。オリジナル生成に逃げない。

Q3. CSV内に経験量を示す数字（「5000人聞いてきて」「3年見てきて」等）がある場合、演者の立場から見てその数字は自然か？
  → 自然：そのまま。
  → 桁外れ・嘘っぽい：演者の立場で自然に響く規模に下げる。

このフローを通せないCSV実例は、オリジナル生成のネタにしない。次のCSVを選ぶ。

# フック作成スキル本体＋素材プール（最優先で従う・上記3段階フローのソース）
{hook_skill_text}

# 商品情報（このアカウントが売るもの・固定CTA・演者の事実とバックストーリー）
**重要：バックストーリーは thread 中盤の根拠として使う。冒頭1行目に「私の話」は出さない。**

{account_info}

# ターゲット研究（参考素材）
{target_research}

# フック評価軸（内部チェックのみ・本文に書き込まない）
{eval_criteria}
"""

    user_prompt = f"""# 実績データ

## 伸びたフック（参考・構造を学ぶ）
{top_text}

## 伸びなかったフック（避ける構造）
{bottom_text}

## 再投稿で再現性確認済みフック
{proven_text}

# タスク

次の3日分のフック30本を生成する。**各フックに本文の入り方タイプ（body_pattern）も一緒にアサインする**。

## based_on（過去ベースの配分・**新規創造を最小化する版**）

ハクオウのインプ低下の主因は「AIが新規創造に走って造語＋自分語りが湧く」こと。
これを構造的に防ぐため、**過去伸びたフックの再投稿を主体にする**。

- **repost 15本以上**：以下から優先順位で再投稿
  1. proven_hooks（再現性確認済み・複数回投稿で平均views高い）
  2. top_hooks（過去 views >= 1000 のフック）からそのまま再投稿
  3. 投稿時期がバラければ同じフックの再投稿は完全に問題ない
- **variation 10本**：伸びたフック（top）の中で1回だけ投稿のものを**主張部分は維持して周辺ワードを微修正**して再投稿
- **new 5本以下**：完全新規はここに収める。CSV48本由来の構造から派生したもののみ

**禁止**：based_on=new で「察してちゃん」「○○タイプ」みたいなオリジナル造語、または「あの頃の私」みたいな自分語り start は不可。発見次第その候補を捨てて別の repost/variation に置き換える。

## body_pattern（本文の入り方の配分）

スキル本体の本文パターンに従う。AIが追加でラベル分類する必要はあるが、本文の質はスキル本体に委ねる。

| body_pattern | 説明 |
|---|---|
| `reader_now` | 読者の今この瞬間の行動・感情を描写して始める |
| `mechanism_first` | メカニズム解説から始める（事例は補強だけ・自分語りNG） |
| `reverse_hope` | 反転希望から始める（絶望→希望の急展開・事例なしでもOK） |
| `mens_voice_quote` | 男の本音セリフから始める（自分の話じゃなく男側のセリフ） |
| `case_success` | 相談者成功事例から始める |
| `case_failure` | 失敗警告事例から始める |

**ルール**：
- `case_success` + `case_failure` を**合計4本以下**に厳格制限（テンプレ化防止）
- 同じ body_pattern が3本連続しない
- フックの内容と body_pattern を**自然な組み合わせ**で選ぶ

## 出力形式（JSON only・他のテキスト一切不要・**source_csv_id 必須**）

```json
{{
  "analysis": {{
    "top_patterns": ["伸びた構造の共通点（箇条書き）"],
    "bottom_failures": ["伸びなかった構造の共通点（箇条書き）"]
  }},
  "hooks": [
    {{
      "id": "{actor}_YYYYMMDD_NN",
      "hook_text": "1行目のフック",
      "structure_label": "常識否定型 / 男性心理暴露型 / 落差ストーリー型 / 命題型 / 反転希望型 など",
      "body_pattern": "claim_first / reader_now / mechanism_first / reverse_hope / mens_voice_quote / case_success / case_failure のいずれか",
      "based_on": "repost / variation / new",
      "source_csv_id": "派生元のCSV id（例：F-7-a, A-3-a）。new の場合でも派生元のCSV idを書く。完全オリジナルは禁止",
      "source_reference": "repost/variation の場合は元のフック先頭40字／new の場合は派生の根拠（CSVのどの構造から派生したか1行説明）",
      "scheduled_at": "ISO8601（下の slots から順に使う）"
    }}
  ]
}}
```

## スケジュールスロット（hook の scheduled_at に順に使う・30個）
{json.dumps(schedule_slots[:30], ensure_ascii=False)}
"""
    return sys_prompt + "\n\n---\n\n" + user_prompt


# ============== Phase 2: フック1本→本文生成 ==============

def build_phase2_prompt(actor, hook, account_info, body_skill_text):
    body_pattern_guide = {
        "reader_now": "読者の今この瞬間の行動・感情を描写して始める。「いま追いLINE送ろうとしてる人」「3週間既読スルーされて、夜眠れずスマホ見てる人」みたいに読者の現在地に直接届く。事例は最小限。**オリジナル造語（『察してちゃん』『○○タイプ』）は冒頭NG**。",
        "mechanism_first": "メカニズム解説から始める。原理→具体例で補強。事例で始めない。「男の脳ではこう動く」「回避型の特徴は〇〇」みたいな構造解説が先。",
        "reverse_hope": "反転希望から始める。「諦めかけてる人、まだ可能性ある」「終わったと思ってる人、実はここから戻せる」みたいに、絶望→希望の急展開で開く。事例なしでも成立する。**根拠を示さず希望だけ言うのはNG**。",
        "mens_voice_quote": "男の本音セリフを段落の中心に置く。「振った後の彼が言ってた」「復縁した男に直接聞いたら〜」みたいに、男の生の声を主役に。",
        "case_success": "相談者成功事例から始める。来談→分析→助言→成功→リスク提示の流れ。**「僕の購入者さんで…って泣きながら来た」テンプレの連発NG**。30本中で同じ事例構造が3本以上出ないよう、入り方を毎回変える。",
        "case_failure": "失敗警告事例から始める。来談→助言→動かなかった→手遅れ→教訓。緊張感／自責の警告。",
    }
    pattern = hook.get("body_pattern", "mechanism_first")
    pattern_explanation = body_pattern_guide.get(pattern, "")

    sys_prompt = f"""あなたは {actor} のポスト本文生成ロボットです。

# 役割
渡された1行目のフックに、指定された body_pattern で続きの本文と thread（ぶら下げ）を書く。
これは「リライトモード（人間がフックを当てて、AIが本文を作る）」の自動化版。

# 最優先ルール（守らないと不合格・添削で指摘された落とし穴を全部潰す版）

## A. 自分語り start を本文・thread 冒頭で使わない（添削指摘・最重要）
「あの頃の私」「別れて4日目」「私も〜だった」みたいな個人エピソード冒頭はNG。
これは読者と関係ない・スクロールされる。
**バックストーリー素材は thread の中盤で「根拠」として使う**。冒頭では使わない。

## B. オリジナル造語を本文で使わない（添削指摘・最重要）
「察してちゃん」「○○タイプ」「○○ちゃんラベル」みたいな AI造語・ターゲットが日常で使ってない語彙は本文・thread 冒頭で使わない。
本文中盤で「説明文付き」なら可（例：「この行動を僕は『察してちゃんラベル』って呼んでます」みたいに 1度説明を入れる）。

## C. 既存ルール
1. 渡された hook_text を1行目として **そのまま** 使う。書き換えない。
2. 続く本文（メイン部分・計100〜150字）と thread（3〜4段落＋CTA）を書く。CTAは本文ごとに作り直す（固定文言の使い回しはしない）。
3. **body_pattern に指定された入り方で書く**。他のパターンに勝手に変えない。
4. 読者を観客じゃなく **プレイヤー（当事者）** として扱う。本文中に「あなた／今のあなた」が出てくる箇所を必ず作る。
5. **スキル本体の段落別固定句リストはテンプレ強制じゃなく、参考の選択肢**。毎回同じ固定句（「僕の購入者さんで…」「〜って泣きながら来た」等）を使わない。
6. 同じ語彙・構造の連発NG。「臨床心理士として」「1000人見てきて」「相談者で」みたいなフレーズの連発はしない。
7. evaluation_criteria の5問は内部チェックのみ。本文に書き込まない。
8. target_research のセクション番号を本文に引用しない。
9. **CTAは本文ごとに作り直す。** 誘導先（プロフのnote等）は固定だが、CTAの言い回しは毎回そのポストの中身（指摘した「やっちゃってる」やテーマ）に合わせて変える。全ポスト同じCTAの使い回しはNG（業者感）。誘導記号は「↓」か言い切り、▼は使わない。

## D. AI感監視員ルール（説明調・整いすぎ・三角記号を出さない）
10. **体験者の口で書く（解説者の口で書かない）**：心の動きを"仕組み"として名詞化・説明しない。「固定される／上書きできない／スイッチが入る／印象固定／過去化する／〜が勝手に立ち上がる／分類する最大の要因」みたいな解説調は禁止。「固まる／もう戻せない／思い込む」みたいに、その人が実際に口で喋る体感の言葉にする。
11. **整いすぎない**：数字・対句・並列をきれいに揃えすぎない（「ほぼ全員一致で／100%／必ず／3つが同時に」みたいな作った感はNG。"だいたい/ほぼ"に崩す）。**ただし演者の実績数字（相談1000件等）はそのまま残す**——これは権威。
12. **三角の誘導記号「▼」は使わない**（確定の好み）。誘導は「↓」か言い切り（記号なし）で。

# ポスト作成スキル本体（恋愛系特化・参考にする）
スキル本体の「段落別固定句リスト」「本文4パターン」は売れる構造の素材集として参照する。
ただし**そのままコピペする強制テンプレじゃない**。指定の body_pattern と合わない固定句は使わない。

{body_skill_text}

# 商品情報（演者の最低限の事実・商品・固定CTA・バックストーリー）
**重要：バックストーリーは thread の中盤で「根拠」として使う。本文・thread 冒頭で「あの頃の私」型の自分語り start はNG。**

{account_info}
"""

    user_prompt = f"""# 入力

## フック（1行目・そのまま使う）
{hook['hook_text']}

## カテゴリ/構造（参考）
{hook.get('structure_label', '')}

## 元ネタ
{hook.get('based_on', 'new')}

## body_pattern（本文の入り方・必ずこれに従う）
**{pattern}**

{pattern_explanation}

# タスク
このフックから続く本文（メイン続き）と thread（ぶら下げ）を、上記の body_pattern に従って書く。

# 出力形式（JSON only・他のテキスト一切不要）

```json
{{
  "text": "メインテキスト（1行目フック含む全体100〜150字）",
  "thread": ["ぶら下げ全文＋固定CTAを1要素にまとめた文字列"]
}}
```
"""
    return sys_prompt + "\n\n---\n\n" + user_prompt


# ============== hook_archive 更新 ==============

def update_hook_archive(actor, hooks):
    """生成した30本のフックを hook_archive.json に追加（再投稿の追跡用）"""
    archive_path = os.path.join(ROOT, f"analytics/{actor}/hook_archive.json")
    archive = load_json(archive_path, {"hooks": {}})

    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    for h in hooks:
        hid = fookid(h["hook_text"])
        h["fookid"] = hid
        if hid not in archive["hooks"]:
            archive["hooks"][hid] = {
                "text": h["hook_text"],
                "structure_label": h.get("structure_label", ""),
                "first_used_at": today,
                "history": [],
            }
        # 予約スロットを記録（views は後で fetch から追記される）
        archive["hooks"][hid]["history"].append({
            "scheduled_at": h.get("scheduled_at"),
            "registered_at": today,
            "views": None,
        })

    save_json(archive_path, archive)
    return archive_path


# ============== main run ==============

def run(actor, phase1_only=False, limit=None, reuse_phase1=False):
    knowledge_dir = os.path.join(ROOT, f"knowledge/{actor}")
    shared_dir = os.path.join(ROOT, "knowledge/shared")
    account_dir = os.path.join(ROOT, f"accounts/{actor}")
    analytics_dir = os.path.join(ROOT, f"analytics/{actor}")

    eval_path = os.path.join(knowledge_dir, "evaluation_criteria.md")
    if not os.path.exists(eval_path):
        eval_path = os.path.join(shared_dir, "evaluation_criteria.md")
    research_path = os.path.join(knowledge_dir, "target_research.md")
    if not os.path.exists(research_path):
        research_path = os.path.join(shared_dir, "target_research.md")
    setting_path = os.path.join(account_dir, "アカウント情報総合管理.md")
    db_path = os.path.join(analytics_dir, "posts_db.json")
    hook_archive_path = os.path.join(analytics_dir, "hook_archive.json")
    prev_batch_path = os.path.join(analytics_dir, "next_batch.json")

    for path, label in [(eval_path, "evaluation_criteria"), (research_path, "target_research"),
                         (setting_path, "アカウント情報総合管理"), (db_path, "posts_db")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}")
            sys.exit(1)

    print(f"[hook_improve] {actor} 開始")
    print(f"  evaluation_criteria: {os.path.relpath(eval_path, ROOT)}")

    eval_criteria = load_text(eval_path)
    target_research = load_text(research_path)
    account_info = load_text(setting_path)
    posts_db = load_json(db_path, {"posts": {}})
    hook_archive = load_json(hook_archive_path, {"hooks": {}})

    hook_skill_text = "\n\n".join([
        load_text(os.path.join(ROOT, p), optional=True) for p in HOOK_SKILL_FILES
    ])
    body_skill_text = "\n\n".join([
        load_text(os.path.join(ROOT, p), optional=True) for p in BODY_SKILL_FILES
    ])

    top_hooks, bottom_hooks, proven_hooks = extract_performance_data(posts_db, hook_archive)
    print(f"  実績: top={len(top_hooks)} bottom={len(bottom_hooks)} proven={len(proven_hooks)}")

    start_date = find_next_start_date(posts_db, prev_batch_path)
    schedule_slots = generate_schedule(start_date)
    print(f"  スケジュール: {start_date.strftime('%Y-%m-%d')} 〜 {(start_date + timedelta(days=2)).strftime('%Y-%m-%d')}")

    # === Phase 1: フック30本生成 ===
    preview_path = os.path.join(analytics_dir, "phase1_hooks_preview.json")
    if reuse_phase1 and os.path.exists(preview_path):
        print(f"\n[Phase 1] --reuse-phase1 モード: 既存の {preview_path} を使う")
        prev = load_json(preview_path)
        phase1_result = {
            "analysis": prev.get("analysis", {}),
            "hooks": prev.get("hooks", []),
        }
    else:
        print("\n[Phase 1] フック30本生成中（1回の呼び出し）...")
        phase1_prompt = build_phase1_prompt(
            actor, account_info, target_research, eval_criteria,
            hook_skill_text, top_hooks, bottom_hooks, proven_hooks, schedule_slots
        )
        cc_output, err = call_claude_code(phase1_prompt, timeout=600)
        if err:
            print(f"  ✗ Phase 1 失敗:\n{err[:1500]}")
            sys.exit(1)
        try:
            phase1_result = extract_json_from_text(cc_output.get("result", ""))
        except (ValueError, json.JSONDecodeError) as e:
            err_path = os.path.join(analytics_dir, "hook_improve_phase1_error.txt")
            with open(err_path, 'w', encoding='utf-8') as f:
                f.write(cc_output.get("result", ""))
            print(f"  ✗ Phase 1 JSON抽出失敗: {e}（生レスポンスを {err_path} に保存）")
            sys.exit(1)

        usage = cc_output.get("usage", {})
        if usage:
            print(f"    tokens: input={usage.get('input_tokens', 0)}, output={usage.get('output_tokens', 0)}, "
                  f"cache_read={usage.get('cache_read_input_tokens', 0)}")

    hooks = phase1_result.get("hooks", [])[:30]
    print(f"  ✓ Phase 1 完了: {len(hooks)}本のフック")

    if phase1_only:
        # Phase 1 だけ走らせるテストモード。フック中身を別ファイルに出して終了。
        out_path = os.path.join(analytics_dir, "phase1_hooks_preview.json")
        save_json(out_path, {
            "演者": actor,
            "generated_at": datetime.now(tz=JST).isoformat(),
            "analysis": phase1_result.get("analysis", {}),
            "hooks_count": len(hooks),
            "hooks": hooks,
        })
        print(f"  --phase1-only モード: フック中身を {out_path} に保存して終了")
        return out_path

    # === Phase 2: 1本ずつ本文生成（シーケンシャル）===
    phase2_hooks = hooks if limit is None else hooks[:limit]
    print(f"\n[Phase 2] 本文生成（{len(phase2_hooks)}回シーケンシャル・並列はしない）...")
    posts = []
    for i, hook in enumerate(phase2_hooks, 1):
        ht = (hook.get("hook_text", "") or "").replace("\n", " ")
        print(f"  ({i}/{len(phase2_hooks)}) {ht[:60]}...")
        p2_prompt = build_phase2_prompt(actor, hook, account_info, body_skill_text)
        cc_out, err = call_claude_code(p2_prompt, timeout=300)
        if err:
            print(f"    ✗ 失敗: {err[:300]}")
            continue
        try:
            body = extract_json_from_text(cc_out.get("result", ""))
        except (ValueError, json.JSONDecodeError) as e:
            print(f"    ✗ JSON抽出失敗: {e}")
            continue

        thread = body.get("thread", [])
        if isinstance(thread, list) and len(thread) > 1:
            thread = ["\n\n".join(t for t in thread if isinstance(t, str) and t.strip())]

        posts.append({
            "id": hook.get("id"),
            "fookid": fookid(hook["hook_text"]),
            "structure_label": hook.get("structure_label"),
            "based_on": hook.get("based_on"),
            "scheduled_at": hook.get("scheduled_at"),
            "text": body.get("text", ""),
            "thread": thread,
        })

    print(f"  ✓ Phase 2 完了: {len(posts)}/{len(phase2_hooks)}本の本文生成")

    if limit is not None:
        # 部分テスト時は hook_archive 更新しない（本番運用じゃないため）
        test_out_path = os.path.join(analytics_dir, f"phase2_test_{len(posts)}posts.json")
        save_json(test_out_path, {
            "演者": actor,
            "generated_at": datetime.now(tz=JST).isoformat(),
            "limit": limit,
            "posts": posts,
        })
        print(f"  --limit テストモード: {test_out_path} に保存して終了")
        return test_out_path

    # === hook_archive 更新 ===
    archive_path = update_hook_archive(actor, hooks)
    print(f"  ✓ hook_archive 更新: {archive_path}")

    # === next_batch.json 出力（schedule_posts.py 互換）===
    output = {
        "演者": actor,
        "generated_at": datetime.now(tz=JST).isoformat(),
        "cycle_start": start_date.isoformat(),
        "cycle_end": (start_date + timedelta(days=2)).isoformat(),
        "analysis": phase1_result.get("analysis", {}),
        "総本数": len(posts),
        "posts": posts,
    }
    out_path = os.path.join(analytics_dir, "next_batch.json")
    save_json(out_path, output)
    print(f"\n  ✓ 出力: {out_path}")

    return out_path


def main():
    if len(sys.argv) < 2:
        print("usage: python note_tools/hook_improve.py <演者名> [--phase1-only] [--limit N] [--reuse-phase1]")
        sys.exit(1)
    actor = sys.argv[1]
    phase1_only = "--phase1-only" in sys.argv
    reuse_phase1 = "--reuse-phase1" in sys.argv
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass
            break
    run(actor, phase1_only=phase1_only, limit=limit, reuse_phase1=reuse_phase1)


if __name__ == "__main__":
    main()
