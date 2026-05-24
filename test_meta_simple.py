import sys
import importlib
import subprocess

# 强制重新加载模块
if 'novalpie' in sys.modules:
    del sys.modules['novalpie']

from novalpie import fetch_book_meta, make_session, read_cookie_line, sync_playwright

print(f'Playwright available: {sync_playwright is not None}')

book_id = 353690
chapter_url = 'https://novalpie.cc/book/353690/8853740'

cookie_line = read_cookie_line('./novalpie.txt')
session = make_session(cookie_line)

print(f'Testing book_id: {book_id}')

meta = fetch_book_meta(session, book_id, chapter_url)
print('\n=== Book Meta ===')
print(f'Title: {repr(meta.title)}')
print(f'Author: {repr(meta.author)}')
print(f'Description: {repr(meta.description)}')
print(f'Tags: {meta.tags}')
