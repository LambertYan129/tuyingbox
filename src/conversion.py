from __future__ import annotations

import json
import math
import os
import subprocess
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, ImageSequence

from media import NO_WINDOW, TaskCancelled, require_tool, run_tool


VIDEO_INPUTS = 'mp4 mkv mov avi webm m4v ts mts m2ts wmv flv mpg mpeg 3gp ogv'
AUDIO_INPUTS = 'mp3 m4a aac flac wav ogg opus wma aiff aif alac m4b mka'
IMAGE_INPUTS = 'png jpg jpeg webp avif gif ico bmp tif tiff'
VIDEO_FORMATS = ('MP4', 'MKV', 'MOV', 'WebM')
AUDIO_FORMATS = ('MP3', 'M4A', 'FLAC', 'WAV', 'AAC', 'OGG', 'Opus')
IMAGE_FORMATS = ('PNG', 'JPG', 'WebP', 'AVIF', 'GIF', 'GIF（低画质）', 'ICO', 'PDF')
INPUTS = {'video': VIDEO_INPUTS, 'speed': VIDEO_INPUTS, 'extract': VIDEO_INPUTS,
          'audio': AUDIO_INPUTS, 'ncm': 'ncm', 'image': IMAGE_INPUTS}
FORMATS = {'video': VIDEO_FORMATS, 'speed': VIDEO_FORMATS, 'extract': AUDIO_FORMATS,
           'audio': AUDIO_FORMATS, 'ncm': ('原始格式（MP3 / FLAC）', *AUDIO_FORMATS), 'image': IMAGE_FORMATS}
QUALITY = {'标准': (21, 31, '192k'), '高画质 / 高音质': (17, 24, '256k'),
           '小体积': (27, 39, '128k')}
FFMPEG_STALL_TIMEOUT = 90


@dataclass(frozen=True)
class Options:
    mode: str
    target: str
    encoding: str = '自动'
    quality: str = '标准'
    track: int = 0
    by_duration: bool = False
    speed: str = '1.5'
    scale: float = 1.0
    rotation: int = 0

    @property
    def extension(self):
        return self.target.split('（', 1)[0].lower()


