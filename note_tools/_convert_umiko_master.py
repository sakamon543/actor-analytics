# -*- coding: utf-8 -*-
"""
うみこ master を ハクオウ形式（analyze互換）に変換する一回ぽっきりスクリプト。

変換内容:
    - トップレベルキー「全100本」→「posts」にrename
    - 各ポストに text フィールドを hook + main で埋める

実行後、predict_post_rank.py で prediction フィールドを付与する。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "accounts/うみこ/master_100posts_ranked.json")

with open(PATH, encoding='utf-8') as f:
    data = json.load(f)

# 1. キーrename
if "全100本" in data:
    posts = data["全100本"]
    del data["全100本"]
elif "posts" in data:
    print("既に posts キーになってる → スキップ")
    posts = data["posts"]
else:
    print("ERROR: 全100本もpostsも見つからない")
    sys.exit(1)

# 2. 各ポストに text フィールド埋め（hook + "\n" + main）
fixed = 0
for p in posts:
    text = p.get("text") or ""
    if not text.strip():
        hook = p.get("hook") or ""
        main = p.get("main") or ""
        p["text"] = (hook + "\n" + main).strip() if (hook or main) else ""
        fixed += 1

data["posts"] = posts

with open(PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"変換完了: {len(posts)}本中 {fixed}本の text を埋めた")
print(f"出力: {PATH}")
