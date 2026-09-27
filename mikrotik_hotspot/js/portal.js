(function () {
  "use strict";

  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-tab]"));
  var panels = Array.prototype.slice.call(document.querySelectorAll(".tab-panel"));
  var testMode = document.getElementById("test-mode");

  function activateTab(button) {
    tabs.forEach(function (tab) {
      var selected = tab === button;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", selected ? "true" : "false");
    });

    panels.forEach(function (panel) {
      var active = panel.id === button.getAttribute("data-tab");
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
      if (!active && panel.id === "media-panel") {
        panel.querySelectorAll("video, audio").forEach(function (player) { player.pause(); });
      }
    });
    if (testMode) testMode.hidden = button.getAttribute("data-tab") === "media-panel";
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { activateTab(tab); });
  });

  var demoResult = document.getElementById("demo-result");
  var demoTitle = document.getElementById("demo-title");
  var demoMessage = document.getElementById("demo-message");
  var demoClose = document.getElementById("demo-close");

  window.showDemoResult = function (title, message) {
    if (!demoResult) return;
    demoTitle.textContent = title;
    demoMessage.textContent = message;
    demoResult.hidden = false;
    demoResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  if (demoClose) {
    demoClose.addEventListener("click", function () { demoResult.hidden = true; });
  }

  var routerError = document.getElementById("router-error");
  if (routerError) {
    var errorMessage = routerError.getAttribute("data-error") || "";
    if (errorMessage && errorMessage.indexOf("$(") === -1) {
      document.getElementById("router-error-message").textContent = errorMessage;
      routerError.hidden = false;
    }
  }

  var trialLink = document.getElementById("trial-link");
  if (trialLink && document.body.getAttribute("data-trial") === "yes") {
    trialLink.hidden = false;
  }

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var dots = Array.prototype.slice.call(document.querySelectorAll("[data-slide-index]"));
  var slideIndex = 0;
  var slideTimer;

  function showSlide(nextIndex) {
    if (!slides.length) return;
    slideIndex = (nextIndex + slides.length) % slides.length;
    slides.forEach(function (slide, index) { slide.classList.toggle("is-active", index === slideIndex); });
    dots.forEach(function (dot, index) { dot.classList.toggle("is-active", index === slideIndex); });
  }

  function startSlides() {
    window.clearInterval(slideTimer);
    slideTimer = window.setInterval(function () { showSlide(slideIndex + 1); }, 6500);
  }

  document.querySelectorAll("[data-slide]").forEach(function (button) {
    button.addEventListener("click", function () {
      showSlide(slideIndex + (button.getAttribute("data-slide") === "next" ? 1 : -1));
      startSlides();
    });
  });

  dots.forEach(function (dot) {
    dot.addEventListener("click", function () {
      showSlide(Number(dot.getAttribute("data-slide-index")) || 0);
      startSlides();
    });
  });

  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) startSlides();

  var mediaViewer = document.getElementById("media-viewer");
  var mediaList = document.getElementById("media-list");
  var filmsAccessLink = document.getElementById("films-access-link");
  var mediaItems = (window.WifiZoneMedia || []).filter(function (item) {
    return item && item.enabled !== false && item.src && item.type;
  });
  var mediaButtons = [];

  if (filmsAccessLink) {
    filmsAccessLink.href = document.body.getAttribute("data-films-url") || "films.html";
    if (document.body.getAttribute("data-payment-mode") === "demo") {
      filmsAccessLink.firstChild.nodeValue = "Voir le catalogue test ";
    }
  }

  function mediaTypeLabel(type) {
    if (type === "video") return "VIDÉO";
    if (type === "audio") return "AUDIO";
    if (type === "link") return "LIEN";
    return "IMAGE";
  }

  function renderMedia(index) {
    if (!mediaViewer || !mediaItems.length) return;
    var item = mediaItems[index] || mediaItems[0];
    mediaViewer.innerHTML = "";
    mediaViewer.setAttribute("aria-label", (item.title || "Média WiFi Zone") + ". " + (item.description || "Contenu disponible immédiatement."));

    if (item.type === "video") {
      var video = document.createElement("video");
      video.controls = true;
      video.playsInline = true;
      video.preload = "metadata";
      if (item.poster) video.poster = item.poster;
      video.src = item.src;
      video.setAttribute("aria-label", item.title || "Vidéo WiFi Zone");
      mediaViewer.appendChild(video);
    } else if (item.type === "audio") {
      var audioWrap = document.createElement("div");
      audioWrap.className = "audio-player";
      var audioIcon = document.createElement("span");
      audioIcon.setAttribute("aria-hidden", "true");
      audioIcon.textContent = "♫";
      var audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = item.src;
      audio.setAttribute("aria-label", item.title || "Audio WiFi Zone");
      audioWrap.appendChild(audioIcon);
      audioWrap.appendChild(audio);
      mediaViewer.appendChild(audioWrap);
    } else if (item.type === "link") {
      var link = document.createElement("a");
      link.className = "media-link-card";
      link.href = item.src;
      link.textContent = item.action || "Ouvrir le contenu";
      mediaViewer.appendChild(link);
    } else {
      var image = document.createElement("img");
      image.src = item.src;
      image.alt = item.title || "Visuel WiFi Zone";
      mediaViewer.appendChild(image);
    }

    mediaButtons.forEach(function (button, buttonIndex) {
      var active = buttonIndex === index;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  if (mediaViewer && mediaList) {
    if (!mediaItems.length) {
      mediaViewer.className += " is-empty";
      mediaViewer.textContent = "Aucun média n’est encore disponible.";
    } else {
      mediaItems.forEach(function (item, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "media-item";
        button.setAttribute("aria-pressed", index === 0 ? "true" : "false");

        var type = document.createElement("span");
        type.className = "media-item-type";
        type.textContent = mediaTypeLabel(item.type);
        var text = document.createElement("strong");
        text.textContent = item.title || "Média WiFi Zone";
        button.appendChild(type);
        button.appendChild(text);
        button.addEventListener("click", function () { renderMedia(index); });
        mediaList.appendChild(button);
        mediaButtons.push(button);
      });
      renderMedia(0);
    }
  }

  var plans = Array.prototype.slice.call(document.querySelectorAll('input[name="plan"]'));
  var total = document.getElementById("payment-total");
  var paymentPhone = document.getElementById("payment-phone");
  var loyaltyCount = document.getElementById("loyalty-count");
  var loyaltyStatus = document.getElementById("loyalty-status");
  var loyaltyDevice = document.getElementById("loyalty-device");
  var loyaltySteps = Array.prototype.slice.call(document.querySelectorAll("#loyalty-steps i"));
  var loyaltyReset = document.getElementById("loyalty-reset");
  var loyaltyMemory = {};
  var loyaltyPrefix = "faso-isp-loyalty-mac-v1:";
  var loyaltyCore = window.FasoLoyalty;
  var paymentButton = null;
  var refreshPaymentButton = function () {};

  function deviceIdentity() {
    var rawMac = document.body.getAttribute("data-mac") || "";
    return loyaltyCore.deviceIdentity(rawMac);
  }

  function displayMac(deviceId) {
    return loyaltyCore.displayMac(deviceId);
  }

  function loyaltyKey(deviceId, planCode) {
    return loyaltyCore.loyaltyKey(loyaltyPrefix, deviceId, planCode);
  }

  function readLoyalty(deviceId, planCode) {
    if (!deviceId || !planCode) return 0;
    var key = loyaltyKey(deviceId, planCode);
    try {
      return Math.max(0, Math.min(4, Number(window.localStorage.getItem(key)) || 0));
    } catch (error) {
      return loyaltyMemory[key] || 0;
    }
  }

  function writeLoyalty(deviceId, planCode, value) {
    var key = loyaltyKey(deviceId, planCode);
    try {
      window.localStorage.setItem(key, String(value));
    } catch (error) {
      loyaltyMemory[key] = value;
    }
  }

  function currentPlan() {
    return document.querySelector('input[name="plan"]:checked');
  }

  function updateLoyaltyProgress() {
    if (!loyaltyCount || !loyaltyStatus) return;
    var plan = currentPlan();
    var deviceId = deviceIdentity();
    var count = readLoyalty(deviceId, plan ? plan.value : "");
    loyaltyCount.textContent = count + "/5";
    loyaltySteps.forEach(function (step, index) { step.classList.toggle("is-filled", index < count); });
    if (loyaltyDevice) loyaltyDevice.textContent = displayMac(deviceId);
    loyaltyStatus.textContent = count + " achat" + (count > 1 ? "s" : "") + " sur 5 pour le forfait " + plan.getAttribute("data-label") + ".";
  }

  function recordDemoLoyalty(deviceId, planCode) {
    var progress = loyaltyCore.nextPurchase(readLoyalty(deviceId, planCode), 5);
    writeLoyalty(deviceId, planCode, progress.count);
    updateLoyaltyProgress();
    return progress;
  }

  function updateTotal() {
    var plan = document.querySelector('input[name="plan"]:checked');
    if (!plan || !total) return;
    var price = Number(plan.getAttribute("data-price") || 0);
    total.textContent = price > 0 ? price.toLocaleString("fr-FR") + " F CFA" : "Prix à définir";
    refreshPaymentButton();
  }

  plans.forEach(function (plan) {
    plan.addEventListener("change", function () {
      updateTotal();
      updateLoyaltyProgress();
    });
  });
  if (loyaltyReset) {
    loyaltyReset.addEventListener("click", function () {
      var deviceId = deviceIdentity();
      try {
        var keys = [];
        for (var index = 0; index < window.localStorage.length; index += 1) {
          var storedKey = window.localStorage.key(index);
          if (storedKey && storedKey.indexOf(loyaltyPrefix + deviceId + ":") === 0) keys.push(storedKey);
        }
        keys.forEach(function (key) { window.localStorage.removeItem(key); });
      } catch (error) {
        Object.keys(loyaltyMemory).forEach(function (key) {
          if (key.indexOf(loyaltyPrefix + deviceId + ":") === 0) delete loyaltyMemory[key];
        });
      }
      updateLoyaltyProgress();
      window.showDemoResult("Compteurs réinitialisés", "La progression de test de cet appareil a été remise à zéro pour tous les forfaits.");
    });
  }

  updateLoyaltyProgress();

  var paymentForm = document.getElementById("payment-form");
  if (paymentForm) {
    paymentButton = paymentForm.querySelector('button[type="submit"]');
    var providerInputs = Array.prototype.slice.call(paymentForm.querySelectorAll('input[name="provider"]'));
    var phoneLabel = document.getElementById("payment-phone-label");

    refreshPaymentButton = function () {
      if (!paymentButton) return;
      var selectedPlan = currentPlan();
      var selectedProvider = paymentForm.querySelector('input[name="provider"]:checked');
      var hasPrice = selectedPlan && Number(selectedPlan.getAttribute("data-price") || 0) > 0;
      var isCash = selectedProvider && selectedProvider.value === "cash";
      paymentButton.disabled = !hasPrice;
      if (!hasPrice) {
        paymentButton.innerHTML = "Prix à définir";
      } else if (bodyPaymentMode() === "demo") {
        paymentButton.innerHTML = isCash ? "Simuler la validation du vendeur <span>→</span>" : "Tester le paiement <span>→</span>";
      } else {
        paymentButton.innerHTML = isCash ? "Valider la vente en espèces <span>→</span>" : "Payer et recevoir mon ticket <span>→</span>";
      }
    };

    function updatePaymentMethod() {
      var selectedProvider = paymentForm.querySelector('input[name="provider"]:checked');
      var isCash = selectedProvider && selectedProvider.value === "cash";
      if (paymentPhone) {
        paymentPhone.required = !isCash;
        paymentPhone.placeholder = isCash ? "Facultatif pour les espèces" : "70 00 00 00";
      }
      if (phoneLabel) phoneLabel.textContent = isCash ? "2. Numéro de téléphone (facultatif)" : "2. Numéro de paiement";
      refreshPaymentButton();
    }

    function bodyPaymentMode() {
      return document.body.getAttribute("data-payment-mode");
    }

    providerInputs.forEach(function (input) { input.addEventListener("change", updatePaymentMethod); });
    updatePaymentMethod();
    updateTotal();

    paymentForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!paymentForm.checkValidity()) {
        paymentForm.reportValidity();
        return;
      }

      var body = document.body;
      var plan = paymentForm.querySelector('input[name="plan"]:checked');
      var provider = paymentForm.querySelector('input[name="provider"]:checked');
      var phone = document.getElementById("payment-phone").value.replace(/\s+/g, "");
      var paymentUrl = body.getAttribute("data-payment-url");
      var params = new URLSearchParams();

      if (Number(plan.getAttribute("data-price") || 0) <= 0) {
        window.showDemoResult("Prix à définir", "Le prix du forfait " + plan.getAttribute("data-label") + " doit être renseigné avant d’activer son paiement.");
        return;
      }

      if (body.getAttribute("data-payment-mode") === "demo") {
        var providerName = provider.closest("label").querySelector("strong").textContent;
        var planName = plan.getAttribute("data-label");
        var amount = Number(plan.getAttribute("data-price") || 0).toLocaleString("fr-FR");
        var demoCode = "TEST-" + provider.value.substring(0, 3).toUpperCase() + "-" + String(Date.now()).slice(-4);
        var loyalty = recordDemoLoyalty(deviceIdentity(), plan.value);
        var loyaltyMessage = loyalty.bonusEarned
          ? " Bonus obtenu : 1 ticket " + planName + " offert (simulation)."
          : " Progression bonus : " + loyalty.count + "/5 pour ce forfait.";
        var cashMessage = provider.value === "cash" ? " Validation vendeur simulée." : "";
        window.showDemoResult(
          "Paiement de test réussi",
          providerName + " · " + planName + " · " + amount + " F CFA · Ticket simulé : " + demoCode + ". Aucun argent n’a été débité." + cashMessage + loyaltyMessage
        );
        return;
      }

      params.set("plan", plan.value);
      params.set("phone", phone);
      params.set("provider", provider.value);
      params.set("mac", body.getAttribute("data-mac") || "");
      params.set("ip", body.getAttribute("data-ip") || "");
      params.set("login_url", body.getAttribute("data-login-url") || "");
      params.set("destination", body.getAttribute("data-destination") || "");
      params.set("site_code", body.getAttribute("data-site-code") || "");

      window.location.href = paymentUrl + (paymentUrl.indexOf("?") === -1 ? "?" : "&") + params.toString();
    });
  }

})();

