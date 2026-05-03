# AIキット 図解生成ルール（全ジャンル対応）

> **このルールの役割**
> コンテンツ作成ルールのPhase 2で図解画像を生成する際のデザイン仕様書。
> ジャンルを問わず使える汎用ルール。恋愛でもビジネスでも育児でもスピでも、**何にでも対応する**。
> AIが自らWeb検索でそのジャンルの最適なデザインを調べ、コンセプトに合った配色と世界観で図解を作る。

---

## 0. 前提

- 図解は `generate_image` ツール（またはGemini API）で生成する
- 1回に2枚以上同時生成しない（精度が激落ちする）
- レター3個＋コンテンツ10〜11個＝計13〜14個の図解を生成する
- **1記事内の全図解は必ず同じデザインテーマで統一すること**

---

## 1. デザイン構築フロー（毎回これを実行）

固定のカラーパレットを使うのではなく、**ジャンル × コンセプト × ターゲットに合わせてAIが動的にデザインを決定する。**

### STEP1：Web検索でデザインリサーチ

`search_web` で以下を検索し、そのジャンルで実際に使われている「高品質なデザインの傾向」を把握する。

**検索クエリの例：**
- `[ジャンル名] インフォグラフィック デザイン 高級感`
- `[ジャンル名] note サムネイル 人気`
- `[ジャンル名] 本 表紙デザイン トレンド`
- `[ジャンル名] ブログ 図解 おしゃれ`
- `[ターゲット層] 好む デザイン 色`

例：
- 恋愛系 → `恋愛系 女性向け デザイン ピンク パステル おしゃれ`
- ビジネス → `ビジネス 副業 インフォグラフィック ダーク 高級感`
- スピリチュアル → `占い スピリチュアル 神秘的 デザイン パープル`
- 育児 → `育児 ママ向け デザイン ナチュラル 温かみ`
- 筋トレ → `筋トレ フィットネス デザイン スポーティー`
- 英語学習 → `英語学習 教育 デザイン クリーン`

**最低2〜3クエリは検索すること。** リサーチなしでデザインを決めるのは禁止。

### STEP2：デザインテーマを決定

Web検索の結果を元に、以下の項目を全て決定する。

```
【デザインテーマ】
ジャンル：
コンセプト名：
ターゲット層：（年齢・性別・雰囲気）

【配色】
背景グラデーション起点：# （色名）
背景グラデーション終点：# （色名）
背景パターン：（何を散らすか。例：ハート、星、幾何学、葉、月、ダイヤ、なし）
背景パターン色：# （ごく薄い）
タイトル色：# （目立つが品がある）
バッジ色：# （STEP等のラベル）
アクセント色：# （ゴールド系が安全）
カード背景色：#FFFFFF or カスタム
カードボーダー色：# （強調用。グロウ or 薄ボーダー）

【スタイルフレーズ】
Style: [ここにジャンルの雰囲気を一文で記述。例: "Premium feminine blog style, romantic and elegant"]

【装飾要素】
使用する装飾アイコン：（例：♡ ✦ 👑 ✨ ◆ 🍃 ☽ etc.）
使用しない装飾：（例：回路基板パターン、コインマーク等）

【背景テンプレート】
BACKGROUND: [文章で背景指示を記述。全プロンプトにコピペする]
```

**デザイン決定の基準：**
- ターゲットが「この記事ちゃんとしてるな」と思えるクオリティ
- 情報商材のギラギラしたデザインにしない
- そのジャンルの王道の本・ブログ・SNSで使われてる雰囲気に合わせる
- コンセプトのトーン（ズルい、本格的、繊細、etc.）をデザインに反映する

### STEP3：テスト画像を1枚生成

デザインテーマが決まったら、まず1枚だけテスト生成する。
パターンAのフロー図で試す。

生成結果を見て以下をチェック：
- 背景のグラデーションと装飾パターンが出ているか
- 日本語テキストが読めるか
- カードの角丸とシャドウがあるか
- 全体の雰囲気がジャンルに合っているか

問題なければ残りの12〜13枚を生成する。
問題があればデザインテーマを調整して再テスト。

---

## 2. 4パターンのプロンプトテンプレート

### パターンA：フロー図（左→右の流れ）

STEP系の説明・変化のプロセスを見せるときに使う。

