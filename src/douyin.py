import html
import json
import mimetypes
import re
from contextlib import contextmanager
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from playwright.sync_api import Error as BrowserError, sync_playwright

from media import app_directory, identify_site, output_file, run_tool, site_url

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Mobile Safari/537.36"
)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def extract_aweme_id(url: str):
    patterns = [
        r"/(?:note|video|slides|gallery)/(\d+)",
        r"/share/(?:note|video|slides)/(\d+)",
        r"[?&]modal_id=(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def extract_balanced_json(text: str, marker: str):
    pos = text.find(marker)
    if pos < 0:
        return None

    start = text.find("{", pos + len(marker))
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = text[start:i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None

    return None


def extract_page_json(html_text: str):
    results = []

    patterns = [
        (
            r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
            False,
        ),
        (
            r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>',
            True,
        ),
    ]

    for pattern, url_encoded in patterns:
        for match in re.finditer(pattern, html_text, re.S | re.I):
            raw = html.unescape(match.group(1).strip())

            candidates = [raw]
            if url_encoded:
                candidates.insert(0, unquote(raw))

            for candidate in candidates:
                try:
                    obj = json.loads(candidate)
                except Exception:
                    continue
                results.append(obj)
                break

    for marker in (
        "window._ROUTER_DATA",
        "window._SSR_DATA",
        "window.__INIT_PROPS__",
        "_ROUTER_DATA",
        "_SSR_DATA",
    ):
        obj = extract_balanced_json(html_text, marker)
        if obj is not None:
            results.append(obj)

    return results


def iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_dicts(value)


def normalize_id(value) -> str:
    return "" if value is None else str(value)


def score_aweme_dict(d: dict, aweme_id: str) -> int:
    score = 0

    found_id = (
        d.get("aweme_id")
        or d.get("awemeId")
        or d.get("itemId")
        or d.get("id")
    )

    if found_id and normalize_id(found_id) != aweme_id:
        return 0
    if normalize_id(found_id) == aweme_id:
        score += 100

    if isinstance(d.get("images"), list):
        score += 30

    image_post_info = d.get("image_post_info") or d.get("imagePostInfo")
    if isinstance(image_post_info, dict):
        if isinstance(image_post_info.get("images"), list):
            score += 40
        if isinstance(image_post_info.get("image_list"), list):
            score += 40

    if isinstance(d.get("image_list"), list):
        score += 20

    return score


def find_aweme_dict(objects: list, aweme_id: str):
    best = None
    best_score = 0

    for obj in objects:
        for d in iter_dicts(obj):
            score = score_aweme_dict(d, aweme_id)
            if score > best_score:
                best = d
                best_score = score

    return best if best_score >= 20 else None


def get_image_entries(aweme: dict):
    image_post_info = aweme.get("image_post_info") or aweme.get("imagePostInfo")

    if isinstance(image_post_info, dict):
        for key in ("images", "image_list", "imageList"):
            images = image_post_info.get(key)
            if isinstance(images, list) and images:
                return images

    for key in (
        "images",
        "image_list",
        "imageList",
        "image_infos",
        "original_images",
    ):
        images = aweme.get(key)
        if isinstance(images, list) and images:
            return images

    return []


def only_http_urls(value):
    result = []

    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            result.append(value)

    elif isinstance(value, list):
        for item in value:
            for url in only_http_urls(item):
                if url not in result:
                    result.append(url)

    elif isinstance(value, dict):
        for item in value.values():
            for url in only_http_urls(item):
                if url not in result:
                    result.append(url)

    return result


def no_watermark_candidates(image):
    """
    图文图片候选 URL 的优先级：
    1. image["url_list"]：倒序，优先最后一个，通常是无水印高清源
    2. origin_image / origin_url 等原图字段
    3. display_image 作为最后兜底

    特意不使用 download_url_list / download_url：
    这些字段可能返回官方带水印图片。
    """
    if not isinstance(image, dict):
        if isinstance(image, str) and image.startswith("http"):
            return [image]
        return []

    result = []

    def add_urls(value, reverse=False):
        urls = only_http_urls(value)
        if reverse:
            urls = list(reversed(urls))
        for url in urls:
            if url not in result:
                result.append(url)

    # 最优先：图文自身 url_list，末尾通常是原图/CDN 源
    for key in ("url_list", "urlList"):
        if key in image:
            add_urls(image[key], reverse=True)

    # 其次：明确的原图字段
    for key in (
        "origin_image",
        "originImage",
        "origin_url",
        "originUrl",
        "original_image",
        "originalImage",
        "original_url",
        "originalUrl",
    ):
        if key in image:
            add_urls(image[key], reverse=True)

    # 部分结构会包一层 display_image，但里面也可能有 url_list
    for key in ("display_image", "displayImage", "image_url", "imageUrl"):
        value = image.get(key)
        if isinstance(value, dict):
            for nested_key in ("url_list", "urlList"):
                if nested_key in value:
                    add_urls(value[nested_key], reverse=True)

    # 最后才允许 display/image 字段中的普通 URL 兜底
    for key in ("display_image", "displayImage", "image_url", "imageUrl"):
        if key in image:
            add_urls(image[key], reverse=True)

    return result


def extract_image_candidates(aweme: dict):
    result = []

    for image in get_image_entries(aweme):
        candidates = no_watermark_candidates(image)
        if candidates:
            result.append(candidates)

    return result


def detect_extension(response: requests.Response, url: str) -> str:
    content_type = response.headers.get("Content-Type", "").split(";")[0].lower()

    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }

    if content_type in mapping:
        return mapping[content_type]

    ext = Path(urlparse(url).path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        return ".jpg" if ext == ".jpeg" else ext

    guessed = mimetypes.guess_extension(content_type) if content_type else None
    return guessed or ".jpg"


def page_data(objects, aweme_id):
    aweme = find_aweme_dict(objects, aweme_id)
    return extract_image_candidates(aweme) if aweme else []


def fetch_page_data(session, pages, aweme_id, reader, log):
    for url in pages:
        if identify_site(url) != 'douyin':
            continue
        log(f'解析抖音网页 · {urlparse(url).hostname}')
        try:
            response = session.get(url, timeout=(8, 12), headers={
                'User-Agent': MOBILE_UA if 'iesdouyin.com' in urlparse(url).hostname else DESKTOP_UA,
            })
            response.raise_for_status()
        except requests.RequestException:
            continue
        if identify_site(response.url) != 'douyin':
            continue
        candidates = reader(extract_page_json(response.text), aweme_id)
        if candidates:
            return candidates, response.url
    return [], pages[0]


def fetch_rendered_data(session, url, aweme_id, reader, log, *, video=False):
    log('尝试用浏览器渲染抖音网页。')
    cookies = []
    for cookie in session.cookies:
        domain = cookie.domain.lstrip('.')
        if not domain or identify_site('https://' + domain) != 'douyin':
            continue
        entry = {'name': cookie.name, 'value': cookie.value, 'path': cookie.path or '/',
                 'domain': cookie.domain, 'secure': cookie.secure,
                 'httpOnly': cookie.has_nonstandard_attr('HTTPOnly')}
        if cookie.expires and not cookie.is_expired():
            entry['expires'] = cookie.expires
        if not cookie.is_expired():
            cookies.append(entry)

    bundled = app_directory() / 'tools' / 'chromium' / 'chrome-headless-shell.exe'
    options = [{'executable_path': str(bundled)}] if bundled.is_file() else [{}]
    options += [{'channel': 'msedge'}, {'channel': 'chrome'}]
    with sync_playwright() as playwright:
        for option in options:
            try:
                browser = playwright.chromium.launch(**option, headless=True, timeout=10_000)
            except BrowserError:
                continue
            try:
                context = browser.new_context(locale='zh-CN')
                if cookies:
                    context.add_cookies(cookies)
                page = context.new_page()
                objects = []
                media_urls = []

                def collect(response):
                    content_type = response.headers.get('content-type', '')
                    if (video and response.ok and response.request.resource_type == 'media'
                            and is_video_url(response.url, content_type)):
                        media_urls.append(response.url)
                    if (identify_site(response.url) == 'douyin'
                            and response.request.resource_type in ('xhr', 'fetch')
                            and 'application/json' in content_type):
                        try:
                            objects.append(response.json())
                        except (BrowserError, ValueError):
                            pass

                page.on('response', collect)
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=15_000)
                    if video:
                        page.locator('video').first.evaluate(
                            '(v) => { v.muted = true; v.play().catch(() => {}); }', timeout=4000)
                    # 图文数据可能在 DOM 就绪后才由网页动态请求。
                    page.wait_for_load_state('networkidle', timeout=5_000)
                except BrowserError:
                    pass
                if identify_site(page.url) != 'douyin':
                    return [], url
                candidates = reader(extract_page_json(page.content()) + objects, aweme_id)
                if video and not candidates and extract_aweme_id(page.url) == aweme_id:
                    current = page.locator('video').evaluate_all(
                        '(els) => els.filter(v => v.videoWidth > 0).map(v => v.currentSrc)')
                    candidates = [url for url in current if is_video_url(url)] + media_urls
                for cookie in context.cookies():
                    if identify_site('https://' + cookie['domain'].lstrip('.')) == 'douyin':
                        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                                            path=cookie['path'], secure=cookie['secure'])
                return candidates, page.url
            finally:
                browser.close()
    log('无法启动浏览器。')
    return [], url