/* ══════════════════════════════════════════════════════════════════════════
 * Bonus fidélité — animation de félicitations (écran + jingle).
 * Interroge le serveur : « cet appareil a-t-il un ticket bonus à fêter ? ».
 * Fonctionne pour les tickets PHYSIQUES comme pour les achats en ligne.
 * Son + animation déclenchés au TAP (autoplay/mini-navigateurs captifs).
 * ══════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";
  var body = document.body;
  var mode = body.getAttribute("data-payment-mode");
  var mac = body.getAttribute("data-mac") || "";
  var site = body.getAttribute("data-site-code") || "";
  var payUrl = body.getAttribute("data-payment-url") || "";
  var loginUrl = body.getAttribute("data-login-url") || "";
  if (mode === "demo") return;                       // pas de bonus réel en démo
  if (!mac || mac.indexOf("$(") !== -1 || !site || !payUrl) return;

  var origin;
  try { origin = new URL(payUrl).origin; } catch (e) { return; }
  var q = "mac=" + encodeURIComponent(mac) + "&site_code=" + encodeURIComponent(site);

  fetch(origin + "/wifi/bonus/?" + q, { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (d) { if (d && d.has_bonus && d.code) showBonus(d.code, d.duration_label || ""); })
    .catch(function () {});

  function injectStyle() {
    if (document.getElementById("wzc-style")) return;
    var css =
      '#wzc-gift{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:10000;' +
      'padding:14px 22px;border:0;border-radius:999px;cursor:pointer;color:#3a2600;' +
      'font:800 1rem Inter,system-ui,sans-serif;background:linear-gradient(135deg,#ffcb3f,#f2b416);' +
      'box-shadow:0 12px 34px rgba(242,180,22,.5);animation:wzc-pulse 1.4s ease-in-out infinite}' +
      '@keyframes wzc-pulse{0%,100%{transform:translateX(-50%) scale(1)}50%{transform:translateX(-50%) scale(1.06)}}' +
      '#wzc-ovl{position:fixed;inset:0;z-index:10001;display:none;place-items:center;padding:20px;' +
      'background:rgba(4,10,20,.86)}#wzc-ovl.on{display:grid}' +
      '#wzc-cv{position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:10002}' +
      '.wzc-card{position:relative;z-index:10003;width:min(430px,100%);text-align:center;padding:30px 24px;' +
      'color:#fff;background:linear-gradient(160deg,#12233b,#0b1626);border:1px solid rgba(242,180,22,.4);' +
      'border-radius:26px;box-shadow:0 30px 80px rgba(0,0,0,.5)}' +
      '.wzc-emo{font-size:3.2rem;line-height:1;animation:wzc-pop .6s ease}' +
      '@keyframes wzc-pop{0%{transform:scale(0)}70%{transform:scale(1.25)}100%{transform:scale(1)}}' +
      '.wzc-card h2{margin:10px 0 4px;font-size:1.5rem;color:#ffcb3f}' +
      '.wzc-card p{margin:0 0 8px;color:#cfe0f0;font-size:.95rem}' +
      '.wzc-code{margin:16px 0;padding:16px;background:#0a1524;border:1px dashed #ffcb3f;border-radius:14px;' +
      'font-size:2rem;font-weight:900;letter-spacing:.12em;color:#fff}' +
      '.wzc-btn{display:block;width:100%;min-height:50px;margin-top:12px;padding:13px;border:0;border-radius:13px;' +
      'cursor:pointer;color:#10151c;font:850 1rem Inter,system-ui,sans-serif;' +
      'background:linear-gradient(135deg,#ffcb3f,#e59900)}' +
      '.wzc-close{margin-top:10px;background:transparent;border:0;color:#9aabc0;cursor:pointer;font-size:.85rem;text-decoration:underline}';
    var st = document.createElement("style");
    st.id = "wzc-style"; st.textContent = css;
    document.head.appendChild(st);
  }

  function jingle() {
    try {
      var C = window.AudioContext || window.webkitAudioContext; if (!C) return;
      var x = new C(), n = x.currentTime, f = [523.25, 659.25, 783.99, 1046.5];
      f.forEach(function (hz, i) {
        var o = x.createOscillator(), g = x.createGain();
        o.type = "triangle"; o.frequency.value = hz;
        var t = n + i * 0.12;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.25, t + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.38);
        o.connect(g); g.connect(x.destination); o.start(t); o.stop(t + 0.42);
      });
    } catch (e) {}
  }

  function confetti() {
    var cv = document.getElementById("wzc-cv"); if (!cv) return;
    var c = cv.getContext("2d");
    var W = cv.width = window.innerWidth, H = cv.height = window.innerHeight;
    var col = ["#f2b416", "#24c7e8", "#31d58b", "#ff6b72", "#ffcb3f", "#ffffff"], ps = [];
    for (var i = 0; i < 140; i++) ps.push({ x: Math.random() * W, y: -Math.random() * H, r: 4 + Math.random() * 6,
      c: col[i % col.length], v: 2 + Math.random() * 4, a: Math.random() * 6.28, s: (Math.random() - 0.5) * 0.25 });
    var t0 = Date.now();
    (function loop() {
      c.clearRect(0, 0, W, H);
      ps.forEach(function (p) { p.y += p.v; p.a += p.s; p.x += Math.sin(p.a);
        c.save(); c.translate(p.x, p.y); c.rotate(p.a); c.fillStyle = p.c;
        c.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 0.62); c.restore(); });
      if (Date.now() - t0 < 4800) requestAnimationFrame(loop); else c.clearRect(0, 0, W, H);
    })();
  }

  function showBonus(code, dur) {
    injectStyle();
    var gift = document.createElement("button");
    gift.id = "wzc-gift"; gift.type = "button"; gift.textContent = "🎁 Ouvrir mon cadeau";

    var ovl = document.createElement("div");
    ovl.id = "wzc-ovl"; ovl.setAttribute("role", "dialog"); ovl.setAttribute("aria-modal", "true");
    ovl.innerHTML =
      '<canvas id="wzc-cv"></canvas>' +
      '<div class="wzc-card">' +
      '<div class="wzc-emo">🎉</div><h2>Félicitations !</h2>' +
      '<p>Merci de votre fidélité 🙏</p>' +
      '<p>Vous avez gagné un ticket <b></b> offert. Voici votre code cadeau :</p>' +
      '<div class="wzc-code"></div>' +
      '<button class="wzc-btn" type="button">Utiliser ce code maintenant</button>' +
      '<button class="wzc-close" type="button">Fermer</button>' +
      '</div>';
    document.body.appendChild(gift);
    document.body.appendChild(ovl);
    ovl.querySelector(".wzc-card b").textContent = dur;
    ovl.querySelector(".wzc-code").textContent = code;

    function open() {
      ovl.classList.add("on"); gift.style.display = "none"; jingle(); confetti();
      // marque le bonus comme annoncé côté serveur (ne se répétera plus)
      fetch(origin + "/wifi/bonus/?" + q + "&ack=1&code=" + encodeURIComponent(code), { cache: "no-store" }).catch(function () {});
    }
    gift.addEventListener("click", open);
    ovl.querySelector(".wzc-close").addEventListener("click", function () { ovl.classList.remove("on"); });
    ovl.querySelector(".wzc-btn").addEventListener("click", function () {
      // pré-remplit le code dans l'onglet « J'ai déjà un ticket »
      var input = document.getElementById("ticket-code");
      var tab = document.getElementById("ticket-tab");
      if (input) input.value = code;
      if (tab) tab.click();
      ovl.classList.remove("on");
      if (input) { input.focus(); input.scrollIntoView({ behavior: "smooth", block: "center" }); }
    });
  }
})();
