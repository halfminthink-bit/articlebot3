# -*- coding: utf-8 -*-
"""
既存 out_batch/*/article.md をまとめて:
  1) Googleドキュメント化（Driveに作成）
  2) 共有権限を「リンクを知っている全員＝編集者」に付与（任意）
  3) アフィリエイト文言とURLを挿入（タイトル直下/中盤/末尾）
  4) スプレッドシートへ [persona, title, url] を追記

依存: 同ディレクトリに publish_gdoc_html.py（認証・APIヘルパー群）
認証: credentials.json（Drive/Docs/Sheets有効化）＋ token.json（自動生成/再利用）

OFFICIAL_URL は .env か環境変数、または --official-url で指定（--official-url が最優先）
"""

import argparse
import pathlib
import sys
from typing import Tuple, Optional

import os
from dotenv import load_dotenv  # ← 追加

# 既存ユーティリティを再利用（認証＆API操作は publish_gdoc_html 側に実装済み）
from publish_gdoc_html import (  # noqa: F401
    get_creds,
    md_to_html,
    drive_create_gdoc_from_html,
    sheets_client,
    sheets_get_or_create_sheet_id,  # 未使用でも import だけ維持
    # 追加: 共有とCTA系
    drive_share_anyone_writer,
    docs_insert_disclosure_below_title,
    docs_insert_midpage_cta,
    docs_append_anchor_link,
)

def read_md(md_path: pathlib.Path) -> str:
    if not md_path.is_file():
        raise FileNotFoundError(f"md not found: {md_path}")
    return md_path.read_text(encoding="utf-8").strip()

def extract_title_from_md(md_text: str, fallback: str) -> str:
    # 先頭H1をタイトルとして採用。無ければフォルダ名
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback

def guess_persona_from_dir(dir_path: pathlib.Path) -> str:
    """
    末尾ディレクトリ名: 例) 20251005_141544_ren -> 'ren'
    '_' 区切りの最後を persona として推測。
    """
    name = dir_path.name
    if "_" in name:
        parts = name.split("_")
        if parts[-1]:
            return parts[-1]
    return "unknown"

def sheets_append_row(creds, spreadsheet_id: str, sheet_name: str,
                      persona: str, title: str, url: str):
    """
    A: persona, B: title, C: url で1行追記
    """
    svc = sheets_client(creds)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[persona, title, url]]}
    ).execute()

def post_affiliate_blocks(creds,
                          file_id: str,
                          ad_disclosure: str,
                          mid_cta_text: str,
                          last_cta_text: str,
                          official_url: str):
    """
    既存の publish_gdoc_html の挿入ユーティリティを使って
    1) タイトル直下に注意喚起（太字/11pt/リンクなし）
    2) 中盤CTA（太字/11pt/リンクあり）
    3) 末尾CTA（太字/リンクあり）
    を挿入する。official_url が空なら 2/3 はスキップ。
    """
    try:
        if (ad_disclosure or "").strip():
            # タイトル直下に注意喚起
            docs_insert_disclosure_below_title(creds, file_id, ad_disclosure.strip())
    except Exception as e:
        print(f"[warn] disclosure insert skipped: {e}", file=sys.stderr)

    try:
        if official_url:
            # 中盤CTA（H2手前を狙う実装。publish_gdoc_html 内部で配置ロジック）
            docs_insert_midpage_cta(
                creds, file_id,
                anchor_text=mid_cta_text,
                url=official_url,
                bold=True,
                font_size_pt=11
            )
        else:
            print("[info] OFFICIAL_URL empty; skip mid CTA", file=sys.stderr)
    except Exception as e:
        print(f"[warn] mid CTA insert skipped: {e}", file=sys.stderr)

    try:
        if official_url:
            # 末尾CTA（最後の一致にリンク/太字適用）
            docs_append_anchor_link(
                creds, file_id,
                anchor_text=last_cta_text,
                url=official_url,
                bold=True
            )
        else:
            print("[info] OFFICIAL_URL empty; skip last CTA", file=sys.stderr)
    except Exception as e:
        print(f"[warn] last CTA insert skipped: {e}", file=sys.stderr)

