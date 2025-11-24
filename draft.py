# python wordpress/wp-auto-draft.py

"""
# 下書き変更対象を確認（確認プロンプトあり）
python wordpress/wp-auto-draft.py

# 確認なしで即変更
python wordpress/wp-auto-draft.py --confirm
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
import requests
from xmlrpc.client import ServerProxy, Fault, ProtocolError

# ====== 設定 ======
SHEET_TAB = 'fomula'  # タブ名
TARGET_SLUG = 'fomula'  # 対象スラッグ

# 認証情報の設定
SPREADSHEET_ID = '1TJHVpMMGZtQaxK9WxK93-bIUXogNBluxWDrRxN3zh0w'

# 共通モジュール
from lib.auth import GoogleAuth

# スプレッドシートから対象記事を取得（列順 A:H）
# A: サイトURL
# B: WordPressユーザー名
# C: アプリケーションパスワード
# D: Google DocsのURL
# E: スラッグ
# F: 投稿済み
# G: 投稿日時
# H: WordPress記事URL
def get_posts_to_draft(sheets_service):
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!A2:H"
    ).execute()
    values = result.get('values', [])
    posts = []
    for i, row in enumerate(values, start=2):
        while len(row) < 8:
            row.append('')
        site_url, username, app_password, doc_url, slug, posted, post_date, wp_url = row
        # スラッグが TARGET_SLUG と一致し、投稿済み（F列が「済」）かつ、WordPress記事URL（H列）がある記事のみ
        if slug.strip() == TARGET_SLUG and posted and posted.lower() == '済' and wp_url and wp_url.strip():
            posts.append({
                'row_number': i,
                'site_url': (site_url or '').strip().rstrip('/'),
                'username': (username or '').strip(),
                'app_password': (app_password or '').strip(),
                'slug': (slug or '').strip(),
                'wp_url': (wp_url or '').strip(),
            })
    return posts

# WordPress記事URLから投稿IDを抽出
def extract_post_id_from_url(wp_url, site_url):
    """
    WordPress記事URLから投稿IDを抽出する
    - パーマリンク形式: https://example.com/post-slug/ → REST APIで取得
    - ?p=123 形式: https://example.com/?p=123 → 123
    """
    # ?p=123 形式
    m = re.search(r'[?&]p=(\d+)', wp_url)
    if m:
        return m.group(1)
    
    # パーマリンク形式の場合はNoneを返す（REST APIで検索が必要）
    return None

# REST APIで投稿IDを検索（スラッグから）
def search_post_id_by_url(site_url, username, app_password, wp_url):
    """
    WordPress記事URLから投稿IDを検索する
    """
    # URLからスラッグを抽出
    slug = wp_url.rstrip('/').split('/')[-1]
    
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    api_url = f"{site_url}/wp-json/wp/v2/posts"
    headers = {'Authorization': f'Basic {token}'}
    params = {'slug': slug, 'per_page': 1}
    
    try:
        r = requests.get(api_url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            posts = r.json()
            if posts and len(posts) > 0:
                return str(posts[0]['id'])
    except:
        pass
    
    return None

# WordPress REST APIで下書きに変更
def draft_post_rest(site_url, username, app_password, post_id):
    if not site_url:
        return False, "エラー: site_url が空です"
    
    credentials = f"{username}:{app_password}"
    token = base64.b64encode(credentials.encode()).decode('utf-8')
    api_url = f"{site_url}/wp-json/wp/v2/posts/{post_id}"
    headers = {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }
    
    try:
        # statusをdraftに変更
        data = {'status': 'draft'}
        r = requests.post(api_url, headers=headers, json=data, timeout=30)
    except requests.RequestException as e:
        return False, f"REST接続エラー: {e}"
    
    if r.status_code == 200:
        return True, "下書き変更成功"
    return False, f"REST失敗: {r.status_code} - {r.text[:300]}"

# XML-RPCで下書きに変更
def draft_post_xmlrpc(site_url, username, app_password, post_id):
    if not site_url:
        return False, "エラー: site_url が空です"
    
    endpoint = f"{site_url}/xmlrpc.php"
    try:
        s = ServerProxy(endpoint)
        blog_id = 0
        content = {'post_status': 'draft'}
        result = s.wp.editPost(blog_id, username, app_password, post_id, content)
        if result:
            return True, "下書き変更成功"
        else:
            return False, "下書き変更失敗（XML-RPC）"
    except ProtocolError as e:
        return False, f"XML-RPC ProtocolError: {e.errmsg}"
    except Fault as e:
        return False, f"XML-RPC Fault: {e.faultString}"
    except Exception as e:
        return False, f"XML-RPC 接続エラー: {e}"

# スプレッドシートを更新（下書き変更後、F列を「下書き」に、G列に変更日時）
def update_spreadsheet_after_draft(sheets_service, row_number):
    sheet = sheets_service.spreadsheets()
    draft_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    values = [['下書き', f'下書きに変更 {draft_time}']]
    body = {'values': values}
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!F{row_number}:G{row_number}",
        valueInputOption='RAW',
        body=body
    ).execute()

# メイン処理
def main():
    parser = argparse.ArgumentParser(description='WordPress記事下書き変更ツール')
    parser.add_argument('--confirm', action='store_true',
                        help='確認なしで下書き変更を実行')
    args = parser.parse_args()
    
    print(f"WordPress記事下書き変更ツールを開始します（対象スラッグ: {TARGET_SLUG}）...")
    auth = GoogleAuth()
    sheets_service = auth.build_service('sheets', 'v4')

    posts = get_posts_to_draft(sheets_service)
    if not posts:
        print(f"スラッグが '{TARGET_SLUG}' の下書き変更対象記事がありません。")
        return

    print(f"\n下書き変更対象: {len(posts)}件\n")
    for i, post in enumerate(posts, 1):
        print(f"{i}. スラッグ: {post['slug']}")
        print(f"   URL: {post['wp_url']}")
    
    if not args.confirm:
        print("\n本当に下書きに変更しますか？")
        response = input("変更する場合は 'yes' と入力してください: ")
        if response.lower() != 'yes':
            print("下書き変更をキャンセルしました。")
            return
    
    print(f"\n{len(posts)}件の記事を下書きに変更します...\n")
    success_count = 0
    failed_count = 0

    for post in posts:
        try:
            print(f"処理中: スラッグ '{post['slug']}'")
            print(f"  URL: {post['wp_url']}")
            
            # 投稿IDを取得
            post_id = extract_post_id_from_url(post['wp_url'], post['site_url'])
            
            if not post_id:
                # URLから直接IDが取れない場合、REST APIで検索
                print(f"  投稿IDを検索中...")
                post_id = search_post_id_by_url(
                    post['site_url'], 
                    post['username'], 
                    post['app_password'], 
                    post['wp_url']
                )
            
            if not post_id:
                print(f"  ✗ 投稿IDが見つかりません\n")
                failed_count += 1
                continue
            
            print(f"  投稿ID: {post_id}")
            
            # まずREST APIで下書き変更を試みる
            ok, result = draft_post_rest(
                post['site_url'],
                post['username'],
                post['app_password'],
                post_id
            )
            
            # RESTが失敗したらXML-RPCで再試行
            if not ok and ('404' in result or '403' in result or 'Forbidden' in result or 'rest_not_logged_in' in result or '401' in result or 'Authorization' in result):
                print(f"  ↪ REST失敗。XML-RPC で再試行...")
                ok, result = draft_post_xmlrpc(
                    post['site_url'],
                    post['username'],
                    post['app_password'],
                    post_id
                )
            
            if ok:
                print(f"  ✓ 下書き変更成功\n")
                update_spreadsheet_after_draft(sheets_service, post['row_number'])
                success_count += 1
            else:
                print(f"  ✗ 下書き変更失敗: {result}\n")
                failed_count += 1

        except Exception as e:
            print(f"  ✗ エラー: {str(e)}\n")
            failed_count += 1

    print("=" * 50)
    print("処理完了")
    print(f"下書き変更成功: {success_count}件")
    print(f"下書き変更失敗: {failed_count}件")
    print("=" * 50)

if __name__ == '__main__':
    main()