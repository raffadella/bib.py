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

import subprocess
import urllib
import functools
import requests
import bibtexparser
import isbnlib
import unidecode

# Local configuration: your email, used to identify yourself when querying CROSSREF
USER_INFO = 'mailto:raffaele.dellavalle@unibo.it'

# URLs to resolve a DOI with crossref.org or doi.org - {} becomes the DOI
XREF_URL = 'http://api.crossref.org/works/{}/transform/application/x-bibtex'
DOI_URL = 'https://doi.org/{}'

# A regular expression (RE) matching a key (either ISBN or DOI)
KEY_RE = r'\b(ISBN(-10|-13|)[:\s]+\d[\d -]{8,15}[\dX]|10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d])\b'

# A regular expression (RE) matching EBOOK types handled by ebook-meta
EBOOK_RE = r'(?i)\.(azw|azw[134]?|docx|epub|mobi|odt|rtf|pdf)$'

# Standard names found in BibTeX files when months are given as strings
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
          'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

# We use a single global variable, CONFIRM, set only by function command() and
# tested only by function query2bib(). It controls y/n queries to the user.
# Its possible values are True, False and None. True and False correspond to
# options -y and -n (always accept or deny without asking). None means "ask".
CONFIRM = None

# Declare type for BibTeX entries: key -> value dictionary, both are strings
BibEntry = dict[str, str]

# NOTE: In this code we deliberately use mutable defaults to memorize
# INITIALLY EMPTY PRIVATE lists and dictionaries (either [] or {}).
# The pylint complaints about dangerous-default-value are irrelevant.

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


def str2alphabetic(txt: str) -> str:
    """Convert string to str2alphabetic characters. Letters with
       diacritical marks are converted to their normal equivalents.
       TeX diacritics such as \v{c} and all non alphabetic
       characters are stripped. Return the string in lower case."""
    txt = unidecode.unidecode(txt)
    return re_strip(txt, r'\\[utrdcvHkb]\{', r'[^A-Za-z]').lower()


def str2chksum(txt: str, divisor: int) -> int:
    """Return the checksum of a string, modulo the given divisor. The string is
    first converted to lower case, with non str2alphabetic characters removed."""
    txt = str2alphabetic(txt)
    return functools.reduce(lambda nm, ch: (nm + ord(ch)) % divisor, txt, 0)


def entry2ay_key(entry: BibEntry) -> str:
    """Make AY (author-year) partial key, with surname of the first author
       (lower-case, non str2alphabetic characters stripped) and publication year.
       Keep only last word for quoted surnames containg spaces {{Tito Livio}}.
       For empty years, use 9900 plus the modulo 1000 checksum of the title."""
    author = entry.get('author') or entry.get('editor', 'unknown')
    author = re_find(author, '^(.*?)( and |$)', 1)
    au_dict = bibtexparser.customization.splitname(author, strict_mode=False)
    author = ''.join(au_dict['last'])
    author = re_find(author, '.*?([^ }]+)}*$', 1)
    author = str2alphabetic(author)
    year = re_find(entry.get('urldate', entry.get('year', '')), r'\d{4}')
    if not year:
        year = f'9{str2chksum(entry.get("title", ""), 1000):03d}'
    return author + year


def entry2char_key(entry: BibEntry) -> str:
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


def entry2ayc_key(entry: BibEntry) -> str:
    """Make AYC (author-year-character) key. Like entry2ay_key() with the
       final character discussed for entry2char_key(). To avoid overwrites,
       return existing AYC if already present with correct author and year."""
    author_year = entry2ay_key(entry)
    if author_year == entry['ID'][:-1]:
        return entry['ID']
    char = entry2char_key(entry)
    ayc_key = author_year + char
    return ayc_key


def entry2safe_key(entry: BibEntry) -> str:
    """Make key: DOI or ISBN string if available, otherwise first author, plus
       year, plus title (in lower case with non alphanumeric characters removed).
       DOI and ISBN uniquely identify a publication and thus are safe keys, but
       may be absent. The author-year-title key used as fallback SHOULD be safe."""
    return ( entry.get('doi') or
             entry.get('isbn') or
             entry2ay_key(entry) + re_strip(entry.get("title", "").lower(), r'[^a-z0-9 ]') )


