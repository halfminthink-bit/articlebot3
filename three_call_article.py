# three_call_article.py（OpenAI／Anthropic 切替対応＋CSVキーワード一括対応版）
# -*- coding: utf-8 -*-
"""
変更点（要約）
- 既存の info.json 単発生成はそのままに、`--keywords_csv` を渡すと CSV から順にキーワードを読み、
  行ごとに info を合成 → タイトル/アウトライン/本文を生成して保存。
- CSV は先頭から順に処理し、`status` 列が空 or READY の行だけを対象。成功した行は `DONE` に上書き保存。
- 列名はデフォルトで `keyword` / `status` / （任意）`affiliate_url`/`search_intent`/`angle`/`silo`/`persona`。
  列名は引数で変更可（--csv_keyword_col など）。

使い方（例）
  python three_call_article.py --keywords_csv data/keywords.csv --info C:\\...\\info.json --out out
  # 既存通り1本生成：
  python three_call_article.py --info C:\\...\\info.json --out out
"""

import os
import re
import csv
import json
import argparse
import pathlib
import random
import sys
from typing import Any, Dict, List, Tuple, Optional

from dotenv import load_dotenv

# ───────── LLMクライアント（必要に応じて import） ─────────
from openai import OpenAI  # pip install openai

try:
    from anthropic import Anthropic  # pip install anthropic（Claude使用時）
except Exception:
    Anthropic = None  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parent

# ─────────────── 既定パス（必要に応じて修正してください） ───────────────
DEFAULT_INFO            = pathlib.Path(r"C:\\Users\\hyokaimen\\kyota\\articlebot2\\data\\info.json")
DEFAULT_PERSONA_URLS    = pathlib.Path(r"C:\\Users\\hyokaimen\\kyota\\articlebot2\\data\\persona_urls.txt")
DEFAULT_TITLE_PROMPT    = pathlib.Path(r"C:\\Users\\hyokaimen\\kyota\\articlebot2\\good_prompts\\title_prompt_pre_outline.txt")
DEFAULT_OUTLINE_PROMPT  = pathlib.Path(r"C:\\Users\\hyokaimen\\kyota\\articlebot2\\good_prompts\\outline_prompt_2call.txt")
DEFAULT_DRAFT_PROMPT    = pathlib.Path(r"C:\\Users\\hyokaimen\\kyota\\articlebot2\\good_prompts\\draft_prompt_2call.txt")
DEFAULT_OUTDIR          = pathlib.Path("out")

# .env を（スクリプト隣優先で）ロード
load_dotenv(dotenv_path=ROOT / ".env", override=True)

# ─────────────── Provider & API Keys ───────────────
PROVIDER = os.getenv("PROVIDER", "openai").strip().lower()  # openai / anthropic
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "").strip()
CLAUDE_API_KEY  = os.getenv("CLAUDE_API_KEY", "").strip()

MODEL_DEFAULT_OPENAI      = "gpt-4o"
MODEL_DEFAULT_ANTHROPIC   = "claude-3-5-sonnet-latest"
MODEL_TITLE   = os.getenv("MODEL_TITLE",  (MODEL_DEFAULT_ANTHROPIC if PROVIDER=="anthropic" else MODEL_DEFAULT_OPENAI)).strip()
MODEL_OUTLINE = os.getenv("MODEL_OUTLINE",(MODEL_DEFAULT_ANTHROPIC if PROVIDER=="anthropic" else MODEL_DEFAULT_OPENAI)).strip()
MODEL_DRAFT   = os.getenv("MODEL_DRAFT",  (MODEL_DEFAULT_ANTHROPIC if PROVIDER=="anthropic" else MODEL_DEFAULT_OPENAI)).strip()

client_oa: Optional[OpenAI] = None
client_an: Optional[Anthropic] = None  # type: ignore

