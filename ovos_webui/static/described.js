/* ovos-control-panel — a page described in controlpanel.json, drawn here.
 *
 * The server checked the file and put it in the page (#cp-desc), or in a
 * step of the Setup guide (/api/setup/guide). Every
 * request names a part of the page (ref); the server decides which bus
 * message that is and what it may carry. Values from the skill are put on the
 * page as text, never as HTML. */
(function () {
  "use strict";
  // One described page, drawn into root. A described page's own document
  // draws itself (below); the Setup guide draws a page as one of its steps
  // (OvosWebUI.drawDescribed).
  function drawPage(root, page) {
    var el = OvosWebUI.el, esc = OvosWebUI.esc, say = OvosWebUI.say;
    var base = "/api/cp/" + encodeURIComponent(page.id);
    var EN = page.en || {};
    // The panel's own words, in English; their translations are the panel's.
    var COMMON = {
      "common.save": "Save", "common.delete": "Delete", "common.play": "Play", "common.stop": "Stop",
      "common.download": "Download", "common.upload": "Upload", "common.refresh": "Refresh",
      "common.cancel": "Cancel", "common.rename": "Save name", "common.sure": "Are you sure?",
      "common.saved": "Saved.", "common.done": "Done.", "common.nomatch": "That did not match, so nothing was sent.", "common.loading": "Loading …",
      "common.newer": "This part of the page needs a newer control panel.",
      "common.name": "Name", "common.none": "Nothing here yet.", "common.password_set": "A password is set; leave empty to keep it.",
      "common.noanswer": "The skill or plugin did not answer. Is it running?",
      "common.needed": "Fill in: {fields}",
      "common.nofile": "The answer carried no file.",
      "common.upload.pick": "Choose a file first.",
      "common.upload.kind": "It can take: {accept}",
      "common.upload.big": "The file is larger than {mb} MB.",
      "common.upload.busy": "Sending …",
      "common.all": "All",
      "module.tts.title": "The voice",
      "module.stt.title": "Speech recognition",
      "module.active": "This is the one in use.",
      "module.fallback": "This is the fallback, used when the one in use fails.",
      "module.unused": "This is not in use.",
      "module.use": "Use this",
      "module.useFallback": "Use as fallback",
      "module.test": "Hear it",
      "module.test.sentence": "Hello, this is how I sound.",
      "provider.title": "The provider",
      "provider.on": "It is on: the assistant searches it when you ask for something to play.",
      "provider.off": "It is off: the assistant does not search it.",
      "provider.allOff": "All media providers are turned off in the OCP pipeline's configuration, so none is searched.",
      "provider.turnOn": "Turn on",
      "provider.turnOff": "Turn off",
      "provider.restart": "The assistant picks a change up when it starts again."
    };
    // What the server says, in the words of the page: its known answers have
    // keys here, and a skill may answer with a key of its own page.
    var SERVER = {
      "the skill or plugin did not answer; is it running?": "common.noanswer",
      "the answer carried no file": "common.nofile"
    };
    function why(e) {
      var m = e && e.message ? e.message : String(e);
      if (SERVER[m]) { return t(SERVER[m]); }
      if (EN[m]) { return t(m); }
      return m;
    }
    var params = {};

    function t(label) {
      if (!label) { return ""; }
      var key = typeof label === "string" ? label : label.key;
      var en = EN[key] || COMMON[key] || (typeof label === "object" && label.en) || key;
      return OvosWebUI.t(key, en);
    }
    function day(value, withTime) {
      try {
        var opts = {day: "numeric", month: "short", year: "numeric"};
        if (withTime) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
        return new Date(value * 1000).toLocaleString(document.documentElement.lang || undefined, opts);
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
      return String(text).replace(/\{([a-z_][a-z0-9_.]*)(?::(date|time))?(?:@([A-Za-z0-9_.-]+))?\}/g,
        function (all, name, fmt, prefix) {
          var v = get(data, name);
          if (v === undefined || v === null) { return ""; }
          if (fmt) { return day(v, fmt === "time"); }
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
      if (action.confirm_text) {
        // what cannot be undone: the reader types the word the label asks for
        var typed = window.prompt(t(action.confirm));
        if (typed === null) { return; }
        if (typed.trim() !== action.confirm_text) { say(msg, t("common.nomatch"), true); return; }
      } else if (action.confirm && !OvosWebUI.confirmed(t(action.confirm))) { return; }
      if (action.download) {
        var url = base + (action.privileged ? "/download-locked" : "/download") + "?ref="
          + encodeURIComponent(action.ref) + "&key=" + encodeURIComponent(key || "");
        window.location.href = url;
        return;
      }
      post(action.privileged ? "/act" : "/act-open", {ref: action.ref, key: key, params: params})
        .then(function (r) { say(msg, t(action.done || "common.done")); if (after) { after(r); } })
        .catch(function (e) { say(msg, why(e), true); });
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
        if (block.text) { p.textContent = t(block.text); }
        if (!block.steps) { return p; }
        var wrap = document.createElement("div");
        if (block.text) { wrap.appendChild(p); }
        var ol = document.createElement("ol");
        ol.className = "cp-steps";
        block.steps.forEach(function (s) {
          var li = document.createElement("li");
          li.textContent = t(s);
          ol.appendChild(li);
        });
        wrap.appendChild(ol);
        return wrap;
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
              var dd = document.createElement("dd");
              var value = r.text ? fill(t(r.text), data) : fill(r.value, data);
              dd.textContent = value || (r.empty ? t(r.empty) : "");
              if (r.label) {
                var dt = document.createElement("dt");
                dt.textContent = t(r.label);
                rows.appendChild(dt);
              } else {
                dd.className = "cp-note";
              }
              rows.appendChild(dd);
            });
            row.innerHTML = "";
            (block.actions || []).forEach(function (a) {
              if (holds(a.when, data)) { row.appendChild(button(a, function () { run(a, null, msg, function () { load(); reloadAll(); }); })); }
            });
          }).catch(function (e) {
            // a status that is always there says why it is empty; one shown
            // only for a state (playing now) just stays away
            card.hidden = !!block.show;
            if (!block.show) { say(msg, why(e), true); }
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
            r.appendChild(button({label: block.rename.label || "common.rename", secondary: true}, function () {
              post(block.rename.privileged ? "/act" : "/act-open",
                   {ref: block.ref + ".rename", key: key, value: input.value.trim(), params: params})
                .then(function () { say(msgId, t("common.saved")); load(); })
                .catch(function (e) { say(msgId, why(e), true); });
            }));
            li.appendChild(r);
          } else {
            var name = document.createElement("span");
            name.className = "cp-title";
            name.textContent = title;
            li.appendChild(name);
          }
          if (block.text) {
            var text = document.createElement("span");
            text.className = "cp-text";
            text.textContent = fill(block.text, item);
            li.appendChild(text);
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
          // a picture from the page's own pictures folder, beside the row
          // (a row without one keeps the place, so the rows line up)
          if (block.picture) {
            var file = item[block.picture];
            var img = document.createElement(typeof file === "string"
              && /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$/.test(file) ? "img" : "span");
            if (img.tagName === "IMG") {
              img.src = "/pages/" + encodeURIComponent(page.id) + "/" + encodeURIComponent(file);
              img.alt = "";
            }
            img.className = "cp-picture";
            var body = document.createElement("div");
            body.className = "cp-row-body";
            while (li.firstChild) { body.appendChild(li.firstChild); }
            li.className = "cp-with-picture";
            li.appendChild(img);
            li.appendChild(body);
          }
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
        // a filter: the rows with one value of a field, chosen here (the
        // choice is kept while the list is read again)
        var chosen = "", choose = null, chooser = null;
        if (block.filter) {
          chooser = document.createElement("label");
          chooser.className = "cp-filter";
          chooser.textContent = t(block.filter.label) + " ";
          choose = document.createElement("select");
          chooser.appendChild(choose);
          choose.addEventListener("change", function () { chosen = choose.value; draw(lastItems); });
        }
        function fillChooser(items) {
          var seen = {};
          items.forEach(function (i) {
            var v = i[block.filter.by];
            if (v !== undefined && v !== null && v !== "") { seen[String(v)] = true; }
          });
          var values = Object.keys(seen).sort();
          if (chosen && !seen[chosen]) { chosen = ""; }
          choose.innerHTML = "";
          [""].concat(values).forEach(function (v) {
            var o = document.createElement("option");
            o.value = v;
            o.textContent = v || t(block.filter.all);
            if (v === chosen) { o.selected = true; }
            choose.appendChild(o);
          });
        }
        var lastItems = [];
        function draw(all) {
          var items = chosen ? all.filter(function (i) { return String(i[block.filter.by]) === chosen; }) : all;
          holder.innerHTML = "";
          if (chooser) { holder.appendChild(chooser); }
          if (block.split) {
            var no = items.filter(function (i) { return !i[block.split.by]; });
            var yes = items.filter(function (i) { return !!i[block.split.by]; });
            holder.appendChild(listCard(block.split["false"], no));
            if (yes.length) { holder.appendChild(listCard(block.split["true"], yes)); }
          } else {
            holder.appendChild(listCard(block.heading, items));
          }
          holder.appendChild(msgCard);
        }
        function load() {
          return post("/query", {ref: block.ref, params: params}).then(function (data) {
            // a list of text is rows with that text as their key
            lastItems = (get(data, block.items) || []).map(function (i) {
              if (typeof i !== "string") { return i; }
              var row = {};
              row[block.key] = i;
              return row;
            });
            if (choose) { fillChooser(lastItems); }
            draw(lastItems);
          }).catch(function (e) {
            // the list's own heading over what went wrong
            holder.innerHTML = "";
            var heading = block.heading || (block.split && block.split["false"]);
            var card = heading ? section({heading: heading}) : holder;
            card.appendChild(msgCard);
            if (card !== holder) { holder.appendChild(card); }
            say(msgId, why(e), true);
          });
        }
        msgId = msgEl(msgCard);
        holder.appendChild(msgCard);
        refreshers.push(load);
        load();
        if (block.refresh) { setInterval(load, block.refresh * 1000); }
        return holder;
      },
      module: function (block) {
        // whether this plugin is the one in use, to make it so, and to hear it
        var card = section({heading: block.heading || ("module." + block.kind + ".title")});
        var line = document.createElement("p");
        card.appendChild(line);
        var row = document.createElement("div");
        row.className = "row";
        card.appendChild(row);
        var msg = msgEl(card);
        var ref = block.ref + ".module";
        function show(state) {
          line.textContent = t(state.active ? "module.active" : state.fallback ? "module.fallback" : "module.unused");
          row.innerHTML = "";
          if (!state.active) {
            row.appendChild(button({label: "module.use"}, function () { use("module"); }));
          }
          if (!state.active && !state.fallback) {
            row.appendChild(button({label: "module.useFallback", secondary: true}, function () { use("fallback_module"); }));
          }
          if (state.active && block.kind === "tts") {
            row.appendChild(button({label: "module.test", secondary: true}, function () {
              post("/module/test", {ref: ref, text: t("module.test.sentence"), lang: document.documentElement.lang || ""})
                .then(function () { say(msg, t("common.done")); })
                .catch(function (e) { say(msg, why(e), true); });
            }));
          }
        }
        function use(role) {
          post("/module", {ref: ref, as: role})
            .then(function (state) { show(state); say(msg, t("common.done")); })
            .catch(function (e) { say(msg, why(e), true); });
        }
        function load() {
          return OvosWebUI.api(base + "/module?ref=" + encodeURIComponent(ref)).then(show)
            .catch(function (e) { say(msg, why(e), true); });
        }
        refreshers.push(load);
        load();
        return card;
      },
      provider: function (block) {
        // whether the assistant searches this media provider, and a switch
        var card = section({heading: block.heading || "provider.title"});
        var line = document.createElement("p");
        card.appendChild(line);
        var note = document.createElement("p");
        note.className = "hint";
        card.appendChild(note);
        var row = document.createElement("div");
        row.className = "row";
        card.appendChild(row);
        var msg = msgEl(card);
        var ref = block.ref + ".provider";
        function show(state) {
          line.textContent = t(state.enabled ? "provider.on" : "provider.off");
          note.textContent = state.all_off ? t("provider.allOff") : "";
          note.hidden = !state.all_off;
          row.innerHTML = "";
          row.appendChild(button({label: state.enabled ? "provider.turnOff" : "provider.turnOn",
                                  secondary: state.enabled}, function () {
            post("/provider", {ref: ref, enabled: !state.enabled})
              .then(function (next) { show(next); say(msg, t("provider.restart")); })
              .catch(function (e) { say(msg, why(e), true); });
          }));
        }
        function load() {
          return OvosWebUI.api(base + "/provider?ref=" + encodeURIComponent(ref)).then(show)
            .catch(function (e) { say(msg, why(e), true); });
        }
        refreshers.push(load);
        load();
        return card;
      },
      upload: function (block) {
        var card = section(block);
        var file = document.createElement("input");
        file.type = "file";
        file.accept = block.accept.join(",");
        var pick = document.createElement("label");
        pick.appendChild(file);
        card.appendChild(pick);
        var kinds = document.createElement("p");
        kinds.className = "hint";
        kinds.textContent = t("common.upload.kind").replace("{accept}", block.accept.join(", "));
        card.appendChild(kinds);
        var extra = null;
        if (block.field) {
          var label = document.createElement("label");
          label.textContent = t(block.field.label);
          extra = document.createElement("input");
          extra.type = "text";
          extra.maxLength = block.field.max_length;
          label.appendChild(extra);
          card.appendChild(label);
        }
        var row = document.createElement("div");
        row.className = "row";
        var send = document.createElement("button");
        send.textContent = t("common.upload");
        row.appendChild(send);
        card.appendChild(row);
        var msg = msgEl(card);
        send.addEventListener("click", function () {
          var f = file.files && file.files[0];
          if (!f) { say(msg, t("common.upload.pick"), true); return; }
          var dot = f.name.lastIndexOf(".");
          var ending = dot >= 0 ? f.name.slice(dot).toLowerCase() : "";
          if (block.accept.indexOf(ending) < 0) {
            say(msg, t("common.upload.kind").replace("{accept}", block.accept.join(", ")), true);
            return;
          }
          if (f.size > block.max_mb * 1024 * 1024) {
            say(msg, t("common.upload.big").replace("{mb}", block.max_mb), true);
            return;
          }
          var fd = new FormData();
          fd.append("ref", block.ref + ".upload");
          fd.append("file", f);
          if (extra) { fd.append(block.field.name, extra.value.trim()); }
          send.disabled = true;
          say(msg, t("common.upload.busy"));
          OvosWebUI.api(base + "/upload", {method: "POST", body: fd})
            .then(function () {
              say(msg, t("common.done"));
              file.value = "";
              if (extra) { extra.value = ""; }
              reloadAll();
            })
            .catch(function (e) { say(msg, why(e), true); })
            .then(function () { send.disabled = false; });
        });
        return card;
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
              if (f.voices) {
                // the plugin's own voices for the reader's language
                OvosWebUI.api(base + "/voices?ref=" + encodeURIComponent(block.ref + ".form") + "&field="
                  + encodeURIComponent(f.name) + "&lang=" + encodeURIComponent(document.documentElement.lang || "en"))
                  .then(function (data) {
                    (data.voices || []).forEach(function (o) {
                      var opt = document.createElement("option");
                      opt.value = o.value; opt.textContent = o.label;
                      input.appendChild(opt);
                    });
                    var want = input.dataset.want;
                    if (want && !Array.prototype.some.call(input.options, function (o) { return o.value === want; })) {
                      // a voice set by hand stays, even if the plugin does not list it
                      var own = document.createElement("option");
                      own.value = want; own.textContent = want;
                      input.appendChild(own);
                    }
                    if (want) { input.value = want; }
                  }).catch(function () { /* the fixed options stay */ });
              }
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
              input.type = {password: "password", number: "number", slider: "range", url: "url"}[f.type] || "text";
              if (f.type === "password") { input.autocomplete = "new-password"; }
              ["min", "max", "step"].forEach(function (k) { if (f[k] !== undefined) { input[k] = f[k]; } });
              if (f.type === "text" || f.type === "password" || f.type === "url") { input.maxLength = f.max_length; }
              if (f.type === "url") { input.placeholder = "https://"; input.spellcheck = false; }
              if (f.required) { input.required = true; }
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
        save.textContent = t(block.button || "common.save");
        row.appendChild(save);
        card.appendChild(row);
        var msg = msgEl(card);
        OvosWebUI.api(base + "/form?ref=" + encodeURIComponent(block.ref + ".form")).then(function (r) {
          var values = r.values || {};
          Object.keys(inputs).forEach(function (name) {
            var f = inputs[name].field, input = inputs[name].input, v = values[name];
            if (v === undefined) { return; }
            if (f.type === "checkbox") { input.checked = "on" in f ? !same(v, f.off) : !!v; }
            else if (f.type === "password") { input.placeholder = v.set ? t("common.password_set") : ""; inputs[name].set = !!v.set; }
            else if (f.type === "lines") { input.value = (Array.isArray(v) ? v : (v ? [String(v)] : [])).join("\n"); }
            else {
              if (f.voices && input.tagName === "SELECT" && v !== "" &&
                  !Array.prototype.some.call(input.options, function (o) { return o.value === String(v); })) {
                var own = document.createElement("option");
                own.value = String(v); own.textContent = String(v);
                input.appendChild(own);
              }
              input.value = v; input.dataset.want = v;
            }
            if (input.cpShow) { input.cpShow(); }
          });
          showFields();
        }).catch(function (e) { say(msg, why(e), true); });
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
          var lacking = Object.keys(inputs).filter(function (name) {
            var i = inputs[name];
            var v = values[name];
            var empty = v === undefined || v === "" || v === null || (Array.isArray(v) && !v.length);
            return i.field.required && !i.set && !i.label.hidden && empty;
          }).map(function (name) { return t(inputs[name].field.label); });
          if (lacking.length) { say(msg, t("common.needed").replace("{fields}", lacking.join(", ")), true); return; }
          post("/form", {ref: block.ref + ".form", values: values})
            .then(function () { say(msg, t("common.saved")); reloadAll(); })
            .catch(function (e) { say(msg, why(e), true); });
        });
        return card;
      }
    };

    function reloadAll() { refreshers.forEach(function (f) { f(); }); }

    page.blocks.forEach(function (block) {
      var made = (draw[block.type] || draw.unknown)(block);
      if (made) { root.appendChild(made); }
    });
  }

  OvosWebUI.drawDescribed = drawPage;
  // a described page's own document: the server put the page in #cp-desc
  var node = document.getElementById("cp-desc");
  if (node) {
    OvosWebUI.ready(function () {
      var root = document.getElementById("cp-page");
      if (root) { drawPage(root, JSON.parse(node.textContent)); }
    });
  }
})();
