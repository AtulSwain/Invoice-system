// New-invoice screen: add/remove rows, live amounts and totals, customer auto-fill.
(function () {
  var items = document.getElementById("items");
  var tpl = document.getElementById("row-template");
  var totals = document.getElementById("totals");

  function paiseFromRate(text) {
    text = (text || "").replace(/,/g, "").trim();
    if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
    var parts = text.split(".");
    return parseInt(parts[0], 10) * 100 + (parts[1] ? parseInt((parts[1] + "0").slice(0, 2), 10) : 0);
  }
  function qtyFrom(text) {
    text = (text || "").replace(/,/g, "").trim();
    return /^\d+$/.test(text) && parseInt(text, 10) > 0 ? parseInt(text, 10) : null;
  }
  function tax(net, rate) { // half-up to the paisa, same as the server
    var milli = Math.round(parseFloat(rate) * 1000);
    return Math.floor((net * milli + 50000) / 100000);
  }
  function group(n) { // Indian digit grouping
    var s = String(n);
    if (s.length <= 3) return s;
    var head = s.slice(0, -3), tail = s.slice(-3);
    return head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail;
  }
  function money(p) { return group(Math.floor(p / 100)) + "." + String(p % 100).padStart(2, "0"); }

  function recalc() {
    var net = 0;
    var rows = items.querySelectorAll(".item");
    rows.forEach(function (row, i) {
      row.querySelector(".sr").textContent = i + 1;
      var q = qtyFrom(row.querySelector(".qty").value);
      var r = paiseFromRate(row.querySelector(".rate").value);
      var cell = row.querySelector(".amount");
      if (q !== null && r !== null) { cell.textContent = money(q * r); net += q * r; }
      else cell.textContent = "–";
    });
    var c = tax(net, totals.dataset.cgst), s = tax(net, totals.dataset.sgst);
    document.getElementById("t-net").textContent = money(net);
    document.getElementById("t-cgst").textContent = money(c);
    document.getElementById("t-sgst").textContent = money(s);
    document.getElementById("t-grand").textContent = "₹" + money(net + c + s);
    document.getElementById("add-row").disabled = rows.length >= window.MAX_ITEMS;
  }

  document.getElementById("add-row").addEventListener("click", function () {
    if (items.querySelectorAll(".item").length >= window.MAX_ITEMS) return;
    var row = tpl.content.firstElementChild.cloneNode(true);
    items.appendChild(row);
    recalc();
    row.querySelector("input[name=description]").focus();
  });
  items.addEventListener("click", function (e) {
    if (!e.target.classList.contains("remove")) return;
    var rows = items.querySelectorAll(".item");
    var row = e.target.closest(".item");
    if (rows.length === 1) { row.querySelectorAll("input").forEach(function (i) { if (i.name !== "hsn_code") i.value = ""; }); }
    else row.remove();
    recalc();
  });
  items.addEventListener("input", recalc);

  // Customer: fill address and GSTIN when a saved customer is picked
  var name = document.getElementById("customer_name");
  var addr = document.getElementById("customer_address");
  var gst = document.getElementById("customer_gstin");
  var hint = document.getElementById("cust-hint");
  var autofilled = false;
  name.addEventListener("input", function () {
    var v = name.value.trim().toLowerCase();
    var match = (window.CUSTOMERS || []).find(function (c) { return c.name.toLowerCase() === v; });
    if (match) {
      if (!addr.value || autofilled) addr.value = match.address;
      if (!gst.value || autofilled) gst.value = match.gstin;
      autofilled = true;
      hint.textContent = "Saved customer";
    } else {
      if (autofilled) { addr.value = ""; gst.value = ""; autofilled = false; }
      hint.textContent = v ? "New customer – will be saved for next time" : "";
    }
  });
  gst.addEventListener("input", function () { gst.value = gst.value.toUpperCase(); });
  recalc();
})();
