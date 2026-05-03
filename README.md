# hakuoo-analytics

ハクオウ（@hakuoo96）アカウントのThreadsポスト成績を自動取得・分析するリポジトリ。
リモートエージェント（cron）で毎日09:00 JSTに動作する想定。

## 構成

```
hakuoo-analytics/
├ note_tools/
│  ├ fetch_threads_analytics.py    成績取得（threads-auto-af の ai-report 叩く）
│  ├ analyze_post_performance.py   仮説 vs 実績の照合分析
│  └ predict_post_rank.py          予想ランク付与（生成直後に1回だけ）
├ data/
│  └ ハクオウ_post_master_100posts_ranked.json  仮説ランク付き計画100本
└ analytics/
   └ ハクオウ/
      ├ posts_db.json              成績蓄積DB
      ├ raw/                       ai-report の生レスポンス（日別）
      └ analysis_{日付}.md         分析レポート
```

## 自動運用

### 毎日09:00 JST（cron）

```bash
python note_tools/fetch_threads_analytics.py ハクオウ <token> 7
git add analytics/
git commit -m "data: 成績取得 $(date +%Y-%m-%d)"
git push
```

### 5/14以降（投稿完走の翌日）

```bash
python note_tools/analyze_post_performance.py ハクオウ data/ハクオウ_post_master_100posts_ranked.json
git add analytics/
git commit -m "report: 100本完走分析"
git push
```

## ローカルでの手動実行

```bash
# 成績取得
python note_tools/fetch_threads_analytics.py ハクオウ taf_xxxxx 7

# 分析
python note_tools/analyze_post_performance.py ハクオウ data/ハクオウ_post_master_100posts_ranked.json
```

## 投稿期間

2026-05-04 11:08 〜 2026-05-13 23:58（10日間×1日10本＝100本）

## 関連

- 投稿元：threads-auto-af（https://threads-auto-af.vercel.app）
- 演者：ハクオウ（@hakuoo96）
- 100本生成元：ナレッジ本体の `恋愛系AIポスト作成` Skill
