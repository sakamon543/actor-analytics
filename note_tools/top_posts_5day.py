# -*- coding: utf-8 -*-
"""
5日ごと上位ポスト通知（演者別Top3）
=====================================
毎日VPS cronで起動するが、state ファイルで「最後の送信から5日経過」を判定し、
未経過なら即終了。経過していたら全演者の Top3 ポストを1メッセージで送る。

state ファイル:
    analytics/_global/top_posts_state.json
    { "last_sent_at": "YYYY-MM-DD" }

使い方:
    python note_tools/top_posts_5day.py            # 自動判定（5日経過時のみ送信）
    python note_tools/top_posts_5day.py --force    # 強制送信（state無視）
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
import yaml

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "note_tools"))
from notify_line import send_text  # noqa: E402

JST = timezone(timedelta(hours=9))
ACCOUNTS_YAML = os.path.join(ROOT, "アカウント帳簿総合.yaml")
STATE_PATH = os.path.join(ROOT, "analytics/_global/top_posts_state.json")
INTERVAL_DAYS = 5
TOP_N = 3
TEXT_PREVIEW_LEN = 40  # ポスト先頭表示文字数


def load_accounts():
    if not os.path.exists(ACCOUNTS_YAML):
        return []
    with open(ACCOUNTS_YAML, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return [a for a in data.get("accounts", []) if a.get("enabled")]


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_top_posts(actor, n=TOP_N):
    p = os.path.join(ROOT, f"analytics/{actor}/posts_db.json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding='utf-8') as f:
            db = json.load(f)
    except json.JSONDecodeError:
        return []
    posts = list(db.get("posts", {}).values())
    posts.sort(key=lambda x: x.get("views", 0), reverse=True)
    return posts[:n]


def truncate_text(text, n=TEXT_PREVIEW_LEN):
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


def main():
    force = "--force" in sys.argv
    now = datetime.now(tz=JST)
    today = now.date()

    state = load_state()
    last_sent = state.get("last_sent_at")
    if last_sent and not force:
        try:
            last_date = datetime.fromisoformat(str(last_sent)).date()
            elapsed = (today - last_date).days
            if elapsed < INTERVAL_DAYS:
                print(f"前回送信 {last_date} から {elapsed}日経過 → 未満なのでスキップ（{INTERVAL_DAYS}日経過で送信）")
                return
        except ValueError:
            pass

    accounts = load_accounts()
    if not accounts:
        print("enabled演者なし → 何もしない")
        return

    lines = [f"{INTERVAL_DAYS}日のTop3"]
    # 演者の最高インプ降順で並べ替え（伸びてる演者から上に来る）
    actor_blocks = []
    for a in accounts:
        name = a["name"]
        tops = get_top_posts(name, TOP_N)
        if not tops:
            actor_blocks.append((0, name, [f"■{name}", " データなし（fetch未完了）"]))
            continue
        block = [f"■{name}"]
        for i, p in enumerate(tops, 1):
            views = p.get("views", 0)
            preview = truncate_text(p.get("text", ""))
            block.append(f" {i}) {views} {preview}")
        max_views = tops[0].get("views", 0)
        actor_blocks.append((max_views, name, block))

    actor_blocks.sort(key=lambda x: x[0], reverse=True)
    for _, _, block in actor_blocks:
        lines.append("")
        lines.extend(block)

    text = "\n".join(lines)
    ok = send_text(text)
    print(text)
    print("LINE送信:", "OK" if ok else "FAIL")

    if ok:
        state["last_sent_at"] = today.isoformat()
        save_state(state)


if __name__ == "__main__":
    main()
