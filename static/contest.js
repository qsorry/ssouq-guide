/* بطاقة «توقّع النتيجة واربح» في صفحة المباراة (‏#predict[data-m]).
   الحالة من /api/contest بلا كاش، فالصفحة نفسها تبقى مخزَّنة: مفتوحة ← النموذج والعدّاد،
   مقفلة ← ماذا توقّع الناس وبصمة التوقّعات، مفروزة ← الفائز وفيديو الفرز (contest-draw.js).
   التسجيل برسالة واتساب: النتيجة والاسم ← رمزٌ (‏/api/contest/start) ← واتساب برسالةٍ جاهزة
   ← الصفحة تنتظر الرمز (‏/api/contest/ticket) حتى يُسجَّل برقم مرسل الرسالة. والرمز محفوظ في
   المتصفح، فمن رجع من واتساب أو أغلق الصفحة يجد حاله كما تركها. */
(function () {
  "use strict";
  var box = document.getElementById("predict");
  if (!box) return;
  var EID = box.getAttribute("data-m"), body = box.querySelector(".pbody");
  var KEY = "ssouq_predict_" + EID, TKEY = KEY + "_t",
      RULES = box.getAttribute("data-rules") || "/predict#rules";              // شروط المسابقة
  var data = null, skew = 0, tick = null, again = null, player = null, poll = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  // النتيجة رقمان منفصلان: صاحب الأرض يمينًا بجانب اسمه، كما في صفحات البطولة
  function score(h, a) { return '<span class="pscore"><b>' + h + "</b><i>-</i><b>" + a + "</b></span>"; }
  function named(h, a) { return esc(data.match.home) + " " + score(h, a) + " " + esc(data.match.away); }
  function get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } }
  function put(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function mine() { return get(KEY); }
  function keep(v) { put(KEY, v); }
  function ticket() { return get(TKEY); }
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function crest(u) { return u ? '<img src="' + esc(u) + '" alt="" width="44" height="44">' : '<i class="crest"></i>'; }
  function crests(root) {                            // شعارٌ تعذّر تحميله يصير دائرةً فارغة لا أيقونةً مكسورة
    root.querySelectorAll(".pteam img").forEach(function (im) {
      var swap = function () { var i = document.createElement("i"); i.className = "crest"; im.replaceWith(i); };
      if (im.complete && !im.naturalWidth) swap(); else im.addEventListener("error", swap);
    });
  }
  // 0 · توقّعٌ واحد · توقّعان · 3-10 توقّعات · 11+ توقّعًا
  function preds(n) {
    return n === 1 ? "توقّعٌ واحد" : n === 2 ? "توقّعان" : num(n) + (n % 100 >= 3 && n % 100 <= 10 ? " توقّعات" : " توقّعًا");
  }

  function load() {
    clearTimeout(again);
    return fetch("/api/contest?m=" + encodeURIComponent(EID), {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        data = d; skew = (d.now || Date.now() / 1000) * 1000 - Date.now();
        render();
      })
      .catch(function () {
        body.innerHTML = '<p class="sub">تعذّر تحميل المسابقة الآن. حدّث الصفحة بعد قليل.</p>';
        again = setTimeout(load, 30000);
      });
  }

  function render() {
    clearInterval(tick);
    clearTimeout(poll);
    if (!data || !data.ok || data.state === "off") { box.hidden = true; return; }
    box.hidden = false;
    if (data.state === "open") return open();
    if (data.state === "done") return done();
    closed();
  }

  // ---------- مفتوحة ----------
  function countdown() {
    var el = body.querySelector(".cd");
    if (!el) return;
    var left = Math.floor(((data.closes || data.match.ts) * 1000 - (Date.now() + skew)) / 1000);   // الإقفال: الصافرة ودقائق المدير
    if (left <= 0) { clearInterval(tick); load(); return; }
    var d = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
    var hms = [h, m, s].map(function (x) { return (x < 10 ? "0" : "") + x; }).join(":");
    var days = d === 1 ? "يوم" : d === 2 ? "يومين" : d <= 10 ? d + " أيام" : d + " يومًا";
    el.innerHTML = (d ? days + " و" : "") + '<span class="hms">' + hms + "</span>";
  }

  function open() {
    var me = mine(), tk = ticket();
    var head = '<p class="pcount">' + (data.count ? "<b>" + preds(data.count) + "</b> حتى الآن" : "كن أول من يتوقّع") +
      ' · تُقفل التوقّعات بعد <b class="cd">…</b></p>' +
      '<p class="pcount">' + (data.mode === "outcome" ? "يفوز من يصيب النتيجة بالضبط، فإن لم يُصبها أحد فمن يصيب الفائز"
                                                      : "يفوز من يصيب النتيجة بالضبط فقط") + "</p>";
    if (me) body.innerHTML = head + mineHtml(me) + share();
    else if (tk) waiting(head, tk);
    else if (data.reg === false) body.innerHTML = head + '<p class="pmsg err">التسجيل عبر واتساب متوقّفٌ الآن. حاول بعد قليل.</p>';
    else {
      var m = data.match;
      body.innerHTML = head +
        '<form class="pform" novalidate>' +
        '<div class="pteams">' +
        '<div class="pteam">' + crest(m.home_logo) + "<b>" + esc(m.home) + "</b>" + stepper("h", m.home) + "</div>" +
        '<span class="pvs">-</span>' +
        '<div class="pteam">' + crest(m.away_logo) + "<b>" + esc(m.away) + "</b>" + stepper("a", m.away) + "</div>" +
        "</div>" +
        '<label class="pl" for="p-name">اسمك</label>' +
        '<input id="p-name" name="name" type="text" maxlength="30" autocomplete="given-name" required>' +
        '<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">' +
        '<label class="chk"><input type="checkbox" name="agree"><span>قرأت <a class="link" href="' + RULES +
        '" target="_blank" rel="noopener">شروط المسابقة</a> وأوافق عليها</span></label>' +
        '<label class="chk"><input type="checkbox" name="promo"><span>أرسلوا لي عروض الاشتراكات على واتساب (اختياري)</span></label>' +
        '<button class="btn wa" type="submit">' + WA + "أرسل توقّعي على واتساب</button>" +
        '<small class="hint">ينفتح واتساب برسالةٍ جاهزة فيها رمز توقّعك؛ أرسلها كما هي، ويُسجَّل توقّعك برقمك الذي أرسلت منه.</small>' +
        '<p class="pmsg" role="status" aria-live="polite"></p>' +
        "</form>";
      wire(body.querySelector("form"));
      crests(body);
    }
    countdown();
    tick = setInterval(countdown, 1000);
  }

  var WA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 3.5A11 11 0 0 0 3.4 17.3L2 22l4.8-1.3A11 11 0 1 0 20.5 3.5zM12 20a8 8 0 0 1-4.2-1.2l-.3-.2-2.8.8.8-2.7-.2-.3A8 8 0 1 1 12 20zm4.4-6c-.2-.1-1.4-.7-1.7-.8s-.4-.1-.6.1-.6.8-.8 1-.3.2-.5.1a6.6 6.6 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3a.4.4 0 0 0 0-.4l-.8-1.9c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.8 11.9 11.9 0 0 0 4.6 4c1.7.7 2.4.8 3.2.7a2.8 2.8 0 0 0 1.8-1.3 2.3 2.3 0 0 0 .2-1.3c-.1-.1-.3-.2-.5-.3z"/></svg>';

  function mineHtml(me) {
    return '<div class="pmine">' + (me.h == null
      ? "رقمك سجّل توقّعه لهذه المباراة من قبل" + (me.n ? " — رقم توقّعك <b>" + me.n + "</b>" : "") + ". والتوقّع لا يُعدَّل."
      : "سجّلت توقّعك" + (me.phone ? ' من رقم <span class="ph">' + esc(me.phone) + "</span>" : "") + ": " + named(me.h, me.a) +
        " — رقم توقّعك <b>" + me.n + "</b>.<br>الفرز آليٌّ بعد صافرة النهاية، ونبلّغك على واتساب إن فزت.") + "</div>";
  }

  // الرمز أُخذ والرسالة لم تصل بعد: زرّ واتساب، وانتظارٌ حتى يُسجَّل
  function waiting(head, tk) {
    body.innerHTML = head + '<div class="pwait"><b>آخر خطوة: أرسل الرسالة من واتساب</b>' +
      "<p>توقّعك: " + named(tk.h, tk.a) + ' · رمزه <code dir="ltr">' + esc(tk.code) + "</code></p>" +
      '<a class="btn wa" href="' + esc(tk.url) + '" target="_blank" rel="noopener">' + WA + "افتح واتساب وأرسل الرسالة</a>" +
      '<p class="pstat"><i class="spin" aria-hidden="true"></i><span>بانتظار رسالتك… أرسلها كما هي قبل إقفال التوقّعات، ' +
      "ويظهر هنا تأكيد التسجيل.</span></p>" +
      '<button class="plink" type="button" data-a="redo">غيّر توقّعي</button></div>';
    body.querySelector('[data-a="redo"]').addEventListener("click", function () { put(TKEY, null); render(); });
    check(tk);
  }

  function check(tk) {
    clearTimeout(poll);
    fetch("/api/contest/ticket?m=" + encodeURIComponent(EID) + "&c=" + encodeURIComponent(tk.code), {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (t) {
        if (ticket() === null || ticket().code !== tk.code) return;    // غيّر توقّعه أثناء الانتظار
        if (t.state === "pending") { poll = setTimeout(function () { check(tk); }, document.hidden ? 15000 : 3000); return; }
        put(TKEY, null);
        if (t.state === "done") { keep({n: t.n, h: t.h, a: t.a, phone: t.phone || ""}); data.count = (data.count || 0) + 1; }
        else if (t.state === "dup") keep({n: t.n, phone: t.phone || ""});
        else if (t.state === "late") put(KEY + "_note", "وصلت رسالتك بعد إقفال التوقّعات، فلم يُحتسب التوقّع.");
        load();
      })
      .catch(function () { poll = setTimeout(function () { check(tk); }, 8000); });
  }

  // من رجع من واتساب: يُسأل عن الرمز فورًا لا بعد مهلة
  document.addEventListener("visibilitychange", function () {
    var tk = ticket();
    if (!document.hidden && tk && data && (data.state === "open" || data.state === "closed")) check(tk);
  });

  function stepper(side, team) {
    return '<div class="stepper" data-side="' + side + '">' +
      '<button type="button" data-d="1" aria-label="هدف إضافي لـ' + esc(team) + '">+</button>' +
      '<output aria-label="أهداف ' + esc(team) + '">0</output>' +
      '<button type="button" data-d="-1" aria-label="هدف أقل لـ' + esc(team) + '">−</button></div>';
  }

  function share() {
    var text = "توقّعت نتيجة مباراة " + data.match.home + " و" + data.match.away + " في مسابقة سمارت سوق 🎁\n" +
      "توقّع أنت واربح " + data.prize + ": " + location.origin + location.pathname + "#predict";
    return '<a class="btn ghost pshare" href="https://wa.me/?text=' + encodeURIComponent(text) +
      '" target="_blank" rel="noopener">شارك المسابقة مع أصحابك</a>';
  }

  function wire(form) {
    var goals = {h: 0, a: 0}, msg = form.querySelector(".pmsg"), busy = false;
    form.querySelectorAll(".stepper").forEach(function (st) {
      var side = st.getAttribute("data-side"), out = st.querySelector("output");
      st.addEventListener("click", function (e) {
        var b = e.target.closest("button");
        if (!b) return;
        goals[side] = Math.max(0, Math.min(15, goals[side] + Number(b.getAttribute("data-d"))));
        out.textContent = goals[side];
      });
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (busy) return;
      form.querySelectorAll(".bad").forEach(function (x) { x.classList.remove("bad"); });
      var f = form.elements;
      var req = {m: EID, h: goals.h, a: goals.a, name: f.name.value, agree: f.agree.checked, promo: f.promo.checked,
                 website: f.website.value};
      if (!req.name.trim()) return fail("اكتب اسمك", "name");
      if (!req.agree) return fail("وافق على شروط المسابقة أولًا", "agree");
      busy = true; msg.className = "pmsg"; msg.textContent = "نجهّز رسالتك…";
      fetch("/api/contest/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(req)})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          busy = false;
          if (d.ok && d.url) {
            var tk = {code: d.code, h: d.h, a: d.a, url: d.url};
            put(TKEY, tk);
            window.open(d.url, "_blank", "noopener");          // وإن منعه المتصفح فزرّ واتساب في الخطوة التالية
            return open();
          }
          if (d.state && d.state !== "open") return load();
          fail(d.error || "تعذّر الإرسال", d.field);
        })
        .catch(function () { busy = false; fail("تعذّر الإرسال، تحقّق من الاتصال وأعد المحاولة"); });
    });
    function fail(text, field) {
      msg.className = "pmsg err"; msg.textContent = text;
      var el = field && form.elements[field];
      if (el && el.focus) { if (el.classList) el.classList.add("bad"); el.focus(); }
    }
  }

  // ---------- مقفلة / بانتظار الفرز / ملغاة ----------
  function bars(dist) {
    var n = dist.n || 1, rows = [[data.match.home, dist.home], ["التعادل", dist.draw], [data.match.away, dist.away]];
    var out = rows.map(function (r) {
      var w = Math.round(100 * r[1] / n);
      return '<div class="pbar"><span>' + (r[0] === "التعادل" ? "التعادل" : "فوز " + esc(r[0])) + '</span><i style="width:' + w +
        '%"></i><b>' + w + "%</b></div>";
    }).join("");
    var top = (dist.top || []).map(function (t) {
      return "<li>" + score(t.h, t.a) + " <small>" + num(t.c) + "</small></li>";
    }).join("");
    return '<h3>ماذا توقّع الناس؟</h3><div class="pbars">' + out + "</div>" +
      (top ? '<h3>أكثر النتائج توقّعًا</h3><ul class="ptop">' + top + "</ul>" : "");
  }

  function fp() {
    return data.fp ? '<details class="pfp"><summary>بصمة التوقّعات</summary><code>' + esc(data.fp) + "</code>" +
      "<p>تُحسب من قائمة التوقّعات لحظة الإقفال، ومنها ومن النتيجة النهائية يخرج رقم القرعة — فلا تتغيّر " +
      "القائمة بعد الإقفال، ولا يعرف أحدٌ الفائز قبل صافرة النهاية.</p></details>" : "";
  }

  function closed() {
    var me = mine(), tk = ticket(), note = get(KEY + "_note"), html = '<p><b>' + esc(data.msg) + "</b></p>";
    if (note) html += '<p class="pmsg err">' + esc(note) + "</p>";
    if (tk && !me && data.state === "closed") {
      html += '<p class="pstat"><i class="spin" aria-hidden="true"></i><span>إن أرسلت رسالة توقّعك قبل الصافرة فتأكيدها ' +
        "يظهر هنا خلال دقائق.</span></p>";
      check(tk);
    } else if (tk && data.state !== "closed") put(TKEY, null);
    if (data.state !== "hold" && data.state !== "void") {
      html += '<p class="pcount"><b>' + preds(data.count) + "</b>" +
        (data.state === "pending" ? " · النتيجة تُفرز الآن" : " · الفرز آليٌّ بعد صافرة النهاية") + "</p>";
    }
    if (me) html += mineHtml(me);
    if (data.dist && data.dist.n) html += bars(data.dist);
    html += fp();
    body.innerHTML = html;
    if (data.state !== "void") again = setTimeout(load, data.state === "pending" ? 20000 : 60000);
  }

  // ---------- مفروزة ----------
  function done() {
    var d = data.draw, me = mine(), picks = d.picks || [];
    var tier = {exact: "أصاب النتيجة بالضبط", outcome: "أصاب الفائز"};
    var html = "";
    if (picks.length) {
      html += '<div class="pwin"><span class="eyebrow">' + (picks.length > 1 ? "الفائزون" : "الفائز") + "</span>" +
        picks.map(function (p) {
          return '<div class="wrow"><b>' + esc(p.name) + '</b><span class="ph">' + esc(p.phone) + "</span>" +
            "<small>توقّع " + named(p.h, p.a) + " · " + tier[p.tier] + " · رقم توقّعه " + p.n + "</small></div>";
        }).join("") + "</div>";
    } else {
      html += "<p><b>" + (d.mode === "outcome" ? "لم يُصب أحدٌ النتيجة ولا الفائز" : "لم يُصب أحدٌ النتيجة بالضبط") +
        "، فلا فائز في هذه المباراة.</b></p>";
    }
    html += '<p class="pcount">النتيجة النهائية: <b>' + named(d.score[0], d.score[1]) + "</b> · " + preds(d.count) +
      " · أصاب النتيجة بالضبط " + num(d.exact) + "</p>";
    if (me && me.n) {
      var won = picks.some(function (p) { return p.n === me.n; });
      html += '<div class="pmine">' + (won ? "🎉 مبروك! أنت الفائز — تواصلنا معك على واتساب." :
        (me.h == null ? "" : "توقّعك كان " + named(me.h, me.a) + ". ") + "حظًا أوفر في المباراة القادمة!") + "</div>";
    }
    html += '<button class="btn go pplay" type="button"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>' +
      "شاهد كيف تم الفرز</button>";
    if (picks.length) {
      var p = picks[0];
      html += '<details class="pfp"><summary>الفرز بالأرقام</summary>' +
        "<p>بصمة التوقّعات عند الإقفال:</p><code>" + esc(d.fp) + "</code>" +
        "<p>رقم القرعة = SHA-256(البصمة | " + esc(EID) + " | " + d.score[0] + "-" + d.score[1] + "):</p><code>" + esc(d.seed) + "</code>" +
        "<p>رقم الفائز = أول 12 خانة من SHA-256(رقم القرعة:0) = <b>" + num(p.num) + "</b>، وعلى " + num(p.size) +
        " مؤهّلًا يبقى <b>" + p.idx + "</b> — فالفائز المؤهّل رقم " + (p.idx + 1) + " بترتيب التسجيل.</p></details>";
    }
    body.innerHTML = html;
    body.querySelector(".pplay").addEventListener("click", play);
    if (location.hash === "#draw") play();
  }

  // ---------- فيديو الفرز ----------
  function script(src) {
    return new Promise(function (ok, no) {
      if (window.SSDraw) return ok();
      var s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = no;
      document.head.appendChild(s);
    });
  }

  function play() {
    var v = box.getAttribute("data-draw") || "";
    var wrap = document.createElement("div");
    wrap.className = "pvid";
    wrap.innerHTML = '<canvas width="1080" height="1920" role="img" aria-label="فيديو يشرح كيف تم الفرز"></canvas>' +
      '<div class="bar"><button class="btn buy" type="button" data-a="again">إعادة</button>' +
      '<button class="btn ghost" type="button" data-a="save" hidden>تنزيل الفيديو</button>' +
      '<button class="btn ghost" type="button" data-a="close">إغلاق</button></div><p class="pmsg"></p>';
    document.body.appendChild(wrap);
    var canvas = wrap.querySelector("canvas"), msg = wrap.querySelector(".pmsg"), rec = false;
    function close() { if (player) player.stop(); player = null; wrap.remove(); document.removeEventListener("keydown", key); }
    function key(e) { if (e.key === "Escape" && !rec) close(); }
    document.addEventListener("keydown", key);
    wrap.addEventListener("click", function (e) {
      if (rec) return;                                 // التسجيل لا يُقطع
      var a = e.target.closest("[data-a]");
      if (e.target === wrap) return close();
      if (!a) return;
      var act = a.getAttribute("data-a");
      if (act === "close") return close();
      if (act === "again" && player) return player.play();
      if (act === "save") {
        rec = true; msg.textContent = "نسجّل الفيديو… أبقِ الصفحة مفتوحة";
        if (player) player.stop();
        window.SSDraw.record(report(), {canvas: canvas, onProgress: function (p) {
          msg.textContent = "نسجّل الفيديو… " + Math.round(p * 100) + "%";
        }}).then(function (out) {
          rec = false;
          window.SSDraw.save(out, "فرز-" + data.match.home + "-" + data.match.away);
          msg.textContent = "نُزّل الفيديو.";
          player = window.SSDraw.play(canvas, report());
        }).catch(function (err) {
          rec = false; msg.textContent = (err && err.message) || "تعذّر التسجيل";
          player = window.SSDraw.play(canvas, report());
        });
      }
    });
    script("/static/contest-draw.js" + (v ? "?v=" + v : "")).then(function () {
      if (!wrap.isConnected) return;
      wrap.querySelector('[data-a="save"]').hidden = !window.SSDraw.canRecord();
      player = window.SSDraw.play(canvas, report());
    }).catch(function () { msg.textContent = "تعذّر تحميل الفيديو"; });
  }

  function report() {
    return {match: data.match, when: data.when, prize: data.prize, eid: EID, draw: data.draw,
            site: location.host + location.pathname};
  }

  load();
})();
