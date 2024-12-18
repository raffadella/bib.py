#! /usr/bin/python3
"""bib.py - Create, combine, complete and clean BibTeX bibliographies.
See docstring of main() below, and README.md 'restructured text' file."""

# WARNING: Set "common_strings=True" to allow months given as "month = jan".
# The current documented default should be "True", but since many versions
# of bparser.py instead set it to "False", we fix it by changing the source:
# /usr/lib/python3/dist-packages/bibtexparser/bparser.py
#                 common_strings=True,

# See also:
#   bib.py on github  - https://github.com/raffadella/bib.py
#   CrossRef REST API - https://github.com/CrossRef/rest-api-doc

import os
import sys
import re
from typing import Any, Dict, List

import subprocess
import urllib
import functools
import requests
import bibtexparser
import isbnlib

# Items for local configuration: email and other info of the user, and
# commands to display a text string and a PDF file in new windows.
USER_INFO = 'mailto:raffaele.dellavalle@unibo.it'
TXT_DISPLAY = ['xterm', '-geometry', '-0+0', '-hold', '-e', 'echo']
PDF_DISPLAY = ['xpdf', '-q', '-geometry', 'x600-0-0']

# URLs to resolve a DOI with crossref.org or doi.org - {} becomes the DOI
XREF_URL = 'http://api.crossref.org/works/{}/transform/application/x-bibtex'
DOI_URL = 'https://doi.org/{}'

# Declare type for BibTeX entries: key -> value dictionary, both are strings
BibEntry = Dict[str, str]

# Standard names found in BibTeX files when months are given as strings
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
          'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

# A regular expression (RE) matching a key (either ISBN or DOI)
KEY_RE = r'\b(ISBN(-10|-13|)[:\s]+\d[\d -]{8,15}[\dX]|10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d])\b'

# NOTE 1: In this code we deliberately use mutable defaults to memorize
# INITIALLY EMPTY PRIVATE lists and dictionaries (either [] or {}).
# The pylint3 complaints about dangerous-default-value are irrelevant.

# NOTE 2: The following kinds of key, val pairs are used through record()
# 'all_confirm'  True or False to confirm 'YES' or 'NO' text queries
# 'item_str'     item string (to print item trace)
# 'entries_int'  number of accumulated BibTeX entries (to print item trace)


def re_strip(txt: str, *regexps: str) -> str:
    """Utility: strip any number of regexp's from string txt"""
    for regexp in regexps:
        txt = re.sub(regexp, '', txt)
    return txt


def re_find(txt: str, regexp: str, i: int = 0) -> str:
    """Utility: search string txt for a regexp and return i-th group
       (i.e. parenthesis) if match succeds. Default is whole match."""
    match = re.search(regexp, txt)
    if match:
        return match.group(i)
    return ''


def record(key: Any, val: Any = None, default: Any = None,
           memo_dict: Dict[Any, Any] = {}) -> Any:
    """Record a mapping in an INITIALLY EMPTY PRIVATE dictionary. If val is
       supplied (not None) store dict[key] = val and return val. If val is
       None return the stored dict[key] if available, default otherwise."""
    if val is None:
        return memo_dict.get(key, default)
    memo_dict[key] = val
    return val


def str2chksum(txt: str, divisor: int) -> int:
    """Return the checksum of a string, modulo the given divisor. The string is
    first converted to lower case, with non alphanumeric characters removed."""
    txt = re_strip(txt.lower(), r'[^a-z0-9 ]')
    return functools.reduce(lambda nm, ch: (nm + ord(ch)) % divisor, txt, 0)


def make_ay_key(entry: BibEntry) -> str:
    """Make AY (author-year) partial key, with surname of the first author
       (lower-case, non alphabetic characters removed) and publication year.
       For empty years, use 9900 plus the modulo 1000 checksum of the title."""
    author = entry.get('author') or entry.get('editor', 'unknown')
    author = re_find(author, '^(.*?)( and |$)', 1)
    au_dict = bibtexparser.customization.splitname(author, strict_mode=False)
    author = ' '.join(au_dict['last'])
    author = re_strip(author.lower(), r'\\[a-hj-z][a-z]*', r'[^a-z]')
    year = re_find(entry.get('year', ''), r'\d{4}')
    if not year:
        year = f'9{str2chksum(entry.get("title", ""), 1000):03d}'
    return author + year


def make_char_key(entry: BibEntry) -> str:
    """Make single character partial key: 'a b ... l' for the publication month
       'jan feb ... dec' (if available); or the LAST digit of the FIRST page
       (if available); or 'm n ... z' from the modulo 13 checksum of the title."""
    if 'month' in entry:
        month = entry['month']
        if re.match(r'^(0?[1-9]|1[012])$', month):
            imonth = int(month) - 1
        else:
            imonth = MONTHS.index(month[:3].lower())
        return chr(imonth + ord('a'))
    page = re_find(entry.get('pages', ''), r'\d*(\d)', 1)
    if page:
        return page
    return chr(ord('m') + str2chksum(entry.get('title', ''), 13))


