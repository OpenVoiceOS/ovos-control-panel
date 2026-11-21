/* ovos-control-panel — a page described in controlpanel.json, drawn here.
 *
 * The server checked the file and put it in the page (#cp-desc). Every
 * request names a part of the page (ref); the server decides which bus
 * message that is and what it may carry. Values from the skill are put on the
 * page as text, never as HTML. */
OvosWebUI.ready(function () {
  "use strict";
  var el = OvosWebUI.el, esc = OvosWebUI.esc, say = OvosWebUI.say;
  var root = document.getElementById("cp-page");
  var node = document.getElementById("cp-desc");
  if (!root || !node) { return; }
  var page = JSON.parse(node.textContent);
  var base = "/api/cp/" + encodeURIComponent(page.id);
  var EN = page.en || {};
  // The panel's own words, in English; their translations are the panel's.
  var COMMON = {
    "common.save": "Save", "common.delete": "Delete", "common.play": "Play", "common.stop": "Stop",
    "common.download": "Download", "common.upload": "Upload", "common.refresh": "Refresh",
    "common.cancel": "Cancel", "common.rename": "Save name", "common.sure": "Are you sure?",
    "common.saved": "Saved.", "common.done": "Done.", "common.loading": "Loading …",
    "common.newer": "This part of the page needs a newer control panel.",
    "common.name": "Name", "common.none": "Nothing here yet.", "common.password_set": "A password is set; leave empty to keep it."
  };
  var params = {};

  function t(label) {
    if (!label) { return ""; }
    var key = typeof label === "string" ? label : label.key;
    var en = EN[key] || COMMON[key] || (typeof label === "object" && label.en) || key;
    return OvosWebUI.t(key, en);
  }
  function day(value) {
    try {
      return new Date(value * 1000).toLocaleDateString(document.documentElement.lang || undefined,
        {day: "numeric", month: "short", year: "numeric"});
    } catch (e) { return ""; }
  }
  // a field of an answer, maybe nested ("ports.outputs")
  function get(data, path) {
    return String(path).split(".").reduce(function (d, k) { return d == null ? undefined : d[k]; }, data);
  }
  function truthy(v) { return Array.isArray(v) ? v.length > 0 : !!v; }
  // "{name}", "{saved:date}", and "{engine@midi.engine}": the value as a
  // label (midi.engine.fluidsynth); a list is joined with commas
  function fill(text, data) {
    return String(text).replace(/\{([a-z_][a-z0-9_.]*)(?::(date))?(?:@([A-Za-z0-9_.-]+))?\}/g,
      function (all, name, fmt, prefix) {
        var v = get(data, name);
        if (v === undefined || v === null) { return ""; }
        if (fmt === "date") { return day(v); }
        if (prefix) {
          // a label per value; one that is not there shows nothing, and the
          // label may carry the answer's values ({ha_version})
          var key = prefix + "." + v, text = t(key);
          return text === key ? "" : fill(text, data);
        }
        return Array.isArray(v) ? v.join(", ") : String(v);
      });
  }
  function holds(when, data) {
    if (!when) { return true; }
    var not = when.charAt(0) === "!", v = truthy(get(data, not ? when.slice(1) : when));
    return not ? !v : v;
  }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function post(path, body) {
    return OvosWebUI.api(base + path, {method: "POST", headers: {"Content-Type": "application/json"},
                                       body: JSON.stringify(body || {})});
  }
  function msgEl(card) {
    var m = document.createElement("div");
    m.className = "msg"; m.setAttribute("role", "status"); m.setAttribute("aria-live", "polite"); m.hidden = true;
    m.id = "cp-msg-" + Math.random().toString(36).slice(2);
    card.appendChild(m);
    return m.id;
  }
  function button(action, onClick) {
    var b = document.createElement("button");
    b.textContent = t(action.label);
    var danger = action.send && /delete|remove|forget|reset|wipe|erase/i.test(action.send);
    b.className = danger ? "danger" : (action.download || action.secondary ? "secondary" : "");
    b.addEventListener("click", onClick);
    return b;
  }
  function run(action, key, msg, after) {
    if (action.confirm && !OvosWebUI.confirmed(t(action.confirm))) { return; }
    if (action.download) {
      var url = base + (action.privileged ? "/download-locked" : "/download") + "?ref="
        + encodeURIComponent(action.ref) + "&key=" + encodeURIComponent(key || "");
      window.location.href = url;
      return;
    }
    post(action.privileged ? "/act" : "/act-open", {ref: action.ref, key: key, params: params})
      .then(function (r) { say(msg, t("common.done")); if (after) { after(r); } })
      .catch(function (e) { say(msg, e.message, true); });
  }

  var refreshers = [];
  function section(block) {
    var card = document.createElement("section");
    card.className = "card";
    if (block.heading) {
      var h = document.createElement("h2");
      h.textContent = t(block.heading);
      card.appendChild(h);
    }
    return card;
  }

  // ── the blocks ───────────────────────────────────────────────────────────
  var draw = {
    text: function (block) {
      var p = document.createElement("p");
      p.className = "hint";
      p.textContent = t(block.text);
      return p;
    },
    unknown: function () {
      var p = document.createElement("p");
      p.className = "hint";
      p.textContent = t("common.newer");
      return p;
    },
    choice: function (block) {
      var wrap = document.createElement("div");
      wrap.className = "tabs";
      wrap.setAttribute("role", "group");
      params[block.param] = block.options[0].value;
      block.options.forEach(function (o, i) {
        var b = document.createElement("button");
        b.textContent = t(o.label);
        b.setAttribute("aria-pressed", i === 0 ? "true" : "false");
        b.addEventListener("click", function () {
          params[block.param] = o.value;
          wrap.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
          refreshers.forEach(function (f) { f(); });
        });
        wrap.appendChild(b);
      });
      return wrap;
    },
    status: function (block) {
      var card = section(block);
      var line = document.createElement("p");
      card.appendChild(line);
      var rows = document.createElement("dl");
      rows.className = "cp-rows";
      card.appendChild(rows);
      var row = document.createElement("div");
      row.className = "row";
      card.appendChild(row);
      var msg = msgEl(card);
      card.hidden = true;
      function load() {
        return post("/query", {ref: block.ref, params: params}).then(function (data) {
          card.hidden = !holds(block.show, data);
          line.hidden = !block.text;
          line.textContent = block.text ? fill(t(block.text), data) : "";
          rows.innerHTML = "";
          (block.rows || []).forEach(function (r) {
            if (!holds(r.when, data)) { return; }
            var dt = document.createElement("dt"), dd = document.createElement("dd");
            dt.textContent = t(r.label);
            var value = r.text ? fill(t(r.text), data) : fill(r.value, data);
            dd.textContent = value || (r.empty ? t(r.empty) : "");
            rows.appendChild(dt); rows.appendChild(dd);
          });
          row.innerHTML = "";
          (block.actions || []).forEach(function (a) {
            if (holds(a.when, data)) { row.appendChild(button(a, function () { run(a, null, msg, function () { load(); reloadAll(); }); })); }
          });
        }).catch(function (e) {
          // a status that is always there says why it is empty; one shown
          // only for a state (playing now) just stays away
          card.hidden = !!block.show;
          if (!block.show) { say(msg, e.message, true); }
        });
      }
      refreshers.push(load);
      load();
      if (block.refresh) { setInterval(load, block.refresh * 1000); }
      return card;
    },
    actions: function (block) {
      var card = section(block);
      var row = document.createElement("div");
      row.className = "row";
      card.appendChild(row);
      var msg = msgEl(card);
      block.actions.forEach(function (a) {
        row.appendChild(button(a, function () { run(a, null, msg, reloadAll); }));
      });
      return card;
    },
    list: function (block) {
      var holder = document.createElement("div");
      var msgCard = document.createElement("div");
      function rowFor(item) {
        var li = document.createElement("li");
        var key = item[block.key];
        var title = fill(block.title, item);
        if (block.rename && holds(block.rename.when, item)) {
          var r = document.createElement("span");
          r.className = "row";
          var input = document.createElement("input");
          input.type = "text"; input.maxLength = block.rename.max_length; input.value = item[block.rename.field] || title;
          input.setAttribute("aria-label", t("common.name"));
          r.appendChild(input);
          r.appendChild(button({label: "common.rename", secondary: true}, function () {
            post(block.rename.privileged ? "/act" : "/act-open",
                 {ref: block.ref + ".rename", key: key, value: input.value.trim(), params: params})
              .then(function () { say(msgId, t("common.saved")); load(); })
              .catch(function (e) { say(msgId, e.message, true); });
          }));
          li.appendChild(r);
        } else {
          var name = document.createElement("span");
          name.className = "cp-title";
          name.textContent = title;
          li.appendChild(name);
        }
        if (block.meta) {
          var meta = document.createElement("span");
          meta.className = "cp-meta";
          meta.textContent = fill(t(block.meta), item);
          li.appendChild(meta);
        }
        var acts = document.createElement("span");
        acts.className = "row";
        (block.actions || []).forEach(function (a) {
          if (holds(a.when, item)) { acts.appendChild(button(a, function () { run(a, key, msgId, function () { load(); reloadAll(); }); })); }
        });
        if (acts.children.length) { li.appendChild(acts); }
        return li;
      }
      function listCard(heading, items) {
        var card = section({heading: heading});
        var ul = document.createElement("ul");
        ul.className = "cp-list";
        if (!items.length) {
          var li = document.createElement("li");
          li.className = "empty";
          li.textContent = t(block.empty || "common.none");
          ul.appendChild(li);
        }
        items.forEach(function (item) { ul.appendChild(rowFor(item)); });
        card.appendChild(ul);
        return card;
      }
      var msgId;
      function load() {
        return post("/query", {ref: block.ref, params: params}).then(function (data) {
          var items = get(data, block.items) || [];
          holder.innerHTML = "";
          if (block.split) {
            var no = items.filter(function (i) { return !i[block.split.by]; });
            var yes = items.filter(function (i) { return !!i[block.split.by]; });
            holder.appendChild(listCard(block.split["false"], no));
            if (yes.length) { holder.appendChild(listCard(block.split["true"], yes)); }
          } else {
            holder.appendChild(listCard(block.heading, items));
          }
          holder.appendChild(msgCard);
        }).catch(function (e) {
          holder.innerHTML = "";
          holder.appendChild(msgCard);
          say(msgId, e.message, true);
        });
      }
      msgId = msgEl(msgCard);
      holder.appendChild(msgCard);
      refreshers.push(load);
      load();
      if (block.refresh) { setInterval(load, block.refresh * 1000); }
      return holder;
    },
    form: function (block) {
      var card = section(block);
      var inputs = {};
      block.fields.forEach(function (f) {
        var label = document.createElement("label");
        var span = document.createElement("span");
        span.textContent = t(f.label);
        var input;
        if (f.type === "checkbox") {
          label.className = "check";
          input = document.createElement("input");
          input.type = "checkbox";
          label.appendChild(input);
          label.appendChild(span);
        } else {
          label.appendChild(span);
          if (f.type === "select") {
            input = document.createElement("select");
            (f.options || []).forEach(function (o) {
              var opt = document.createElement("option");
              opt.value = o.value; opt.textContent = t(o.label);
              input.appendChild(opt);
            });
            if (f.options_from) {
              post("/options", {ref: block.ref + ".form", field: f.name}).then(function (data) {
                var src = f.options_from;
                (get(data, src.items) || []).forEach(function (o) {
                  var opt = document.createElement("option");
                  var plain = typeof o !== "object" || o === null;
                  opt.value = String(plain ? o : o[src.value]);
                  opt.textContent = String(plain ? o : o[src.label]);
                  input.appendChild(opt);
                });
                if (input.dataset.want) { input.value = input.dataset.want; }
              }).catch(function () { /* the fixed options stay */ });
            }
          } else if (f.type === "lines") {
            input = document.createElement("textarea");
            input.rows = 4; input.spellcheck = false;
          } else {
            input = document.createElement("input");
            input.type = {password: "password", number: "number", slider: "range"}[f.type] || "text";
            if (f.type === "password") { input.autocomplete = "new-password"; }
            ["min", "max", "step"].forEach(function (k) { if (f[k] !== undefined) { input[k] = f[k]; } });
            if (f.type === "text" || f.type === "password") { input.maxLength = f.max_length; }
          }
          if (f.type === "slider") {
            // the value beside it: a percent for 0..1
            var wrap = document.createElement("span"), out = document.createElement("output");
            wrap.className = "cp-range";
            var show = function () {
              out.textContent = f.max === 1 && (f.min || 0) === 0 ? Math.round(input.value * 100) + " %" : input.value;
            };
            input.addEventListener("input", show);
            input.addEventListener("change", show);
            wrap.appendChild(input); wrap.appendChild(out);
            label.appendChild(wrap);
            input.cpShow = show;
          } else {
            label.appendChild(input);
          }
        }
        card.appendChild(label);
        if (f.hint) {
          var hint = document.createElement("p");
          hint.className = "hint";
          hint.textContent = t(f.hint);
          card.appendChild(hint);
        }
        inputs[f.name] = {field: f, input: input, label: label};
      });
      // a field shown only for one value of another (the port, for "a MIDI port")
      function showFields() {
        Object.keys(inputs).forEach(function (name) {
          var f = inputs[name].field;
          if (!f.show_when || !inputs[f.show_when.field]) { return; }
          var other = inputs[f.show_when.field].input;
          var v = other.type === "checkbox" ? other.checked : other.value;
          inputs[name].label.hidden = String(v) !== String(f.show_when.value);
        });
      }
      Object.keys(inputs).forEach(function (name) {
        inputs[name].input.addEventListener("change", showFields);
      });
      var row = document.createElement("div");
      row.className = "row";
      var save = document.createElement("button");
      save.textContent = t("common.save");
      row.appendChild(save);
      card.appendChild(row);
      var msg = msgEl(card);
      OvosWebUI.api(base + "/form?ref=" + encodeURIComponent(block.ref + ".form")).then(function (r) {
        var values = r.values || {};
        Object.keys(inputs).forEach(function (name) {
          var f = inputs[name].field, input = inputs[name].input, v = values[name];
          if (v === undefined) { return; }
          if (f.type === "checkbox") { input.checked = "on" in f ? !same(v, f.off) : !!v; }
          else if (f.type === "password") { input.placeholder = v.set ? t("common.password_set") : ""; }
          else if (f.type === "lines") { input.value = (v || []).join("\n"); }
          else { input.value = v; input.dataset.want = v; }
          if (input.cpShow) { input.cpShow(); }
        });
        showFields();
      }).catch(function (e) { say(msg, e.message, true); });
      save.addEventListener("click", function () {
        var values = {};
        Object.keys(inputs).forEach(function (name) {
          var f = inputs[name].field, input = inputs[name].input;
          if (f.type === "checkbox") { values[name] = input.checked; }
          else if (f.type === "number" || f.type === "slider") { if (input.value !== "") { values[name] = Number(input.value); } }
          else if (f.type === "lines") { values[name] = input.value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean); }
          else if (f.type === "password") { if (input.value) { values[name] = input.value; } }
          else { values[name] = input.value; }
        });
        post("/form", {ref: block.ref + ".form", values: values})
          .then(function () { say(msg, t("common.saved")); reloadAll(); })
          .catch(function (e) { say(msg, e.message, true); });
      });
      return card;
    }
  };

  function reloadAll() { refreshers.forEach(function (f) { f(); }); }

  page.blocks.forEach(function (block) {
    var made = (draw[block.type] || draw.unknown)(block);
    if (made) { root.appendChild(made); }
  });
});
