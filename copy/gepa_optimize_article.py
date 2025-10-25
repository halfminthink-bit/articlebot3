# -*- coding: utf-8 -*-
"""
GEPA 最適化（ASP向け/主観・テンポ・一貫性＋内容評価）
- 入力: キーワード, info.json（一次情報の要点を含む）
- 出力: SEOタイトル / アウトライン(H2想定) / 本文(です・ます調, 2000–3000±10%)
- 最適化: GEPA (score + 文章feedback) で指示文を学習
- 連結性: Title -> Outline -> Draft を title/keyword/context で接続
- 評価: フォーム評価 + コンテキスト・カバレッジ + （任意）LLM整合性ジャッジ

使い方（PowerShell）:
  # 事前に API キーを設定
  # $env:OPENAI_API_KEY = "sk-..."
  # （任意）モデル変更
  # $env:OPENAI_MODEL = "openai/gpt-4o-mini"

  # 1) 最適化して保存 + テスト生成（info.jsonを使う）
  # python .\gepa_optimize_article.py --optimize --save --info "C:\path\to\info.json" --keyword "GEPA プロンプト 最適化"

  # 2) 学習せずにテスト生成だけ（info.jsonを使う）
  # python .\gepa_optimize_article.py --info "C:\path\to\info.json" --keyword "AI音声アシスタント おすすめ"

  # 3) 任意：LLM整合性ジャッジも実施（追加コストあり）
  # python .\gepa_optimize_article.py --info ".\data\info.json" --keyword "GEPA プロンプト 最適化" --judge
"""

import os, re, json, math
from pathlib import Path
from typing import Dict, Any, List, Tuple

try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

import dspy

# ====== LLM 設定 ======
API_KEY = os.getenv("OPENAI_API_KEY")
assert API_KEY, "OPENAI_API_KEY を .env または環境変数で設定してください。"
MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
dspy.configure(lm=dspy.LM(MODEL, api_key=API_KEY))

# ====== 署名（最適化対象の“指示文”になる） ======
class MakeTitle(dspy.Signature):
    """与えられたキーワードでASP向けの日本語SEOタイトルを1本作る。
    ルール:
    - 主要キーワードを必ず自然に含める（語順任意／不自然な詰め込みNG）
    - 28〜38文字を目安。数字や記号（｜/【】/：/（））で具体性・約束を明確に
    - 読者の検索意図を満たす“具体”（手順/比較/真相/実例/注意/結論 など）を1つ以上含む
    - 誇大表現・煽りNG。クリック後の満足度を最優先
    - このタイトルは後続のアウトライン・本文の方向性（主張）と一貫させる
    """
    keyword: str = dspy.InputField()
    title: str = dspy.OutputField()

class MakeOutline(dspy.Signature):
    """受け取ったタイトルに“沿う”H2（必要ならH3）アウトラインを作る。
    ルール:
    - 本文は書かない。H2中心（5〜6本目安、各H2の意図が明確）
    - 主要キーワードを含むH2を最低1つ
    - H2はフック/インパクト重視（例: 結論/真相/なぜ/具体例/手順/注意/比較/まとめ）
    - タイトルの主張や約束（何を明らかにするか）に論理的に接続
    - 見出しは後続の本文で“一字一句”再掲されるため、簡潔かつ確定的な文言にする
    - context（一次情報要約）に反しない/反映する
    """
    title: str = dspy.InputField()
    keyword: str = dspy.InputField()
    context: str = dspy.InputField()
    outline: str = dspy.OutputField()

class MakeDraft(dspy.Signature):
    """タイトルとアウトラインに厳密に従って本文を作る（ASP向け）。
    ルール:
    - です・ます調（敬体率≧85%を目安）。URL直記載NG
    - 全体で 2000〜3000 文字目安（±10%可）
    - 導入100文字以内に主要キーワード＋結論の要旨を自然に含める（結論先出し）
    - 主観を入れて“何が言いたいか”を明確化（私は〜/〜と感じます/〜と思います等）
    - テンポ重視：平均文長≦60字、短文も適度に混ぜる、段落は過度に長くしない
    - 構成は“主張→理由→具体例→注意→結論”の順を基本（各H2内）
    - 見出し（H2/H3）はアウトラインの文言・順序を“一字一句”変更せず再掲
    - context（一次情報要約）に整合し、各H2で最低1回はcontextの具体を参照表現で触れる
    """
    title: str = dspy.InputField()
    keyword: str = dspy.InputField()
    outline: str = dspy.InputField()
    context: str = dspy.InputField()
    article: str = dspy.OutputField()

