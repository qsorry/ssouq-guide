#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
قراءة بوكيهات الخط في صفحة تعديل لوحة Xtream-Masters (مرح): الباقة فارغة (= بلا تغيير) و`selected_bouquets` فارغ،
واللوحة تكتب بوكيهات الخط في سكربت الصفحة عناصرَ حرفية لقائمة «الخط». بلا هذه القراءة يُرفض التغيير بـ
«تعذّر قراءة بوكيهات الخط» (لقطة مصغّرة من صفحة حقيقية، بلا أي بيانات عميل).

    python tests/test_edit_bouquets.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import xm_web  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  FAIL  " + label + (("  (%s)" % extra) if extra else ""))


FORM = """<form action="./user_reseller.php?id=7" method="POST" id="user_form">
<input type="hidden" name="edit" value="7" />
<input type="text" name="username" value="111122223333">
<input type="text" name="password" value="999988887777">
<select name="package"><option value="">Select Package</option><option value="13">تجربة</option></select>
<select multiple id="listbox-in" size="10"></select>
<input type="hidden" name="selected_bouquets" id="selected_bouquets" value="" />
<input type="hidden" name="submit_user" value="1" />
</form>"""

# كما في الصفحة الحقيقية: فرع الباقة المختارة يملأ من rData (لا يُقرأ)، وفرع «بلا باقة» (وضع التعديل) يكتب الأرقام حرفيًا
SCRIPT = """<script>
$.getJSON("./user_reseller.php?action=get_package&package_id=" + $("#package").val() + "&user_id=7", function(rData) {
    $(rData.bouquets).each(function(rIndex) {
        $("#listbox-in").append($('<option>', {
            value: rData.bouquets[rIndex].id,
            text: rData.bouquets[rIndex].bouquet_name
        }));
    });
});
// Edit mode - need to load package bouquets properly
//Via PackID: 13
                    $("#listbox-in").append($('<option>', {
                        value: 1,
                        text: 'قنوات',
                        'data-channels': 9813
                    }));
                                        $("#listbox-in").append($('<option>', {
                        value: 3,
                        text: 'مسلسلات',
                        'data-series': 10448                                }));
</script>"""


def main():
    page = FORM + SCRIPT
    check("script bouquets: literal ids only (not rData.bouquets[i].id)", xm_web.PanelWebSession._edit_script_bouquets(page) == [1, 3])
    check("no literal appends → none", xm_web.PanelWebSession._edit_script_bouquets(FORM) == [])
    s = xm_web.PanelWebSession({"id": "g", "user": "u", "password": "p", "panel_base": "http://x", "host": "http://h"}, tempfile.mkdtemp())
    picked = s._pick_edit_form(page, "7", "111122223333")
    pairs = xm_web.serialize_form(picked["form"]["fields"])
    pairs = s._fill_bouquets(picked, s._set_pair(pairs, "username", "555566667777"), page, "")
    d = dict(pairs)
    check("selected_bouquets filled from the edit script, JSON list", d.get("selected_bouquets") == "[1, 3]", str(d.get("selected_bouquets")))
    check("package stays blank (no paid extension) and the edit marker is kept", d.get("package") == "" and d.get("edit") == "7")
    try:
        s._fill_bouquets(picked, xm_web.serialize_form(picked["form"]["fields"]), FORM, "")
        check("a page with no readable bouquets is still refused (never wipes channels)", False)
    except xm_web.EditUnsupported:
        check("a page with no readable bouquets is still refused (never wipes channels)", True)
    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


main()
