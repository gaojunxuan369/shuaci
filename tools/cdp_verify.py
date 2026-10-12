# -*- coding: utf-8 -*-
"""改完之后再验证一遍：弹窗平时不挡路，用的时候能正常开合。"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from cdp_probe import WS  # noqa: E402

DEBUG = "http://127.0.0.1:9222"


def main():
    targets = json.loads(urllib.request.urlopen(DEBUG + "/json/list", timeout=5).read())
    page = [t for t in targets if t["type"] == "page"][0]
    ws = WS(page["webSocketDebuggerUrl"])
    ws.cmd(1, "Runtime.enable")
    ws.cmd(2, "Page.navigate", {"url": "http://127.0.0.1:8756/?v=2"})
    time.sleep(3)

    def ev(expr, label):
        r = ws.cmd(hash(expr) % 9999 + 100, "Runtime.evaluate",
                   {"expression": expr, "returnByValue": True, "awaitPromise": True})
        v = r["result"]["result"].get("value")
        print("%-44s => %s" % (label, v))
        return v

    bad = 0
    print("=== 1. 默认状态不该挡路 ===")
    if ev("getComputedStyle($('#modal')).display", "modal display（应为 none）") != "none":
        bad += 1
    hit = ev("(()=>{const e=document.elementFromPoint(540,300);return e?e.tagName+'#'+e.id:'null'})()",
             "屏幕中心被谁接住")
    if "mSave" in str(hit) or "mInput" in str(hit):
        bad += 1

    print("\n=== 2. 点「认识」应该能翻面 ===")
    ev("$('[data-a=know]').click()", "点认识")
    time.sleep(0.5)
    if ev("$('#mean').hidden", "翻面后 mean.hidden（应为 false）") is not False:
        bad += 1
    ev("$('#mean').textContent.slice(0,30)", "看到的意思")

    print("\n=== 3. 空格过词 ===")
    before = ev("$('#word').textContent", "当前词")
    ev("""document.dispatchEvent(new KeyboardEvent('keydown',{key:' '}))""", "按空格")
    time.sleep(1.0)
    after = ev("$('#word').textContent", "下一个词")
    if before == after:
        bad += 1

    print("\n=== 4. E 键开弹窗，再取消 ===")
    ev("""document.dispatchEvent(new KeyboardEvent('keydown',{key:'e'}))""", "按 E")
    time.sleep(0.4)
    if ev("getComputedStyle($('#modal')).display", "弹窗 display（应为 flex）") != "flex":
        bad += 1
    if ev("getComputedStyle($('#modal')).display", "再次确认") != "flex":
        bad += 1
    ev("$('#mWord').textContent", "弹窗里的词")
    ev("$('#mCancel').click()", "点取消")
    time.sleep(0.3)
    if ev("getComputedStyle($('#modal')).display", "取消后（应为 none）") != "none":
        bad += 1
    hit2 = ev("(()=>{const e=document.elementFromPoint(540,300);return e?e.tagName+'#'+e.id:'null'})()",
              "取消后屏幕中心")
    if "mSave" in str(hit2):
        bad += 1

    print("\n=== 5. 改释义并保存 ===")
    ev("""document.dispatchEvent(new KeyboardEvent('keydown',{key:'e'}))""", "再按 E")
    time.sleep(0.3)
    ev("$('#mInput').value='测试释义'; $('#mInput2').value='测试提示'", "填内容")
    ev("$('#mSave').click()", "点保存")
    time.sleep(1.2)
    if ev("getComputedStyle($('#modal')).display", "保存后（应为 none）") != "none":
        bad += 1

    print("\n=== 6. 切到其它标签页 ===")
    for tab, name in [("fav", "收藏"), ("all", "词表"), ("src", "词表来源"), ("drill", "刷词")]:
        ev("switchView('%s')" % tab, "切到" + name)
        time.sleep(0.5)
    ev("document.querySelectorAll('.view.on').length", "同时显示的视图数（应为 1）")

    print("\n" + ("全部通过" if bad == 0 else "有 %d 项没通过" % bad))


if __name__ == "__main__":
    main()
