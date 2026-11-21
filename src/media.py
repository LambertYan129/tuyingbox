from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps


SITES = {
    'youtube': ('YouTube', ('youtube.com', 'youtu.be', 'youtube-nocookie.com')),
    'twitter': ('X / Twitter', ('x.com', 'twitter.com')),
    'bilibili': ('哔哩哔哩', ('bilibili.com', 'b23.tv', 'bili2233.cn')),
    'douyin': ('抖音', ('douyin.com', 'iesdouyin.com')),
    'instagram': ('Instagram', ('instagram.com',)),
}
VIDEO_SITES = ('youtube', 'twitter', 'bilibili', 'douyin')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def app_directory():
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def tool(name):
    bundled = app_directory() / 'tools' / f'{name}.exe'
    return str(bundled) if bundled.is_file() else shutil.which(name)


def require_tool(name):
    path = tool(name)
    if not path:
        raise ValueError(f'找不到 {name}.exe，请检查便携版的 tools 文件夹。')
    return path


def identify_site(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme not in ('http', 'https') or parsed.username is not None:
            return None
    except ValueError:
        return None
    for site, (_, domains) in SITES.items():
        if any(host == domain or host.endswith('.' + domain) for domain in domains):
            return site
    return None


def site_url(raw, allowed):
    value = raw.strip().strip('"\'')
    # 抖音分享文案和其他平台的完整链接使用同一个入口。
    match = re.search(r'https?://[^\s<>"\'，。；]+', value, re.IGNORECASE)
    if match:
        value = match.group().rstrip('.,;)]}）】')
    elif value and not re.search(r'\s|://', value):
        value = 'https://' + value
    site = identify_site(value)
    if site not in allowed:
        names = '、'.join(SITES[key][0] for key in allowed)
        raise ValueError(f'请输入有效的 {names} 链接。')
    return value, site


def clean_path(raw):
    value = raw.strip().strip('"\'')
    if value.startswith('file:///'):
        value = unquote(urlsplit(value).path)
        if re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]
    return Path(os.path.expandvars(value)).expanduser().resolve()


def cookie_path(raw, site):
    if not raw.strip():
        return None
    path = clean_path(raw)
    if not path.is_file():
        raise ValueError(f'{SITES[site][0]} 的 Cookies 文件不存在。请在设置中重新选择。')
    return path


@contextmanager
def private_cookie_copy(cookie):
    # yt-dlp 退出时可能写回 cookie jar，原始导出文件由用户管理。
    if cookie is None:
        yield None
        return
    with TemporaryDirectory(prefix='media-cookies-') as directory:
        target = Path(directory) / 'cookies.txt'
        shutil.copyfile(cookie, target)
        yield target


class TaskCancelled(Exception):
    pass


class ToolControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None

    def check(self):
        if self.cancelled.is_set():
            raise TaskCancelled('已停止转换。')

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.process is not None:
                self.process.kill()

    @contextmanager
    def watch(self, process):
        with self.lock:
            self.process = process
            if self.cancelled.is_set():
                process.kill()
        try:
            yield
        finally:
            with self.lock:
                self.process = None


def read_tool_progress(process, on_line, stall_timeout):
    lines = queue.SimpleQueue()

    def read():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = monotonic() + stall_timeout
    try:
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args[0], stall_timeout)
            line = lines.get(timeout=remaining)
            if line is None:
                return process.wait(timeout=max(0, deadline - monotonic()))
            if line.strip() and on_line(line.strip()):
                deadline = monotonic() + stall_timeout
    except queue.Empty as exc:
        raise subprocess.TimeoutExpired(process.args[0], stall_timeout) from exc
    finally:
        if process.poll() is None:
            process.kill()
        reader.join()


def run_tool(args, on_line, *, control=None, stall_timeout=None):
    if control is not None:
        control.check()
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    with subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding='utf-8', errors='replace', env=env, creationflags=NO_WINDOW,
    ) as process:
        with control.watch(process) if control is not None else nullcontext():
            if stall_timeout is None:
                for line in process.stdout:
                    if line.strip():
                        on_line(line.strip())
                result = process.wait()
            else:
                result = read_tool_progress(process, on_line, stall_timeout)
        if control is not None:
            control.check()
        return result


