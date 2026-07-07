# -*- coding: utf-8 -*-
"""
3日サイクル run（routineエントリポイント）
==========================================
アカウント帳簿総合.yaml を読んで、enabled: true の全演者について以下を実行：

1. fetch: threads-auto-af の ai-report 取得 → posts_db.json 蓄積
2. analyze: 仮説 vs 実績の照合分析 → analysis_{日付}.md 出力
3. （end_date を過ぎてれば）次の30本生成タスクをマーカーとして残す

routine prompt はこのスクリプトの実行 + git commit & push を担当する。
LLM要素はこのスクリプト内には無い（純Python）。

使い方（手動）:
    python note_tools/run_3day_cycle.py

使い方（routine内）:
    cd /workspace
    python note_tools/run_3day_cycle.py
    git add -A
    git commit -m "cycle: $(date +%Y-%m-%d)"
    git push
"""
import os
import sys
import json
import subprocess
import time
import yaml
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_YAML = os.path.join(ROOT, "アカウント帳簿総合.yaml")
JST = timezone(timedelta(hours=9))

# LINE 通知（失敗しても本処理を止めない）
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from notify_line import send_text as _line_send, send_error as _line_send_error
except Exception:
    def _line_send(text):
        return False
    def _line_send_error(actor, where, detail):
        return False


