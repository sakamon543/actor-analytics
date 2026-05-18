# -*- coding: utf-8 -*-
"""
ポスト成績照合・分析スクリプト
==============================
予想ランク（master_*_ranked.json）と実績（posts_db.json）を照合して、
仮説 vs 実績のギャップ分析レポートを出力する。

使い方:
    python note_tools/analyze_post_performance.py <演者名> <ranked_master.json>
    例: python note_tools/analyze_post_performance.py ハクオウ generated_x_posts/ハクオウ_post_master_100posts_ranked.json

出力:
    analytics/{演者名}/analysis_{日付}.md   人間向け分析レポート
    analytics/{演者名}/matched_posts.json   予想と実績がマッチしたポストの統合データ
"""
import json
import os
import sys
import re
import statistics
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def normalize(text, n=50):
    """マッチング用の正規化キー（先頭n字）"""
    t = re.sub(r'\s+', '', text)[:n]
    return t


def match_posts(planned_posts, db_posts):
    """
    予想ポストと実績DB（蓄積）をtextの先頭でマッチング。
    マッチした分だけ actual_views を付与する。
    """
    db_keys = {normalize(p["text"]): p for p in db_posts.values()}
    matched = []
    unmatched = []
    for pp in planned_posts:
        key = normalize(pp["text"])
        if key in db_keys:
            actual = db_keys[key]
            merged = {**pp, "actual_views": actual["views"], "actual_seen_in": actual["last_seen_in"]}
            matched.append(merged)
        else:
            unmatched.append(pp)
    return matched, unmatched


def aggregate_by(posts, key_fn, label):
    """key_fn(p) ごとに actual_views の中央値・件数を集計"""
    buckets = defaultdict(list)
    for p in posts:
        k = key_fn(p)
        buckets[k].append(p["actual_views"])
    rows = []
    for k, vs in sorted(buckets.items()):
        rows.append({
            "key": k,
            "n": len(vs),
            "median_views": statistics.median(vs) if vs else 0,
            "max_views": max(vs) if vs else 0,
            "min_views": min(vs) if vs else 0,
        })
    return rows


