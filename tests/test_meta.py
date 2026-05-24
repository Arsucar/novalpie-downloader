import sys
from novalpie.network import fetch_book_meta, make_session
from novalpie.utils import read_cookie_line

book_id = 458
chapter_url = 'https://novalpie.cc/book/1535/352729'

cookie_line = read_cookie_line('./novalpie.txt')
session = make_session(cookie_line)

print(f'Testing book_id: {book_id}')

meta = fetch_book_meta(session, book_id, chapter_url)
print('\n=== Book Meta ===')
print(f'Title: {repr(meta.title)}')
print(f'Author: {repr(meta.author)}')
print(f'Description: {repr(meta.description)}')
print(f'Tags: {meta.tags}')
