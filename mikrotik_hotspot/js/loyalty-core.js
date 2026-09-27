(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FasoLoyalty = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function normalizeMac(value) {
    return String(value || "").trim().toUpperCase().replace(/[^0-9A-F]/g, "");
  }

  function deviceIdentity(rawMac) {
    var raw = String(rawMac || "");
    var normalized = normalizeMac(raw);
    if (raw.indexOf("$(") !== -1 || normalized.length !== 12) return "DEMO-DEVICE-01";
    return normalized;
  }

  function displayMac(deviceId) {
    if (deviceId === "DEMO-DEVICE-01") return "Appareil de test local";
    return "Appareil MikroTik · " + String(deviceId).match(/.{1,2}/g).join(":");
  }

  function loyaltyKey(prefix, deviceId, planCode) {
    return String(prefix) + String(deviceId) + ":" + String(planCode);
  }

  function nextPurchase(currentCount, threshold) {
    var limit = Number(threshold) || 5;
    var current = Math.max(0, Math.min(limit - 1, Number(currentCount) || 0));
    var next = current + 1;
    var bonusEarned = next >= limit;
    return {
      count: bonusEarned ? 0 : next,
      bonusEarned: bonusEarned,
    };
  }

  return {
    normalizeMac: normalizeMac,
    deviceIdentity: deviceIdentity,
    displayMac: displayMac,
    loyaltyKey: loyaltyKey,
    nextPurchase: nextPurchase,
  };
});
