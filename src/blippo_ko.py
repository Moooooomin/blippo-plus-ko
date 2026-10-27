#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blippo+ 한글 패치 도구 (blippo-ko)

게임에 내장된 로컬라이제이션 시스템의 KOREAN(=10) 슬롯에 번역문을 주입한다.
영상/오디오는 건드리지 않고 텍스트 번들만 수정한다.

    python blippo_ko.py status
    python blippo_ko.py extract -o ko.json --tsv ko.tsv
    python blippo_ko.py apply   -i ko.json
    python blippo_ko.py restore

의존성: UnityPy  (pip install UnityPy)
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import time

try:                                    # 윈도우 cp949 콘솔에서 한글 깨짐 방지
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import UnityPy
except ImportError:
    sys.exit("UnityPy가 필요합니다:  pip install UnityPy")

UNITY_VERSION = "6000.0.62f1"
UnityPy.config.FALLBACK_UNITY_VERSION = UNITY_VERSION

# 번들 헤더에 버전이 비어 있어 매번 폴백 경고가 뜬다. 의도된 동작이므로 끈다.
try:
    import warnings
    from UnityPy.exceptions import UnityVersionFallbackWarning
    warnings.simplefilter("ignore", UnityVersionFallbackWarning)
except Exception:
    pass

KOREAN_ID = 10
LANG_NAMES = {
    0: "en-US", 1: "ja", 2: "fr", 3: "es-419", 4: "de", 5: "nl",
    6: "pt-BR", 7: "it", 8: "zh-CN", 9: "zh-TW", 10: "ko",
    11: "ru", 12: "en-GB", 13: "fr-CA", 14: "es-ES", 15: "pt",
}
# 참고 번역으로 함께 뽑아줄 언어 (실제로 100% 채워져 있는 것들)
REF_LANGS = (8, 14, 6)

# 언어 선택 메뉴의 버튼은 프리팹에 고정 배치되어 있고 한국어 버튼은 없다.
# 그래서 이미 메뉴에 있는 언어의 "자리"를 빌려 한국어를 넣는다(--slot).
# 각 언어의 표시 이름을 담은 .string 에셋 이름.
LANG_NAME_ASSETS = {
    0: "American English", 1: "Japanese", 2: "French", 3: "Spanish",
    4: "German", 5: "Dutch", 6: "Brazilian Portuguese", 7: "Italian",
    8: "Chinese (Simplified)", 9: "Chinese (Traditional)", 10: "Korean",
    11: "Russian", 12: "British English", 13: "Canadian French",
    14: "European Spanish", 15: "Portuguese",
}
KOREAN_LABEL = "한국어"

# 메뉴/HUD가 실제로 읽는 UI 문자열은 번들이 아니라 이 파일의 사본이다.
# 타입트리가 없어서 metadata 번들의 정의를 빌려 파싱한다.
SHARED_ASSETS = ("sharedassets0.assets", "sharedassets1.assets")

TEXT_BUNDLE = "metadata_assets_all.bundle"
PG_BUNDLE = "programguide_assets_all.bundle"
FONT_BUNDLES = (TEXT_BUNDLE, PG_BUNDLE)
META_CAB = "CAB-bc0f0ef9368035f84965003945707ddb"   # Unifont가 들어있는 CAB

GAME_FOLDER = "Blippo+"


