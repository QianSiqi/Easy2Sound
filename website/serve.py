import http.server
import os

PORT = 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))

handler = http.server.SimpleHTTPRequestHandler
handler.extensions_map.update({'.json': 'application/json', '.bmp': 'image/bmp'})

with http.server.HTTPServer(('localhost', PORT), handler) as s:
    print(f'本地服务器已启动: http://localhost:{PORT}')
    s.serve_forever()
