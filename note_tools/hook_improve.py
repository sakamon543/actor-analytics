#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フック分析＋次バッチ自動生成（2段階処理版）
==========================================
3日サイクルの analyze 後に実行。

Phase 1: posts_db.json + hook_archive.json + 恋愛系フックスキル
         から「フック30本（1行目のみ）」を1回の呼び出しで生成
Phase 2: フック1本ずつ、恋愛系ポスト作成スキル本体に従って本文生成
         （30回シーケンシャル・並列はしない）

設計の核（必読）:
- フックを当てて、そのフックで恋愛系ポスト作成スキルを起動する仕組みを
  自動化したもの。リライトモードの自動版。
- アカウント情報総合管理.md は商品情報＋演者の事実だけの参照。テンプレ強制しない。
- evaluation_criteria は内部チェックのみ。本文に書き込まない。
- target_research はターゲット素材として参考に。セクション番号を本文に引用しない。
- 「読者をプレイヤー（当事者）として扱う」「同じ語彙の連発禁止」を最優先ルールとして明記。
- 蓄積は hook_archive.json（フック単位の投稿履歴）で行う＝再投稿の追跡。

使い方:
    python note_tools/hook_improve.py <演者名>
"""
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))

SCHEDULE_TEMPLATE = [
    (11, 8), (13, 17), (14, 42),
    (18, 3), (19, 17), (19, 52),
    (20, 28), (21, 3), (22, 17), (22, 48),
]

# ===== v2投稿構成（2026-06-13 ユーザー指示）=====
# 対象6演者は1日9本：短文(≤80字)×3 ＋ 中文(~180字)×3 ＋ ぶら下げ付き(メイン80字+ぶら下げ150〜200字)×3。
# 誘導(note直リンク)を入れるのは「ぶら下げ付き(thread_cta)」3本だけ。短文・中文はCTAなし。
# ハクオウ・うみこ等この集合に無い演者は従来どおり（1日10本・全ポストにぶら下げ＋CTA）。
V2_ACTORS = {"リクオウ", "みさき", "りお", "ホンネ", "ヒロ", "ハカセ", "miho", "みき", "みな", "りさ", "りょう", "あや", "かれん"}
V2_PER_DAY = 9
# note誘導(thread_cta)と単発を半々程度に（note誘導5＋単発4）。note誘導は1日の中に散らす。
V2_DAY_PLAN = ["thread_cta", "short80", "thread_cta", "mid180", "thread_cta",
               "short80", "thread_cta", "mid180", "thread_cta"]
# 誘導先（note直リンク）。プロフ誘導ではなく投稿のCTAにこのURLを直接貼る。
NOTE_URLS = {
    "リクオウ": "https://note.com/novel_lotus9919/n/ne79a6cc58623",
    "みさき": "https://note.com/owaseru_misaki/n/n785d4a4409d3",
    "りお": "https://note.com/witty_cougar4536/n/nd6f64511a7e3",
    "ホンネ": "https://note.com/cool_abelia8956/n/n8c42924cc652",
    "ヒロ": "https://note.com/eager_llama3480/n/nbb7c579fa140",
    "ハカセ": "https://note.com/dend11/n/nf40a8f8f1b06",
}

# Phase 1（フック生成）で読み込むスキル本体＋素材プール
# 「変数選定の3段階フロー」（Step1 素材実例集 → Step2 観察ワード → Step3 新規生成）の
# Step1/2 を実行するために素材ファイル群を必ず渡す。AIの想像で変数を埋めるのは禁止。
HOOK_SKILL_FILES = [
    "skills/思考スキル_フック作成.md",
    "skills/パターン集_フック細分化v2.md",
    "materials/素材実例集_CSV由来.md",
    "materials/恋愛ダスト_分析用.csv",
]

# Phase 2（本文生成）で読み込むスキル本体（恋愛系特化）
BODY_SKILL_FILES = [
    "skills/スキル_恋愛ポスト作成AI.md",
    "skills/判断軸_恋愛ポスト作成.md",
    "skills/思考スキル_本文作成.md",
    "skills/思考スキル_統括_売れる教育ポスト.md",
    "skills/口調文体ルール_一般人感.md",
]

# ===== 丸ごとリサイクル（2026-07-05 阪本さん指示）=====
# 「伸びたポストは丸ごと保存して、1ヶ月ごとにそのまま再投稿」。生成ゼロ＝品質実証済みの弾。
RECYCLE_VIEWS_THRESHOLD = 2000   # この views 以上で recycle_pool に自動昇格
RECYCLE_COOLDOWN_DAYS = 30       # 同じポストを再投稿するまでの間隔
RECYCLE_MAX_USES = 3             # 同じポストの再投稿上限（飽き対策）
RECYCLE_PER_DAY = 2              # 1日に混ぜる丸ごと再投稿の本数（プールが薄ければ自動で減る）

# ===== 収集フック（x_scraperの実績フック・2026-07-05 阪本さん指示）=====
# 「1〜2行目は実際に伸びた人間のフックをそのまま。本文はスキルで生成」。
# プールは全演者共通（materials/hook_pool_scraped.json）。x-to-threads の収集から push される。
SCRAPED_POOL_PATH = "materials/hook_pool_scraped.json"
SCRAPED_PER_DAY = 4              # 1日に使う収集フックの本数（プールが薄ければ自動で減る）


# ============== I/O ヘルパー ==============

def load_text(path, optional=False):
    if not os.path.exists(path):
        if optional:
            return ""
        raise FileNotFoundError(path)
    with open(path, encoding='utf-8') as f:
        return f.read()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default if default is not None else {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def fookid(text):
    """フック1行目から安定ID生成。同一フックは同一IDになる。"""
    norm = re.sub(r'\s+', '', (text or ""))[:80]
    return "fookid_" + hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]


# ============== スケジュール ==============

def find_next_start_date(posts_db, prev_batch_path=None):
    tomorrow = datetime.now(tz=JST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    candidates = [tomorrow]

    latest_posted = None
    for p in posts_db.get("posts", {}).values():
        try:
            dt = datetime.fromisoformat(p["posted_at"]).astimezone(JST)
            if latest_posted is None or dt > latest_posted:
                latest_posted = dt
        except (ValueError, KeyError):
            continue
    if latest_posted:
        candidates.append((latest_posted + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))

    if prev_batch_path and os.path.exists(prev_batch_path):
        try:
            with open(prev_batch_path, encoding='utf-8') as f:
                prev = json.load(f)
            latest_scheduled = None
            for p in prev.get("posts", []):
                sa = p.get("scheduled_at")
                if not sa:
                    continue
                dt = datetime.fromisoformat(sa).astimezone(JST)
                if latest_scheduled is None or dt > latest_scheduled:
                    latest_scheduled = dt
            if latest_scheduled:
                candidates.append((latest_scheduled + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        except (json.JSONDecodeError, ValueError):
            pass

    return max(candidates)


def generate_schedule(start_date, days=3, per_day=10):
    slots = []
    for d in range(days):
        day = start_date + timedelta(days=d)
        for i, (h, m) in enumerate(SCHEDULE_TEMPLATE[:per_day]):
            dt = day.replace(hour=h, minute=m, second=0, microsecond=0)
            slots.append(dt.isoformat())
    return slots


# ============== 実績データ抽出 ==============

def extract_performance_data(posts_db, hook_archive, top_n=15, bottom_n=10):
    """
    実績データから「伸びたフック」「伸びなかったフック」「再現性確認済みフック」を抽出する。
    PDCAのインプット。
    """
    posts = posts_db.get("posts", {})
    items = []
    for key, p in posts.items():
        first_line = (p.get("text", "") or "").split("\n")[0]
        items.append({
            "hook": first_line,
            "views": p.get("views", 0),
            "posted_at": p.get("posted_at", ""),
        })
    items.sort(key=lambda x: x["views"], reverse=True)
    top_hooks = items[:top_n]
    bottom_hooks = items[-bottom_n:] if len(items) >= bottom_n else []

    # hook_archive から「2回以上投稿していて、平均が一定以上のフック」を抽出（再現性確認済み）
    proven_hooks = []
    for hid, entry in hook_archive.get("hooks", {}).items():
        history = [h for h in entry.get("history", []) if h.get("views") is not None]
        if len(history) >= 2:
            views_list = [h["views"] for h in history]
            avg = sum(views_list) / len(views_list)
            if avg >= 1500:
                proven_hooks.append({
                    "hook": entry["text"],
                    "rounds": len(history),
                    "avg_views": avg,
                    "structure": entry.get("structure_label", "unknown"),
                })
    proven_hooks.sort(key=lambda x: x["avg_views"], reverse=True)

    return top_hooks, bottom_hooks, proven_hooks


# ============== 丸ごとリサイクル ==============

def collect_thread_sources(analytics_dir):
    """過去の生成バッチ（next_batch.json / _gen_*.json / phase2_test_*.json）から
    fookid → {text, thread} を復元する。posts_db には thread が保存されてないため。"""
    import glob
    sources = {}
    patterns = [os.path.join(analytics_dir, "next_batch.json"),
                os.path.join(analytics_dir, "_gen_*.json"),
                os.path.join(analytics_dir, "phase2_test_*.json")]
    for pat in patterns:
        for path in glob.glob(pat):
            data = load_json(path, {})
            for p in data.get("posts", []):
                text = p.get("text", "")
                if not text:
                    continue
                hid = fookid(text.split("\n")[0])
                # 同じフックが複数バッチにある場合、thread があるものを優先
                if hid not in sources or (p.get("thread") and not sources[hid].get("thread")):
                    sources[hid] = {"text": text, "thread": p.get("thread") or []}
    return sources


def promote_recycle_pool(actor, posts_db, analytics_dir):
    """posts_db から views>=閾値 のポストを recycle_pool.json に自動昇格する。
    thread は過去の生成バッチから復元（できなければ text 単発として登録）。"""
    pool_path = os.path.join(analytics_dir, "recycle_pool.json")
    pool = load_json(pool_path, {"actor": actor, "items": {}})
    items = pool.setdefault("items", {})
    thread_sources = collect_thread_sources(analytics_dir)

    added = 0
    for p in posts_db.get("posts", {}).values():
        views = p.get("views", 0) or 0
        text = p.get("text", "") or ""
        if views < RECYCLE_VIEWS_THRESHOLD or not text.strip():
            continue
        hid = fookid(text.split("\n")[0])
        rid = "rcyc_" + hid.replace("fookid_", "")
        src = thread_sources.get(hid, {})
        if rid in items:
            # views の最新値だけ更新（最高値を保持）
            if views > items[rid].get("first_seen_views", 0):
                items[rid]["first_seen_views"] = views
            continue
        items[rid] = {
            "recycle_id": rid,
            "text": src.get("text") or text,   # バッチ由来の完全版text優先（posts_dbは切れてる場合がある）
            "thread": src.get("thread") or [],
            "first_seen_views": views,
            "first_seen_at": p.get("posted_at", ""),
            "status": "ready",
            "used_count": 0,
            "last_used_at": None,
        }
        added += 1
    pool["updated_at"] = datetime.now(tz=JST).isoformat()
    save_json(pool_path, pool)
    return pool, pool_path, added


def select_recycle_items(pool, max_count):
    """クールダウン明け＆使用上限内のアイテムを views 降順で max_count 本選ぶ。"""
    now = datetime.now(tz=JST)
    ready = []
    for it in pool.get("items", {}).values():
        if it.get("used_count", 0) >= RECYCLE_MAX_USES:
            continue
        last = it.get("last_used_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=JST)
                if (now - last_dt).days < RECYCLE_COOLDOWN_DAYS:
                    continue
            except ValueError:
                pass
        ready.append(it)
    ready.sort(key=lambda x: x.get("first_seen_views", 0), reverse=True)
    # 同じ冒頭（類似ポスト）が同一バッチに2本入らないよう、1行目の先頭30字でデデュープ
    seen_heads = set()
    deduped = []
    for it in ready:
        head = re.sub(r'\s+', '', (it.get("text", "") or "").split("\n")[0])[:30]
        if head in seen_heads:
            continue
        seen_heads.add(head)
        deduped.append(it)
    return deduped[:max_count]


def mark_recycle_used(analytics_dir, used_ids):
    pool_path = os.path.join(analytics_dir, "recycle_pool.json")
    pool = load_json(pool_path, {"items": {}})
    today = datetime.now(tz=JST).isoformat()
    for rid in used_ids:
        it = pool.get("items", {}).get(rid)
        if it:
            it["used_count"] = it.get("used_count", 0) + 1
            it["last_used_at"] = today
            it["status"] = "used"
    pool["updated_at"] = today
    save_json(pool_path, pool)


# ============== 収集フックプール（scraped） ==============

def load_scraped_pool():
    return load_json(os.path.join(ROOT, SCRAPED_POOL_PATH), {"hooks": []})


SCRAPED_MAX_ACTORS = 2        # 同一フックを使える演者は通算2人まで
SCRAPED_CROSS_COOLDOWN = 3    # 他演者が使ってから3日以上空ける

# 男性当事者として語る演者（一人称=僕/俺）。ここに無い演者は女性当事者（一人称=私）扱い。
MALE_ACTORS = {"ハクオウ", "ホンネ", "ヒロ", "ハカセ", "リクオウ", "りょう"}

_QUOTED_RE = re.compile(r"[「『][^」』]*[」』]")


def voice_mismatch(hook_text, actor):
    """収集フックの語り手の性別が演者と食い違っていないか判定する。

    収集フックは「実績文言なので一字も変えない」運用のため、男性演者から集めた
    「僕も振った彼女が〜」をそのまま女性演者のメインに置くと一人称が壊れる
    （2026-07-23に かれん/あや/miho で実際に発生）。カギ括弧内は彼のセリフ引用＝
    正常なので除外し、地の文の一人称だけを見る。"""
    bare = _QUOTED_RE.sub("", hook_text or "")
    male = re.search(r"僕|俺", bare)
    female = re.search(r"私|あたし", bare)
    if actor in MALE_ACTORS:
        return bool(female) and not male    # 男性演者の地の文に「私」だけ＝女性演者のフック
    return bool(male)                       # 女性演者の地の文に「僕/俺」＝男性演者のフック


def select_scraped_hooks(pool, actor, max_count):
    """この演者が未使用の収集フックを選ぶ（演者間の被り制御込み・2026-07-11改修）。
    - 同一フックは通算 SCRAPED_MAX_ACTORS 演者まで
    - 他演者の使用から SCRAPED_CROSS_COOLDOWN 日以上空ける
    - views降順トップ固定取りをやめ、上位プールからランダム抽選（同日実行の演者間で自然に散らす）
    - 2人目の使用には _second_use フラグ（プロンプト側で語尾リライト指示）"""
    today = datetime.now(tz=JST).date()
    avail = []
    for h in pool.get("hooks", []):
        if not (h.get("first_lines") or "").strip():
            continue
        if voice_mismatch(h.get("first_lines"), actor):
            continue                          # 語り手の性別が演者と食い違うフックは使わない
        ub = h.get("used_by") or {}
        if actor in ub:
            continue                          # 同演者の再利用禁止（従来通り）
        if len(ub) >= SCRAPED_MAX_ACTORS:
            continue                          # 通算上限
        recent = False
        for d in ub.values():
            try:
                if (today - datetime.fromisoformat(str(d)).date()).days < SCRAPED_CROSS_COOLDOWN:
                    recent = True
                    break
            except (ValueError, TypeError):
                pass
        if recent:
            continue                          # 他演者が直近3日以内に使用→見送り
        hh = dict(h)                          # プール本体を汚さないようコピーに印を付ける
        hh["_second_use"] = len(ub) >= 1
        avail.append(hh)
    avail.sort(key=lambda x: x.get("views", 0), reverse=True)
    top = avail[:max(max_count * 3, max_count)]
    if len(top) <= max_count:
        return top
    return random.sample(top, max_count)


def mark_scraped_used(pool, used_pool_ids, actor):
    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    for h in pool.get("hooks", []):
        if h.get("pool_id") in used_pool_ids:
            h.setdefault("used_by", {})[actor] = today
    pool["updated_at"] = datetime.now(tz=JST).isoformat()
    save_json(os.path.join(ROOT, SCRAPED_POOL_PATH), pool)


# ============== Claude Code 呼び出し ==============

def call_claude_code(full_prompt, timeout=600):
    process = subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=full_prompt,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=timeout,
    )
    if process.returncode != 0:
        err = f"returncode={process.returncode}\nstderr: {process.stderr[:1500]}\nstdout: {process.stdout[:1500]}"
        return None, err
    try:
        cc_output = json.loads(process.stdout)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}\nstdout先頭: {process.stdout[:1500]}"
    if cc_output.get("is_error"):
        return None, f"Claude Code error: {cc_output.get('result', '')[:1500]}"
    return cc_output, None


def _repair_json_text(s):
    """LLM出力JSONにありがちな、文字列内の裸の二重引用符（例: どう感じさせるかの"仕掛け"を提示）を
    全角引用符に置換して救済する。正当なJSON構造の引用符（前後が {}[],: か空白）は触らない。"""
    return re.sub(r'(?<=[^\s\{\}\[\],:])"(?=[^\s\{\}\[\],:])', '”', s)


def _loads_with_repair(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    try:
        # 文字列内の生改行・タブ等の制御文字を許容（Invalid control character 対策）
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        # 裸の二重引用符（"仕掛け" 等）を修復して再トライ（制御文字許容も併用）
        return json.loads(_repair_json_text(s), strict=False)


def extract_json_from_text(text):
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        return _loads_with_repair(match.group(1))
    try:
        return _loads_with_repair(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            return _loads_with_repair(text[start:end])
    raise ValueError("JSON extraction failed")


# ============== Phase 1: フック30本生成 ==============

def build_phase1_prompt(actor, account_info, target_research, eval_criteria,
                          hook_skill_text, top_hooks, bottom_hooks, proven_hooks,
                          schedule_slots, scraped_hooks=None):
    top_text = "\n".join([f"- [{h['views']}views] {h['hook']}" for h in top_hooks])
    bottom_text = "\n".join([f"- [{h['views']}views] {h['hook']}" for h in bottom_hooks])
    proven_text = "\n".join([f"- {h['hook']} (平均{int(h['avg_views'])}views・{h['rounds']}回投稿)" for h in proven_hooks]) or "（まだ無し）"

    n_posts = len(schedule_slots)
    scraped_hooks = scraped_hooks or []
    scraped_block = ""
    if scraped_hooks:
        lines = []
        has_second = False
        for s in scraped_hooks:
            fl = s.get("first_lines", "").replace("\n", "\\n")
            mark = " ★他アカ使用済み→口調リライト必須" if s.get("_second_use") else ""
            if s.get("_second_use"):
                has_second = True
            lines.append(f"- pool_id={s.get('pool_id')} [{s.get('views', 0)}views]{mark} {fl}")
        second_rule = ""
        if has_second:
            second_rule = """
