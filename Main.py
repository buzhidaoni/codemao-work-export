# -*- coding: utf-8 -*-
import json
import base64
import urllib.request
import uuid
import sys
import traceback
import random
import re
from xml.sax.saxutils import escape


def fetch_json(url, tag=""):
    print("  GET JSON %s%s" % (tag, url[:100]))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    print("  OK %s (%d keys)" % (tag, len(data) if isinstance(data, dict) else 0))
    return data


def fetch_bytes(url, tag=""):
    print("  GET BYTES %s%s" % (tag, url[:100]))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    print("  OK %s (%d bytes)" % (tag, len(data)))
    return data


def guess_mime(d):
    if d[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if d[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if d[:4] == b"GIF8": return "image/gif"
    if d[:5] == b"<?xml" or d[:4] == b"<svg": return "image/svg+xml"
    if d[:3] == b"ID3" or d[:2] == b"\xff\xfb" or d[:2] == b"\xff\xf3": return "audio/mpeg"
    if d[:4] == b"RIFF": return "audio/wav"
    return "application/octet-stream"


def to_data_uri(d):
    mime = guess_mime(d)
    print("    MIME=%s size=%d" % (mime, len(d)))
    return "data:%s;base64,%s" % (mime, base64.b64encode(d).decode())


def rid():
    a = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choice(a) for _ in range(20))


def sanitize_filename(name, max_total=240, ext="", suffix=""):
    illegal = '\\/:*?"<>|'
    original = name
    for ch in illegal:
        name = name.replace(ch, " ")
    name = name.strip()
    if not name:
        name = "unnamed"
    fixed = len(original) - len(name) + (original.count(illegal[0]))
    reserved = 1 + len(ext) + len(suffix)
    max_name = max_total - reserved
    if max_name < 1:
        max_name = 1
    if len(name) > max_name:
        print("  [文件名] 名称过长 %d > %d，截断" % (len(name), max_name))
        name = name[:max_name]
    if name != original:
        print("  [文件名] 原名 %r -> 新名 %r" % (original, name))
    return name


SHADOW_ALL_TYPES = {
    "math_number", "controller_shadow", "text", "logic_empty",
    "lists_get", "broadcast_input", "get_audios", "get_whole_audios",
    "get_current_costume", "default_value", "get_current_scene",
    "get_sensing_current_scene",
}

SHADOW_FIELD_ATTRS = {
    "math_number": {"name": "NUM", "constraints": "-Infinity,Infinity,0,", "allow_text": "true"},
    "controller_shadow": {"name": "NUM", "constraints": "-Infinity,Infinity,0,false"},
    "text": {"name": "TEXT"},
    "lists_get": {"name": "VAR"},
    "broadcast_input": {"name": "MESSAGE"},
    "get_audios": {"name": "sound_id"},
    "get_whole_audios": {"name": "sound_id"},
    "get_current_costume": {"name": "style_id"},
    "default_value": {"name": "TEXT", "has_been_edited": "false"},
    "get_current_scene": {"name": "scene"},
    "get_sensing_current_scene": {"name": "scene"},
}

SHADOW_DEFAULTS = {
    "math_number": "0", "controller_shadow": "0", "text": "",
    "lists_get": "?", "broadcast_input": "Hi", "get_audios": "?",
    "get_whole_audios": "all", "get_current_costume": "",
    "default_value": "0", "get_current_scene": "",
    "get_sensing_current_scene": "",
}


def cs(t, bid=None, text=None):
    if t == "logic_empty":
        return '<empty xmlns="http://www.w3.org/1999/xhtml" type="logic_empty" id="%s" visible="visible" editable="false"></empty>' % (bid or rid())
    if bid is None:
        bid = rid()
    if text is None:
        text = SHADOW_DEFAULTS.get(t, "")
    attrs = SHADOW_FIELD_ATTRS.get(t, {})
    a = " ".join('%s="%s"' % (k, v) for k, v in attrs.items())
    return '<shadow xmlns="http://www.w3.org/1999/xhtml" type="%s" id="%s" visible="visible"><field %s>%s</field></shadow>' % (t, bid, a, escape(str(text)))


def collect_ref(node, out):
    if not isinstance(node, dict):
        return
    nb = node.get("next_block")
    if isinstance(nb, dict) and nb.get("id"):
        out.add(nb["id"])
        collect_ref(nb, out)
    cb = node.get("child_block")
    if isinstance(cb, list):
        for s in cb:
            if isinstance(s, dict) and s.get("id"):
                out.add(s["id"])
                collect_ref(s, out)
    conds = node.get("conditions")
    if isinstance(conds, list):
        for s in conds:
            if isinstance(s, dict) and s.get("id"):
                out.add(s["id"])
                collect_ref(s, out)
    for v in (node.get("params") or {}).values():
        if isinstance(v, dict) and v.get("id"):
            out.add(v["id"])
            collect_ref(v, out)
        elif isinstance(v, list):
            for s in v:
                if isinstance(s, dict) and s.get("id"):
                    out.add(s["id"])
                    collect_ref(s, out)


class BlockDecompiler:
    def __init__(self, compiled, actor):
        self.compiled = compiled
        self.actor = actor
        self.block = {}
        self.connection = {}
        self.shadows = {}
        self.fields = {}

    def start(self):
        bid = self.compiled.get("id")
        if bid and bid in self.actor.done_blocks:
            return self.actor.blocks.get(bid)
        self.info()
        if self.id:
            self.actor.done_blocks.add(self.id)
        self.nexts()
        self.children()
        self.conditions()
        self.params()
        return self.block

    def info(self):
        self.id = self.block["id"] = self.compiled["id"]
        self.kind = self.compiled.get("kind")
        self.type = self.block["type"] = self.compiled["type"]
        self.block["location"] = [0, 0]
        self.block["is_shadow"] = self.type in SHADOW_ALL_TYPES
        self.block["collapsed"] = False
        self.block["disabled"] = False
        self.block["deletable"] = True
        self.block["movable"] = True
        self.block["editable"] = True
        self.block["visible"] = "visible"
        self.block["shadows"] = self.shadows
        self.block["fields"] = self.fields
        self.block["field_constraints"] = {}
        self.block["field_extra_attr"] = {}
        self.block["comment"] = None
        self.block["mutation"] = ""
        self.block["is_output"] = (
            self.type in SHADOW_ALL_TYPES
            or self.type in {"logic_boolean", "procedures_2_stable_parameter"}
        )
        self.block["parent_id"] = None
        self.actor.connections[self.id] = self.connection
        self.actor.blocks[self.id] = self.block

    def nexts(self):
        nb = self.compiled.get("next_block")
        if not isinstance(nb, dict) or not nb.get("id"):
            return
        n = get_bd(nb, self.actor).start()
        if n:
            n["parent_id"] = self.id
            self.connection[n["id"]] = {"type": "next"}

    def children(self):
        cb = self.compiled.get("child_block")
        if not isinstance(cb, list):
            return
        for i in range(len(cb)):
            if cb[i] is None:
                continue
            c = get_bd(cb[i], self.actor).start()
            if not c:
                continue
            c["parent_id"] = self.id
            name = self.getChildInputName(i)
            self.connection[c["id"]] = {"type": "input", "input_type": "statement", "input_name": name}
            self.shadows[name] = ""

    def getChildInputName(self, count):
        return "DO"

    def conditions(self):
        conds = self.compiled.get("conditions")
        if not isinstance(conds, list):
            return
        for i in range(len(conds)):
            c = get_bd(conds[i], self.actor).start()
            if not c:
                continue
            c["parent_id"] = self.id
            name = "IF%d" % i
            if c["type"] != "logic_empty":
                self.connection[c["id"]] = {"type": "input", "input_type": "value", "input_name": name}
            self.shadows[name] = cs("logic_empty", c["id"])

    def params(self):
        params = self.compiled.get("params") or {}
        for name, value in params.items():
            if isinstance(value, dict):
                p = get_bd(value, self.actor).start()
                if not p:
                    continue
                p["parent_id"] = self.id
                pt = p["type"]
                pf = p.get("fields") or {}
                if pt in SHADOW_ALL_TYPES:
                    if pt == "logic_empty":
                        self.shadows[name] = cs("logic_empty", p["id"])
                    elif pf:
                        fv = next(iter(pf.values()))
                        self.shadows[name] = cs(pt, p["id"], fv)
                    else:
                        self.shadows[name] = cs(pt, p["id"])
                else:
                    st = "logic_empty" if name in {"condition", "BOOL"} else "math_number"
                    self.shadows[name] = cs(st)
                self.connection[p["id"]] = {"type": "input", "input_type": "value", "input_name": name}
            else:
                self.fields[name] = value


class ControlsIfDecompiler(BlockDecompiler):
    def start(self):
        b = super().start()
        cb = self.compiled.get("child_block") or []
        nc = len(self.compiled.get("conditions") or [])
        has_else = len(cb) == nc + 1 and cb[-1] is not None
        has_slot = len(cb) == nc + 1
        if nc <= 1 and not has_else:
            self.shadows["EXTRA_ADD_ELSE"] = ""
        else:
            attrs = []
            if nc > 1:
                attrs.append('elseif="%d"' % (nc - 1))
            if has_else or (has_slot and cb[-1] is None):
                attrs.append('else="1"')
            if attrs:
                self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" ' + " ".join(attrs) + '></mutation>'
            self.shadows["ELSE_TEXT"] = ""
        return b

    def getChildInputName(self, count):
        nc = len(self.compiled.get("conditions") or [])
        if count < nc:
            return "DO%d" % count
        return "ELSE"


class AskDecompiler(BlockDecompiler):
    def start(self):
        b = super().start()
        n = len(self.compiled.get("params") or {}) - 1
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" items="%d"></mutation>' % n
        return b


class TextJoinDecompiler(BlockDecompiler):
    def start(self):
        b = super().start()
        n = len(self.compiled.get("params") or {})
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" items="%d"></mutation>' % n
        return b


class TextSelectDecompiler(BlockDecompiler):
    def start(self):
        b = super().start()
        n = len(self.compiled.get("params") or {}) - 1
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" items="%d"></mutation>' % n
        return b


class ProcDefDecompiler(BlockDecompiler):
    def start(self):
        bid = self.compiled.get("id")
        if bid and bid in self.actor.done_blocks:
            return self.actor.blocks.get(bid)
        self.info()
        if self.id:
            self.actor.done_blocks.add(self.id)
        self.children()
        self.shadows["PROCEDURES_2_DEFNORETURN_DEFINE"] = ""
        self.shadows["PROCEDURES_2_DEFNORETURN_MUTATOR"] = ""
        self.fields["NAME"] = self.compiled.get("procedure_name", "")
        args = []
        c = 0
        for name in (self.compiled.get("params") or {}):
            iname = "PARAMS%d" % c
            args.append('<arg name="%s"></arg>' % iname)
            self.shadows[iname] = cs("math_number")
            pb = get_bd({
                "id": rid(),
                "kind": "domain_block",
                "type": "procedures_2_stable_parameter",
                "params": {"param_name": name, "param_default_value": ""},
            }, self.actor).start()
            if pb:
                pb["parent_id"] = self.block["id"]
                self.connection[pb["id"]] = {"type": "input", "input_type": "value", "input_name": iname}
            c += 1
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml">' + "".join(args) + '</mutation>'
        return self.block

    def getChildInputName(self, count):
        return "STACK"


class ProcRetDecompiler(BlockDecompiler):
    def start(self):
        b = super().start()
        self.shadows["PROCEDURES_2_DEFRETURN_RETURN"] = ""
        self.shadows["PROCEDURES_2_DEFRETURN_RETURN_MUTATOR"] = ""
        n = len(self.compiled.get("params") or {})
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" items="%d"></mutation>' % n
        return b


class ProcCallDecompiler(BlockDecompiler):
    def start(self):
        bid = self.compiled.get("id")
        if bid and bid in self.actor.done_blocks:
            return self.actor.blocks.get(bid)
        self.info()
        if self.id:
            self.actor.done_blocks.add(self.id)
        self.nexts()
        name = self.compiled.get("procedure_name", "")
        try:
            fid = self.actor.work.functions[name]["id"]
        except (KeyError, TypeError):
            fid = rid()
            self.block["disabled"] = True
        self.shadows["NAME"] = ""
        self.fields["NAME"] = name
        xml = []
        c = 0
        for pname, value in (self.compiled.get("params") or {}).items():
            pb = get_bd(value, self.actor).start()
            if pb:
                self.shadows["ARG%d" % c] = cs("default_value", pb["id"])
                xml.append('<procedures_2_parameter_shadow name="%s" value="0"></procedures_2_parameter_shadow>' % pname)
                self.connection[pb["id"]] = {"type": "input", "input_type": "value", "input_name": "ARG%d" % c}
            c += 1
        self.block["mutation"] = '<mutation xmlns="http://www.w3.org/1999/xhtml" name="%s" def_id="%s">%s</mutation>' % (name, fid, "".join(xml))
        return self.block


SPECIAL = {
    "controls_if": ControlsIfDecompiler,
    "controls_if_no_else": ControlsIfDecompiler,
    "ask_and_choose": AskDecompiler,
    "text_join": TextJoinDecompiler,
    "text_select_changeable": TextSelectDecompiler,
    "procedures_2_defnoreturn": ProcDefDecompiler,
    "procedures_2_return_value": ProcRetDecompiler,
    "procedures_2_callnoreturn": ProcCallDecompiler,
    "procedures_2_callreturn": ProcCallDecompiler,
}


def get_bd(compiled, actor):
    if not isinstance(compiled, dict) or not compiled.get("id"):
        return None
    t = compiled.get("type")
    if t in SPECIAL:
        return SPECIAL[t](compiled, actor)
    return BlockDecompiler(compiled, actor)


class ActorDecompiler:
    def __init__(self, work, actor, compiled, kind="actor"):
        self.work = work
        self.actor = actor
        self.compiled = compiled
        self.kind = kind
        self.blocks = {}
        self.connections = {}
        self.done_blocks = set()

    def prepare(self):
        self.actor["block_data_json"] = {"blocks": self.blocks, "connections": self.connections, "comments": {}}

    def start(self):
        print("  [%s] %s 开始反编译" % (self.kind, self.actor.get("name", self.actor.get("id", "?"))[:30]))
        procs = self.compiled.get("procedures") or {}
        print("  [%s] 函数数: %d" % (self.kind, len(procs)))
        for name, cf in procs.items():
            print("    [%s] 函数 %r" % (self.kind, name))
            self.work.functions[name] = ProcDefDecompiler(cf, self).start()

        cbm = self.compiled.get("compiled_block_map") or {}
        print("  [%s] compiled_block_map: %d" % (self.kind, len(cbm)))
        refs = set()
        for _bid, bn in cbm.items():
            collect_ref(bn, refs)
        print("  [%s] 被引用 id: %d" % (self.kind, len(refs)))

        roots = 0
        for bid, bn in cbm.items():
            if bid in refs:
                continue
            roots += 1
            d = get_bd(bn, self)
            if d:
                d.start()
        print("  [%s] root 积木: %d" % (self.kind, roots))

        orphans = 0
        for bid, bn in cbm.items():
            if bid in self.done_blocks:
                continue
            orphans += 1
            d = get_bd(bn, self)
            if d:
                d.start()
        if orphans:
            print("  [%s] WARN 孤儿积木: %d" % (self.kind, orphans))

        types = {}
        for b in self.blocks.values():
            types[b["type"]] = types.get(b["type"], 0) + 1
        roots_final = sum(1 for b in self.blocks.values() if b.get("parent_id") is None)
        print("  [%s] 结果: blocks=%d conns=%d roots=%d" % (self.kind, len(self.blocks), len(self.connections), roots_final))
        print("  [%s] 类型统计: %s" % (self.kind, json.dumps(types, ensure_ascii=False)))


class KittenWorkDecompiler:
    def __init__(self, work_info, work):
        self.work_info = work_info
        self.work = work
        self.functions = {}

    def start(self):
        ds = []
        for ac in self.work.get("compile_result", []):
            aid = ac.get("id")
            actor = self.get_actor(aid)
            if actor is None:
                print("  WARN: 找不到 %s" % aid)
                continue
            kind = "scene" if aid in self.work.get("theatre", {}).get("scenes", {}) else "actor"
            ds.append(ActorDecompiler(self, actor, ac, kind))
        print("  compile_result 条目: %d" % len(ds))
        for d in ds:
            d.prepare()
        for d in ds:
            d.start()
        self.work.pop("compile_result", None)
        self.work.pop("preview", None)
        self.work.pop("author_nickname", None)
        self.work["hidden_toolbox"] = {"toolbox": [], "blocks": []}
        self.work["work_source_label"] = 0
        self.work["sample_id"] = ""
        self.work["project_name"] = self.work_info["name"]
        self.work["toolbox_order"] = self.work["last_toolbox_order"] = [
            "event", "control", "action", "appearance", "audio", "pen", "sensing",
            "operator", "data", "data", "procedure", "mobile_control", "physic",
            "physics2", "cloud_variable", "cloud_list", "advanced", "ai_lab",
            "ai_game", "cognitive", "camera", "video", "wood", "arduino", "weeemake",
            "microbit", "ai", "midimusic",
        ]
        return self.work

    def get_actor(self, aid):
        t = self.work.get("theatre", {})
        if aid in t.get("actors", {}):
            return t["actors"][aid]
        if aid in t.get("scenes", {}):
            return t["scenes"][aid]
        return None


def main():
    print("=" * 60)
    print("编程猫社区作品反编译")
    print("基于 https://github.com/S-LIGHTNING/Kitten-4-Decompiler")
    print("=" * 60)
    wid = input("作品 ID: ").strip()
    print("[1/6] 获取作品信息...")
    info = fetch_json("https://api.codemao.cn/creation-tools/v1/works/" + wid, tag="work-info")
    name = info["work_name"]
    wt = info["type"]
    print("  名称: %s" % name)
    print("  类型: %s" % wt)
    print("  作者: %s" % info["user_info"]["nickname"])

    ext_map = {"KITTEN4": "bcm4", "KITTEN3": "bcm", "KITTEN2": "bcm", "COCO": "json"}
    ext = ext_map.get(wt, "bcm4")
    print("  扩展名: .%s" % ext)

    print("[2/6] 获取编译文件 URL...")
    if wt == "COCO":
        m = fetch_json("https://api-creation.codemao.cn/coconut/web/work/" + wid + "/load", tag="coco-meta")
        src = m["data"]["bcmc_url"]
    else:
        m = fetch_json("https://api-creation.codemao.cn/kitten/r2/work/player/load/" + wid, tag="kitten-meta")
        src = m["source_urls"][0]
    print("  src: %s" % src[:100])

    print("[3/6] 获取工程 JSON...")
    project = fetch_json(src, tag="project")
    theatre = project.setdefault("theatre", {})
    print("  顶层 keys: %s" % list(project.keys()))
    print("  theatre keys: %s" % list(theatre.keys()))
    print("  顶层 styles: %s" % list(project.get("styles", {}).keys()))
    print("  theatre.styles: %s" % list(theatre.get("styles", {}).keys()))
    print("  audio: %s" % list(project.get("audio", {}).keys()))
    print("  scenes: %s" % list(theatre.get("scenes", {}).keys()))
    print("  actors: %s" % list(theatre.get("actors", {}).keys()))

    print("[4/6] 内嵌素材...")
    sc = 0
    for sid, s in theatre.get("styles", {}).items():
        u = s.get("cdn_url") or s.get("url")
        print("  style %s url=%s" % (sid[:8], str(u)[:80]))
        if u and not u.startswith("data:"):
            try:
                s["url"] = to_data_uri(fetch_bytes(u, tag="style"))
                sc += 1
            except Exception as e:
                print("  WARN style %s 失败: %s" % (sid[:8], e))
    print("  styles 完成: %d" % sc)

    ac = 0
    for aid, a in project.get("audio", {}).items():
        u = a.get("cdn_url") or a.get("url")
        print("  audio %s url=%s" % (aid[:8], str(u)[:80]))
        if u and not u.startswith("data:"):
            try:
                a["url"] = to_data_uri(fetch_bytes(u, tag="audio"))
                ac += 1
            except Exception as e:
                print("  WARN audio %s 失败: %s" % (aid[:8], e))
    print("  audio 完成: %d" % ac)

    print("[5/6] 反编译积木...")
    if wt == "COCO":
        out = project
        print("  COCO 类型，跳过积木反编译")
    else:
        out = KittenWorkDecompiler({"name": name}, project).start()
        for aid, a in {**theatre.get("scenes", {}), **theatre.get("actors", {})}.items():
            p = a.get("block_data_json")
            if p:
                print("  %s: blocks=%d conns=%d" % (aid[:8], len(p["blocks"]), len(p["connections"])))

    print("[6/6] 保存文件...")
    safe_name = sanitize_filename(name, max_total=240, ext=ext, suffix="_" + wid)
    fn = "%s_%s.%s" % (safe_name, wid, ext)
    print("  文件名: %s (长度=%d)" % (fn, len(fn)))
    print("  保存路径: %s" % fn)
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("  完成。")
    print("=" * 60)
    input("按回车键退出。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        input("按回车键退出。")