def probe(source, control=None):
    if control is not None:
        control.check()
    with subprocess.Popen(
        [require_tool('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(source)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
    ) as process, (control.watch(process) if control is not None else nullcontext()):
        try:
            stdout, stderr = process.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ValueError('读取媒体信息超时。') from None
        if control is not None:
            control.check()
        if process.returncode:
            raise ValueError(stderr.strip() or '无法读取媒体信息。')
    return json.loads(stdout)


def finite_number(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def source_duration(info, stream=None):
    containers = (stream or {}, info.get('format', {}), *info.get('streams', ()))
    for container in containers:
        duration = finite_number(container.get('duration'))
        if duration is not None and duration > 0:
            return duration
    return None


def audio_tracks(info):
    return [stream for stream in info.get('streams', ()) if stream.get('codec_type') == 'audio']


def parse_speed_value(value, by_duration):
    parts = value.strip().split(':') if by_duration else [value.strip()]
    numbers = [finite_number(part) for part in parts]
    if (len(parts) > 3 or any(number is None or number < 0 for number in numbers)
            or any(not number.is_integer() for number in numbers[:-1])
            or any(number >= 60 for number in numbers[1:])):
        raise ValueError('时长请输入秒数、分:秒或时:分:秒。' if by_duration else '请输入 0.25–4 之间的倍率。')
    total = sum(number * 60 ** index for index, number in enumerate(reversed(numbers)))
    if not math.isfinite(total) or total <= 0:
        raise ValueError('目标时长必须大于 0。' if by_duration else '请输入 0.25–4 之间的倍率。')
    if not by_duration and not 0.25 <= total <= 4:
        raise ValueError('请输入 0.25–4 之间的倍率。')
    return total


def speed_plan(duration, options):
    if duration is None:
        raise ValueError('读不到原视频时长。')
    requested = parse_speed_value(options.speed, options.by_duration)
    if not options.by_duration:
        return requested, duration / requested
    ratio = duration / requested
    if ratio < 0.25 - 1e-9 or ratio > 4 + 1e-9:
        raise ValueError(f'目标时长超出 0.25×–4× 对应的范围。此视频可设 {duration / 4:.3f}–{duration * 4:.3f} 秒。')
    return min(4, max(0.25, ratio)), requested


def tempo_filter(ratio):
    factors = []
    while ratio < 0.5:
        factors.append(0.5)
        ratio /= 0.5
    while ratio > 2:
        factors.append(2)
        ratio /= 2
    factors.append(ratio)
    return ','.join(f'atempo={factor:.12g}' for factor in factors)


def speed_frame_rate(video, ratio):
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            source_rate = float(Fraction(video.get(key, '0/0')))
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        if source_rate > 0:
            return min(120, max(30, source_rate * ratio))
    return 30


def ffmpeg_progress(source, target, arguments, duration, progress, *, control=None, input_options=()):
    recent = deque(maxlen=5)
    latest = {'frame': 0, 'out_time_us': 0}

    def handle(line):
        key, _, value = line.partition('=')
        if key in latest and value.isdecimal():
            current = int(value)
            if current <= latest[key]:
                return False
            latest[key] = current
            if key == 'out_time_us' and duration:
                progress(min(99, current / 10000 / duration))
            return True
        elif not key.replace('_', '').isalnum() or '=' not in line:
            recent.append(line)
        return False

    command = [require_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               *input_options, '-i', str(source), *arguments, '-progress', 'pipe:1', '-nostats', str(target)]
    try:
        result = run_tool(command, handle, control=control, stall_timeout=FFMPEG_STALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        if control is not None:
            control.check()
        raise RuntimeError(f'FFmpeg 连续 {FFMPEG_STALL_TIMEOUT} 秒没有推进，已停止处理此文件。') from None
    if result:
        raise RuntimeError(' · '.join(recent) or 'FFmpeg 无法写入该格式。')


def video_codecs(extension, quality, speed_filter=None):
    h264, vp9, bitrate = QUALITY[quality]
    if extension == 'webm':
        codecs = ['-c:v', 'libvpx-vp9', '-crf', str(vp9), '-b:v', '0', '-deadline', 'good',
                  '-cpu-used', '3', '-c:a', 'libopus']
    else:
        codecs = ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(h264), '-c:a', 'aac']
    filters = ['pad=ceil(iw/2)*2:ceil(ih/2)*2']
    if speed_filter:
        filters.append(speed_filter)
    return [*codecs, '-pix_fmt', 'yuv420p', '-b:a', bitrate, '-vf', ','.join(filters)]


def convert_video(source, target, options, info, progress, log, control=None):
    video = next((stream for stream in info.get('streams', ())
                  if stream.get('codec_type') == 'video' and not stream.get('disposition', {}).get('attached_pic')), None)
    if video is None:
        raise ValueError('文件中没有视频轨道。')
    duration = source_duration(info)
    extension = options.extension
    video_mapping = f"0:{video['index']}" if options.mode == 'speed' else '0:V'
    mapping = ['-map', video_mapping, '-map', '0:a?', '-map_metadata', '0']
    flags = ['-movflags', '+faststart'] if extension in ('mp4', 'mov') else []
    if options.mode == 'speed':
        ratio, result_duration = speed_plan(duration, options)
        start = finite_number(info.get('format', {}).get('start_time')) or 0

        def offset(stream):
            time = finite_number(stream.get('start_time'))
            return (time - start) / ratio if time is not None else 0

        rate = speed_frame_rate(video, ratio)
        vf = (f'settb=AVTB,setpts=(PTS-STARTPTS)/{ratio:.12g}+{offset(video):.12g}/TB,'
              f'fps={rate:.8f},tpad=stop_mode=clone:stop_duration={result_duration:.9f},'
              f'trim=end={result_duration:.9f}')
        codecs = video_codecs(extension, options.quality, vf)
        # Keep the encoder from holding video frames while the speed filters drain the audio.
        codecs += ['-lag-in-frames', '0'] if extension == 'webm' else ['-tune', 'zerolatency']
        audio_filters = []
        for index, stream in enumerate(audio_tracks(info)):
            af = (f'{tempo_filter(ratio)},asetpts=PTS-STARTPTS+{offset(stream):.12g}/TB,'
                  f'apad=pad_dur={result_duration:.9f},atrim=end={result_duration:.9f}')
            audio_filters.extend([f'-filter:a:{index}', af])
        log(f'开始变速编码 · {ratio:.3g}× · 目标约 {result_duration:.2f} 秒')
        # Limit decoder lookahead so an interleaved audio queue cannot block VP9 startup.
        ffmpeg_progress(source, target, [*mapping, '-map_chapters', '-1', *codecs, *audio_filters,
                                         *flags], result_duration, progress, control=control,
                        input_options=('-threads:v', '4'))
        return
    mapping += ['-map_chapters', '0']
    if options.encoding != '重新编码':
        try:
            ffmpeg_progress(source, target, [*mapping, '-c', 'copy', *flags], duration, progress, control=control)
        except RuntimeError as exc:
            if options.encoding == '仅无损封装':
                raise
            target.unlink(missing_ok=True)
            log(f'无损封装失败，改用重新编码。{exc}')
        else:
            log('已无损封装。')
            return
    ffmpeg_progress(source, target, [*mapping, *video_codecs(extension, options.quality), *flags],
                    duration, progress, control=control)


def convert_audio(source, target, options, info, progress, control=None):
    tracks = audio_tracks(info)
    if not tracks:
        raise ValueError('文件中没有音频轨道。')
    if not 0 <= options.track < len(tracks):
        raise ValueError(f'未找到第 {options.track + 1} 条音轨。此文件有 {len(tracks)} 条音轨。')
    _, _, bitrate = QUALITY[options.quality]
    codec = {'mp3': 'libmp3lame', 'm4a': 'aac', 'aac': 'aac', 'flac': 'flac',
             'wav': 'pcm_s16le', 'ogg': 'libvorbis', 'opus': 'libopus'}[target.suffix[1:]]
    arguments = ['-map', f'0:a:{options.track}', '-map_metadata', '0', '-map_chapters', '-1', '-c:a', codec]
    if codec not in ('flac', 'pcm_s16le'):
        arguments += ['-b:a', bitrate]
    if codec in ('libmp3lame', 'libvorbis', 'libopus', 'aac'):
        channels = tracks[options.track].get('channels', 2)
        if channels > 2:
            arguments += ['-ac', '2']
    if target.suffix in ('.mp3', '.m4a', '.flac'):
        covers = [stream['index'] for stream in info.get('streams', ())
                  if stream.get('disposition', {}).get('attached_pic')]
        if covers:
            arguments += ['-map', f'0:{covers[0]}', '-c:v', 'mjpeg', '-disposition:v', 'attached_pic']
    ffmpeg_progress(source, target, arguments, source_duration(info, tracks[options.track]), progress, control=control)


def convert_ncm(source, folder, options, progress, control=None):
    log = deque(maxlen=5)
    result = run_tool([require_tool('ncmdump'), '-o', str(folder), str(source)], log.append, control=control)
    files = [file for file in folder.iterdir() if file.suffix.lower() in ('.mp3', '.flac')
             and file.is_file() and file.stat().st_size]
    if result or len(files) != 1:
        raise RuntimeError('未能读取此 NCM 文件。' + (' · ' + ' · '.join(log) if log else ''))
    original = files[0]
    if options.target == FORMATS['ncm'][0] or original.suffix.lower() == '.' + options.extension:
        return original
    converted = folder / f'converted.{options.extension}'
    convert_audio(original, converted, options, probe(original, control), progress, control)
    return converted


def image_frame(frame, options):
    with ImageOps.exif_transpose(frame) as oriented:
        result = oriented.convert('RGBA')
    if options.rotation:
        direction = Image.Transpose.ROTATE_90 if options.rotation == 90 else Image.Transpose.ROTATE_270
        rotated = result.transpose(direction)
        result.close()
        result = rotated
    if options.scale != 1:
        scaled = result.resize(tuple(max(1, round(size * options.scale)) for size in result.size),
                               Image.Resampling.LANCZOS)
        result.close()
        result = scaled
    return result


def gif_frame(frame, low_quality):
    colors = 64 if low_quality else 256
    with frame.convert('RGB') as rgb:
        palette = rgb.quantize(colors=colors - 1)
    with frame.getchannel('A') as alpha, alpha.point(lambda value: 255 if value < 128 else 0) as mask:
        palette.paste(colors - 1, mask=mask)
    palette.info['transparency'] = colors - 1
    return palette


def convert_image(source, target, options, progress):
    extension = options.extension
    frames = []
    durations = []
    try:
        with Image.open(source) as image:
            count = image.n_frames if getattr(image, 'is_animated', False) else 1
            start = int(bool(image.info.get('default_image')))
            if extension not in ('gif', 'webp', 'avif', 'png'):
                count = 1
                start = 0
            loop = image.info.get('loop', 1)
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                if index >= count:
                    break
                if index < start:
                    continue
                durations.append(max(1, int(frame.info.get('duration', 100))))
                frame_image = image_frame(frame, options)
                if extension == 'gif':
                    with frame_image:
                        frame_image = gif_frame(frame_image, options.target != 'GIF')
                frames.append(frame_image)
                progress(min(90, (index + 1) / count * 90))
        first, *rest = frames
        settings = {}
        if rest:
            settings.update(save_all=True, append_images=rest, duration=durations, loop=loop)
            if extension == 'gif':
                settings.update(disposal=2, optimize=False)
        if extension in ('jpg', 'pdf'):
            with Image.new('RGB', first.size, 'white') as rgb, first.getchannel('A') as alpha:
                rgb.paste(first, mask=alpha)
                rgb.save(target, quality=92)
        elif extension == 'ico':
            with ImageOps.contain(first, (256, 256), Image.Resampling.LANCZOS) as fitted:
                with Image.new('RGBA', (256, 256)) as canvas:
                    canvas.alpha_composite(fitted, ((256 - fitted.width) // 2, (256 - fitted.height) // 2))
                    canvas.save(target)
        else:
            first.save(target, **settings)
    finally:
        for frame in frames:
            frame.close()


def publish(temporary, folder, name, extension):
    if not temporary.is_file() or not temporary.stat().st_size:
        raise RuntimeError('转换程序没有生成有效的输出文件。')
    number = 1
    while True:
        stem = name if number == 1 else f'{name} ({number})'
        target = folder / (stem + extension)
        try:
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            number += 1
        else:
            return target


def convert_one(source, folder, options, progress, log, control=None):
    if control is not None:
        control.check()
    if source.suffix.lower()[1:] not in INPUTS[options.mode].split():
        raise ValueError('文件扩展名与当前转换类型不匹配。')
    if not source.is_file():
        raise ValueError('源文件不存在。')
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.tuyingbox-', dir=folder) as directory:
        work = Path(directory)
        if options.mode == 'ncm':
            target = convert_ncm(source, work, options, progress, control)
        else:
            target = work / ('output.' + options.extension)
            if options.mode == 'image':
                convert_image(source, target, options, progress)
            elif options.mode in ('video', 'speed'):
                convert_video(source, target, options, probe(source, control), progress, log, control)
            else:
                convert_audio(source, target, options, probe(source, control), progress, control)
        if control is not None:
            control.check()
        name = source.stem
        if options.mode == 'speed':
            value = parse_speed_value(options.speed, options.by_duration)
            unit = 's' if options.by_duration else 'x'
            name += f'_变速_{value:.12g}{unit}'
        return publish(target, folder, name, target.suffix.lower())


def convert_batch(sources, destination, options, update, progress, log, control=None):
    total = len(sources)
    succeeded = 0
    for index, source in enumerate(sources):
        update(index, '准备中', None)

        def report(value):
            if control is not None:
                control.check()
            update(index, f'处理中 {value:.1f}%', None)
            progress((index + value / 100) / total * 100)

        try:
            target = convert_one(source, destination or source.parent, options, report, log, control)
        except TaskCancelled:
            update(index, '已取消', '当前转换已停止。')
            for waiting in range(index + 1, total):
                update(waiting, '未处理', '批量转换已停止。')
            raise TaskCancelled(f'已停止转换。保留 {succeeded} 个已完成文件。') from None
        except (OSError, RuntimeError, ValueError, MemoryError, subprocess.SubprocessError,
                Image.DecompressionBombError) as exc:
            detail = str(exc) or type(exc).__name__
            update(index, '失败', detail)
            log(f'{source.name} · {detail}')
        else:
            succeeded += 1
            update(index, '已完成', str(target))
            log(f'已保存 {target}')
        progress((index + 1) / total * 100)
    summary = f'转换结束，成功 {succeeded} 个，失败 {total - succeeded} 个。'
    if not succeeded:
        raise RuntimeError(summary)
    return summary
