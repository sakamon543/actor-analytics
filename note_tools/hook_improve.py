#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フック分析＋次バッチ自動生成
============================
3日サイクルの analyze 後に実行。
posts_db.json の実績を Claude API で分析し、次の3日分（30本）を生成する。

使い方:
    python note_tools/hook_improve.py <演者名>

環境変数:
    ANTHROPIC_API_KEY: Claude API キー
"""
import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))

SCHEDULE_TEMPLATE = [
    (11, 8), (13, 17), (14, 42),
    (18, 3), (19, 17), (19, 52),
    (20, 28), (21, 3), (22, 17), (22, 48),
]


def load_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def find_next_start_date(posts_db, prev_batch_path=None):
    """起点候補（最も未来のものを採用）:
    1. 明日（過去日時を生成しないため）
    2. 過去投稿の最新日 + 1（posts_db.json）
    3. 前回バッチの最終スケジュール日 + 1（next_batch.json、3日サイクル累積防止）"""
    tomorrow = datetime.now(tz=JST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    candidates = [tomorrow]

    latest_posted = None
    for p in posts_db.get("posts", {}).values():
        dt = datetime.fromisoformat(p["posted_at"]).astimezone(JST)
        if latest_posted is None or dt > latest_posted:
            latest_posted = dt
    if latest_posted:
        candidates.append((latest_posted + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))

    if prev_batch_path and os.path.exists(prev_batch_path):
        with open(prev_batch_path, encoding='utf-8') as f:
            prev = json.load(f)
        latest_scheduled = None
        for p in prev.get("posts", []):
            if not p.get("scheduled_at"):
                continue
            dt = datetime.fromisoformat(p["scheduled_at"]).astimezone(JST)
            if latest_scheduled is None or dt > latest_scheduled:
                latest_scheduled = dt
        if latest_scheduled:
            candidates.append((latest_scheduled + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))

    return max(candidates)


def generate_schedule(start_date, days=3, per_day=10):
    """3日分の投稿スケジュールを生成（人間っぽい時刻）"""
    slots = []
    for d in range(days):
        day = start_date + timedelta(days=d)
        for i, (h, m) in enumerate(SCHEDULE_TEMPLATE[:per_day]):
            dt = day.replace(hour=h, minute=m, second=0, microsecond=0)
            slots.append(dt.isoformat())
    return slots


def extract_performance_summary(posts_db):
    """posts_db から上位・下位フックと統計を抽出"""
    posts = posts_db.get("posts", {})
    if not posts:
        return "実績データなし"

    items = []
    for key, p in posts.items():
        items.append({
            "hook": p["text"].split("\n")[0],
            "views": p["views"],
            "type": p.get("type", "unknown"),
            "seen_in": p.get("last_seen_in", "unknown"),
        })

    items.sort(key=lambda x: x["views"], reverse=True)

    lines = []
    lines.append(f"総ポスト数: {len(items)}")
    if items:
        avg = sum(x["views"] for x in items) / len(items)
        lines.append(f"平均views: {avg:.0f}")

    lines.append("\n### 上位フック（効いたもの）")
    for p in items[:5]:
        lines.append(f"- [{p['views']}views] {p['hook']}")

    lines.append("\n### 下位フック（効かなかったもの）")
    for p in items[-5:]:
        lines.append(f"- [{p['views']}views] {p['hook']}")

    summary = posts_db.get("latest_summary", {})
    if summary.get("hooks_analysis"):
        ha = summary["hooks_analysis"]
        lines.append("\n### 直近の成功・失敗フック（API由来）")
        lines.append("成功: " + " / ".join(ha.get("worked", [])[:3]))
        lines.append("失敗: " + " / ".join(ha.get("failed", [])[:3]))

    return "\n".join(lines)


def build_messages(actor, eval_criteria, target_research, account_setting, performance_summary, schedule_slots):
    system = [
        {
            "type": "text",
            "text": (
                f"あなたは{actor}のThreadsポスト自動改善ロボットです。\n\n"
                "## 役割\n"
                "実績データを分析し、evaluation_criteria.md の思考プロセスで評価した上で、"
                "次の3日分（30本）のポストを生成します。\n\n"
                "## 絶対ルール\n"
                "- フック（1行目）は evaluation_criteria.md の5つの問いを通す\n"
                "- 各問いで target_research.md の該当セクションを参照する\n"
                "- アカウント設定の固定CTA・語尾・NG表現を厳守する\n"
                "- 「なんとなく良さそう」で出さない。構造的根拠がないフックは不合格\n"
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## フック評価基準\n\n{eval_criteria}",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## ターゲットリサーチ\n\n{target_research}",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## アカウント設定\n\n{account_setting}",
        },
    ]

    schedule_json = json.dumps(schedule_slots[:30], ensure_ascii=False)

    user = f"""## 直近の実績データ

{performance_summary}

---

## タスク

### Step 1: 分析
上位フックと下位フックを evaluation_criteria.md の5つの問いで評価せよ。
- 上位の共通パターンを言語化
- 下位の共通失敗を言語化

### Step 2: バッチ生成（30本）
分析結果を使って次の3日分を生成。

バッチ構成:
- **新規 15本以上**: target_research.md セクション10の欲求8つ × セクション7のフック構造6パターンから組み合わせを散らす。同じ「欲求×構造」を2本以上使わない
- **再投稿 6〜9本**: 上位フックをそのまま or 微調整で再利用（パターン再現性テスト）
- **改善 6〜9本**: 下位フックを Part 4 の改善手順（1→2→3→4→5）で改善

### Step 3: セルフチェック
生成した30本それぞれについて:
- evaluation_criteria.md の問い1〜5に1文ずつ回答
- アカウント設定のチェックリスト通過確認
- 不合格なら差し替え

