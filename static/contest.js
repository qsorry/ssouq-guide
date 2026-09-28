/* بطاقة «توقّع النتيجة واربح» في صفحة المباراة (‏#predict[data-m]).
   الحالة من /api/contest بلا كاش، فالصفحة نفسها تبقى مخزَّنة: مفتوحة ← النموذج والعدّاد،
   مقفلة ← ماذا توقّع الناس وبصمة التوقّعات، مفروزة ← الفائز وفيديو الفرز (contest-draw.js). */
(function () {
  "use strict";
  var box = document.getElementById("predict");
  if (!box) return;
  var EID = box.getAttribute("data-m"), body = box.querySelector(".pbody");
  var KEY = "ssouq_predict_" + EID, RULES = "/nations-league/predict#rules";
  var data = null, skew = 0, tick = null, again = null, player = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  // النتيجة رقمان منفصلان: صاحب الأرض يمينًا بجانب اسمه، كما في صفحات البطولة
  function score(h, a) { return '<span class="pscore"><b>' + h + "</b><i>-</i><b>" + a + "</b></span>"; }
  function named(h, a) { return esc(data.match.home) + " " + score(h, a) + " " + esc(data.match.away); }
  function mine() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  function keep(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) {} }
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
    var left = Math.floor((data.match.ts * 1000 - (Date.now() + skew)) / 1000);
    if (left <= 0) { clearInterval(tick); load(); return; }
    var d = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
    var hms = [h, m, s].map(function (x) { return (x < 10 ? "0" : "") + x; }).join(":");
    var days = d === 1 ? "يوم" : d === 2 ? "يومين" : d <= 10 ? d + " أيام" : d + " يومًا";
    el.innerHTML = (d ? days + " و" : "") + '<span class="hms">' + hms + "</span>";
  }

  function open() {
    var me = mine();
    var head = '<p class="pcount">' + (data.count ? "<b>" + preds(data.count) + "</b> حتى الآن" : "كن أول من يتوقّع") +
      ' · تُقفل التوقّعات بعد <b class="cd">…</b></p>';
    if (me) {
      body.innerHTML = head + '<div class="pmine">سجّلت توقّعك: ' + named(me.h, me.a) + " — رقم توقّعك <b>" + me.n +
        "</b>.<br>الفرز آليٌّ بعد صافرة النهاية، ونبلّغك على واتساب إن فزت." + share() + "</div>";
    } else {
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
        '<label class="pl" for="p-phone">رقم واتساب</label>' +
        '<input id="p-phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="05xxxxxxxx" required>' +
        '<small class="hint">نبلّغ الفائز على هذا الرقم، والجائزة لا تُسلَّم إلا له. ورقمٌ من خارج السعودية يُكتب بمفتاح دولته.</small>' +
        '<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">' +
        '<label class="chk"><input type="checkbox" name="agree"><span>قرأت <a class="link" href="' + RULES +
        '" target="_blank" rel="noopener">شروط المسابقة</a> وأوافق عليها</span></label>' +
        '<label class="chk"><input type="checkbox" name="promo"><span>أرسلوا لي عروض الاشتراكات على واتساب (اختياري)</span></label>' +
        '<button class="btn buy" type="submit">أرسل توقّعي</button>' +
        '<p class="pmsg" role="status" aria-live="polite"></p>' +
        "</form>";
      wire(body.querySelector("form"));
      crests(body);
    }
    countdown();
    tick = setInterval(countdown, 1000);
  }

  function stepper(side, team) {
    return '<div class="stepper" data-side="' + side + '">' +
      '<button type="button" data-d="1" aria-label="هدف إضافي لـ' + esc(team) + '">+</button>' +
      '<output aria-label="أهداف ' + esc(team) + '">0</output>' +
      '<button type="button" data-d="-1" aria-label="هدف أقل لـ' + esc(team) + '">−</button></div>';
  }

  function share() {
    var text = "توقّعت نتيجة مباراة " + data.match.home + " و" + data.match.away + " في مسابقة سمارت سوق 🎁\n" +
      "توقّع أنت واربح " + data.prize + ": " + location.origin + location.pathname + "#predict";
    return '<a class="btn wa" href="https://wa.me/?text=' + encodeURIComponent(text) +
      '" target="_blank" rel="noopener">شارك المسابقة على واتساب</a>';
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
      var req = {m: EID, h: goals.h, a: goals.a, name: f.name.value, phone: f.phone.value,
                 agree: f.agree.checked, promo: f.promo.checked, website: f.website.value};
      if (!req.name.trim()) return fail("اكتب اسمك", "name");
      if (!req.phone.trim()) return fail("اكتب رقم واتساب", "phone");
      if (!req.agree) return fail("وافق على شروط المسابقة أولًا", "agree");
      busy = true; msg.className = "pmsg"; msg.textContent = "نرسل توقّعك…";
      fetch("/api/contest/enter", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(req)})
        .then(function (r) { return r.json().then(function (d) { return [r.status, d]; }); })
        .then(function (x) {
          busy = false;
          var d = x[1];
          if (d.ok) {
            keep({n: d.n, h: d.h, a: d.a});
            data.count = d.count || data.count + 1;
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
    var me = mine(), html = '<p><b>' + esc(data.msg) + "</b></p>";
    if (data.state !== "hold" && data.state !== "void") {
      html += '<p class="pcount"><b>' + preds(data.count) + "</b>" +
        (data.state === "pending" ? " · النتيجة تُفرز الآن" : " · الفرز آليٌّ بعد صافرة النهاية") + "</p>";
    }
    if (me) html += '<div class="pmine">توقّعك: ' + named(me.h, me.a) + " — رقم توقّعك <b>" + me.n + "</b></div>";
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
      html += '<p><b>لم يُصب أحدٌ النتيجة ولا الفائز، فلا فائز في هذه المباراة.</b></p>';
    }
    html += '<p class="pcount">النتيجة النهائية: <b>' + named(d.score[0], d.score[1]) + "</b> · " + preds(d.count) +
      " · أصاب النتيجة بالضبط " + num(d.exact) + "</p>";
    if (me) {
      var won = picks.some(function (p) { return p.n === me.n; });
      html += '<div class="pmine">' + (won ? "🎉 مبروك! أنت الفائز — تواصلنا معك على واتساب." :
        "توقّعك كان " + named(me.h, me.a) + ". حظًا أوفر في المباراة القادمة!") + "</div>";
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
