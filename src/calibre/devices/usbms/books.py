# -*- coding: utf-8 -*-

__license__ = 'GPL 3'
__copyright__ = '2009, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

import os, re, time, sys

from calibre.ebooks.metadata import MetaInformation
from calibre.devices.mime import mime_type_ext
from calibre.devices.interface import BookList as _BookList
from calibre.constants import filesystem_encoding, preferred_encoding
from calibre import isbytestring
from calibre.utils.config import prefs

class Book(MetaInformation):

    BOOK_ATTRS = ['lpath', 'size', 'mime', 'device_collections', '_new_book']

    JSON_ATTRS = [
        'lpath', 'title', 'authors', 'mime', 'size', 'tags', 'author_sort',
        'title_sort', 'comments', 'category', 'publisher', 'series',
        'series_index', 'rating', 'isbn', 'language', 'application_id',
        'book_producer', 'lccn', 'lcc', 'ddc', 'rights', 'publication_type',
        'uuid',
    ]

    def __init__(self, prefix, lpath, size=None, other=None):
        from calibre.ebooks.metadata.meta import path_to_ext

        MetaInformation.__init__(self, '')

        self._new_book = False
        self.device_collections = []
        self.path = os.path.join(prefix, lpath)
        if os.sep == '\\':
            self.path = self.path.replace('/', '\\')
            self.lpath = lpath.replace('\\', '/')
        else:
            self.lpath = lpath
        self.mime = mime_type_ext(path_to_ext(lpath))
        self.size = size # will be set later if None
        try:
            self.datetime = time.gmtime(os.path.getctime(self.path))
        except:
            self.datetime = time.gmtime()
        if other:
            self.smart_update(other)

    def __eq__(self, other):
        # use lpath because the prefix can change, changing path
        return self.lpath == getattr(other, 'lpath', None)

    @dynamic_property
    def db_id(self):
        doc = '''The database id in the application database that this file corresponds to'''
        def fget(self):
            match = re.search(r'_(\d+)$', self.lpath.rpartition('.')[0])
            if match:
                return int(match.group(1))
            return None
        return property(fget=fget, doc=doc)

    @dynamic_property
    def title_sorter(self):
        doc = '''String to sort the title. If absent, title is returned'''
        def fget(self):
            return re.sub('^\s*A\s+|^\s*The\s+|^\s*An\s+', '', self.title).rstrip()
        return property(doc=doc, fget=fget)

    @dynamic_property
    def thumbnail(self):
        return None

    def smart_update(self, other, replace_metadata=False):
        '''
        Merge the information in C{other} into self. In case of conflicts, the information
        in C{other} takes precedence, unless the information in C{other} is NULL.
        '''

        MetaInformation.smart_update(self, other, replace_metadata)

        for attr in self.BOOK_ATTRS:
            if hasattr(other, attr):
                val = getattr(other, attr, None)
                setattr(self, attr, val)

    def to_json(self):
        json = {}
        for attr in self.JSON_ATTRS:
            val = getattr(self, attr)
            if isbytestring(val):
                enc = filesystem_encoding if attr == 'lpath' else preferred_encoding
                val = val.decode(enc, 'replace')
            elif isinstance(val, (list, tuple)):
                val = [x.decode(preferred_encoding, 'replace') if
                        isbytestring(x) else x for x in val]
            json[attr] = val
        return json

class BookList(_BookList):

    def __init__(self, oncard, prefix, settings):
        _BookList.__init__(self, oncard, prefix, settings)
        self._bookmap = {}

    def supports_collections(self):
        return False

    def add_book(self, book, replace_metadata):
        try:
            b = self.index(book)
        except (ValueError, IndexError):
            b = None
        if b is None:
            self.append(book)
            return True
        if replace_metadata:
            self[b].smart_update(book, replace_metadata=True)
            return True
        return False

    def remove_book(self, book):
        self.remove(book)

    def get_collections(self):
        return {}

class CollectionsBookList(BookList):

    def supports_collections(self):
        return True

    def get_collections(self, collection_attributes):
        from calibre.devices.usbms.driver import debug_print
        debug_print('Starting get_collections:', prefs['manage_device_metadata'])
        collections = {}
        series_categories = set([])
        # This map of sets is used to avoid linear searches when testing for
        # book equality
        collections_lpaths = {}
        for book in self:
            # Make sure we can identify this book via the lpath
            lpath = getattr(book, 'lpath', None)
            if lpath is None:
                continue
            # Decide how we will build the collections. The default: leave the
            # book in all existing collections. Do not add any new ones.
            attrs = ['device_collections']
            if getattr(book, '_new_book', False):
                if prefs['manage_device_metadata'] == 'manual':
                    # Ensure that the book is in all the book's existing
                    # collections plus all metadata collections
                    attrs += collection_attributes
                else:
                    # For new books, both 'on_send' and 'on_connect' do the same
                    # thing. The book's existing collections are ignored. Put
                    # the book in collections defined by its metadata.
                    attrs = collection_attributes
            elif prefs['manage_device_metadata'] == 'on_connect':
                # For existing books, modify the collections only if the user
                # specified 'on_connect'
                attrs = collection_attributes
            for attr in attrs:
                attr = attr.strip()
                val = getattr(book, attr, None)
                if not val: continue
                if isbytestring(val):
                    val = val.decode(preferred_encoding, 'replace')
                if isinstance(val, (list, tuple)):
                    val = list(val)
                elif isinstance(val, unicode):
                    val = [val]
                for category in val:
                    if attr == 'tags' and len(category) > 1 and \
                            category[0] == '[' and category[-1] == ']':
                        continue
                    if category not in collections:
                        collections[category] = []
                        collections_lpaths[category] = set()
                    if lpath not in collections_lpaths[category]:
                        collections_lpaths[category].add(lpath)
                        collections[category].append(book)
                    if attr == 'series' or getattr(book, 'series', None) == category:
                        series_categories.add(category)
        # Sort collections
        for category, books in collections.items():
            def tgetter(x):
                return getattr(x, 'title_sort', 'zzzz')
            books.sort(cmp=lambda x,y:cmp(tgetter(x), tgetter(y)))
            if category in series_categories:
                # Ensures books are sub sorted by title
                def getter(x):
                    return getattr(x, 'series_index', sys.maxint)
                books.sort(cmp=lambda x,y:cmp(getter(x), getter(y)))
        return collections

    def rebuild_collections(self, booklist, oncard):
        '''
        For each book in the booklist for the card oncard, remove it from all
        its current collections, then add it to the collections specified in
        device_collections.

        oncard is None for the main memory, carda for card A, cardb for card B,
        etc.

        booklist is the object created by the :method:`books` call above.
        '''
        pass