## 出力形式

以下のJSON形式で出力。JSONのみ出力し、JSON以外のテキストは出力しない。

```json
{{
  "analysis": {{
    "top_patterns": ["上位の共通パターン（箇条書き）"],
    "bottom_failures": ["下位の共通失敗（箇条書き）"]
  }},
  "posts": [
    {{
      "id": "{actor.upper()}_YYYYMMDD_NN",
      "batch_type": "new|repost|improved",
      "category": "F系/G系/D系/A-2/A-3/B-3 + サブカテゴリ",
      "target_desire": "セクション10の欲求番号（#1〜#8）",
      "hook_structure": "セクション7のパターン名",
      "scheduled_at": "ISO8601",
      "text": "フック＋本文（100〜150字）",
      "thread": ["1要素のみ。3〜4段落（\\n\\nで段落区切り）の本文の最後に固定CTAを付けた1つの文字列。配列に複数要素を入れないこと（複数入れると別リプライとして連鎖投稿される）"],
      "evaluation": {{
        "q1": "どの会話に入るか（1文）",
        "q2": "前提知識の確認（1文）",
        "q3": "自分事か（1文）",
        "q4": "覚醒度（1文）",
        "q5": "被り確認（1文）"
      }},
      "improved_from": "改善元のフック（batch_type=improvedの場合のみ）"
    }}
  ]
}}
```

投稿スケジュール（この時刻を scheduled_at に使う）:
{schedule_json}
"""

    messages = [{"role": "user", "content": user}]
    return system, messages


def extract_json_from_response(text):
    """レスポンスからJSON部分を抽出"""
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
    raise ValueError("JSONの抽出に失敗")


def run(actor):
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic パッケージが必要です。pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 環境変数が未設定")
        sys.exit(1)

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

    for path, label in [(eval_path, "evaluation_criteria"), (research_path, "target_research"),
                         (setting_path, "アカウント情報総合管理"), (db_path, "posts_db")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} が見つかりません: {path}")
            sys.exit(1)
    print(f"  evaluation_criteria: {os.path.relpath(eval_path, ROOT)}")

    print(f"[hook_improve] {actor} の分析＋生成を開始")

    eval_criteria = load_text(eval_path)
    target_research = load_text(research_path)
    account_setting = load_text(setting_path)
    posts_db = load_json(db_path)

    performance_summary = extract_performance_summary(posts_db)
    print(f"  実績サマリー抽出完了（{len(posts_db.get('posts', {}))}本）")

    prev_batch_path = os.path.join(analytics_dir, "next_batch.json")
    start_date = find_next_start_date(posts_db, prev_batch_path)
    schedule_slots = generate_schedule(start_date)
    print(f"  スケジュール生成: {start_date.strftime('%Y-%m-%d')} 〜 {(start_date + timedelta(days=2)).strftime('%Y-%m-%d')}")

    system, messages = build_messages(
        actor, eval_criteria, target_research, account_setting,
        performance_summary, schedule_slots
    )

    client = anthropic.Anthropic(api_key=api_key)

    print(f"  Claude API 呼び出し中（claude-sonnet-4-6、ストリーミング）...")
    raw_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=32000,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            raw_text += text
        final_message = stream.get_final_message()

    print(f"  レスポンス受信: {len(raw_text)}文字")

    usage = final_message.usage
    print(f"  トークン: input={usage.input_tokens}, output={usage.output_tokens}")
    if hasattr(usage, 'cache_creation_input_tokens'):
        print(f"  キャッシュ: creation={usage.cache_creation_input_tokens}, read={usage.cache_read_input_tokens}")

    try:
        result = extract_json_from_response(raw_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  ✗ JSON解析失敗: {e}")
        error_path = os.path.join(analytics_dir, "hook_improve_error.txt")
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(raw_text)
        print(f"  生レスポンスを {error_path} に保存")
        sys.exit(1)

    posts = result.get("posts", [])
    merged_count = 0
    for p in posts:
        thread = p.get("thread")
        if isinstance(thread, list) and len(thread) > 1:
            p["thread"] = ["\n\n".join(t for t in thread if isinstance(t, str) and t.strip())]
            merged_count += 1
    if merged_count > 0:
        print(f"  ⚠ {merged_count}本のthreadを複数要素→1要素に正規化（2連型固定）")

    n_posts = len(posts)
    print(f"  生成完了: {n_posts}本")

    output = {
        "演者": actor,
        "generated_at": datetime.now(tz=JST).isoformat(),
        "cycle_start": start_date.isoformat(),
        "cycle_end": (start_date + timedelta(days=2)).isoformat(),
        "analysis": result.get("analysis", {}),
        "総本数": n_posts,
        "posts": result.get("posts", []),
    }

    out_path = os.path.join(analytics_dir, "next_batch.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 出力: {out_path}")

    analysis = result.get("analysis", {})
    if analysis.get("top_patterns"):
        print(f"\n  上位パターン:")
        for p in analysis["top_patterns"]:
            print(f"    - {p}")
    if analysis.get("bottom_failures"):
        print(f"  下位失敗:")
        for p in analysis["bottom_failures"]:
            print(f"    - {p}")

    batch_counts = {}
    for p in result.get("posts", []):
        bt = p.get("batch_type", "unknown")
        batch_counts[bt] = batch_counts.get(bt, 0) + 1
    print(f"\n  バッチ構成: {batch_counts}")

    return out_path


def main():
    if len(sys.argv) < 2:
        print("usage: python note_tools/hook_improve.py <演者名>")
        sys.exit(1)
    actor = sys.argv[1]
    run(actor)


if __name__ == "__main__":
    main()
