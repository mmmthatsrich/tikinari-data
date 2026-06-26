import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import argparse
import numpy as np
import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageFilter

from utils import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH   = os.path.join(ROOT, "A Grammaer of the New Zealand Language.pdf")
OCR_DIR    = os.path.join(ROOT, "sources", "maunsell", "ocr")

START_PAGE = 145
END_PAGE   = 244
OCR_CONFIG = '--psm 6 --oem 3 -l eng'

# Handles common OCR misreads of '(' — e.g. ¢, {, [, c, © — and ')' as }
BOOK_PAGE_RE = re.compile(r'[\(\[{¢©c]\s*(\d{2,3})\s*[\)\]\}]')


def otsu_threshold(arr):
    """Return Otsu's optimal binarization threshold for a grayscale numpy array."""
    hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
    total = arr.size
    sum_all = float(np.dot(np.arange(256), hist))
    sum_bg, w_bg, var_max, threshold = 0.0, 0, 0.0, 128
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / w_bg
        mean_fg = (sum_all - sum_bg) / w_fg
        var = w_bg * w_fg * (mean_bg - mean_fg) ** 2
        if var > var_max:
            var_max = var
            threshold = t
    return threshold


def preprocess(pix):
    """raw pixmap -> PIL grayscale -> Otsu binarize -> mild UnsharpMask."""
    img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
    arr = np.array(img)
    t = otsu_threshold(arr)
    binary = ((arr > t).astype(np.uint8) * 255)
    img_bin = Image.fromarray(binary, mode='L')
    return img_bin.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))


def extract_book_page(text):
    """Extract book-page number from OCR header like ( 165 ) or ¢ 205) near top of page."""
    m = BOOK_PAGE_RE.search(text[:200])
    return int(m.group(1)) if m else None


def ocr_page(doc, pdf_page_num):
    page = doc[pdf_page_num - 1]
    mat  = fitz.Matrix(300 / 72, 300 / 72)
    pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img  = preprocess(pix)
    text = pytesseract.image_to_string(img, config=OCR_CONFIG)
    return text, extract_book_page(text)


def main():
    parser = argparse.ArgumentParser(description='Maunsell OCR — pages 145-244')
    parser.add_argument('--limit', type=int, default=0,
                        help='Stop after N pages processed (0 = all, skips not counted)')
    args = parser.parse_args()

    os.makedirs(OCR_DIR, exist_ok=True)
    doc = fitz.open(PDF_PATH)
    pages_done = 0

    for pdf_page_num in range(START_PAGE, END_PAGE + 1):
        out_path = os.path.join(OCR_DIR, f"page_{pdf_page_num:03d}.txt")
        if os.path.exists(out_path):
            print(f"  p{pdf_page_num}: skip (exists)")
            continue

        text, book_page = ocr_page(doc, pdf_page_num)
        header = f"# PDF_PAGE={pdf_page_num} BOOK_PAGE={book_page}\n"

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(header + text)

        print(f"  p{pdf_page_num}: BOOK_PAGE={book_page}  {len(text):5d} chars -> {os.path.basename(out_path)}")
        pages_done += 1

        if args.limit and pages_done >= args.limit:
            print(f"\nLimit {args.limit} reached. Run again to continue from where it stopped.")
            break

    doc.close()
    print(f"\nDone. {pages_done} pages OCR'd. Output: {OCR_DIR}")


if __name__ == '__main__':
    main()