def download_image(session, urls, folder, stem, referer):
    for existing in folder.glob(stem + '.*'):
        if (existing.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.bmp', '.tiff', '.heic', '.svg'}
                and existing.is_file() and existing.stat().st_size > 0):
            return existing, False
    for url in urls:
        try:
            with session.get(url, headers={'Referer': referer, 'Accept': 'image/*'},
                             timeout=(8, 20), stream=True) as response:
                response.raise_for_status()
                if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                    continue
                target = folder / (stem + detect_extension(response, response.url))
                if target.is_file() and target.stat().st_size > 0:
                    return target, False
                with output_file(target, overwrite=target.is_file()) as temporary:
                    with temporary.open('wb') as file:
                        for chunk in response.iter_content(256 * 1024):
                            file.write(chunk)
                    if not temporary.stat().st_size:
                        raise ValueError('空图片')
                return target, True
        except (requests.RequestException, ValueError):
            continue
    raise RuntimeError('原图候选地址均无法下载。')


@contextmanager
def douyin_session(cookie):
    with requests.Session() as session:
        session.headers.update({'User-Agent': DESKTOP_UA, 'Accept-Language': 'zh-CN,zh;q=0.9',
                                'Referer': 'https://www.douyin.com/'})
        if cookie:
            jar = MozillaCookieJar(str(cookie))
            try:
                jar.load(ignore_discard=True)
            except OSError as exc:
                raise ValueError('抖音 Cookies 无法读取，请检查 Netscape .txt 格式。') from exc
            for entry in jar:
                if identify_site('https://' + entry.domain.lstrip('.')) == 'douyin':
                    session.cookies.set_cookie(entry)
        yield session