if PROVIDER == "openai":
    if not OPENAI_API_KEY:
        raise RuntimeError("PROVIDER=openai ですが OPENAI_API_KEY が見つかりません。.env を設定してください。")
    client_oa = OpenAI(api_key=OPENAI_API_KEY)
elif PROVIDER == "anthropic":
    if not CLAUDE_API_KEY:
        raise RuntimeError("PROVIDER=anthropic ですが CLAUDE_API_KEY が見つかりません。.env を設定してください。")
    if Anthropic is None:
        raise RuntimeError("anthropic パッケージが見つかりません。'pip install anthropic' を実行してください。")
    client_an = Anthropic(api_key=CLAUDE_API_KEY)
else:
    raise RuntimeError(f"未知の PROVIDER={PROVIDER}. 'openai' または 'anthropic' を指定してください。")

# ─────────────── 基本ユーティリティ ───────────────

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

# ─────────────── プレースホルダ前処理（追加） ───────────────

_PLACEHOLDER_LINE_RE = re.compile(r'^\s*[#>\-\s]*<{3}[^>]+>{3}\s*$')

def preprocess_prompt(text: str, selected_title: str, primary_keyword: str) -> str:
    """LLM投入前に、角カッコ3つの記法を除去・置換する前処理。"""
    if not text:
        return text

    # 既知の置換（安全に生値へ）
    text = text.replace("<<<SELECTED_TITLE>>>", selected_title)
    text = text.replace("<<<PRIMARY_KEYWORD>>>", primary_keyword)

    # 万一、他の <<<...>>> が残っていても出力に影響しないように行ごと除去
    lines = []
    for ln in text.splitlines():
        if _PLACEHOLDER_LINE_RE.match(ln):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def sanitize_generated_markdown(md: str, selected_title: str) -> str:
    """保険：生成物に <<<...>>> や二重H1が混入した場合の後処理。"""
    lines = md.splitlines()

    # 1) <<<...>>> 行を除去
    lines = [ln for ln in lines if not _PLACEHOLDER_LINE_RE.match(ln)]

    # 2) 先頭H1を selected_title に正規化（なければ付与）
    h1_pat = re.compile(r'^\s*#\s*(.+?)\s*$')
    found_h1 = False
    new_lines = []
    for ln in lines:
        m = h1_pat.match(ln)
        if m and not found_h1:
            new_lines.append(f"# {selected_title}")
            found_h1 = True
        else:
            new_lines.append(ln)
    lines = new_lines

    # 3) 同一H1の重複を削除
    deduped = []
    h1_seen = False
    for ln in lines:
        m = h1_pat.match(ln)
        if m and m.group(1).strip() == selected_title.strip():
            if h1_seen:
                continue
            h1_seen = True
        deduped.append(ln)

    return "\n".join(deduped).strip()

# ─────────────── info 派生ヘルパ ───────────────

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

# ─────────────── LLM 呼び出し ───────────────

