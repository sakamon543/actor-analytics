# -*- coding: utf-8 -*-
"""
予想ランク付与スクリプト
========================
ポストJSONを読み込み、各ポストに「予想ランクS/A/B/C」＋「メタタグ」を付与する。
答え合わせ（実績との照合）の土台。

使い方:
    python note_tools/predict_post_rank.py <input.json> <output.json>

メタタグ:
    has_number      数字（11倍／9割／50件／3週間 等）が含まれるか
    has_reversal    反転表現（逆効果／真逆／9割は嘘 等）が含まれるか
    has_concrete_quote 具体セリフ「」or『』が含まれるか
    has_authority   権威ワード（臨床心理士／1000人／相談者で 等）が含まれるか
    has_risk        リスク提示（このまま動かないと／手遅れ／致命傷 等）が含まれるか
    has_kaishaku    解釈モデル破壊（〇〇って嘘／間違い／誤解／通説 等）が含まれるか
    hook_length     第1文の文字数

ランクロジック:
    S: 6要素中5以上揃い、hook 15-50字
    A: 4要素揃い
    B: 3要素揃い
    C: 2要素以下
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

NUMBER_RE = re.compile(r'\d+[倍ヶ年月週日時%人件本回件]|半数以上|半数|9割|圧倒的|半分|3週間|7日|7倍|10倍|11倍|98%|1000人|50件|50人|断トツ|過半数|大半|ほぼ全員|ほぼ100')
REVERSAL_RE = re.compile(r'逆効果|真逆|9割は嘘|半分嘘|嘘だ|間違い|誤解|迷信|半分間違|半分は|9割誤読|致命傷|裏目|逆')
QUOTE_RE = re.compile(r'[「『][^」』]{2,}[」』]')
AUTHORITY_RE = re.compile(r'臨床心理士|公認心理師|1000人|相談者|復縁した男たち|心理学的に|10年|追跡|見てきた|男たちに片っ端から')
RISK_RE = re.compile(r'このまま|動かないと|手遅れ|致命傷|失う|消える|過去化|諦めの形成期|完全に過去|戻れない|難易度.*跳ね上が|永遠に|3ヶ月経つ頃|新しい彼女|難しくなる')
KAISHAKU_RE = re.compile(r'って通説|って助言|って言われる|って言われて|って復縁界|って復縁|って思って|常識|通説|アドバイス')


def evaluate(text):
    """ポスト本文を評価してメタタグとランクを返す"""
    first_sent = text.split('。')[0] + '。'
    full = text  # メイン全文で評価

    tags = {
        "has_number": bool(NUMBER_RE.search(full)),
        "has_reversal": bool(REVERSAL_RE.search(full)),
        "has_concrete_quote": bool(QUOTE_RE.search(full)),
        "has_authority": bool(AUTHORITY_RE.search(full)),
        "has_risk": bool(RISK_RE.search(full)),
        "has_kaishaku": bool(KAISHAKU_RE.search(full)),
        "hook_length": len(first_sent),
        "main_length": len(text),
    }

    score = sum(1 for k in ["has_number", "has_reversal", "has_concrete_quote",
                            "has_authority", "has_risk", "has_kaishaku"] if tags[k])

    # ランク判定
    if score >= 5 and 15 <= tags["hook_length"] <= 50:
        rank = "S"
    elif score >= 4:
        rank = "A"
    elif score >= 3:
        rank = "B"
    else:
        rank = "C"

    # 予想理由（短く）
    reasons = []
    if tags["has_number"]: reasons.append("数字")
    if tags["has_reversal"]: reasons.append("反転")
    if tags["has_concrete_quote"]: reasons.append("具体セリフ")
    if tags["has_authority"]: reasons.append("権威")
    if tags["has_risk"]: reasons.append("リスク提示")
    if tags["has_kaishaku"]: reasons.append("解釈モデル破壊")
    reason_str = "／".join(reasons) if reasons else "弱要素"

    return {
        "predicted_rank": rank,
        "predicted_score": score,
        "tags": tags,
        "reason": reason_str,
    }


def main():
    if len(sys.argv) < 3:
        print("usage: python predict_post_rank.py <input.json> <output.json>")
        sys.exit(1)

    inp, out = sys.argv[1], sys.argv[2]
    data = json.load(open(inp, encoding='utf-8'))

    rank_count = {"S": 0, "A": 0, "B": 0, "C": 0}
    for p in data['posts']:
        ev = evaluate(p['text'])
        p['prediction'] = ev
        rank_count[ev['predicted_rank']] += 1

    # ファイル先頭にメタ追加
    data['予想ランク分布'] = rank_count
    data['予想ランク付与日'] = "2026-05-04"
    data['予想ランクロジック'] = "6メタタグ（数字／反転／具体セリフ／権威／リスク提示／解釈モデル破壊）の合致数 + hook字数で判定"

    json.dump(data, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    print(f"完了: {len(data['posts'])}本評価")
    print(f"分布: S={rank_count['S']} A={rank_count['A']} B={rank_count['B']} C={rank_count['C']}")
    print(f"出力: {out}")


if __name__ == "__main__":
    main()
