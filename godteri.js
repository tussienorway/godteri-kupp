/* GodteriKupp: hent norske godteritilbud fra eTilbudsavis.
   Kan lastes fra andre nettsteder:
   <script src="https://tussienorway.github.io/godteri-kupp/godteri.js"></script>
   GodteriKupp.hent().then(function (offers) { ... })
*/
(function (root) {
  var QUERIES = [
    "godteri", "smågodt", "sjokolade", "lakris", "karamell", "haribo", "nidar",
    "freia", "twist", "snickers", "kinder", "malaco", "drops", "seigmenn",
    "tyggegummi", "bounty", "twix", "halloween", "daim", "kvikk lunsj"
  ];
  var CANDY_RE = /godte|sjokolade|lakris|karamell|bolsje|drops|seigmenn|vingummi|marshmallow|tyggis|tyggegummi|sukkertøy|sukkertoy|candy|sweets?|haribo|nidar|freia|\btwist\b|snickers|\bbounty\b|\btwix\b|kit\s?kat|kvikk|\bnon\s?stop\b|\bsmash\b|\bstratos\b|\bhobby\b|malaco|smørbukk|smorbukk|\bkinder\b|skittles|wine\s?gums?|lakrids|fruktisar|gottes|\bdaim\b|\bjapp\b|\blion\b|toblerone|after eight|m&m|party mix|smågodt|smagodt|godis|påskeegg|paseegg|\bskum\b|\bgel[eé]\b|\bmars\b|marsipan|\bjelly\b|toffifee|toffee|lakrisal|fruit dips|dippies/i;
  var EXCLUDE_RE = /sjokolademelk|kakaomelk|yoghurt|youghurt|pudding|iskrem|\bis\b|ispinne|fløte|pålegg|nutella|chips|potetgull|nøtt|peanøtt|\bbrus\b|\bøl\b|\bvin\b|\bsaft\b|juice|\bkaffe\b|kakemiks|frokost|pizza|grandiosa|pølse|\bost\b|\bmelk\b|smoothie|kjeks|\bkake\b|boller|\bbrød\b|knekkebrød|vafler|sjokoladesaus|kokesjokolade|bake|kakao\b|pulver|dressing|müsli|musli|havregryn|donut|proteinbar|halslinser|halstablett|\btoddy\b/i;
  var NONFOOD_RE = /halskjede|bøtte|kostyme|polyester|lysende|edderkopp|\bpynt\b|julepynt|ledlys|godteribolle|\bbolle\b|serviett|stearin|ballong|peruk|tekstil|løpelengde|ansiktsmaling|\bsminke\b|tallerk|verktøy|spøkelse/i;
  var BAR_RE = /sjokoladekake|kvikk\s*lunsj|\bsmash\b|\bstratos\b|\bhobby\b|\btwist\b|\bfreia\b|\bnidar\b|\bdaim\b|\bjapp\b|\blion\b|\bbounty\b|snickers|\btwix\b|\bmars\b|kit\s?kat|after eight|toblerone/i;
  var COLORS = {
    "REMA 1000": "#e30613", "KIWI": "#2f9e44", "Extra": "#d23732", "MENY": "#e4002b",
    "Meny": "#e4002b", "SPAR": "#d62828", "Joker": "#0b7a52", "Coop Prix": "#c99212",
    "Coop Mega": "#0b5e56", "Obs": "#004993", "Bunnpris": "#c9a227", "Europris": "#e10600",
    "Nille": "#7a1f6d", "Normal": "#111111", "Matkroken": "#1f6b4a", "Gigaboks": "#5b3a29"
  };

  function isCandy(heading, description) {
    heading = heading || "";
    description = description || "";
    var text = heading + "\n" + description;
    if (/\bEUR\b/.test(description)) return false;
    if (NONFOOD_RE.test(heading) || NONFOOD_RE.test(description.slice(0, 240))) return false;
    if (EXCLUDE_RE.test(heading)) return false;
    if (/\b(cola|brus|øl)\b/i.test(description) && !CANDY_RE.test(heading)) return false;
    if (BAR_RE.test(heading) && !/kakemiks|\bbake\b/i.test(text)) return true;
    if (CANDY_RE.test(heading)) return true;
    if (/kalender/i.test(heading) && /sjokolade|godteri/i.test(description)) return true;
    if (/gott\s*(&|og)\s*blandet/i.test(text)) return true;
    if (/utvalg|godteri|godtepose|halloweenpose|party mix/i.test(heading) && CANDY_RE.test(description)) return true;
    return false;
  }

  function slugFor(offer) {
    var markets = (offer.dealer && offer.dealer.markets) || [];
    var i;
    for (i = 0; i < markets.length; i++) {
      if (markets[i].country_code === "NO" && markets[i].slug) return markets[i].slug;
    }
    return markets[0] && markets[0].slug;
  }

  function offerUrl(offer) {
    var slug = slugFor(offer);
    if (slug && offer.id && offer.catalog_id) {
      return "https://etilbudsavis.no/" + encodeURIComponent(slug) +
        "?publication=" + encodeURIComponent(offer.catalog_id) +
        "&offer=" + encodeURIComponent(offer.id);
    }
    return "https://etilbudsavis.no/soek/" + encodeURIComponent(offer.heading || "godteri");
  }

  function normalize(offer) {
    var dealer = offer.dealer || {};
    var country = dealer.country && dealer.country.id;
    var pricing = offer.pricing || {};
    var price = pricing.price;
    var heading = (offer.heading || "").trim();
    var description = (offer.description || "").trim();
    var before;
    var store;
    var images;
    if (country !== "NO" || pricing.currency !== "NOK") return null;
    if (typeof price !== "number" || price <= 0 || price >= 500) return null;
    if (!heading || !isCandy(heading, description)) return null;
    if (offer.run_till && new Date(offer.run_till).getTime() < Date.now()) return null;
    before = pricing.pre_price;
    if (typeof before !== "number" || before <= price) before = null;
    store = (dealer.name || "Ukjent butikk").trim();
    images = offer.images || {};
    return {
      id: offer.id,
      name: heading,
      description: description.slice(0, 280),
      price: Math.round(price * 100) / 100,
      before: before == null ? null : Math.round(before * 100) / 100,
      savings: before == null ? null : Math.round((before - price) * 100) / 100,
      store: store,
      color: COLORS[store] || "#6b3a2a",
      image: images.view || images.thumb || null,
      logo: (offer.branding && offer.branding.logo) || dealer.logo || null,
      valid_from: offer.run_from || null,
      valid_until: offer.run_till || null,
      url: offerUrl(offer),
      currency: "NOK"
    };
  }

  function fetchPage(query, offset) {
    var url = "https://squid-api.tjek.com/v2/offers/search?query=" +
      encodeURIComponent(query) + "&limit=100&offset=" + offset;
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (res) {
      if (!res.ok) throw new Error("Søk feilet (" + res.status + ")");
      return res.json();
    });
  }

  function pool(jobs, limit) {
    var i = 0;
    var running = 0;
    var out = [];
    return new Promise(function (resolve, reject) {
      function next() {
        if (i >= jobs.length && running === 0) {
          resolve(out);
          return;
        }
        while (running < limit && i < jobs.length) {
          (function (job) {
            running += 1;
            job().then(function (value) {
              out.push(value);
              running -= 1;
              next();
            }).catch(reject);
          })(jobs[i]);
          i += 1;
        }
      }
      next();
    });
  }

  function hent() {
    var jobs = [];
    QUERIES.forEach(function (query) {
      [0, 100, 200].forEach(function (offset) {
        jobs.push(function () { return fetchPage(query, offset); });
      });
    });
    return pool(jobs, 4).then(function (pages) {
      var seen = {};
      var offers = [];
      pages.forEach(function (rows) {
        (rows || []).forEach(function (row) {
          var item;
          if (!row || !row.id || seen[row.id]) return;
          seen[row.id] = true;
          item = normalize(row);
          if (!item) return;
          var key = item.store.toLowerCase() + "|" + item.name.toLowerCase() + "|" + item.price;
          if (seen[key]) return;
          seen[key] = true;
          offers.push(item);
        });
      });
      offers.sort(function (a, b) { return a.price - b.price || a.name.localeCompare(b.name, "nb"); });
      return offers;
    });
  }

  root.GodteriKupp = {
    hent: hent,
    isCandy: isCandy,
    normalize: normalize,
    queries: QUERIES
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
