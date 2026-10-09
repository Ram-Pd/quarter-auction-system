/*
 * Live countdowns.
 *
 * Markup:  <span data-countdown="2026-10-09T15:30:00+05:30" data-prefix="Ends in "></span>
 * The <script> tag carries data-server-now (the server's clock when the page
 * was rendered), so a wrong clock on the user's computer doesn't matter.
 *
 * When any countdown reaches zero the page reloads once, so the server can
 * move the auction to its next phase (Upcoming -> Live -> Closing).
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var serverNow = Date.parse(script && script.dataset.serverNow);
  // Difference between server clock and this browser's clock, in ms.
  var clockOffset = isNaN(serverNow) ? 0 : serverNow - Date.now();

  function format(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var d = Math.floor(total / 86400);
    var h = Math.floor((total % 86400) / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return (d > 0 ? d + "d " : "") + pad(h) + ":" + pad(m) + ":" + pad(s);
  }

  var elements = Array.prototype.slice.call(document.querySelectorAll("[data-countdown]"));
  var reloading = false;

  function tick() {
    var now = Date.now() + clockOffset;
    elements.forEach(function (el) {
      var remaining = Date.parse(el.dataset.countdown) - now;
      el.textContent = (el.dataset.prefix || "") + format(remaining);
      if (remaining <= 0 && !reloading) {
        reloading = true;
        setTimeout(function () { window.location.reload(); }, 1500);
      }
    });
  }

  if (elements.length) {
    tick();
    setInterval(tick, 1000);
  }
})();