- **★印のフックだけ例外**：近い時期に別アカウントでも使われているため、完全一致だと同一運営バレする。
  主張・構造・数字・具体名詞は一字一句保持したまま、**語尾・一人称・接続の言い回しだけをこの演者の口調に合わせて書き換える**（例：「〜なんです」→「〜だったりする」等）。
  1行目が元のフックと完全一致になるのは禁止。意味を変える・要約する・盛るのは禁止。"""
        scraped_block = f"""
## 収集済み実績フック（実際にX/Threadsで伸びた人間のフック・最優先で使う）

以下の {len(scraped_hooks)} 本は **hooks に全部含める**こと。ルール：
- hook_text は**一字一句そのまま使う**（改行 \\n も保持。言い換え・要約・整形は一切禁止）{second_rule}
- based_on は "scraped"、source_reference に pool_id を書く
- あなたがやるのは structure_label と body_pattern の割当だけ（フック内容と自然に合うものを選ぶ）

{chr(10).join(lines)}
"""

    sys_prompt = f"""あなたは {actor} のフック生成ロボットです。

# 役割
{n_posts}本のフック（ポストの1行目だけ）を生成する。本文は作らない。
1行目で **ターゲットの問に対する明確な主張** を出して、読者を止めることに集中する。

# 最優先ルール（守らないと不合格・添削で指摘された落とし穴を全部潰す版）

