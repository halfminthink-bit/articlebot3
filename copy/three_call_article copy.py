# three_call_article.py
# -*- coding: utf-8 -*-

import os
import re
import json
import argparse
import pathlib
import random
import sys
from typing import Any, Dict, List, Tuple, Optional
from dotenv import load_dotenv
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent

# ─────────────── 既定パス（必要に応じて修正してください） ───────────────
DEFAULT_INFO            = pathlib.Path(r"C:\Users\hyokaimen\kyota\articlebot2\data\info.json")
DEFAULT_PERSONA_URLS    = pathlib.Path(r"C:\Users\hyokaimen\kyota\articlebot2\data\persona_urls.txt")
DEFAULT_TITLE_PROMPT    = pathlib.Path(r"C:\Users\hyokaimen\kyota\articlebot2\good_promptstitle_prompt_pre_outline.txt")
DEFAULT_OUTLINE_PROMPT  = pathlib.Path(r"C:\Users\hyokaimen\kyota\articlebot2\good_promptsoutline_prompt_2call.txt")
DEFAULT_DRAFT_PROMPT    = pathlib.Path(r"C:\Users\hyokaimen\kyota\articlebot2\good_promptsdraft_prompt_2call.txt")
DEFAULT_OUTDIR          = pathlib.Path("out")

# .env を（スクリプト隣優先で）ロード
load_dotenv(dotenv_path=ROOT / ".env", override=True)

MODEL_TITLE   = os.getenv("MODEL_TITLE", "gpt-4o").strip()
MODEL_OUTLINE = os.getenv("MODEL_OUTLINE", "gpt-4o").strip()
MODEL_DRAFT   = os.getenv("MODEL_DRAFT", "gpt-4o").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY が見つかりません。.env を設定してください。")

client = OpenAI(api_key=OPENAI_API_KEY)

# ─────────────── ユーティリティ ───────────────
def log(msg: str):
    print(msg, file=sys.stdout, flush=True)

def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")

def read_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(read_text(path))

def read_lines_strip(path: pathlib.Path) -> List[str]:
    if not path.exists():
        return []
    lines = [ln.strip() for ln in read_text(path).splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]

def ensure_outdir(path: pathlib.Path):
    path.mkdir(parents=True, exist_ok=True)

def save(path: pathlib.Path, content: str):
    path.write_text(content, encoding="utf-8")

def save_json(path: pathlib.Path, obj: Any):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def derive_persona_label(info: Dict[str, Any]) -> str:
    return (info.get("persona_label")
            or info.get("persona", {}).get("persona_label")
            or "外部ライター（第三者視点）")

def derive_target(info: Dict[str, Any]) -> str:
    for k in ("target_name", "person_name", "company_name", "target"):
        v = info.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "対象"

def title_samples(info: Dict[str, Any]) -> List[str]:
    v = info.get("title_samples", [])
    return v if isinstance(v, list) else []

def derive_primary_keyword(info: Dict[str, Any]) -> str:
    v = info.get("primary_keyword")
    if isinstance(v, str) and v.strip():
        return v.strip()
    raise ValueError(
        "primary_keyword が info.json に存在しません。例：\n"
        '{\n'
        '  "primary_keyword": "PLAUD NOTE",\n'
        '  "title_samples": [],\n'
        '  "target_name": "PLAUD NOTE の検証記事"\n'
        '}'
    )

# ─────────────── OpenAI 呼び出し ───────────────
def call_llm(model: str, system: str, user: str, temperature: float = 0.5, max_tokens: int = 6000) -> str:
    log(f"[LLM] call -> model={model} temp={temperature} max_tokens={max_tokens}")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"system","content":system},
                  {"role":"user","content":user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = (resp.choices[0].message.content or "").strip()
    log(f"[LLM] ok <- chars={len(text)}")
    return text

# ─────────────── プレースホルダ充填 ───────────────
def fill_title_prompt(tpl: str, info: Dict[str, Any], persona_urls: List[str]) -> str:
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<TITLE_SAMPLES>>>", json.dumps(title_samples(info), ensure_ascii=False))
            .replace("<<<PRIMARY_KEYWORD>>>", derive_primary_keyword(info))
            )

def fill_outline_prompt(tpl: str,
                        info: Dict[str, Any],
                        persona_urls: List[str],
                        selected_title: str) -> str:
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<TITLE_SAMPLES>>>", json.dumps(title_samples(info), ensure_ascii=False))
            .replace("<<<TARGET_NAME>>>", derive_target(info))
            .replace("<<<PERSONA_LABEL>>>", derive_persona_label(info))
            .replace("<<<SELECTED_TITLE>>>", selected_title)
            )

