#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""كاتب Excel صغير بالمكتبة القياسية وحدها (لا openpyxl).

المشروع بلا اعتمادات خارجية، فالتصدير يُبنى يدويًا: ملف xlsx ما هو إلا حزمة
zip فيها XML. نكتب أوراقًا بخلايا نصّية (inlineStr) ورقمية، ورأسًا عريضًا.
يكفي هذا لفتحه في Excel وGoogle Sheets ونُمْبرز، والعربية تمرّ كما هي UTF-8.

الاستعمال:
    data = build_xlsx([("اللوحات", ["يوزر","مدة"], [["abc", 15], ...])])
    open("out.xlsx","wb").write(data)
"""

import io
import zipfile
from xml.sax.saxutils import escape


def _col(n):
    """1→A، 27→AA."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _cell(ref, value, style=None):
    st = ' s="%d"' % style if style else ""
    if value is None or value == "":
        return '<c r="%s"%s/>' % (ref, st)
    if _is_number(value):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, value)
    text = escape(str(value))
    # يحفظ الفراغات الطرفية وأسطر النصّ
    return ('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, st, text))


def _sheet_xml(headers, rows):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetData>']
    r = 1
    if headers:
        cells = "".join(_cell("%s%d" % (_col(i + 1), r), h, style=1)
                        for i, h in enumerate(headers))
        out.append('<row r="%d">%s</row>' % (r, cells))
        r += 1
    for row in rows:
        cells = "".join(_cell("%s%d" % (_col(i + 1), r), v)
                        for i, v in enumerate(row))
        out.append('<row r="%d">%s</row>' % (r, cells))
        r += 1
    out.append('</sheetData></worksheet>')
    return "".join(out)


def _safe_name(name, used):
    """اسم ورقةٍ صالح: بلا []:*?/\\ وبطول ≤٣١ وفريد."""
    n = "".join(c for c in str(name or "Sheet") if c not in '[]:*?/\\')[:31] or "Sheet"
    base, i = n, 2
    while n.lower() in used:
        suffix = " (%d)" % i
        n = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(n.lower())
    return n


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '%s</Types>')

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>')

# نمطان: العادي (0) والعريض للرأس (1).
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
    '<cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs>'
    '</styleSheet>')


def build_xlsx(sheets):
    """‏sheets = [(اسم_الورقة, [رؤوس], [[صفوف]])] → bytes لملف xlsx كامل."""
    if not sheets:
        sheets = [("Sheet1", [], [])]
    used = set()
    named = [(_safe_name(n, used), h, r) for (n, h, r) in sheets]

    overrides, wb_sheets, wb_rels, files = [], [], [], {}
    for i, (name, headers, rows) in enumerate(named, start=1):
        part = "xl/worksheets/sheet%d.xml" % i
        overrides.append('<Override PartName="/%s" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % part)
        wb_sheets.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), i, i))
        wb_rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i))
        files[part] = _sheet_xml(headers, rows)

    files["[Content_Types].xml"] = _CONTENT_TYPES % "".join(overrides)
    files["_rels/.rels"] = _RELS
    files["xl/styles.xml"] = _STYLES
    files["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>%s</sheets></workbook>' % "".join(wb_sheets))
    files["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '%s</Relationships>' % "".join(wb_rels))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml أولًا عُرفًا
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()
