from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import unicodedata

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# Map des auteurs connus sur UQAM
AUTHOR_MAP = {
    # Philosophie / Littérature française
    "camus":                 "camus_albert",
    "albert camus":          "camus_albert",
    "sartre":                "sartre_jean-paul",
    "jean paul sartre":      "sartre_jean-paul",
    "jean-paul sartre":      "sartre_jean-paul",
    "simone de beauvoir":    "beauvoir_simone_de",
    "beauvoir":              "beauvoir_simone_de",
    "hugo":                  "hugo_victor",
    "victor hugo":           "hugo_victor",
    "zola":                  "zola_emile",
    "emile zola":            "zola_emile",
    "balzac":                "balzac_honore_de",
    "honore de balzac":      "balzac_honore_de",
    "flaubert":              "flaubert_gustave",
    "gustave flaubert":      "flaubert_gustave",
    "proust":                "proust_marcel",
    "marcel proust":         "proust_marcel",
    "baudelaire":            "baudelaire_charles",
    "charles baudelaire":    "baudelaire_charles",
    "moliere":               "moliere",
    "racine":                "racine_jean",
    "jean racine":           "racine_jean",
    "voltaire":              "voltaire",
    "rousseau":              "rousseau_jj",
    "jean-jacques rousseau": "rousseau_jj",
    "montaigne":             "montaigne",
    "pascal":                "pascal_blaise",
    "blaise pascal":         "pascal_blaise",
    "descartes":             "descartes_rene",
    "rene descartes":        "descartes_rene",
    # Littérature étrangère / traduite
    "kafka":                 "kafka_franz",
    "franz kafka":           "kafka_franz",
    "orwell":                "orwell_george",
    "george orwell":         "orwell_george",
    "dostoievski":           "dostoievski_fedor",
    "dostoevsky":            "dostoievski_fedor",
    "dostoievsky":           "dostoievski_fedor",
    "fedor dostoievski":     "dostoievski_fedor",
    # Sciences sociales
    "freud":                 "freud_sigmund",
    "sigmund freud":         "freud_sigmund",
    "nietzsche":             "nietzsche_friedrich",
    "friedrich nietzsche":   "nietzsche_friedrich",
    "durkheim":              "durkheim_emile",
    "emile durkheim":        "durkheim_emile",
    "marx":                  "marx_karl",
    "karl marx":             "marx_karl",
    "weber":                 "weber_max",
    "max weber":             "weber_max",
    "bourdieu":              "bourdieu_pierre",
    "pierre bourdieu":       "bourdieu_pierre",
    "tocqueville":           "tocqueville_alexis_de",
    "machiavel":             "machiavel",
    "montesquieu":           "montesquieu",
    "platon":                "platon",
    "aristote":              "aristote",
    "hegel":                 "hegel_georg_wilhelm_friedrich",
    "kant":                  "kant_emmanuel",
    "emmanuel kant":         "kant_emmanuel",
}

BASE = "https://classiques.uqam.ca/classiques/"


def normalize(s: str) -> str:
    s = s.lower().strip()
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )


def get_uqam_path(author: str) -> str:
    n = normalize(author)

    # Correspondance directe
    if n in AUTHOR_MAP:
        return AUTHOR_MAP[n]

    # Essai sur chaque mot (nom de famille seul)
    for part in n.split():
        if part in AUTHOR_MAP:
            return AUTHOR_MAP[part]

    # Construction automatique: prenom_nom → nom_prenom
    parts = n.split()
    if len(parts) >= 2:
        return f"{parts[-1]}_{parts[0]}"

    return n.replace(' ', '_').replace('-', '_')


def scrape_uqam(author: str, title: str = "") -> list:
    if not HAS_DEPS:
        return []

    path = get_uqam_path(author)
    url  = f"{BASE}{path}/{path}.html"

    try:
        r = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.content, "html.parser")
        results = []
        seen    = set()

        # Mots-clés du titre pour filtrer (si fourni)
        title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue

            text = a.get_text(" ", strip=True)
            if not text or len(text) < 3:
                continue

            # URL absolue
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"https://classiques.uqam.ca{href}"
            else:
                full_url = f"{BASE}{path}/{href}"

            if full_url in seen:
                continue
            seen.add(full_url)

            # Filtrage par titre
            if title_words:
                text_n = normalize(text)
                if not any(w in text_n for w in title_words):
                    continue

            results.append({
                "title":  text,
                "author": author,
                "url":    full_url,
                "format": "PDF",
                "source": "UQAM",
                "lang":   "FR",
                "cta":    "Ouvrir dans Apple Books",
                "grey":   False,
            })

        return results[:8]

    except Exception:
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs     = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)

        author = params.get("author", [""])[0].strip()
        title  = params.get("title",  [""])[0].strip()

        data = scrape_uqam(author, title) if author else []
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Désactive les logs Vercel inutiles