def load_accounts():
    with open(ACCOUNTS_YAML, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return [a for a in data["accounts"] if a.get("enabled")]


def get_token(account):
    """環境変数から token 取得。
    優先順: (1) 直接env var、(2) ALL_SECRETS_JSON 内のキー。
    GitHub Actions では toJSON(secrets) で全Secretsを1変数に流せるので、
    新アカウントを追加してもワークフローYAMLの編集が要らない。
    """
    token_env = account["token_env"]
    token = os.environ.get(token_env)
    if token:
        return token
    all_secrets_raw = os.environ.get("ALL_SECRETS_JSON")
    if all_secrets_raw:
        try:
            all_secrets = json.loads(all_secrets_raw)
            token = all_secrets.get(token_env)
            if token:
                return token
        except json.JSONDecodeError:
            pass
    print(f"  ⚠ 環境変数 {token_env} 未設定（ALL_SECRETS_JSON にも無し） → スキップ")
    return None


def run_fetch(account, token):
    name = account["name"]
    cmd = [sys.executable, os.path.join(ROOT, "note_tools/fetch_threads_analytics.py"),
           name, token, "7"]
    print(f"  [fetch] {' '.join(cmd[:3])} <token> 7")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ fetch失敗:")
        print(result.stderr)
        # 401 / トークン期限切れ等は即時アラート
        combined = (result.stdout or "") + (result.stderr or "")
        if "HTTP 401" in combined or "HTTP 403" in combined:
            _line_send_error(name, "fetch_threads_analytics.py", "HTTP 401/403 → token期限切れの可能性。GitHub Secretsの " + account.get("token_env", "?") + " を確認。")
        else:
            _line_send_error(name, "fetch_threads_analytics.py", (result.stderr or "")[:300])
        return False
    print(f"  ✓ fetch完了")
    return True


def run_analyze(account):
    name = account["name"]
    master = account.get("master") or "none"
    cmd = [sys.executable, os.path.join(ROOT, "note_tools/analyze_post_performance.py"),
           name, master]
    print(f"  [analyze] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ analyze失敗:")
        print(result.stderr)
        _line_send_error(name, "analyze_post_performance.py", (result.stderr or "")[:300])
        return False
    print(f"  ✓ analyze完了")
    return True


def is_completed(account):
    """end_dateを過ぎているか（YAMLが date 型を返すケースに対応）"""
    end_date_str = str(account["end_date"])
    end_date = datetime.fromisoformat(end_date_str).replace(tzinfo=JST)
    return datetime.now(tz=JST) > end_date


def cycle_state_path(actor):
    return os.path.join(ROOT, f"analytics/{actor}/cycle_state.json")


def load_cycle_state(actor):
    p = cycle_state_path(actor)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_cycle_state(actor, state):
    p = cycle_state_path(actor)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def should_run_today(account, today):
    """このアカウントを今日サイクル実行すべきか判定。
    - last_cycle_at が記録あり: today - last_cycle_at >= 3日
    - 初回（記録なし）: today >= start_date（当日から即起動。ドロップイン即運用を可能にする）"""
    state = load_cycle_state(account["name"])
    last_cycle = state.get("last_cycle_at")
    if last_cycle:
        last_date = datetime.fromisoformat(str(last_cycle)).date()
        return (today - last_date).days >= 3, f"前回サイクル {last_date} から{(today - last_date).days}日経過"
    start_date = datetime.fromisoformat(str(account["start_date"])).date()
    diff = (today - start_date).days
    return today >= start_date, f"初回サイクル: start_date {start_date} から {diff}日経過"


def mark_cycle_completed(actor, today):
    state = load_cycle_state(actor)
    state["last_cycle_at"] = today.isoformat()
    save_cycle_state(actor, state)


def run_hook_improve(account):
    """フック分析＋次バッチ自動生成（Claude Code経由）"""
    name = account["name"]
    cmd = [sys.executable, os.path.join(ROOT, "note_tools/hook_improve.py"), name]
    print(f"  [hook_improve] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        err = (result.stderr or "")[:500]
        print(f"  ✗ hook_improve失敗:")
        print(result.stderr)
        # Claude Code の認証期限切れ検知（stdoutのJSONに認証エラーが入る）
        combined = (result.stdout or "") + (result.stderr or "")
        if ("401" in combined and ("authenticate" in combined.lower() or "credential" in combined.lower())) \
                or "Invalid authentication credentials" in combined \
                or "Failed to authenticate" in combined:
            _line_send_error(
                name,
                "hook_improve.py (Claude Code 401)",
                "VPS の Claude Code credentials が期限切れ。Claude Code に「VPS復旧して」と言ってください。"
            )
        else:
            _line_send_error(name, "hook_improve.py", err or (result.stdout or "")[:500])
        return False
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            print(f"    {line}")
    print(f"  ✓ hook_improve完了")
    return True


def run_schedule(account, token):
    """生成したバッチを threads-auto-af に予約投稿"""
    name = account["name"]
    batch_path = os.path.join(ROOT, f"analytics/{name}/next_batch.json")
    if not os.path.exists(batch_path):
        print(f"  ⚠ next_batch.json なし → schedule スキップ")
        _line_send_error(name, "schedule_posts.py", "next_batch.json なし。hook_improve が生成失敗してる可能性。")
        return False
    cmd = [sys.executable, os.path.join(ROOT, "note_tools/schedule_posts.py"), name, token]
    print(f"  [schedule] {name}: 予約投稿中...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        err = (result.stderr or "")[:500]
        print(f"  ✗ schedule失敗:")
        print(result.stderr)
        combined = (result.stdout or "") + (result.stderr or "")
        if "HTTP 401" in combined or "HTTP 403" in combined:
            _line_send_error(name, "schedule_posts.py", "HTTP 401/403 → token期限切れの可能性。")
        else:
            _line_send_error(name, "schedule_posts.py", err)
        return False
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            print(f"    {line}")
    print(f"  ✓ schedule完了")
    return True


def main():
    now = datetime.now(tz=JST)
    today = now.date()
    print(f"=== 3日サイクル開始: {now.isoformat()} ===\n")

    if not os.path.exists(ACCOUNTS_YAML):
        print(f"ERROR: {ACCOUNTS_YAML} が見つかりません")
        _line_send_error("system", "run_3day_cycle.py", f"{ACCOUNTS_YAML} が見つかりません")
        sys.exit(1)

    accounts = load_accounts()
    print(f"enabled演者: {len(accounts)}件\n")

    ran_count = 0
    skipped_count = 0
    cycle_results = []  # 演者別 [(name, status_text)]

    for account in accounts:
        name = account["name"]
        should_run, reason = should_run_today(account, today)
        if not should_run:
            print(f"--- {name} スキップ ---")
            print(f"  理由: {reason}（3日未満なのでサイクル不要）")
            print()
            skipped_count += 1
            continue

        print(f"--- {name} 実行 ---")
        print(f"  判定: {reason}")
        token = get_token(account)
        if not token:
            cycle_results.append((name, "TOKEN_MISSING"))
            _line_send_error(name, "run_3day_cycle.py", f"環境変数 {account.get('token_env')} 未設定")
            continue

        steps = []
        # 1. fetch
        ok_fetch = run_fetch(account, token)
        steps.append("fetch:" + ("OK" if ok_fetch else "NG"))
        if not ok_fetch:
            cycle_results.append((name, " / ".join(steps)))
            continue

        # 2. analyze
        ok_analyze = run_analyze(account)
        steps.append("analyze:" + ("OK" if ok_analyze else "NG"))

        # 3. hook_improve（フック分析＋次バッチ生成）
        #    一時的なclaude -p失敗（レート制限・瞬間的な認証リフレッシュ等）に備えて最大2回試行
        ok_hook = run_hook_improve(account)
        if not ok_hook:
            print(f"  ↻ hook_improve 1回目失敗 → 30秒待ってリトライ")
            time.sleep(30)
            ok_hook = run_hook_improve(account)
        steps.append("hook:" + ("OK" if ok_hook else "NG"))

        ok_sched = False
        if ok_hook:
            # 4. schedule（生成したバッチを予約投稿）
            ok_sched = run_schedule(account, token)
            steps.append("sched:" + ("OK" if ok_sched else "NG"))

        ran_count += 1
        # 完了マーキング：★生成→予約まで成功した時だけ★ cycle_state を進める。
        # 失敗した演者は cycle_state を据え置き＝翌日のcronで自動リトライされる（沈黙を防ぐ）。
        if ok_hook and ok_sched:
            mark_cycle_completed(name, today)
        else:
            print(f"  ⚠ {name}: 生成/予約が未完 → cycle_stateを進めない（翌日のcronで自動リトライ）")
        cycle_results.append((name, " / ".join(steps)))
        print()

    end_ts = datetime.now(tz=JST)
    print(f"=== 3日サイクル完了: {end_ts.isoformat()} ===")
    print(f"  実行: {ran_count}件 / スキップ: {skipped_count}件")

    # サイクル完了の集約通知（実行0件の日は送らない）
    if ran_count > 0:
        ng_count = sum(1 for _, s in cycle_results if "NG" in s or "TOKEN_MISSING" in s)
        if ng_count == 0:
            text = f"{ran_count}アカのサイクル完了 全工程OK"
        else:
            lines = [f"{ran_count}アカのサイクル完了 異常{ng_count}"]
            for name, status in cycle_results:
                mark = "■" if "NG" not in status and "TOKEN_MISSING" not in status else "✗"
                lines.append(f"{mark}{name} {status}")
            text = "\n".join(lines)
        _line_send(text)


if __name__ == "__main__":
    main()
