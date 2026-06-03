"""
Локальный сервер для разработки iprahelp.ru
Запуск: python3 serve_local.py
Открыть: http://localhost:8080/index.html
"""
import http.server
import socketserver
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR   = os.path.join(SCRIPT_DIR, '..', 'site')

PORT = 8080

os.chdir(SITE_DIR)
Handler = http.server.SimpleHTTPRequestHandler

print(f'Сервер запущен: http://localhost:{PORT}/index.html')
print('Для остановки: Ctrl+C')

with socketserver.TCPServer(('', PORT), Handler) as httpd:
    httpd.serve_forever()