def make_ayc_key(entry: BibEntry) -> str:
    """Make AYC (author-year-character) key. Like make_ay_key() with the
       final character discussed for make_char_key(). To avoid overwrites,
       return existing AYC if already present with correct author and year."""
    author_year = make_ay_key(entry)
    if author_year == entry['ID'][:-1]:
        return entry['ID']
    char = make_char_key(entry)
    ayc_key = author_year + char
    return ayc_key


def make_safe_key(entry: BibEntry) -> str:
    """Make key: DOI or ISBN string if available, otherwise first author, plus
       year, plus title (in lower case with non alphanumeric characters removed).
       DOI and ISBN uniquely identify a publication and thus are safe keys, but
       may be absent. The author-year-title key used as fallback SHOULD be safe."""
    return ( entry.get('doi') or
             entry.get('isbn') or
             make_ay_key(entry) + re_strip(entry.get("title", "").lower(), r'[^a-z0-9 ]') )


def user_confirm(bib: str, filename: str) -> Any:
    """Ask user to confirm a BibTeX entry: display entry (in a xterm window) and
       PDF file (if given), and ask 'n, y, N, Y' to user. Record 'Y' or 'N' answer
       (which hold from now on). Return Truthy ('y' or 'Y') or Falsy ('n' or 'N')."""
    proc1 = subprocess.Popen(TXT_DISPLAY + [bib])
    if filename:
        proc2 = subprocess.Popen(PDF_DISPLAY + [filename])
    try:
        answer = input('     Reference is correct? n (default), y, N, Y (for all): ')
    except EOFError:
        answer = 'N'
    proc1.terminate()
    if filename:
        proc2.terminate()
    answer = re_find(answer, r'[A-Za-z]+')
    if re.match(r'^[YN]', answer):
        command(answer, entries=[])
    return re.match('^[yY]', answer)


def doi2str(doi: str, url: str) -> str:
    """Given DOI string, insert at {} in URL, query URL and return BibTeX
       entry as a string if successful, otherwise return empty string."""
    response = requests.get(url.format(doi),
                            timeout=10,
                            headers={'accept': 'application/x-bibtex'})
    if response.status_code == 200:
        return response.text
    return ''


def isbn2str(isbn: str, service: str = 'goob') -> str:
    """Given ISBN string, query either 'goob' (Google Books, default) or
       'openl' (CROSSREF) WWW service and return BibTeX entry as a string"""
    try:
        return isbnlib.registry.bibformatters['bibtex'](isbnlib.meta(isbn, service=service))
    except (Exception, KeyboardInterrupt):
        return ''


def jabfile(entry: BibEntry, filename: str = '') -> str:
    """JabRef filenames handling. JabRef stores filenames surrounded by ':'
       characters in a 'file' field of the BibTeX entry. This function stores
       the filename if given, or returns it without the ':', otherwise."""
    if filename:
        entry['file'] = ':' + filename + ':'
        return ''
    return re_find(entry.get('file', ''), '^:?(.+?):?$', 1)


def item_trace(txt: str = '', num: int = 0) -> None:
    """Utility to trace growth of BibTeX entries: item_trace(num=n) update
       total of entries, item_trace(txt=item) print text item"""
    if num:
        record('entries_int', num)
        return
    if txt == record('item_str', default=''):
        return
    if txt:
        record('item_str', txt)
        print(f"{record('entries_int', default=0):4d}", re.sub(r'^(.{70,}?)\s.*', r'\1...', txt))
    return


def command(txt: str, entries: List[BibEntry]) -> str:
    """Handle commands complete, rename, YES, NO (check only the first letter).
       Return all obtained entries as a string for add_doi_isbn, '' otherwise."""
    if re.match(r'^[cC]', txt):
        return add_doi_isbn(entries=entries)
    if re.match(r'^[rR]', txt):
        rename_files(entries=entries)
    if re.match(r'^[YN]', txt):
        record('all_confirm', txt[0] == 'Y')
    return ''


