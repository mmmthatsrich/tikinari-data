import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import re
import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from utils import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAUNSELL_PDF     = os.path.join(ROOT, "A Grammaer of the New Zealand Language.pdf")
HEKARAO_PDF      = os.path.join(ROOT, "EMI0001_A-korao.pdf")
MAUNSELL_SAMPLES = os.path.join(ROOT, "sources", "maunsell", "samples")
HEKARAO_SAMPLES  = os.path.join(ROOT, "sources", "hekarao", "samples")

# Letters used in Maori (no b,c,d,f,g,j,l,q,s,v,x,y,z)
MAORI_LETTERS = set('aehikmnoprtuw')


def maori_word_ratio(text):
    """Fraction of alphabetic tokens whose letters are all in the Maori set."""
    words = re.findall(r'[A-Za-z]{2,}', text)
    if not words:
        return 0.0
    maori = sum(1 for w in words if set(w.lower()).issubset(MAORI_LETTERS))
    return maori / len(words)


def assess_maunsell():
    os.makedirs(MAUNSELL_SAMPLES, exist_ok=True)
    doc = fitz.open(MAUNSELL_PDF)
    print(f"Maunsell PDF total pages: {len(doc)}")

    sample_pages = [145, 150, 180, 220, 244]
    print("\n--- Maunsell Grammar samples ---")
    for page_num in sample_pages:
        page = doc[page_num - 1]
        mat  = fitz.Matrix(300 / 72, 300 / 72)
        pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img  = Image.frombytes("L", [pix.width, pix.height], pix.samples)

        text = pytesseract.image_to_string(img, config='--psm 6 --oem 3 -l eng')

        out  = os.path.join(MAUNSELL_SAMPLES, f"page_{page_num}.txt")
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text)

        ratio = maori_word_ratio(text)
        print(f"  p{page_num}: {len(text):5d} chars  {ratio:.0%} Maori-pattern  [{pix.width}x{pix.height}px]  -> {out}")

    doc.close()


def assess_hekarao():
    os.makedirs(HEKARAO_SAMPLES, exist_ok=True)
    doc = fitz.open(HEKARAO_PDF)
    print(f"\nHe Karao PDF total pages: {len(doc)}")

    sample_pages = [14, 20, 50, 55]
    print("\n--- He Karao samples ---")
    for page_num in sample_pages:
        page   = doc[page_num - 1]
        images = page.get_images(full=True)
        if not images:
            print(f"  p{page_num}: no embedded images found")
            continue

        xref     = images[0][0]
        img_data = doc.extract_image(xref)
        pil_img  = Image.open(io.BytesIO(img_data['image']))
        orig_w, orig_h = pil_img.size

        new_h   = int(orig_h * 1500 / orig_w)
        pil_img = pil_img.resize((1500, new_h), Image.LANCZOS)
        gray    = pil_img.convert('L')

        text = pytesseract.image_to_string(gray, config='--psm 6 --oem 3 -l eng')

        out  = os.path.join(HEKARAO_SAMPLES, f"page_{page_num}.txt")
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text)

        ratio = maori_word_ratio(text)
        print(f"  p{page_num}: {img_data['ext'].upper()} {orig_w}x{orig_h} -> 1500x{new_h}  {len(text):5d} chars  {ratio:.0%} Maori-pattern  -> {out}")

    doc.close()


def main():
    print("Session 23: Historical PDF Assessment")
    print("=" * 40)
    assess_maunsell()
    assess_hekarao()
    print("\nDone. Review sample .txt files before proceeding to Session 24.")


if __name__ == '__main__':
    main()