def user_confirm(bib: str, txt: str, pdf_file: str) -> bool:
    """Ask user to confirm a BibTeX entry: display search text, found entry and
       PDF file (if given), and ask 'n, y, N, Y' to user. Record 'Y' or 'N' answer
       (which hold from now on). Return True ('y' or 'Y') or False ('n' or 'N')."""

    print('-' * 77)
    print('SEARCHED:', txt)
    print('OBTAINED:', bib)

    if pdf_file:
        proc = subprocess.Popen(['okular', pdf_file])
    try:
        answer = input('     Reference is correct? n (default), y, N, Y (for all): ')
    except (EOFError, KeyboardInterrupt):
        answer = 'n'
        print("\t", answer)
    if pdf_file:
        proc.terminate()

    answer = re_strip(answer, r'[^nyNY]')
    if re.match(r'^[YN]', answer):
        command(answer, entries=[])
    return bool(re.match('^[yY]', answer))


def doi2bib(doi: str, url: str) -> str:
    """Given DOI string, insert at {} in URL, query URL and return BibTeX
       entry as a string if successful, otherwise return empty string."""
    response = requests.get(url.format(doi),
                            timeout=10,
                            headers={'accept': 'application/x-bibtex'})
    if response.status_code == 200:
        return response.text
    return ''


def isbn2bib(isbn: str, service: str = 'goob') -> str:
    """Given ISBN string, query either 'goob' (Google Books, default) or
       'openl' (CROSSREF) WWW service and return BibTeX entry as a string"""
    if isbnlib.notisbn(isbn, level='strict'):
        return ''
    isbn = isbnlib.to_isbn13(isbnlib.canonical(isbn))
    return isbnlib.registry.bibformatters['bibtex'](isbnlib.meta(isbn, service=service))


def jabfile(entry: BibEntry, filename: str = '') -> str:
    """JabRef filenames handling. JabRef stores filenames surrounded by ':'
       characters in a 'file' field of the BibTeX entry. This function stores
       the filename if given, or returns it without the ':', otherwise."""
    if filename:
        entry['file'] = ':' + filename + ':'
        return ''
    return re_find(entry.get('file', ''), '^:?(.+?):?$', 1)


def command(txt: str, entries: list[BibEntry]) -> str:
    """Handle commands COMPLETE, RENAME, YES, NO (check only the first letter)."""
    if re.match(r'^[cC]', txt):
        complete(entries=entries)
    if re.match(r'^[rR]', txt):
        rename_files(entries=entries)
    if re.match(r'^[yYnN]', txt):
        global CONFIRM
        CONFIRM = txt[0].lower() == 'y'
    return ''


def item2bib(item: str, entries: list[BibEntry] = []) -> str:
    """Convert any item to BibTeX entries packed as a string. Return *.bib files
       as a string. Query WWW for DOI, ISBN or search text. Convert files as
       appropriate. Handle -whatever commands. Split other files either by
       paragraphs (if possible) or by lines (otherwise), convert each fragment to
       a BibTeX entry as a string and return all concatenated entries. The entries
       parameter is just forwarded to suitable functions."""
    item = item.strip()
    if len(item) < 1:
        return ''
    try:
        if re.search(r'(?i)\.bib(tex)?$', item):
            return open(item, encoding = 'utf8').read()
        if re.match(r'^10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d]', item):
            return doi2bib(item, XREF_URL) or doi2bib(item, DOI_URL)
        if re.match(r'^\d[\d -]{8,15}[\dX]$', item):
            return isbn2bib(item, 'openl') or isbn2bib(item, 'goob')
        if re.search(r'(?i)\.pdf$', item):
            return pdf2bib(item)
        if re.search(EBOOK_RE, item):
            return entry2bib(ebook2entry(item))
        if re.match(r'^-[A-Za-z]', item):
            return command(item[1:], entries=entries)
        if re.search(r'(\S+\s+){4}\S', item):
            return query2bib(item)
        item = open(item, encoding = 'utf8').read()
        separator = r'\n\n+' if re.search(r'\S\s*\n\n+\s*\S', item) else r'\n'
        return '\n\n'.join(item2bib(re.sub(r'\s+', ' ', item))
                           for item in re.split(separator, item))
    except (Exception, KeyboardInterrupt) as exception:
        print('     Ignored exception:', exception)
        return ''


