/* Keep ScribbleAI's original HTML, CSS and interaction code while using the cloud API. */
(function () {
  "use strict";
  var nativeFetch = window.fetch.bind(window);
  var prefix = "scribbleai-cloud-demo-v1:";
  var traceKey = prefix + "traces";
  var resetKey = prefix + "resetAfter";
  var infoKey = prefix + "checkpoint";
  var traces = {};
  try { traces = JSON.parse(localStorage.getItem(traceKey) || "{}"); } catch (_) {}

  function json(data, status) {
    return new Response(JSON.stringify(data), {
      status: status || 200,
      headers: { "Content-Type": "application/json" }
    });
  }
  function hash(s) {
    var n = 2166136261;
    s = String(s || "");
    for (var i = 0; i < s.length; i++) n = Math.imul(n ^ s.charCodeAt(i), 16777619);
    return (n >>> 0) || 1;
  }
  function remember(id, ink, ms, alts, strokes) {
    if (!id || !ink) return;
    traces[hash(id)] = { ink: ink, conf: null, idx: null, chars: [], blank: -1,
      ms: ms || {}, alts: alts || null, strokes: strokes || 0 };
    var keys = Object.keys(traces);
    while (keys.length > 30) delete traces[keys.shift()];
    try { localStorage.setItem(traceKey, JSON.stringify(traces)); } catch (_) {
      try { localStorage.removeItem(traceKey); } catch (_) {}
    }
  }
  function adaptStats(s) {
    var cutoff = 0;
    try { cutoff = Number(localStorage.getItem(resetKey) || 0); } catch (_) {}
    var rows = (s.recent || []).filter(function (r) { return Date.parse(r.ts) >= cutoff; });
    var byMode = { greedy: [], beam: [], beam_lm: [], beam_lm_spell: [] };
    var breakdown = { preprocess: 0, model: 0, decode: 0 };
    rows.forEach(function (r) {
      var m = traces[hash(r.request_id)] || {};
      (byMode[r.mode] || (byMode[r.mode] = [])).push(Number(r.total_ms || 0));
      Object.keys(breakdown).forEach(function (k) { breakdown[k] += Number((m.ms || {})[k] || 0); });
    });
    Object.keys(breakdown).forEach(function (k) { breakdown[k] /= rows.length || 1; });
    var recent = rows.map(function (r) {
      var m = traces[hash(r.request_id)] || {};
      return { id: hash(r.request_id), t: Date.parse(r.ts) / 1000, text: r.text || "",
        mode: r.mode || "greedy", compare: !!m.alts, alts: m.alts,
        total: Number(r.total_ms || 0), frames: Number(r.frames || 0),
        strokes: m.strokes || 0 };
    });
    var filtered = cutoff > 0;
    var count = filtered ? rows.length : Number(s.count || 0);
    return {
      checkpoint: (function () { try { return localStorage.getItem(infoKey); } catch (_) { return null; } })() || "Cloud model",
      uptime_s: Number((s.cloud || {}).container_age_s || 0), count: count,
      median_ms: filtered ? percentile(rows, .5) : Number(s.p50_ms || 0),
      p95_ms: filtered ? percentile(rows, .95) : Number(s.p95_ms || 0),
      mean_frames: rows.reduce(function (sum, r) { return sum + Number(r.frames || 0); }, 0) / (rows.length || 1),
      breakdown_ms: breakdown, lat_by_mode: byMode, recent: recent
    };
  }
  function percentile(rows, p) {
    var v = rows.map(function (r) { return Number(r.total_ms || 0); }).sort(function (a,b) { return a-b; });
    return v.length ? v[Math.min(v.length-1, Math.round((v.length-1)*p))] : 0;
  }
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : input.url;
    var path;
    try { path = new URL(url, location.href).pathname; } catch (_) { return nativeFetch(input, init); }
    if (path === "/api/stats/reset") {
      try { localStorage.setItem(resetKey, String(Date.now())); } catch (_) {}
      return Promise.resolve(json({ ok: true }));
    }
    if (path.indexOf("/api/trace/") === 0) {
      var trace = traces[Number(path.slice("/api/trace/".length))];
      return Promise.resolve(trace ? json(trace) : json({ detail: "Trace unavailable" }, 404));
    }
    if (path === "/api/info") {
      return nativeFetch(input, init).then(function (response) {
        if (!response.ok) return response;
        return response.json().then(function (data) {
          var model = (data.models || []).filter(function (m) { return m.id === data.default_model && m.available; })[0] ||
                      (data.models || []).filter(function (m) { return m.available; })[0];
          if (!model) return json({ detail: "No cloud model uploaded" }, 503);
          try { localStorage.setItem(infoKey, model.checkpoint || model.id); } catch (_) {}
          return json({ checkpoint: model.checkpoint || model.id, epoch: model.epoch,
            val_cer: model.val_cer, modes: model.modes || [], vocab_size: model.vocab_size,
            params: model.params });
        });
      });
    }
    if (path === "/api/recognize") {
      var body;
      try { body = JSON.parse((init || {}).body || "{}"); } catch (_) { body = {}; }
      return nativeFetch(input, init).then(function (response) {
        if (!response.ok) return response;
        return response.json().then(function (data) {
          remember((data.cloud || {}).request_id, data.ink, data.ms,
            data.all && Object.keys(data.all).length ? Object.fromEntries(Object.entries(data.all).map(function (pair) { return [pair[0], pair[1].text]; })) : null,
            (body.strokes || []).length);
          return json(data);
        });
      });
    }
    if (path === "/api/stats") {
      return nativeFetch(input, init).then(function (response) {
        if (!response.ok) return response;
        return response.json().then(function (data) { return json(adaptStats(data)); });
      });
    }
    return nativeFetch(input, init);
  };
})();