def resolve_post(session, url):
    if aweme_id := extract_aweme_id(url):
        return aweme_id, url
    with session.get(url, timeout=(8, 15), stream=True,
                     headers={'User-Agent': MOBILE_UA}) as response:
        response.raise_for_status()
        final_url = response.url
    if identify_site(final_url) != 'douyin' or not (aweme_id := extract_aweme_id(final_url)):
        raise ValueError('无法识别抖音作品 ID，请粘贴完整的作品链接。')
    return aweme_id, final_url


def download_note(raw, destination, cookie, log):
    url, _ = site_url(raw, ('douyin',))
    with douyin_session(cookie) as session:
        aweme_id, final_url = resolve_post(session, url)
        note_url = f'https://www.douyin.com/note/{aweme_id}'
        pages = tuple(dict.fromkeys((final_url, note_url,
                                    f'https://www.iesdouyin.com/share/slides/{aweme_id}/',
                                    f'https://www.iesdouyin.com/share/note/{aweme_id}/')))
        candidates, referer = fetch_page_data(session, pages, aweme_id, page_data, log)
        if not candidates:
            candidates, referer = fetch_rendered_data(session, note_url, aweme_id, page_data, log)
        if not candidates:
            raise RuntimeError('没有解析到图文原图。请确认作品是可访问的图文，并检查抖音 Cookies。')

        folder = destination / f'抖音_{aweme_id}'
        folder.mkdir(parents=True, exist_ok=True)
        saved = skipped = failed = 0
        for index, urls in enumerate(candidates, 1):
            try:
                path, created = download_image(session, urls, folder, f'{aweme_id}_{index:02d}', referer)
                saved += int(created)
                skipped += int(not created)
                log(f'{path.name} · ' + ('已保存' if created else '已存在'))
            except RuntimeError as exc:
                log(f'第 {index} 张 · {exc}')
                failed += 1
        summary = f'保存 {saved} 张，已存在 {skipped} 张。目录 {folder}'
        if failed:
            raise RuntimeError(f'{failed} 张下载失败。{summary}')
        return summary


