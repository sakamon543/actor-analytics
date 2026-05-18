# -*- coding: utf-8 -*-
"""
LINE Messaging API Push 通知ラッパー
====================================
他の note_tools/*.py から import して使う共通ラッパー。

環境変数:
    LINE_CHANNEL_ACCESS_TOKEN   LINE Messaging API の長期アクセストークン
    LINE_USER_ID                送信先ユーザーID（U で始まる33文字）
    ALL_SECRETS_JSON            （フォールバック）全Secretsを1変数に流す方式

使い方（モジュール）:
    from note_tools.notify_line import send_text
    send_text("[Health 2026-05-19] 50演者中 異常2 / 警告3 / 正常45")

使い方（CLI・テスト）:
    python note_tools/notify_line.py "テストメッセージ"
"""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_TEXT_LIMIT = 4900  # LINE仕様5000字。安全マージン取って4900


def _load_from_all_secrets(key):
    raw = os.environ.get("ALL_SECRETS_JSON")
    if not raw:
        return None
    try:
        return json.loads(raw).get(key)
    except json.JSONDecodeError:
        return None


def get_credentials():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or _load_from_all_secrets("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID") or _load_from_all_secrets("LINE_USER_ID")
    return token, user_id


def send_text(text, user_id=None, token=None):
    """LINEにテキスト通知を送る。成功:True / 失敗:False"""
    if not token or not user_id:
        t, u = get_credentials()
        token = token or t
        user_id = user_id or u
    if not token or not user_id:
        print("[notify_line] LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定", file=sys.stderr)
        return False

    # LINEの1メッセージ上限超えたら分割
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:LINE_TEXT_LIMIT])
        remaining = remaining[LINE_TEXT_LIMIT:]
    # LINE Push は1リクエストで messages 最大5件
    chunks = chunks[:5]

    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": c} for c in chunks],
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(PUSH_URL, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urlopen(req, timeout=30) as res:
            res.read()
            return True
    except HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')[:500]
        print(f"[notify_line] HTTP {e.code}: {body_text}", file=sys.stderr)
        return False
    except URLError as e:
        print(f"[notify_line] URLError: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[notify_line] error: {e}", file=sys.stderr)
        return False


def send_error(actor, where, detail):
    """異常即時アラート用の整形ヘルパー。"""
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    now = datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M")
    text = f"[ERROR] {actor} {now}\n{where}\n{detail[:1500]}"
    return send_text(text)


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "[test] notify_line.py 動作確認"
    ok = send_text(text)
    print("OK" if ok else "FAIL")
    sys.exit(0 if ok else 1)
