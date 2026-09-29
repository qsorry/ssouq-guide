/* فيديو «كيف تم الفرز» لمسابقة التوقّعات (contest.py).
   يُرسم على canvas بمقاس القصص (1080×1920) من تقرير الفرز العام في /api/contest (draw)، فيُعرض
   في صفحة المباراة ويُسجَّل ملفَّ فيديو من المتصفح نفسه (MediaRecorder): MP4 حيث يدعمه
   المتصفح (كروم وسفاري)، وإلا WebM. لا مكتبات ولا خادم فيديو.

   المشاهد: المباراة والجائزة ← الإقفال (العدد والبصمة) ← النتيجة النهائية ← التصفية (من أصاب)
   ← القرعة (رقمها، باقي القسمة، والدولاب يقف على الفائز) ← الفائز.

   SSDraw.play(canvas, report)         يعرضه في canvas ← {ready, play(), stop(), total}
   SSDraw.record(report, {canvas, onProgress, bitrate}) ← Promise<{blob, type, ext}> — bitrate افتراضًا 8 ميغابت
   SSDraw.prepare(canvas, report, {scale}) ← Promise<{frame(t), total}> — إطارٌ بعينه (للاختبار ولتصدير الإطارات)
   SSDraw.canRecord() · SSDraw.save(out, name) */