def is_video_url(url, content_type=''):
    parsed = urlparse(url)
    host = parsed.hostname or ''
    domains = ('douyin.com', 'iesdouyin.com', 'douyinvod.com', 'douyinstatic.com',
               'bytecdn.cn', 'bytecdntp.com', 'byteimg.com', 'snssdk.com',
               'amemv.com', 'pstatp.com', 'ixigua.com', 'zjcdn.com', 'volccdn.com')
    return (parsed.scheme in ('http', 'https') and not parsed.username
            and any(host == suffix or host.endswith('.' + suffix) for suffix in domains)
            and not content_type.startswith('audio/'))


def video_data(objects, aweme_id):
    candidates = []
    for obj in objects:
        for item in iter_dicts(obj):
            item_id = item.get('aweme_id') or item.get('awemeId') or item.get('itemId')
            video = item.get('video')
            if str(item_id) != aweme_id or not isinstance(video, dict):
                continue
            for key in ('play_addr', 'playAddr', 'play_url', 'playUrl'):
                candidates.extend(url for url in only_http_urls(video.get(key)) if is_video_url(url))
    return list(dict.fromkeys(candidates))


def download_video_from_page(url, destination, cookie, ffmpeg, log):
    log('yt-dlp 未能获取抖音视频，改用网页播放器。')
    with douyin_session(cookie) as session:
        aweme_id, final_url = resolve_post(session, url)
        target = destination / f'抖音 [{aweme_id}].mp4'
        if target.is_file() and target.stat().st_size > 0:
            log(f'已存在 {target.name}')
            return
        webpage = f'https://www.douyin.com/video/{aweme_id}'
        share_page = f'https://www.iesdouyin.com/share/video/{aweme_id}/'
        pages = tuple(dict.fromkeys((final_url, share_page)))
        candidates, referer = fetch_page_data(session, pages, aweme_id, video_data, log)
        if not candidates:
            try:
                candidates, referer = fetch_rendered_data(session, webpage, aweme_id, video_data, log, video=True)
            except BrowserError as exc:
                raise RuntimeError('无法读取抖音浏览器播放数据。') from exc
    for candidate in list(dict.fromkeys(candidates))[:5]:
        try:
            with output_file(target, overwrite=target.is_file()) as temporary:
                args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                        '-rw_timeout', '12000000', '-protocol_whitelist', 'http,https,tcp,tls,crypto',
                        '-user_agent', DESKTOP_UA, '-referer', referer, '-i', candidate,
                        '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy', '-movflags', '+faststart', str(temporary)]
                if run_tool(args, log):
                    raise RuntimeError('网页媒体无法合并为 MP4。')
        except RuntimeError:
            continue
        log(f'已保存 {target.name}')
        return
    raise RuntimeError('抖音网页没有返回可用视频。请在设置中选择有效的抖音 Cookies 后重试。')