## A. 冒頭は「ターゲットの問への主張」型を最優先
ターゲット（復縁したい女性）が抱える疑問に対して明確な主張で開く。
良い例：
- 「友達からやり直すのが安全」は嘘
- 復縁の成功確率0%があるとしたら、それは「諦めてる」ことくらい
- 復縁するために外見磨きは必要ない
- 男性は気持ちが冷めた相手にはそもそも迷いなく距離を置く

主張になってない悪い例：
- 「あの頃の私に教えたい」← 自分語り start・読者と関係ない
- 「別れて4日目、彼から〜のLINEが来た」← 自分語り start
- 「察してちゃんを治す必要なんてない」← オリジナル造語が読者にピンとこない
- 「復縁した女性が共通してやめたのは〜」← 教訓系・読者の状況に即接続しない

## B. オリジナル造語禁止（最重要・添削で指摘）
「察してちゃん」「○○タイプ」「○○ちゃんラベル」「○○モード」みたいな
**AI造語・ターゲットが日常で使ってない語彙は冒頭で使わない**。
ターゲットの「これ私のこと」即時一致が崩れる。

## C. 自分語り start 禁止（添削で指摘）
「あの頃の私」「別れて4日目」「私も〜だった」みたいな個人エピソード冒頭は NG。
**バックストーリー素材は thread 内（中盤の根拠）でだけ使う**。冒頭1行目では使わない。

