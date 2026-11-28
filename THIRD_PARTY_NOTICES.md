# 第三方组件说明

图影盒通过命令行调用 FFmpeg、yt-dlp、Deno、gallery-dl 和 ncmdump，并通过 Playwright 使用 Chromium。下列项目各自适用其上游许可。发布用源码目录包含图影盒代码，构建过程会从本机的 Python 环境及已准备好的工具取得运行组件。

| 组件 | 上游源码或项目说明 |
| --- | --- |
| Python / Tk | [CPython](https://github.com/python/cpython) / [Tcl/Tk](https://www.tcl-lang.org/) |
| FFmpeg / FFprobe | [FFmpeg 源码](https://ffmpeg.org/download.html#source) · [Gyan Windows 构建](https://www.gyan.dev/ffmpeg/builds/) · [许可说明](https://ffmpeg.org/legal.html) |
| yt-dlp | [yt-dlp 2026.11.23](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23) |
| pypdfium2 / PDFium | [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) / [PDFium](https://pdfium.googlesource.com/pdfium/) |
| Deno | [Deno](https://github.com/denoland/deno) |
| ncmdump 1.5.1 | [上游发布与对应源码](https://github.com/taurusxin/ncmdump/releases/tag/1.5.1)（MIT） |
| gallery-dl | [gallery-dl 源码](https://codeberg.org/mikf/gallery-dl) |
| Chromium | [Chromium 源码](https://chromium.googlesource.com/chromium/src/) |
| Playwright | [Playwright for Python](https://github.com/microsoft/playwright-python) |
| Pillow | [Pillow](https://github.com/python-pillow/Pillow) |
| Requests | [Requests](https://github.com/psf/requests) |
| tkinterdnd2 | [TkinterDnD2](https://github.com/Eliav2/tkinterdnd2) |
| PyInstaller | [PyInstaller](https://github.com/pyinstaller/pyinstaller) |

便携包的许可文本分布在 `licenses/`、Chromium 目录和组件自带的许可文件中。此表用于定位上游项目。发布含第三方二进制的版本时，应进一步核对所分发版本的对应源码及其分发许可。