def call_llm(model: str, system: str, user: str, temperature: float = 0.5, max_tokens: int = 6000) -> str:
    log(f"[LLM] call -> provider={PROVIDER} model={model} temp={temperature} max_tokens={max_tokens}")

    if PROVIDER == "anthropic":
        assert client_an is not None
        resp = client_an.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        chunks: List[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                chunks.append(getattr(block, "text", ""))
        text = "".join(chunks).strip()
        log(f"[LLM] ok <- chars={len(text)} (anthropic)")
        return text

    # OpenAI の場合
    assert client_oa is not None
    
    # 基本パラメータ
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    # 試行1: デフォルトパラメータで試行
    try:
        resp = client_oa.chat.completions.create(**params)
        text = (resp.choices[0].message.content or "").strip()
        log(f"[LLM] ok <- chars={len(text)} (openai: default params)")
        return text
    except Exception as e:
        error_msg = str(e).lower()
        
        # エラーパターン1: max_tokens 問題
        if "max_tokens" in error_msg and ("unsupported" in error_msg or "not supported" in error_msg):
            log(f"[LLM] max_tokens not supported, switching to max_completion_tokens...")
            params.pop("max_tokens", None)
            params["max_completion_tokens"] = max_tokens
            
            # 試行2: max_completion_tokens で再試行
            try:
                resp = client_oa.chat.completions.create(**params)
                text = (resp.choices[0].message.content or "").strip()
                log(f"[LLM] ok <- chars={len(text)} (openai: max_completion_tokens)")
                return text
            except Exception as e2:
                error_msg2 = str(e2).lower()
                
                # エラーパターン2: temperature 問題
                if "temperature" in error_msg2 and "unsupported" in error_msg2:
                    log(f"[LLM] temperature not supported, removing it...")
                    params.pop("temperature", None)
                    
                    # 試行3: temperature を削除して再試行
                    try:
                        resp = client_oa.chat.completions.create(**params)
                        text = (resp.choices[0].message.content or "").strip()
                        log(f"[LLM] ok <- chars={len(text)} (openai: no temperature)")
                        return text
                    except Exception as e3:
                        log(f"[LLM] ERROR: all attempts failed")
                        raise e3
                else:
                    raise e2
        
        # エラーパターン3: temperature 問題（最初から）
        elif "temperature" in error_msg and "unsupported" in error_msg:
            log(f"[LLM] temperature not supported, removing it...")
            params.pop("temperature", None)
            
            # 試行2b: temperature を削除して再試行
            try:
                resp = client_oa.chat.completions.create(**params)
                text = (resp.choices[0].message.content or "").strip()
                log(f"[LLM] ok <- chars={len(text)} (openai: no temperature)")
                return text
            except Exception as e2:
                error_msg2 = str(e2).lower()
                
                # max_tokens 問題が後から出た場合
                if "max_tokens" in error_msg2 and ("unsupported" in error_msg2 or "not supported" in error_msg2):
                    log(f"[LLM] max_tokens also not supported, switching to max_completion_tokens...")
                    params.pop("max_tokens", None)
                    params["max_completion_tokens"] = max_tokens
                    
                    # 試行3: max_completion_tokens で再試行
                    try:
                        resp = client_oa.chat.completions.create(**params)
                        text = (resp.choices[0].message.content or "").strip()
                        log(f"[LLM] ok <- chars={len(text)} (openai: no temp + max_completion_tokens)")
                        return text
                    except Exception as e3:
                        log(f"[LLM] ERROR: all attempts failed")
                        raise e3
                else:
                    raise e2
        else:
            # その他のエラーはそのまま raise
            raise e

# ─────────────── プロンプト充填 ───────────────

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

# ─────────────── タイトル出力の簡易パース（互換維持） ───────────────

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

# ─────────────── 1本生成ロジックを関数化 ───────────────

def generate_once_from_info(info: Dict[str, Any],
                            persona_urls: List[str],
                            title_prompt_path: pathlib.Path,
                            outline_tpl: str,
                            draft_tpl: str,
                            outdir: pathlib.Path,
                            t0: float, t1: float, t2: float) -> Dict[str, Any]:
    ensure_outdir(outdir)

    # ① タイトル
    log("[STEP] Title resolution start (fallback first)")
    sel_title = (
        (info.get("selected_title") or "").strip()
        or (info.get("title") or "").strip()
        or derive_primary_keyword(info).strip()
    )

    pk = derive_primary_keyword(info).strip()

    def _norm(s: str) -> str:
        return re.sub(r"[ \t\u3000「」『』\"'【】\[\]()（）!?！？\-—｜|：:・…]", "", s or "")

    needs_gen = (not sel_title) or (_norm(sel_title) == _norm(pk)) or (len(sel_title) < max(6, len(pk) + 2))

    title_prompt_path_str = "(skipped)"
    title_candidates_preview = "SKIPPED"

    if needs_gen:
        log("[STEP] Title seems insufficient -> try single-shot generation")
        if title_prompt_path.exists():
            try:
                tpl = read_text(title_prompt_path)
                user_title = fill_title_prompt(tpl, info, persona_urls)
                system_title = (
                    f"あなたはnote記事の編集者です。<<<PRIMARY_KEYWORD>>>を自然に含めた、"
                    f"検索意図に合致し読みたくなるSEOタイトルを1本だけ返してください。"
                    f"装飾や誇張は最小限にし、信頼感・具体性・読者メリットが一読で伝わる表現にしてください。"
                )
                gen = call_llm(MODEL_TITLE, system_title, user_title, temperature=t0, max_tokens=300)
                first_line = (gen.splitlines()[0] if gen else "").strip().strip('\'"')
                if first_line:
                    sel_title = first_line
                    title_candidates_preview = gen[:500]
                    title_prompt_path_str = str(title_prompt_path)
                    save(outdir / "title_candidates.txt", gen)
                    log(f"[STEP] Title generated -> {sel_title}")
                else:
                    raise RuntimeError("empty title from LLM")
            except Exception as e:
                log(f"[WARN] title generation failed ({e}); use safe synthesized title")
                sel_title = f"{pk}の実像を一次情報で検証—料金・使い方・向いている人"
                save(outdir / "title_candidates.txt", "AUTO-FALLBACK: generation failed\n")
        else:
            log("[WARN] title_prompt not found; use safe synthesized title")
            sel_title = f"{pk}の実像を一次情報で検証—料金・使い方・向いている人"
            save(outdir / "title_candidates.txt", "AUTO-FALLBACK: no title prompt found\n")
    else:
        save(outdir / "title_candidates.txt", "SKIPPED: title selection disabled\n")
        log(f"[STEP] Title accepted from info -> {sel_title}")

    save(outdir / "selected_title.txt", sel_title)

    # ② アウトライン
    log("[STEP] Outline generation start]")
    system_outline = (
        f"あなたは{derive_persona_label(info)}として、編集構成を作る熟練の構成作家です。"
        f"出力形式はプロンプトの指示に従い、必要ならMarkdownなど自由な体裁で。"
        f"アウトラインは「人格に寄せた構成・視座・文体・立場」を反映し、機械的なテンプレを避けてください。"
    )
    user_outline = fill_outline_prompt(outline_tpl, info, persona_urls, sel_title)
    
    # 【追加】投入直前の前処理
    user_outline = preprocess_prompt(user_outline, selected_title=sel_title, primary_keyword=pk)
    
    outline_text = call_llm(MODEL_OUTLINE, system_outline, user_outline, temperature=t1, max_tokens=6000)
    save(outdir / "outline.txt", outline_text)
    log("[STEP] Outline generated")

    # ③ 本文
    log("[STEP] Draft generation start")
    system_draft = (
        f"あなたは{derive_persona_label(info)}として、冷静で説得力のある本文を書く熟練ライターです。"
        f"アウトラインの意図を汲み、情報の羅列を避け、適切に見解や示唆を織り込みます。"
        f"日本語で約3000字（±10%の範囲は許容）。出力形式はプロンプト指示に従うこと。"
    )
    user_draft = fill_draft_prompt(draft_tpl, info, persona_urls, outline_text)
    
    # 【追加】投入直前の前処理
    user_draft = preprocess_prompt(user_draft, selected_title=sel_title, primary_keyword=pk)
    
    article_text = call_llm(MODEL_DRAFT, system_draft, user_draft, temperature=t2, max_tokens=8000)
    
    # 【追加】生成後の保険サニタイズ
    article_text = sanitize_generated_markdown(article_text, selected_title=sel_title)
    
    save(outdir / "article.md", article_text)
    log("[STEP] Draft saved -> article.md")

    # 再現用コンテキスト
    ctx = {
        "provider": PROVIDER,
        "models": {"title": MODEL_TITLE, "outline": MODEL_OUTLINE, "draft": MODEL_DRAFT},
        "temps": {"t0_title": t0, "t1_outline": t1, "t2_draft": t2},
        "persona_label": derive_persona_label(info),
        "primary_keyword": pk,
        "selected_title": sel_title,
        "outline_preview": outline_text[:500]
    }
    save_json(outdir / "context.json", ctx)
    return ctx

# ─────────────── CSV ループ処理 ───────────────

def try_int(v: Optional[str], default: int) -> int:
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

def process_csv(csv_path: pathlib.Path,
                base_info_path: pathlib.Path,
                persona_path: pathlib.Path,
                title_prompt_path: pathlib.Path,
                outline_prompt_path: pathlib.Path,
                draft_prompt_path: pathlib.Path,
                outdir: pathlib.Path,
                keyword_col: str,
                status_col: str,
                ready_values: List[str],
                done_value: str,
                optional_cols: Dict[str, str],
                limit: int,
                temps: Tuple[float,float,float]) -> None:
    """CSV を先頭から走査し、READY 行を順に処理 → 成功で DONE に上書き保存。"""
    ensure_outdir(outdir)

    # 読み込む
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if keyword_col not in fieldnames:
        raise ValueError(f"CSVに '{keyword_col}' 列がありません: {csv_path}")
    if status_col not in fieldnames:
        fieldnames.append(status_col)  # 無ければ後で列を作る

    # ベース info を読む（行ごとに shallow copy して上書き）
    base_info = read_json(base_info_path)

    persona_urls = read_lines_strip(persona_path)
    outline_tpl  = read_text(outline_prompt_path)
    draft_tpl    = read_text(draft_prompt_path)

    processed = 0

    for idx, row in enumerate(rows):
        if limit and processed >= limit:
            break

        status = (row.get(status_col, "") or "").strip().upper()
        kw     = (row.get(keyword_col, "") or "").strip()
        if not kw:
            continue
        if status and status not in ready_values:
            continue  # 既に処理済みなど

        # info 合成
        info = dict(base_info)
        info["primary_keyword"] = kw
        # 任意列のコピー
        for info_key, csv_col in optional_cols.items():
            if csv_col and (csv_col in row) and row[csv_col].strip():
                info[info_key] = row[csv_col].strip()

        # 出力ディレクトリ（記事ごと）
        slug = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ヶー_]+", "_", kw)[:64]
        article_out = outdir / slug
        ensure_outdir(article_out)

        try:
            ctx = generate_once_from_info(
                info,
                persona_urls,
                title_prompt_path,
                outline_tpl,
                draft_tpl,
                article_out,
                t0=temps[0], t1=temps[1], t2=temps[2]
            )
            rows[idx][status_col] = done_value
            processed += 1
            log(f"[OK] {kw} -> DONE (#{processed})")
        except Exception as e:
            rows[idx][status_col] = f"ERROR: {e}"
            log(f"[ERROR] {kw} -> {e}")

    # 書き戻し
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"[DONE] CSV updated: {csv_path}")

