"""
Scraper UQAM - stdlib uniquement (pas de requests ni beautifulsoup4).
Toutes les autres sources sont gérées côté client (index.html).
"""
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import urllib.request
import unicodedata
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

UQAM_BASE = "https://classiques.uqam.ca/classiques/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

AUTHOR_MAP = {
    "camus":                  "camus_albert",
    "albert camus":           "camus_albert",
    "sartre":                 "sartre_jean-paul",
    "jean paul sartre":       "sartre_jean-paul",
    "jean-paul sartre":       "sartre_jean-paul",
    "simone de beauvoir":     "beauvoir_simone_de",
    "beauvoir":               "beauvoir_simone_de",
    "hugo":                   "hugo_victor",
    "victor hugo":            "hugo_victor",
    "zola":                   "zola_emile",
    "emile zola":             "zola_emile",
    "balzac":                 "balzac_honore_de",
    "honore de balzac":       "balzac_honore_de",
    "flaubert":               "flaubert_gustave",
    "gustave flaubert":       "flaubert_gustave",
    "proust":                 "proust_marcel",
    "marcel proust":          "proust_marcel",
    "baudelaire":             "baudelaire_charles",
    "charles baudelaire":     "baudelaire_charles",
    "moliere":                "moliere",
    "racine":                 "racine_jean",
    "voltaire":               "voltaire",
    "rousseau":               "rousseau_jj",
    "jean-jacques rousseau":  "rousseau_jj",
    "montaigne":              "montaigne",
    "pascal":                 "pascal_blaise",
    "descartes":              "descartes_rene",
    "kafka":                  "kafka_franz",
    "franz kafka":            "kafka_franz",
    "orwell":                 "orwell_george",
    "george orwell":          "orwell_george",
    "dostoievski":            "dostoievski_fedor",
    "dostoevsky":             "dostoievski_fedor",
    "dostoievsky":            "dostoievski_fedor",
    "freud":                  "freud_sigmund",
    "sigmund freud":          "freud_sigmund",
    "nietzsche":              "nietzsche_friedrich",
    "durkheim":               "durkheim_emile",
    "marx":                   "marx_karl",
    "karl marx":              "marx_karl",
    "weber":                  "weber_max",
    "bourdieu":               "bourdieu_pierre",
    "tocqueville":            "tocqueville_alexis_de",
    "machiavel":              "machiavel",
    "montesquieu":            "montesquieu",
    "platon":                 "platon",
    "aristote":               "aristote",
    "hegel":                  "hegel_georg_wilhelm_friedrich",
    "kant":                   "kant_emmanuel",
}


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


# ── Parser HTML minimal (stdlib) ──────────────────────────────────────────────

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []          # [(href, text)]
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


def fetch_links(url: str, timeout: int = 5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        ct = resp.headers.get("Content-Type", "")
        enc = "utf-8"
        if "charset=" in ct:
            enc = ct.split("charset=")[-1].strip().split(";")[0]
        try:
            html = raw.decode(enc, errors="replace")
        except Exception:
            html = raw.decode("latin-1", errors="replace")
        p = LinkParser()
        p.feed(html)
        return p.links
    except Exception:
        return []


# ── UQAM (2 niveaux) ──────────────────────────────────────────────────────────

def scrape_uqam(author: str, title: str = "") -> list:
    path     = get_uqam_path(author)
    url      = f"{UQAM_BASE}{path}/{path}.html"
    base_url = f"{UQAM_BASE}{path}/"

    links = fetch_links(url, timeout=6)
    if not links:
        return []

    title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []

    # Niveau 1 : sous-pages de livres (liens relatifs HTML avec sous-dossier)
    book_pages = []
    for href, text in links:
        if (
            not href.startswith("http")
            and not href.startswith("/")
            and not href.startswith("javascript")
            and "/" in href
            and href.lower().endswith(".html")
        ):
            if title_words and not any(w in normalize(text) for w in title_words):
                continue
            book_pages.append((text or href.split("/")[0], base_url + href))

    if not book_pages:
        return []

    book_pages = book_pages[:10]

    # Niveau 2 : PDF dans chaque sous-page
    def get_pdf(book_title: str, book_url: str):
        sub_links = fetch_links(book_url, timeout=4)
        book_dir  = book_url.rsplit("/", 1)[0]
        for href, _ in sub_links:
            if href.lower().endswith(".pdf"):
                if href.startswith("http"):
                    pdf_url = href
                elif href.startswith("/"):
                    pdf_url = f"https://classiques.uqam.ca{href}"
                else:
                    pdf_url = f"{book_dir}/{href}"
                return {
                    "title":  book_title,
                    "author": author,
                    "url":    pdf_url,
                    "format": "PDF",
                    "source": "UQAM",
                    "lang":   "FR",
                    "cta":    "Ouvrir dans Apple Books",
                    "grey":   False,
                }
        return None

    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(get_pdf, t, u) for t, u in book_pages]
        try:
            for future in as_completed(futures, timeout=7):
                res = future.result()
                if res:
                    results.append(res)
        except Exception:
            pass

    return results[:8]


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
