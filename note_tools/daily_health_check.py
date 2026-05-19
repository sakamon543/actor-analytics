# -*- coding: utf-8 -*-
"""
日次ヘルスチェック（全演者集約サマリをLINEに1通だけ送信）
========================================================
毎朝VPS cronで起動。enabled な全演者について次をチェックし、
異常 / 警告 / 正常 に分類して1メッセージで通知する。

チェック項目:
    [異常] cycle 停止（last_cycle_at が STALE_DAYS 日以上更新なし）
    [異常] fetch 停止（posts_db.json の最後 fetched_at が STALE_DAYS 日以上更新なし）
    [警告] インプ下落（直近 WINDOW ポスト平均 vs 前 WINDOW ポスト平均で -DROP_RATIO 以下）

使い方:
    python note_tools/daily_health_check.py
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

# 閾値
STALE_DAYS = 5         # 3日サイクル+2日猶予。これ以上更新が無ければ異常
DROP_RATIO = 0.30      # 直近平均が前期平均から -30% 以下なら警告
WINDOW = 10            # 比較ウィンドウ（直近10ポスト vs その前10ポスト）


def load_accounts():
    if not os.path.exists(ACCOUNTS_YAML):
        return []
    with open(ACCOUNTS_YAML, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return [a for a in data.get("accounts", []) if a.get("enabled")]


def cycle_elapsed_days(actor, today):
    p = os.path.join(ROOT, f"analytics/{actor}/cycle_state.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            state = json.load(f)
    except json.JSONDecodeError:
        return None
    last = state.get("last_cycle_at")
    if not last:
        return None
    try:
        last_date = datetime.fromisoformat(str(last)).date()
    except ValueError:
        return None
    return (today - last_date).days


def posts_db_status(actor, today):
    """戻り値: (fetch_elapsed_days or None, drop_ratio or None)"""
    p = os.path.join(ROOT, f"analytics/{actor}/posts_db.json")
    if not os.path.exists(p):
        return None, None
    try:
        with open(p, encoding='utf-8') as f:
            db = json.load(f)
    except json.JSONDecodeError:
        return None, None

    history = db.get("history", [])
    last_fetched_days = None
    if history:
        last_fetched = history[-1].get("fetched_at")
        if last_fetched:
            try:
                # "+09:00" を含む可能性に備える
                date_part = last_fetched.split("T")[0]
                last_fetched_date = datetime.fromisoformat(date_part).date()
                last_fetched_days = (today - last_fetched_date).days
            except ValueError:
                pass

    drop = None
    posts = list(db.get("posts", {}).values())
    posts.sort(key=lambda x: x.get("posted_at", ""), reverse=True)
    if len(posts) >= WINDOW * 2:
        recent = posts[:WINDOW]
        prev = posts[WINDOW:WINDOW * 2]
        avg_recent = sum(p.get("views", 0) for p in recent) / WINDOW
        avg_prev = sum(p.get("views", 0) for p in prev) / WINDOW
        if avg_prev > 0:
            drop = (avg_recent - avg_prev) / avg_prev

    return last_fetched_days, drop


def main():
    now = datetime.now(tz=JST)
    today = now.date()
    accounts = load_accounts()

    if not accounts:
        send_text("enabledアカなし。帳簿確認を。")
        return

    abnormal = []  # [(name, [msg, ...])]
    warning = []
    normal = []

    for a in accounts:
        name = a["name"]
        critical_msgs = []
        warn_msgs = []

        elapsed = cycle_elapsed_days(name, today)
        if elapsed is not None and elapsed > STALE_DAYS:
            critical_msgs.append(f"cycle停止{elapsed}日")

        fetch_days, drop = posts_db_status(name, today)
        if fetch_days is not None and fetch_days > STALE_DAYS:
            critical_msgs.append(f"fetch停止{fetch_days}日")
        if drop is not None and drop <= -DROP_RATIO:
            warn_msgs.append(f"インプ{int(drop * 100)}%")

        if critical_msgs:
            abnormal.append((name, critical_msgs + warn_msgs))
        elif warn_msgs:
            warning.append((name, warn_msgs))
        else:
            normal.append(name)

    total = len(accounts)

    # 全部正常なら1行で終わり
    if not abnormal and not warning:
        text = f"{total}アカ 正常稼働中"
    else:
        lines = [f"異常{len(abnormal)} 警告{len(warning)} 正常{len(normal)}（{total}アカ）"]
        if abnormal:
            lines.append("")
            lines.append("■異常")
            for name, msgs in abnormal:
                lines.append(f" {name} {' '.join(msgs)}")
        if warning:
            lines.append("")
            lines.append("■警告")
            for name, msgs in warning:
                lines.append(f" {name} {' '.join(msgs)}")
        text = "\n".join(lines)

    ok = send_text(text)
    print(text)
    print("LINE送信:", "OK" if ok else "FAIL")


if __name__ == "__main__":
    main()