# ─────────────── メイン ───────────────

def main():
    ap = argparse.ArgumentParser()
    # 既存引数
    ap.add_argument("--info",            default=str(DEFAULT_INFO))
    ap.add_argument("--persona_urls",    default=str(DEFAULT_PERSONA_URLS))
    ap.add_argument("--title_prompt",    default=str(DEFAULT_TITLE_PROMPT))
    ap.add_argument("--outline_prompt",  default=str(DEFAULT_OUTLINE_PROMPT))
    ap.add_argument("--draft_prompt",    default=str(DEFAULT_DRAFT_PROMPT))
    ap.add_argument("--out",             default=str(DEFAULT_OUTDIR))
    ap.add_argument("--t0", type=float, default=0.7, help="タイトル用 temperature")
    ap.add_argument("--t1", type=float, default=0.6, help="アウトライン用 temperature")
    ap.add_argument("--t2", type=float, default=0.6, help="本文用 temperature")

    # 追加：CSV 一括モード
    ap.add_argument("--keywords_csv", default="", help="CSVファイルを指定すると一括処理モードになり、READY行を順に処理")
    ap.add_argument("--csv_keyword_col", default="keyword")
    ap.add_argument("--csv_status_col",  default="status")
    ap.add_argument("--csv_ready_values", default=",READY", help="対象とみなす status 値をカンマ区切りで（空文字を含めるには先頭を空にして ',READY' のようにする）")
    ap.add_argument("--csv_done_value",  default="DONE")
    ap.add_argument("--limit", type=int, default=0, help="処理上限（0=無制限）")
    # 任意列→infoキーへのマッピング（存在すれば上書き）
    ap.add_argument("--csv_affiliate_col", default="affiliate_url")
    ap.add_argument("--csv_intent_col",    default="search_intent")
    ap.add_argument("--csv_angle_col",     default="angle")
    ap.add_argument("--csv_silo_col",      default="silo")
    ap.add_argument("--csv_persona_col",   default="persona")

    args = ap.parse_args()

    log(f"[BOOT] provider={PROVIDER} title={MODEL_TITLE} outline={MODEL_OUTLINE} draft={MODEL_DRAFT}")

    info_path     = pathlib.Path(args.info)
    persona_path  = pathlib.Path(args.persona_urls)
    title_prompt  = pathlib.Path(args.title_prompt)
    out_prompt    = pathlib.Path(args.outline_prompt)
    draft_prompt  = pathlib.Path(args.draft_prompt)
    outdir        = pathlib.Path(args.out)
    ensure_outdir(outdir)

    for p in (info_path, out_prompt, draft_prompt):
        if not p.exists():
            raise FileNotFoundError(f"見つかりません: {p}")

    # 1) CSV 一括モード
    if args.keywords_csv:
        csv_path = pathlib.Path(args.keywords_csv)
        if not csv_path.exists():
            raise FileNotFoundError(f"keywords_csv が見つかりません: {csv_path}")
        ready_values = [x.strip().upper() for x in args.csv_ready_values.split(",")]
        optional_cols = {
            "affiliate_url": args.csv_affiliate_col,
            "search_intent": args.csv_intent_col,
            "angle":         args.csv_angle_col,
            "silo":          args.csv_silo_col,
            "persona":       args.csv_persona_col,
        }
        process_csv(
            csv_path=csv_path,
            base_info_path=info_path,
            persona_path=persona_path,
            title_prompt_path=title_prompt,
            outline_prompt_path=out_prompt,
            draft_prompt_path=draft_prompt,
            outdir=outdir,
            keyword_col=args.csv_keyword_col,
            status_col=args.csv_status_col,
            ready_values=ready_values,
            done_value=args.csv_done_value,
            optional_cols=optional_cols,
            limit=args.limit,
            temps=(args.t0, args.t1, args.t2),
        )
        print("[OK] CSV batch completed.")
        return

    # 2) 単発（既存互換）：info.json から primary_keyword を読んで1本生成
    info = read_json(info_path)
    _ = derive_primary_keyword(info)  # 早期検証

    persona_urls = read_lines_strip(persona_path)
    outline_tpl  = read_text(out_prompt)
    draft_tpl    = read_text(draft_prompt)

    ctx = generate_once_from_info(
        info,
        persona_urls,
        title_prompt,
        outline_tpl,
        draft_tpl,
        outdir,
        t0=args.t0, t1=args.t1, t2=args.t2,
    )

    # デバッグ用: 最低限の実行情報
    save_json(outdir / "context_root.json", {
        "paths": {
            "info": str(info_path),
            "persona_urls": str(persona_path),
            "title_prompt": str(title_prompt),
            "outline_prompt": str(out_prompt),
            "draft_prompt": str(draft_prompt),
            "outdir": str(outdir),
        },
        "ctx": ctx,
    })

    print("[OK] title_candidates.txt / selected_title.txt / outline.txt / article.md を生成しました。")

if __name__ == "__main__":
    main()
