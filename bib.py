#! /usr/bin/python
"""bib.py - Create, combine, complete and clean BibTeX bibliographies.
See docstring of main() below, and README.md 'restructured text' file."""

# Crossref REST API - https://github.com/CrossRef/rest-api-doc

import os
import sys
import re
from typing import Any, Dict, List

import subprocess
import urllib
import requests
import bibtexparser

from isbnlib import meta, registry

# Items for local configuration: email and other info of the user, and
# commands to display a text string and a PDF file in new windows.
USER_INFO = 'mailto:raffaele.dellavalle@unibo.it'
TXT_DISPLAY = ['xterm', '-geometry', '-0+0', '-hold', '-e', 'echo']
PDF_DISPLAY = ['xpdf', '-q', '-geometry', 'x300-0-0']

# URLs to resolve a DOI with crossref.org or doi.org - {} becomes the DOI
XREF_URL = 'http://api.crossref.org/works/{}/transform/application/x-bibtex'
DOI_URL = 'https://doi.org/{}'

# Declare type for BibTeX entries: key -> value dictionary, both are strings
BibEntry = Dict[str, str]

# Standard names found in BibTeX files when months are given as strings
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
          'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

# A regular expression (RE) matching a DOI (Digital Object Identifier)
DOI_RE = r'\b10\.\d{4,}/[A-Za-z\d()[\]{}<>%._/#:;-]+[A-Za-z\d]\b'

# NOTE 1: In this code we deliberately use mutable defaults to memorize
# INITIALLY EMPTY PRIVATE lists and dictionaries (either [] or {}).
# The pylint3 complaints about dangerous-default-value are irrelevant.

# NOTE 2: The following kinds of key, val pairs are used through record()
# 'all_confirm'  True or False to confirm 'all' or 'none' text queries
# 'unique_int'   successive negative integers, used as unique keys
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


def make_ay_key(entry: BibEntry) -> str:
    """Make AY (author-year) partial key, with surname of the first author
       (lower-case, non alphabetic characters removed) and publication year"""
    author = entry.get('author', 'unknown')
    author = re_find(author, '^(.*?)( and |$)', 1)
    au_dict = bibtexparser.customization.splitname(author, strict_mode=False)
    author = ' '.join(au_dict['last'])
    author = re_strip(author.lower(), r'\\[a-hj-z][a-z]*', r'[^a-z]')
    year = re_find(entry.get('year', '9999'), r'\d{4}')
    return author + year


def make_pm_key(entry: BibEntry) -> str:
    """Make PM (page-month) partial key, with the first page (if available)
       and a final character in 'a b ... l' to indicate the publication month
       'jan feb ... dec' (if available). Return 'm' if both are unavailable."""
    page = re_find(entry.get('pages', ''), r'[0-9]+')
    if 'month' in entry:
        month = entry['month']
        if re.match(r'^(0?[1-9]|1[012])$', month):
            imonth = int(month) - 1
        else:
            imonth = MONTHS.index(month[:3].lower())
        page += chr(imonth + ord('a'))
    return page or 'm'


def record(key: Any, val: Any = None, default: Any = None,
           memo_dict: Dict[Any, Any] = {}) -> Any:
    """Record a mapping in an INITIALLY EMPTY PRIVATE dictionary. If val is
       supplied (not None) store dict[key] = val and return val. If val is
       None return the stored dict[key] if available, default otherwise."""
    if val is None:
        return memo_dict.get(key, default)
    memo_dict[key] = val
    return val


def make_safe_key(entry: BibEntry) -> str:
    """Make safe key: DOI or ISBN string if available, or unique '-1', '-2' ..."""
    return (entry.get('doi') or
            entry.get('isbn') or
            str(record('unique_int', record('unique_int', default=0) - 1))).lower()


def make_unsafe_key(entry: BibEntry) -> str:
    """Make unsafe key. DOI and ISBN are safe keys which uniquely identify
       a publication, but may be absent. This function returns the AYP
       (author-year-page) combination, which MIGHT be unique."""
    return make_ay_key(entry) + re_find(entry.get('pages', '0'), r'[0-9]+')