# ====== ユーティリティ ======
TRAIN_KEYWORDS = [
    "物販システム ACCESS 稼げない",
    "AI音声アシスタント おすすめ",
    "Meta Vibes とは",
    "オルビスユードット 口コミ 悪い",
    "GEPA プロンプト 最適化",
    "僕のAIアカデミー 評判",
]

def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())

def _strip_urls(s: str) -> str:
    return re.sub(r"https?://\S+", "", s)

def load_info(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        print(f"[warn] info.json not found: {p} (empty context will be used)")
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] failed to parse info.json: {e} (empty context will be used)")
        return {}

def flatten_info_to_context(data: Dict[str, Any]) -> str:
    """
    info.json から “本文にはURLを出さない” 方針のため、URLを落とした要点の箇条書きを作る。
    可能なキー例：
      - target_name, persona_label, title_samples
      - service{name}, company{name_ja,name_en}, sources[{title,url}], notes など
    """
    lines: List[str] = []
    if not data:
        return ""

    def add_line(txt: str):
        txt = _strip_urls(str(txt)).strip()
        if txt:
            lines.append(f"- {txt}")

    # 代表名
    for k in ["target_name", "persona_label"]:
        if k in data and data[k]:
            add_line(f"{k}: {data[k]}")

    # service / company
    for key in ["service", "company"]:
        obj = data.get(key)
        if isinstance(obj, dict):
            for kk, vv in obj.items():
                if vv:
                    add_line(f"{key}.{kk}: {vv}")

    # title samples
    ts = data.get("title_samples")
    if isinstance(ts, list):
        for t in ts[:5]:
            add_line(f"sample_title: {t}")

    # sources（URLは落としてタイトルのみ）
    srcs = data.get("sources")
    if isinstance(srcs, list):
        for s in srcs:
            ttl = (s.get("title") if isinstance(s, dict) else None) or str(s)
            add_line(f"source_title: {ttl}")

    # その他の一次情報らしい数値・期間など（浅く走査）
    for k, v in data.items():
        if k in {"target_name", "persona_label", "service", "company", "title_samples", "sources"}:
            continue
        if isinstance(v, (str, int, float)):
            add_line(f"{k}: {v}")
        elif isinstance(v, list) and v and isinstance(v[0], (str, int, float)):
            add_line(f"{k}: " + " / ".join(str(x) for x in v[:5]))
        elif isinstance(v, dict):
            # 深追いはしない（安全第一）
            pass

    return "\n".join(lines)

# ====== スコアリング（フォーム） ======
def score_title(keyword: str, title: str) -> Dict[str, Any]:
    score, fb = 1.0, []
    t = _normalize(title)

    # キーワード（空白で区切って各語を粗チェック）
    missing = []
    for token in re.split(r"\s+", keyword.strip()):
        token_n = _normalize(token)
        if token and token_n and token_n not in t:
            missing.append(token)
    if missing:
        score -= 0.4
        fb.append(f"キーワード不足: {missing} を自然に含める。")

    # 長さ
    n = len(title)
    if n < 28 or n > 38:
        score -= 0.2
        fb.append(f"長さ調整: 現在{n}文字。目安28〜38。")

    # 具体性（数字/コロン/括弧など簡易判定）
    if not re.search(r"[0-9：:\[\]【】（）/｜-]", title):
        score -= 0.1
        fb.append("具体性を示す数字/記号が不足。例: 【比較】/3つの手順 など。")

    if not fb:
        fb = ["perfect"]
    return {"score": max(0.0, min(1.0, score)), "feedback": " | ".join(fb)}