def item2str(txt: str, filename: str = '', entries: List[BibEntry] = []) -> str:
    """Convert any item to BibTeX entries as a string. Query WWW for DOI, ISBN or
       search text. Convert files as appropriate. Handle -whatever commands. The
       filename and entries parameters are just forwarded to suitable functions."""
    txt = re_find(txt, r'^\s*(.*?)\s*$', 1)
    if len(txt) < 1:
        return ''
    item_trace(txt=txt)
    if re.match(r'^10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d]', txt):
        return doi2str(txt, XREF_URL) or doi2str(txt, DOI_URL)
    if re.match(r'^\d[\d -]{8,15}[\dX]$', txt):
        return isbn2str(txt, 'openl') or isbn2str(txt, 'goob')
    if re.search(r'(\S+\s+){4}\S', txt):
        return query2str(txt, filename=filename)
    if re.match(r'^-[A-Za-z]', txt):
        return command(txt[1:], entries=entries)
    return file2str(txt)


def query2str(txt: str, filename: str) -> str:
    """Given a search text, query Google Books to obtain a likely ISBN, on
       failure query CROSSREF to obtain a likely DOI. Convert to BibTeX entry
       as a string, and return it. Queries fail if not confirmed by the user."""
    if record('all_confirm') is False:
        return ''

    bib = isbn2str(isbnlib.isbn_from_words(txt))
    if bib and (record('all_confirm') or user_confirm(bib, filename)):
        return bib

    url = 'https://api.crossref.org/works'
    params = {'rows': '1', 'query.bibliographic': txt, 'select': 'DOI'}
    headers = {'User-Agent': f"DOI Importer ({USER_INFO})"}

    url = url + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, None, headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            encoding = response.info().get_param('charset', 'utf8')
            txt = response.read().decode(encoding)
    except (Exception, KeyboardInterrupt) as exception:
        print('     exception:', exception)
        return ''

    doi = re_find(txt, r'{"DOI":"(10\.\d{4,}[^"]+)"}', 1)
    doi = doi.replace(r'\/', '/')
    bib = item2str(doi)
    if bib and (record('all_confirm') or user_confirm(bib, filename)):
        return bib
    return ''


def pdf2str(filename: str) -> str:
    """Given a PDF file, return a BibTeX entry as a string. Extract from first
       5000 characters of a PDF file anything that looks like an ISBN or a DOI,
       if possible. Otherwise, use about 400 characters as search text."""
    txt = os.popen(f"pdftotext -enc ASCII7 -nopgbrk -q -l 8 {filename} -").read()[:5000]

    if not txt or len(txt) < 13:
        return ''

    key = re_find(txt, KEY_RE, 1)
    if key:
        key = re_strip(key, r'^ISBN(-10|-13|)[:\s]+')
        return item2str(key.replace(r' ', ''))

    return query2str(re_find(txt, r'^[\S\s]{1,400}[^ ]*'), filename=filename)


def file2str(filename: str) -> str:
    """Given a file, return BibTeX entries as a string. Just return *.bib files
       as a string. Convert *.pdf files as above. Split other files either by
       paragraphs (if possible) or by lines (otherwise), convert each fragment
       to a BibTeX entry as a string and return all concatenated entries."""
    try:
        with open(filename) as infile:
            if re.search(r'(?i)\.bib(tex)?$', filename):
                return infile.read()
            if re.search(r'(?i)\.pdf$', filename):
                return pdf2str(filename)
            txt = infile.read()
            separator = r'\n\n+' if re.search(r'\S\s*\n\n+\s*\S', txt) else r'\n'
            return '\n\n'.join(item2str(re.sub(r'\s+', ' ', item))
                               for item in re.split(separator, txt))
    except FileNotFoundError:
        return ''


def entry2query(entry: BibEntry) -> str:
    """Given BibTeX entry as a list, return text string appropriate for a query"""
    return ' '.join(entry.get(field, '')
                    for field in ['year', 'title', 'author'])


def add_doi_isbn(entries: List[BibEntry]) -> str:
    """Given list of BibTeX entries, attempt to obtain any missing DOI or ISBN
       by querying the WWW, and return all obtained entries as a string"""
    return '\n\n'.join(item2str(entry2query(entry), filename=jabfile(entry))
                       for entry in entries
                       if 'doi' not in entry and 'isbn' not in entry)


def rename_files(entries: List[BibEntry]) -> None:
    """If a BibTeX entry contains a 'file' field, or if the entry is obtained
       from a PDF file, the 'file' field is updated (or created) with the AYC
       (author-year-character ID) of the entry as basename. All files matching
       the old basename are renamed with the new basename if they differ."""
    for entry in entries:
        filename = jabfile(entry)
        if filename:
            head, tail = os.path.split(filename)
            root, ext = (re.match(r'^(.+?)(\.?[^.]*)$', tail)).group(1, 2)
            newroot = entry['ID']
            jabfile(entry, os.path.join(head, newroot + ext))
            if root != newroot:
                os.system(f"rename -r 's:{root}:{newroot}:' '{os.path.join(head, root)}'[._-]*")


