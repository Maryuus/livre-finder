"""
LivreFinder — Agrégateur de sources ebooks
Chaque source est une fonction indépendante qui retourne une liste de livres.

Format de retour standard pour chaque livre :
{
    "title":  str,   # Titre du livre
    "author": str,   # Auteur
    "url":    str,   # URL directe de téléchargement ou page du livre
    "format": str,   # "ePub", "PDF", "MOBI", "AZW3"
    "source": str,   # Nom affiché dans l'UI
    "lang":   str,   # "FR", "EN", "DE", "ES", ...
    "cta":    str,   # Texte du bouton ("Télécharger", "Ouvrir dans Apple Books", ...)
    "grey":   bool,  # True = bouton gris (lien externe), False = bouton bleu (téléchargement direct)
    "cover":  str|None  # URL de la couverture (optionnel)
}
"""

from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import urllib.request
import unicodedata
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def normalize(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

FULL_NAMES = {
    "camus":       "albert camus",
    "kafka":       "franz kafka",
    "orwell":      "george orwell",
    "sartre":      "jean-paul sartre",
    "dostoievski": "fyodor dostoevsky",
    "dostoevsky":  "fyodor dostoevsky",
    "hugo":        "victor hugo",
    "zola":        "emile zola",
    "balzac":      "honore de balzac",
    "flaubert":    "gustave flaubert",
    "proust":      "marcel proust",
    "baudelaire":  "charles baudelaire",
    "nietzsche":   "friedrich nietzsche",
    "freud":       "sigmund freud",
    "marx":        "karl marx",
    "rousseau":    "jean-jacques rousseau",
    "tolstoi":     "leo tolstoy",
    "tolstoy":     "leo tolstoy",
    "shakespeare": "william shakespeare",
    "dickens":     "charles dickens",
    "voltaire":    "voltaire",
    "moliere":     "moliere",
    "stendhal":    "stendhal",
}

def expand(author: str) -> str:
    """'kafka' → 'franz kafka'"""
    return FULL_NAMES.get(normalize(author), author)

def fetch(url: str, timeout: int = 7) -> bytes:
    """Requête HTTP simple, retourne b'' en cas d'erreur."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":      UA,
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return b""


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 1 — LIBGEN
#  Des millions de livres dans toutes les langues et formats
# ══════════════════════════════════════════════════════════════════════════════

def search_libgen(author: str, title: str = "") -> list:
    from bs4 import BeautifulSoup
    query = f"{expand(author)} {title}".strip()
    if not query:
        return []
    url = ("https://libgen.rs/search.php?" +
           urllib.parse.urlencode({"req": query, "res": 25,
                                   "view": "simple", "phrase": 1, "column": "def"}))
    raw = fetch(url, timeout=8)
    if not raw:
        return []
    soup = BeautifulSoup(raw, "html.parser")

    # Le tableau de résultats est reconnaissable par son header
    results_table = None
    for t in soup.find_all("table"):
        header = t.find("tr")
        if header and any("Author" in th.get_text() for th in header.find_all("th")):
            results_table = t
            break
    if not results_table:
        return []

    results = []
    for row in results_table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 10:
            continue
        author_text = cols[1].get_text(strip=True)
        title_links = cols[2].find_all("a")
        title_text  = title_links[0].get_text(strip=True) if title_links else cols[2].get_text(strip=True)
        lang = cols[6].get_text(strip=True)[:2].upper()
        ext  = cols[8].get_text(strip=True).lower()
        # MD5 extrait du lien miroir (ex: http://library.lol/main/MD5)
        mirror_a = cols[9].find("a")
        if not mirror_a:
            continue
        href = mirror_a.get("href", "")
        md5  = href.rstrip("/").split("/")[-1]
        if not md5 or len(md5) != 32:
            continue
        fmt = "ePub" if "epub" in ext else ("PDF" if "pdf" in ext else ext.upper() or "ePub")
        results.append({
            "title":  title_text,
            "author": author_text,
            "url":    f"https://libgen.rocks/get.php?md5={md5}",
            "format": fmt,
            "source": "Libgen",
            "lang":   lang or "EN",
            "cta":    "Télécharger",
            "grey":   False,
            "cover":  None,
        })
    return results[:10]


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 2 — PROJECT GUTENBERG (via Gutendex)
#  Livres domaine public — principalement EN/DE, quelques FR
# ══════════════════════════════════════════════════════════════════════════════

def search_gutenberg(author: str, title: str = "") -> list:
    query = f"{title} {expand(author)}".strip()
    url   = f"https://gutendex.com/books/?search={urllib.parse.quote(query)}"
    raw   = fetch(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    results = []
    for b in data.get("results", [])[:8]:
        epub_url = (
            b.get("formats", {}).get("application/epub+zip")
            or b.get("formats", {}).get("application/epub")
        )
        if not epub_url:
            continue
        langs = b.get("languages", [])
        lang  = "FR" if "fr" in langs else (langs[0].upper() if langs else "")
        results.append({
            "title":  b.get("title", ""),
            "author": ", ".join(a["name"] for a in b.get("authors", [])),
            "url":    epub_url,
            "format": "ePub",
            "source": "Gutenberg",
            "lang":   lang,
            "cta":    "Ouvrir dans Apple Books",
            "grey":   False,
            "cover":  b.get("formats", {}).get("image/jpeg"),
        })
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 3 — STANDARD EBOOKS (OPDS)
#  Classiques domaine public haute qualité — EN uniquement
# ══════════════════════════════════════════════════════════════════════════════

class AtomParser(HTMLParser):
    """Parser Atom/OPDS minimal (stdlib)."""
    def __init__(self):
        super().__init__()
        self.entries  = []
        self._in_entry = False
        self._title    = ""
        self._buf      = []
        self._epub     = None
        self._tag      = ""

    def handle_starttag(self, tag, attrs):
        self._tag = tag.lower().split(":")[-1]
        if self._tag == "entry":
            self._in_entry = True
            self._title    = ""
            self._epub     = None
            self._buf      = []
        if self._in_entry and self._tag == "link":
            ad = dict(attrs)
            if "epub" in ad.get("type", ""):
                href = ad.get("href", "")
                if href:
                    self._epub = href if href.startswith("http") else f"https://standardebooks.org{href}"

    def handle_data(self, data):
        if self._in_entry and self._tag == "title":
            self._buf.append(data)

    def handle_endtag(self, tag):
        t = tag.lower().split(":")[-1]
        if t == "title" and self._in_entry:
            self._title = " ".join(self._buf).strip()
            self._buf   = []
        if t == "entry" and self._in_entry:
            if self._title and self._epub:
                self.entries.append((self._title, self._epub))
            self._in_entry = False

def search_standard_ebooks(author: str, title: str = "") -> list:
    fa    = expand(author)
    parts = normalize(fa).split()
    slugs = ["-".join(parts)]
    if len(parts) >= 2:
        slugs.append("-".join(reversed(parts)))

    title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []

    for slug in slugs:
        raw = fetch(f"https://standardebooks.org/feeds/opds/authors/{slug}", timeout=6)
        if not raw:
            continue
        try:
            html = raw.decode("utf-8", errors="replace")
        except Exception:
            continue
        p = AtomParser()
        p.feed(html)
        results = []
        for book_title, epub_url in p.entries:
            if title_words and not any(w in normalize(book_title) for w in title_words):
                continue
            results.append({
                "title":  book_title,
                "author": fa or author,
                "url":    epub_url,
                "format": "ePub",
                "source": "Standard Ebooks",
                "lang":   "EN",
                "cta":    "Ouvrir dans Apple Books",
                "grey":   False,
                "cover":  None,
            })
        if results:
            return results[:6]
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  AGRÉGATEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

SOURCES = [
    search_libgen,
    search_gutenberg,
    search_standard_ebooks,
]

def search_all(author: str, title: str) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as ex:
        futures = [ex.submit(fn, author, title) for fn in SOURCES]
        try:
            for future in as_completed(futures, timeout=9):
                try:
                    results.extend(future.result())
                except Exception:
                    pass
        except Exception:
            pass
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLER VERCEL
# ══════════════════════════════════════════════════════════════════════════════

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs     = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        author = params.get("author", [""])[0].strip()
        title  = params.get("title",  [""])[0].strip()

        results = search_all(author, title) if (author or title) else []

        body = json.dumps(results, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
