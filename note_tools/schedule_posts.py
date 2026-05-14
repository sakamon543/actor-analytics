#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ポスト予約投稿スクリプト
========================
next_batch.json を読んで threads-auto-af に予約投稿する。

使い方:
    python note_tools/schedule_posts.py <演者名> <token>
"""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_BASE = "https://threads-auto-af.vercel.app/api/v1"


def load_batch(actor):
    path = os.path.join(ROOT, f"analytics/{actor}/next_batch.json")
    if not os.path.exists(path):
        return None, path
    with open(path, encoding='utf-8') as f:
        return json.load(f), path


def convert_to_api_format(batch):
    """next_batch.json → threads-auto-af POST形式に変換"""
    api_posts = []
    for p in batch.get("posts", []):
        post = {
            "text": p["text"],
            "scheduled_at": p["scheduled_at"],
        }
        if p.get("thread"):
            post["thread"] = p["thread"]
        api_posts.append(post)
    return {"posts": api_posts}


def post_to_api(token, payload):
    url = f"{API_BASE}/posts"
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=data, method='POST', headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode('utf-8')), res.status
    except HTTPError as e:
        body = e.read().decode('utf-8')[:500]
        return {"error": body}, e.code


def main():
    if len(sys.argv) < 3:
        print("usage: python note_tools/schedule_posts.py <演者名> <token>")
        sys.exit(1)

    actor = sys.argv[1]
    token = sys.argv[2]

    batch, path = load_batch(actor)
    if batch is None:
        print(f"next_batch.json が見つかりません: {path}")
        sys.exit(1)

    n_posts = len(batch.get("posts", []))
    print(f"[schedule] {actor}: {n_posts}本を予約投稿")

    payload = convert_to_api_format(batch)
    result, status = post_to_api(token, payload)

    if status == 200 or status == 201:
        print(f"  ✓ 予約完了 (HTTP {status})")
        if isinstance(result, dict):
            print(f"  レスポンス: {json.dumps(result, ensure_ascii=False)[:300]}")
    else:
        print(f"  ✗ 予約失敗 (HTTP {status})")
        print(f"  エラー: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
