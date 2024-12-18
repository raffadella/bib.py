
bib.py
------

Create, combine, complete and clean BibTeX bibliographies.

The **bib.py** python script creates BibTeX bibliographies starting from just about any kind of file or information from which bibliographic data can be extracted or deduced.


Features
--------

* Output files are in a format suitable for reference managers able to handle BibTeX, such as JabRef.

* DOI (Digital Object Identifier) and ISBN (International Standard Book Number) resolution.

* Search **crossref.org** and **google books** for authors, title, year, etc.

* Extract DOI, ISBN and search text from PDF files.


History and purpose
-------------------

I've written **bib.py** to solve a problem that also other people might have, and for this reason I've decided to share it. I've been publishing scientific papers for about 40 years and I've accumulated bibliographic data in many different forms:

* Modern BibTeX files complete with DOI (Digital Object Identifier) and ISBN (International Standard Book Number) information.

* Ancient BibTeX files without DOI or ISBN information.

* Textual bibliographies in TeX (before BibTeX) or extracted from various kinds of files (PDF, DOC and long-forgotten word processors such as WordStar).

* Folders (directories) with lots of PDF files without an index to their content.

I wanted to generate BibTeX files for my heterogeneous collection of bibliographic data with as little effort as possible, and for this purpose I've written the script **bib.py**. The script does not attempt to clean and reformat BibTeX entries, since good tools such as JabRef ( https://github.com/JabRef/jabref ) and bibtexformat ( https://github.com/yfpeng/pengyifan-bibtexformat ) exist for this.


Usage
-----

The script **bib.py** is used on the command line as

* **bib.py** destination.bib item1 item2 item3 ...

  The first argument (destination.bib in all examples) is required and must be a BibTeX file (a *.bib or *.bibtex file), which is read if existing or created if not, and which receives all BibTeX entries obtained from all 'items' given as arguments (if any). Erroneous arguments and empty or non-existing files are gracefully ignored.


Examples
--------

The behaviour of the script is best explained through some examples:

* **bib.py**

  Display usage message and stop.

* **bib.py** destination.bib source1.bib source2.bib source3.bib

  Combines BibTeX files: destination.bib receives BibTeX entries from all files. Entries are considered duplicated if they have the same DOI, or the same ISBN or, if DOI and ISBN are both missing, the same first author, year and title. Only the first of a set of duplicated entries is kept, except for missing fields (if any) which are taken from later entries.

  Each distinct (i.e. non duplicated) entry receives an AYC (author-year-character) key of the form 'surname2010x', containing the surname of the first author (the editor if there is no author) converted to lower-case with non alphabetic characters removed, the publication year, and a final character that guarantees unicity. This character is **a** **b** ... **l** to indicate the publication month **jan** **feb** ... **dec** if available, or the last digit **0** **1** ... **9** of the page if available or, if both are unavailable, a letter from **m** to **z** based on a modulo 13 checksum of the title. A still unused letter from **a** to **z** is used in case of a collision (distinct entries which would otherwise have the same AYC keys). Whenever necessary, the AYC key is used as default file basename.

* **bib.py** destination.bib 10.1103/PhysRevD.46.603 9780553109535

  Obtain BibTeX entries for all given DOI and ISBN keys (by querying **doi.org** and/or **crossref.org**) and adds them to destination.bib.

