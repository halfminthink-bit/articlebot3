#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# https://docs.google.com/spreadsheets/d/1TJHVpMMGZtQaxK9WxK93-bIUXogNBluxWDrRxN3zh0w/edit?gid=0#gid=0
"""
WordPress 自動投稿スクリプト v3
（列並び：サイトURL / WordPressユーザー名 / アプリケーションパスワード / Google DocsのURL / スラッグ / 投稿済み / 投稿日時 / WordPress記事URL）

シート列(A:H)：
A サイトURL (例: https://mizunosuisan.jp)
B WordPressユーザー名 (例: admin)
C アプリケーションパスワード (WP Application Password、空白可)
D Google DocsのURL
E スラッグ (任意)
F 投稿済み（"済"ならスキップ）
G 投稿日時（自動更新）
H WordPress記事URL（自動更新）

依存:
  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib requests
  credentials.json を同一ディレクトリへ配置（Sheets/Docs 読取用）
"""
import os
import sys
import pathlib

# プロジェクトルートをパスに追加
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import re
import base64
import argparse
from datetime import datetime
from typing import Tuple, Dict, Any, List

import requests
from xmlrpc.client import ServerProxy, Fault, ProtocolError

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ====== 設定（必要に応じて編集） ======
SHEET_TAB = os.getenv('WP_TAB', '')  # タブ名
SPREADSHEET_ID = os.getenv('WP_SHEET_ID', '1TJHVpMMGZtQaxK9WxK93-bIUXogNBluxWDrRxN3zh0w')  # あなたのスプシID

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents.readonly',
]

# 共通モジュール
from lib.auth import GoogleAuth


def apply_text_style(text: str, text_style: Dict[str, Any]) -> str:
    """Google Docs の textRun -> HTML 変換（最低限）"""
    if not text:
        return ''
    html = text
    if text_style and 'link' in text_style:
        url = text_style['link'].get('url', '')
        html = f'<a href="{url}">{html}</a>'
    if text_style and text_style.get('bold'):
        html = f'<strong>{html}</strong>'
    if text_style and text_style.get('italic'):
        html = f'<em>{html}</em>'
    if text_style and text_style.get('underline'):
        html = f'<u>{html}</u>'
    return html


def get_document_content(docs_service, doc_url: str) -> Tuple[str, str]:
    """Google Docs からタイトルと本文(HTML)を取得"""
    m = re.search(r'/document/d/([a-zA-Z0-9\-_]+)', doc_url)
    if not m:
        raise ValueError(f"無効なGoogle Docs URL: {doc_url}")
    doc_id = m.group(1)
    document = docs_service.documents().get(documentId=doc_id).execute()
    content = document.get('body', {}).get('content', [])
    html_body: List[str] = []
    title = None

    for element in content:
        if 'paragraph' in element:
            p = element['paragraph']
            named = p.get('paragraphStyle', {}).get('namedStyleType', 'NORMAL_TEXT')
            paragraph_text = ''
            for el in p.get('elements', []):
                if 'textRun' in el:
                    run = el['textRun']
                    paragraph_text += apply_text_style(run.get('content', ''), run.get('textStyle', {}))
            paragraph_text = paragraph_text.strip()
            if not paragraph_text:
                continue
            # 最初の見出しをタイトルとみなす
            if named == 'HEADING_1' and title is None:
                title = re.sub(r'<.*?>', '', paragraph_text)  # HTML除去
                continue
            tag_map = {'HEADING_1': 'h1', 'HEADING_2': 'h2', 'HEADING_3': 'h3',
                       'HEADING_4': 'h4', 'HEADING_5': 'h5', 'HEADING_6': 'h6'}
            tag = tag_map.get(named)
            if tag:
                html_body.append(f'<{tag}>{paragraph_text}</{tag}>')
            else:
                html_body.append(f'<p>{paragraph_text}</p>')

    if title is None:
        title = document.get('title', 'タイトルなし')
    return title, '\n'.join(html_body)


def normalize_app_password(pwd: str) -> str:
    """WP Application Password の空白を除去（Basic Authの安定のため）"""
    return re.sub(r'\s+', '', (pwd or '').strip())


def normalize_site_url(site: str) -> str:
    """サイトURLの正規化（scheme付与・末尾スラ削除）"""
    site = (site or '').strip()
    if not site:
        return site
    if not site.startswith(('http://', 'https://')):
        # ドメインだけの場合は https を付与
        if '.' in site and ' ' not in site:
            site = 'https://' + site
    return site.rstrip('/')


def get_posts_to_publish(sheets_service) -> List[Dict[str, str]]:
    """
    シートから投稿対象行を取得（A:H）
    A:サイトURL B:ユーザー名 C:アプリパス D:GDocsURL E:スラッグ F:投稿済み G:日時 H:WP記事URL
    """
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!A2:H"
    ).execute()
    values = result.get('values', [])
    posts: List[Dict[str, str]] = []
    for i, row in enumerate(values, start=2):
        row = (row + [''] * 8)[:8]  # 長さ調整
        site_url, username, app_password, doc_url, slug, posted, post_date, wp_url = [c.strip() for c in row]

        if posted == '済':
            continue
        posts.append({
            'row_number': i,
            'site_url': normalize_site_url(site_url),
            'username': username,
            'app_password': normalize_app_password(app_password),
            'doc_url': doc_url,
            'slug': slug,
        })
    return posts


