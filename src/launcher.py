from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def report_error(kind, value, details):
    """启动失败时也能记录异常，不依赖 Tk 或下载组件。"""
    executable = sys.executable if getattr(sys, 'frozen', False) else __file__
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / '图影盒'
    locations = (Path(executable).resolve().parent, local)
    for folder in locations:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / 'error.log'
            with path.open('a', encoding='utf-8') as log:
                log.write(f'\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n')
                traceback.print_exception(kind, value, details, file=log)
            return f'错误详情见 {path}'
        except OSError:
            continue
    return f'{kind.__name__}：{value}'


def main():
    if sys.argv[1:2] == ['--gallery-worker']:
        import gallery_dl

        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        del sys.argv[1]
        return gallery_dl.main()

    try:
        from display import enable_dpi_awareness

        enable_dpi_awareness()
        import app

        return app.main(report_error)
    except Exception:
        message = report_error(*sys.exc_info())
        ctypes.windll.user32.MessageBoxW(None, f'图影盒无法启动。\n\n{message}', '图影盒 v1.1.4', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