## D. 既存スキル本体の継続ルール
- 読者を観客じゃなく **プレイヤー（当事者）** として扱う
- 第三者語り（「振った男は」「相談者で」だけで始める文体）は禁止
- 同じ語彙・構造の連発禁止
- 演者キャラの定型フレーズ（「臨床心理士として」「1000人見てきて」「相談者で」等）を連発しない
- evaluation_criteria の5問は内部チェックのみ。出力JSONに書き込まない
- target_research のセクション番号を引用しない

# 変数選定の3段階フロー（必須・スキル本体の核）
**AIの想像で変数を埋めるのは禁止**。必ず以下の順で素材を選ぶ：

```
Step1：素材実例集_CSV由来.md の Part 1（CSV直接実例）／恋愛ダスト_分析用.csv を見る
       → 該当サブパターンに直接実例があれば、それを最優先で参考にする
       → CSV48本の id（例：F-7-a, A-3-a 等）を引用元として記録する

Step2：Step1に無ければ Part 2（観察ワード集）から変数を組合せる

Step3：Step1/2 にも無ければ、4テスト合格を条件に新規生成
       □ イメージテスト：読んで具体シーン／動作が浮かぶか
       □ 圧縮テスト：1〜2語で観察を圧縮してるか
       □ 造語感テスト：オリジナル造語じゃないか（「察してちゃん」級は NG）
       □ 観察由来テスト：「なんで思い付いた？」に「実生活で見た」と答えられるか
```

# CSV実例参照時の思考フロー（フック1本ごとに必ず通す）

CSV実例の Part 1 から1本選んだら、以下を順に自問する。

Q1. CSVの語り手部分（例：「うちが見てきた」「うちの店に来た」「私の経験上」）は、本演者の立場・職業・性別と整合しているか？
  → 整合：そのまま使う。
  → 不整合：Q2へ。

Q2. 演者のプロフィール（職業・経験・立場）から見て、CSVの語り手部分を自然な表現に置き換えられるか？
  → 置き換え可能：人称・冠詞・口調だけ置き換える。構造（主張内容・男の本音セリフ・展開順）は完全に保つ。
  → 置き換え不能：このCSVは捨てて別のCSVを選ぶ。オリジナル生成に逃げない。

Q3. CSV内に経験量を示す数字（「5000人聞いてきて」「3年見てきて」等）がある場合、演者の立場から見てその数字は自然か？
  → 自然：そのまま。
  → 桁外れ・嘘っぽい：演者の立場で自然に響く規模に下げる。

このフローを通せないCSV実例は、オリジナル生成のネタにしない。次のCSVを選ぶ。

# フック作成スキル本体＋素材プール（最優先で従う・上記3段階フローのソース）
{hook_skill_text}

# 商品情報（このアカウントが売るもの・固定CTA・演者の事実とバックストーリー）
**重要：バックストーリーは thread 中盤の根拠として使う。冒頭1行目に「私の話」は出さない。**

{account_info}

# ターゲット研究（参考素材）
{target_research}

# フック評価軸（内部チェックのみ・本文に書き込まない）
{eval_criteria}
"""

    user_prompt = f"""# 実績データ

## 伸びたフック（参考・構造を学ぶ）
{top_text}

## 伸びなかったフック（避ける構造）
{bottom_text}

## 再投稿で再現性確認済みフック
{proven_text}
{scraped_block}
# タスク

次の3日分のフック{n_posts}本を生成する。**各フックに本文の入り方タイプ（body_pattern）も一緒にアサインする**。

## based_on（過去ベースの配分・**新規創造を最小化する版**）

インプ低下の主因は「AIが新規創造に走って造語＋自分語りが湧く」こと。
これを構造的に防ぐため、**実績あるフック（収集済み実績フック＋過去伸びたフックの再投稿）を主体にする**。

- **scraped（収集済み実績フックがある場合）**：上のリストを全部 hooks に含める（一字一句そのまま）。最優先
- **repost**：残り枠の主体。以下から優先順位で再投稿
  1. proven_hooks（再現性確認済み・複数回投稿で平均views高い）
  2. top_hooks（過去 views >= 1000 のフック）からそのまま再投稿
  3. 投稿時期がバラければ同じフックの再投稿は完全に問題ない
- **variation**：伸びたフック（top）の中で1回だけ投稿のものを**主張部分は維持して周辺ワードを微修正**して再投稿
- **new（残り枠の1/5以下）**：完全新規はここに収める。CSV48本由来の構造から派生したもののみ

**禁止**：based_on=new で「察してちゃん」「○○タイプ」みたいなオリジナル造語、または「あの頃の私」みたいな自分語り start は不可。発見次第その候補を捨てて別の repost/variation に置き換える。

## body_pattern（本文の入り方の配分）

スキル本体の本文パターンに従う。AIが追加でラベル分類する必要はあるが、本文の質はスキル本体に委ねる。

| body_pattern | 説明 |
|---|---|
| `reader_now` | 読者の今この瞬間の行動・感情を描写して始める |
| `mechanism_first` | メカニズム解説から始める（事例は補強だけ・自分語りNG） |
| `reverse_hope` | 反転希望から始める（絶望→希望の急展開・事例なしでもOK） |
| `mens_voice_quote` | 男の本音セリフから始める（自分の話じゃなく男側のセリフ） |
| `case_success` | 相談者成功事例から始める |
| `case_failure` | 失敗警告事例から始める |

