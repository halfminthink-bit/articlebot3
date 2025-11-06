# 半分
# https://docs.google.com/spreadsheets/d/1Lh9QGPn0RWXK4ddjQ-TavKdpFITl0ml1ycKdX9bdpmM/edit?gid=0#gid=0
# やめませんか
# https://docs.google.com/spreadsheets/d/1XEOsAIiKNBe5IwqGmvV87ui8tVrvyA6TF8wVPkW_zNA/edit?gid=0#gid=0

# python wordpress/wp-auto_half.py
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
from googleapiclient.discovery import build
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from xmlrpc.client import ServerProxy, Fault, ProtocolError


# ====== 設定 ======
SHEET_TAB = 'kasegenai'  # ここにタブ名

# 認証情報の設定
SPREADSHEET_ID = '1XEOsAIiKNBe5IwqGmvV87ui8tVrvyA6TF8wVPkW_zNA'

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

# URLを正規化（https://を追加）
def normalize_url(url):
    """URLにスキームが無ければhttps://を追加"""
    if not url:
        return ''
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

# スプレッドシートから投稿情報を取得（列順 A:J）
# A: サイトURL
# B: タイトル
# C: Google DocsのURL
# D: WordPressユーザー名
# E: アプリケーションパスワード
# F: スラッグ
# G: カテゴリ（スラッグまたは名前、カンマ区切りで複数指定可）
# H: 投稿済み
# I: 投稿日時
# J: WordPress記事URL
def get_posts_to_publish(sheets_service):
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!A2:J"
    ).execute()
    values = result.get('values', [])
    posts = []
    for i, row in enumerate(values, start=2):
        while len(row) < 10:
            row.append('')
        site_url, title, doc_url, username, app_password, slug, categories, posted, post_date, wp_url = row
        if not posted or posted.lower() != '済':
            posts.append({
                'row_number': i,
                'site_url': normalize_url(site_url),  # ★ ここで正規化
                'title': (title or '').strip(),
                'doc_url': (doc_url or '').strip(),
                'username': (username or '').strip(),
                'app_password': (app_password or '').strip(),
                'slug': (slug or '').strip(),
                'categories': (categories or '').strip(),
            })
    return posts

# カテゴリIDを取得または作成（REST API用）
def get_or_create_category_ids_rest(site_url, username, app_password, category_names):
    """
    カテゴリ名のリストからカテゴリIDのリストを取得
    存在しない場合は新規作成
    """
    if not category_names:
        return []
    
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}
    
    category_ids = []
    
    for cat_name in category_names:
        cat_name = cat_name.strip()
        if not cat_name:
            continue
        
        # 既存カテゴリを検索
        api_url = f"{site_url}/wp-json/wp/v2/categories?search={cat_name}&per_page=100"
        try:
            r = requests.get(api_url, headers=headers, timeout=30)
            if r.status_code == 200:
                categories = r.json()
                # 完全一致を探す
                found = None
                for cat in categories:
                    if cat.get('name', '').lower() == cat_name.lower() or cat.get('slug', '').lower() == cat_name.lower():
                        found = cat
                        break
                
                if found:
                    category_ids.append(found['id'])
                    print(f"    カテゴリ '{cat_name}' 見つかりました (ID: {found['id']})")
                    continue
            
            # 見つからなければ新規作成
            create_url = f"{site_url}/wp-json/wp/v2/categories"
            payload = {'name': cat_name}
            r = requests.post(create_url, json=payload, headers=headers, timeout=30)
            if r.status_code == 201:
                new_cat = r.json()
                category_ids.append(new_cat['id'])
                print(f"    カテゴリ '{cat_name}' を作成しました (ID: {new_cat['id']})")
            else:
                print(f"    カテゴリ '{cat_name}' の作成に失敗: {r.status_code}")
        
        except Exception as e:
            print(f"    カテゴリ '{cat_name}' の処理でエラー: {e}")
    
    return category_ids

# WordPress REST API（まず試す）
def post_to_wordpress_rest(site_url, username, app_password, title, content, slug, categories_str, status='publish'):
    if not site_url:
        return False, "エラー: site_url が空です"
    
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {token}', 'Content-Type': 'application/json'}
    
    # カテゴリ処理
    category_ids = []
    if categories_str:
        category_names = [c.strip() for c in categories_str.split(',') if c.strip()]
        if category_names:
            print(f"  カテゴリ処理中: {', '.join(category_names)}")
            category_ids = get_or_create_category_ids_rest(site_url, username, app_password, category_names)
    
    api_url = f"{site_url}/wp-json/wp/v2/posts"
    payload = {'title': title, 'content': content, 'status': status}
    if slug:
        payload['slug'] = slug
    if category_ids:
        payload['categories'] = category_ids
    
    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        return False, f"REST接続エラー: {e}"
    if r.status_code == 201:
        return True, r.json().get('link', '')
    return False, f"REST失敗: {r.status_code} - {r.text[:300]}"

# XML-RPC（RESTがダメな環境のフォールバック）
def post_to_wordpress_xmlrpc(site_url, username, app_password, title, content, slug, categories_str, status='publish'):
    if not site_url:
        return False, "エラー: site_url が空です"
    endpoint = f"{site_url}/xmlrpc.php"
    try:
        s = ServerProxy(endpoint)
        blog_id = 0
        
        # カテゴリ処理（XML-RPCではカテゴリ名を直接指定可能）
        terms_names = {}
        if categories_str:
            category_names = [c.strip() for c in categories_str.split(',') if c.strip()]
            if category_names:
                print(f"  カテゴリ設定: {', '.join(category_names)}")
                terms_names['category'] = category_names
        
        content_struct = {
            'post_type': 'post',
            'post_status': status,
            'post_title': title,
            'post_content': content,
        }
        if slug:
            content_struct['post_name'] = slug
        if terms_names:
            content_struct['terms_names'] = terms_names
        
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

# スプレッドシートを更新
def update_spreadsheet(sheets_service, row_number, status, post_date, wp_url):
    sheet = sheets_service.spreadsheets()
    values = [[status, post_date, wp_url]]
    body = {'values': values}
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!H{row_number}:J{row_number}",
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
            if post['categories']:
                print(f"  カテゴリ: {post['categories']}")

            # まず REST でトライ
            ok, result = post_to_wordpress_rest(
                post['site_url'], post['username'], post['app_password'],
                final_title, content, post['slug'], post['categories'], 
                status=post_status
            )

            # RESTが失敗したら XML-RPC に自動フォールバック
            if not ok and ('rest_not_logged_in' in result or '401' in result or 'Authorization' in result):
                print("  ↪ RESTが拒否（ヘッダ未通過の可能性）。XML-RPC で再試行します…")
                ok, result = post_to_wordpress_xmlrpc(
                    post['site_url'], post['username'], post['app_password'],
                    final_title, content, post['slug'], post['categories'],
                    status=post_status
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

        except KeyboardInterrupt:
            print("\n\n処理を中断しました。")
            print("=" * 50)
            print("中断時点の結果")
            print(f"成功: {success_count}件")
            print(f"失敗: {failed_count}件")
            print("=" * 50)
            sys.exit(0)
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