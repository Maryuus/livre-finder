from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# Map des auteurs connus sur UQAM
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
    "jean racine":            "racine_jean",
    "voltaire":               "voltaire",
    "rousseau":               "rousseau_jj",
    "jean-jacques rousseau":  "rousseau_jj",
    "montaigne":              "montaigne",
    "pascal":                 "pascal_blaise",
    "blaise pascal":          "pascal_blaise",
    "descartes":              "descartes_rene",
    "rene descartes":         "descartes_rene",
    "kafka":                  "kafka_franz",
    "franz kafka":            "kafka_franz",
    "orwell":                 "orwell_george",
    "george orwell":          "orwell_george",
    "dostoievski":            "dostoievski_fedor",
    "dostoevsky":             "dostoievski_fedor",
    "dostoievsky":            "dostoievski_fedor",
    "fedor dostoievski":      "dostoievski_fedor",
    "freud":                  "freud_sigmund",
    "sigmund freud":          "freud_sigmund",
    "nietzsche":              "nietzsche_friedrich",
    "friedrich nietzsche":    "nietzsche_friedrich",
    "durkheim":               "durkheim_emile",
    "emile durkheim":         "durkheim_emile",
    "marx":                   "marx_karl",
    "karl marx":              "marx_karl",
    "weber":                  "weber_max",
    "max weber":              "weber_max",
    "bourdieu":               "bourdieu_pierre",
    "pierre bourdieu":        "bourdieu_pierre",
    "tocqueville":            "tocqueville_alexis_de",
    "machiavel":              "machiavel",
    "montesquieu":            "montesquieu",
    "platon":                 "platon",
    "aristote":               "aristote",
    "hegel":                  "hegel_georg_wilhelm_friedrich",
    "kant":                   "kant_emmanuel",
    "emmanuel kant":          "kant_emmanuel",
}

UQAM_BASE = "https://classiques.uqam.ca/classiques/"
HEADERS   = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def normalize(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


# ── 1. UQAM (Québec) ──────────────────────────────────────────────────────────

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
    return n.replace(" ", "_").replace("-", "_")


def scrape_uqam(author: str, title: str = "") -> list:
    if not HAS_DEPS:
        return []
    path = get_uqam_path(author)
    url  = f"{UQAM_BASE}{path}/{path}.html"
    try:
        r = requests.get(url, timeout=6, headers=HEADERS)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.content, "html.parser")
        results, seen = [], set()
        title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            text = a.get_text(" ", strip=True)
            if not text or len(text) < 3:
                continue
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"https://classiques.uqam.ca{href}"
            else:
                full_url = f"{UQAM_BASE}{path}/{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            if title_words and not any(w in normalize(text) for w in title_words):
                continue
            results.append({
                "title": text, "author": author,
                "url": full_url, "format": "PDF",
                "source": "UQAM", "lang": "FR",
                "cta": "Ouvrir dans Apple Books", "grey": False,
            })
        return results[:8]
    except Exception:
        return []


# ── 2. Gallica — Bibliothèque nationale de France ─────────────────────────────

def search_gallica(author: str, title: str = "") -> list:
    if not HAS_DEPS:
        return []
    parts = []
    if author:
        parts.append(f'dc.creator adj "{author}"')
    if title:
        parts.append(f'dc.title adj "{title}"')
    if not parts:
        return []
    query = " and ".join(parts) + ' and dc.type all "monographie"'
    try:
        r = requests.get(
            "https://gallica.bnf.fr/SRU",
            params={
                "operation": "searchRetrieve",
                "version":   "1.2",
                "query":     query,
                "maximumRecords": 5,
                "collapsing": "true",
            },
            timeout=7, headers=HEADERS,
        )
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        DC  = "http://purl.org/dc/elements/1.1/"
        OAI = "http://www.openarchives.org/OAI/2.0/oai_dc/"
        SRW = "http://www.loc.gov/zing/srw/"

        results = []
        for record in root.iter(f"{{{SRW}}}record"):
            dc = record.find(f".//{{{OAI}}}dc")
            if dc is None:
                continue
            rec_title = dc.find(f"{{{DC}}}title")
            rec_id    = dc.find(f"{{{DC}}}identifier")
            rec_auth  = dc.find(f"{{{DC}}}creator")
            if rec_title is None or rec_id is None:
                continue
            ark = (rec_id.text or "").strip()
            if not ark:
                continue
            doc_url = f"https://gallica.bnf.fr/{ark}" if ark.startswith("ark:") else ark
            results.append({
                "title":  rec_title.text or "Sans titre",
                "author": rec_auth.text if rec_auth is not None else author,
                "url":    doc_url,
                "format": "PDF/ePub",
                "source": "Gallica (BnF)",
                "lang":   "FR",
                "cta":    "Voir sur Gallica",
                "grey":   True,
            })
        return results[:5]
    except Exception:
        return []