**ルール**：
- `case_success` + `case_failure` を**合計4本以下**に厳格制限（テンプレ化防止）
- 同じ body_pattern が3本連続しない
- フックの内容と body_pattern を**自然な組み合わせ**で選ぶ

## 出力形式（JSON only・他のテキスト一切不要・**source_csv_id 必須**）

**JSONの文字列の中で半角二重引用符（"）を使うことは絶対禁止**（パースが壊れる）。強調・引用・セリフは必ず『』「」を使う。

```json
{{
  "analysis": {{
    "top_patterns": ["伸びた構造の共通点（箇条書き）"],
    "bottom_failures": ["伸びなかった構造の共通点（箇条書き）"]
  }},
  "hooks": [
    {{
      "id": "{actor}_YYYYMMDD_NN",
      "hook_text": "1行目のフック",
      "structure_label": "常識否定型 / 男性心理暴露型 / 落差ストーリー型 / 命題型 / 反転希望型 など",
      "body_pattern": "claim_first / reader_now / mechanism_first / reverse_hope / mens_voice_quote / case_success / case_failure のいずれか",
      "based_on": "scraped / repost / variation / new",
      "source_csv_id": "派生元のCSV id（例：F-7-a, A-3-a）。scraped の場合は空文字。new の場合でも派生元のCSV idを書く。完全オリジナルは禁止",
      "source_reference": "scraped の場合は pool_id／repost/variation の場合は元のフック先頭40字／new の場合は派生の根拠（CSVのどの構造から派生したか1行説明）",
      "scheduled_at": "ISO8601（下の slots から順に使う）"
    }}
  ]
}}
```

## スケジュールスロット（hook の scheduled_at に順に使う・{n_posts}個）
{json.dumps(schedule_slots[:n_posts], ensure_ascii=False)}
"""
    return sys_prompt + "\n\n---\n\n" + user_prompt


# ============== Phase 2: フック1本→本文生成 ==============

def build_phase2_prompt(actor, hook, account_info, body_skill_text):
    body_pattern_guide = {
        "reader_now": "読者の今この瞬間の行動・感情を描写して始める。「いま追いLINE送ろうとしてる人」「3週間既読スルーされて、夜眠れずスマホ見てる人」みたいに読者の現在地に直接届く。事例は最小限。**オリジナル造語（『察してちゃん』『○○タイプ』）は冒頭NG**。",
        "mechanism_first": "メカニズム解説から始める。原理→具体例で補強。事例で始めない。「男の脳ではこう動く」「回避型の特徴は〇〇」みたいな構造解説が先。",
        "reverse_hope": "反転希望から始める。「諦めかけてる人、まだ可能性ある」「終わったと思ってる人、実はここから戻せる」みたいに、絶望→希望の急展開で開く。事例なしでも成立する。**根拠を示さず希望だけ言うのはNG**。",
        "mens_voice_quote": "男の本音セリフを段落の中心に置く。「振った後の彼が言ってた」「復縁した男に直接聞いたら〜」みたいに、男の生の声を主役に。",
        "case_success": "相談者成功事例から始める。来談→分析→助言→成功→リスク提示の流れ。**「僕の購入者さんで…って泣きながら来た」テンプレの連発NG**。30本中で同じ事例構造が3本以上出ないよう、入り方を毎回変える。",
        "case_failure": "失敗警告事例から始める。来談→助言→動かなかった→手遅れ→教訓。緊張感／自責の警告。",
    }
    pattern = hook.get("body_pattern", "mechanism_first")
    pattern_explanation = body_pattern_guide.get(pattern, "")

    # v2: post_type ごとに「字数・ぶら下げ有無・CTA(note直リンク)」を出し分ける
    post_type = hook.get("post_type")
    note_url = NOTE_URLS.get(actor, "")
    if post_type == "short80":
        task_block = ("このフックを起点に、**80字以内の単発ポスト**を書く。**ぶら下げ(thread)もCTAも付けない**。"
                      "フックの主張を1〜2文で言い切って完結させる。末尾に「↓」や「続き」誘導は付けない（単発で完結）。")
        output_block = '{\n  "text": "80字以内・単発で完結（CTA・↓なし）",\n  "thread": []\n}'
    elif post_type == "mid180":
        task_block = ("このフックを起点に、**180字前後の単発ポスト**を書く。**ぶら下げ(thread)もCTAも付けない**。"
                      "フック＋根拠や具体で読ませて言い切る。末尾に「↓」や「続き」誘導は付けない（単発で完結）。")
        output_block = '{\n  "text": "180字前後・単発で完結（CTA・↓なし）",\n  "thread": []\n}'
    elif post_type == "thread_cta":
        task_block = (f"このフックを起点に、**メイン本文(100〜140字)** と **濃いぶら下げ(thread 250〜400字)** の2部構成で必ず書く。\n"
                      f"型は「**メイン＝冒頭で自己主張／ぶら下げ＝その主張を教育**」。\n"
                      f"※ただしハクオウ（男性心理特化）の角度をそのまま流用しない（丸パクリ禁止）。"
                      f"**この演者({actor})自身のコンセプト・強み・勝ち筋**（下の商品情報/実績/キャラ）に当てはめて書く。各アカウントで主張の切り口も使う武器も違っていい。\n"
                      f"【メイン】冒頭で、この演者の核になる主張（常識否定でもOK）を言い切る。読者の現在地（「今〜してるあなた」）に重ねて刺す。100字前後の読み応え。\n"
                      f"【ぶら下げ】メインの主張を“教育”する＝なぜそうなのか／どう動けばいいかを、**この演者が持つ武器**で具体的に深掘り：\n"
                      f"  ・演者本人の体験・失敗談、相談者の事例、その演者ならではの本音やデータ など（account_infoの勝ち筋に沿う／無い武器を捏造しない）。\n"
                      f"  ・場面・セリフ・具体で描く（抽象解説の名詞化＝固定される/印象固定/過去化する 等は禁止。口語で）。\n"
                      f"  ・動かないとどうなるか（境界線）を自然に1つ入れてよい（毎回機械的に入れなくてよい）。\n"
                      f"・**threadは絶対に空にしない**（ぶら下げ無し＝不合格）。ぶら下げ末尾CTAは**プロフのnoteに誘導**する（投稿に直リンクURLは貼らない）。「〜はプロフのnoteに書いてる／まとめた」のように商品の中身が見える言い回しで、毎回変える。\n"
                      f"・メイン本文(text)の末尾には「↓」や続き記号を付けない（メインだけでも意味が通る言い切り。ぶら下げは必ず別途出力）。")
        output_block = ('{\n  "text": "メイン100〜140字・冒頭でこの演者の核の自己主張＋読者の現在地（末尾に↓なし）",\n'
                        '  "thread": ["ぶら下げ250〜400字（必須）。メインの主張をこの演者の強み/勝ち筋で教育（丸パクリしない）。末尾CTAはプロフのnoteへ誘導（直リンクURLは貼らない）"]\n}')
    else:
        # 非v2（ハクオウ/うみこ等）：従来どおり メイン100〜150字＋ぶら下げ＋固定CTA
        task_block = "このフックから続く本文（メイン続き）と thread（ぶら下げ）を、上記の body_pattern に従って書く。"
        output_block = '{\n  "text": "メインテキスト（1行目フック含む全体100〜150字）",\n  "thread": ["ぶら下げ全文＋CTAを1要素にまとめた文字列"]\n}'

    sys_prompt = f"""あなたは {actor} のポスト本文生成ロボットです。