def score_outline(title: str, keyword: str, outline: str) -> Dict[str, Any]:
    score, fb = 1.0, []
    h2 = [ln for ln in outline.splitlines() if ln.strip().startswith("## ")]
    h2n = len(h2)
    if h2n < 5 or h2n > 6:
        score -= 0.3
        fb.append(f"H2本数が不適切: {h2n}本（目安5〜6本）。")

    # キーワードを含むH2の有無
    if not any(_normalize(keyword) in _normalize(ln) for ln in h2):
        score -= 0.2
        fb.append("H2のどれかに主要キーワードを含める。")

    # 章タイトルの具体語（フック語）
    needed = ["結論", "真相", "なぜ", "検証", "具体例", "データ", "手順", "仕組み", "注意", "比較", "まとめ"]
    if sum(any(w in ln for w in needed) for ln in h2) < 3:
        score -= 0.2
        fb.append("H2に『結論/真相/なぜ/検証/具体例/手順/注意/比較/まとめ』系の具体語を増やす。")

    # タイトルとの一貫性（主要語がH2群に反映されているかの簡易検査）
    title_core = re.sub(r"[【】\[\]\(\)｜：:\s]", "", title)
    if title_core and not any(re.sub(r"\s", "", ln).find(title_core[:6]) >= 0 for ln in h2):
        score -= 0.1
        fb.append("タイトルの核心語がH2に十分反映されていません。")

    if not fb:
        fb = ["perfect"]
    return {"score": max(0.0, min(1.0, score)), "feedback": " | ".join(fb)}

def score_draft_form(title: str, keyword: str, outline: str, article: str) -> Dict[str, Any]:
    score, fb = 1.0, []
    text = article
    chars = len(text)

    # 文字量（2000-3000 ±10%）
    if chars < 1800 or chars > 3300:
        score -= 0.25
        fb.append(f"文字量: 現在{chars}字（目安2000〜3000）。")

    # 敬体率（です/ます）
    politeness = sum(1 for _ in re.finditer(r"(です。|ます。)", text)) / max(1, text.count("。"))
    if politeness < 0.85:
        score -= 0.25
        fb.append(f"敬体率が不足: {politeness:.2f}（>=0.85）。")

    # URL 直記載NG
    if re.search(r"https?://", text):
        score -= 0.3
        fb.append("URL直記載はNG。出典は参照表現にとどめる。")

    # 主観（簡易）：一人称/感情語
    subj_hits = len(re.findall(r"(私は|わたしは|と感じ|と思い|と考え|正直|個人的には)", text))
    if subj_hits < 2:
        score -= 0.15
        fb.append("主観の明示が不足（私は/〜と感じます 等）。")

    # テンポ（簡易）：平均文長・短文比率・段落長
    sentences = [s for s in re.split(r"[。！？]\s*", text) if s.strip()]
    avg_len = sum(len(s) for s in sentences) / max(1, len(sentences))
    short_ratio = sum(1 for s in sentences if len(s) <= 30) / max(1, len(sentences))
    if avg_len > 60:
        score -= 0.15
        fb.append(f"平均文長が長い: {avg_len:.1f}（<=60推奨）。")
    if short_ratio < 0.15:
        score -= 0.1
        fb.append("短文が少ない。テンポに緩急を。")
    # 段落長
    paras = [p for p in text.splitlines() if p.strip()]
    if any(len(p) > 220 for p in paras):
        score -= 0.1
        fb.append("長過ぎる段落があります（>220字）。")

    # 導入100字以内：KW＋結論の要旨
    head = text[:120]
    if _normalize(keyword) not in _normalize(head):
        score -= 0.1
        fb.append("導入100字以内に主要キーワードが不足。")
    if not re.search(r"(結論|要するに|端的に言うと|まず結論)", head):
        score -= 0.1
        fb.append("導入で結論先出しが弱い。")

    # 見出し一致性（H2/H3がアウトラインと完全一致か）
    h2o = [ln.strip() for ln in outline.splitlines() if ln.strip().startswith("## ")]
    h3o = [ln.strip() for ln in outline.splitlines() if ln.strip().startswith("### ")]
    h2a = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("## ")]
    h3a = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("### ")]
    if h2o != h2a:
        score -= 0.3
        fb.append("本文側のH2がアウトラインと一致していません（文言/順序の差異）。")
    if h3o and h3o != h3a:
        score -= 0.1
        fb.append("本文側のH3がアウトラインと一致していません。")

    if not fb:
        fb = ["perfect"]
    return {"score": max(0.0, min(1.0, score)), "feedback": " | ".join(fb)}

# ====== コンテンツ（内容）評価 ======
def extract_facts_from_context(context: str) -> List[str]:
    """context（箇条書き推奨）から“記事で触れてほしい要点”を抽出。"""
    bullets = [ln[2:].strip() for ln in context.splitlines() if ln.strip().startswith("- ")]
    facts: List[str] = []
    for b in bullets:
        b = _strip_urls(b)
        if len(b) >= 6:
            facts.append(b)
    return facts[:30]  # 上限