def query2bib(txt: str, pdf_file: str = '') -> str:
    """Given a search text, return a BibTeX entry as a string. Try to extract
       anything that looks like an ISBN or a DOI and search for that. Failing
       this, use about 400 characters as search text. Query Google Books to
       obtain a likely ISBN, on failure query CROSSREF to obtain a likely
       DOI, and search for that. Queries fail if not confirmed by the user."""
    if len(txt) < 13:
        return ''

    key = re_find(txt, KEY_RE, 1)
    if key:
        key = re_strip(key, r'^ISBN(-10|-13|)[:\s]+')
        return item2bib(key.replace(r' ', ''))

    if CONFIRM is False:
        return ''

    txt = re_find(txt, r'^[\S\s]{1,400}[^ ]*')
    isbn = isbnlib.isbn_from_words(txt)
    if isbn:
        bib = isbn2bib(isbn, "goob")
        if bib and (CONFIRM or user_confirm(bib, txt, pdf_file)):
            return bib

    url = 'https://api.crossref.org/works'
    params = {'rows': '1', 'query.bibliographic': txt, 'select': 'DOI'}
    headers = {'User-Agent': f"DOI Importer ({USER_INFO})"}
    url = url + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, None, headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        encoding = response.info().get_param('charset', 'utf8')
        doi = response.read().decode(encoding)
    doi = re_find(doi, r'{"DOI":"(10\.\d{4,}[^"]+)"}', 1)
    doi = doi.replace(r'\/', '/')

    bib = item2bib(doi)
    if bib and (CONFIRM or user_confirm(bib, txt, pdf_file)):
        return bib
    return ''


def pdf2bib(pdf_file: str) -> str:
    """Given a PDF file, return a BibTeX entry as a string. Just extract from
       first 5000 characters of the PDF file and pass everything to query2bib()."""
    txt = subprocess.run(['pdftotext', '-enc', 'ASCII7', '-nopgbrk', '-q', '-l', '8', pdf_file, '-'],
                         check=True, text=True, capture_output=True).stdout[:5000]
    return query2bib(txt, pdf_file=pdf_file)


def entry2bib(entry: BibEntry):
    """Pack BibTeX dictionary entry into a string, only for the main fields."""
    bibtex = '@book{EPUB,'
    for (key, val) in entry.items():
        if key in ['author', 'publisher', 'title', 'year']:
            bibtex += key + ' = {' + val + '},\n'
    bibtex += '}\n'
    return bibtex


def ebook2entry(filename: str) -> BibEntry:
    """Given an EBOOK, convert metadata to a BibTeX dictionary entry."""
    entry = {}
    txt = subprocess.run(['ebook-meta', filename],
                         check=True, text=True, capture_output=True).stdout
    for line in txt.splitlines():
        (key, val) = re.split("[^A-Za-z][^:]*:", line, maxsplit=1)
        entry[key.lower()] = val.strip()
    entry['year'] = re_find(entry.get('published',''), r'\d{4}')
    return entry


def entry2query(entry: BibEntry) -> str:
    """Given BibTeX entry as a list, return text string appropriate for a query"""
    return ' '.join(entry.get(field, '')
                    for field in ['year', 'title', 'author', 'publisher'])


def complete(entries: list[BibEntry]) -> None:
    """Given list of BibTeX entries, attempt to complete it. If DOI and ISBN
        are both missing, build text query with available data, query the
        WWW, and merge newly found and previous BibTeX entries. Only fields
        previously non existing are filled with the newly found data."""
    for num, entry in enumerate(entries):
        if 'doi' not in entry and 'isbn' not in entry:
            txt = entry2query(entry)
            txt = item2bib(txt)
            if txt:
                bib = bibtexparser.loads(txt).entries[0]
                entries[num] = {**bib, **entry}


def rename_files(entries: list[BibEntry]) -> None:
    """If a BibTeX entry contains a 'file' field, or if the entry is
       obtained from a PDF file, the 'file' field is updated (or created)
       with the AYC (author-year-character ID) of the entry as basename.
       All files matching the old basename are renamed with the new
       basename.  Files with spaces in the name are never renamed."""
    for entry in entries:
        filename = jabfile(entry)
        if filename and not re_find(filename, r' '):
            head, tail = os.path.split(filename)
            root, ext = (re.match(r'^(.+?)(\.?[^.]*)$', tail)).group(1, 2)
            newroot = entry['ID']
            jabfile(entry, os.path.join(head, newroot + ext))
            if root != newroot:
                os.system(f"rename 's:{root}:{newroot}:' '{os.path.join(head, root)}'[._-]*")