# 役割
渡された1行目のフックに、指定された body_pattern で続きの本文と thread（ぶら下げ）を書く。
これは「リライトモード（人間がフックを当てて、AIが本文を作る）」の自動化版。

# 最優先ルール（守らないと不合格・添削で指摘された落とし穴を全部潰す版）

## A. 自分語り start を本文・thread 冒頭で使わない（添削指摘・最重要）
「あの頃の私」「別れて4日目」「私も〜だった」みたいな個人エピソード冒頭はNG。
これは読者と関係ない・スクロールされる。
**バックストーリー素材は thread の中盤で「根拠」として使う**。冒頭では使わない。

## B. オリジナル造語を本文で使わない（添削指摘・最重要）
「察してちゃん」「○○タイプ」「○○ちゃんラベル」みたいな AI造語・ターゲットが日常で使ってない語彙は本文・thread 冒頭で使わない。
本文中盤で「説明文付き」なら可（例：「この行動を僕は『察してちゃんラベル』って呼んでます」みたいに 1度説明を入れる）。

## C. 既存ルール
1. 渡された hook_text を冒頭として **そのまま** 使う。書き換えない。（hook_text が改行入りの2行の場合も、2行ともそのまま冒頭に置く。収集フックは実際に伸びた実績文言なので一字も変えない）
2. 続く本文（メイン部分・計100〜150字）と thread（3〜4段落＋CTA）を書く。CTAは本文ごとに作り直す（固定文言の使い回しはしない）。
3. **body_pattern に指定された入り方で書く**。他のパターンに勝手に変えない。
4. 読者を観客じゃなく **プレイヤー（当事者）** として扱う。本文中に「あなた／今のあなた」が出てくる箇所を必ず作る。
5. **スキル本体の段落別固定句リストはテンプレ強制じゃなく、参考の選択肢**。毎回同じ固定句（「僕の購入者さんで…」「〜って泣きながら来た」等）を使わない。
6. 同じ語彙・構造の連発NG。「臨床心理士として」「1000人見てきて」「相談者で」みたいなフレーズの連発はしない。
7. evaluation_criteria の5問は内部チェックのみ。本文に書き込まない。
8. target_research のセクション番号を本文に引用しない。
9. **CTAは本文ごとに作り直す。** CTAの言い回しは毎回そのポストの中身（指摘した「やっちゃってる」やテーマ）に合わせて変える。全ポスト同じCTAの使い回しはNG（業者感）。**メイン本文(text)の末尾には「↓」を付けない**（textは単体で完結させる。ぶら下げが投稿失敗してもメインだけで破綻しないように）。「↓」を使うのは thread 末尾のCTA直前だけ。▼は使わない。**単発ポスト（ぶら下げ無し）にはCTAも↓も付けない**。

## D. AI感監視員ルール（説明調・整いすぎ・三角記号を出さない）
10. **体験者の口で書く（解説者の口で書かない）**：心の動きを"仕組み"として名詞化・説明しない。「固定される／上書きできない／スイッチが入る／印象固定／過去化する／〜が勝手に立ち上がる／分類する最大の要因」みたいな解説調は禁止。「固まる／もう戻せない／思い込む」みたいに、その人が実際に口で喋る体感の言葉にする。
11. **整いすぎない**：数字・対句・並列をきれいに揃えすぎない（「ほぼ全員一致で／100%／必ず／3つが同時に」みたいな作った感はNG。"だいたい/ほぼ"に崩す）。**ただし演者の実績数字（相談1000件等）はそのまま残す**——これは権威。
12. **三角の誘導記号「▼」は使わない**（確定の好み）。誘導は「↓」か言い切り（記号なし）で。

# ポスト作成スキル本体（恋愛系特化・参考にする）
スキル本体の「段落別固定句リスト」「本文4パターン」は売れる構造の素材集として参照する。
ただし**そのままコピペする強制テンプレじゃない**。指定の body_pattern と合わない固定句は使わない。

{body_skill_text}

# 商品情報（演者の最低限の事実・商品・固定CTA・バックストーリー）
**重要：バックストーリーは thread の中盤で「根拠」として使う。本文・thread 冒頭で「あの頃の私」型の自分語り start はNG。**

{account_info}
"""

    user_prompt = f"""# 入力

## フック（1行目・そのまま使う）
{hook['hook_text']}

## カテゴリ/構造（参考）
{hook.get('structure_label', '')}

## 元ネタ
{hook.get('based_on', 'new')}

## body_pattern（本文の入り方・必ずこれに従う）
**{pattern}**

{pattern_explanation}

# タスク（字数・ぶら下げ有無・CTAは下記を最優先。sys_promptのC2「100〜150字＋thread」より優先）
{task_block}

# 出力形式（JSON only・他のテキスト一切不要）

**JSONの文字列の中で半角二重引用符（"）を使うことは絶対禁止**（パースが壊れる）。強調・引用・セリフは必ず『』「」を使う。