def make_ayc_key(entry: BibEntry, next_char: Dict[str, str] = {}) -> str:
    """Make AYC (author-year-character) unique key. Like make_ay_key() with a
       final character in 'a b ... l' to indicate the publication month 'jan
       feb ... dec' if available, or the last digit '0 1 ... 9' of the page
       if available, or 'm' if both are unavailable. In case of collisions,
       successive characters 'n o p q ..." are used to ensure an unique
       key. An INITIALLY EMPTY PRIVATE dictionary is used store the next
       free character to be used, with the default AYC as the key."""
    author_year = make_ay_key(entry)
    page_month = make_pm_key(entry)
    char = page_month[-1]
    ayc_key = author_year + char
    if ayc_key in next_char:
        char = next_char[ayc_key]
        next_char[ayc_key] = chr(ord(char) + 1)
        ayc_key = author_year + char
    else:
        next_char[ayc_key] = 'n'
    assert re.match(r'^[0-9a-z]$', char), 'Too many bib entries with the same author-year-character'
    return ayc_key


def user_confirm(bib: str, filename: str) -> Any:
    """Ask user to confirm a BibTeX entry: display entry (in a xterm window) and
       PDF file (if given), and ask 'n, y, all, none' to user. Record 'all' or
       'none' answer. Return Truthy ('y' or 'all') or Falsy ('n' or 'none')."""
    proc1 = subprocess.Popen(TXT_DISPLAY + [bib])
    if filename:
        proc2 = subprocess.Popen(PDF_DISPLAY + [filename])
    try:
        answer = input('     Reference is correct? n (default), y, all, none: ')
    except EOFError:
        answer = 'none'
    proc1.terminate()
    if filename:
        proc2.terminate()
    answer = re_find(answer.lower(), r'[a-z]+')
    if re.match(r'^(all|none)', answer):
        command(answer, entries=[])
    return re.match('^[ay]', answer)


def doi2str(doi: str, url: str) -> str:
    """Insert DOI at {} in URL, query URL and return BibTeX entry as a string"""
    response = requests.get(url.format(doi),
                            headers={'accept': 'application/x-bibtex'})
    if response.status_code == 200:
        return response.text
    return ''


def isbn2str(isbn: str) -> str:
    """Given ISBN string, query WWW and return BibTeX entry as a string"""
    return registry.bibformatters['bibtex'](meta(isbn, 'openl'))


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
    """Commands doi-add, rename-files, all, none (check only the first letter).
       Return all obtained entries as a string for doi-add, or '' otherwise."""
    if re.match(r'^d', txt):
        return doi_add(entries=entries)
    if re.match(r'^r', txt):
        rename_files(entries=entries)
    if re.match(r'^[an]', txt):
        record('all_confirm', txt[0] == 'a')
    return ''


def item2str(txt: str, filename: str = '', entries: List[BibEntry] = []) -> str:
    """Convert any item to BibTeX entries as a string. Query WWW for DOI, ISBN or
       search text. Convert files as appropriate. Handle -whatever commands. The
       filename and entries parameters are just forwarded to suitable functions."""
    txt = re_find(txt, r'^\s*(.*?)\s*$', 1)
    if len(txt) < 2:
        return ''
    item_trace(txt=txt)
    if re.match(DOI_RE, txt):
        return doi2str(txt, XREF_URL) or doi2str(txt, DOI_URL)
    if re.match(r'^\d[\d-]{8,15}[\dX]$', txt):
        return isbn2str(txt)
    if re.search(r'(\S+\s+){4}\S', txt):
        return query2str(txt, filename=filename)
    if re.match(r'^-[A-Za-z-]+$', txt):
        return command(txt[1:].lower(), entries=entries)
    return file2str(txt)


