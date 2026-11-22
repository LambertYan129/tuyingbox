from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import media


class InstagramDownloadTests(unittest.TestCase):
    def test_instagram_post_keeps_both_media_types_and_copies_cookies(self):
        with TemporaryDirectory() as work:
            folder = Path(work)
            cookie = folder / 'instagram.txt'
            cookie.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')

            def check_command(args, _log):
                self.assertIn('extractor.instagram.videos=merged', args)
                self.assertNotIn('extractor.instagram.videos=false', args)
                self.assertNotIn('--filter', args)
                copy = Path(args[args.index('--cookies') + 1])
                self.assertNotEqual(cookie, copy)
                self.assertEqual(cookie.read_bytes(), copy.read_bytes())
                return 0

            with patch.object(media, 'run_tool', side_effect=check_command) as run:
                media.download_gallery('instagram', 'instagram.com/p/example/', folder, cookie, '', '', lambda _: None)
            run.assert_called_once()

    def test_video_entry_routes_instagram_reels_to_the_gallery_worker(self):
        url = 'https://www.instagram.com/reel/example/'
        with TemporaryDirectory() as work, patch.object(media, 'run_tool', return_value=0) as run, (
                patch.object(media, 'require_tool', side_effect=AssertionError('Expected gallery-dl'))):
            media.download_video(url, Path(work), {'instagram': ''}, False, self.fail, lambda _: None)
        args = run.call_args.args[0]
        self.assertIn('extractor.instagram.videos=merged', args)
        self.assertIn('extension', args[args.index('--filter') + 1])
        self.assertEqual(url, args[-1])

    def test_twitter_entry_still_filters_out_videos(self):
        with TemporaryDirectory() as work, patch.object(media, 'run_tool', return_value=0) as run:
            media.download_gallery('twitter', '@example', Path(work), None, '', '50', lambda _: None)
        self.assertIn('extractor.twitter.videos=false', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