```json
{output_block}
```
"""
    return sys_prompt + "\n\n---\n\n" + user_prompt


# ============== hook_archive 更新 ==============

def update_hook_archive(actor, hooks):
    """生成した30本のフックを hook_archive.json に追加（再投稿の追跡用）"""
    archive_path = os.path.join(ROOT, f"analytics/{actor}/hook_archive.json")
    archive = load_json(archive_path, {"hooks": {}})

    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    for h in hooks:
        hid = fookid(h["hook_text"])
        h["fookid"] = hid
        if hid not in archive["hooks"]:
            archive["hooks"][hid] = {
                "text": h["hook_text"],
                "structure_label": h.get("structure_label", ""),
                "first_used_at": today,
                "history": [],
            }
        # 予約スロットを記録（views は後で fetch から追記される）
        archive["hooks"][hid]["history"].append({
            "scheduled_at": h.get("scheduled_at"),
            "registered_at": today,
            "views": None,
        })

    save_json(archive_path, archive)
    return archive_path


# ============== main run ==============

def run(actor, phase1_only=False, limit=None, reuse_phase1=False):
    knowledge_dir = os.path.join(ROOT, f"knowledge/{actor}")
    shared_dir = os.path.join(ROOT, "knowledge/shared")
    account_dir = os.path.join(ROOT, f"accounts/{actor}")
    analytics_dir = os.path.join(ROOT, f"analytics/{actor}")

    eval_path = os.path.join(knowledge_dir, "evaluation_criteria.md")
    if not os.path.exists(eval_path):
        eval_path = os.path.join(shared_dir, "evaluation_criteria.md")
    research_path = os.path.join(knowledge_dir, "target_research.md")
    if not os.path.exists(research_path):
        research_path = os.path.join(shared_dir, "target_research.md")
    setting_path = os.path.join(account_dir, "アカウント情報総合管理.md")
    db_path = os.path.join(analytics_dir, "posts_db.json")
    hook_archive_path = os.path.join(analytics_dir, "hook_archive.json")
    prev_batch_path = os.path.join(analytics_dir, "next_batch.json")

    for path, label in [(eval_path, "evaluation_criteria"), (research_path, "target_research"),
                         (setting_path, "アカウント情報総合管理"), (db_path, "posts_db")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}")
            sys.exit(1)

    print(f"[hook_improve] {actor} 開始")
    print(f"  evaluation_criteria: {os.path.relpath(eval_path, ROOT)}")

    eval_criteria = load_text(eval_path)
    target_research = load_text(research_path)
    account_info = load_text(setting_path)
    posts_db = load_json(db_path, {"posts": {}})
    hook_archive = load_json(hook_archive_path, {"hooks": {}})

    hook_skill_text = "\n\n".join([
        load_text(os.path.join(ROOT, p), optional=True) for p in HOOK_SKILL_FILES
    ])
    body_skill_text = "\n\n".join([
        load_text(os.path.join(ROOT, p), optional=True) for p in BODY_SKILL_FILES
    ])

    top_hooks, bottom_hooks, proven_hooks = extract_performance_data(posts_db, hook_archive)
    print(f"  実績: top={len(top_hooks)} bottom={len(bottom_hooks)} proven={len(proven_hooks)}")

    start_date = find_next_start_date(posts_db, prev_batch_path)
    per_day = V2_PER_DAY if actor in V2_ACTORS else 10
    schedule_slots = generate_schedule(start_date, per_day=per_day)
    print(f"  スケジュール: {start_date.strftime('%Y-%m-%d')} 〜 {(start_date + timedelta(days=2)).strftime('%Y-%m-%d')}")

    # === 丸ごとリサイクル：伸びたポストを昇格→クールダウン明けを先に枠確保（生成ゼロ）===
    recycle_pool, recycle_pool_path, promoted = promote_recycle_pool(actor, posts_db, analytics_dir)
    recycle_items = select_recycle_items(recycle_pool, RECYCLE_PER_DAY * 3)
    print(f"  リサイクル: プール{len(recycle_pool.get('items', {}))}件（今回昇格+{promoted}）→ 今バッチに{len(recycle_items)}本")

    # === 収集フック（scraped）：この演者が未使用のものを確保 ===
    scraped_pool = load_scraped_pool()
    n_ai_slots_estimate = len(schedule_slots) - len(recycle_items)
    scraped_hooks = select_scraped_hooks(scraped_pool, actor, min(SCRAPED_PER_DAY * 3, max(0, n_ai_slots_estimate - 3)))
    print(f"  収集フック: プール{len(scraped_pool.get('hooks', []))}件 → 今バッチに{len(scraped_hooks)}本")

    # スロット分割：リサイクル分は日内に散らす（各日の 1番目と6番目あたり）
    recycle_slot_idx = []
    if recycle_items:
        per_batch = len(recycle_items)
        stride_positions = [1, 6, 3, 8][:RECYCLE_PER_DAY]  # 日内の位置（0始まり）
        k = 0
        for d in range(3):
            for pos in stride_positions:
                if k >= per_batch:
                    break
                idx = d * per_day + pos
                if idx < len(schedule_slots):
                    recycle_slot_idx.append(idx)
                    k += 1
    recycle_slot_idx = sorted(set(recycle_slot_idx))[:len(recycle_items)]
    ai_slot_idx = [i for i in range(len(schedule_slots)) if i not in recycle_slot_idx]
    ai_slots = [schedule_slots[i] for i in ai_slot_idx]

    # === Phase 1: フック30本生成 ===
    preview_path = os.path.join(analytics_dir, "phase1_hooks_preview.json")
    if reuse_phase1 and os.path.exists(preview_path):
        print(f"\n[Phase 1] --reuse-phase1 モード: 既存の {preview_path} を使う")
        prev = load_json(preview_path)
        phase1_result = {
            "analysis": prev.get("analysis", {}),
            "hooks": prev.get("hooks", []),
        }
    else:
        print(f"\n[Phase 1] フック{len(ai_slots)}本生成中（うち収集フック{len(scraped_hooks)}本はそのまま採用）...")
        phase1_prompt = build_phase1_prompt(
            actor, account_info, target_research, eval_criteria,
            hook_skill_text, top_hooks, bottom_hooks, proven_hooks, ai_slots,
            scraped_hooks=scraped_hooks
        )
        cc_output, err = call_claude_code(phase1_prompt, timeout=600)
        if err:
            print(f"  ✗ Phase 1 失敗:\n{err[:1500]}")
            sys.exit(1)
        try:
            phase1_result = extract_json_from_text(cc_output.get("result", ""))
        except (ValueError, json.JSONDecodeError) as e:
            err_path = os.path.join(analytics_dir, "hook_improve_phase1_error.txt")
            with open(err_path, 'w', encoding='utf-8') as f:
                f.write(cc_output.get("result", ""))
            print(f"  ✗ Phase 1 JSON抽出失敗: {e}（生レスポンスを {err_path} に保存）")
            sys.exit(1)

        usage = cc_output.get("usage", {})
        if usage:
            print(f"    tokens: input={usage.get('input_tokens', 0)}, output={usage.get('output_tokens', 0)}, "
                  f"cache_read={usage.get('cache_read_input_tokens', 0)}")

    hooks = phase1_result.get("hooks", [])[:len(ai_slots)]
    # scheduled_at を ai_slots で強制上書き（AIのslot選択ミス対策）＋
    # v2演者：post_type は「実際のスロット位置（日内position）」基準で振り分ける
    for i, h in enumerate(hooks):
        h["scheduled_at"] = ai_slots[i] if i < len(ai_slots) else h.get("scheduled_at")
        if actor in V2_ACTORS and i < len(ai_slot_idx):
            h["post_type"] = V2_DAY_PLAN[ai_slot_idx[i] % V2_PER_DAY]
    print(f"  ✓ Phase 1 完了: {len(hooks)}本のフック")

    if phase1_only:
        # Phase 1 だけ走らせるテストモード。フック中身を別ファイルに出して終了。
        out_path = os.path.join(analytics_dir, "phase1_hooks_preview.json")
        save_json(out_path, {
            "演者": actor,
            "generated_at": datetime.now(tz=JST).isoformat(),
            "analysis": phase1_result.get("analysis", {}),
            "hooks_count": len(hooks),
            "hooks": hooks,
        })
        print(f"  --phase1-only モード: フック中身を {out_path} に保存して終了")
        return out_path

    # === Phase 2: 1本ずつ本文生成（シーケンシャル）===
    phase2_hooks = hooks if limit is None else hooks[:limit]
    print(f"\n[Phase 2] 本文生成（{len(phase2_hooks)}回シーケンシャル・並列はしない）...")
    posts = []
    for i, hook in enumerate(phase2_hooks, 1):
        ht = (hook.get("hook_text", "") or "").replace("\n", " ")
        print(f"  ({i}/{len(phase2_hooks)}) {ht[:60]}...")
        p2_prompt = build_phase2_prompt(actor, hook, account_info, body_skill_text)
        cc_out, err = call_claude_code(p2_prompt, timeout=300)
        if err:
            print(f"    ✗ 失敗: {err[:300]}")
            continue
        try:
            body = extract_json_from_text(cc_out.get("result", ""))
        except (ValueError, json.JSONDecodeError) as e:
            print(f"    ✗ JSON抽出失敗: {e}")
            continue

        def _norm_thread(th):
            if isinstance(th, list) and len(th) > 1:
                return ["\n\n".join(t for t in th if isinstance(t, str) and t.strip())]
            return th if isinstance(th, list) else []

        def _has_thread(th):
            return isinstance(th, list) and any((t or "").strip() for t in th)

        thread = _norm_thread(body.get("thread", []))

        # v2 thread_cta なのに ぶら下げが空 → 1回だけ強めに再生成（ぶら下げ付き3本/日を確保）
        if hook.get("post_type") == "thread_cta" and not _has_thread(thread):
            retry_prompt = p2_prompt + (
                "\n\n# 再指示（重要）\n前回の出力は thread が空だった。このポストは必ず「メイン＋ぶら下げ」の2部構成。"
                "thread を150〜200字で必ず書き、末尾CTAに指定のnote直リンクを貼って、同じJSON形式で出し直すこと。thread を空にしない。"
            )
            cc_out2, err2 = call_claude_code(retry_prompt, timeout=300)
            if not err2:
                try:
                    body2 = extract_json_from_text(cc_out2.get("result", ""))
                    t2 = _norm_thread(body2.get("thread", []))
                    if _has_thread(t2):
                        body = body2
                        thread = t2
                        print("    ↻ thread空→再生成でぶら下げ復活")
                except (ValueError, json.JSONDecodeError):
                    pass
            if not _has_thread(thread):
                print("    ⚠ thread_cta だが ぶら下げ生成できず（単発で投入）")

        posts.append({
            "id": hook.get("id"),
            "fookid": fookid(hook["hook_text"]),
            "structure_label": hook.get("structure_label"),
            "based_on": hook.get("based_on"),
            "post_type": hook.get("post_type"),
            "scheduled_at": hook.get("scheduled_at"),
            "text": body.get("text", ""),
            "thread": thread,
        })

    print(f"  ✓ Phase 2 完了: {len(posts)}/{len(phase2_hooks)}本の本文生成")

    if limit is not None:
        # 部分テスト時は hook_archive 更新しない（本番運用じゃないため）
        test_out_path = os.path.join(analytics_dir, f"phase2_test_{len(posts)}posts.json")
        save_json(test_out_path, {
            "演者": actor,
            "generated_at": datetime.now(tz=JST).isoformat(),
            "limit": limit,
            "posts": posts,
        })
        print(f"  --limit テストモード: {test_out_path} に保存して終了")
        return test_out_path

    # === hook_archive 更新 ===
    archive_path = update_hook_archive(actor, hooks)
    print(f"  ✓ hook_archive 更新: {archive_path}")

    # === 丸ごとリサイクル分を posts に統合（生成ゼロ・実績実証済みの弾）===
    today_str = datetime.now(tz=JST).strftime("%Y%m%d")
    used_recycle_ids = []
    for n, it in enumerate(recycle_items):
        if n >= len(recycle_slot_idx):
            break
        thread = it.get("thread") or []
        posts.append({
            "id": f"{actor}_{today_str}_r{n+1:02d}",
            "fookid": fookid((it.get("text", "") or "").split("\n")[0]),
            "structure_label": it.get("structure_label", ""),
            "based_on": "recycle",
            "post_type": ("thread_cta" if thread else "mid180") if actor in V2_ACTORS else None,
            "scheduled_at": schedule_slots[recycle_slot_idx[n]],
            "text": it.get("text", ""),
            "thread": thread,
        })
        used_recycle_ids.append(it.get("recycle_id"))
    if used_recycle_ids:
        mark_recycle_used(analytics_dir, used_recycle_ids)
        print(f"  ✓ リサイクル {len(used_recycle_ids)}本を統合（{RECYCLE_COOLDOWN_DAYS}日クールダウン記録）")

    # === 収集フックの使用マーク（based_on=scraped で採用されたもの）===
    used_pool_ids = [h.get("source_reference") for h in hooks
                     if h.get("based_on") == "scraped" and h.get("source_reference")]
    if used_pool_ids:
        mark_scraped_used(scraped_pool, used_pool_ids, actor)
        print(f"  ✓ 収集フック {len(used_pool_ids)}本を使用済みマーク")

    posts.sort(key=lambda p: p.get("scheduled_at") or "")

    # === next_batch.json 出力（schedule_posts.py 互換）===
    output = {
        "演者": actor,
        "generated_at": datetime.now(tz=JST).isoformat(),
        "cycle_start": start_date.isoformat(),
        "cycle_end": (start_date + timedelta(days=2)).isoformat(),
        "analysis": phase1_result.get("analysis", {}),
        "総本数": len(posts),
        "posts": posts,
    }
    out_path = os.path.join(analytics_dir, "next_batch.json")
    save_json(out_path, output)
    print(f"\n  ✓ 出力: {out_path}（生成{len(posts)-len(used_recycle_ids)}＋リサイクル{len(used_recycle_ids)}）")

    return out_path


def main():
    if len(sys.argv) < 2:
        print("usage: python note_tools/hook_improve.py <演者名> [--phase1-only] [--limit N] [--reuse-phase1]")
        sys.exit(1)
    actor = sys.argv[1]
    phase1_only = "--phase1-only" in sys.argv
    reuse_phase1 = "--reuse-phase1" in sys.argv
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass
            break
    run(actor, phase1_only=phase1_only, limit=limit, reuse_phase1=reuse_phase1)


if __name__ == "__main__":
    main()
