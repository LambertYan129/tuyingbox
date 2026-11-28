from __future__ import annotations

import math
import re
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pypdfium2 as pdfium

from conversion import publish


PDF_DPI = (150, 300, 450, 600, 900, 1200)
DEFAULT_DPI = 600
MAX_PAGE_PIXELS = 150_000_000


def selected_pages(selection, count):
    if not selection.strip():
        return range(1, count + 1)

    pages = set()
    for part in selection.replace('，', ',').split(','):
        span = re.fullmatch(r'([0-9]+)(?:\s*-\s*([0-9]+))?', part.strip())
        if span is None:
            raise ValueError('请填写页码或范围，例如 1-3,5。')
        first = int(span[1])
        last = int(span[2]) if span[2] else first
        if not 1 <= first <= last <= count:
            raise ValueError(f'页码 {part.strip()} 无效，此 PDF 共有 {count} 页。')
        pages.update(range(first, last + 1))
    return sorted(pages)


def render_page(page, destination, dpi):
    scale = dpi / 72
    width, height = page.get_size()
    if not all(math.isfinite(side) and side > 0 for side in (width, height)):
        raise ValueError('PDF 页面尺寸无效。')
    if math.ceil(width * scale) * math.ceil(height * scale) > MAX_PAGE_PIXELS:
        raise ValueError(f'此页面在 {dpi} DPI 下超过 1.5 亿像素，请降低 DPI 后重试。')

    with closing(page.render(scale=scale, draw_annots=True, rev_byteorder=True,
                             force_bitmap_format=pdfium.raw.FPDFBitmap_BGRA)) as bitmap:
        with bitmap.to_pil() as image:
            image.save(destination, format='PNG', dpi=(dpi, dpi), compress_level=4)


def export_pdf(source, destination, dpi, selection, progress, log, control):
    if dpi not in PDF_DPI:
        raise ValueError('请选择列表中的输出 DPI。')
    control.check()
    try:
        document = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as exc:
        raise ValueError(f'无法打开 PDF，可能是文件损坏或需要密码。{exc}') from exc

    with document:
        document.init_forms()
        count = len(document)
        if count == 0:
            raise ValueError('PDF 没有可以导出的页面。')
        pages = selected_pages(selection, count)
        digits = max(3, len(str(count)))
        destination.mkdir(parents=True, exist_ok=True)
        log(f'按 {dpi} DPI 渲染 {len(pages)} 页 · {source.name}')
        with TemporaryDirectory(prefix='.tuyingbox-pdf-', dir=destination) as folder:
            temporary = Path(folder) / 'page.png'
            for completed, number in enumerate(pages, 1):
                control.check()
                try:
                    with closing(document[number - 1]) as page:
                        render_page(page, temporary, dpi)
                except (OSError, ValueError, pdfium.PdfiumError) as exc:
                    raise ValueError(f'第 {number} 页导出失败。{exc}') from exc
                control.check()
                output = publish(temporary, destination, f'{source.stem}_p{number:0{digits}d}', '.png')
                temporary.unlink(missing_ok=True)
                log(f'已保存第 {number} 页 · {output.name}')
                progress(completed / len(pages) * 100)
    return f'已导出 {len(pages)} 张 PNG · {destination}'