* **bib.py** destination.bib '2005 Information loss in black holes'

  Obtain BibTeX entries by querying **crossref.org** and/or **google books** for title, author, year, etc. (only one paper in this example, with the publication year) and adds them to destination.bib. The search text must be quoted (with either **"** or **'**), and must contain at least five words to be recognized. Since BibTeX entries obtained by searching for text are unreliable, they are shown on the screen and the user is prompted for confirmation. The possible choices are: **y**, **n** (obvious), **Y** and **N** (always grant or deny confirmation from now on, without further prompting).

* **bib.py** destination.bib hawking1992.pdf hawking2005.pdf

  Scan the first few pages of each PDF file to extract anything that looks like an ISBN or a DOI, and use it to obtain a BibTeX entry. This will fail for the 1992 paper (like for most papers published before 2000). In this case the first 400 text characters (which often contains author, title, year, etc) are used to query **crossref.org** and/or **google books**. Since this method is very unreliable, the PDF file and the resulting BibTeX entry (if any) are shown on the screen. The entry is accepted only if the user confirms it. A **file** field is added to the entry, in the format used by JabRef.

* **bib.py** destination.bib **-yes** hawking1992.pdf hawking2005.pdf

  Exactly the same, but all BibTeX entries obtained by searching for text are accepted without asking for confirmation.

* **bib.py** destination.bib **-no** hawking1992.pdf hawking2005.pdf

  The opposite, text searching is disabled, and no entry obtained by searching for text is accepted. 

* **bib.py** destination.bib **-complete**

  Attempt to add ISBN or DOI to all BibTeX entries which do not have one, by quering **google books** and/or **crossref.org** with year, authors and title of the publication. The user is prompted for confirmation, as above.

* **bib.py** destination.bib **-rename**

  Files indicated in **file** fields and PDF files given as command line arguments are renamed to match the AYC (author-year-character) key which, as already mentioned, is used as default basename.  If the AYC is 'surname2010x' and the **file** field contains 'whatever.pdf', then all files starting with 'whatever' are renamed: 'whatever.pdf', 'whatever.txt' and 'whatever-01.dat' become 'surname2010x.pdf', 'surname2010x.txt' and 'surname2010x-01.dat'.

* **bib.py** destination.bib text-file

  Anything else (i.e. anything that is not BibTeX, DOI, ISBN, search text, PDF or -whatever) is taken as a text file containing items to be processed, and handled exactly as command line items (except that search text is not quoted). Items must be given one per paragraph (i.e. separated by one or more empty lines), or one per line. The first format (which is tried first) is probably preferable for year-author-title search text. The second is probably easier for lists of DOI, ISBN and PDF filenames.

* **bib.py** destination.bib /home/user/path/\*.pdf

  Add to destination.bib all BibTeX entries obtained from ISBN, DOI or search text extracted from all given PDF files. Created **file** fields will contain absolute paths, since file names start with **/**.

* **bib.py** destination.bib path/\*.pdf

  Add to destination.bib all BibTeX entries obtained from ISBN, DOI or search text extracted from all given PDF files. Created **file** fields will contain relative paths, since file names DO NOT start with **/**. With JabRef, this corresponds to the setting 'Options / Preferences / File / Use the BIB file location as primary file directory'. 

* **bib.py** destination.bib **-no** path/\*.pdf

  Add to destination.bib all BibTeX entries obtained from ISBN or DOI extracted from all given PDF files. Text searching is disabled since **-no** has been given. Only the first letter of the command is actually checked: **-no**, **-yes**, **-complete** and **-rename** may be shortened to **-n**, **-y**, **-c** and **-r**. Upper and lower cases are equivalent: **-N** is the same as **-n**.
  

BibTeX Field handling
---------------------

* Fields **author**, **editor**, **year**, **month**, **page** and **title** are used to construct AYC (author-year-character) BibTeX keys. When the field **year** is missing, AYC keys like 'surname9000x' are used. The last three character of the 'year' are a modulo 1000 checksum of the **title** field, converted to lower cases and with non-alphanumeric characters removed.

* Fields **doi** and **isbn**, if present, are used to uniquely identify BibTeX entries. If both are missing, fields **author** (or **editor**), **year** and **title** are instead used to identify entries.

* If possible, the **file** field is created with PDF file names given on the command line. The base name of the file is changed to the AYC key if the command **-rename-files** is given.

* If the **isbn** and **doi** field are missing and the command **-complete** is given, fields **author**, **year** and **title** are used to attempt to discover the actual ISBN and/or DOI.

* The **url** field is deleted if it actually contains a DOI and a **doi** field exists.

* All other field are neither used nor changed.  


Language
--------

* python3 with **mypy** type hints.


Requirements
------------

* Linux/Unix

* python3

* **subprocess**, **urllib**, **requests**, **bibtexparser**, **functools** and **isbnlib** (python packages)

* **pdftotext** and **rename** (command line tools, the latter is also known as **perl-rename**)

* **xterm** and **xpdf** (GUI tools, may be replaced with equivalent programs)


Installation
------------

* Satisfy all requirements.

* Copy **bib.py** anywhere on your path and ensure it is executable.

* Modify the variables **USER_INFO**, **TXT_DISPLAY** and **PDF_DISPLAY** at the beginning of the script as appropriate for your environment.

* The documented default value of the variable **common_strings** in the library **bparser.py** is **True**. However, some library versions instead set it to **False**. In this case, edit **bparser.py** to specify "**common_strings=True**".


License
-------

MIT


Author
------

Raffaele Guido Della Valle (https://raffaeledellavalle.neocities.org/, raffaele.dellavalle@unibo.it, raffadella@gmail.com)


Using **bib.py** as a library
-----------------------------

The script may be used a library (with **import bib**). All functions with names such as **Something2str** accept **Something** (given as a string) and return either BibTeX entries as a string (if they succed) or the empty string (if they fail). Functions with names like **make_Something_key** accept a BibTeX entry given as a field-value dictionary and return a **Something** key (as a string). Other functions return useful string values, **True** or **False** to indicate success or failure, or **None** if they are to be called only for side-effects and have nothing useful to return. A graph with the complete function call tree is available (https://github.com/raffadella/bib.py/blob/main/README.png). 