def build_video_command(url, site, destination, ffmpeg, ytdlp, deno, cookie, playlist):
    args = [
        ytdlp, '--ignore-config', '--no-js-runtimes', '--color', 'never', '--encoding', 'utf-8',
        '--paths', str(destination), '--output', '%(title).180B [%(id)s].%(ext)s',
        '--windows-filenames', '--newline', '--no-overwrites', '--continue',
        '--retries', '5', '--fragment-retries', '10', '--socket-timeout', '25',
        '--ffmpeg-location', ffmpeg, '--format', 'bestvideo*+bestaudio/best',
        '--merge-output-format', 'mp4/mkv',
        '--yes-playlist' if playlist else '--no-playlist',
    ]
    if site == 'youtube' and deno:
        # 官方 Windows yt-dlp 包内含 EJS。运行器仅在需要解 JS 挑战时启动。
        args += ['--js-runtimes', f'deno:{deno}']
    if site == 'twitter':
        args += ['--downloader', 'm3u8:native']
    if site in ('twitter', 'bilibili'):
        args += ['--concurrent-fragments', '1']
    if cookie:
        args += ['--cookies', str(cookie)]
    return args + ['--', url]


def download_video(raw, destination, cookies, playlist, douyin_fallback, log):
    ytdlp, ffmpeg = require_tool('yt-dlp'), require_tool('ffmpeg')
    successes = 0
    failures = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            url, site = site_url(line, VIDEO_SITES)
            cookie = cookie_path(cookies[site], site)
            deno = tool('deno') if site == 'youtube' else None
            if site == 'youtube':
                log('YouTube · Deno 自动启用' if deno else 'YouTube · 未找到 Deno，可用格式可能减少。')
            else:
                log(f'{SITES[site][0]} · 开始下载')
            with private_cookie_copy(cookie) as copy:
                args = build_video_command(url, site, destination, ffmpeg, ytdlp, deno, copy, playlist)
                status = run_tool(args, log)
            if status and site == 'douyin':
                douyin_fallback(url, destination, cookie, ffmpeg, log)
            elif status:
                raise RuntimeError(f'{SITES[site][0]} 下载失败，yt-dlp 退出代码 {status}。')
            successes += 1
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append(str(exc))
            log(str(exc))
    if failures:
        raise RuntimeError(f'{successes} 个链接完成，{len(failures)} 个失败。请查看日志。')
    return f'{successes} 个视频链接处理完成。'


def twitter_target(raw):
    value = raw.strip()
    if '/' in value:
        url, _ = site_url(value, ('twitter',))
        parts = list(filter(None, urlsplit(url).path.split('/')))
        if len(parts) == 3 and parts[1] == 'status' and parts[2].isdigit():
            return url, '帖子'
        if len(parts) == 1 or (len(parts) == 2 and parts[1] == 'media'):
            value = parts[0]
        else:
            raise ValueError('请输入 X 账号、账号主页或帖子链接。')
    username = value.removeprefix('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,15}', username):
        raise ValueError('请输入有效的 X 账号，或粘贴帖子链接。')
    return f'https://x.com/{username}/media', username.lower()


def start_date(raw):
    for pattern in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            pass
    raise ValueError('起始日期格式为 YYYY-MM-DD。')


def gallery_command():
    if getattr(sys, 'frozen', False):
        return [str(app_directory() / 'gallery-worker.exe'), '--gallery-worker']
    return [sys.executable, '-m', 'gallery_dl']


