"""selectors.py"""

class NoteSelectors:
    """noteのUI要素セレクタ"""
    
    # ログイン関連
    LOGIN_LINKS = [
        '.o-navbarPrimaryGuest__navItem.login a',
        'a.a-button[href^="/login"]',
        'a[href^="/login"]',
        '//a[contains(.,"ログイン")]',
    ]
    
    EMAIL_INPUT = "input#email"
    PASSWORD_INPUT = "input#password"
    LOGIN_BUTTONS = ".o-login__button button:enabled, button[type='submit']:enabled"
    
    # ログイン確認
    AVATAR_SELECTORS = [
        'img[alt="ユーザーアイコン"]',
        'a[href^="/users/"] img',
        'button[aria-haspopup="menu"] img',
        'a[href^="/settings"]',
        'a[href^="/@"] img',
    ]
    
    # ポップアップ
    POPUP_CLOSE = [
        "button#onetrust-accept-btn-handler",
        "button[data-testid='cookie-policy-agree-button']",
        "button[aria-label='閉じる']",
        "button[aria-label='Close']",
        "//button[contains(., '同意')]",
        "//button[contains(., 'OK')]",
        "//button[contains(., '後で')]",
    ]
    
    # 新規投稿
    NEW_POST_BUTTONS = [
        'a.a-split-button__left.svelte-4d611i[href="/notes/new"]',
        'a.a-split-button__left[href="/notes/new"]',
        'a[href="/notes/new"]',
        'a.a-split-button__left[href^="/notes/new"]',
    ]
    
    # タイトル入力
    TITLE_INPUT_PRIORITY = [
        'textarea[placeholder="記事タイトル"][spellcheck="true"]',
        'textarea.sc-80832eb4-0.heevId',
    ]
    
    TITLE_INPUT_FALLBACKS = [
        'textarea[placeholder="記事タイトル"]',
        'textarea[spellcheck="true"]',
        'textarea.sc-80832eb4-0',
        '//textarea[@placeholder="記事タイトル"]',
    ]
    
    # エディタ
    EDITOR_SELECTORS = [
        'div.ProseMirror.note-common-styles__textnote-body[contenteditable="true"]',
        'div.ProseMirror[contenteditable="true"]',
        'div[role="textbox"][contenteditable="true"]',
        '.ProseMirror'
    ]
    
    # アイキャッチ画像
    IMAGE_ADD_BUTTON = [
        'button[aria-label="画像を追加"]',
        '//button[@aria-label="画像を追加"]'
    ]
    
    IMAGE_UPLOAD_BUTTON = [
        '//button[.//div[normalize-space()="画像をアップロード"]]',
        'button.sc-920a17ca-7.cZcUfD'
    ]
    
    FILE_INPUT = [
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    ]
    
    UPLOADED_IMAGE = [
        'img[src*="noteusercontent"]',
        'img[src^="blob:"]',
        'img[alt*="アイキャッチ"]'
    ]
    
    # 目次
    MENU_BUTTON = [
        'button#menu-button[aria-label="メニューを開く"]',
        'button#menu-button',
        '//button[@id="menu-button"]',
        '//button[contains(@aria-label,"メニュー")]',
    ]
    
    TOC_BUTTON = [
        'button#toc-setting',
        '//button[@id="toc-setting"]',
        '//button[.//div[normalize-space()="目次"] or normalize-space()="目次"]',
    ]
    
    # 公開
    PUBLISH_STEP1 = [
        "//button[.//span[contains(normalize-space(.), '公開に進む')]]",
        "//span[contains(normalize-space(.), '公開に進む')]/ancestor::button[1]",
    ]
    
    PUBLISH_STEP2 = [
        "//button[.//span[contains(normalize-space(.), '投稿する')]]",
        "//span[contains(normalize-space(.), '投稿する')]/ancestor::button[1]",
    ]