def query2str(txt: str, filename: str) -> str:
    """Given a search text, query CROSSREF to obtain a probable DOI, convert
       to BibTeX entry as a string, and return it if confirmed by the user."""
    if record('all_confirm') is False:
        return ''

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
       2 pages of a PDF file anything that looks like a DOI, if possible.
       Otherwise, use the first 200 characters as search text to query CROSSREF."""
    txt = os.popen(f"pdftotext -q -l 2 {filename} -").read()
    if not txt or len(txt) < 10:
        return ''
    doi = re_find(txt, DOI_RE)
    if doi:
        return item2str(doi)
    txt = re.sub(r'\s+', ' ', txt)[:200]
    return item2str(txt, filename=filename)


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


def doi_add(entries: List[BibEntry]) -> str:
    """Given list of BibTeX entries, attempt to obtain all missing DOIs by
       querying CROSSREF, and return all obtained entries as a string"""
    return '\n\n'.join(item2str(entry2query(entry), filename=jabfile(entry))
                       for entry in entries
                       if 'doi' not in entry)


def rename_files(entries: List[BibEntry]) -> None:
    """If a BibTeX entry contains a 'file' field, or if the entry is obtained
       from a PDF file, the 'file' field is updated (or created) with the AYC
       (author-year-character ID) of the entry as basename. All files matching
       the old basename are renamed with the new basename if they differ."""
    for entry in entries:
        path = jabfile(entry)
        if path:
            head, tail = os.path.split(path)
            root, ext = (re.match(r'(?i)^([a-z]+\d{2,4}[a-z\d]?)([_-].+)$', tail) or
                         re.match(r'^(.+?)(\.?[^.]*)$', tail)).group(1, 2)
            newroot = entry['ID']
            jabfile(entry, os.path.join(head, newroot + ext))
            if root != newroot:
                os.system(f"rename.ul -v '{root}' '{newroot}' '{os.path.join(head, root)}'[._-]*")


def cleanup_entry(entry: BibEntry, item: str) -> None:
    """Clean DOI, delete URLs which are DOIs, add FILE if available"""
    if 'doi' in entry:
        entry['doi'] = re_find(entry['doi'], DOI_RE)
    if 'url' in entry and re.search(r'[/.]doi[/.].*10\.\d\d\d\d', entry['url']):
        del entry['url']
    if re.search(r'(?i)\.pdf$', item):
        jabfile(entry, item)


def add2database(entries: List[BibEntry], entry: BibEntry, item: str,
                 memo_dict: Dict[str, int] = {}) -> None:
    """Append one BibTeX entry to list of entries (if not there already),
       or just add any missing field (otherwise). An INITIALLY EMPTY PRIVATE
       dictionary is used to index the list, with both safe (DOI or ISBN) and
       unsafe AYP (author-year-page) keys. The value associated to a key is
       the position (the index) of the corresponding entry in the list."""
    cleanup_entry(entry, item)
    safe_key = make_safe_key(entry)
    unsafe_key = make_unsafe_key(entry)
    num = memo_dict.get(safe_key) or memo_dict.get(unsafe_key)
    if num is not None:
        for field, value in entry.items():
            if field != 'ID' and field not in entries[num]:
                entries[num][field] = value
    else:
        entry['ID'] = make_ayc_key(entry)
        memo_dict[unsafe_key] = memo_dict[safe_key] = len(entries)
        entries.append(entry)


def main(items: List[str]) -> None:
    """bib.py - Create, combine, complete and clean BibTeX bibliographies.

Usage: bib.py item ...

The script obtains BibTeX entries from one or more items given as
arguments. The items are interpreted as in the following examples:

   bibtex.bib         BibTeX bibliography file
   10.1002/jrs.4278   DOI (Digital Object Identifier)
   9780553109535      ISBN (International Standard Book Number)
   'title and more'   search text (title, author ... whatever)
   fermi1932.pdf      PDF (Portable Document Format) file
   -doi-add           add missing DOIs to all PREVIOUS entries
   -rename-files      rename files as AYC for all PREVIOUS entries
   -all-confirm       grant search text confirmation from NOW ON
   -none-confirm      deny search text confirmation from NOW ON
   any-text-file      a list of any of the items above

BibTeX files are read in. Data from DOI, ISBN or search text is obtained by
querying doi.org and crossref.org. PDF files are scanned to extract anything
that looks like a DOI if possible, search text otherwise. Commands -doi-add,
-rename-files, -all-confirm and -none-confirm are obeyed. Any other item is
taken as a text file containing a list of the items above, by paragraph or by
line. Since BibTeX entries obtained by searching text are unreliable, they
line. Unreliable BibTeX entries obtained by searching text are accepted only
if the user confirms them (unless -all-confirm or -none-confirm are given).
The first argument MUST be a bibtex file, which is read if existing or
created if not, and which receives all obtained BibTeX entries.

    """

    # Arguments: one or more items, the first must match '*.bib'
    assert items and re.search(r'(?i)\.bib(tex)?$', items[0]), main.__doc__

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
