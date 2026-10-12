# -*- coding: utf-8 -*-
"""用 Chrome 的调试端口跑一遍页面，抓控制台报错和点击结果。诊断用。"""
import json
import socket
import struct
import sys
import time
import urllib.request
from base64 import b64encode
from hashlib import sha1

DEBUG = "http://127.0.0.1:9222"


class WS:
    def __init__(self, url):
        _, _, host, path = url.split("/", 3)
        self.sock = socket.create_connection((host.split(":")[0], int(host.split(":")[1])), timeout=15)
        key = b64encode(b"x" * 16).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, key))
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf = b""

    def send(self, obj):
        data = json.dumps(obj).encode()
        header = struct.pack("!BB", 0x81, 0x80 | 127) + struct.pack("!Q", len(data))
        mask = b"\x01\x02\x03\x04"
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout=8):
        self.sock.settimeout(timeout)
        try:
            b1, b2 = self._read(2)
            ln = b2 & 127
            if ln == 126:
                ln = struct.unpack("!H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._read(8))[0]
            return self._read(ln).decode("utf-8", "ignore")
        except socket.timeout:
            return None

    def cmd(self, mid, method, params=None, wait=True):
        self.send({"id": mid, "method": method, "params": params or {}})
        if not wait:
            return None
        while True:
            msg = self.recv()
            if msg is None:
                return None
            j = json.loads(msg)
            if j.get("id") == mid:
                return j


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8756/"
    targets = json.loads(urllib.request.urlopen(DEBUG + "/json/list", timeout=5).read())
    page = [t for t in targets if t["type"] == "page"][0]
    ws = WS(page["webSocketDebuggerUrl"])
    events = []
    ws.cmd(1, "Runtime.enable")
    ws.cmd(2, "Page.enable")
    ws.cmd(3, "Log.enable")
    ws.cmd(4, "Page.navigate", {"url": url})
    time.sleep(3)

    # 收集已经推送到的事件
    ws.sock.settimeout(0.3)
    while True:
        try:
            msg = ws.recv(0.3)
        except Exception:
            break
        if not msg:
            break
        events.append(json.loads(msg))

    print("=== 控制台 / 异常 ===")
    found = False
    for e in events:
        m = e.get("method")
        if m == "Runtime.exceptionThrown":
            found = True
            d = e["params"]["exceptionDetails"]
            print("异常:", d.get("text"), "|",
                  (d.get("exception") or {}).get("description", "")[:300])
            print("  位置:", d.get("url"), d.get("lineNumber"))
        if m == "Runtime.consoleAPICalled":
            args = [a.get("value") or a.get("description") for a in e["params"].get("args", [])]
            print("console.%s:" % e["params"].get("type"), args)
        if m == "Log.entryAdded":
            lv = e["params"]["entry"]
            print("log[%s]:" % lv.get("level"), lv.get("text"), lv.get("url"), lv.get("lineNumber"))
    if not found:
        print("（没有 JS 异常）")

    def ev(expr, label):
        r = ws.cmd(100 + hash(expr) % 1000, "Runtime.evaluate",
                   {"expression": expr, "returnByValue": True, "awaitPromise": True})
        try:
            v = r["result"]["result"].get("value")
        except Exception:
            v = r
        print("%s => %s" % (label, v))
        return v

    print("\n=== 页面状态 ===")
    ev("document.querySelectorAll('.view').length", "视图数量")
    ev("document.querySelector('#view-drill').className", "刷词视图 class")
    ev("!!window.onerror", "onerror 是否绑定")
    ev("typeof $", "$ 是否存在")
    ev("!!(document.querySelector('#word')||{}).textContent", "卡片文字存在")
    ev("document.querySelector('#word').textContent", "当前单词")
    ev("document.querySelector('#modal').hidden", "弹窗 hidden")
    ev("[...document.querySelector('#acts').children].map(b=>b.dataset.a).join(',')", "按钮列表")

    print("\n=== 点击「认识」 ===")
    ev("document.querySelector('[data-a=know]').click()", "点击结果")
    time.sleep(0.6)
    ev("document.querySelector('#mean').hidden", "翻面后 mean.hidden")
    ev("document.querySelector('#mean').textContent.slice(0,40)", "翻面后释义")

    print("\n=== 点击「记住了，下一个」 ===")
    ev("document.querySelector('[data-a=next]').click()", "点击结果")
    time.sleep(1.2)
    ev("document.querySelector('#word').textContent", "下一个单词")
    ev("document.querySelector('#drillCount').textContent", "进度")

    print("\n=== 打开改释义弹窗并保存 ===")
    ev("document.querySelector('#modal').hidden=true; openModal({w:'test',m:'测试',tip:''})", "打开弹窗")
    ev("document.querySelector('#modal').hidden", "弹窗 hidden")
    ev("$('#mSave').onclick ? 'onclick 已绑定' : '没绑定'", "保存按钮")
    ev("document.querySelector('#mSave').click()", "点保存")
    time.sleep(1.2)
    ev("document.querySelector('#modal').hidden", "保存后弹窗 hidden")

    ws.cmd(999, "Browser.close", wait=False) if False else None
    print("\n完成")


if __name__ == "__main__":
    main()
