/*
 * Live auction page.
 *
 * - Opens a WebSocket to /ws/auctions/<id>/ and keeps it open.
 * - Draws every update the server sends (snapshot, bid_accepted, state).
 * - Sends bids as {"type": "bid", "amount": "...", "client_bid_id": "<uuid>"}.
 * - Reconnects automatically after a network drop (1s, 2s, 4s ... max 15s) and
 *   resyncs; the server sends a fresh snapshot on every connect.
 * - Asks for a resync when the tab becomes visible again (laptop woke up, etc.).
 *
 * The server is always the authority: this script never decides whether a bid
 * is valid, it only shows what the server says.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var wsPath = script.dataset.wsPath;
  var state = JSON.parse(document.getElementById("initial-state").textContent);

  // Close codes from auctions/consumers.py: these mean "don't retry".
  var FATAL_CLOSE = { 4401: "Please log in again.", 4403: "You are not a participant in this auction.",
                      4404: "Auction not found." };

  var el = function (id) { return document.getElementById(id); };
  var ui = {
    phase: el("phase"), countdown: el("countdown"), countdownLabel: el("countdown-label"),
    highest: el("highest"), minimum: el("minimum"), deadline: el("deadline"),
    extended: el("extended-note"), connection: el("connection"), bids: el("bids"),
    form: el("bid-form"), amount: el("bid-amount"), button: el("bid-button"),
    minButton: el("bid-min"), message: el("bid-message"), result: el("result"),
    bidPanel: el("bid-panel"), biddingClosed: el("bidding-closed"), minimumBlock: el("minimum-block")
  };

  var socket = null;
  var connected = false;
  var retryDelay = 1000;
  var clockOffset = 0;           // server clock minus browser clock (ms)
  var pendingBidId = null;       // client_bid_id of the bid waiting for a result
  var pendingTimer = null;
  var lastSyncRequest = 0;
  var leader = null;             // anonymous code of the current highest bidder
  var lastSuggested = ui.amount ? ui.amount.value : null;  // last value WE put in the bid box

  var DEADLINE_FORMAT = { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric",
                          hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };

  // ---------------------------------------------------------------- helpers

  function rupees(value) {
    if (value === null || value === undefined) { return "No bids yet"; }
    return "Rs. " + Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function timeOnly(iso) {
    // "2026-10-09T20:15:03.120000+05:30" -> "20:15:03" (already in IST from the server)
    return iso ? iso.substring(11, 19) : "";
  }

  function newBidId() {
    if (window.crypto && crypto.randomUUID) { return crypto.randomUUID(); }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0;
      return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  function setMessage(text, ok) {
    if (!ui.message) { return; }
    ui.message.textContent = text;
    ui.message.className = "bid-message " + (ok ? "msg-ok" : "msg-err");
  }

  function canBid() {
    return connected && state.phase === "LIVE" && state.you && pendingBidId === null;
  }

  function refreshControls() {
    if (!ui.button) { return; }
    ui.button.disabled = !canBid();
    ui.minButton.disabled = !canBid();
  }

  // ---------------------------------------------------------------- drawing

  function applyState(s) {
    var previousDeadline = state.end_time;
    Object.assign(state, s);
    if (s.server_now) { clockOffset = Date.parse(s.server_now) - Date.now(); }

    ui.phase.textContent = state.phase_label;
    ui.phase.className = "badge badge-" + state.phase.toLowerCase();
    ui.highest.textContent = rupees(state.highest_bid);
    ui.minimum.textContent = rupees(state.minimum_next_bid);
    ui.deadline.textContent = new Date(state.end_time).toLocaleString("en-GB", DEADLINE_FORMAT);
    if (previousDeadline && state.end_time !== previousDeadline && s.extended) {
      ui.extended.hidden = false;
    }
    drawResult(state.result);
    suggestMinimum();
    tick();
    refreshControls();
  }

  function drawResult(result) {
    // Same wording as the server-rendered panel in auction_room.html.
    var finished = Boolean(result);
    if (ui.bidPanel) { ui.bidPanel.hidden = finished; }
    if (ui.biddingClosed) { ui.biddingClosed.hidden = !finished; }
    if (ui.minimumBlock) { ui.minimumBlock.hidden = finished; }
    if (!ui.result) { return; }
    if (!result) { ui.result.hidden = true; return; }
    var title, text;
    if (result.outcome === "won" && result.bidder === state.you) {
      title = "Congratulations, you won!";
      text = "Your bid of " + rupees(result.amount) + " was the highest. Details have been emailed to you.";
    } else if (result.outcome === "won") {
      title = "Auction closed";
      text = "Won by " + result.bidder + " with " + rupees(result.amount) + ".";
    } else if (result.outcome === "no_bids") {
      title = "Auction closed";
      text = "No valid bids were placed. The quarter remains vacant.";
    } else {
      title = "Auction cancelled";
      text = "This auction was cancelled by the auction office.";
    }
    ui.result.innerHTML = "";
    var h = document.createElement("h2");
    h.textContent = title;
    var p = document.createElement("p");
    p.textContent = text;
    ui.result.appendChild(h);
    ui.result.appendChild(p);
    ui.result.hidden = false;
    if (ui.message && result.outcome !== "won") { ui.message.textContent = ""; }
  }

  function suggestMinimum() {
    // Keep the bid box at the new minimum, unless the bidder typed their own
    // higher amount that is still valid.
    if (!ui.amount || state.minimum_next_bid === null) { return; }
    var typed = Number(ui.amount.value);
    var minimum = Number(state.minimum_next_bid);
    var untouched = ui.amount.value === lastSuggested || ui.amount.value === "";
    if (untouched || isNaN(typed) || typed < minimum) {
      lastSuggested = minimum.toFixed(2);
      ui.amount.value = lastSuggested;
    }
  }

  function updateLeader(newLeader) {
    if (state.you && leader === state.you && newLeader && newLeader !== state.you) {
      setMessage("You have been outbid by " + newLeader + ". The minimum bid is now " +
                 rupees(state.minimum_next_bid) + ".", false);
    }
    leader = newLeader;
  }

  function addBidRow(bid, highlight) {
    var empty = ui.bids.querySelector(".empty");
    if (empty) { empty.remove(); }
    var row = document.createElement("tr");
    [timeOnly(bid.time), bid.bidder + (bid.bidder === state.you ? " (you)" : ""),
     Number(bid.amount).toLocaleString("en-IN", { minimumFractionDigits: 2 })].forEach(function (text, i) {
      var cell = document.createElement("td");
      cell.textContent = text;      // textContent, never innerHTML: no script injection
      if (i === 2) { cell.className = "num"; }
      row.appendChild(cell);
    });
    if (bid.bidder === state.you) { row.className = "mine"; }
    if (highlight) { row.classList.add("flash"); }
    ui.bids.insertBefore(row, ui.bids.firstChild);
  }

  function drawAllBids(bids) {
    ui.bids.innerHTML = "";
    if (!bids.length) {
      ui.bids.innerHTML = '<tr class="empty"><td colspan="3" class="muted">No bids yet.</td></tr>';
      return;
    }
    bids.slice().reverse().forEach(function (b) { addBidRow(b, false); });
  }

  // ---------------------------------------------------------------- countdown

  function format(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return pad(h) + ":" + pad(m) + ":" + pad(s);
  }

  function tick() {
    var now = Date.now() + clockOffset;
    if (state.phase === "UPCOMING") {
      ui.countdownLabel.textContent = "Starts in";
      var toStart = Date.parse(state.start_time) - now;
      ui.countdown.textContent = format(toStart);
      if (toStart <= 0) { requestSync(); }
    } else if (state.phase === "LIVE") {
      ui.countdownLabel.textContent = "Time left";
      var left = Date.parse(state.end_time) - now;
      ui.countdown.textContent = format(left);
      ui.countdown.classList.toggle("urgent", left <= 60000);
      if (left <= 0) { requestSync(); }
    } else {
      ui.countdownLabel.textContent = "Time left";
      ui.countdown.textContent = "00:00:00";
      ui.countdown.classList.remove("urgent");
    }
  }

  function requestSync() {
    // A deadline passed on our clock: ask the server (at most every 3 s) until
    // it confirms the new phase. The server decides, not the browser.
    var now = Date.now();
    if (now - lastSyncRequest < 3000) { return; }
    lastSyncRequest = now;
    send({ type: "sync" });
  }

  // ---------------------------------------------------------------- socket

  function send(message) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  function setConnection(text, cls) {
    ui.connection.textContent = text;
    ui.connection.className = "conn " + cls;
  }

  function connect() {
    var scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
    socket = new WebSocket(scheme + window.location.host + wsPath);

    socket.onopen = function () {
      connected = true;
      retryDelay = 1000;
      setConnection("Connected", "conn-ok");
      refreshControls();
    };

    socket.onmessage = function (event) {
      var msg = JSON.parse(event.data);
      if (msg.type === "snapshot") {
        applyState(msg);
        drawAllBids(msg.bids || []);
        updateLeader(msg.bids && msg.bids.length ? msg.bids[0].bidder : null);
      } else if (msg.type === "bid_accepted") {
        addBidRow(msg.bid, true);
        applyState(msg);
        updateLeader(msg.bid.bidder);
      } else if (msg.type === "state") {
        applyState(msg);
      } else if (msg.type === "bid_result") {
        if (msg.client_bid_id === pendingBidId) {
          clearTimeout(pendingTimer);
          pendingBidId = null;
        }
        setMessage(msg.message, msg.ok);
        refreshControls();
      } else if (msg.type === "error") {
        setMessage(msg.message, false);
      }
    };

    socket.onclose = function (event) {
      connected = false;
      refreshControls();
      if (FATAL_CLOSE[event.code]) {
        setConnection(FATAL_CLOSE[event.code], "conn-bad");
        return;
      }
      setConnection("Reconnecting…", "conn-wait");
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    };
  }

  // ---------------------------------------------------------------- bidding

  if (ui.form) {
    ui.form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!canBid()) { return; }
      pendingBidId = newBidId();
      var sent = send({ type: "bid", amount: ui.amount.value, client_bid_id: pendingBidId });
      if (!sent) {
        pendingBidId = null;
        setMessage("Not connected. Your bid was not sent.", false);
        return;
      }
      setMessage("Sending bid…", true);
      refreshControls();
      // If no answer arrives (connection dropped), unlock the button and resync.
      pendingTimer = setTimeout(function () {
        pendingBidId = null;
        setMessage("No reply from the server. Check the bid history before bidding again.", false);
        send({ type: "sync" });
        refreshControls();
      }, 10000);
    });

    ui.minButton.addEventListener("click", function () {
      lastSuggested = Number(state.minimum_next_bid).toFixed(2);
      ui.amount.value = lastSuggested;
      ui.amount.focus();
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") { send({ type: "sync" }); }
  });

  applyState(state);
  setInterval(tick, 1000);
  connect();
})();
