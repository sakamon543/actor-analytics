# actor-analytics（仮ディレクトリ名: hakuoo-analytics）

恋愛系演者の Threads ポスト運用を**3日サイクルで自動改善し続ける**リポジトリ。

リモートエージェント（cron）が3日に1回起動して、全演者の成績取得→分析→次の30本生成→投稿予約を自動で回す。

## 設計思想

- **アカウントごとにrepo作らない**：1リポジトリで全演者をカバー
- **演者追加 = `アカウント帳簿総合.yaml` に1行追記するだけ**
- **人間介入は月次の方針見直しのみ**、日々の運用は完全自動

## 構成

```
.
├ アカウント帳簿総合.yaml                演者リスト（追加するだけで自動運用に乗る）
├ accounts/                    演者別のデータ・設定
│  ├ ハクオウ/
│  │  ├ アカウント設定.md
│  │  ├ master_100posts_ranked.json
│  │  ├ posts_db.json           成績蓄積（cronで更新）
│  │  └ analysis_{日付}.md       分析レポート（cronで生成）
│  └ {新演者}/...
├ skills/                       恋愛系AIポスト作成スキル一式（routineが参照）
├ aikit/                        AIキット（note貼り付け／図解生成等）
├ materials/                    バズ素材プール（CSV／実例集）
└ note_tools/
   ├ run_3day_cycle.py         routineエントリ（cronで呼ばれる）
   ├ fetch_threads_analytics.py 成績取得（threads-auto-af の ai-report）
   ├ analyze_post_performance.py 仮説 vs 実績の照合分析
   └ predict_post_rank.py       予想ランク付与（生成直後に1回）
```

## 自動運用サイクル（3日に1回）

```
[Day 1〜3]
  threads-auto-af 経由で1日10本×3日＝30本投稿
  
[Day 4 09:00 JST] ← routine 起動
  1. fetch: 各演者の直近成績を取得 → posts_db.json 蓄積
  2. analyze: 予想ランク vs 実績インプを照合
     - メタタグ別の伸び率（数字／反転／具体セリフ／権威／リスク／解釈モデル破壊）
     - 仮説外しのリスト（Cと予想したのに伸びた等）
     - 自動改善提案
  3. 完走判定: end_date を過ぎていれば next_generation_needed.txt マーカー
  4. git commit & push（履歴と分析結果が永続蓄積）
```

LLMは routine の cron でも呼ばれない（純 Python）。Anthropic API 課金ゼロ運用。

## 演者追加手順

1. `accounts/{新演者}/` ディレクトリを作成
2. `アカウント設定.md` `master_*.json` を配置
3. `アカウント帳簿総合.yaml` に1ブロック追加（既存ハクオウをコピーして書き換え）
4. routine 環境変数に `{新演者大文字}_TOKEN` を追加（threads-auto-af tokenを設定）
5. git push

これだけで次の routine 実行から自動的にループに乗る。

## ローカルでの手動実行

```bash
# 環境変数で token 設定
export HAKUOO_TOKEN=taf_xxxxxxxxxxxxxx
# 全演者ループ
python note_tools/run_3day_cycle.py
```

## 関連

- 投稿元：threads-auto-af（https://threads-auto-af.vercel.app）
- 100本生成元：`skills/恋愛系AIポスト作成_SKILL.md`（恋愛系演者運用の統括Skill）