(function () {
  "use strict";
  var W = 1080, H = 1920, FPS = 30;
  var FONT = '"IBM Plex Sans Arabic", "Amazon-Ember", Tahoma, "DejaVu Sans", Arial, sans-serif';
  var MONO = '"IBM Plex Mono", ui-monospace, Menlo, Consolas, "DejaVu Sans Mono", monospace';
  var C = {bg1: "#012E45", bg2: "#004D73", gold: "#F0A12B", gold2: "#FFD79A", goldInk: "#2A1D04", ink: "#FFFFFF",
           mute: "#BFD8E6", line: "rgba(255,255,255,.18)", card: "rgba(255,255,255,.07)", dim: "rgba(255,255,255,.12)",
           green: "#34D399"};
  // MP4 بـ H.264 وحده (كروم وسفاري) — فهو ما يقبله الآيفون وواتساب؛ و«video/mp4» بلا ترميز يعطي
  // في كروميوم VP9 داخل MP4 لا يعمل هناك، فيُقبل فقط حيث لا VP9 أصلًا (سفاري)، وإلا فـ WebM.
  var TYPES = ["video/mp4;codecs=avc1.42E01E", "video/mp4;codecs=avc1", "video/mp4",
               "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];

  // ---------- أدوات ----------
  function clamp(x, a, b) { return Math.max(a === undefined ? 0 : a, Math.min(b === undefined ? 1 : b, x)); }
  function prog(l, a, b) { return clamp((l - a) / (b - a)); }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeOut4(t) { return 1 - Math.pow(1 - t, 4); }
  function easeInOut(t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function back(t) { var c = 1.7; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); }
  function mod(k, n) { return ((k % n) + n) % n; }
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function rng(seed) {                                   // mulberry32: عشوائيةٌ ثابتة من بذرة
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // الجمع العربي: 1 توقّع واحد · 2 توقّعان · 3-10 توقّعات · 11+ توقّعًا
  function plural(n, f) { return n === 1 ? f[0] : n === 2 ? f[1] : (n % 100 >= 3 && n % 100 <= 10) ? f[2] : f[3]; }
  var PRED = ["توقّع واحد", "توقّعان", "توقّعات", "توقّعًا"];

  function text(ctx, s, x, y, o) {
    o = o || {};
    var size = o.size || 48, weight = o.weight || 700, font = o.font || FONT;
    ctx.save();
    ctx.direction = o.dir || "rtl";
    ctx.textAlign = o.align || "center";
    ctx.textBaseline = "middle";
    ctx.font = weight + " " + size + "px " + font;
    if (o.max) {                                       // يصغر الخط حتى يتّسع السطر
      while (size > 18 && ctx.measureText(s).width > o.max) {
        size -= 2;
        ctx.font = weight + " " + size + "px " + font;
      }
    }
    if (o.alpha !== undefined) ctx.globalAlpha *= o.alpha;
    ctx.fillStyle = o.color || C.ink;
    ctx.fillText(s, x, y);
    ctx.restore();
  }

  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function pill(ctx, s, x, y, o) {
    o = o || {};
    var size = o.size || 40;
    ctx.save();
    ctx.font = "700 " + size + "px " + FONT;
    ctx.direction = "rtl";
    var w = Math.min(ctx.measureText(s).width + size * 1.4, o.max || W - 120), h = size * 1.9;
    rrect(ctx, x - w / 2, y - h / 2, w, h, h / 2);
    ctx.fillStyle = o.bg || C.gold;
    ctx.fill();
    ctx.restore();
    text(ctx, s, x, y + 2, {size: size, color: o.color || C.goldInk, max: w - size});
  }

  function crest(ctx, im, x, y, r, name, scale) {
    scale = scale === undefined ? 1 : scale;
    if (scale <= 0) return;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.beginPath();
    ctx.arc(0, 0, r + 8, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,.10)";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = "#F4F8FB";
    ctx.fill();
    if (im) {
      ctx.save();
      ctx.clip();
      ctx.drawImage(im, -r * 0.86, -r * 0.86, r * 1.72, r * 1.72);
      ctx.restore();
    } else {
      text(ctx, String(name || "?").trim().charAt(0), 0, 4, {size: r, color: C.bg2});
    }
    ctx.restore();
  }

  // ---------- التقرير ----------
  function norm(rep) {
    var d = rep.draw || {}, m = rep.match || {};
    var big = function (u) { return u ? String(u).replace(/&w=\d+&h=\d+/, "&w=240&h=240") : ""; };
    var picks = d.picks || [];
    return {
      home: m.home || "", away: m.away || "", homeLogo: big(m.home_logo), awayLogo: big(m.away_logo),
      stage: m.stage || "", when: rep.when || "", prize: rep.prize || "", eid: rep.eid || "",
      count: d.count || 0, score: d.score || [0, 0], fp: d.fp || "", seed: d.seed || "",
      exact: d.exact || 0, outcome: d.outcome || 0, picks: picks, pool: d.pool || [], poolFrom: d.pool_from || 0,
      fallback: !d.exact && picks.length > 0, site: rep.site || "guide.ssouq.com", sample: !!rep.sample,
      nobody: d.mode === "outcome" ? "لم يُصب أحدٌ النتيجة ولا الفائز" : "لم يُصب أحدٌ النتيجة بالضبط",
      seedNum: parseInt(String(d.seed || "5eed").slice(0, 8), 16) || 1
    };
  }

  function plan(r) {
    var S = [], t = 0;
    function add(id, d) { S.push({id: id, t0: t, d: d}); t += d; }
    add("intro", 2.4);
    add("lock", 2.9);
    add("score", 2.3);
    add("filter", r.fallback ? 4.4 : 3.2);
    if (r.picks.length) add("draw", 7.0);                // ويقف الدولاب على الفائز ثانيةً كاملة
    add("win", 4.0);
    return {S: S, total: t, steps: r.picks.length ? 4 : 3};
  }

  // ---------- الخلفية والإطار ----------
  function background(ctx, t) {
    var g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, C.bg2);
    g.addColorStop(1, C.bg1);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    var glow = function (x, y, r, col) {
      var rg = ctx.createRadialGradient(x, y, 0, x, y, r);
      rg.addColorStop(0, col);
      rg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = rg;
      ctx.fillRect(x - r, y - r, r * 2, r * 2);
    };
    glow(W * .82 + Math.sin(t * .6) * 40, 260 + Math.cos(t * .5) * 30, 620, "rgba(240,161,43,.16)");
    glow(W * .15 + Math.cos(t * .4) * 50, H * .78 + Math.sin(t * .45) * 40, 720, "rgba(99,184,226,.14)");
    ctx.save();                                        // ملعبٌ خافت: خط المنتصف ودائرته
    ctx.strokeStyle = "rgba(255,255,255,.045)";
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.arc(W / 2, H / 2, 300, 0, Math.PI * 2);
    ctx.moveTo(0, H / 2);
    ctx.lineTo(W, H / 2);
    ctx.stroke();
    ctx.restore();
  }

  function chrome(ctx, r, P, sc, t) {
    text(ctx, "سمارت سوق", W - 80, 128, {size: 46, align: "right"});
    text(ctx, "مسابقة توقّع النتيجة", W - 80, 186, {size: 32, weight: 500, align: "right", color: C.gold2});
    var step = {lock: 1, score: 2, filter: 3, draw: 4}[sc.id];
    if (step) text(ctx, "الخطوة " + step + " من " + P.steps, 80, 150, {size: 34, weight: 500, align: "left", color: C.mute});
    var y = 1790, x0 = 80, w = W - 160, p = clamp(t / P.total);
    ctx.save();
    rrect(ctx, x0, y, w, 8, 4);
    ctx.fillStyle = C.dim;
    ctx.fill();
    rrect(ctx, x0 + w * (1 - p), y, w * p, 8, 4);        // يمتلئ من اليمين
    ctx.fillStyle = C.gold;
    ctx.fill();
    ctx.restore();
    text(ctx, r.site, W / 2, 1860, {size: 30, weight: 500, dir: "ltr", color: C.mute, max: W - 160});
    if (r.sample) pill(ctx, "عيّنة تجريبية ببيانات وهمية", W / 2, 290, {size: 34, bg: "#DC2626", color: "#FFFFFF"});
  }

  function title(ctx, s, l, y) {
    var a = easeOut(prog(l, 0, .45));
    text(ctx, s, W / 2, (y || 450) + (1 - a) * 30, {size: 84, alpha: a, max: W - 160});
  }

  // ---------- المشاهد ----------
  var SCENES = {
    intro: function (ctx, r, l, im) {
      var a = easeOut(prog(l, 0, .5));
      text(ctx, "فرز مسابقة", W / 2, 470 - (1 - a) * 30, {size: 60, color: C.gold2, alpha: a});
      text(ctx, "توقّع النتيجة", W / 2, 590 - (1 - a) * 30, {size: 116, alpha: a});
      var s1 = back(prog(l, .35, .95)), s2 = back(prog(l, .5, 1.1));
      crest(ctx, im.home, W / 2 + 250, 900, 112, r.home, s1);
      crest(ctx, im.away, W / 2 - 250, 900, 112, r.away, s2);
      var n = easeOut(prog(l, .7, 1.2));
      text(ctx, "ضد", W / 2, 900, {size: 44, weight: 500, color: C.mute, alpha: n});
      text(ctx, r.home, W / 2 + 250, 1085, {size: 50, alpha: n, max: 400});
      text(ctx, r.away, W / 2 - 250, 1085, {size: 50, alpha: n, max: 400});
      var meta = [r.stage, r.when].filter(Boolean).join(" · ");
      if (meta) text(ctx, meta, W / 2, 1200, {size: 34, weight: 500, color: C.mute, alpha: n, max: W - 160});
      if (r.prize) {
        ctx.save();
        ctx.globalAlpha *= easeOut(prog(l, 1.1, 1.6));
        pill(ctx, "الجائزة: " + r.prize, W / 2, 1360, {size: 46});
        ctx.restore();
      }
    },

    lock: function (ctx, r, l) {
      title(ctx, "أُقفلت التوقّعات", l);
      text(ctx, "مع صافرة البداية — ولا يُقبل بعدها شيء", W / 2, 548, {size: 36, weight: 500, color: C.mute,
           alpha: easeOut(prog(l, .2, .7)), max: W - 160});
      var c = Math.round(r.count * easeOut(prog(l, .3, 1.6)));
      text(ctx, num(c), W / 2, 800, {size: 230, color: C.gold, dir: "ltr"});
      text(ctx, plural(r.count, PRED), W / 2, 950, {size: 56, weight: 500});
      var a = easeOut(prog(l, .9, 1.4));
      ctx.save();
      ctx.globalAlpha *= a;
      rrect(ctx, 100, 1060, W - 200, 400, 36);
      ctx.fillStyle = C.card;
      ctx.fill();
      ctx.strokeStyle = C.line;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
      text(ctx, "بصمة التوقّعات · SHA-256", W / 2, 1140, {size: 36, alpha: a, color: C.gold2});
      var shown = Math.floor(64 * prog(l, 1.2, 2.4));
      var hex = r.fp.slice(0, shown);
      [hex.slice(0, 16), hex.slice(16, 32), hex.slice(32, 48), hex.slice(48, 64)].forEach(function (line, i) {
        text(ctx, line.replace(/(.{4})/g, "$1 ").trim(), W / 2, 1225 + i * 58, {size: 42, weight: 500, font: MONO,
             dir: "ltr", alpha: a});
      });
      text(ctx, "تُنشر لحظة الإقفال: لا تتغيّر القائمة بعدها", W / 2, 1540, {size: 34, weight: 500, color: C.mute,
           alpha: easeOut(prog(l, 2.0, 2.5)), max: W - 160});
    },

    score: function (ctx, r, l, im) {
      title(ctx, "النتيجة النهائية", l);
      crest(ctx, im.home, W / 2 + 250, 760, 104, r.home, easeOut(prog(l, .1, .6)));
      crest(ctx, im.away, W / 2 - 250, 760, 104, r.away, easeOut(prog(l, .1, .6)));
      text(ctx, r.home, W / 2 + 250, 930, {size: 48, max: 400, alpha: easeOut(prog(l, .3, .7))});
      text(ctx, r.away, W / 2 - 250, 930, {size: 48, max: 400, alpha: easeOut(prog(l, .3, .7))});
      var s1 = back(prog(l, .5, 1.0)), s2 = back(prog(l, .65, 1.15));
      [[r.score[0], W / 2 + 250, s1], [r.score[1], W / 2 - 250, s2]].forEach(function (x) {
        if (x[2] <= 0) return;
        ctx.save();
        ctx.translate(x[1], 1200);
        ctx.scale(x[2], x[2]);
        text(ctx, String(x[0]), 0, 0, {size: 300, color: C.gold, dir: "ltr"});
        ctx.restore();
      });
      text(ctx, "–", W / 2, 1190, {size: 150, alpha: easeOut(prog(l, .6, 1.0))});
      text(ctx, "انتهت المباراة", W / 2, 1420, {size: 38, weight: 500, color: C.mute, alpha: easeOut(prog(l, 1.0, 1.4))});
    },

    filter: function (ctx, r, l, im, cache) {
      title(ctx, "من أصاب النتيجة؟", l);
      text(ctx, r.home + " " + r.score[0] + " – " + r.score[1] + " " + r.away, W / 2, 548,
           {size: 42, weight: 500, color: C.mute, alpha: easeOut(prog(l, .2, .6)), max: W - 160});
      var N = Math.min(r.count, 480);
      if (!N) {
        text(ctx, "لا توقّعات على هذه المباراة", W / 2, 1000, {size: 56, alpha: easeOut(prog(l, .3, .8))});
        return;
      }
      if (!cache.order) {                              // ترتيبٌ ثابت يختار نقاط المؤهّلين
        var rand = rng(r.seedNum), order = [];
        for (var i = 0; i < N; i++) order.push(i);
        for (var j = N - 1; j > 0; j--) { var k = Math.floor(rand() * (j + 1)); var tmp = order[j]; order[j] = order[k]; order[k] = tmp; }
        cache.order = order;
        cache.rank = [];
        order.forEach(function (v, i) { cache.rank[v] = i; });
      }
      var share = function (x) { return x ? Math.max(1, Math.round(N * x / r.count)) : 0; };
      var ex = share(r.exact), oc = share(r.outcome);
      var cols = Math.min(24, Math.max(6, Math.ceil(Math.sqrt(N * 1.6))));
      var gap = N < 60 ? 64 : N < 200 ? 46 : 34, dot = gap * .3;
      var rows = Math.ceil(N / cols), gw = (cols - 1) * gap;
      var x0 = W / 2 + gw / 2, y0 = 960 - (rows - 1) * gap / 2, base = ctx.globalAlpha;
      var phase2 = r.fallback ? prog(l, 2.2, 3.4) : 0;
      for (var d = 0; d < N; d++) {
        var col = d % cols, row = Math.floor(d / cols);
        var x = x0 - col * gap, y = y0 + row * gap;          // من اليمين إلى اليسار
        var at = .6 + 1.3 * (d / N), q = prog(l, at, at + .35);
        var inEx = cache.rank[d] < ex, inOc = cache.rank[d] < oc;
        var fill = C.ink, alpha = .85 * easeOut(prog(l, 0, .5)), rad = dot;
        if (!r.fallback) {
          if (inEx) { fill = C.gold; rad = dot * (1 + .4 * Math.sin(Math.PI * q)); }
          else alpha *= 1 - .85 * q;
        } else {
          alpha *= 1 - .85 * q;                               // لم يُصب أحدٌ النتيجة بالضبط
          if (inOc && phase2 > 0) {
            var q2 = prog(phase2, (d / N) * .6, (d / N) * .6 + .3);
            fill = C.green;
            alpha = .15 + .85 * q2;
            rad = dot * (1 + .3 * Math.sin(Math.PI * q2));
          }
        }
        ctx.beginPath();
        ctx.arc(x, y, rad, 0, Math.PI * 2);
        ctx.fillStyle = fill;
        ctx.globalAlpha = base * alpha;
        ctx.fill();
      }
      ctx.globalAlpha = base;
      if (r.count > N) {
        text(ctx, "كل نقطة ≈ " + num(Math.round(r.count / N * 10) / 10) + " توقّع", W / 2, y0 + rows * gap + 10,
             {size: 28, weight: 500, color: C.mute});
      }
      var ly = 1420, a = easeOut(prog(l, .8, 1.3));
      if (!r.fallback) {
        var c = Math.round(r.exact * easeOut(prog(l, .6, 1.9)));
        text(ctx, num(c), W / 2, ly, {size: 150, color: C.gold, dir: "ltr", alpha: a});
        text(ctx, r.exact ? "أصابوا النتيجة بالضبط من " + num(r.count) : r.nobody,
             W / 2, ly + 120, {size: 42, alpha: a, max: W - 160});
        if (r.exact) text(ctx, "هؤلاء وحدهم يدخلون القرعة", W / 2, ly + 185, {size: 34, weight: 500, color: C.mute,
                         alpha: easeOut(prog(l, 2.0, 2.5))});
      } else {
        text(ctx, "لم يُصب أحدٌ النتيجة بالضبط", W / 2, ly - 20, {size: 44, alpha: a * (1 - prog(l, 2.0, 2.3))});
        var b = easeOut(prog(l, 2.3, 2.8));
        var who = r.score[0] === r.score[1] ? "من توقّع التعادل" : "من أصاب الفائز";
        text(ctx, num(Math.round(r.outcome * easeOut(prog(l, 2.3, 3.4)))), W / 2, ly, {size: 150, color: C.green, dir: "ltr", alpha: b});
        text(ctx, "فالقرعة بين " + who, W / 2, ly + 120, {size: 44, alpha: b, max: W - 160});
      }
    },

    draw: function (ctx, r, l) {
      var p = r.picks[0];
      title(ctx, "القرعة", l);
      var a = easeOut(prog(l, .2, .7));
      ctx.save();
      ctx.globalAlpha *= a;
      rrect(ctx, 100, 540, W - 200, 250, 32);
      ctx.fillStyle = C.card;
      ctx.fill();
      ctx.strokeStyle = C.line;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
      text(ctx, "رقم القرعة = SHA-256 (البصمة + المباراة + النتيجة)", W / 2, 600, {size: 32, color: C.gold2, alpha: a, max: W - 260});
      var hex = r.seed.slice(0, Math.floor(64 * prog(l, .4, 1.2)));
      [hex.slice(0, 32), hex.slice(32, 64)].forEach(function (line, i) {
        text(ctx, line, W / 2, 672 + i * 56, {size: 36, weight: 500, font: MONO, dir: "ltr", alpha: a});
      });
      // الرقم العشري: خاناته تدور ثم تثبت من اليسار
      var target = num(p.num), b = prog(l, 1.2, 2.6);
      if (l > 1.2) {
        var rand = rng(Math.floor(l * 30) + 7), out = "";
        var fixed = Math.floor(target.length * easeInOut(b));
        for (var i = 0; i < target.length; i++) {
          var ch = target.charAt(i);
          out += i < fixed || ch === "," ? ch : String(Math.floor(rand() * 10));
        }
        text(ctx, "رقم الفائز", W / 2, 860, {size: 34, weight: 500, color: C.mute, alpha: easeOut(prog(l, 1.2, 1.5))});
        text(ctx, out, W / 2, 930, {size: 74, font: MONO, dir: "ltr", color: C.gold, max: W - 140});
      }
      var c = easeOut(prog(l, 2.6, 3.0));
      text(ctx, "÷ " + num(p.size) + " " + plural(p.size, ["مؤهّل", "مؤهّلان", "مؤهّلين", "مؤهّلًا"]) + "  ←  الباقي " + num(p.idx),
           W / 2, 1030, {size: 50, alpha: c, max: W - 160});
      text(ctx, "فالفائز: المؤهّل رقم " + num(p.idx + 1) + " بترتيب التسجيل", W / 2, 1095,
           {size: 38, weight: 500, color: C.gold2, alpha: c, max: W - 160});
      // الدولاب: يمرّ على المؤهّلين ويقف على الفائز
      var L = r.pool.length;
      if (!L || l < 2.8) return;
      var w = p.idx - r.poolFrom, spin = Math.max(30, Math.min(90, L * 3));
      var q = prog(l, 3.0, 5.4), v = w - spin * (1 - easeOut4(q));
      var cy = 1425, rh = 112, top = cy - rh * 2.5, bot = cy + rh * 2.5;
      var fade = easeOut(prog(l, 2.8, 3.1));
      ctx.save();
      ctx.globalAlpha *= fade;
      ctx.beginPath();
      ctx.rect(0, top, W, bot - top);
      ctx.clip();
      for (var k = Math.floor(v) - 3; k <= Math.floor(v) + 3; k++) {
        var y = cy + (k - v) * rh, e = r.pool[mod(k, L)], pos = r.poolFrom + mod(k, L) + 1;
        var near = 1 - Math.min(1, Math.abs(y - cy) / (rh * 2.6));
        rrect(ctx, 150, y - rh / 2 + 8, W - 300, rh - 16, 22);
        ctx.fillStyle = "rgba(255,255,255," + (.05 + .07 * near) + ")";
        ctx.fill();
        text(ctx, "#" + pos, W - 190, y, {size: 32, weight: 500, align: "right", color: C.mute, alpha: .3 + .7 * near});
        text(ctx, e.name, W - 320, y, {size: 46, align: "right", alpha: .3 + .7 * near, max: 380});
        text(ctx, e.phone, 190, y, {size: 36, weight: 500, align: "left", dir: "ltr", color: C.mute, alpha: .3 + .7 * near});
      }
      ctx.restore();
      var lock = prog(l, 5.4, 5.7);                   // وقف الدولاب: الإطار الذهبي يمتلئ
      var pulse = lock >= 1 ? 1 + .025 * Math.sin((l - 5.7) * 9) : 1;
      ctx.save();
      ctx.globalAlpha *= fade;
      ctx.translate(W / 2, cy);
      ctx.scale(pulse, pulse);
      ctx.translate(-W / 2, -cy);
      rrect(ctx, 138, cy - rh / 2 + 2, W - 276, rh - 4, 26);
      ctx.lineWidth = 6;
      ctx.strokeStyle = C.gold;
      ctx.stroke();
      if (lock > 0) {
        ctx.globalAlpha *= lock;
        ctx.fillStyle = C.gold;
        ctx.fill();
        var e0 = r.pool[mod(w, L)];
        text(ctx, "#" + (p.idx + 1), W - 190, cy, {size: 32, align: "right", color: C.goldInk});
        text(ctx, e0.name, W - 320, cy, {size: 46, align: "right", color: C.goldInk, max: 380});
        text(ctx, e0.phone, 190, cy, {size: 36, align: "left", dir: "ltr", color: C.goldInk});
      }
      ctx.restore();
    },

    win: function (ctx, r, l, im, cache, t) {
      confetti(ctx, r, l, cache);
      var p = r.picks[0];
      if (!p) {
        title(ctx, "لا فائز في هذه المباراة", l, 700);
        text(ctx, r.nobody, W / 2, 820, {size: 44, weight: 500, color: C.mute,
             alpha: easeOut(prog(l, .3, .8))});
        text(ctx, "نلقاكم في المباراة القادمة", W / 2, 1000, {size: 56, color: C.gold2, alpha: easeOut(prog(l, .6, 1.1))});
        return;
      }
      var s = back(prog(l, 0, .6));
      ctx.save();
      ctx.translate(W / 2, 470);
      ctx.scale(Math.max(s, .01), Math.max(s, .01));
      text(ctx, "مبروك!", 0, 0, {size: 120, color: C.gold2});
      ctx.restore();
      var a = easeOut(prog(l, .3, .8));
      ctx.save();
      ctx.globalAlpha *= a;
      rrect(ctx, 90, 580, W - 180, 640, 44);
      ctx.fillStyle = "rgba(1,40,62,.92)";
      ctx.fill();
      ctx.strokeStyle = C.gold;
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.restore();
      text(ctx, r.picks.length > 1 ? "الفائز الأول" : "الفائز", W / 2, 660, {size: 36, weight: 500, color: C.mute, alpha: a});
      text(ctx, p.name, W / 2, 780, {size: 120, alpha: a, max: W - 260});
      text(ctx, p.phone, W / 2, 900, {size: 54, weight: 500, dir: "ltr", color: C.mute, alpha: a});
      text(ctx, "توقّع " + r.home + " " + p.h + " – " + p.a + " " + r.away, W / 2, 1000, {size: 42, alpha: a, max: W - 260});
      text(ctx, (p.tier === "exact" ? "أصاب النتيجة بالضبط" : "أصاب الفائز") + " · رقم توقّعه " + p.n, W / 2, 1070,
           {size: 36, weight: 500, color: p.tier === "exact" ? C.gold2 : C.green, alpha: a, max: W - 260});
      if (r.picks.length > 1) {
        var rest = r.picks.slice(1, 5).map(function (x) { return x.name + " " + x.phone; }).join(" · ");
        text(ctx, "ومعه: " + rest, W / 2, 1150, {size: 32, weight: 500, color: C.mute, alpha: a, max: W - 240});
      }
      if (r.prize) {
        ctx.save();
        ctx.globalAlpha *= easeOut(prog(l, .7, 1.2));
        pill(ctx, "الجائزة: " + r.prize, W / 2, 1340, {size: 46});
        ctx.restore();
      }
      text(ctx, "نبلّغ الفائز على واتساب بالرقم الذي سجّل به", W / 2, 1480, {size: 34, weight: 500, color: C.mute,
           alpha: easeOut(prog(l, 1.0, 1.5)), max: W - 160});
      text(ctx, "تفاصيل الفرز كلها في صفحة المباراة", W / 2, 1540, {size: 34, weight: 500, color: C.mute,
           alpha: easeOut(prog(l, 1.2, 1.7)), max: W - 160});
    }
  };

  function confetti(ctx, r, l, cache) {
    if (!r.picks.length) return;
    if (!cache.bits) {
      var rand = rng(r.seedNum ^ 0x9e3779b9), cols = [C.gold, C.gold2, "#FFFFFF", C.green, "#60A5FA", "#F472B6"];
      cache.bits = [];
      for (var i = 0; i < 140; i++) {
        cache.bits.push({x: rand() * W, y0: -rand() * H, v: 260 + rand() * 380, s: 10 + rand() * 16,
                         w: rand() * 6.28, spin: (rand() - .5) * 8, sway: 20 + rand() * 50, c: cols[i % cols.length]});
      }
    }
    var a = easeOut(prog(l, .1, .5));
    cache.bits.forEach(function (b) {
      var y = mod(b.y0 + b.v * l, H + 100) - 50, x = b.x + Math.sin(l * 2 + b.w) * b.sway;
      ctx.save();
      ctx.globalAlpha *= .85 * a;
      ctx.translate(x, y);
      ctx.rotate(b.w + b.spin * l);
      ctx.fillStyle = b.c;
      ctx.fillRect(-b.s / 2, -b.s / 4, b.s, b.s / 2);
      ctx.restore();
    });
  }

  // ---------- التحميل ----------
  function fontCss() {
    if (document.querySelector('link[href*="IBM+Plex+Sans+Arabic"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@500;700&family=IBM+Plex+Mono:wght@500&display=swap";
    document.head.appendChild(l);
  }

  function fonts() {
    fontCss();
    if (!document.fonts || !document.fonts.load) return Promise.resolve();
    var want = ['700 60px "IBM Plex Sans Arabic"', '500 40px "IBM Plex Sans Arabic"', '500 40px "IBM Plex Mono"'];
    return Promise.race([
      Promise.all(want.map(function (f) { return document.fonts.load(f, "مبروك سمارت سوق 0123abc"); })),
      sleep(3500)
    ]).catch(function () {});
  }

  function image(u) {
    return new Promise(function (ok) {
      if (!u) return ok(null);
      var im = new Image(), done = false;
      var fin = function (v) { if (!done) { done = true; ok(v); } };
      im.crossOrigin = "anonymous";                    // وإلا تتلوّث اللوحة فلا تُسجَّل
      im.onload = function () { fin(im); };
      im.onerror = function () { fin(null); };
      setTimeout(function () { fin(im.complete && im.naturalWidth ? im : null); }, 4000);
      im.src = u;
    });
  }

  function prepare(canvas, report, opts) {
    var k = (opts && opts.scale) || 1;                 // الرسم بإحداثيات 1080×1920 دائمًا، واللوحة بمقاسها
    canvas.width = Math.round(W * k);
    canvas.height = Math.round(H * k);
    var ctx = canvas.getContext("2d"), r = norm(report), P = plan(r), cache = {}, im = {};
    return Promise.all([fonts(), image(r.homeLogo), image(r.awayLogo)]).then(function (x) {
      im.home = x[1];
      im.away = x[2];
      function frame(t) {
        t = Math.max(0, t);
        var sc = P.S[P.S.length - 1];
        for (var i = 0; i < P.S.length; i++) {
          if (t < P.S[i].t0 + P.S[i].d) { sc = P.S[i]; break; }
        }
        var l = t - sc.t0, last = sc === P.S[P.S.length - 1];
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.globalAlpha = 1;
        background(ctx, t);
        ctx.save();
        ctx.globalAlpha = last ? Math.min(1, l / .35) : Math.max(0, Math.min(1, l / .35, (sc.d - l) / .3));
        SCENES[sc.id](ctx, r, l, im, cache, t);
        ctx.restore();
        chrome(ctx, r, P, sc, t);
      }
      frame(0);
      return {frame: frame, total: P.total};
    });
  }

  // ---------- العرض ----------
  function play(canvas, report, opts) {
    var raf = 0, start = 0, gen = 0, api = null, onEnd = null;
    function loop(now) {
      if (!start) start = now;
      var t = (now - start) / 1000;
      api.frame(t);
      if (t >= api.total && onEnd) { var f = onEnd; onEnd = null; f(); }
      raf = requestAnimationFrame(loop);               // يبقى المشهد الأخير حيًّا (القصاصات)
    }
    var ctl = {
      total: 0,
      ready: prepare(canvas, report, opts).then(function (a) { api = a; ctl.total = a.total; return ctl; }),
      play: function () {
        var my = ++gen;
        return ctl.ready.then(function () {
          if (my !== gen) return;                      // أُوقف أو أُعيد قبل أن يجهز
          cancelAnimationFrame(raf);
          start = 0;
          return new Promise(function (ok) { onEnd = ok; raf = requestAnimationFrame(loop); });
        });
      },
      progress: function () { return api && start ? clamp((performance.now() - start) / 1000 / api.total) : 0; },
      stop: function () { gen++; cancelAnimationFrame(raf); }
    };
    if (!opts || opts.auto !== false) ctl.play();
    return ctl;
  }

  function pick() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    var ok = function (t) { return MediaRecorder.isTypeSupported(t); };
    for (var i = 0; i < TYPES.length; i++) {
      if (TYPES[i] === "video/mp4" && ok("video/mp4;codecs=vp9")) continue;
      if (ok(TYPES[i])) return TYPES[i];
    }
    return "";
  }

  function canRecord() {
    return !!(pick() && window.HTMLCanvasElement && HTMLCanvasElement.prototype.captureStream);
  }

  // التسجيل بالوقت الحقيقي: H.264 يرمّزه الجهاز نفسه فيبقى 1080×1920، وWebM ترميزٌ برمجيٌّ
  // يُسقط الإطارات بهذا المقاس على جهازٍ مشغول فيُسجَّل 720×1280. وتسجيلٌ خرج فارغًا يُعاد مرة.
  function record(report, opts) {
    opts = opts || {};
    var canvas = opts.canvas || document.createElement("canvas");
    var type = pick();
    if (!type || !canvas.captureStream) return Promise.reject(new Error("المتصفح لا يدعم تسجيل الفيديو — جرّب كروم أو سفاري"));
    return once(canvas, report, type, opts).then(function (out) {
      return out.blob.size > 10000 ? out : once(canvas, report, type, opts);
    }).then(function (out) {
      if (out.blob.size > 10000) return out;
      throw new Error("تعذّر التسجيل — أبقِ الصفحة ظاهرةً وأعد المحاولة");
    });
  }

  function once(canvas, report, type, opts) {
    var ctl = play(canvas, report, {auto: false, scale: /mp4/.test(type) ? 1 : 2 / 3}), timer = 0;
    return ctl.ready.then(function () {
      var stream = canvas.captureStream(FPS);
      var rec = new MediaRecorder(stream, {mimeType: type, videoBitsPerSecond: opts.bitrate || 8000000});
      var chunks = [];
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      var stopped = new Promise(function (ok) { rec.onstop = ok; });
      rec.start(1000);
      if (opts.onProgress) timer = setInterval(function () { opts.onProgress(ctl.progress()); }, 250);
      return ctl.play().then(function () { return sleep(1500); }).then(function () {
        clearInterval(timer);
        rec.stop();
        return stopped;
      }).then(function () {
        ctl.stop();
        stream.getTracks().forEach(function (t) { t.stop(); });
        var base = type.split(";")[0];
        return {blob: new Blob(chunks, {type: base}), type: base, ext: /mp4/.test(base) ? "mp4" : "webm"};
      });
    });
  }

  function save(out, name) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(out.blob);
    a.download = String(name || "draw").replace(/[\\/:*?"<>|\s]+/g, "-") + "." + out.ext;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }

  window.SSDraw = {play: play, record: record, prepare: prepare, canRecord: canRecord, save: save, W: W, H: H};
})();