def build_report(actor, matched, unmatched, planned_total, db, latest_summary):
    """Markdown形式の分析レポートを組み立てる"""
    lines = []
    lines.append(f"# {actor} ポスト成績分析レポート")
    lines.append(f"")
    lines.append(f"生成日：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")
    lines.append(f"## 1. 全体サマリー")
    lines.append(f"")
    lines.append(f"- 計画本数：{planned_total}本")
    lines.append(f"- 実績マッチ：{len(matched)}本（{len(matched)/planned_total*100:.1f}%）")
    lines.append(f"- 未マッチ：{len(unmatched)}本（top/bottomに入らなかった or 投稿前）")
    if latest_summary and latest_summary.get("ai_summary"):
        lines.append(f"")
        lines.append(f"### 直近のAIサマリー（threads-auto-af由来）")
        lines.append(f"")
        lines.append(f"> {latest_summary['ai_summary']}")

    if not matched:
        lines.append(f"")
        lines.append(f"_実績データがまだ蓄積されてないので、以降の分析はスキップ_")
        return "\n".join(lines)

    # 2. 予想ランク vs 実績の照合
    lines.append(f"")
    lines.append(f"## 2. 予想ランク vs 実績インプ（中央値）")
    lines.append(f"")
    rank_agg = aggregate_by(matched, lambda p: p["prediction"]["predicted_rank"], "rank")
    lines.append(f"| 予想 | n | 中央値 | 最大 | 最小 |")
    lines.append(f"|---|---|---|---|---|")
    for r in rank_agg:
        lines.append(f"| {r['key']} | {r['n']} | {r['median_views']:.0f} | {r['max_views']} | {r['min_views']} |")
    lines.append(f"")
    lines.append(f"**仮説検証**：S→A→B→Cの順に中央値が下がっていれば仮説は正しい。逆転してたら判定ロジックの修正が必要。")

    # 3. メタタグ別の平均
    lines.append(f"")
    lines.append(f"## 3. メタタグ別パフォーマンス")
    lines.append(f"")
    for tag in ["has_number", "has_reversal", "has_concrete_quote", "has_authority", "has_risk", "has_kaishaku"]:
        on = [p["actual_views"] for p in matched if p["prediction"]["tags"][tag]]
        off = [p["actual_views"] for p in matched if not p["prediction"]["tags"][tag]]
        if on and off:
            on_med = statistics.median(on)
            off_med = statistics.median(off)
            ratio = on_med / off_med if off_med > 0 else 0
            lines.append(f"- **{tag}**：あり={on_med:.0f} (n={len(on)}) / なし={off_med:.0f} (n={len(off)}) → 比率 {ratio:.2f}x")

    # 4. ギャップ抽出（仮説外し）
    lines.append(f"")
    lines.append(f"## 4. 仮説外し（学習対象）")
    lines.append(f"")
    if matched:
        sorted_actual = sorted(matched, key=lambda p: p["actual_views"], reverse=True)
        # CランクなのにTop20%入りしてるもの
        top_threshold = sorted_actual[len(sorted_actual)//5]["actual_views"] if len(sorted_actual) >= 5 else 0
        bottom_threshold = sorted_actual[-len(sorted_actual)//5]["actual_views"] if len(sorted_actual) >= 5 else 0
        c_in_top = [p for p in matched if p["prediction"]["predicted_rank"] in ("C", "B") and p["actual_views"] >= top_threshold]
        s_in_bottom = [p for p in matched if p["prediction"]["predicted_rank"] in ("S", "A") and p["actual_views"] <= bottom_threshold]

        lines.append(f"### 4-1. 「弱いと予想したけど伸びた」ポスト（{len(c_in_top)}本）")
        lines.append(f"")
        for p in c_in_top[:10]:
            lines.append(f"- [{p['prediction']['predicted_rank']}/{p['actual_views']}views] {p['text'][:80]}")
        lines.append(f"")
        lines.append(f"### 4-2. 「強いと予想したのに伸びなかった」ポスト（{len(s_in_bottom)}本）")
        lines.append(f"")
        for p in s_in_bottom[:10]:
            lines.append(f"- [{p['prediction']['predicted_rank']}/{p['actual_views']}views] {p['text'][:80]}")

    # 5. 時間帯・タイプ分析（threads-auto-af由来）
    if latest_summary and latest_summary.get("time_analysis"):
        lines.append(f"")
        lines.append(f"## 5. 時間帯・タイプ分析")
        lines.append(f"")
        ta = latest_summary["time_analysis"]
        lines.append(f"- ベスト時間帯：{ta.get('best_hours')}")
        lines.append(f"- ワースト時間帯：{ta.get('worst_hours')}")
        if latest_summary.get("type_analysis"):
            ty = latest_summary["type_analysis"]
            lines.append(f"- normal平均：{ty.get('normal_avg_views')} (n={ty.get('normal_count')})")
            lines.append(f"- thread平均：{ty.get('thread_avg_views')} (n={ty.get('thread_count')})")
            lines.append(f"- 勝者：{ty.get('winner')}")

    # 6. 次回への改善提案（自動）
    lines.append(f"")
    lines.append(f"## 6. 次回生成への改善提案")
    lines.append(f"")
    proposals = []
    # メタタグの中で比率1.3x以上のものを推奨
    for tag in ["has_number", "has_reversal", "has_concrete_quote", "has_authority", "has_risk", "has_kaishaku"]:
        on = [p["actual_views"] for p in matched if p["prediction"]["tags"][tag]]
        off = [p["actual_views"] for p in matched if not p["prediction"]["tags"][tag]]
        if on and off:
            on_med = statistics.median(on)
            off_med = statistics.median(off)
            if off_med > 0 and on_med / off_med >= 1.3:
                proposals.append(f"**{tag}** あり構造を増やす（比率 {on_med/off_med:.2f}x で伸びてる）")
            elif on_med > 0 and off_med / on_med >= 1.3:
                proposals.append(f"**{tag}** なし構造の方が伸びてる（比率 {off_med/on_med:.2f}x で逆転）→ 判定ロジック見直し")
    if proposals:
        for pr in proposals:
            lines.append(f"- {pr}")
    else:
        lines.append(f"- 有意な差分なし（データ不足 or 仮説と実績が一致）")

    return "\n".join(lines)


def append_prediction_history(actor, matched, db, latest_summary):
    """予想と実績のペアを prediction_history.json に追記する。

    詳細な蓄積方針は knowledge/shared/データ蓄積方法論.md を参照。
    ベイズ更新の発想（過去のペアを次の予想の事前知識として使う）／
    calibration（予想精度の時系列記録）／失敗予想の蓄積を実装する。
    """
    history_path = f"analytics/{actor}/prediction_history.json"
    if os.path.exists(history_path):
        try:
            history = json.load(open(history_path, encoding='utf-8'))
        except json.JSONDecodeError:
            history = {"history": []}
    else:
        history = {"history": []}

    # サイクルの calibration 指標を算出
    # 予想ランク別の実績中央値（S>A>B>C なら予想ロジックが機能している）
    rank_medians = {}
    for rank in ("S", "A", "B", "C"):
        vs = [m["actual_views"] for m in matched if m["prediction"]["predicted_rank"] == rank]
        if vs:
            rank_medians[rank] = statistics.median(vs)

    # 失敗予想（学習素材として最重要）の抽出
    # 弱い予想（C/B）なのに伸びた／強い予想（S/A）なのに伸びなかったポスト
    misses = []
    if matched:
        sorted_actual = sorted(matched, key=lambda p: p["actual_views"], reverse=True)
        if len(sorted_actual) >= 5:
            top_threshold = sorted_actual[len(sorted_actual) // 5]["actual_views"]
            bottom_threshold = sorted_actual[-len(sorted_actual) // 5]["actual_views"]
            for m in matched:
                rank = m["prediction"]["predicted_rank"]
                v = m["actual_views"]
                if rank in ("C", "B") and v >= top_threshold:
                    misses.append({"type": "weak_predicted_but_high", "rank": rank, "views": v, "text_head": m["text"][:80], "tags": m["prediction"]["tags"]})
                elif rank in ("S", "A") and v <= bottom_threshold:
                    misses.append({"type": "strong_predicted_but_low", "rank": rank, "views": v, "text_head": m["text"][:80], "tags": m["prediction"]["tags"]})

    today = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "cycle_date": today,
        "fetched_at": (db.get("history", [{}])[-1].get("fetched_at") if db.get("history") else None),
        "matched_count": len(matched),
        "rank_medians": rank_medians,
        "misses": misses,
        "pairs": [
            {
                "predicted_rank": m["prediction"]["predicted_rank"],
                "predicted_score": m["prediction"]["predicted_score"],
                "tags": m["prediction"]["tags"],
                "actual_views": m["actual_views"],
                "text_head": m["text"][:80],
            }
            for m in matched
        ],
    }
    # 同じcycle_dateのエントリがあれば置き換える（重複追記を防ぐ）。なければ新規追加
    replaced = False
    for i, h in enumerate(history["history"]):
        if h.get("cycle_date") == today:
            history["history"][i] = entry
            replaced = True
            break
    if not replaced:
        history["history"].append(entry)

    # 蓄積方法論メタ情報も保存
    history["_methodology_ref"] = "knowledge/shared/データ蓄積方法論.md"
    history["_last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    cumulative_pairs = sum(len(h.get("pairs", [])) for h in history["history"])
    cumulative_misses = sum(len(h.get("misses", [])) for h in history["history"])
    print(f"prediction_history 追記: {history_path}")
    print(f"  累計サイクル数: {len(history['history'])}")
    print(f"  累計マッチペア数: {cumulative_pairs}")
    print(f"  累計失敗予想数: {cumulative_misses}")


def main():
    if len(sys.argv) < 3:
        print("usage: python analyze_post_performance.py <演者名> <ranked_master.json>")
        sys.exit(1)

    actor = sys.argv[1]
    ranked_path = sys.argv[2]
    db_path = f"analytics/{actor}/posts_db.json"

    if not os.path.exists(db_path):
        print(f"DB未存在: {db_path} ← 先に fetch_threads_analytics.py を実行してください")
        sys.exit(1)

    if ranked_path in ("", "none", "null", "None") or not os.path.exists(ranked_path):
        print(f"master 未指定または未存在（{ranked_path}）→ 照合分析スキップ")
        sys.exit(0)
    try:
        master_data = json.load(open(ranked_path, encoding='utf-8'))
    except Exception as e:
        print(f"⚠ master 読み込み失敗: {e} → 照合分析スキップ")
        sys.exit(0)
    planned = master_data.get("posts")
    if not planned:
        print(f"⚠ master に posts キー無し（フォーマット不一致）→ 照合分析スキップ")
        sys.exit(0)
    db = json.load(open(db_path, encoding='utf-8'))

    matched, unmatched = match_posts(planned, db["posts"])
    print(f"マッチ: {len(matched)}/{len(planned)}本")

    # 統合データ保存
    out_dir = f"analytics/{actor}"
    matched_path = f"{out_dir}/matched_posts.json"
    json.dump({"matched": matched, "unmatched_count": len(unmatched)},
              open(matched_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(f"統合データ: {matched_path}")

    # レポート生成
    report = build_report(actor, matched, unmatched, len(planned), db, db.get("latest_summary"))
    report_path = f"{out_dir}/analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(report_path, 'w', encoding='utf-8') as fp:
        fp.write(report)
    print(f"レポート: {report_path}")
    print()
    print(report[:1500])

    # 蓄積処理：予想と実績のペアを prediction_history.json に追記
    # 蓄積方針は knowledge/shared/データ蓄積方法論.md を参照
    if matched:
        append_prediction_history(actor, matched, db, db.get("latest_summary"))


if __name__ == "__main__":
    main()