def app_dir():
    """패처가 놓인 폴더.

    PyInstaller 로 묶으면 __file__ 은 임시 해제 폴더를 가리키므로,
    exe 로 실행 중일 때는 exe 가 있는 폴더를 쓴다.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

FORMAT_VERSION = 1


# --------------------------------------------------------------- 경로/공통

class Paths:
    def __init__(self, game):
        self.game = os.path.abspath(game)
        self.data = os.path.join(self.game, "Blippo+_Data")
        self.aa = os.path.join(self.data, "StreamingAssets", "aa")
        self.bundles = os.path.join(self.aa, "StandaloneWindows64")
        self.catalog = os.path.join(self.aa, "catalog.json")

    def bundle(self, name):
        return os.path.join(self.bundles, name)

    def check(self):
        if not os.path.isdir(self.bundles):
            sys.exit("게임 경로가 올바르지 않습니다: %s\n  --game 으로 직접 지정하세요." % self.game)


def steam_root():
    """Steam 설치 폴더. 레지스트리를 먼저 보고, 없으면 흔한 위치를 본다."""
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg is not None:
        keys = ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"))
        for hive, key, name in keys:
            try:
                with winreg.OpenKey(hive, key) as k:
                    v = winreg.QueryValueEx(k, name)[0]
                if v and os.path.isdir(v):
                    return os.path.normpath(v)
            except OSError:
                continue
    for cand in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam",
                 os.path.expanduser("~/.steam/steam"),
                 os.path.expanduser("~/Library/Application Support/Steam")):
        if os.path.isdir(cand):
            return cand
    return None


def steam_libraries():
    """libraryfolders.vdf 를 읽어 모든 Steam 라이브러리 경로를 모은다."""
    root = steam_root()
    libs = []
    if not root:
        return libs
    libs.append(root)
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            text = ""
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            path = m.group(1).replace("\\\\", "\\")
            if os.path.isdir(path):
                libs.append(os.path.normpath(path))
    # 중복 제거 (대소문자 무시)
    out, seen = [], set()
    for p in libs:
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def find_game(explicit):
    if explicit:
        p = Paths(explicit)
        p.check()
        return p

    tried = []
    # 1) 패처 바로 옆 (게임 폴더 안이나 그 형제 폴더에 두고 실행하는 경우)
    here = app_dir()
    for cand in (here, os.path.join(here, GAME_FOLDER),
                 os.path.join(os.path.dirname(here), GAME_FOLDER)):
        tried.append(cand)
        p = Paths(cand)
        if os.path.isdir(p.bundles):
            return p

    # 2) Steam 라이브러리 전체
    for lib in steam_libraries():
        cand = os.path.join(lib, "steamapps", "common", GAME_FOLDER)
        tried.append(cand)
        p = Paths(cand)
        if os.path.isdir(p.bundles):
            return p

    print("Blippo+ 설치 폴더를 찾지 못했습니다. 다음 위치를 확인했습니다:")
    for t in tried[:8]:
        print("   %s" % t)
    print("\nSteam 라이브러리에서 Blippo+ > 관리 > 로컬 파일 보기 로 경로를 확인한 뒤,")
    print("그 경로를 아래처럼 지정하세요:")
    print('   %s --game "<경로>" ...' % os.path.basename(sys.argv[0]))
    sys.exit(1)


def sha1(path, limit=1 << 22):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(limit))
    return h.hexdigest()[:16]


def human(n):
    return "%.1fMB" % (n / 1048576)


# ----------------------------------------------- 번역 단위 탐색 (핵심 로직)

def is_lang_dict(lst):
    """언어ID -> 문자열 사전인지 판별. 다른 UnityDictionary와 구분한다."""
    if not isinstance(lst, list) or not lst:
        return False
    for e in lst:
        if not isinstance(e, dict) or "key" not in e or "value" not in e:
            return False
        if not isinstance(e["key"], int) or not (0 <= e["key"] <= 15):
            return False
        if not isinstance(e["value"], str):
            return False
    return any(e["key"] == 0 for e in lst)


def iter_units(node, path=""):
    """typetree를 순회하며 (경로, 언어사전 list)를 내놓는다."""
    if isinstance(node, dict):
        if is_lang_dict(node.get("list")):
            yield path, node["list"]
            return
        for k, v in node.items():
            if k in ("m_GameObject", "m_Script"):
                continue
            yield from iter_units(v, (path + "." + k) if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_units(v, "%s[%d]" % (path, i))


def get_lang(lst, lang_id):
    for e in lst:
        if e.get("key") == lang_id:
            return e.get("value")
    return None


def set_lang(lst, lang_id, text):
    """언어 항목을 삽입/갱신하고 key 오름차순을 유지한다."""
    for e in lst:
        if e.get("key") == lang_id:
            if e.get("value") == text:
                return False
            e["value"] = text
            return True
    lst.append({"key": lang_id, "value": text, "duplicatedKey": 0})
    lst.sort(key=lambda e: e["key"])
    return True


def collect_units(tt):
    """하나의 typetree에서 (이름, 경로, list) 목록을 뽑는다."""
    name = str(tt.get("m_Name", ""))
    return [(name, path, lst) for path, lst in iter_units(tt)]


# --------------------------------------------------------------- 백업 관리

def dest_for(label, paths):
    """백업 라벨 -> 게임 폴더 안의 실제 위치."""
    if label in FONT_BUNDLES:
        return paths.bundle(label)
    if label == "catalog.json":
        return paths.catalog
    if label in SHARED_ASSETS:
        return os.path.join(paths.data, label)
    return None


# GUI 가 진행률을 받아 가는 자리. hook(label, n, total) — total 은 None 일 수 있다.
PROGRESS_HOOK = None


class Progress:
    """오래 걸리는 루프의 진행 상황을 한 줄로 갱신해 보여준다.
    출력이 파이프로 넘어가는 경우(터미널이 아닌 경우)에는 조용히 있는다."""

    def __init__(self, label, total=None):
        self.label = label
        self.total = total
        self.n = 0
        self.t0 = time.time()
        self.last = 0.0
        self.hook_last = 0.0
        # 창 모드 exe 에서는 sys.stdout 이 None 이다
        self.live = bool(getattr(sys.stdout, "isatty", lambda: False)())
        if not self.live:
            print("      %s ..." % label, flush=True)
        if PROGRESS_HOOK:
            PROGRESS_HOOK(label, 0, total)

    def step(self, n=1):
        self.n += n
        now = time.time()
        if PROGRESS_HOOK and now - self.hook_last >= 0.1:
            self.hook_last = now
            PROGRESS_HOOK(self.label, self.n, self.total)
        if not self.live:
            return
        if now - self.last < 0.3:
            return
        self.last = now
        if self.total:
            pct = 100.0 * self.n / self.total
            bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
            msg = "      %s [%s] %5.1f%%  %s/%s" % (
                self.label, bar, pct, format(self.n, ","), format(self.total, ","))
        else:
            msg = "      %s  %s개 처리" % (self.label, format(self.n, ","))
        sys.stdout.write("\r" + msg.ljust(78))
        sys.stdout.flush()

    def done(self, note=""):
        if PROGRESS_HOOK:
            PROGRESS_HOOK(self.label, self.total or self.n, self.total or self.n)
        secs = time.time() - self.t0
        msg = "      %s 완료 (%s개, %.1f초)%s" % (
            self.label, format(self.n, ","), secs, (" " + note) if note else "")
        if self.live:
            sys.stdout.write("\r" + msg.ljust(78) + "\n")
            sys.stdout.flush()
        else:
            print(msg, flush=True)


def say(msg):
    """긴 작업 직전에 '멈춘 게 아니다'를 알리는 한 줄."""
    print(msg, end="", flush=True)


def said(note=""):
    print(note, flush=True)


def looks_patched(paths, trans):
    """게임 파일에 이미 한국어가 들어가 있는가.

    새 폴더에서 설치 프로그램을 돌리면 backup 이 비어 있다. 그때 게임이 이미 패치된
    상태라면, 패치된 파일을 '원본'으로 백업해 버려 되돌리기가 망가진다.
    원본 게임에는 한국어가 언어 이름("한국어")밖에 없으므로, 메뉴 번역문이 여럿
    보이면 패치된 것으로 본다. (sharedassets1 은 압축되지 않아 바이트로 찾을 수 있다)
    """
    fp = os.path.join(paths.data, "sharedassets1.assets")
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except OSError:
        return False
    # 언어 이름처럼 원문 그대로 둔 번역은 원본에도 있으니, 한글 두 글자 이상 든 것만 쓴다
    probes = [t for (a, _), t in trans.items()
              if a.endswith(".string") and len(t) >= 4 and re.search("[가-힣]{2}", t)][:40]
    return sum(1 for t in probes if t.encode("utf-8") in data) >= 3


class Backup:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.manifest = os.path.join(self.root, "manifest.json")
        self.refuse_new = False     # 이미 패치된 파일을 원본으로 착각해 저장하지 않는다
        self.refused = []

    def load_manifest(self):
        if os.path.isfile(self.manifest):
            with open(self.manifest, encoding="utf-8") as f:
                return json.load(f)
        return {"tool": "blippo-ko", "files": {}}

    def save(self, label, src):
        """최초 1회만 백업한다 (이미 있으면 덮어쓰지 않음)."""
        os.makedirs(self.root, exist_ok=True)
        dst = os.path.join(self.root, label)
        if os.path.exists(dst):
            return False
        if self.refuse_new:
            self.refused.append(label)
            return False
        shutil.copy2(src, dst)
        m = self.load_manifest()
        m["files"][label] = {
            "original_path": src,
            "size": os.path.getsize(src),
            "sha1": sha1(src),
            "saved": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.manifest, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        return True

    def original_size(self, label):
        return self.load_manifest()["files"].get(label, {}).get("size")

    def restore_all(self, paths):
        """백업을 되돌린다. 목적지는 manifest에 적힌 절대경로가 아니라
        지금 감지된 게임 경로에서 다시 계산한다 (다른 PC에서도 동작하도록)."""
        m = self.load_manifest()
        n = 0
        for label, info in m["files"].items():
            src = os.path.join(self.root, label)
            if not os.path.isfile(src):
                print("  ! 백업 파일 누락: %s" % label)
                continue
            dst = dest_for(label, paths)
            if dst is None:
                print("  ! 목적지를 알 수 없어 건너뜀: %s" % label)
                continue
            if not os.path.isdir(os.path.dirname(dst)):
                print("  ! 게임 폴더에 없는 위치라 건너뜀: %s" % dst)
                continue
            # 제자리 쓰기 — Windows에서 파일 핸들이 잡혀 있어도 대체로 통과한다
            mode = "r+b" if os.path.exists(dst) else "wb"
            with open(src, "rb") as fsrc, open(dst, mode) as fdst:
                shutil.copyfileobj(fsrc, fdst, 8 << 20)
                fdst.truncate()
            print("  복구: %-38s %s" % (label, human(info["size"])))
            n += 1
        return n


# ----------------------------------------------------------- catalog CRC

def patch_catalog_crc(catalog_path, bundle_size):
    """
    catalog.json의 AssetBundleRequestOptions에서 대상 번들의 m_Crc를 0으로 만든다.
    base64 블롭 안 UTF-16 JSON을 '0'+공백으로 덮어써 바이트 길이를 그대로 보존한다.
    (로컬 번들은 LoadFromFileAsync로 로드되어 CRC를 타지 않지만 안전장치로 둔다.)
    """
    with open(catalog_path, encoding="utf-8") as f:
        cat = json.load(f)
    raw = base64.b64decode(cat["m_ExtraDataString"])
    blob = bytearray(raw)
    marker = ('"m_BundleSize":%d' % bundle_size).encode("utf-16-le")
    i = blob.find(marker)
    if i < 0:
        return "대상 번들 옵션을 찾지 못함 (건너뜀)"
    start = blob.rfind('{"m_Hash"'.encode("utf-16-le"), 0, i)
    end = blob.find("}".encode("utf-16-le"), i) + 2
    seg = bytes(blob[start:end])
    m = re.search(rb'("\x00m\x00_\x00C\x00r\x00c\x00"\x00:\x00)((?:[0-9 ]\x00)+)', seg)
    if not m:
        return "m_Crc 필드를 찾지 못함 (건너뜀)"
    old = m.group(2).decode("utf-16-le")
    if old.strip() == "0":
        return "이미 0 (변경 없음)"
    new = ("0" + " " * (len(old) - 1)).encode("utf-16-le")
    if len(new) != len(m.group(2)):
        return "길이 보존 실패 (건너뜀)"
    blob[start + m.start(2):start + m.end(2)] = new
    json.loads(bytes(blob[start:end]).decode("utf-16-le"))   # 유효성 확인
    cat["m_ExtraDataString"] = base64.b64encode(bytes(blob)).decode()
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, separators=(",", ":"))
    return "m_Crc %s -> 0" % old.strip()


# ------------------------------------------------------------- 폰트 폴백

def borrow_nodesets(paths):
    """metadata 번들에서 종류별 타입트리 정의를 빌려온다.

    빌드된 .assets 파일에는 타입트리가 없어서 MonoBehaviour 필드를 읽을 수 없다.
    같은 C# 타입이 애드레서블 번들에도 들어 있으므로 그 정의를 그대로 재사용한다.
    """
    env = UnityPy.load(paths.bundle(TEXT_BUNDLE))
    out = {}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        ext = tt.get("assetExtension")
        if isinstance(ext, str) and ext not in out:
            out[ext] = o.serialized_type.node
    return out


def _script_ptr(raw):  # 현재 미사용 (진단용으로 남겨둠)
    """타입트리 없이 MonoBehaviour 헤더에서 m_Script 포인터만 꺼낸다."""
    if len(raw) < 24:
        return None
    return (struct.unpack_from("<i", raw, 16)[0],
            struct.unpack_from("<q", raw, 20)[0])


def _raw_name(raw):
    """타입트리 없이 MonoBehaviour의 m_Name을 읽는다.

    레이아웃: m_GameObject(12) + m_Enabled&패딩(4) + m_Script(12) + m_Name(길이접두 UTF-8)
    이라 이름 길이는 오프셋 28에 있다. 빌드가 달라질 때를 대비해 인접 값도 시도한다.
    """
    for off in (28, 24, 32, 20):
        if len(raw) < off + 4:
            continue
        n = struct.unpack_from("<i", raw, off)[0]
        if not (0 < n <= 512) or len(raw) < off + 4 + n:
            continue
        try:
            s = raw[off + 4:off + 4 + n].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if s.isprintable():
            return s
    return None


def _ext_of(name):
    if name and "." in name:
        return "." + name.rsplit(".", 1)[1]
    return None


def iter_assets_objects(env, nodesets, stats=None, on_visit=None):
    """.assets 파일의 MonoBehaviour를 에셋 이름의 확장자로 타입트리를 골라 읽는다.

    예전에는 스크립트 포인터로 묶은 뒤 '그룹의 첫 오브젝트' 하나로만 타입트리를
    탐침했다. 그 하나가 실패하면 그룹 전체가 조용히 버려졌고, 실제로 .episode
    404개가 통째로 패치에서 빠졌다. 이제는 오브젝트마다 확장자로 정의를 직접
    고르고, 고르지 못한 것은 stats에 남겨 눈에 보이게 한다.
    on_visit: MonoBehaviour 하나를 볼 때마다 불린다 (진행률 표시용).
    """
    if stats is None:
        stats = {}
    ok = stats.setdefault("matched", collections.Counter())
    ng = stats.setdefault("unmatched", collections.Counter())
    # 스크립트 타입별로 "어떤 nodeset이 맞는지"를 기억한다.
    # 같은 타입을 오브젝트마다 다시 탐침하면 .assets 하나가 몇 분씩 걸린다.
    cache = {}

    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        if on_visit:
            on_visit()
        try:
            raw = o.get_raw_data()
        except Exception:
            ng["(원시데이터 실패)"] += 1
            continue

        name = _raw_name(raw)
        ext = _ext_of(name)
        tt = nd = None

        cand = nodesets.get(ext) if ext else None
        if cand is not None:
            try:
                probe = o.read_typetree(cand)
            except Exception:
                probe = None
            if isinstance(probe, dict) and probe.get("m_Name") == name:
                tt, nd = probe, cand

        if nd is None:
            key = _script_ptr(raw)
            if key in cache:                      # 이미 판정난 타입
                cached = cache[key]
                if cached is None:
                    ng[ext or "(이름없음)"] += 1
                    continue
                try:
                    probe = o.read_typetree(cached)
                except Exception:
                    probe = None
                if isinstance(probe, dict) and probe.get("m_Name") == name:
                    tt, nd = probe, cached
            else:
                # 확장자로 못 고르면 전부 시도하되 m_Name이 일치해야 채택한다.
                # 로컬라이즈 유닛이 나오는 쪽을 우선한다.
                fallback = None
                for c in nodesets.values():
                    try:
                        probe = o.read_typetree(c)
                    except Exception:
                        continue
                    if not isinstance(probe, dict) or probe.get("m_Name") != name:
                        continue
                    if any(True for _ in collect_units(probe)):
                        tt, nd = probe, c
                        break
                    if fallback is None:
                        fallback = (probe, c)
                if nd is None and fallback is not None:
                    tt, nd = fallback
                cache[key] = nd

        if nd is None:
            ng[ext or "(이름없음)"] += 1
            continue
        ok[ext or "(확장자없음)"] += 1
        yield o, tt, nd


def patch_assets_file(path, nodesets, trans, slot, dry, backup, label_asset, stats=None):
    """빌드된 .assets 파일 안의 로컬라이즈 문자열에 한국어를 넣는다."""
    say("      %s 읽는 중 ..." % os.path.basename(path))
    env = UnityPy.load(path)
    said("")
    total = applied = aliased = relabeled = 0
    n_mb = sum(1 for o in env.objects if o.type.name == "MonoBehaviour")
    prog = Progress("  %s 패치" % os.path.basename(path), n_mb)
    for o, tt, nd in iter_assets_objects(env, nodesets, stats, on_visit=prog.step):
        total += 1
        name = str(tt.get("m_Name", ""))
        dirty = False
        if slot is not None and name == label_asset:
            for _, _, lst in collect_units(tt):
                for e in lst:
                    if e.get("value") != KOREAN_LABEL:
                        e["value"] = KOREAN_LABEL
                        dirty = True
                if set_lang(lst, KOREAN_ID, KOREAN_LABEL):
                    dirty = True
            relabeled += 1
        else:
            for _, upath, lst in collect_units(tt):
                txt = trans.get((name, upath))
                if txt and set_lang(lst, KOREAN_ID, txt):
                    dirty = True
                    applied += 1
                if slot is not None:
                    ko = get_lang(lst, KOREAN_ID)
                    if ko and set_lang(lst, slot, ko):
                        dirty = True
                        aliased += 1
        if dirty and not dry:
            o.save_typetree(tt, nd)
    prog.done()
    if not dry:
        backup.save(os.path.basename(path), path)
        say("      저장 중 ...")
        data = env.file.save()
        with open(path, "wb") as f:
            f.write(data)
        said(" %s" % human(len(data)))
    return total, applied, aliased, relabeled


def string_nodes(paths):
    """metadata 번들에서 LocalizedStringObject의 타입트리 정의를 빌려온다."""
    env = UnityPy.load(paths.bundle(TEXT_BUNDLE))
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        if str(tt.get("m_Name", "")).endswith(".string"):
            return o.serialized_type.node
    return None


def iter_shared_strings(env, nodes):
    """sharedassets1 안의 LocalizedStringObject 사본을 (obj, typetree)로 내놓는다."""
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree(nodes)
        except Exception:
            continue
        n = tt.get("m_Name")
        if isinstance(n, str) and n.endswith(".string"):
            yield o, tt


def patch_shared(paths, nodes, trans, slot, dry, backup):
    """메뉴가 실제로 읽는 UI 문자열 사본에 한국어를 넣는다."""
    spath = os.path.join(paths.data, SHARED_ASSETS)
    env = UnityPy.load(spath)
    label = (LANG_NAME_ASSETS.get(slot, "") + " (untranslated).string") if slot is not None else None
    applied = aliased = relabeled = total = 0
    for o, tt in iter_shared_strings(env, nodes):
        total += 1
        name = tt["m_Name"]
        lst = (tt.get("localizedString") or {}).get("list")
        if not isinstance(lst, list):
            continue
        dirty = False
        if slot is not None and name == label:
            for e in lst:
                if e.get("value") != KOREAN_LABEL:
                    e["value"] = KOREAN_LABEL
                    dirty = True
            relabeled += 1
        else:
            txt = trans.get((name, "localizedString"))
            if txt and set_lang(lst, KOREAN_ID, txt):
                dirty = True
                applied += 1
            if slot is not None:
                ko = get_lang(lst, KOREAN_ID)
                if ko and set_lang(lst, slot, ko):
                    dirty = True
                    aliased += 1
        if dirty and not dry:
            o.save_typetree(tt, nodes)
    if not dry:
        backup.save(SHARED_ASSETS, spath)
        data = env.file.save()
        with open(spath, "wb") as f:
            f.write(data)
    return total, applied, aliased, relabeled


def find_unifont(paths):
    env = UnityPy.load(paths.bundle(TEXT_BUNDLE))
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        if "m_AtlasPopulationMode" in tt and str(tt.get("m_Name")) == "Unifont":
            return o.path_id
    sys.exit("Unifont 폰트 에셋을 찾지 못했습니다.")


def meta_file_id(env):
    """이 번들에서 metadata CAB을 가리키는 m_FileID. 같은 번들이면 0, 없으면 -1."""
    for _, f in env.files.items():
        for cab_name, cf in (getattr(f, "files", {}) or {}).items():
            if META_CAB in cab_name:
                return 0
            for i, e in enumerate(getattr(cf, "externals", []) or []):
                if META_CAB in getattr(e, "path", ""):
                    return i + 1
    return -1


def scan_fonts(env, unifont_id):
    """(폴백 있음, 폴백 없음) 폰트 이름 목록."""
    fid = meta_file_id(env)
    ok, bad = [], []
    if fid < 0:
        return ok, bad, fid
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        if "m_AtlasPopulationMode" not in tt:
            continue
        name = str(tt.get("m_Name"))
        if name == "Unifont":
            continue
        fb = tt.get("m_FallbackFontAssetTable")
        if fb is None:
            continue
        if any(x.get("m_PathID") == unifont_id and x.get("m_FileID") == fid for x in fb):
            ok.append(name)
        else:
            bad.append(name)
    return ok, bad, fid


EPG_FONT_SIZE = 16.0          # Unifont 의 pointSize
EPG_FIX_SIZES = (12.0, 17.0)  # 한글이 들어가는 편성표 텍스트의 원래 크기


def fix_epg_font_sizes(env, dry):
    """편성표에서 한글 획이 끊기는 문제를 보정한다.

    Unifont 는 pointSize 16 이고, TMP 는 폴백 글리프를
        배율 = 컴포넌트 m_fontSize / 16
    으로 그린다. Unifont 는 16ppem 에서 획이 정확히 1px 로 떨어지는 글꼴이라
    배율이 1.0 이 아니면 1px 획이 리샘플링되며 사라진다.
        17px -> 1.0625   12px -> 0.75

    대상은 '이름이 Title 인 GameObject 에 붙은 TMP 텍스트' 중 크기가 12/17 인 것.
    - NowNextLater/Title : "현재 방송 / 다음 방송 / 이후 방송" 머리글 (12px)
    - Grid Item*/Title   : 편성표 칸의 프로그램 제목 (17px)
    채널 번호(Channel)와 호출부호(Call sign)는 한글이 들어가지 않아 건드리지 않는다.
    pathID 대신 이름으로 찾으므로 게임이 업데이트돼도 계속 동작한다.
    """
    objs = {o.path_id: o for o in env.objects}
    names = {}

    def go_name(pid):
        if pid not in names:
            o = objs.get(pid)
            try:
                names[pid] = str(o.read_typetree().get("m_Name", "")) if o else ""
            except Exception:
                names[pid] = ""
        return names[pid]

    changed = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        if not isinstance(d, dict) or "m_fontSize" not in d or "m_fontAsset" not in d:
            continue
        size = d.get("m_fontSize")
        if size not in EPG_FIX_SIZES:
            continue
        if go_name((d.get("m_GameObject") or {}).get("m_PathID")) != "Title":
            continue
        changed.append((size, o.path_id))
        if dry:
            continue
        d["m_fontSize"] = EPG_FONT_SIZE
        if d.get("m_fontSizeBase") in EPG_FIX_SIZES:
            d["m_fontSizeBase"] = EPG_FONT_SIZE
        o.save_typetree(d)
    return changed


def fix_fonts(env, unifont_id, dry):
    """Unifont 폴백이 없는 TMP 폰트에 폴백을 덧붙인다 (기존 폴백은 보존)."""
    fid = meta_file_id(env)
    if fid < 0:
        return []
    fixed = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        if "m_AtlasPopulationMode" not in tt:
            continue
        name = str(tt.get("m_Name"))
        if name == "Unifont":
            continue
        fb = tt.get("m_FallbackFontAssetTable")
        if fb is None:
            continue
        if any(x.get("m_PathID") == unifont_id and x.get("m_FileID") == fid for x in fb):
            continue
        fb.append({"m_FileID": fid, "m_PathID": unifont_id})
        if not dry:
            o.save_typetree(tt)
        fixed.append(name)
    return fixed


# --------------------------------------------------------------- TSV 입출력

def tsv_escape(s):
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "").replace("\n", "\\n")


def tsv_unescape(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\"}.get(c, "\\" + c))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


TSV_COLS = ("asset", "path", "category", "en", "ko")


def write_tsv(path, units):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(TSV_COLS) + "\n")
        for u in units:
            f.write("\t".join(tsv_escape(str(u.get(k, ""))) for k in TSV_COLS) + "\n")


def read_units(path):
    """번역 파일을 읽어 (units, meta) 반환. .json / .tsv 모두 지원."""
    if path.lower().endswith((".tsv", ".csv", ".txt")):
        units = []
        with open(path, encoding="utf-8-sig") as f:
            header = f.readline().rstrip("\r\n").split("\t")
            idx = {k: i for i, k in enumerate(header)}
            for key in ("asset", "path", "ko"):
                if key not in idx:
                    sys.exit("TSV에 '%s' 열이 없습니다." % key)
            for line in f:
                if not line.strip():
                    continue
                c = line.rstrip("\r\n").split("\t")
                if len(c) <= idx["ko"]:
                    continue
                units.append({
                    "asset": tsv_unescape(c[idx["asset"]]),
                    "path": tsv_unescape(c[idx["path"]]),
                    "ko": tsv_unescape(c[idx["ko"]]),
                })
        return units, {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, list):
        return doc, {}
    return doc.get("units", []), doc.get("_meta", {})


# ------------------------------------------------------------------ 명령어

def cmd_status(args):
    p = find_game(args.game)
    p.check()
    print("게임 경로  : %s" % p.game)
    print("Unity      : %s\n" % UNITY_VERSION)

    bpath = p.bundle(TEXT_BUNDLE)
    print("텍스트 번들: %s  (%s)" % (TEXT_BUNDLE, human(os.path.getsize(bpath))))

    env = UnityPy.load(bpath)
    total = ko = 0
    langs = {}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        for _, _, lst in collect_units(tt):
            total += 1
            for e in lst:
                langs[e["key"]] = langs.get(e["key"], 0) + 1
            if get_lang(lst, KOREAN_ID):
                ko += 1
    print("번역 단위  : %s개" % format(total, ","))
    print("한국어 수록: %s개  (%.1f%%)\n" % (format(ko, ","), ko / max(total, 1) * 100))
    print("언어별 수록 현황:")
    for k in sorted(langs):
        bar = "#" * int(langs[k] / max(total, 1) * 30)
        print("   %-7s %6s  %s" % (LANG_NAMES.get(k, k), format(langs[k], ","), bar))

    uni = find_unifont(p)
    print("\n폰트 폴백(Unifont) 상태:")
    for b in FONT_BUNDLES:
        e2 = UnityPy.load(p.bundle(b))
        okl, badl, _ = scan_fonts(e2, uni)
        print("   %-34s 적용 %2d / 미적용 %2d" % (b, len(okl), len(badl)))
        if badl:
            print("      미적용: %s%s" % (", ".join(badl[:5]), " ..." if len(badl) > 5 else ""))

    bk = Backup(args.backup_dir)
    m = bk.load_manifest()
    if m["files"]:
        print("\n백업: %d개 파일 @ %s" % (len(m["files"]), bk.root))
    else:
        print("\n백업: 없음 (아직 패치 전)")


def cmd_extract(args):
    p = find_game(args.game)
    p.check()
    bpath = p.bundle(TEXT_BUNDLE)
    print("추출 중: %s ..." % TEXT_BUNDLE)
    env = UnityPy.load(bpath)
    units = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        cat = tt.get("assetExtension") or ""
        for name, path, lst in collect_units(tt):
            en = get_lang(lst, 0)
            if en is None:
                continue
            u = {
                "asset": name,
                "path": path,
                "category": cat,
                "en": en,
                "ko": get_lang(lst, KOREAN_ID) or "",
            }
            if args.refs:
                for rl in REF_LANGS:
                    v = get_lang(lst, rl)
                    if v:
                        u["ref_" + LANG_NAMES[rl]] = v
            units.append(u)

    units.sort(key=lambda u: (u["category"], u["asset"], u["path"]))
    doc = {
        "_meta": {
            "tool": "blippo-ko",
            "format": FORMAT_VERSION,
            "language_id": KOREAN_ID,
            "language": "KOREAN",
            "generated": _dt.datetime.now().isoformat(timespec="seconds"),
            "source_bundle": TEXT_BUNDLE,
            "source_size": os.path.getsize(bpath),
            "source_sha1": sha1(bpath),
            "unit_count": len(units),
        },
        "units": units,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    words = sum(len(u["en"].split()) for u in units)
    chars = sum(len(u["en"]) for u in units)
    done = sum(1 for u in units if u["ko"].strip())
    print("  -> %s" % args.out)
    print("     번역 단위 %s개 / 영문 %s단어 %s글자"
          % (format(len(units), ","), format(words, ","), format(chars, ",")))
    print("     이미 한국어 있음: %d개" % done)
    if args.tsv:
        write_tsv(args.tsv, units)
        print("  -> %s  (스프레드시트용, 줄바꿈은 \\n 으로 이스케이프)" % args.tsv)

    by = {}
    for u in units:
        k = u["category"] or "(기타)"
        e = by.setdefault(k, [0, 0])
        e[0] += 1
        e[1] += len(u["en"].split())
    print("\n  분류별:")
    for k, (c, w) in sorted(by.items(), key=lambda x: -x[1][1]):
        print("     %-22s %6s단위  %7s단어" % (k, format(c, ","), format(w, ",")))


def cmd_apply(args):
    p = find_game(args.game)
    p.check()
    units, meta = read_units(args.input)
    trans = {}
    for u in units:
        ko = u.get("ko")
        if isinstance(ko, str) and ko.strip():
            trans[(u["asset"], u["path"])] = ko
    if not trans:
        sys.exit("번역문(ko)이 하나도 없습니다. 파일을 확인하세요.")

    print("번역 파일 : %s" % args.input)
    print("적용 대상 : %s개 (파일 내 전체 %s개)"
          % (format(len(trans), ","), format(len(units), ",")))

    bk = Backup(args.backup_dir)
    dry = args.dry_run
    bpath = p.bundle(TEXT_BUNDLE)

    if looks_patched(p, trans) and len(bk.load_manifest().get("files", {})) < 5:
        bk.refuse_new = True
        print("  ! 이미 한글 패치가 적용된 게임인데, 이 폴더에는 원본 백업이 없습니다.")
        print("    패치된 파일을 원본으로 잘못 저장하지 않도록 백업을 새로 만들지 않습니다.")
        print("    원래대로 되돌리려면 Steam '게임 파일 무결성 확인'을 쓰거나,")
        print("    처음 설치했던 폴더의 backup 폴더를 이 폴더로 옮기세요.")

    if meta.get("source_sha1") and sha1(bpath) != meta["source_sha1"]:
        print("  ! 주의: 번들이 추출 당시와 다릅니다. 이미 패치됐거나 게임이 업데이트된 상태일 수 있습니다.")

    if dry:
        print("\n[모의 실행] 파일을 쓰지 않습니다.")

    # --- 1) 한국어 주입 -------------------------------------------------
    if not dry and bk.save(TEXT_BUNDLE, bpath):
        print("\n백업 생성: %s" % os.path.join(bk.root, TEXT_BUNDLE))
    slot = args.slot
    print("\n[1/4] 한국어 주입 -> %s" % TEXT_BUNDLE)
    if slot is not None:
        print("      슬롯 대여: %s(id %d) 자리를 한국어로 대체"
              % (LANG_NAMES.get(slot, slot), slot))
    say("      번들 읽는 중 ...")
    env = UnityPy.load(bpath)
    all_objs = list(env.objects)
    said(" %s개 오브젝트" % format(len(all_objs), ","))
    applied = changed = aliased = relabeled = 0
    seen = set()
    label_targets = set()
    if slot is not None:
        base_name = LANG_NAME_ASSETS.get(slot, "")
        label_targets = {base_name + ".string", base_name + " (untranslated).string"}
    prog = Progress("한국어 주입", len(all_objs))
    for o in all_objs:
        prog.step()
        if o.type.name != "MonoBehaviour":
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        dirty = False
        nm = str(tt.get("m_Name", ""))
        is_label = nm in label_targets
        for name, path, lst in collect_units(tt):
            seen.add((name, path))
            txt = trans.get((name, path))
            if txt and set_lang(lst, KOREAN_ID, txt):
                dirty = True
                applied += 1
            if slot is None:
                continue
            if is_label:
                # 메뉴에 뜨는 언어 이름 자체를 "한국어"로 바꾼다.
                # (어떤 언어로 보고 있든 이 버튼은 한국어라고 읽혀야 한다)
                for e in lst:
                    if e.get("value") != KOREAN_LABEL:
                        e["value"] = KOREAN_LABEL
                        dirty = True
                if set_lang(lst, KOREAN_ID, KOREAN_LABEL):
                    dirty = True
                relabeled += 1
            else:
                ko = get_lang(lst, KOREAN_ID)
                if ko and set_lang(lst, slot, ko):
                    dirty = True
                    aliased += 1
        if dirty:
            changed += 1
            if not dry:
                o.save_typetree(tt)
    missing = [k for k in trans if k not in seen]
    print("      적용 %s개 / 에셋 %s개 수정" % (format(applied, ","), format(changed, ",")))
    if slot is not None:
        print("      슬롯 복제 %s개 / 언어 이름 변경 %d개"
              % (format(aliased, ","), relabeled))
    if missing:
        print("      ! 번들에 없는 항목 %d개는 무시됨 (예: %s)" % (len(missing), missing[0]))

    # --- 2) 폰트 폴백 ---------------------------------------------------
    print("\n[2/4] 폰트 폴백 보정")
    fixed_pg = []
    if args.no_font_fix:
        print("      건너뜀 (--no-font-fix)")
    else:
        uni = find_unifont(p)
        fixed_meta = fix_fonts(env, uni, dry)
        print("      %-34s %2d개 보정" % (TEXT_BUNDLE, len(fixed_meta)))
        if fixed_meta:
            print("         %s%s" % (", ".join(fixed_meta[:5]),
                                     " ..." if len(fixed_meta) > 5 else ""))

    if not dry:
        data = env.file.save(packer="original")
        with open(bpath, "wb") as f:
            f.write(data)
        print("\n      저장: %-34s %s" % (TEXT_BUNDLE, human(len(data))))

    if not args.no_font_fix:
        pg = p.bundle(PG_BUNDLE)
        say("      %s 읽는 중 ..." % PG_BUNDLE)
        env2 = UnityPy.load(pg)
        said("")
        fixed_pg = fix_fonts(env2, find_unifont(p), dry)
        print("      %-34s %2d개 보정" % (PG_BUNDLE, len(fixed_pg)))
        if fixed_pg:
            print("         %s" % ", ".join(fixed_pg[:5]))
        sized = fix_epg_font_sizes(env2, dry)
        print("      편성표 한글 글자 크기 %d개 -> %g (획 끊김 보정)"
              % (len(sized), EPG_FONT_SIZE))
        if sized:
            per = collections.Counter(s for s, _ in sized)
            print("         %s" % ", ".join("%g -> %g %d개" % (k, EPG_FONT_SIZE, v)
                                            for k, v in sorted(per.items())))
        if (fixed_pg or sized) and not dry:
            bk.save(PG_BUNDLE, pg)
            say("      저장 중 ...")
            d2 = env2.file.save(packer="original")
            with open(pg, "wb") as f:
                f.write(d2)
            said(" %-34s %s" % (PG_BUNDLE, human(len(d2))))

    # --- 3) 빌드에 복제된 본편 데이터 ------------------------------------
    print("\n[3/4] 게임 본체 데이터 (.assets 복제본)")
    nodesets = borrow_nodesets(p)
    label_asset = None
    if slot is not None:
        label_asset = LANG_NAME_ASSETS.get(slot, "") + " (untranslated).string"
    if not nodesets:
        print("      ! 타입트리 정의를 찾지 못해 건너뜀")
    else:
        for fn in SHARED_ASSETS:
            fp = os.path.join(p.data, fn)
            if not os.path.isfile(fp):
                continue
            stats = {}
            tot, ap, al, rl = patch_assets_file(fp, nodesets, trans, slot, dry, bk,
                                                label_asset, stats)
            print("      %-22s 에셋 %4d개 / 한국어 %4d개 / 슬롯 복제 %4d개%s"
                  % (fn, tot, ap, al, "  [언어 버튼명 변경]" if rl else ""))
            matched = stats.get("matched", {})
            if matched:
                print("         종류별: %s"
                      % ", ".join("%s %d" % (k, v)
                                  for k, v in sorted(matched.items())))
            missed = stats.get("unmatched", {})
            if missed:
                print("         ! 타입트리를 맞추지 못한 에셋 %d개: %s"
                      % (sum(missed.values()),
                         ", ".join("%s %d" % (k, v) for k, v in sorted(missed.items()))))

    # --- 4) catalog CRC -------------------------------------------------
    print("\n[4/4] catalog.json CRC 무력화")
    if args.no_crc_fix:
        print("      건너뜀 (--no-crc-fix)")
    elif dry:
        print("      (모의 실행)")
    else:
        bk.save("catalog.json", p.catalog)
        size = bk.original_size(TEXT_BUNDLE) or meta.get("source_size")
        if not size:
            print("      원본 크기를 알 수 없어 건너뜀")
        else:
            print("      %s" % patch_catalog_crc(p.catalog, size))

    if dry:
        print("\n모의 실행 완료.")
        return

    # --- 검증 -----------------------------------------------------------
    print("\n검증 중 ...")
    env3 = UnityPy.load(bpath)
    ok = 0
    objs3 = [o for o in env3.objects if o.type.name == "MonoBehaviour"]
    prog3 = Progress("재읽기", len(objs3))
    for o in objs3:
        prog3.step()
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        for name, path, lst in collect_units(tt):
            want = trans.get((name, path))
            if want is not None and get_lang(lst, KOREAN_ID) == want:
                ok += 1
    print("  재읽기 확인: %s / %s개 일치" % (format(ok, ","), format(len(trans), ",")))
    if ok < len(trans) - len(missing):
        print("  ! 일부 항목이 확인되지 않았습니다.")
    else:
        print("\n패치 완료. 게임 설정에서 한국어를 선택하세요.")
        if getattr(sys, "frozen", False):
            print("되돌리려면 설치 프로그램에서 '원본으로 되돌리기'를 누르세요.")
        else:
            print("되돌리기:  python %s restore" % os.path.basename(__file__))


def cmd_verify(args):
    """패치된 게임 파일을 실제로 읽어 한국어가 들어갔는지 확인한다.

    번들만 보면 안 된다. 게임은 .assets 복제본에서 읽기 때문에, 번들이 멀쩡해도
    .assets 가 빠지면 화면에는 원래 언어가 그대로 나온다 (.episode 404개가 그랬다).
    """
    p = find_game(args.game)
    p.check()
    units, _ = read_units(args.input)
    want = {}
    for u in units:
        ko = u.get("ko")
        if isinstance(ko, str) and ko.strip():
            want[(u["asset"], u["path"])] = ko
    print("게임 경로 : %s" % p.game)
    print("기준 번역 : %s (%s개)\n" % (args.input, format(len(want), ",")))

    slot = args.slot
    grand_bad = 0

    def check(label, pairs):
        """pairs: (asset, path, lst) 반복자"""
        nonlocal grand_bad
        seen = ko_ok = ko_bad = slot_bad = 0
        bad_ext = collections.Counter()
        sample = []
        for name, upath, lst in pairs:
            exp = want.get((name, upath))
            if exp is None:
                continue
            seen += 1
            got = get_lang(lst, KOREAN_ID)
            if got == exp:
                ko_ok += 1
            else:
                ko_bad += 1
                bad_ext[_ext_of(name) or "?"] += 1
                if len(sample) < 3:
                    sample.append((name, upath, (got or "")[:40]))
            if slot is not None and get_lang(lst, slot) != exp:
                slot_bad += 1
        print("  %-26s 대조 %5d개 / 한국어 OK %5d / 불일치 %4d / 슬롯 불일치 %4d"
              % (label, seen, ko_ok, ko_bad, slot_bad))
        if bad_ext:
            print("      불일치 종류: %s"
                  % ", ".join("%s %d" % (k, v) for k, v in sorted(bad_ext.items())))
            for nm, up, got in sample:
                print("      예: %s [%s] -> %r" % (nm, up, got))
        grand_bad += ko_bad + slot_bad

    say("  번들 읽는 중 ...")
    env = UnityPy.load(p.bundle(TEXT_BUNDLE))
    said("")

    def bundle_pairs():
        for o in env.objects:
            if o.type.name != "MonoBehaviour":
                continue
            try:
                tt = o.read_typetree()
            except Exception:
                continue
            for t in collect_units(tt):
                yield t

    check(TEXT_BUNDLE, bundle_pairs())

    nodesets = borrow_nodesets(p)
    for fn in SHARED_ASSETS:
        fp = os.path.join(p.data, fn)
        if not os.path.isfile(fp):
            continue
        say("  %s 읽는 중 ..." % fn)
        env2 = UnityPy.load(fp)
        said("")
        stats = {}

        n_mb = sum(1 for o in env2.objects if o.type.name == "MonoBehaviour")
        prog = Progress("  %s 대조" % fn, n_mb)

        def assets_pairs():
            for o, tt, nd in iter_assets_objects(env2, nodesets, stats, on_visit=prog.step):
                name = str(tt.get("m_Name", ""))
                for _, upath, lst in collect_units(tt):
                    yield name, upath, lst

        check(fn, assets_pairs())
        missed = stats.get("unmatched", {})
        if missed:
            print("      (타입트리 미매칭 %d개: %s)"
                  % (sum(missed.values()),
                     ", ".join("%s %d" % (k, v) for k, v in sorted(missed.items()))))

    print()
    if grand_bad:
        print("! 불일치 %s건. 패치가 덜 적용됐습니다." % format(grand_bad, ","))
        sys.exit(1)
    print("이상 없음. 모든 파일에서 한국어가 확인되었습니다.")


def cmd_restore(args):
    p = find_game(args.game)
    p.check()
    bk = Backup(args.backup_dir)
    m = bk.load_manifest()
    if not m["files"]:
        sys.exit("백업이 없습니다: %s\n  (패치를 한 번도 적용하지 않았다면 복구할 것도 없습니다)"
                 % bk.root)
    print("게임 경로: %s" % p.game)
    print("백업에서 복구: %s" % bk.root)
    n = bk.restore_all(p)
    print("\n%d개 파일 복구 완료." % n)


BANNER = r"""
==========================================================
   Blippo+ 한글 패치
