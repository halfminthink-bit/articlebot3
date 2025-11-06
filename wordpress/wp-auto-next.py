# https://docs.google.com/spreadsheets/d/1Lh9QGPn0RWXK4ddjQ-TavKdpFITl0ml1ycKdX9bdpmM/edit?gid=0#gid=0
# python wordpress/wp-auto-next.py
import os
import sys
import pathlib

# プロジェクトルートをパスに追加
project_root = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import re
import base64
import argparse
import random
from datetime import datetime, timedelta
from googleapiclient.discovery import build
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from xmlrpc.client import ServerProxy, Fault, ProtocolError

# ====== 設定 ======
SHEET_TAB = 'fra'  # ここにタブ名

# 認証情報の設定
SPREADSHEET_ID = '1RaysuPyx13mGygHjr2hpVhQCJw2cD6xvadvV9ALxxEU'

# 共通モジュール
from lib.auth import GoogleAuth

# テキストランのスタイルを適用してHTMLに変換
def apply_text_style(text, text_style):
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

# Google Docsから記事内容を取得してHTML化
def get_document_content(docs_service, doc_url):
    m = re.search(r'/document/d/([a-zA-Z0-9-_]+)', doc_url)
    if not m:
        raise ValueError(f"無効なGoogle Docs URL: {doc_url}")
    doc_id = m.group(1)
    document = docs_service.documents().get(documentId=doc_id).execute()
    content = document.get('body', {}).get('content', [])
    html_body, title = [], None
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
            if named == 'HEADING_1' and title is None:
                title = paragraph_text
                continue
            tag = {'HEADING_1':'h1','HEADING_2':'h2','HEADING_3':'h3','HEADING_4':'h4','HEADING_5':'h5','HEADING_6':'h6'}.get(named)
            if tag:
                html_body.append(f'<{tag}>{paragraph_text}</{tag}>')
            else:
                html_body.append(f'<p>{paragraph_text}</p>')
    if title is None:
        title = document.get('title', 'タイトルなし')
    return title, '\n'.join(html_body)

# スプレッドシートから投稿情報を取得（列順 A:I）
# A: サイトURL
# B: タイトル
# C: Google DocsのURL
# D: WordPressユーザー名
# E: アプリケーションパスワード
# F: スラッグ
# G: 投稿済み
# H: 投稿日時
# I: WordPress記事URL
def get_posts_to_publish(sheets_service):
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!A2:I"
    ).execute()
    values = result.get('values', [])
    posts = []
    for i, row in enumerate(values, start=2):
        while len(row) < 9:
            row.append('')
        site_url, title, doc_url, username, app_password, slug, posted, post_date, wp_url = row
        if not posted or posted.lower() != '済':
            posts.append({
                'row_number': i,
                'site_url': (site_url or '').strip().rstrip('/'),
                'title': (title or '').strip(),
                'doc_url': (doc_url or '').strip(),
                'username': (username or '').strip(),
                'app_password': (app_password or '').strip(),
                'slug': (slug or '').strip(),
            })
    return posts

# WordPress REST API（まず試す）
def post_to_wordpress_rest(site_url, username, app_password, title, content, slug, status='publish'):
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
        r = requests.post(api_url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"REST接続エラー: {e}"
    if r.status_code == 201:
        return True, r.json().get('link', '')
    return False, f"REST失敗: {r.status_code} - {r.text[:300]}"

# XML-RPC（RESTがダメな環境のフォールバック）
def post_to_wordpress_xmlrpc(site_url, username, app_password, title, content, slug, status='publish'):
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
        return False, f"XML-RPC ProtocolError: {e.errmsg}"
    except Fault as e:
        return False, f"XML-RPC Fault: {e.faultString}"
    except Exception as e:
        return False, f"XML-RPC 接続エラー: {e}"

# スプレッドシートを更新
def update_spreadsheet(sheets_service, row_number, status, post_date, wp_url):
    sheet = sheets_service.spreadsheets()
    values = [[status, post_date, wp_url]]
    body = {'values': values}
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!G{row_number}:I{row_number}",
        valueInputOption='RAW',
        body=body
    ).execute()

# メイン処理
def main():
    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(description='WordPress自動投稿ツール')
    parser.add_argument('--draft', action='store_true', 
                        help='下書きとして保存（デフォルトは公開）')
    args = parser.parse_args()
    
    # 投稿ステータスを決定
    post_status = 'draft' if args.draft else 'publish'
    status_text = '下書き保存' if args.draft else '公開'
    
    print(f"WordPress自動投稿を開始します...（{status_text}モード）")
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
            print(f"処理中: {post['site_url']}")
            doc_title, content = get_document_content(docs_service, post['doc_url'])
            final_title = post['title'] if post['title'] else doc_title
            print(f"  タイトル: {final_title}")
            print(f"  スラッグ: {post['slug']}")

            # まず REST でトライ
            ok, result = post_to_wordpress_rest(
                post['site_url'], post['username'], post['app_password'],
                final_title, content, post['slug'], status=post_status
            )

            # RESTが失敗したら XML-RPC に自動フォールバック
            # 404, 401, 認証エラーなど、REST APIが使えない場合
            if not ok and ('404' in result or 'rest_not_logged_in' in result or '401' in result or 'Authorization' in result):
                print(f"  ↪ REST失敗（{result[:100]}）。XML-RPC で再試行します…")
                ok, result = post_to_wordpress_xmlrpc(
                    post['site_url'], post['username'], post['app_password'],
                    final_title, content, post['slug'], status=post_status
                )

            if ok:
                print(f"  ✓ 投稿成功: {result}\n")
                update_spreadsheet(
                    sheets_service,
                    post['row_number'],
                    '済',
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
    print(f"成功: {success_count}件")
    print(f"失敗: {failed_count}件")
    print("=" * 50)

if __name__ == '__main__':
    main()