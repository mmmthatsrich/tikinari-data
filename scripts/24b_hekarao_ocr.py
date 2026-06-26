import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import numpy as np
import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageFilter

from utils import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(ROOT, "EMI0001_A-korao.pdf")
OCR_DIR  = os.path.join(ROOT, "sources", "hekarao", "ocr")

# p14 = syllable index (skip); vocabulary on p15-27 and p50-58
PAGE_RANGES = list(range(15, 28)) + list(range(50, 59))

OCR_CONFIG = '--psm 6 --oem 3 -l eng'


def otsu_threshold(arr):
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
    img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
    arr = np.array(img)
    t = otsu_threshold(arr)
    binary = ((arr > t).astype(np.uint8) * 255)
    img_bin = Image.fromarray(binary, mode='L')
    return img_bin.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))


def ocr_page(doc, pdf_page_num):
    page = doc[pdf_page_num - 1]
    mat  = fitz.Matrix(300 / 72, 300 / 72)
    pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img  = preprocess(pix)
    tsv  = pytesseract.image_to_data(img, config=OCR_CONFIG)
    return tsv, pix.width, pix.height


def main():
    parser = argparse.ArgumentParser(description='He Karao OCR -- pages 15-27 + 50-58')
    parser.add_argument('--limit', type=int, default=0,
                        help='Stop after N pages processed (0 = all, skips not counted)')
    args = parser.parse_args()

    os.makedirs(OCR_DIR, exist_ok=True)
    doc = fitz.open(PDF_PATH)
    pages_done = 0

    for pdf_page_num in PAGE_RANGES:
        out_path = os.path.join(OCR_DIR, f"page_{pdf_page_num:03d}.tsv")
        if os.path.exists(out_path):
            print(f"  p{pdf_page_num}: skip (exists)")
            continue

        tsv, img_w, img_h = ocr_page(doc, pdf_page_num)
        header = f"# PDF_PAGE={pdf_page_num} IMG_WIDTH={img_w} IMG_HEIGHT={img_h}\n"

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(header + tsv)

        word_lines = [l for l in tsv.splitlines()
                      if len(l.split('\t')) == 12 and l.split('\t')[11].strip()]
        print(f"  p{pdf_page_num}: {len(word_lines)} words -> {os.path.basename(out_path)}")
        pages_done += 1

        if args.limit and pages_done >= args.limit:
            print(f"\nLimit {args.limit} reached. Run again to continue.")
            break

    doc.close()
    print(f"\nDone. {pages_done} pages OCR'd. Output: {OCR_DIR}")


if __name__ == '__main__':
    main()
