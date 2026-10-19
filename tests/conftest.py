"""Gemeinsame Testseite für Recorder-Tests (Elemente absolut positioniert, damit Klickpositionen stabil sind)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PAGE = """<!doctype html><meta charset="utf-8"><title>Testbox</title>
<style>body{margin:0;font:16px sans-serif} .a{position:absolute;display:block}</style>
<input id="user" type="text" class="a" style="left:20px;top:20px;width:300px;height:30px">
<input name="pwd" type="password" class="a" style="left:20px;top:70px;width:300px;height:30px">
<button id="login" class="a" style="left:20px;top:120px;width:120px;height:30px"
  onclick="document.getElementById('panel').hidden=false">Anmelden</button>
<div id="panel" hidden>
  <input id="enabled" type="checkbox" class="a" style="left:20px;top:200px;width:20px;height:20px">
  <input id="hid" type="checkbox" style="display:none">
  <label for="hid" class="a" style="left:20px;top:240px;width:120px;height:24px">Versteckt</label>
  <a href="#x" class="a" style="left:20px;top:280px;width:60px;height:24px">Hilfe</a>
  <select id="mode" class="a" style="left:20px;top:320px;width:120px;height:30px">
    <option value="a">Alpha</option><option value="b">Beta</option></select>
  <button class="a" style="left:200px;top:200px;width:120px;height:30px"
    onclick="document.getElementById('status').textContent='gespeichert'">Übernehmen</button>
  <span id="status" class="a" style="left:200px;top:240px;width:150px;height:24px"></span>
  <button class="a" style="left:20px;top:360px;width:60px;height:30px">OK</button>
  <button class="a" style="left:20px;top:400px;width:60px;height:30px">OK</button>
  <input name="port" type="text" class="a" style="left:20px;top:440px;width:200px;height:30px">
</div>
<div class="a" style="left:3000px;top:3000px;width:10px;height:10px"></div>
<span id="pos" style="position:fixed;left:900px;top:20px;width:150px;height:24px">0,0</span>
<script>addEventListener("scroll",()=>{document.getElementById("pos").textContent=Math.round(scrollX)+","+Math.round(scrollY)})</script>
<img src="http://10.255.255.1/tracker.png" alt="">
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