```
Premium infographic diagram for a [ジャンル] advice blog article about [テーマ]. 16:9 landscape ratio, 1920x1080 feel.

[STEP2で決めた背景テンプレートをコピペ]

TITLE (top center):
- Main title in bold [タイトル色]: "[欲求喚起タイトル]"
- Thin [アクセント色] accent line below title

MAIN FLOW (center, left to right with [テーマカラー] gradient arrows):

Card 1 (left):
- White rounded card with soft shadow
- [アイコン] icon
- Bold: "[状態A or ステップ名]"
- Smaller: "[具体的なアクション]"

Arrow ([テーマカラー] gradient) →

Card 2 (center, slightly larger with [ボーダー色] glow border):
- [アイコン] icon
- Bold: "[状態B or 変化]"
- Smaller: "[内容]"

Arrow →

Card 3 (right, with subtle [アクセント色] sparkle border):
- [アイコン] icon
- Bold: "[理想の状態 or 結果]"
- Smaller: "[ベネフィット]"

BOTTOM: Highlighted callout badge with [アクセント色] border:
"[読者メリットを一言で]"

[STEP2で決めたスタイルフレーズ]. All Japanese text crisp and perfectly legible. Noto Sans JP typeface. No photographs, no people.
```

### パターンB：比較図（ビフォー・アフター / 間違いvs正解）

```
Premium infographic diagram comparing [比較テーマ]. 16:9 landscape ratio, 1920x1080 feel.

[背景テンプレートをコピペ]

TITLE (top center):
- Main title in bold [タイトル色]: "[比較タイトル]"
- Thin [アクセント色] accent line below

LEFT COLUMN - [左ラベル（NG例・ビフォー）]:
- Soft gray or muted tone (less vibrant)
- Header: "[左ラベル]"
- Content card:
  - "[特徴1]"
  - "[特徴2]"
- Result: ❌ or sad icon at bottom

CENTER: "VS" in a circular badge with [アクセント色] border

RIGHT COLUMN - [右ラベル（OK例・アフター）]:
- Vibrant, recommended tone
- Header: "[右ラベル]" with ✨ icon
- Content card (with [ボーダー色] glow border):
  - "[特徴1]"
  - "[特徴2]"
- Result: ✨ or check icon at bottom

BOTTOM: [アクセント色] accent callout: "[結論メッセージ]"

[スタイルフレーズ]. All Japanese text crisp and perfectly legible. Noto Sans JP typeface. No photographs, no people.
```

### パターンC：循環図（繰り返しのメカニズム）

```
Premium infographic diagram showing a cyclical process about [テーマ]. 16:9 landscape ratio, 1920x1080 feel.

[背景テンプレートをコピペ]

TITLE (top center):
- Main title in bold [タイトル色]: "[循環テーマ]"
- Thin [アクセント色] accent line

CIRCULAR FLOW (clockwise, 4 cards connected by [テーマカラー] gradient arrows):

Top card:
- [アイコン] icon
- Bold: "[ステップA]"
- Smaller: "[詳細]"

Right card (highlighted with [アクセント色] glow border):
- [アイコン] icon
- Bold: "[ステップB]"
- Smaller: "[詳細]"

Bottom card:
- [アイコン] icon
- Bold: "[ステップC]"
- Smaller: "[詳細]"

Left card:
- [アイコン] icon
- Bold: "[ステップD]"
- Smaller: "[詳細]"

CENTER of the circle: "[核となるコンセプト]" in large text with [アクセント色] sparkle accent

BOTTOM: [アクセント色] badge: "[最大メリット]"

[スタイルフレーズ]. All Japanese text crisp and perfectly legible. Noto Sans JP typeface. No photographs, no people.
```

### パターンD：ヒーロー図解（冒頭インパクト・章概要）

```
Premium infographic, 16:9 landscape, 1920x1080 feel.

[背景テンプレートをコピペ]

TITLE (top center, LARGE, bold [タイトル色]):
"[インパクトのあるヘッドライン]"
Subtitle in muted [サブ色]: "[補足テキスト]"

MAIN CONTENT:
[章構成・特典・ステップを並べる。白いカード型が基本]

Each item is a white rounded card with soft shadow:
- Step number or icon in a [バッジ色] or [アクセント色] circle
- Bold label: "[内容]"
- Small supporting text in gray

BOTTOM: Wide [アクセント色] banner spanning width:
"[最大の価値提案メッセージ]"

Decorative elements: [STEP2で決めた装飾要素]

[スタイルフレーズ]. All Japanese text crisp and perfectly legible. Noto Sans JP typeface. No photographs, no people.
```

