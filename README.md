# 图影盒 v1.1.2

<img src="assets/app.png" width="72" height="72" alt="图影盒标志">

图影盒是一款 Windows 便携工具，可下载图片和视频、预览并拼接图片，以及批量转换视频、音频和图片。

## 功能

| 栏目 | 功能 |
| --- | --- |
| 下载图片 | 批量下载 X／Twitter 图片，可按日期和数量筛选。支持抖音图文。选择 Instagram 可同时保存帖子中的图片和视频。 |
| 下载视频 | 支持 YouTube、X／Twitter、哔哩哔哩、抖音和 Instagram 视频。一行一个链接，可选下载完整播放列表。YouTube 需要处理 JavaScript 时会调用 Deno。 |
| 编辑图片 | 支持拖入、排序、横向或竖向拼接，在导出 PNG 前可实时查看预览和成品尺寸。 |
| 格式转换 | 视频转 MP4、MKV、MOV、WebM，支持无损封装或重新编码。视频可保持音高变速，可选固定倍率或目标时长。支持按音轨提取音频、音频转码、网易云音乐 NCM 转换，以及图片转换、等比缩放和旋转。 |

## 从 v1.0 升级到 v1.1.1

- **视频格式**支持 MKV、MP4、MOV、AVI、WebM、M4V、TS 等输入，自动模式优先无损封装。
- **视频变速**支持 0.25×–4×，默认保持音高。可设固定倍率，也可输入秒数、分:秒或时:分:秒作为目标时长。成品文件名会标出倍率或目标时长，例如 `视频_变速_1.5x.mp4` 和 `视频_变速_140s.mp4`。
- **音频提取与转换**支持 MP3、M4A、FLAC、WAV、AAC、OGG、Opus。可选择源文件的音轨序号。
- **NCM 转换**默认还原文件中的 MP3 或 FLAC，并保留可读取的标签和封面。也可以主动指定音频输出格式。
- **图片转换**支持 PNG、JPG、WebP、AVIF、GIF、低画质 GIF、ICO、PDF 输出。可同时按 75%／25% 等比缩放，并向左或向右旋转 90°。
- **批量转换**支持多选和拖放，显示每个文件的进度与结果。同名成品自动编号。留空输出目录时，成品保存到各自的源文件目录。
- **变速修复与任务控制**修复部分 VP9 视频变速卡在 0% 的问题。可点击「停止转换」，也可通过关闭窗口停止并退出。源文件和已完成的成品会保留。

## v1.1.2 更新

- 在「下载图片」中选择 Instagram，粘贴帖子或 Reel 链接，即可保存其中的图片和视频。
- 在「下载视频」中粘贴 Instagram 帖子或 Reel 链接时，只保存视频。需要登录的内容可在「Cookies 设置」中为 Instagram 选择 Netscape 文件。

## 下载与使用

1. 前往 [Releases](https://github.com/LambertYan129/tuyingbox/releases) 下载 `tuyingbox-v1.1.2-windows-x64.zip`。
2. 在 Windows 64 位电脑上完整解压，双击 `图影盒.exe`。
3. 下载目录默认为 `%USERPROFILE%\Downloads\图影盒`，运行时会定位到当前账号的用户目录。需要登录时，在 **Cookies 设置** 中为对应网站选择符合 Netscape 格式的 `.txt` 文件。

便携版带有运行所需的 Python、FFmpeg、yt-dlp、Deno、Chromium 和 ncmdump。窗口会跟随 Windows 显示缩放调整字号、控件和布局。

使用 Get cookies.txt LOCALLY 时，导出格式选 **Netscape**。图影盒的文件导入支持 Netscape `.txt`。JSON 和 Header String 无法直接导入。登录状态、可访问范围和平台响应会影响下载结果。请保存你有权下载的媒体。

更多操作见[使用说明](使用说明.txt)。

## 从源码运行与构建

需要 Windows x64、带 Tk 的 Python 3.14，以及可在 PowerShell 中找到的 `yt-dlp.exe`、`ffmpeg.exe`、`ffprobe.exe`、`deno.exe` 和 `ncmdump.exe`。也可以用下方构建脚本的参数为各工具指定完整路径。

在仓库根目录运行：

```powershell
python -m venv .venv
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python -m pip install -r requirements-build.txt
& $python -m playwright install chromium --only-shell
& $python src/launcher.py
```

关闭从源码运行的窗口后，构建便携包：

```powershell
.\build-portable.ps1 -Python $python
```

构建输出为 `dist\图影盒v1.1.2-便携版\`。运行或分发时，请随 `图影盒.exe` 保留该目录中的运行组件。工具没有加入 `PATH` 时，使用 `-YtDlp`、`-FFmpeg`、`-FFprobe`、`-Deno` 和 `-NcmDump` 指定各自的 EXE 路径。用 `-NcmDumpLicense` 指定上游 ncmdump 的 LICENSE.txt。Chromium 放在自定义目录时，使用 `-ChromiumDirectory` 指定 `chrome-headless-shell.exe` 所在目录。

## 反馈问题

请附上软件版本、Windows 版本、操作步骤和相关任务日志。提交前请遮住账号、个人路径和私密链接，Cookies 文件只保存在自己的设备上。

## 第三方组件

依赖和便携包组件的来源见[第三方组件说明](THIRD_PARTY_NOTICES.md)。