def cleanup_entry(entry: BibEntry, item: str) -> None:
    """Clean DOI, delete URLs which are DOIs, add FILE if available"""
    if 'doi' in entry:
        entry['doi'] = re_find(entry['doi'], r'10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d]')
    if 'url' in entry and re.search(r'[/.]doi[/.].*10\.\d\d\d\d', entry['url']):
        del entry['url']
    if re.search(r'(?i)\.pdf$', item):
        jabfile(entry, item)


def next_letter(chars: str) -> str:
    """Starting from the last character of a string, return the next
    'a'...'z' letter (in cyclic order) not already present in the string."""
    assert len(chars) < 25, "Too many AYC collisions (more than 25)"
    n = ord(chars[-1]) - ord("a")
    while True:
        n = (n + 1) % 25
        ch = chr(n + ord("a"))
        if ch not in chars:
            return ch

def add2database(entries: List[BibEntry], entry: BibEntry, item: str,
                 memo_dict: Dict[str, int] = {}) -> None:
    """Append one BibTeX entry to list of entries (if not there already), or
       just add any missing field (otherwise). An INITIALLY EMPTY PRIVATE
       dictionary is used to index the list, with a safe key (DOI, ISBN, or
       AYC plus title). The value associated to the key is the position (the
       index) of the corresponding entry in the list. The AYC key is also
       stored in the dictionary to discover collisions. In case of an AYC
       collision, select the next unused 'a'...'z' letter (in cyclic order)."""
    cleanup_entry(entry, item)
    safe_key = make_safe_key(entry)
    num = memo_dict.get(safe_key)
    if num is not None:
        for field, value in entry.items():
            if field != 'ID' and field not in entries[num]:
                entries[num][field] = value
    else:
        ayc_key = make_ayc_key(entry)

        if ayc_key in memo_dict:
            ch = next_letter(memo_dict[ayc_key])
            memo_dict[ayc_key] += ch
            ayc_key = ayc_key[:-1] + ch
        else:
            memo_dict[ayc_key] = ayc_key[-1]

        entry['ID'] = ayc_key
        memo_dict[safe_key] = len(entries)
        entries.append(entry)


def main(items: List[str]) -> None:
    """bib.py - Create, combine, complete and clean BibTeX bibliographies.

Usage: bib.py item ...

The script obtains BibTeX entries from one or more items given as
arguments. The items are interpreted as in the following examples:

   bibtex.bib         BibTeX bibliography file (*.bib or *.bibtex)
   10.1002/jrs.4278   DOI (Digital Object Identifier)
   9780553109535      ISBN (International Standard Book Number)
   'title and more'   search text (title, author ... whatever)
   fermi1932.pdf      PDF (Portable Document Format) file
   -rename            rename files as AYC for all PREVIOUS entries
   -complete          add missing DOI or ISBN to all PREVIOUS entries
   -yes               answer YES to all confirm queries from NOW ON
   -no                answer NO to all confirm queries from NOW ON
   any-text-file      file containing a list of the items above

BibTeX files are read in. Data from ISBN, DOI or search text is obtained
by querying doi.org, crossref.org or google books. PDF files are scanned
to extract anything that looks like an ISBN or a DOI, or to obtain search
text. Commands -rename, -complete, -yes and -no are obeyed. Any other
item is taken as a text file containing a list of the items above, by
paragraph or by line. Unreliable BibTeX entries obtained by searching text
are accepted only if the user confirms them (unless preempted by -yes or
-no). The first argument MUST be a bibtex file, which is read if existing
or created if not, and which receives all obtained BibTeX entries."""

    # No arguments: display function "__doc__" string as an usage message
    if len(items) < 1:
        print(main.__doc__)
        sys.exit(1)

    # The first argument must match '*.bib' or '*.bibtex'
    assert re.search(r'(?i)\.bib(tex)?$', items[0]), f"First argument '{items[0]}' is not a BibTeX file"

    # Make empty database
    bibtex_database = bibtexparser.bibdatabase.BibDatabase()

    # For all items: obtain BibTeX entries as a string, parse to list of
    # BibEntry (a key -> value dictionary) and append to the database. The
    # database and the item are passed to item2str and add2database which
    # might forward them to cleanup_entry and query2str, respectively.
    for item in items:
        bibstr = item2str(item, entries=bibtex_database.entries)
        if bibstr:
            for entry in bibtexparser.loads(bibstr).entries:
                add2database(bibtex_database.entries, entry, item)
        item_trace(num=len(bibtex_database.entries))

    # Dump final database if not empty
    if bibtex_database.entries:
        with open(items[0], 'w') as outfile:
            bibtexparser.dump(bibtex_database, outfile)
    item_trace(txt='Total')


# Call "main" with command line arguments when invoked as a script
if __name__ == '__main__':
    main(sys.argv[1:])