---

## 3. テキスト内容の設計ルール

### タイトル（図の上部）＝ 欲求喚起

読者が「おっ」と思う感情に刺さるコピーを入れる。
コンテンツのキーフレーズをそのまま使う。

### ラベル（カード内のテキスト）＝ 具体的アクション・状態

事実ベース。何の図解かがパッと分かるように。
**ラベルは10文字以内が理想。長くても20文字。**

### バッジ（下部のアクセント枠）＝ 読者メリット

読者にとっての最大メリットを一言で。

---

## 4. レター用マーカーの図解内容目安

| 配置場所 | 推奨パターン | 内容 |
|----------|------------|------|
| 序盤マーカー（悩み列挙・問題提起の後） | 比較図B | NG vs OK の行動比較 |
| 中盤マーカー（商品全体像の冒頭） | ヒーローD | 全体ロードマップ |
| 後半マーカー（行動喚起・締め） | フローA | 変化のプロセス（今→変化→理想） |

---

## 5. コンテンツ用図解の配置ルール

コンテンツには10〜11個の図解を配置する。

### マーカー導入文のルール

・本文の流れに合った自然な一文にすること
・記事内でユニークであること（他の箇所と被らない）
・40文字以内が望ましい
・鍵かっこ「」や特殊記号を含まない方が安全
・マーカーは単独行で配置し、前後に改行を入れること

### 推奨パターンの割り振り

10〜11個の図解をパターンA〜Dで分散させる。同じパターンが3回以上連続しないようにする。

| 推奨配分 | パターン | 個数 |
|----------|---------|------|
| フローA | STEP・変化・手順 | 3〜4個 |
| 比較B | NG vs OK・Before/After | 3〜4個 |
| 循環C | サイクル・ループ | 1〜2個 |
| ヒーローD | 全体MAP・章概要 | 1〜2個 |

---

## 6. 文字化け防止ルール

・文字数は極限まで減らす（日本語のみ）
・英語表記は禁止
・説明文は一切入れない
・「タイトル（短め）」＋「日本語キーワード2〜3個」程度
・要素を詰め込みすぎない

---

## 7. 絶対ルール

### 全プロンプトに必ず入れること

- `No photographs, no people`
- `All Japanese text must be crisp and perfectly legible`
- `16:9 landscape ratio, 1920x1080 feel`
- STEP2で決めたスタイルフレーズ
- STEP2で決めた背景テンプレート

### 絶対にやらないこと

- 写真や人物を入れない
- 情報商材のギラギラしたデザイン → NG
- ジャンルに合わないデザイン要素（恋愛系にテック感、スピ系にビジネス感 etc.） → NG
- 1回に2枚以上同時生成しない
- 英語だけの図解はNG。日本語テキスト必須
- 原色の赤・青・黄色、黒すぎる背景、ネオンカラー → NG
- デザインリサーチ（STEP1）をスキップしない

---

## 8. 品質チェックリスト（生成後に毎回確認）

- [ ] 背景にSTEP2で決めたグラデーション＋装飾パターンがあるか
- [ ] 日本語テキストが全て読めるか
- [ ] カードに角丸＋ソフトシャドウがあるか
- [ ] タイトルが目立っているか
- [ ] アクセントカラーの要素があるか
- [ ] 文字量が多すぎないか
- [ ] 写真や人物が混ざっていないか
- [ ] ジャンル外のデザイン要素が混入していないか
- [ ] 16:9の横長比率になっているか
- [ ] 1記事内の全図解で統一感があるか

---

## 9. よくある失敗と対処法

| 症状 | 原因 | 対処 |
|------|------|------|
| テック感が出る | 背景指示が合ってない | STEP1に戻ってリサーチし直す |
| 背景が真っ白 | 背景テンプレートを省略 | 必ずコピペで入れる |
| 文字が読めない | ラベルが長すぎ | ラベル10文字以内 |
| 雰囲気がバラバラ | 背景指示が毎回違う | STEP2で決めた背景を全画像で使い回す |
| 情報商材っぽい | ゴールドを使いすぎ | ゴールドはアクセントのみ。メインに使わない |
| ジャンルに合ってない | STEP1のリサーチが足りない | 追加で2〜3クエリ検索する |
| ターゲットに刺さらない | コンセプトのトーンを反映してない | コンセプト名・USPを見直してデザインに反映 |