==========================================================
"""


def interactive():
    """exe 를 더블클릭했을 때의 메뉴. 창이 바로 닫히지 않게 끝에서 멈춘다."""
    print(BANNER)
    trans = os.path.join(app_dir(), "blippo_ko.json")
    if not os.path.isfile(trans):
        print("  번역 파일을 찾을 수 없습니다:")
        print("    %s" % trans)
        print("\n  압축을 풀 때 blippo_ko.json 이 이 프로그램과")
        print("  같은 폴더에 있어야 합니다.")
        input("\n  Enter 키를 누르면 종료합니다...")
        return 1

    print("   1) 한글 패치 설치")
    print("   2) 원본으로 되돌리기")
    print("   3) 설치 상태 확인")
    print("   0) 종료")
    try:
        choice = input("\n   번호를 입력하고 Enter: ").strip()
    except EOFError:
        choice = "0"

    ns = argparse.Namespace(game=None, backup_dir=os.path.join(app_dir(), "backup"),
                            input=trans, slot=14, dry_run=False,
                            no_font_fix=False, no_crc_fix=False)
    code = 0
    try:
        if choice == "1":
            print("\n  게임이 실행 중이면 먼저 종료하세요.")
            print("  10~20분 정도 걸립니다. 창을 닫지 마세요.\n")
            cmd_apply(ns)
        elif choice == "2":
            cmd_restore(ns)
        elif choice == "3":
            cmd_verify(ns)
        elif choice == "0":
            return 0
        else:
            print("\n  1, 2, 3, 0 중에서 고르세요.")
            code = 2
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except Exception as e:
        code = 1
        print("\n  오류가 발생했습니다: %s: %s" % (type(e).__name__, e))
        print("  게임이 실행 중이거나, 게임 파일이 손상됐을 수 있습니다.")
    input("\n  Enter 키를 누르면 종료합니다...")
    return code


def main():
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        sys.exit(interactive())

    ap = argparse.ArgumentParser(description="Blippo+ 한글 패치 도구")
    ap.add_argument("--game", help="게임 설치 경로 (미지정 시 자동 탐지)")
    ap.add_argument("--backup-dir", default=os.path.join(app_dir(), "backup"),
                    help="백업 폴더")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="현재 상태 점검")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("extract", help="번역 템플릿 추출")
    s.add_argument("-o", "--out", default="blippo_ko.json")
    s.add_argument("--tsv", help="스프레드시트용 TSV도 함께 출력")
    s.add_argument("--no-refs", dest="refs", action="store_false",
                   help="참고 번역(zh-CN/es-ES/pt-BR) 제외")
    s.set_defaults(func=cmd_extract, refs=True)

    s = sub.add_parser("apply", help="한국어 주입")
    s.add_argument("-i", "--input", required=True, help="번역 파일 (.json 또는 .tsv)")
    s.add_argument("--slot", type=int, metavar="ID",
                   help="한국어를 이 언어 슬롯에도 복제하고 메뉴 이름을 '한국어'로 바꾼다. "
                        "(메뉴에 실제로 있는 언어: 6=포르투갈(BR), 8=중국어 간체, 14=스페인(유럽))")
    s.add_argument("--no-font-fix", action="store_true", help="폰트 폴백 보정 생략")
    s.add_argument("--no-crc-fix", action="store_true", help="catalog CRC 수정 생략")
    s.add_argument("--dry-run", action="store_true", help="쓰지 않고 시뮬레이션")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("verify", help="패치된 파일에 한국어가 실제로 들어갔는지 확인")
    s.add_argument("-i", "--input", default="blippo_ko.json", help="기준 번역 파일")
    s.add_argument("--slot", type=int, metavar="ID",
                   help="이 슬롯에도 한국어가 복제됐는지 함께 확인")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("restore", help="원본 복구")
    s.set_defaults(func=cmd_restore)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