def rough_match(needle: str, hay: str) -> bool:
    """超簡易の意味的近傍：正規化＋部分一致。"""
    n = _normalize(needle)
    h = _normalize(hay)
    if len(n) < 6:  # 短すぎると誤検出
        return False
    return n in h

def score_content(context: str, article: str) -> Dict[str, Any]:
    facts = extract_facts_from_context(context)
    if not facts:
        return {"score": 0.5, "feedback": "no-context (neutral 0.5)"}
    covered = sum(1 for f in facts if rough_match(f, article))
    coverage = covered / max(1, len(facts))
    fb = f"coverage={coverage:.2f} ({covered}/{len(facts)})"
    # 単純カバレッジを0.3〜1.0に射影（下駄を履かせ過ぎない）
    score = 0.3 + 0.7 * coverage
    return {"score": max(0.0, min(1.0, score)), "feedback": fb}

def judge_consistency_llm(context: str, article: str) -> Tuple[float, str]:
    """
    LLMに整合性を簡易判定させる（追加コスト）。
    戻り値: (score[0..1], feedback_str)
    """
    if not context.strip():
        return 0.5, "no-context (neutral)"

    prompt = f"""次の context（一次情報の要点）に対して、本文がどの程度整合しているかを判定してください。
- 判定: "consistent" / "ambiguous" / "contradictory" のいずれか
- 理由を一文で
- 200字以内で日本語で回答

[context]
{context}

[article]
{article[:1800]}
"""
    lm = dspy.LM(MODEL, api_key=API_KEY)
    res = lm(prompt)
    text = res if isinstance(res, str) else str(res)
    t = text.lower()
    if "contradict" in t:
        return 0.2, f"judge={text.strip()}"
    if "ambig" in t:
        return 0.5, f"judge={text.strip()}"
    return 0.8, f"judge={text.strip()}"

# ====== GEPA メトリクス（score + feedback） ======
FORM_WEIGHT = 0.7
CONTENT_WEIGHT = 0.3  # LLMジャッジを使う場合、内部で合算時に少し重みを調整してもよい

def metric_title(gold, pred, **kwargs):
    return score_title(gold.keyword, pred.title)

def metric_outline(gold, pred, **kwargs):
    return score_outline(gold.title, gold.keyword, pred.outline)

def metric_draft(gold, pred, **kwargs):
    # gold には title/keyword/outline/context を渡しておく
    form = score_draft_form(gold.title, gold.keyword, gold.outline, pred.article)
    content = score_content(gold.context, pred.article)
    score = FORM_WEIGHT * form["score"] + CONTENT_WEIGHT * content["score"]
    fb = f"[form] {form['feedback']} || [content] {content['feedback']}"
    return {"score": score, "feedback": fb}

# ====== Student（最適化対象） ======
title_prog   = dspy.Predict(MakeTitle)
outline_prog = dspy.Predict(MakeOutline)
draft_prog   = dspy.Predict(MakeDraft)

def _toy_outline_from_keyword(keyword: str) -> str:
    """訓練用のダミーアウトライン（MakeDraft の入力用/GEPAの最初の足場）"""
    base = [
        "## まず結論：{kw}の要点を一言で",
        "## 真相と背景：なぜ{kw}はそう見えるのか",
        "## 具体例：私の体験とケース",
        "## 手順とコツ：今日からできる最小ステップ",
        "## 注意と落とし穴：やりがちな勘違い",
        "## まとめ：{kw}で失敗しない考え方",
    ]
    return "\n".join(s.format(kw=keyword) for s in base)

def _examples_for(sig_name: str) -> List[dspy.Example]:
    """各Signatureの入力項目に合わせた学習用Example"""
    exs: List[dspy.Example] = []
    for k in TRAIN_KEYWORDS:
        title = f"【{k}】の結論と真相：迷わず進むための要点"
        context = "- サンプル: これはダミーの一次情報要約です\n- 具体の数値や固有名詞を入れると評価が上がる設計です"
        if sig_name == "title":
            exs.append(dspy.Example(keyword=k).with_inputs("keyword"))
        elif sig_name == "outline":
            exs.append(dspy.Example(title=title, keyword=k, context=context).with_inputs("title", "keyword", "context"))
        elif sig_name == "draft":
            outline = _toy_outline_from_keyword(k)
            exs.append(
                dspy.Example(title=title, keyword=k, outline=outline, context=context).with_inputs("title", "keyword", "outline", "context")
            )
    return exs

