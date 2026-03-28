"""
Scraper UQAM — stdlib uniquement.
Stratégie : page auteur → liens relatifs HTML → remplace .html par .pdf directement.
"""
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import urllib.request
import unicodedata
from html.parser import HTMLParser

UQAM_BASE = "https://classiques.uqam.ca/classiques/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

AUTHOR_MAP = {
    "camus":                 "camus_albert",
    "albert camus":          "camus_albert",
    "sartre":                "sartre_jean-paul",
    "jean paul sartre":      "sartre_jean-paul",
    "jean-paul sartre":      "sartre_jean-paul",
    "beauvoir":              "beauvoir_simone_de",
    "simone de beauvoir":    "beauvoir_simone_de",
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
    "voltaire":              "voltaire",
    "rousseau":              "rousseau_jj",
    "jean-jacques rousseau": "rousseau_jj",
    "montaigne":             "montaigne",
    "pascal":                "pascal_blaise",
    "descartes":             "descartes_rene",
    "kafka":                 "kafka_franz",
    "franz kafka":           "kafka_franz",
    "orwell":                "orwell_george",
    "george orwell":         "orwell_george",
    "dostoievski":           "dostoievski_fedor",
    "dostoevsky":            "dostoievski_fedor",
    "freud":                 "freud_sigmund",
    "nietzsche":             "nietzsche_friedrich",
    "durkheim":              "durkheim_emile",
    "marx":                  "marx_karl",
    "karl marx":             "marx_karl",
    "weber":                 "weber_max",
    "bourdieu":              "bourdieu_pierre",
    "tocqueville":           "tocqueville_alexis_de",
    "machiavel":             "machiavel",
    "montesquieu":           "montesquieu",
    "platon":                "platon",
    "aristote":              "aristote",
    "hegel":                 "hegel_georg_wilhelm_friedrich",
    "kant":                  "kant_emmanuel",
}

# Liens à ignorer sur les pages auteur UQAM
SKIP_PATTERNS = (
    "benevoles", "/inter/", "javascript", "paypal",
    "wikipedia", "facebook", "mailto", "crossref",
    "cchic", "uqac", "agora", "dx.doi",
)


def normalize(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def get_uqam_path(author: str) -> str:
    n = normalize(author)
    if n in AUTHOR_MAP:
        return AUTHOR_MAP[n]
    for part in n.split():
        if part in AUTHOR_MAP:
            return AUTHOR_MAP[part]
    parts = n.split()
    if len(parts) >= 2:
        return f"{parts[-1]}_{parts[0]}"
    return n.replace(" ", "_")


# ── Parser HTML (stdlib) ───────────────────────────────────────────────────────

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._buf  = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = None
            self._buf  = []
            for name, val in attrs:
                if name == "href" and val:
                    self._href = val

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._buf).strip()))
            self._href = None
            self._buf  = []


def fetch_html(url: str, timeout: int = 6) -> str:
    """Récupère le HTML d'une page. Retourne '' en cas d'erreur."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":      UA,
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",   # pas de gzip → pas de décompression
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ct  = resp.headers.get("Content-Type", "")

        enc = "utf-8"
        if "charset=" in ct:
            enc = ct.split("charset=")[-1].strip().split(";")[0].strip()
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")
    except Exception:
        return ""


def parse_links(html: str):
    p = LinkParser()
    p.feed(html)
    return p.links


# ── UQAM ──────────────────────────────────────────────────────────────────────

def scrape_uqam(author: str, title: str = "") -> list:
    """
    Stratégie directe :
      1. Fetch la page auteur
      2. Repère les liens relatifs HTML de sous-dossiers (ex: etranger/etranger.html)
      3. Remplace .html par .pdf → URL directe du PDF (ex: etranger/etranger.pdf)
    Aucune requête sur les sous-pages — rapide et fiable.
    """
    path     = get_uqam_path(author)
    base_url = f"{UQAM_BASE}{path}/"
    page_url = f"{base_url}{path}.html"

    html = fetch_html(page_url)
    if not html:
        return []

    links       = parse_links(html)
    title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []
    seen        = set()
    results     = []

    for href, text in links:
        # Filtre : lien relatif avec sous-dossier, fichier HTML, pas de navigation
        if not href or href.startswith(("http", "/", "javascript", ".", "#")):
            continue
        if any(p in href for p in SKIP_PATTERNS):
            continue
        if "/" not in href or not href.lower().endswith(".html"):
            continue

        # Dériver l'URL du PDF
        pdf_href = href[:-5] + ".pdf"        # etranger/etranger.html → etranger/etranger.pdf
        pdf_url  = base_url + pdf_href

        if pdf_url in seen:
            continue
        seen.add(pdf_url)

        # Titre affiché : texte du lien ou nom du fichier nettoyé
        display = text or href.split("/")[-1].replace(".html", "").replace("_", " ").title()
        if not display or len(display) < 2:
            continue

        # Filtre par titre si fourni
        if title_words and not any(w in normalize(display) for w in title_words):
            continue

        results.append({
            "title":  display,
            "author": author,
            "url":    pdf_url,
            "format": "PDF",
            "source": "UQAM",
            "lang":   "FR",
            "cta":    "Ouvrir dans Apple Books",
            "grey":   False,
        })

    return results[:12]


# ── Handler Vercel ─────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs     = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)

        author = params.get("author", [""])[0].strip()
        title  = params.get("title",  [""])[0].strip()

        results = scrape_uqam(author, title) if author else []

        body = json.dumps(results, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
