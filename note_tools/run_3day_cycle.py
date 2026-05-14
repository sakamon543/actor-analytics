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
import yaml
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_YAML = os.path.join(ROOT, "アカウント帳簿総合.yaml")
JST = timezone(timedelta(hours=9))


def load_accounts():
    with open(ACCOUNTS_YAML, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return [a for a in data["accounts"] if a.get("enabled")]


def get_token(account):
    """環境変数から token 取得"""
    token_env = account["token_env"]
    token = os.environ.get(token_env)
    if not token:
        print(f"  ⚠ 環境変数 {token_env} 未設定 → スキップ")
        return None
    return token


def run_fetch(account, token):
    name = account["name"]
    cmd = ["python", os.path.join(ROOT, "note_tools/fetch_threads_analytics.py"),
           name, token, "7"]
    print(f"  [fetch] {' '.join(cmd[:3])} <token> 7")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ fetch失敗: {result.stderr[:300]}")
        return False
    print(f"  ✓ fetch完了")
    return True


def run_analyze(account):
    name = account["name"]
    master = account["master"]
    cmd = ["python", os.path.join(ROOT, "note_tools/analyze_post_performance.py"),
           name, master]
    print(f"  [analyze] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ analyze失敗: {result.stderr[:300]}")
        return False
    print(f"  ✓ analyze完了")
    return True


def is_completed(account):
    """end_dateを過ぎているか（YAMLが date 型を返すケースに対応）"""
    end_date_str = str(account["end_date"])
    end_date = datetime.fromisoformat(end_date_str).replace(tzinfo=JST)
    return datetime.now(tz=JST) > end_date


def run_hook_improve(account):
    """フック分析＋次バッチ自動生成（Claude API）"""
    name = account["name"]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  ⚠ ANTHROPIC_API_KEY 未設定 → hook_improve スキップ")
        return False
    cmd = ["python", os.path.join(ROOT, "note_tools/hook_improve.py"), name]
    print(f"  [hook_improve] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ hook_improve失敗:")
        print(result.stderr)
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
        return False
    cmd = ["python", os.path.join(ROOT, "note_tools/schedule_posts.py"), name, token]
    print(f"  [schedule] {name}: 予約投稿中...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"  ✗ schedule失敗:")
        print(result.stderr)
        return False
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            print(f"    {line}")
    print(f"  ✓ schedule完了")
    return True


def main():
    print(f"=== 3日サイクル開始: {datetime.now(tz=JST).isoformat()} ===\n")

    if not os.path.exists(ACCOUNTS_YAML):
        print(f"ERROR: {ACCOUNTS_YAML} が見つかりません")
        sys.exit(1)

    accounts = load_accounts()
    print(f"対象演者: {len(accounts)}件\n")

    for account in accounts:
        name = account["name"]
        print(f"--- {name} ---")
        token = get_token(account)
        if not token:
            continue

        # 1. fetch
        if not run_fetch(account, token):
            continue

        # 2. analyze
        run_analyze(account)

        # 3. hook_improve（フック分析＋次バッチ生成）
        if run_hook_improve(account):
            # 4. schedule（生成したバッチを予約投稿）
            run_schedule(account, token)

        print()

    print(f"=== 3日サイクル完了: {datetime.now(tz=JST).isoformat()} ===")


if __name__ == "__main__":
    main()