def cleanup_entry(entry: BibEntry, item: str) -> None:
    """Clean DOI field, delete URLs which are DOIs, and add a FILE field
       if the item argument matches an EBOOK regexp (including PDF)."""
    if 'doi' in entry:
        entry['doi'] = re_find(entry['doi'], r'10\.\d{4,}/[\w()[\]{}<>%./#:;-]+[A-Za-z\d]')
    if 'url' in entry and re.search(r'[/.]doi[/.].*10\.\d\d\d\d', entry['url']):
        del entry['url']
    if re.search(EBOOK_RE, item):
        jabfile(entry, item)


def next_letter(chars: str) -> str:
    """Starting from the last character of a string, return the next
    'a'...'z' letter (in cyclic order) not already present in the string."""
    assert len(chars) < 25, "Too many AYC collisions (more than 25)"
    num = ord(chars[-1]) - ord("a")
    while True:
        num = (num + 1) % 25
        char = chr(num + ord("a"))
        if char not in chars:
            return char


def add2database(entries: list[BibEntry], entry: BibEntry, item: str,
                 key2num_dict: dict[str, int] = {},
                 key2chr_dict: dict[str, str] = {}) -> None:
    """Append one BibTeX entry to list of entries (if not yet present), or
       add any missing or empty field (otherwise). Two INITIALLY EMPTY
       PRIVATE dictionaries, with a safe key (DOI, ISBN, or AYC plus title)
       are used. For key2num_dict the value associated to the key is the
       position (the index) of the corresponding entry in the list. For
       key2chr_dict the value is a string with all letters already used for
       AYC keys, to discover collisions. In case of an AYC collision,
       we select the next unused 'a'...'z' letter (in cyclic order)."""
    cleanup_entry(entry, item)
    safe_key = entry2safe_key(entry)
    num = key2num_dict.get(safe_key)
    if num is not None:
        for field, value in entry.items():
            if field != 'ID' and not entries[num].get(field):
                entries[num][field] = value
    else:
        ayc_key = entry2ayc_key(entry)
        if ayc_key in key2chr_dict:
            char = next_letter(key2chr_dict[ayc_key])
            key2chr_dict[ayc_key] += char
            ayc_key = ayc_key[:-1] + char
        else:
            key2chr_dict[ayc_key] = ayc_key[-1]

        entry['ID'] = ayc_key
        key2num_dict[safe_key] = len(entries)
        entries.append(entry)


def main(items: list[str]) -> None:
    """bib.py - Create, combine, complete and clean BibTeX bibliographies.

Usage: bib.py item ...

The script obtains BibTeX entries from one or more items given as
arguments. The items are interpreted as in the following examples:

   bibtex.bib         BibTeX bibliography file (*.bib or *.bibtex)
   10.1002/jrs.4278   DOI (Digital Object Identifier)
   9780553109535      ISBN (International Standard Book Number)
   'title and more'   search text (title, author ... whatever)
   fermi1932.pdf      a PDF (Portable Document Format) file
   "The Bible.epub"   an EBOOK (as AZW, DOCX, EPUB, MOBI, ODT or RTF)
   -rename            rename files as AYC for all PREVIOUS entries
   -complete          add missing DOI or ISBN to all PREVIOUS entries
   -yes               answer YES to all confirm queries from NOW ON
   -no                answer NO to all confirm queries from NOW ON
   any-text-file      file containing a sequence of the items above

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
    # database and the item are passed to item2bib and add2database which
    # might forward them to cleanup_entry and query2bib, respectively.
    for item in items:
        bibstr = item2bib(item, entries=bibtex_database.entries)
        if bibstr:
            for entry in bibtexparser.loads(bibstr).entries:
                add2database(bibtex_database.entries, entry, item)

    # Dump final database if not empty
    if bibtex_database.entries:
        with open(items[0], 'w', encoding = 'utf8') as outfile:
            bibtexparser.dump(bibtex_database, outfile)
            print(f'{len(bibtex_database.entries):4d} BibTeX entries')


# Call "main" with command line arguments when invoked as a script
if __name__ == '__main__':
    main(sys.argv[1:])
