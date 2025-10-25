# article_generator.py
# -*- coding: utf-8 -*-
"""
記事生成スクリプト（リファクタ版・temperature削除版）
旧three_call_article.pyの機能を維持しつつ、lib/配下のモジュールを使用

使い方:
  python article_generator.py --info data/info.json --out out
  python article_generator.py --keywords_csv data/keywords.csv --info data/info.json --out out
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

# 共通モジュール
from lib.config import Config
from lib.llm import LLMClient
from lib.utils import read_text, read_json, read_lines_strip, save_text, save_json

ROOT = pathlib.Path(__file__).resolve().parent


# ─────────────── プレースホルダ処理 ───────────────
_PLACEHOLDER_LINE_RE = re.compile(r'^\s*[#>\-\s]*<{3}[^>]+>{3}\s*$')

def preprocess_prompt(text: str, selected_title: str, primary_keyword: str) -> str:
    """プロンプト前処理"""
    if not text:
        return text
    text = text.replace("<<<SELECTED_TITLE>>>", selected_title)
    text = text.replace("<<<PRIMARY_KEYWORD>>>", primary_keyword)
    lines = [ln for ln in text.splitlines() if not _PLACEHOLDER_LINE_RE.match(ln)]
    return "\n".join(lines).strip()

def sanitize_generated_markdown(md: str, selected_title: str) -> str:
    """生成物のサニタイズ"""
    lines = [ln for ln in md.splitlines() if not _PLACEHOLDER_LINE_RE.match(ln)]
    
    # H1正規化
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
    
    # 重複H1削除
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

# ─────────────── info派生ヘルパ ───────────────
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
    raise ValueError("primary_keyword が info.json に存在しません")

# ─────────────── プロンプト充填 ───────────────
def fill_title_prompt(tpl: str, info: Dict[str, Any], persona_urls: List[str]) -> str:
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<TITLE_SAMPLES>>>", json.dumps(title_samples(info), ensure_ascii=False))
            .replace("<<<PRIMARY_KEYWORD>>>", derive_primary_keyword(info)))

def fill_outline_prompt(tpl: str, info: Dict[str, Any], persona_urls: List[str], 
                       selected_title: str) -> str:
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<TITLE_SAMPLES>>>", json.dumps(title_samples(info), ensure_ascii=False))
            .replace("<<<TARGET_NAME>>>", derive_target(info))
            .replace("<<<PERSONA_LABEL>>>", derive_persona_label(info))
            .replace("<<<SELECTED_TITLE>>>", selected_title))

def fill_draft_prompt(tpl: str, info: Dict[str, Any], persona_urls: List[str], 
                     outline_text: str) -> str:
    approx_len = info.get("target_length_chars", 3000)
    return (tpl
            .replace("<<<INFO_JSON>>>", json.dumps(info, ensure_ascii=False))
            .replace("<<<PERSONA_URLS>>>", json.dumps(persona_urls, ensure_ascii=False))
            .replace("<<<OUTLINE_TEXT>>>", outline_text)
            .replace("<<<TARGET_NAME>>>", derive_target(info))
            .replace("<<<PERSONA_LABEL>>>", derive_persona_label(info))
            .replace("<<<TARGET_LENGTH_CHARS>>>", str(approx_len)))

# ─────────────── 1本生成 ───────────────
def generate_once_from_info(
    info: Dict[str, Any],
    persona_urls: List[str],
    title_prompt_path: pathlib.Path,
    outline_tpl: str,
    draft_tpl: str,
    outdir: pathlib.Path,
    llm: LLMClient,
    config: Config
) -> Dict[str, Any]:
    """1記事生成（temperatureパラメータを削除）"""
    outdir.mkdir(parents=True, exist_ok=True)
    
    # ① タイトル
    print("[STEP] Title resolution start")
    sel_title = (
        (info.get("selected_title") or "").strip()
        or (info.get("title") or "").strip()
        or derive_primary_keyword(info).strip()
    )
    
    pk = derive_primary_keyword(info).strip()
    
    def _norm(s: str) -> str:
        return re.sub(r"[ \t\u3000「」『』\"'【】\[\]()（）!?！？\-—｜|：:・…]", "", s or "")
    
    needs_gen = (not sel_title) or (_norm(sel_title) == _norm(pk)) or (len(sel_title) < max(6, len(pk) + 2))
    
    # ※ プロンプトが存在しない場合は main() 側で弾いている
    if needs_gen:
        print("[STEP] Generating title...")
        tpl = read_text(title_prompt_path)
        user_title = fill_title_prompt(tpl, info, persona_urls)
        system_title = (
            f"あなたはnote記事の編集者です。<<<PRIMARY_KEYWORD>>>を自然に含めた、"
            f"検索意図に合致し読みたくなるSEOタイトルを1本だけ返してください。"
        )
        gen = llm.generate(config.model_title, system_title, user_title, max_tokens=2000)
        first_line = (gen.splitlines()[0] if gen else "").strip().strip('\'"')
        if first_line:
            sel_title = first_line
            save_text(outdir / "title_candidates.txt", gen)
            print(f"[STEP] Title: {sel_title}")
        else:
            raise RuntimeError("タイトル生成に失敗しました（モデル応答が空）")
    else:
        save_text(outdir / "title_candidates.txt", "SKIPPED\n")
        print(f"[STEP] Title from info: {sel_title}")
    
    save_text(outdir / "selected_title.txt", sel_title)
    
    # ② アウトライン
    print("[STEP] Generating outline...")
    system_outline = (
        f"あなたは{derive_persona_label(info)}として、編集構成を作る熟練の構成作家です。"
    )
    user_outline = fill_outline_prompt(outline_tpl, info, persona_urls, sel_title)
    user_outline = preprocess_prompt(user_outline, selected_title=sel_title, primary_keyword=pk)
    
    outline_text = llm.generate(config.model_outline, system_outline, user_outline, max_tokens=10000)
    save_text(outdir / "outline.txt", outline_text)
    print("[STEP] Outline saved")
    
    # ③ 本文
    print("[STEP] Generating article...")
    system_draft = (
        f"あなたは{derive_persona_label(info)}として、冷静で説得力のある本文を書く熟練ライターです。"
    )
    user_draft = fill_draft_prompt(draft_tpl, info, persona_urls, outline_text)
    user_draft = preprocess_prompt(user_draft, selected_title=sel_title, primary_keyword=pk)
    
    article_text = llm.generate(config.model_draft, system_draft, user_draft, max_tokens=16000)
    article_text = sanitize_generated_markdown(article_text, selected_title=sel_title)
    
    save_text(outdir / "article.md", article_text)
    print("[STEP] Article saved")
    
    # コンテキスト保存
    ctx = {
        "provider": config.provider,
        "models": {
            "title": config.model_title,
            "outline": config.model_outline,
            "draft": config.model_draft
        },
        "persona_label": derive_persona_label(info),
        "primary_keyword": pk,
        "selected_title": sel_title,
    }
    save_json(outdir / "context.json", ctx)
    return ctx

# ─────────────── CSV処理 ───────────────
def process_csv(
    csv_path: pathlib.Path,
    base_info_path: pathlib.Path,
    persona_path: pathlib.Path,
    title_prompt_path: pathlib.Path,
    outline_prompt_path: pathlib.Path,
    draft_prompt_path: pathlib.Path,
    outdir: pathlib.Path,
    llm: LLMClient,
    config: Config,
    keyword_col: str,
    status_col: str,
    ready_values: List[str],
    done_value: str,
    optional_cols: Dict[str, str],
    limit: int
):
    """CSV一括処理（temperatureパラメータを削除）"""
    outdir.mkdir(parents=True, exist_ok=True)
    
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    
    if keyword_col not in fieldnames:
        raise ValueError(f"CSVに '{keyword_col}' 列がありません")
    if status_col not in fieldnames:
        fieldnames.append(status_col)
    
    base_info = read_json(base_info_path)
    persona_urls = read_lines_strip(persona_path)
    outline_tpl = read_text(outline_prompt_path)
    draft_tpl = read_text(draft_prompt_path)
    
    processed = 0
    
    for idx, row in enumerate(rows):
        if limit and processed >= limit:
            break
        
        status = (row.get(status_col, "") or "").strip().upper()
        kw = (row.get(keyword_col, "") or "").strip()
        
        if not kw or (status and status not in ready_values):
            continue
        
        # info合成
        info = dict(base_info)
        info["primary_keyword"] = kw
        for info_key, csv_col in optional_cols.items():
            if csv_col and (csv_col in row) and row[csv_col].strip():
                info[info_key] = row[csv_col].strip()
        
        # 出力先
        slug = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ヶー_]+", "_", kw)[:64]
        article_out = outdir / slug
        
        try:
            generate_once_from_info(
                info, persona_urls, title_prompt_path, outline_tpl, draft_tpl,
                article_out, llm, config
            )
            rows[idx][status_col] = done_value
            processed += 1
            print(f"[OK] {kw} -> DONE (#{processed})")
        except Exception as e:
            rows[idx][status_col] = f"ERROR: {e}"
            print(f"[ERROR] {kw} -> {e}")
    
    # CSV書き戻し
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[DONE] CSV updated")

# ─────────────── Config/.env 優先のプロンプト解決 ───────────────
def _resolve_prompt_paths_with_config(config: Config) -> Dict[str, pathlib.Path]:
    """
    Config からプロンプトパスを構築する。
    - Config.get_prompt_paths() を使用（.env の PROMPT_DIR 等を前提）
    - 成功時: {"title": Path, "outline": Path, "draft": Path} を返す
    - エラー時: 例外（ここでは握りつぶさず上位で通知）
    """
    # Config.get_prompt_paths は (title, outline, draft) のタプルを返す実装
    # （lib/config.py を参照）
    title_p, outline_p, draft_p = config.get_prompt_paths()  # may raise
    return {"title": pathlib.Path(title_p), "outline": pathlib.Path(outline_p), "draft": pathlib.Path(draft_p)}

def _finalize_prompt_paths(args, config: Config) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """
    優先順位:
      1) ユーザーが CLI で明示指定（--title_prompt 等を本当に指定した場合）
      2) Config/.env 由来（必須）
    フォールバックはしない（未設定ならエラー）
    """
    # CLI 明示指定判定（値の有無）
    cli_spec_title   = bool(args.title_prompt and args.title_prompt.strip())
    cli_spec_outline = bool(args.outline_prompt and args.outline_prompt.strip())
    cli_spec_draft   = bool(args.draft_prompt and args.draft_prompt.strip())

    # 2) Config/.env から取得（ここでエラーならそのまま上げる）
    cfg_pp = _resolve_prompt_paths_with_config(config)

    title_prompt = pathlib.Path(args.title_prompt) if cli_spec_title else cfg_pp["title"]
    outline_prompt = pathlib.Path(args.outline_prompt) if cli_spec_outline else cfg_pp["outline"]
    draft_prompt = pathlib.Path(args.draft_prompt) if cli_spec_draft else cfg_pp["draft"]

    return title_prompt, outline_prompt, draft_prompt

# ─────────────── メイン ───────────────
def main():
    ap = argparse.ArgumentParser()
    # 基本引数
    ap.add_argument("--info", required=True, help="info.jsonのパス")
    ap.add_argument("--persona_urls", required=True, help="persona URLsファイル")
    # フォールバックは使用しないため、デフォルトは空文字（Configから必須取得）
    ap.add_argument("--title_prompt", default="", help="タイトル生成プロンプト（未指定ならConfig/.envを使用）")
    ap.add_argument("--outline_prompt", default="", help="アウトライン生成プロンプト（未指定ならConfig/.envを使用）")
    ap.add_argument("--draft_prompt", default="", help="本文生成プロンプト（未指定ならConfig/.envを使用）")
    ap.add_argument("--out", default="out", help="出力ディレクトリ（既定: out）")
    
    # CSV一括モード
    ap.add_argument("--keywords_csv", default="", help="CSVファイルパス（一括処理モード）")
    ap.add_argument("--csv_keyword_col", default="keyword", help="キーワード列名")
    ap.add_argument("--csv_status_col", default="status", help="ステータス列名")
    ap.add_argument("--csv_ready_values", default=",READY", help="処理対象とする値（カンマ区切り）")
    ap.add_argument("--csv_done_value", default="DONE", help="完了時に書き込む値")
    ap.add_argument("--limit", type=int, default=0, help="処理上限（0=無制限）")
    
    # 任意列マッピング
    ap.add_argument("--csv_affiliate_col", default="affiliate_url")
    ap.add_argument("--csv_intent_col", default="search_intent")
    ap.add_argument("--csv_angle_col", default="angle")
    ap.add_argument("--csv_silo_col", default="silo")
    ap.add_argument("--csv_persona_col", default="persona")
    
    args = ap.parse_args()
    
    # 設定読み込み（★ Config を先に）— .env をロードして各パスを解決
    config = Config()  # will load .env and validate provider/keys
    
    # LLMクライアント初期化
    api_key = config.claude_api_key if config.provider == "anthropic" else config.openai_api_key
    llm = LLMClient(config.provider, api_key)
    
    print(f"[BOOT] {config.provider} / {config.model_title}")
    
    info_path = pathlib.Path(args.info)
    persona_path = pathlib.Path(args.persona_urls)

    # ★ Config/.env を優先し、CLIは明示時だけ上書き（フォールバックなし）
    title_prompt, outline_prompt, draft_prompt = _finalize_prompt_paths(args, config)

    outdir = pathlib.Path(args.out)

    # 存在チェック（プロンプト3種を含めて厳密化）
    for p in (info_path, persona_path, title_prompt, outline_prompt, draft_prompt):
        if not p.exists():
            # どこ由来かは単純化して明示
            raise FileNotFoundError(f"必須ファイルが見つかりません: {p}\n"
                                    f"※ .env の PROMPT_DIR/PROMPT_TITLE/PROMPT_OUTLINE/PROMPT_DRAFT または CLI 指定を確認してください。")

    # CSV一括モード
    if args.keywords_csv:
        csv_path = pathlib.Path(args.keywords_csv)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        
        ready_values = [x.strip().upper() for x in args.csv_ready_values.split(",")]
        optional_cols = {
            "affiliate_url": args.csv_affiliate_col,
            "search_intent": args.csv_intent_col,
            "angle": args.csv_angle_col,
            "silo": args.csv_silo_col,
            "persona": args.csv_persona_col,
        }
        
        # プロンプト本文の事前読込（存在チェック済みなので FileNotFound は起きない）
        process_csv(
            csv_path, info_path, persona_path, title_prompt, outline_prompt, draft_prompt,
            outdir, llm, config, args.csv_keyword_col, args.csv_status_col,
            ready_values, args.csv_done_value, optional_cols, args.limit
        )
        print("[OK] CSV batch completed")
        return
    
    # 単発モード
    info = read_json(info_path)
    _ = derive_primary_keyword(info)
    
    persona_urls = read_lines_strip(persona_path)
    outline_tpl = read_text(outline_prompt)
    draft_tpl = read_text(draft_prompt)
    
    ctx = generate_once_from_info(
        info, persona_urls, title_prompt, outline_tpl, draft_tpl,
        outdir, llm, config
    )
    
    save_json(outdir / "context_root.json", {
        "paths": {
            "info": str(info_path),
            "persona_urls": str(persona_path),
            "title_prompt": str(title_prompt),
            "outline_prompt": str(outline_prompt),
            "draft_prompt": str(draft_prompt),
            "outdir": str(outdir),
        },
        "ctx": ctx,
    })
    
    print("[OK] 記事生成完了")

if __name__ == "__main__":
    main()