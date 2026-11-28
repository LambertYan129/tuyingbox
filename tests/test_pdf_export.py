from contextlib import closing
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
import pypdfium2 as pdfium


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import media
import pdf_export


class PdfExportTests(unittest.TestCase):
    def test_page_selection_uses_document_order_without_duplicates(self):
        self.assertEqual(pdf_export.selected_pages('5,1-3，2', 5), [1, 2, 3, 5])
        self.assertEqual(list(pdf_export.selected_pages('', 2)), [1, 2])
        with self.assertRaisesRegex(ValueError, '共有 5 页'):
            pdf_export.selected_pages('2-6', 5)

    def test_vector_page_is_rendered_at_requested_dpi_and_keeps_existing_png(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '测试表格.pdf'
            with pdfium.PdfDocument.new() as document:
                for _ in range(2):
                    with closing(document.new_page(144, 216)) as page:
                        rect = pdfium.raw.FPDFPageObj_CreateNewRect(12, 12, 24, 12)
                        pdfium.raw.FPDFPageObj_SetFillColor(rect, 0, 0, 255, 255)
                        pdfium.raw.FPDFPath_SetDrawMode(rect, pdfium.raw.FPDF_FILLMODE_WINDING, 0)
                        pdfium.raw.FPDFPage_InsertObject(page, rect)
                        page.gen_content()
                document.save(source)
            output = root / 'PNG'
            output.mkdir()
            original = output / '测试表格_p002.png'
            original.write_bytes(b'existing')
            progress = []
            pdf_export.export_pdf(source, output, 600, '2', progress.append, lambda _: None, media.ToolControl())
            with Image.open(output / '测试表格_p002 (2).png') as image:
                self.assertLessEqual(abs(image.width - 1200), 1)
                self.assertLessEqual(abs(image.height - 1800), 1)
                self.assertAlmostEqual(image.info['dpi'][0], 600, places=1)
                self.assertEqual(image.getpixel((150, 1650))[:3], (0, 0, 255))
            self.assertEqual(progress, [100])
            self.assertEqual(original.read_bytes(), b'existing')
            self.assertEqual(len(list(output.iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
