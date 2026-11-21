from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import threading
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import media


class ConversionControlTests(unittest.TestCase):
    def test_stop_ends_a_running_tool(self):
        started = threading.Event()
        control = media.ToolControl()

        def on_line(line):
            if line == 'started':
                started.set()

        args = [sys.executable, '-u', '-c', 'import time; print("started"); time.sleep(60)']
        with ThreadPoolExecutor(max_workers=1) as worker:
            task = worker.submit(media.run_tool, args, on_line, control=control, stall_timeout=8)
            try:
                self.assertTrue(started.wait(timeout=5))
                control.cancel()
                with self.assertRaises(media.TaskCancelled):
                    task.result(timeout=5)
            finally:
                control.cancel()

    def test_repeated_zero_reports_do_not_reset_the_stall_timeout(self):
        code = 'import time\nwhile True:\n print("out_time_us=0")\n time.sleep(0.05)'
        args = [sys.executable, '-u', '-c', code]
        with self.assertRaises(subprocess.TimeoutExpired):
            media.run_tool(args, lambda line: False, stall_timeout=0.5)


if __name__ == '__main__':
    unittest.main()