# ── 3. Standard Ebooks — classiques haute qualité ─────────────────────────────

def search_standard_ebooks(author: str, title: str = "") -> list:
    if not HAS_DEPS:
        return []

    # Slug OPDS : "Franz Kafka" → "franz-kafka"
    def make_slug(s):
        n = normalize(s)
        return "-".join(n.split())

    slug = make_slug(author)
    # Essai avec slug normal, puis inversé (nom prénom → prénom nom)
    parts = slug.split("-")
    slugs = [slug]
    if len(parts) >= 2:
        slugs.append("-".join(reversed(parts)))

    for s in slugs:
        url = f"https://standardebooks.org/feeds/opds/authors/{s}"
        try:
            r = requests.get(url, timeout=6, headers=HEADERS)
            if r.status_code != 200:
                continue

            root = ET.fromstring(r.content)
            ATOM = "http://www.w3.org/2005/Atom"
            results = []
            title_words = [normalize(w) for w in title.split() if len(w) > 3] if title else []

            for entry in root.iter(f"{{{ATOM}}}entry"):
                t_el = entry.find(f"{{{ATOM}}}title")
                if t_el is None:
                    continue
                book_title = t_el.text or ""

                if title_words and not any(w in normalize(book_title) for w in title_words):
                    continue

                epub_url = None
                for link in entry.findall(f"{{{ATOM}}}link"):
                    if "epub" in link.get("type", ""):
                        href = link.get("href", "")
                        if href:
                            epub_url = href if href.startswith("http") else f"https://standardebooks.org{href}"
                        break

                if not epub_url:
                    continue

                results.append({
                    "title":  book_title,
                    "author": author,
                    "url":    epub_url,
                    "format": "ePub",
                    "source": "Standard Ebooks",
                    "lang":   "EN",
                    "cta":    "Ouvrir dans Apple Books",
                    "grey":   False,
                })

            if results:
                return results[:5]
        except Exception:
            continue

    return []


# ── 4. Feedbooks — catalogue domaine public ────────────────────────────────────

def search_feedbooks(author: str, title: str = "") -> list:
    if not HAS_DEPS:
        return []
    query = " ".join(filter(None, [author, title]))
    try:
        r = requests.get(
            "https://catalog.feedbooks.com/publicdomain/search.atom",
            params={"query": query},
            timeout=6, headers=HEADERS,
        )
        if r.status_code != 200:
            return []

        root = ET.fromstring(r.content)
        ATOM = "http://www.w3.org/2005/Atom"
        DC   = "http://purl.org/dc/terms/"
        results = []

        for entry in root.iter(f"{{{ATOM}}}entry"):
            t_el = entry.find(f"{{{ATOM}}}title")
            if t_el is None or not t_el.text:
                continue

            a_el = entry.find(f".//{{{ATOM}}}author/{{{ATOM}}}name")

            epub_url = None
            for link in entry.findall(f"{{{ATOM}}}link"):
                if "epub" in link.get("type", ""):
                    epub_url = link.get("href", "")
                    break

            if not epub_url:
                continue

            lang_el = entry.find(f"{{{DC}}}language")
            lang = (lang_el.text or "").upper() if lang_el is not None else ""

            results.append({
                "title":  t_el.text,
                "author": a_el.text if a_el is not None else author,
                "url":    epub_url,
                "format": "ePub",
                "source": "Feedbooks",
                "lang":   lang or "FR",
                "cta":    "Ouvrir dans Apple Books",
                "grey":   False,
            })

        return results[:5]
    except Exception:
        return []


# ── Handler Vercel ─────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs     = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)

        author = params.get("author", [""])[0].strip()
        title  = params.get("title",  [""])[0].strip()

        results = []
        if author or title:
            tasks = [
                (scrape_uqam,            author, title),
                (search_gallica,         author, title),
                (search_standard_ebooks, author, title),
                (search_feedbooks,       author, title),
            ]
            # Toutes les sources tournent en parallèle (max 8s total)
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [ex.submit(fn, a, t) for fn, a, t in tasks]
                try:
                    for future in as_completed(futures, timeout=8):
                        try:
                            results.extend(future.result())
                        except Exception:
                            pass
                except Exception:
                    pass

        body = json.dumps(results, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
