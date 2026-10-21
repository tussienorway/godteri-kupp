# Godterikupp

Godteritilbud under 120 kr fra norske kundeaviser. Siden virker i nettleseren på mobil og PC. Andre nettsteder kan hente tallene eller bygge inn siden.

Åpne: https://tussienorway.github.io/godteri-kupp/

Prisene kommer fra [eTilbudsavis](https://etilbudsavis.no/soek/godteri). Det er kundeavispris, ikke hyllepris, og utvalget varierer mellom butikker.

## Bruk fra et annet nettsted

JSON, med CORS, så `fetch` virker fra andre domener:

```
https://tussienorway.github.io/godteri-kupp/data/offers.json
```

Ferske tilbud rett i nettleseren, uten egen server. Scriptet er vårt eget og endres med repoet, derfor er det ingen fast integrity-hash:

```html
<script src="https://tussienorway.github.io/godteri-kupp/godteri.js"></script>
<script>
  GodteriKupp.hent().then(function (offers) {
    var under = offers.filter(function (o) { return o.price < 120; });
    console.log(under);
  });
</script>
```

Bygg inn siden:

```html
<iframe src="https://tussienorway.github.io/godteri-kupp/" title="Godterikupp" style="width:100%;height:800px;border:0"></iframe>
```

## Kjør lokalt

```
python server.py
```

Åpne http://127.0.0.1:8765

`python server.py --snapshot` skriver `data/offers.json`. GitHub Actions gjør det samme hver sjette time.
