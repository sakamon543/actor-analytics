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
1行目で読者を「これは自分のことだ」と止めることに集中する。

# 最優先ルール（守らないと不合格）
1. 読者を観客じゃなく **プレイヤー（当事者）** として扱う。
2. フック1行目で読者の **今この瞬間の行動・感情・現在地** を名指す。
3. 第三者語り（「振った男は」「相談者で」だけで始める文体）は禁止。
4. 同じ語彙・構造の連発禁止。30本全部違う角度。
5. 演者キャラの定型フレーズ（例：「臨床心理士として」「1000人見てきて」「相談者で」等）を連発しない。本文じゃないし、1行目で権威マウントは引く側に回る。
6. evaluation_criteria の5問は内部チェックのみ。出力JSONに書き込まない。
7. target_research のセクション番号を引用しない（1行目に学術引用は不要）。

# 変数選定の3段階フロー（必須・スキル本体の核）
**AIの想像で変数を埋めるのは禁止**。必ず以下の順で素材を選ぶ：

```
Step1：素材実例集_CSV由来.md の Part 1（CSV直接実例）／恋愛ダスト_分析用.csv を見る
       → 該当サブパターンに直接実例があれば、それを最優先で参考にする（丸コピーじゃなく構造とワードを参照）

Step2：Step1に無ければ Part 2（観察ワード集）から変数を組合せる
       → 男の本音セリフ／心理メカニズム／落差描写などから具体ワードを引く

Step3：Step1/2 にも無ければ、4テスト合格を条件に新規生成
       □ イメージテスト：読んで具体シーン／動作が浮かぶか
       □ 圧縮テスト：1〜2語で観察を圧縮してるか
       □ 造語感テスト：「あ、それ」と新鮮さがあるか（AI造語にならない範囲）
       □ 観察由来テスト：「なんで思い付いた？」に「実生活で見た」と答えられるか
```

# フック作成スキル本体＋素材プール（最優先で従う・上記3段階フローのソース）
{hook_skill_text}

# 商品情報（このアカウントが売るもの・固定CTA・演者の事実とバックストーリー）
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

## based_on（過去ベースの配分）
- **再投稿候補 約5本**：proven_hooks（再現性確認済み）からそのまま再投稿（based_on=repost）
- **再現性テスト 約5本**：伸びたフック（top）の中で1回だけ投稿のものを微修正して再投稿（based_on=variation）
- **新規 約20本**：実績の傾向を踏まえつつ新しい角度で（based_on=new）

## body_pattern（本文の入り方の配分・最重要）

スキル本体の段落別固定句リストや本文4パターンは**参考のテンプレ**で、強制じゃない。
30本中で同じ入り方を連発しない。以下の配分で振り分ける：

| body_pattern | 説明 | 配分目安 |
|---|---|---|
| `case_success` | 相談者成功事例から始める（A：相談者成功型） | 最大10本 |
| `case_failure` | 失敗警告事例から始める（B：失敗警告型） | 最大5本 |
| `mens_voice_quote` | 男の本音セリフから始める（C：男の本音引用型） | 最大5本 |
| `mechanism_first` | メカニズム解説から始める（D：メカニズム解説型・事例は補強だけ） | 5本以上 |
| `reader_now` | 読者の今この瞬間の行動・感情を描写して始める（事例なし） | 5本以上 |
| `reverse_hope` | 反転希望から始める（絶望→希望の急展開・事例なしでもOK） | 3本以上 |

**ルール**：
- 30本中 `case_success` を10本超えない（同じ入り方の連発防止）
- `mechanism_first` `reader_now` `reverse_hope` を合計13本以上入れる（事例依存じゃない本文を増やす）
- 同じ body_pattern が3本連続しない（時系列でばらける）
- フックの内容と body_pattern を**自然な組み合わせ**で選ぶ（例：セリフ引用型フックなら mens_voice_quote が自然、命題型フックなら mechanism_first か reader_now が自然）

## 出力形式（JSON only・他のテキスト一切不要）

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
      "body_pattern": "case_success / case_failure / mens_voice_quote / mechanism_first / reader_now / reverse_hope のいずれか",
      "based_on": "new / repost / variation",
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
        "case_success": "相談者成功事例から始める。来談→分析→助言→成功→リスク提示の流れ。固定句『僕の購入者さんで』『〜って泣きながら来た』『〜後、彼から連絡が来た』が使えるが、毎回同じセリフは避ける。",
        "case_failure": "失敗警告事例から始める。来談→助言→動かなかった→手遅れ→教訓。緊張感／自責の警告。",
        "mens_voice_quote": "男の本音セリフを段落の中心に置く。「振った後の彼が言ってた」「復縁した男に直接聞いたら〜」みたいに、男の生の声を主役に。",
        "mechanism_first": "メカニズム解説から始める。原理→具体例で補強。事例で始めない。「男の脳ではこう動く」「回避型の特徴は〇〇」みたいな構造解説が先。",
        "reader_now": "読者の今この瞬間の行動・感情を描写して始める。「いま追いLINE送ろうとしてる人」「3週間既読スルーされて、夜眠れずスマホ見てる人」みたいに読者の現在地に直接届く。事例は最小限。",
        "reverse_hope": "反転希望から始める。「諦めかけてる人、まだ可能性ある」「終わったと思ってる人、実はここから戻せる」みたいに、絶望→希望の急展開で開く。事例なしでも成立する。",
    }
    pattern = hook.get("body_pattern", "case_success")
    pattern_explanation = body_pattern_guide.get(pattern, "")

    sys_prompt = f"""あなたは {actor} のポスト本文生成ロボットです。

# 役割
渡された1行目のフックに、指定された body_pattern で続きの本文と thread（ぶら下げ）を書く。
これは「リライトモード（人間がフックを当てて、AIが本文を作る）」の自動化版。

# 最優先ルール（守らないと不合格）
1. 渡された hook_text を1行目として **そのまま** 使う。書き換えない。
2. 続く本文（メイン部分・計100〜150字）と thread（3〜4段落＋固定CTA）を書く。
3. **body_pattern に指定された入り方で書く**。他のパターンに勝手に変えない。
4. 読者を観客じゃなく **プレイヤー（当事者）** として扱う。本文中に「あなた／今のあなた」が出てくる箇所を必ず作る。
5. **スキル本体の段落別固定句リストはテンプレ強制じゃなく、参考の選択肢**。毎回同じ固定句（「僕の購入者さんで…」「〜って泣きながら来た」「〇〇後、彼から連絡が来た」等）を使わない。指定の body_pattern に合った別の表現を選ぶ。
6. 同じ語彙・構造の連発NG。「臨床心理士として」「1000人見てきて」「相談者で」みたいなフレーズの連発はしない。
7. evaluation_criteria の5問は内部チェックのみ。本文に書き込まない。
8. target_research のセクション番号を本文に引用しない。
9. 固定CTAは商品情報の固定CTAそのまま。改変禁止。

# ポスト作成スキル本体（恋愛系特化・参考にする）
スキル本体の「段落別固定句リスト」「本文4パターン」は売れる構造の素材集として参照する。
ただし**そのままコピペする強制テンプレじゃない**。指定の body_pattern と合わない固定句は使わない。

{body_skill_text}

# 商品情報（演者の最低限の事実・商品・固定CTA）
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