def fill_draft_prompt(tpl: str, info: Dict[str, Any], persona_urls: List[str], outline_text: str) -> str:
    approx_len = info.get("target_length_chars", 3000)
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<OUTLINE_TEXT>>>", outline_text)
            .replace("<<<TARGET_NAME>>>", derive_target(info))
            .replace("<<<PERSONA_LABEL>>>", derive_persona_label(info))
            .replace("<<<TARGET_LENGTH_CHARS>>>", str(approx_len))
            )

# ─────────────── タイトル出力の簡易パース（未使用だが互換のため残置） ───────────────
TITLE_LINE_RE = re.compile(r"^\s*(\d)[\.\)]\s*(.+?)\s*$", re.UNICODE)
SELECTED_INDEX_RE = re.compile(r"^\s*SELECTED_INDEX\s*:\s*([1-5])\s*$", re.IGNORECASE)
SELECTED_TITLE_RE = re.compile(r"^\s*SELECTED_TITLE\s*:\s*(.+?)\s*$", re.IGNORECASE)

def parse_title_output(text: str) -> Tuple[List[str], Optional[int], Optional[str]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    titles: List[str] = []
    selected_index: Optional[int] = None
    selected_title: Optional[str] = None

    for ln in lines:
        m = TITLE_LINE_RE.match(ln)
        if m:
            idx = int(m.group(1))
            title = m.group(2)
            if 1 <= idx <= 5:
                while len(titles) < idx:
                    titles.append("")
                titles[idx-1] = title
            continue
        m = SELECTED_INDEX_RE.match(ln)
        if m:
            selected_index = int(m.group(1))
            continue
        m = SELECTED_TITLE_RE.match(ln)
        if m:
            selected_title = m.group(1)
            continue

    if selected_title is None and selected_index and 1 <= selected_index <= len(titles) and titles[selected_index-1]:
        selected_title = titles[selected_index-1]

    if (selected_index is None or selected_title is None) and titles:
        idx0 = random.randrange(0, min(5, len(titles)))
        selected_index = idx0 + 1
        selected_title = titles[idx0]

    titles = [t for t in titles if t]
    return titles, selected_index, selected_title

# ─────────────── メインフロー ───────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info",            default=str(DEFAULT_INFO))
    ap.add_argument("--persona_urls",    default=str(DEFAULT_PERSONA_URLS))
    ap.add_argument("--title_prompt",    default=str(DEFAULT_TITLE_PROMPT))
    ap.add_argument("--outline_prompt",  default=str(DEFAULT_OUTLINE_PROMPT))
    ap.add_argument("--draft_prompt",    default=str(DEFAULT_DRAFT_PROMPT))
    ap.add_argument("--out",             default=str(DEFAULT_OUTDIR))
    ap.add_argument("--t0", type=float, default=0.7, help="タイトル用 temperature")
    ap.add_argument("--t1", type=float, default=0.6, help="アウトライン用 temperature")
    ap.add_argument("--t2", type=float, default=0.6, help="本文用 temperature")
    args = ap.parse_args()

    info_path     = pathlib.Path(args.info)
    persona_path  = pathlib.Path(args.persona_urls)
    title_prompt  = pathlib.Path(args.title_prompt)  # 互換のため保持（存在チェックは任意）
    out_prompt    = pathlib.Path(args.outline_prompt)
    draft_prompt  = pathlib.Path(args.draft_prompt)
    outdir        = pathlib.Path(args.out)
    ensure_outdir(outdir)

    # タイトル選定をスキップしていたが、必要時のみ発火させるため title_prompt の存在チェックは必須にしない
    for p in (info_path, out_prompt, draft_prompt):
        if not p.exists():
            raise FileNotFoundError(f"見つかりません: {p}")

    info = read_json(info_path)
    _ = derive_primary_keyword(info)  # 早期検証

    persona_urls = read_lines_strip(persona_path)  # 空でも可
    outline_tpl  = read_text(out_prompt)
    draft_tpl    = read_text(draft_prompt)

    # ① タイトル決定：まずフォールバックで決める
    log("[STEP] Title resolution start (fallback first)")
    sel_title = (
        (info.get("selected_title") or "").strip()
        or (info.get("title") or "").strip()
        or derive_primary_keyword(info).strip()
    )

    pk = derive_primary_keyword(info).strip()

    def _norm(s: str) -> str:
        # 空白・一部の括弧・装飾・句読点・疑問/感嘆符を除去して比較
        return re.sub(r"[ \t\u3000「」『』\"'【】\[\]()（）!?！？\-—｜|：:・…]", "", s or "")

    # “pkそのまま問題”を検知：空/同値/短すぎ をタイトル不十分とみなす
    needs_gen = (not sel_title) or (_norm(sel_title) == _norm(pk)) or (len(sel_title) < max(6, len(pk) + 2))

    title_prompt_path_str = "(skipped)"
    title_candidates_preview = "SKIPPED"

    if needs_gen:
        log("[STEP] Title seems insufficient -> try single-shot generation")
        if title_prompt.exists():
            try:
                tpl = read_text(title_prompt)
                user_title = fill_title_prompt(tpl, info, persona_urls)
                system_title = (
                    "あなたはnote記事の編集者です。<<<PRIMARY_KEYWORD>>>を自然に含めた、"
                    "検索意図に合致し読みたくなるSEOタイトルを1本だけ返してください。"
                    "装飾や誇張は最小限にし、信頼感・具体性・読者メリットが一読で伝わる表現にしてください。"
                )
                gen = call_llm(MODEL_TITLE, system_title, user_title, temperature=args.t0, max_tokens=300)
                # 先頭行のみ採用し、引用符を除去
                first_line = (gen.splitlines()[0] if gen else "").strip().strip('\'"')
                if first_line:
                    sel_title = first_line
                    title_candidates_preview = gen[:500]
                    title_prompt_path_str = str(title_prompt)
                    save(outdir / "title_candidates.txt", gen)
                    log(f"[STEP] Title generated -> {sel_title}")
                else:
                    raise RuntimeError("empty title from LLM")
            except Exception as e:
                log(f"[WARN] title generation failed ({e}); use safe synthesized title")
                sel_title = f"{pk}の実像を一次情報で検証—料金・使い方・向いている人"
                save(outdir / "title_candidates.txt", "AUTO-FALLBACK: generation failed\n")
        else:
            # title_prompt が無い場合の最終合成
            log("[WARN] title_prompt not found; use safe synthesized title")
            sel_title = f"{pk}の実像を一次情報で検証—料金・使い方・向いている人"
            save(outdir / "title_candidates.txt", "AUTO-FALLBACK: no title prompt found\n")
    else:
        save(outdir / "title_candidates.txt", "SKIPPED: title selection disabled\n")
        log(f"[STEP] Title accepted from info -> {sel_title}")

    save(outdir / "selected_title.txt", sel_title)

    # ② アウトライン
    log("[STEP] Outline generation start")
    system_outline = (
        f"あなたは{derive_persona_label(info)}として、編集構成を作る熟練の構成作家です。"
        "出力形式はプロンプトの指示に従い、必要ならMarkdownなど自由な体裁で。"
        "アウトラインは“人格に寄せた構成・視座・文体・立場”を反映し、機械的なテンプレを避けてください。"
    )
    user_outline = fill_outline_prompt(outline_tpl, info, persona_urls, sel_title)
    outline_text = call_llm(MODEL_OUTLINE, system_outline, user_outline, temperature=args.t1, max_tokens=6000)
    save(outdir / "outline.txt", outline_text)
    log("[STEP] Outline generated")

    # ③ 本文
    log("[STEP] Draft generation start")
    system_draft = (
        f"あなたは{derive_persona_label(info)}として、冷静で説得力のある本文を書く熟練ライターです。"
        "アウトラインの意図を汲み、情報の羅列を避け、適切に見解や示唆を織り込みます。"
        "日本語で約3000字（±10%の範囲は許容）。出力形式はプロンプト指示に従うこと。"
    )
    user_draft   = fill_draft_prompt(draft_tpl, info, persona_urls, outline_text)
    article_text = call_llm(MODEL_DRAFT, system_draft, user_draft, temperature=args.t2, max_tokens=8000)
    save(outdir / "article.md", article_text)
    log("[STEP] Draft saved -> article.md")

    # 再現用コンテキスト
    save_json(outdir / "context.json", {
        "models": {"title": MODEL_TITLE, "outline": MODEL_OUTLINE, "draft": MODEL_DRAFT},
        "paths": {
            "info": str(info_path),
            "persona_urls": str(persona_path),
            "title_prompt": title_prompt_path_str,
            "outline_prompt": str(out_prompt),
            "draft_prompt": str(draft_prompt),
        },
        "temps": {"t0_title": args.t0, "t1_outline": args.t1, "t2_draft": args.t2},
        "target_name": derive_target(info),
        "persona_label": derive_persona_label(info),
        "primary_keyword": pk,
        "persona_urls": persona_urls,
        "selected_title": sel_title,
        "selected_title_source": (
            "generated" if title_prompt_path_str not in ("(skipped)", "") and title_candidates_preview != "SKIPPED"
            else ("info.selected_title" if info.get("selected_title") else
                  "info.title" if info.get("title") else
                  "info.primary_keyword")
        ),
        "title_candidates_preview": title_candidates_preview,
        "outline_preview": outline_text[:500]
    })

    print("[OK] title_candidates.txt / selected_title.txt / outline.txt / article.md を生成しました。")

if __name__ == "__main__":
    main()
