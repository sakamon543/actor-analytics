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
import json
import os
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_BASE = "https://threads-auto-af.vercel.app/api/v1"


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


if __name__ == "__main__":
    main()