def optimize_all(track_stats: bool = True) -> Dict[str, Any]:
    res = {}
    # Title
    gepa_t = dspy.GEPA(metric=metric_title, auto="light", track_stats=track_stats)
    opt_t  = gepa_t.compile(student=title_prog,   trainset=_examples_for("title"),   valset=_examples_for("title"))
    # Outline
    gepa_o = dspy.GEPA(metric=metric_outline, auto="light", track_stats=track_stats)
    opt_o  = gepa_o.compile(student=outline_prog, trainset=_examples_for("outline"), valset=_examples_for("outline"))
    # Draft
    gepa_d = dspy.GEPA(metric=metric_draft, auto="light", track_stats=track_stats)
    opt_d  = gepa_d.compile(student=draft_prog,   trainset=_examples_for("draft"),   valset=_examples_for("draft"))
    res["title"] = opt_t
    res["outline"] = opt_o
    res["draft"] = opt_d
    return res

def save_learned_prompts(optimized: Dict[str, Any], outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for name, prog in optimized.items():
        try:
            spec = {
                "signature_doc": prog.signature.__doc__,
                "fields": {f.name: f.desc for f in prog.signature.fields()},
                "repr": repr(prog),
            }
        except Exception:
            spec = {"repr": repr(prog)}
        (outdir / f"{name}_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "README.txt").write_text("GEPAで最適化した指示仕様（reprも保存）", encoding="utf-8")

def generate_with(optimized: Dict[str, Any], keyword: str, context: str) -> Dict[str, str]:
    t = optimized["title"](keyword=keyword).title
    o = optimized["outline"](title=t, keyword=keyword, context=context).outline
    a = optimized["draft"](title=t, keyword=keyword, outline=o, context=context).article
    return {"title": t, "outline": o, "article": a}

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--optimize", action="store_true", help="GEPAで最適化を行う")
    p.add_argument("--keyword", type=str, default="GEPA プロンプト 最適化", help="テスト生成用のキーワード")
    p.add_argument("--info", type=str, default="", help="info.json のパス（一次情報）")
    p.add_argument("--save", action="store_true", help="学習した指示仕様を prompts/gepa/ に保存")
    p.add_argument("--judge", action="store_true", help="LLM整合性ジャッジを追加実行（追加コスト）")
    args = p.parse_args()

    info_data = load_info(args.info) if args.info else {}
    context = flatten_info_to_context(info_data)

    if args.optimize:
        print("[*] GEPA optimizing (title / outline / draft)...")
        optimized = optimize_all(track_stats=True)
        print("[*] done.")
        if args.save:
            outdir = Path("prompts") / "gepa"
            save_learned_prompts(optimized, outdir)
            print(f"[*] saved learned specs to: {outdir}")
    else:
        # 既定では“未最適化”のままでも動く
        optimized = {"title": title_prog, "outline": outline_prog, "draft": draft_prog}

    # 生成テスト
    print(f"[*] test keyword: {args.keyword}")
    if context:
        print("[*] context: loaded from info.json (stripped URLs)")
    else:
        print("[*] context: <empty>")

    sample = generate_with(optimized, args.keyword, context)
    print("\n=== TITLE ===\n" + sample["title"])
    print("\n=== OUTLINE ===\n" + sample["outline"])
    print("\n=== ARTICLE (head) ===\n" + sample["article"][:800] + " ...")

    # スコア表示（フォーム＋内容）
    print("\n=== SCORES ===")
    form = score_draft_form(sample["title"], args.keyword, sample["outline"], sample["article"])
    cont = score_content(context, sample["article"])
    total = FORM_WEIGHT * form["score"] + CONTENT_WEIGHT * cont["score"]
    print(f"FORM: {form['score']:.2f} | {form['feedback']}")
    print(f"CONT: {cont['score']:.2f} | {cont['feedback']}")
    print(f"TOTAL: {total:.2f} (w_form={FORM_WEIGHT}, w_content={CONTENT_WEIGHT})")

    # 任意：LLM 整合性ジャッジ
    if args.judge:
        js, jf = judge_consistency_llm(context, sample["article"])
        print(f"\n=== LLM JUDGE ===\nscore={js:.2f} | {jf}")

if __name__ == "__main__":
    main()