def download_gallery(site, raw, destination, cookie, since, limit, log):
    args = gallery_command() + ['--config-ignore', '--windows-filenames', '-o', 'cache.file=:memory:',
                               '-o', f'extractor.{site}.videos=false']
    if site == 'twitter':
        url, account = twitter_target(raw)
        if limit and (not limit.isdecimal() or int(limit) < 1):
            raise ValueError('最多图片数应为正整数。')
        maximum = int(limit or '50')
        # 保留帖子编号和图序，重复运行时可按同一个文件名跳过。
        filename = '{date:%Y%m%d}_{tweet_id}_{num}.{extension}'
        destination = destination / account
        args += ['--range', f'1-{maximum}', '--sleep-request', '1-2']
        if since:
            cutoff = start_date(since).strftime('%Y%m%d')
            args += ['--filter', f"date.strftime('%Y%m%d') >= '{cutoff}'"]
    else:
        url, _ = site_url(raw, ('instagram',))
        filename = '{date:%Y%m%d_%H%M%S}_{post_shortcode}_{num}.{extension}'
    destination.mkdir(parents=True, exist_ok=True)
    args += ['--directory', str(destination), '--filename', filename]
    if cookie:
        args += ['--cookies', str(cookie)]
    log(f'保存到 {destination}')
    if run_tool(args + ['--', url], log):
        if site == 'instagram' and not cookie:
            raise RuntimeError('Instagram 图片下载失败。若日志提示 401 或要求登录，请在设置中选择 Instagram Cookies。')
        raise RuntimeError(f'{SITES[site][0]} 图片下载失败，请查看日志。')
    return '图片任务处理完成。'


@contextmanager
def output_file(target, overwrite=False):
    """在目标目录写完临时文件后再发布，保留已有成品。"""
    with TemporaryDirectory(prefix='.media-', dir=target.parent) as folder:
        temporary = Path(folder) / target.name
        yield temporary
        if overwrite:
            temporary.replace(target)
        elif os.name == 'nt':
            temporary.rename(target)
        else:
            os.link(temporary, target)


def collage_layout(sources, horizontal):
    sizes = []
    for source in sources:
        with Image.open(source) as image:
            w, h = image.size
            if image.getexif().get(274) in (5, 6, 7, 8):
                w, h = h, w
            sizes.append((w, h))
    first_width, first_height = sizes[0]
    if horizontal:
        sizes = [(max(1, round(w * first_height / h)), first_height) for w, h in sizes]
        canvas_size = (sum(w for w, _ in sizes), first_height)
    else:
        sizes = [(first_width, max(1, round(h * first_width / w))) for w, h in sizes]
        canvas_size = (first_width, sum(h for _, h in sizes))
    return sizes, canvas_size


def render_collage(sources, horizontal, sizes, canvas_size, scale=1, log=None):
    width, height = (max(1, round(length * scale)) for length in canvas_size)
    canvas = Image.new('RGBA', (width, height), 'white')
    axis = 0 if horizontal else 1
    axis_scale = canvas.size[axis] / canvas_size[axis]
    offset = 0
    try:
        for source, size in zip(sources, sizes):
            start = round(offset * axis_scale)
            offset += size[axis]
            length = round(offset * axis_scale) - start
            if not length:
                continue
            position = (start, 0) if horizontal else (0, start)
            tile_size = (length, height) if horizontal else (width, length)
            with Image.open(source) as image, ImageOps.exif_transpose(image) as oriented:
                with oriented.convert('RGBA') as rgba, rgba.resize(tile_size, Image.Resampling.LANCZOS) as scaled:
                    canvas.alpha_composite(scaled, position)
            if log:
                log(f'已拼接 {source.name}')
    except Exception:
        canvas.close()
        raise
    return canvas


def preview_collage(sources, horizontal, bounds):
    sizes, canvas_size = collage_layout(sources, horizontal)
    scale = min(1, bounds[0] / canvas_size[0], bounds[1] / canvas_size[1])
    return render_collage(sources, horizontal, sizes, canvas_size, scale), canvas_size


def join_images(sources, horizontal, destination, overwrite, log):
    sizes, canvas_size = collage_layout(sources, horizontal)
    if canvas_size[0] * canvas_size[1] > 80_000_000:
        raise ValueError('拼图超过 8000 万像素，请减少图片数量或缩小第一张图片。')
    with render_collage(sources, horizontal, sizes, canvas_size, log=log) as canvas:
        with output_file(destination, overwrite) as temporary:
            canvas.save(temporary, 'PNG')
    log(f'成品尺寸 {canvas_size[0]} × {canvas_size[1]} px')
    return f'已保存 {destination}'
