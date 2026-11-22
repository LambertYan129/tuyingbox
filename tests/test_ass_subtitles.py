from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import conversion


SUBTITLE = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 128
PlayResY: 96

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&H0000FF00,&H0000FF00,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:01.50,Default,,0,0,0,,{\an7\pos(20,20)\p1}m 0 0 l 50 0 50 26 0 26{\p0}
Dialogue: 0,0:00:00.50,0:00:01.50,Default,,0,0,0,,{\an7\pos(20,65)}测试字幕
"""


class AssSubtitleTests(unittest.TestCase):
    def test_empty_ass_fails_before_encoding(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'empty.ass'
            source.write_text('[Events]\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '没有可压制的字幕事件'):
                conversion.stage_ass(source, Path(folder) / 'captions.ass')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are required')
    def test_burns_ass_into_frames_and_preserves_audio_with_windows_paths(self):
        ffmpeg = shutil.which('ffmpeg')
        filters = subprocess.check_output([ffmpeg, '-hide_banner', '-filters'], text=True)
        if not any(line.split()[1:2] == ['ass'] for line in filters.splitlines()):
            self.skipTest('FFmpeg build does not include the ASS filter')
        with TemporaryDirectory() as folder:
            work = Path(folder) / "中文 [视频], one's"
            work.mkdir()
            video = work / '输入.mp4'
            script = video.with_suffix('.ass')
            script.write_text(SUBTITLE, encoding='utf-16')
            subprocess.run([
                ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=128x96:r=10:d=2',
                '-f', 'lavfi', '-i', 'sine=d=2', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(video),
            ], check=True)
            original = video.read_bytes(), script.read_bytes()

            def green_pixel_count(when):
                frame = subprocess.check_output([
                    ffmpeg, '-v', 'error', '-ss', when, '-i', str(result),
                    '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1',
                ])
                self.assertEqual(len(frame), 128 * 96 * 3)
                return sum(g > 120 and g > r + 60 and g > b + 60
                           for r, g, b in zip(frame[0::3], frame[1::3], frame[2::3]))

            options = conversion.Options('subtitle', 'MP4')
            result = conversion.convert_one(video, work, options, lambda _: None, lambda _: None)
            self.assertEqual(result.name, '输入_字幕压制.mp4')
            self.assertEqual([s['codec_type'] for s in conversion.probe(result)['streams']], ['video', 'audio'])
            self.assertEqual(green_pixel_count('0.1'), 0)
            self.assertGreater(green_pixel_count('1.0'), 500)
            self.assertEqual((video.read_bytes(), script.read_bytes()), original)
            self.assertFalse(list(work.glob('.tuyingbox-*')))


if __name__ == '__main__':
    unittest.main()
