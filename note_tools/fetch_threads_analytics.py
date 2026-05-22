# -*- coding: utf-8 -*-
"""
Threads-auto-af 成績取得スクリプト
==================================
ai-report API を叩いて、結果を analytics/ 配下に蓄積する。

使い方:
    python note_tools/fetch_threads_analytics.py <演者名> <token> [days]
    例: python note_tools/fetch_threads_analytics.py ハクオウ taf_837baa9ecacd4635b06f1ea5fc067472 7

出力:
    analytics/{演者名}/raw/{演者名}_aireport_{日付}_d{days}.json   生レスポンス
    analytics/{演者名}/posts_db.json                              個別ポスト成績DB（蓄積）
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_BASE = "https://threads-auto-af.vercel.app/api/v1"


def fookid(text):
    """フック1行目から安定ID（hook_improve.py と同じロジック）"""
    norm = re.sub(r'\s+', '', (text or ""))[:80]
    return "fookid_" + hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]


def fetch_ai_report(token, days):
    url = f"{API_BASE}/ai-report?days={days}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode('utf-8'))
    except HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        return None


def save_raw(data, actor, days):
    out_dir = f"analytics/{actor}/raw"
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{out_dir}/{actor}_aireport_{today}_d{days}.json"
    with open(path, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    return path


def update_posts_db(data, actor):
    """
    top_posts/bottom_posts から個別ポスト成績を抽出して posts_db.json に蓄積する。
    キーは text の最初の50字（postedAt と組み合わせてユニーク化）。
    """
    db_path = f"analytics/{actor}/posts_db.json"
    if os.path.exists(db_path):
        db = json.load(open(db_path, encoding='utf-8'))
    else:
        db = {"posts": {}, "history": []}

    fetch_meta = {
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "period_days": data.get("period_days"),
        "total_posts": data.get("total_posts"),
        "avg_impressions": data.get("avg_impressions"),
    }
    db["history"].append(fetch_meta)

    # top と bottom 両方を取り込む
    for category in ["top_posts", "bottom_posts"]:
        for p in data.get(category, []):
            text = p.get("text", "")
            posted_at = p.get("posted_at", "")
            key = f"{text[:60]}|{posted_at}"
            if key in db["posts"]:
                # 既存：最新のviewsで更新
                if p.get("views", 0) > db["posts"][key]["views"]:
                    db["posts"][key]["views"] = p["views"]
                    db["posts"][key]["last_seen_in"] = category
                    db["posts"][key]["last_fetched"] = fetch_meta["fetched_at"]
            else:
                db["posts"][key] = {
                    "text": text,
                    "posted_at": posted_at,
                    "views": p.get("views", 0),
                    "type": p.get("type", "unknown"),
                    "first_seen_in": category,
                    "last_seen_in": category,
                    "first_fetched": fetch_meta["fetched_at"],
                    "last_fetched": fetch_meta["fetched_at"],
                }

    # 集計データも保存
    db["latest_summary"] = {
        "fetched_at": fetch_meta["fetched_at"],
        "time_analysis": data.get("time_analysis"),
        "type_analysis": data.get("type_analysis"),
        "hooks_analysis": data.get("hooks_analysis"),
        "ai_summary": data.get("ai_summary"),
    }

    with open(db_path, 'w', encoding='utf-8') as fp:
        json.dump(db, fp, ensure_ascii=False, indent=2)
    return db_path, len(db["posts"])


def update_hook_archive(data, actor):
    """
    fetch した実績から hook_archive.json の各エントリの views を更新する。

    マッチング: text の先頭1行から fookid を計算 → hook_archive.hooks[fookid] があれば、
    history の中で views=null のエントリ（投稿は予約済みだが成績未集計）に views を記入する。
    複数回投稿してる場合は古いnullから順に埋める。
    """
    archive_path = f"analytics/{actor}/hook_archive.json"
    if not os.path.exists(archive_path):
        return None, 0
    try:
        with open(archive_path, encoding='utf-8') as f:
            archive = json.load(f)
    except json.JSONDecodeError:
        return archive_path, 0

    hooks = archive.get("hooks", {})
    if not hooks:
        return archive_path, 0

    updated = 0
    for category in ["top_posts", "bottom_posts"]:
        for p in data.get(category, []):
            text = p.get("text", "") or ""
            first_line = text.split("\n")[0]
            hid = fookid(first_line)
            if hid not in hooks:
                continue
            views = p.get("views", 0)
            posted_at = p.get("posted_at", "")
            history = hooks[hid].get("history", [])

            # views が既に同等以上の最新値で記録されてればスキップ（再fetchで views が上がる場合は更新する）
            existing_max = max([h.get("views") or 0 for h in history], default=0)
            if views <= existing_max:
                continue

            # views=null の最古エントリを埋める。無ければ最後のエントリを上書き
            target_idx = -1
            for i, h in enumerate(history):
                if h.get("views") is None:
                    target_idx = i
                    break
            if target_idx == -1 and history:
                target_idx = len(history) - 1  # 最新エントリの views を最新値で上書き

            if target_idx >= 0:
                history[target_idx]["views"] = views
                if posted_at:
                    history[target_idx]["posted_at"] = posted_at
                updated += 1

    if updated > 0:
        with open(archive_path, 'w', encoding='utf-8') as fp:
            json.dump(archive, fp, ensure_ascii=False, indent=2)

    return archive_path, updated


def main():
    if len(sys.argv) < 3:
        print("usage: python fetch_threads_analytics.py <演者名> <token> [days=7]")
        sys.exit(1)

    actor = sys.argv[1]
    token = sys.argv[2]
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    print(f"=== {actor} 成績取得 (days={days}) ===")
    data = fetch_ai_report(token, days)
    if data is None:
        print("API取得失敗")
        sys.exit(1)

    raw_path = save_raw(data, actor, days)
    print(f"raw保存: {raw_path}")

    db_path, n = update_posts_db(data, actor)
    print(f"DB更新: {db_path} (蓄積{n}件)")
    print(f"今回サマリー:")
    print(f"  総投稿数: {data.get('total_posts')}")
    print(f"  平均インプ: {data.get('avg_impressions')}")
    print(f"  top: {len(data.get('top_posts', []))}件 / bottom: {len(data.get('bottom_posts', []))}件")

    # フック単位の蓄積（hook_archive.json）も更新
    archive_path, updated = update_hook_archive(data, actor)
    if archive_path:
        print(f"hook_archive更新: {archive_path} ({updated}件のフックに views 記録)")


if __name__ == "__main__":
    main()