def process_one(creds,
                dir_path: pathlib.Path,
                folder_id: Optional[str],
                share_anyone_writer: bool,
                ad_disclosure: str,
                mid_cta_text: str,
                last_cta_text: str,
                official_url: str,   # ← 追加（.env 読みは main 側で済ませる）
                spreadsheet_id: str,
                sheet_name: str) -> Tuple[str, str, str]:
    """
    1ディレクトリを処理。戻り値: (persona, title, gdoc_url)
    流れ:
      - article.md 読み込み→HTML化→GDoc作成
      - 共有: anyone=writer を付与（任意）
      - アフィ文言/URLの挿入（official_url が空ならCTAは省略）
      - スプレッドシート追記
    """
    md_path = dir_path / "article.md"
    md_text = read_md(md_path)
    html_text = md_to_html(md_text)

    persona = guess_persona_from_dir(dir_path)
    title = extract_title_from_md(md_text, fallback=dir_path.name)

    # GDoc 作成
    file_id, link = drive_create_gdoc_from_html(creds, html_text, title, folder_id or None)

    # 共有（リンク所持者＝編集者）
    if share_anyone_writer:
        try:
            drive_share_anyone_writer(creds, file_id)
        except Exception as e:
            print(f"[warn] share(anyone=writer) failed: {e}", file=sys.stderr)

    # アフィ文言＋URL（main から渡された official_url を使う）
    post_affiliate_blocks(
        creds,
        file_id=file_id,
        ad_disclosure=ad_disclosure,
        mid_cta_text=mid_cta_text,
        last_cta_text=last_cta_text,
        official_url=official_url
    )

    # スプシ追記
    sheets_append_row(creds, spreadsheet_id, sheet_name, persona, title, link)

    return persona, title, link

def main():
    # .env を先に読み込む（OFFICIAL_URL 等）
    load_dotenv()  # ← 追加

    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", required=True, help="書き込み先スプレッドシートID")
    ap.add_argument("--sheet-name", default="Articles", help="シート名（既定: Articles）")
    ap.add_argument("--folder-id", default="", help="GDoc作成先のDriveフォルダID（任意）")
    ap.add_argument("--force-login", type=int, default=0, help="1=強制再認可（token.jsonを無視）")

    # 追加オプション: 権限付与 & CTA文言 & 公式URL
    ap.add_argument("--share-anyone-writer", type=int, default=1, help="1=リンク所持者を編集者に付与（既定: 1）")
    ap.add_argument("--ad-disclosure", default="本記事にはアフィリエイトリンクを含みます。")
    ap.add_argument("--mid-cta-text", default="公式サイト")
    ap.add_argument("--last-cta-text", default="→公式サイトはこちらから")
    ap.add_argument("--official-url", default="", help="OFFICIAL_URL をここで直接指定（.envより優先）")  # ← 追加

    ap.add_argument("dirs", nargs="+", help=r"処理対象ディレクトリ群（例: C:\path\out_batch\20251005_141544_ren ...）")
    args = ap.parse_args()

    # 認証（publish_gdoc_html のスコープを利用。必要なら同ファイルの SCOPES をフルDriveに設定）
    creds = get_creds(force_login=bool(args.force_login))

    # OFFICIAL_URL 決定：--official-url が最優先 → 環境変数/ .env
    official_url_cli = (args.official_url or "").strip()
    official_url_env = (os.getenv("OFFICIAL_URL", "") or "").strip()
    official_url = official_url_cli or official_url_env
    if not official_url:
        print("[info] OFFICIAL_URL empty; mid/last CTA will be skipped", file=sys.stderr)

    ok = 0
    for d in args.dirs:
        dir_path = pathlib.Path(d)
        try:
            persona, title, url = process_one(
                creds=creds,
                dir_path=dir_path,
                folder_id=(args.folder_id or None),
                share_anyone_writer=bool(args.share_anyone_writer),
                ad_disclosure=args.ad_disclosure,
                mid_cta_text=args.mid_cta_text,
                last_cta_text=args.last_cta_text,
                official_url=official_url,  # ← 追加
                spreadsheet_id=args.sheet_id,
                sheet_name=args.sheet_name
            )
            print(f"[ok] {dir_path.name}  ->  persona='{persona}'  title='{title}'")
            print(f"     url: {url}")
            ok += 1
        except Exception as e:
            print(f"[err] {dir_path}: {e}", file=sys.stderr)

    print(f"[DONE] {ok} 件 追記完了")

if __name__ == "__main__":
    main()
