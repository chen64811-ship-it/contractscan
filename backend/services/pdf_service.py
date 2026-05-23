# -*- coding: utf-8 -*-
"""
Markdown -> PDF Export Service
Uses fpdf2 for direct rendering, reads system fonts (Microsoft YaHei on Windows, fallbacks on macOS/Linux/Docker).
No external system library dependencies.
"""
import re
import os
from io import BytesIO


# Find available CJK font (Windows / macOS / Linux / Docker)
def _find_msyh():
    candidates = [
        # Windows built-in Microsoft YaHei
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\MSYH.TTC",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\MSYH.TTF",
        # macOS built-in CJK fonts
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux / Docker common CJK fonts
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# Strip inline Markdown markers, return plain text
def _clean(s):
    s = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', s)   # bold+italic
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)         # bold
    s = re.sub(r'__(.+?)__', r'\1', s)             # bold (underscore)
    s = re.sub(r'\*(.+?)\*', r'\1', s)             # italic
    s = re.sub(r'_(.+?)_', r'\1', s)               # italic (underscore)
    s = re.sub(r'`(.+?)`', r'\1', s)               # inline code
    s = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', s)      # links
    s = re.sub(r'~~(.+?)~~', r'\1', s)             # strikethrough
    s = re.sub(r'!\[.+?\]\(.+?\)', '', s)          # images (skip)
    return s.strip()


# Main function: Markdown -> PDF byte stream
def markdown_to_pdf(md_text, title=None):
    """
    Convert Markdown string to PDF, return bytes.
    Supports: H1-H6, paragraphs, unordered/ordered lists, nested lists, code blocks, tables, blockquotes, horizontal rules.
    """
    from fpdf import FPDF

    # Initialize PDF
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(left=20, top=20, right=20)
    pdf.set_auto_page_break(auto=True, margin=22)

    # Register CJK font
    font_path = _find_msyh()
    if font_path:
        try:
            pdf.add_font('msyh', style='', fname=font_path)
            pdf.add_font('msyh', style='B', fname=font_path)
            FONT = 'msyh'
        except Exception:
            FONT = 'helvetica'
    else:
        FONT = 'helvetica'

    PAGE_W = 170  # A4 (210mm) - 20mm margins each side

    pdf.add_page()

    # Helper functions
    def write_text(text, size=11, bold=False, indent=0, lh=7, fill=False, fill_color=None):
        """Write a block of text (supports automatic line wrapping)."""
        style = 'B' if bold else ''
        pdf.set_font(FONT, style, size)
        if fill and fill_color:
            pdf.set_fill_color(*fill_color)
        pdf.set_x(20 + indent)
        pdf.multi_cell(
            w=PAGE_W - indent,
            h=lh,
            txt=_clean(text),
            fill=fill,
        )

    def write_heading(text, level):
        cfg = {
            1: (20, 11, True),
            2: (16, 9, True),
            3: (14, 8, True),
            4: (12, 7, True),
            5: (11, 7, True),
            6: (11, 6, False),
        }
        size, lh, bold = cfg.get(level, (11, 7, False))
        pdf.ln(3 if level <= 2 else 2)
        write_text(text, size=size, bold=bold, lh=lh)
        if level == 1:
            # Draw a subtle line below H1
            pdf.set_draw_color(102, 126, 234)
            pdf.set_line_width(0.4)
            pdf.line(20, pdf.get_y(), 190, pdf.get_y())
            pdf.set_line_width(0.2)
            pdf.set_draw_color(0, 0, 0)
        pdf.ln(1)

    def write_table(t_lines):
        """Render Markdown table."""
        rows = []
        for tl in t_lines:
            stripped = tl.strip()
            # Skip separator rows |---|---|
            if re.match(r'^\|[\s\-|:]+\|$', stripped):
                continue
            cells = [_clean(c.strip()) for c in stripped.strip('|').split('|')]
            rows.append(cells)
        if not rows:
            return

        n_cols = max(len(r) for r in rows)
        col_w = PAGE_W / n_cols

        for ri, row in enumerate(rows):
            # Calculate max row height (widest cell)
            is_header = (ri == 0)
            pdf.set_font(FONT, 'B' if is_header else '', 10)
            row_h = 7

            x_start = 20
            y_start = pdf.get_y()

            # Check if near page bottom, add new page if needed
            if y_start + row_h > pdf.h - 22:
                pdf.add_page()
                y_start = pdf.get_y()

            for ci in range(n_cols):
                cell_text = row[ci] if ci < len(row) else ''
                pdf.set_xy(x_start + ci * col_w, y_start)
                pdf.set_fill_color(230, 234, 255) if is_header else pdf.set_fill_color(255, 255, 255)
                pdf.cell(col_w, row_h, cell_text[:40], border=1, fill=True)

            pdf.set_xy(x_start, y_start + row_h)

        pdf.ln(4)

    def write_code_block(code_lines):
        """Render code block."""
        if not code_lines:
            return
        pdf.set_font(FONT, '', 9)
        pdf.set_fill_color(248, 249, 255)
        # Write each line individually to avoid clipping
        for cl in code_lines:
            pdf.set_x(22)
            pdf.set_fill_color(248, 249, 255)
            pdf.multi_cell(PAGE_W - 4, 5.5, cl, fill=True)
        pdf.ln(2)

    # Line-by-line parsing
    lines = md_text.split('\n')
    i = 0
    in_code = False
    code_lines = []

    while i < len(lines):
        line = lines[i]

        # Code fence
        if re.match(r'^```', line):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                in_code = False
                write_code_block(code_lines)
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        stripped = line.strip()

        # Table (collect consecutive table rows)
        if stripped.startswith('|'):
            t_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                t_lines.append(lines[i])
                i += 1
            write_table(t_lines)
            continue

        # Blank line
        if not stripped:
            pdf.ln(3)
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^[-*_]{3,}$', stripped):
            pdf.set_draw_color(200, 200, 200)
            pdf.set_line_width(0.3)
            pdf.line(20, pdf.get_y() + 2, 190, pdf.get_y() + 2)
            pdf.ln(5)
            pdf.set_line_width(0.2)
            pdf.set_draw_color(0, 0, 0)
            i += 1
            continue

        # Heading
        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            level = len(m.group(1))
            write_heading(m.group(2), level)
            i += 1
            continue

        # Blockquote
        if stripped.startswith('> '):
            y0 = pdf.get_y()
            write_text(stripped[2:], size=11, indent=8, fill=True, fill_color=(248, 249, 255))
            y1 = pdf.get_y()
            pdf.set_draw_color(102, 126, 234)
            pdf.set_line_width(0.8)
            pdf.line(21, y0, 21, y1)
            pdf.set_line_width(0.2)
            pdf.set_draw_color(0, 0, 0)
            i += 1
            continue

        # Unordered list (supports -, *, +)
        m = re.match(r'^(\s*)([-*+])\s+(.*)', line)
        if m:
            indent_lvl = len(m.group(1)) // 2
            bullet = '\u2022' if indent_lvl == 0 else ('\u25e6' if indent_lvl == 1 else '\u25aa')
            write_text(f'{bullet} {m.group(3)}', size=11, indent=5 + indent_lvl * 5)
            i += 1
            continue

        # Ordered list
        m = re.match(r'^(\s*)(\d+)[.)]\s+(.*)', line)
        if m:
            indent_lvl = len(m.group(1)) // 2
            write_text(f'{m.group(2)}. {m.group(3)}', size=11, indent=5 + indent_lvl * 5)
            i += 1
            continue

        # Regular paragraph
        write_text(stripped, size=11)
        i += 1

    # Output byte stream
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf.read()
