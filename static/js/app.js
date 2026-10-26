/* Office Stock - small progressive-enhancement helpers. Every page still works with plain form posts. */
(function () {
  'use strict';
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  // ---- mobile menu
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-nav-open]')) document.body.classList.add('nav-open');
    if (e.target.closest('[data-nav-close]')) document.body.classList.remove('nav-open');
  });

  // ---- audit log controls
  document.addEventListener('change', function (e) {
    var form = e.target.closest('form[data-audit-filters]');
    if (form) form.submit();
  });
  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-toggle-row]');
    if (!button) return;
    var row = document.getElementById(button.getAttribute('data-toggle-row'));
    if (!row) return;
    row.classList.toggle('hidden');
    button.textContent = row.classList.contains('hidden') ? 'Details' : 'Hide';
  });

  // ---- confirm before risky actions: <form data-confirm="..."> or <button data-confirm="...">
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-confirm], a[data-confirm]');
    if (b && !window.confirm(b.getAttribute('data-confirm'))) e.preventDefault();
  });

  // ---- stop double submits
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented) return;
    $$('button[type=submit]', e.target).forEach(function (b) { setTimeout(function () { b.disabled = true; }, 0); });
  });
  window.addEventListener('pageshow', function () { $$('button[type=submit]').forEach(function (b) { b.disabled = false; }); });

  // ---- permission picker -------------------------------------------------------------
  function Picker(root) {
    this.root = root;
    this.implies = JSON.parse(root.getAttribute('data-implies') || '{}');
    this.boxes = $$('input[name=permissions]', root);
    this.list = $('[data-picker-list]', root);
    this.tools = $('[data-picker-tools]', root);
    this.locked = $('[data-picker-locked]', root);
    this.waiting = $('[data-picker-waiting]', root);
    this.empty = $('[data-picker-empty]', root);
    var self = this;
    this.boxes.forEach(function (b) { b.addEventListener('change', function () { self.toggle(b.value, b.checked); }); });
    var all = $('[data-picker-all]', root), none = $('[data-picker-none]', root);
    if (all) all.addEventListener('click', function () { self.set(self.boxes.map(function (b) { return b.value; })); });
    if (none) none.addEventListener('click', function () { self.set([]); });
  }
  Picker.prototype.value = function () { return this.boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; }); };
  Picker.prototype.set = function (values) {
    this.boxes.forEach(function (b) { b.checked = values.indexOf(b.value) !== -1; });
    this.refresh();
  };
  Picker.prototype.box = function (v) { return this.boxes.filter(function (b) { return b.value === v; })[0]; };
  // Ticking a feature also ticks what it depends on; unticking "View" also unticks what needs it.
  Picker.prototype.toggle = function (key, on) {
    var self = this;
    if (on) {
      (this.implies[key] || []).forEach(function (dep) { var b = self.box(dep); if (b) b.checked = true; });
    } else {
      Object.keys(this.implies).forEach(function (perm) {
        if (self.implies[perm].indexOf(key) !== -1) { var b = self.box(perm); if (b) b.checked = false; }
      });
    }
    this.refresh();
  };
  // state: 'ready' | 'locked' | 'waiting'
  Picker.prototype.state = function (state) {
    this.mode = state;
    this.list.classList.toggle('hidden', state !== 'ready');
    this.tools.classList.toggle('hidden', state !== 'ready');
    this.locked.classList.toggle('hidden', state !== 'locked');
    this.waiting.classList.toggle('hidden', state !== 'waiting');
    this.refresh();
  };
  Picker.prototype.refresh = function () {
    if (this.empty) this.empty.classList.toggle('hidden', !(this.mode === 'ready' && this.value().length === 0));
    this.root.dispatchEvent(new CustomEvent('picker:change', { bubbles: true }));
  };

  var pickers = {};
  $$('[data-picker]').forEach(function (el) { pickers.main = new Picker(el); });

  // ---- user form: choosing a role ticks its typical features and narrows the branch list
  var userForm = $('[data-user-form]');
  if (userForm && pickers.main) {
    var roles = {};
    try { JSON.parse($('#roles-data').textContent).forEach(function (r) { roles[r.key] = r; }); } catch (err) { /* none */ }
    var roleSel = $('[data-role-select]', userForm), branchSel = $('[data-branch-select]', userForm);
    var roleHint = $('[data-role-hint]', userForm), branchHint = $('[data-branch-hint]', userForm);
    var apply = function (userChanged) {
      var r = roles[roleSel.value];
      var isAdmin = roleSel.value === 'super_admin';
      pickers.main.state(isAdmin ? 'locked' : (r ? 'ready' : 'waiting'));
      roleHint.textContent = (r && r.description) || 'Choosing a role ticks a typical set of features below';
      var branchSide = r && r.side === 'branch';
      branchHint.classList.toggle('hidden', !branchSide);
      $$('option', branchSel).forEach(function (o) {
        var hide = branchSide && o.getAttribute('data-type') === 'main';
        o.hidden = hide; o.disabled = hide;
      });
      if (branchSide && branchSel.selectedOptions[0] && branchSel.selectedOptions[0].getAttribute('data-type') === 'main') branchSel.value = '';
      if (userChanged && r) pickers.main.set(r.permissions);
    };
    roleSel.addEventListener('change', function () { apply(true); });
    apply(false);
  }

  // ---- role form: the "also give these ticks to existing users" box appears when ticks change
  var roleForm = $('[data-role-form]');
  if (roleForm && pickers.main) {
    var sideSel = $('select[name=side]', roleForm);
    var original = JSON.parse(roleForm.getAttribute('data-original-perms') || '[]').slice().sort().join(',');
    var box = $('[data-apply-box]', roleForm);
    var sync = function () {
      pickers.main.state(sideSel && sideSel.value ? 'ready' : 'waiting');
      if (box) box.classList.toggle('hidden', pickers.main.value().slice().sort().join(',') === original);
    };
    if (sideSel) sideSel.addEventListener('change', sync);
    roleForm.addEventListener('picker:change', function () {
      if (box) box.classList.toggle('hidden', pickers.main.value().slice().sort().join(',') === original);
    });
    sync();
  }

  // ---- line items (purchase, issue, request, dispatch) --------------------------------
  $$('[data-lines]').forEach(function (wrap) {
    var rowsEl = $('[data-lines-rows]', wrap);
    var tpl = $('template[data-line-template]', wrap);
    var addBtn = $('[data-add-line]', wrap);
    var totalEl = $('[data-lines-total]', wrap);
    var unitsEl = $('[data-lines-units]', wrap);

    function money(n) { return 'Rs. ' + n.toLocaleString('en-LK', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function recalc() {
      var total = 0, units = 0;
      $$('.line', rowsEl).forEach(function (row) {
        var q = parseFloat(($('[name=line_quantity]', row) || {}).value) || 0;
        var c = parseFloat(($('[name=line_unit_cost]', row) || {}).value) || 0;
        total += q * c; units += q;
      });
      if (totalEl) totalEl.textContent = money(total);
      if (unitsEl) unitsEl.textContent = String(units);
    }
    function wire(row) {
      var sel = $('[name=line_item]', row), unit = $('[data-unit]', row);
      var show = function () {
        var o = sel.selectedOptions[0];
        if (unit) unit.textContent = o && o.value ? (o.getAttribute('data-unit') || '') : '';
      };
      sel.addEventListener('change', function () {
        show();
        var cost = $('[name=line_unit_cost]', row), o = sel.selectedOptions[0];
        if (cost && !cost.value && o && o.getAttribute('data-cost')) cost.value = o.getAttribute('data-cost');
        recalc();
      });
      show();
      var rm = $('[data-remove-line]', row);
      if (rm) rm.addEventListener('click', function () {
        if ($$('.line', rowsEl).length > 1) { row.remove(); } else { $$('input,select', row).forEach(function (i) { i.value = ''; }); show(); }
        recalc();
      });
      $$('input', row).forEach(function (i) { i.addEventListener('input', recalc); });
    }
    $$('.line', rowsEl).forEach(wire);
    if (addBtn && tpl) addBtn.addEventListener('click', function () {
      var frag = tpl.content.cloneNode(true);
      rowsEl.appendChild(frag);
      var row = rowsEl.lastElementChild;
      wire(row);
      var first = $('select,input', row); if (first) first.focus();
    });
    recalc();
  });

  // ---- "fill from the remaining amount" helper on receive / dispatch pages
  $$('[data-fill]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      $$('input[data-max]', document).forEach(function (i) { i.value = i.getAttribute('data-max'); });
    });
  });
})();
