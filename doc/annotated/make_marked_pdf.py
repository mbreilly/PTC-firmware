"""Add the change notes to the original v1.4 PDF.

Each page gets a wider right margin holding the notes (printed with the page), and the
anchor text is highlighted with a real PDF highlight annotation carrying the same note, so
the notes also show in a viewer's comment list.

usage: python3 make_marked_pdf.py IN.pdf OUT.pdf
"""
import sys

import pymupdf

from changes_data import CATEGORIES, CHANGES

MARGIN = 215          # extra width added on the right, in points
FONT = 7
PAD = 3


def find_anchor(doc, ch):
    hint = ch["page"] - 1
    order = [hint] + [p for d in range(1, 4) for p in (hint + d, hint - d)]
    for pno in order:
        if 0 <= pno < len(doc):
            hits = doc[pno].search_for(ch["anchor"])
            if hits:
                return pno, hits
    return None, None


def main(src, dst):
    doc = pymupdf.open(src)
    placed = {}
    missing = []
    for ch in CHANGES:
        pno, hits = find_anchor(doc, ch)
        if pno is None:
            missing.append(ch["id"])
            continue
        placed.setdefault(pno, []).append((hits, ch))

    # widen every page
    for page in doc:
        r = page.rect
        page.set_mediabox(pymupdf.Rect(0, 0, r.width + MARGIN, r.height))

    for page in doc:
        w0 = page.rect.width - MARGIN
        page.draw_rect(pymupdf.Rect(w0, 0, page.rect.width, page.rect.height),
                       color=None, fill=(0.965, 0.965, 0.955), overlay=False)
        page.draw_line((w0, 0), (w0, page.rect.height), color=(0.75, 0.75, 0.75), width=0.5)
        page.insert_text((w0 + 8, 18), "Annotated: changes from the PTC production test station",
                         fontsize=6.5, color=(0.4, 0.4, 0.4))

    for pno, items in placed.items():
        page = doc[pno]
        w0 = page.rect.width - MARGIN
        items.sort(key=lambda it: it[0][0].y0)
        next_free = 26
        for hits, ch in items:
            label, rgb = CATEGORIES[ch["cat"]]
            head = f"{ch['id']}  {label.upper()}"
            # highlight the anchor
            annot = page.add_highlight_annot(hits)
            annot.set_colors(stroke=tuple(0.55 + 0.45 * c for c in rgb))
            annot.set_info(title=f"{ch['id']} {label}", content=ch["text"])
            annot.update(opacity=0.45)
            # note box in the margin
            x0, x1 = w0 + 8, page.rect.width - 8
            body = ch["text"]
            # measure height by trial insertion on a scratch page
            scratch = pymupdf.open().new_page(width=x1 - x0, height=2000)
            hb = scratch.insert_textbox(pymupdf.Rect(PAD, PAD, x1 - x0 - PAD, 2000), body,
                                        fontsize=FONT, fontname="helv")
            text_h = 2000 - PAD - hb
            box_h = text_h + FONT + 3 * PAD + 2
            y0 = max(hits[0].y0 - 4, next_free)
            if y0 + box_h > page.rect.height - 6:
                y0 = max(next_free, page.rect.height - 6 - box_h)
            box = pymupdf.Rect(x0, y0, x1, y0 + box_h)
            page.draw_rect(box, color=rgb, fill=tuple(0.92 + 0.08 * c for c in rgb), width=0.8)
            page.insert_text((x0 + PAD, y0 + PAD + FONT), head, fontsize=FONT,
                             fontname="hebo", color=rgb)
            page.insert_textbox(pymupdf.Rect(x0 + PAD, y0 + PAD + FONT + 2, x1 - PAD,
                                             y0 + box_h), body, fontsize=FONT, fontname="helv")
            # id tag in the original right margin, and a leader line from there to the box
            a = hits[0]
            ym = (a.y0 + a.y1) / 2
            page.insert_text((w0 - 50, ym + 2.5), ch["id"], fontsize=7.5, fontname="hebo",
                             color=rgb)
            page.draw_line((w0 - 30, ym), (x0, y0 + 6), color=rgb, width=0.6)
            next_free = box.y1 + 4

    doc.set_metadata({**doc.metadata, "title": "PTC QC Procedures v1.4 - annotated with "
                      "production test station changes"})
    doc.save(dst, garbage=3, deflate=True)
    print(f"placed {sum(len(v) for v in placed.values())} notes; missing: {missing or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
