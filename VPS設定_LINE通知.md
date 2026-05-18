# VPS設定手順：LINE通知（Phase A）

Phase A（LINE通知システム）を VPS に乗せる手順。SSH接続して上から順に実行する。

## 前提

- VPS：さくらVPS石狩、Ubuntu 24.04
- リポジトリ：`actor-analytics`（GitHub `sakamon543/actor-analytics`）が VPS にクローン済
- VPS上のリポジトリパス：以下では仮に `~/actor-analytics` とする（実際の配置に応じて変更）
- 既に毎日09:00 JSTに `run_3day_cycle.py` を走らせる cron が動作中

---

## 1. リポジトリを最新化

```bash
cd ~/actor-analytics
git pull origin main
```

push 済の以下ファイルが取り込まれる：
- `note_tools/notify_line.py`
- `note_tools/daily_health_check.py`
- `note_tools/top_posts_5day.py`
- `note_tools/run_3day_cycle.py`（既存ファイルに通知呼び出しを追加した版）

---

## 2. 環境変数を設定（2通りのどちらかでOK）

### 方式A：`.env` ファイル方式（推奨・シンプル）

```bash
# ~/actor-analytics/.env または ~/.env に追記
echo 'export LINE_CHANNEL_ACCESS_TOKEN="（チャネルアクセストークン）"' >> ~/.env
echo 'export LINE_USER_ID="U509dbad8586b868a7ebd0e72275a5f80"' >> ~/.env
chmod 600 ~/.env  # 秘密情報なので所有者のみ読み取り可
```

### 方式B：GitHub Secrets 経由（既存 ALL_SECRETS_JSON 仕組みを使う場合）

- GitHub: https://github.com/sakamon543/actor-analytics/settings/secrets/actions/new
- Name: `LINE_CHANNEL_ACCESS_TOKEN` / Value: チャネルアクセストークン
- Name: `LINE_USER_ID` / Value: U509dbad8586b868a7ebd0e72275a5f80

→ 既存の cron / run_loop.sh が `ALL_SECRETS_JSON` を組み立てて渡している場合はこちらで動く。

> どちらか一方でOK。両方やってもOK（直接env varが優先）。

---

## 3. 既存 run_loop.sh が `.env` を読むか確認

```bash
cat ~/run_loop.sh
```

冒頭に `source ~/.env` 等の記述が**無い**場合は、追加する：

```bash
# 例：run_loop.sh の冒頭付近
#!/bin/bash
[ -f ~/.env ] && source ~/.env
export LINE_CHANNEL_ACCESS_TOKEN LINE_USER_ID
cd ~/actor-analytics
# ... 既存処理 ...
```

これで `run_3day_cycle.py` の中の `_line_send` / `_line_send_error` がLINEに飛ぶ。

---

## 4. 健康診断 + Top通知用のラッパーシェルを作成

```bash
cat > ~/run_health.sh << 'EOF'
#!/bin/bash
[ -f ~/.env ] && source ~/.env
export LINE_CHANNEL_ACCESS_TOKEN LINE_USER_ID
cd ~/actor-analytics

# 健康診断（毎日）
python3 note_tools/daily_health_check.py >> ~/cron_health.log 2>&1

# Top通知（state管理で実質5日毎）
python3 note_tools/top_posts_5day.py >> ~/cron_top_posts.log 2>&1
EOF

chmod +x ~/run_health.sh
```

---

## 5. cron に登録

```bash
crontab -e
```

以下を追加（既存の `0 9 * * * ~/run_loop.sh` はそのまま残す）：

```cron
# Phase A：毎朝08:30 JSTにLINE健康診断＋Top通知（state判定で5日毎）
30 8 * * * /home/ubuntu/run_health.sh
```

保存して終了。設定確認：

```bash
crontab -l
```

---

## 6. 動作確認

VPS上で各スクリプトを手動実行してLINEに通知が来るか確認：

```bash
cd ~/actor-analytics

# notify_line 単体テスト
python3 note_tools/notify_line.py "[VPS Test] LINE通知 動作確認"

# 健康診断テスト
python3 note_tools/daily_health_check.py

# Top通知（state未送信なら送信、送信済なら何もしない。強制送信は --force）
python3 note_tools/top_posts_5day.py --force
```

それぞれLINEに通知が届けばPhase A完成。

---

## トラブル時

| 症状 | 対処 |
|---|---|
| `[notify_line] LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定` | `echo $LINE_CHANNEL_ACCESS_TOKEN` で空。.env を source できてない |
| `HTTP 400 The property, 'messages[0].text', is invalid` | ローカルbashの文字エンコ事故。Python実行なら起きないはず。VPSのlocale確認 `locale` |
| `HTTP 401 Invalid channel access token` | トークンが切れた／違う。LINE Developers Consoleで再発行 |
| LINEに届かない | Botを友だち追加済みか確認。ブロックされてないか |

---

## Phase B（Webダッシュボード）に進む前のクリーンアップ

トークンをチャットに貼った場合は、Phase A 完成後に LINE Developers Console で**チャネルアクセストークン再発行**してローテーション。再発行後に `.env` ＋ GitHub Secrets の値も更新。