def post_to_wordpress_rest(site_url: str, username: str, app_password: str,
                           title: str, content: str, slug: str, status='publish') -> Tuple[bool, str]:
    """WordPress REST API に投稿"""
    if not site_url:
        return False, "エラー: site_url が空です"
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    api_url = f"{site_url}/wp-json/wp/v2/posts"
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}
    payload = {'title': title, 'content': content, 'status': status}
    if slug:
        payload['slug'] = slug
    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=45)
    except requests.RequestException as e:
        return False, f"REST接続エラー: {e}"
    if r.status_code == 201:
        return True, r.json().get('link', '')
    return False, f"REST失敗: {r.status_code} - {r.text[:300]}"


def post_to_wordpress_xmlrpc(site_url: str, username: str, app_password: str,
                             title: str, content: str, slug: str, status='publish') -> Tuple[bool, str]:
    """XML-RPC フォールバック"""
    if not site_url:
        return False, "エラー: site_url が空です"
    endpoint = f"{site_url}/xmlrpc.php"
    try:
        s = ServerProxy(endpoint)
        blog_id = 0
        content_struct = {
            'post_type': 'post',
            'post_status': status,
            'post_title': title,
            'post_content': content,
        }
        if slug:
            content_struct['post_name'] = slug
        post_id = s.wp.newPost(blog_id, username, app_password, content_struct)
        post = s.wp.getPost(blog_id, username, app_password, post_id)
        link = post.get('link') or post.get('permalink') or ''
        return True, link or f"(ID:{post_id})"
    except ProtocolError as e:
        return False, f"XML-RPC ProtocolError: {e}"
    except Fault as e:
        return False, f"XML-RPC Fault: {e.faultString}"
    except Exception as e:
        return False, f"XML-RPC 接続エラー: {e}"


def update_spreadsheet(sheets_service, row_number: int, status_text: str, post_date: str, wp_url: str) -> None:
    """F(投稿済み)/G(投稿日時)/H(WP記事URL) を更新"""
    sheet = sheets_service.spreadsheets()
    values = [[status_text, post_date, wp_url]]
    body = {'values': values}
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!F{row_number}:H{row_number}",
        valueInputOption='RAW',
        body=body
    ).execute()


def main():
    parser = argparse.ArgumentParser(description='WordPress自動投稿ツール（新列順対応）')
    parser.add_argument('--draft', action='store_true', help='下書きとして保存（デフォルトは公開）')
    args = parser.parse_args()

    post_status = 'draft' if args.draft else 'publish'
    status_text = '下書き' if args.draft else '済'

    print(f"WordPress自動投稿を開始します...（{'下書き' if args.draft else '公開'}モード）")

    auth = GoogleAuth()
    sheets_service = auth.build_service('sheets', 'v4')
    docs_service = auth.build_service('docs', 'v1')

    posts = get_posts_to_publish(sheets_service)
    if not posts:
        print("投稿対象の記事がありません。")
        return

    print(f"{len(posts)}件の記事を投稿します。\n")
    success_count = 0
    failed_count = 0

    for post in posts:
        try:
            print(f"処理中: {post['site_url']}  行: {post['row_number']}")
            doc_title, content = get_document_content(docs_service, post['doc_url'])
            final_title = doc_title  # タイトル列が無いので Docs から取得
            print(f"  タイトル: {final_title}")
            print(f"  スラッグ: {post['slug']}")

            ok, result = post_to_wordpress_rest(
                post['site_url'], post['username'], post['app_password'],
                final_title, content, post['slug'], status=post_status
            )

            if not ok and ('rest_not_logged_in' in result or '401' in result or 'Authorization' in result):
                print("  ↪ RESTが拒否。XML-RPC で再試行します…")
                ok, result = post_to_wordpress_xmlrpc(
                    post['site_url'], post['username'], post['app_password'],
                    final_title, content, post['slug'], status=post_status
                )

            if ok:
                print(f"  ✓ 投稿成功: {result}\n")
                update_spreadsheet(
                    sheets_service,
                    post['row_number'],
                    status_text,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    result
                )
                success_count += 1
            else:
                print(f"  ✗ 投稿失敗: {result}\n")
                update_spreadsheet(
                    sheets_service,
                    post['row_number'],
                    '失敗',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    result
                )
                failed_count += 1

        except Exception as e:
            print(f"  ✗ エラー: {str(e)}\n")
            update_spreadsheet(
                sheets_service,
                post['row_number'],
                '失敗',
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                str(e)
            )
            failed_count += 1

    print("=" * 50)
    print("処理完了")
    print(f"成功: {success_count}件 / 失敗: {failed_count}件")
    print("=" * 50)


if __name__ == '__main__':
    main()
