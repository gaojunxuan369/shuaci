# -*- coding: utf-8 -*-
"""把「生词_整理_*.md」表格里的释义灌进 data/dict.json，作为初始释义库。
以后在网页里改过的释义不会被覆盖（同名且已有释义时跳过）。
用法： python tools/init_dict.py [整理表路径]
"""
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT_F = os.path.join(BASE, "data", "dict.json")
DESK = os.path.join(os.path.expanduser("~"), "Desktop")

sys.path.insert(0, BASE)
from server import parse_md, load_json, save_json  # noqa: E402

paths = sys.argv[1:] or sorted(glob.glob(os.path.join(DESK, "生词_整理*.md")))
if not paths:
    print("没找到整理表，把路径当参数传进来：python tools/init_dict.py 生词_整理_20261008.md")
    sys.exit(1)

vocab = load_json(DICT_F, {})
added = 0
for p in paths:
    with open(p, "r", encoding="utf-8") as f:
        items = parse_md(f.read(), os.path.basename(p))
    for it in items:
        if not it["meaning"]:
            continue
        if it["w"] in vocab and vocab[it["w"]].get("m"):
            continue
        vocab[it["w"]] = {"m": it["meaning"], "tip": it["tip"], "src": "整理表"}
        added += 1
    print("读入 %s：%d 词" % (os.path.basename(p), len(items)))

save_json(DICT_F, vocab)
print("释义库现有 %d 词，本次新增 %d 词 -> %s" % (len(vocab), added, DICT_F))
