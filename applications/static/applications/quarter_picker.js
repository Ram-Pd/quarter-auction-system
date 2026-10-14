/*
 * Quarter picker on the "Register for bidding" and "Add quarters" pages.
 *   - The search box hides rows that don't match (quarter no., locality, type, floor).
 *   - The total line adds up the EMD of every ticked quarter.
 * Only a convenience: the server recalculates everything from the ticked boxes.
 */
(function () {
  "use strict";
  var search = document.getElementById("quarter-search");
  var total = document.getElementById("emd-total");
  var boxes = Array.prototype.slice.call(document.querySelectorAll('input[name="quarters"]'));
  if (!boxes.length) { return; }

  function rupees(value) {
    return "Rs. " + value.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function updateTotal() {
    var count = 0, sum = 0;
    boxes.forEach(function (box) {
      if (box.checked) { count += 1; sum += Number(box.dataset.emd); }
    });
    total.hidden = false;
    total.textContent = count
      ? count + " quarter" + (count === 1 ? "" : "s") + " selected. Total EMD to pay: " + rupees(sum)
      : "No quarter selected yet.";
  }

  function filter() {
    var words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    document.querySelectorAll(".picker-row").forEach(function (row) {
      var text = row.dataset.search.toLowerCase();
      row.hidden = !words.every(function (w) { return text.indexOf(w) !== -1; });
    });
  }

  boxes.forEach(function (box) { box.addEventListener("change", updateTotal); });
  search.addEventListener("input", filter);
  updateTotal();
})();
