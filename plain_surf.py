#!/usr/bin/env python3
"""
plain_surf.py v4.1 — 座標だけから出すプレーン波予測(人間の評価・スコアなし)

v2: うねりの来る方位に沿って沖を遡ってサンプリングし、
    モデルが計算済みの減衰(遮蔽込み)を「透過率」として表示する。
v3: 配信アダプタ (Slack Webhook / LINE broadcast / HTML)
v4: 8エリア27ポイント + リング15/40/90/150km + --areaフィルタ
v4.1: 実データ対応の堅牢化。欠測null・取得失敗をポイント単位で隔離し、
      1ポイントの失敗で全体が落ちない構造に変更。
v4.2: HTMLをライトテーマのカード型UIに刷新。波高の体感換算
      (スネ/ヒザ/モモ/コシ/ハラ/ムネ/カタ/アタマ)を全チャネルに追加。
      ※体感換算は単位換算でありプレーン原則(評価を入れない)に反しない。
v4.3: 「伝搬 沖→岸」ミニバーを追加。150→90→40→15km→岸のうねり高を
      並べ、経路上の遮蔽・減衰(段差が落ちる形)を視覚化。透過率%を統合。

使い方: python3 plain_surf.py                     # 明日・全27ポイント・stdoutのみ
        python3 plain_surf.py --today             # 今日
        python3 plain_surf.py --area 京丹後        # エリア/ポイント名で絞り込み(部分一致)
        python3 plain_surf.py --html docs/index.html
        実行ごとに plain_surf_log.csv へ透過率を追記(方向別の伝達関数の実測用)
依存: 標準ライブラリのみ
"""
import csv
import json
import math
import os
import sys
import time
import urllib.request
from datetime import date, timedelta

# ---- 設定 ----
# 座標・向きは surfers-ocean.com「関西サーフポイント58」の記載値。
# facing はビーチ正面(海側)の方位(度)。swell はサイト記載の反応うねり(参考コメント、計算には未使用)
SPOTS = [
    # 和歌山
    {"area": "和歌山", "name": "磯の浦",     "lat": 34.25724, "lon": 135.09289, "facing": 202},  # swell: SW-S 台風/春秋
    {"area": "和歌山", "name": "浜の宮",     "lat": 34.16546, "lon": 135.18152, "facing": 247},  # swell: SW-S 磯の浦クローズ時
    # 志摩
    {"area": "志摩",   "name": "国府",       "lat": 34.33097, "lon": 136.87960, "facing": 90},   # swell: E-S 小波でも反応良
    {"area": "志摩",   "name": "市後",       "lat": 34.30457, "lon": 136.88869, "facing": 90},   # swell: E-S 胸〜頭サイズから
    {"area": "志摩",   "name": "南張",       "lat": 34.30349, "lon": 136.72149, "facing": 180},  # swell: SW-SE 頭オーバー要・リーフ
    # 那智勝浦
    {"area": "那智勝浦", "name": "下里",     "lat": 33.57467, "lon": 135.92765, "facing": 135},  # swell: E-SW 東うねりに敏感
    {"area": "那智勝浦", "name": "那智",     "lat": 33.64336, "lon": 135.93925, "facing": 90},   # swell: NE-S リーフ
    # 伊良湖
    {"area": "伊良湖", "name": "伊古部",     "lat": 34.65560, "lon": 137.39210, "facing": 157},  # swell: E-SW
    {"area": "伊良湖", "name": "ロングビーチ", "lat": 34.61310, "lon": 137.21920, "facing": 157},  # swell: E-SW 安定
    {"area": "伊良湖", "name": "全日本",     "lat": 34.60210, "lon": 137.18520, "facing": 157},  # swell: E-SW
    {"area": "伊良湖", "name": "先端",       "lat": 34.58320, "lon": 137.01670, "facing": 270},  # swell: SW-S 西向きリーフ・上級者
    # 静岡
    {"area": "静岡",   "name": "潮見",       "lat": 34.67633, "lon": 137.52142, "facing": 180},  # swell: E-SW
    {"area": "静岡",   "name": "舞阪",       "lat": 34.67365, "lon": 137.60272, "facing": 180},  # swell: E-SW
    {"area": "静岡",   "name": "天竜川",     "lat": 34.64716, "lon": 137.78515, "facing": 180},  # swell: E-W 幅広
    {"area": "静岡",   "name": "御前崎",     "lat": 34.59746, "lon": 138.20566, "facing": 180},  # swell: E-W 幅広
    # 徳島北
    {"area": "徳島北", "name": "鳴門",       "lat": 34.21252, "lon": 134.63083, "facing": 112},  # swell: S-SE 外海クローズ時
    {"area": "徳島北", "name": "小松海岸",   "lat": 34.09139, "lon": 134.60723, "facing": 112},  # swell: S-SE
    # 室戸
    {"area": "室戸",   "name": "内妻",       "lat": 33.65925, "lon": 134.40289, "facing": 180},  # swell: S 東うねりジャンク時の逃げ場
    {"area": "室戸",   "name": "宍喰",       "lat": 33.56376, "lon": 134.31006, "facing": 135},  # swell: S-SE
    {"area": "室戸",   "name": "生見",       "lat": 33.52754, "lon": 134.28384, "facing": 112},  # swell: S-E 年間通して波あり
    {"area": "室戸",   "name": "尾崎",       "lat": 33.36831, "lon": 134.20659, "facing": 112},  # swell: S-E リーフ・ローカルオンリー区域
    # 京丹後 (日本海・冬)
    {"area": "京丹後", "name": "八丁浜",     "lat": 35.69203, "lon": 135.02696, "facing": 315},  # swell: W-NE 地形良・頭オーバー可
    {"area": "京丹後", "name": "琴引浜",     "lat": 35.70369, "lon": 135.05027, "facing": 315},  # swell: W-NE 小波拾える
    {"area": "京丹後", "name": "平",         "lat": 35.75669, "lon": 135.16284, "facing": 315},  # swell: W-NE 風の影響大
    {"area": "京丹後", "name": "浜詰",       "lat": 35.66431, "lon": 134.96348, "facing": 315},  # swell: W-NE 夕日ヶ浦
    {"area": "京丹後", "name": "葛野浜",     "lat": 35.64690, "lon": 134.92065, "facing": 0},    # swell: W-NE 西うねり反応良
    {"area": "京丹後", "name": "小天橋",     "lat": 35.64694, "lon": 134.90498, "facing": 22},   # swell: NW-NE 遠浅・小波向き
]

RINGS_KM = [15, 40, 90, 150]  # うねり方位に沿って遡る距離(外側2つは外洋の生値の把握用)
HOURS = [5, 7, 9, 11, 13, 15, 17]
LOG_FILE = "plain_surf_log.csv"

MARINE_VARS = ("wave_height,wave_direction,wave_period,"
               "swell_wave_height,swell_wave_direction,swell_wave_period,"
               "wind_wave_height")
MARINE_URL = ("https://marine-api.open-meteo.com/v1/marine"
              "?latitude={lat}&longitude={lon}&hourly=" + MARINE_VARS +
              "&timezone=Asia%2FTokyo&forecast_days=3")
WIND_URL = ("https://api.open-meteo.com/v1/jma"
            "?latitude={lat}&longitude={lon}"
            "&hourly=wind_speed_10m,wind_direction_10m"
            "&wind_speed_unit=ms&timezone=Asia%2FTokyo&forecast_days=3")

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

# 体感波高スケール(単位換算)。(上限m, ラベル, 背景色, 文字色)
SIZE_BINS = [
    (0.15, "フラット",     "#eef3f7", "#7b8b98"),
    (0.30, "スネ",         "#e6f3fc", "#28618c"),
    (0.40, "ヒザ",         "#d5eafa", "#235a83"),
    (0.60, "モモ",         "#bfdff7", "#1d4f75"),
    (0.80, "コシ",         "#a4d2f3", "#174463"),
    (1.00, "ハラ",         "#83c1ee", "#113750"),
    (1.20, "ムネ",         "#5fade8", "#0c2c42"),
    (1.40, "カタ",         "#3d97dd", "#ffffff"),
    (1.60, "アタマ",       "#2381c9", "#ffffff"),
    (None, "アタマオーバー", "#1268ac", "#ffffff"),
]


def size_label(m):
    """波高(m)→(体感ラベル, 背景色, 文字色)"""
    if m is None:
        return ("--", "#eef2f5", "#98a4ae")
    for th, label, bg, fg in SIZE_BINS:
        if th is None or m < th:
            return (label, bg, fg)


def fetch(url, retries=2):
    """JSON取得。失敗はリトライし、最終的にNoneを返す(呼び出し側で欠測扱い)"""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
            if isinstance(data, dict) and "hourly" in data:
                return data
            return None  # エラーJSON等
        except Exception:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    return None


def fmt(v, spec, suffix=""):
    """None安全なフォーマット。実データは欠測nullを含む"""
    return "--" if v is None else format(v, spec) + suffix


def compass(deg):
    if deg is None:
        return "--"
    return COMPASS[int((deg + 11.25) % 360 / 22.5)]


def angle_diff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def wind_label(wind_from, facing):
    if wind_from is None:
        return "--"
    d = angle_diff(wind_from, (facing + 180) % 360)
    return "オフ" if d <= 45 else ("オン" if d >= 135 else "サイド")


def forward_point(lat, lon, bearing_deg, dist_km):
    """lat/lonからbearing方向へdist_km進んだ点(球面近似)"""
    R = 6371.0
    br = math.radians(bearing_deg)
    la1 = math.radians(lat)
    lo1 = math.radians(lon)
    ad = dist_km / R
    la2 = math.asin(math.sin(la1) * math.cos(ad) +
                    math.cos(la1) * math.sin(ad) * math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br) * math.sin(ad) * math.cos(la1),
                           math.cos(ad) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def hour_index(data, target, hour):
    if not data:
        return None
    t = f"{target}T{hour:02d}:00"
    times = data["hourly"].get("time", [])
    return times.index(t) if t in times else None


def hv(data, key, idx):
    """hourly値のNone安全な取り出し"""
    if data is None or idx is None:
        return None
    arr = data["hourly"].get(key)
    return arr[idx] if arr and idx < len(arr) else None


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def build_report(spot, target):
    beach = fetch(MARINE_URL.format(lat=spot["lat"], lon=spot["lon"]))
    wind = fetch(WIND_URL.format(lat=spot["lat"], lon=spot["lon"]))
    head = f"◆ {spot['area']}/{spot['name']}  {target}"
    if beach is None:
        line = head + "  [海況データ取得失敗]"
        return line, line, [], {"spot": spot, "error": "海況データ取得失敗"}

    # その日のうねり方位の中央値 → 遡る方向を決める
    idxs = [hour_index(beach, target, h) for h in HOURS]
    up_bearing = median([hv(beach, "swell_wave_direction", i) for i in idxs])

    rings = []
    if up_bearing is not None:
        for dist in RINGS_KM:
            rla, rlo = forward_point(spot["lat"], spot["lon"], up_bearing, dist)
            rings.append({"dist": dist, "data": fetch(
                MARINE_URL.format(lat=f"{rla:.4f}", lon=f"{rlo:.4f}"))})

    lines = [
        head + "  [プレーン予測: モデル値のみ・評価なし]",
        f"  岸格子: {beach['latitude']:.3f},{beach['longitude']:.3f}"
        + (f"  / うねり主方位 {compass(up_bearing)}({up_bearing:.0f}°)に沿って沖を遡り"
           if up_bearing is not None else "  / うねりデータ欠測"),
        "  時刻   有義波高  周期    うねり(岸格子)        "
        + "".join(f"{d}km沖    " for d in RINGS_KM) + "透過率   風",
    ]
    log_rows = []
    data_rows = []
    compact = [f"◆{spot['area']}/{spot['name']} {target[5:]} うねり主方位{compass(up_bearing)}"]
    for h in HOURS:
        i = hour_index(beach, target, h)
        if i is None:
            continue
        hs = hv(beach, "wave_height", i)
        size = size_label(hs)
        sw_h = hv(beach, "swell_wave_height", i)
        sw_t = hv(beach, "swell_wave_period", i)
        sw_d = hv(beach, "swell_wave_direction", i)

        ring_cells = []
        path_vals = []  # (距離km, うねり高) 遮蔽の視覚化用
        outer_h = None
        outer_t = None
        outer_dist = None
        for ring in rings:
            j = hour_index(ring["data"], target, h)
            rh = hv(ring["data"], "swell_wave_height", j)
            rt = hv(ring["data"], "swell_wave_period", j)
            if rh is not None:
                outer_h, outer_t, outer_dist = rh, rt, ring["dist"]  # 値のある最遠リングを採用
            path_vals.append((ring["dist"], rh))
            ring_cells.append(f"{fmt(rh, '.2f')}m/{fmt(rt, '.0f')}s"
                              if rh is not None else "--")

        ratio = None
        if outer_h is not None and outer_h > 0.05 and sw_h is not None:
            ratio = sw_h / outer_h

        wj = hour_index(wind, target, h)
        wd = hv(wind, "wind_direction_10m", wj)
        ws = hv(wind, "wind_speed_10m", wj)
        wind_s = (f"{compass(wd)} {ws:.1f}m/s ({wind_label(wd, spot['facing'])})"
                  if (wd is not None and ws is not None) else "--")

        lines.append(
            f"  {h:02d}:00  {fmt(hs, '.2f', 'm')}({size[0]})  "
            f"{fmt(hv(beach, 'wave_period', i), '.1f', 's')}   "
            f"{fmt(sw_h, '.2f', 'm')}/{fmt(sw_t, '.1f', 's')} "
            f"{compass(sw_d)}({fmt(sw_d, '.0f', '°')})  "
            + "".join(f"{c:<10}" for c in ring_cells)
            + (f"{ratio*100:3.0f}%" if ratio is not None else " --")
            + f"    {wind_s}"
        )
        compact.append(
            f"{h:02d}時 {size[0]}{fmt(hs, '.2f')}m"
            f" うねり{fmt(sw_h, '.2f')}m/{fmt(sw_t, '.0f')}s{compass(sw_d)}"
            + (f" 沖{outer_h:.2f}m透過{ratio*100:.0f}%" if ratio is not None else "")
            + f" 風{wind_s.replace(' ', '').replace('m/s', '')}"
        )
        data_rows.append({
            "time": f"{h:02d}:00", "hs": hs, "size": size,
            "sw_h": sw_h, "path": path_vals,
            "swell": (f"{fmt(sw_h, '.2f', 'm')}/{fmt(sw_t, '.1f', 's')} "
                      f"{compass(sw_d)}") if sw_h is not None else "--",
            "outer": (f"{outer_h:.2f}m/{fmt(outer_t, '.0f', 's')} @{outer_dist}km"
                      if outer_h is not None else "--"),
            "ratio": ratio,
            "wind": (f"{compass(wd)} {ws:.1f}m/s"
                     if (wd is not None and ws is not None) else "--"),
            "wtype": wind_label(wd, spot["facing"]),
        })
        log_rows.append([target, f"{h:02d}:00", spot["name"],
                         fmt(sw_d, ".0f") if sw_d is not None else "",
                         fmt(outer_h, ".2f") if outer_h is not None else "",
                         fmt(sw_h, ".2f") if sw_h is not None else "",
                         f"{ratio:.2f}" if ratio is not None else ""])

    for ring in rings:
        if ring["data"] is not None:
            lines.append(f"  ({ring['dist']}km沖の格子: "
                         f"{ring['data']['latitude']:.3f},{ring['data']['longitude']:.3f}"
                         " — 陸に近い場合は格子スナップに注意)")
        else:
            lines.append(f"  ({ring['dist']}km沖: データ取得失敗)")
    lines.append("  ※透過率 = 岸格子うねり高 ÷ 値のある最遠リングのうねり高。"
                 "モデルの陸地遮蔽・減衰を織り込んだ実効値")
    data = {
        "spot": spot, "error": None,
        "grid": f"{beach['latitude']:.3f},{beach['longitude']:.3f}",
        "bearing": (f"{compass(up_bearing)}({up_bearing:.0f}°)"
                    if up_bearing is not None else "欠測"),
        "rows": data_rows,
        "ring_grids": [(r["dist"],
                        (f"{r['data']['latitude']:.3f},{r['data']['longitude']:.3f}"
                         if r["data"] is not None else "取得失敗"))
                       for r in rings],
    }
    return "\n".join(lines), "\n".join(compact), log_rows, data


# ---- 配信アダプタ (認証情報が無いチャネルは黙ってスキップ) ----

def post_json(url, payload, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def deliver_slack(text):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    post_json(url, {"text": f"```{text}```"})  # 等幅表示のためコードブロック


def deliver_line(compact_text):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return
    # テキスト1通5,000字制限があるためスポット区切りで分割し、
    # broadcast 1リクエスト5通の上限内でまとめて送る
    chunks, cur = [], ""
    for block in compact_text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > 4500:
            chunks.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        chunks.append(cur)
    for i in range(0, len(chunks), 5):
        post_json("https://api.line.me/v2/bot/message/broadcast",
                  {"messages": [{"type": "text", "text": c}
                                for c in chunks[i:i + 5]]},
                  {"Authorization": f"Bearer {token}"})


WIND_TAG = {"オフ": ("#1a7f4e", "#e2f4ea"), "オン": ("#b25a00", "#fdeeda"),
            "サイド": ("#5a6b7a", "#eceff2"), "--": ("#98a4ae", "#f1f4f6")}

PATH_RING = "#a9cfec"   # 伝搬バー: 沖リング(同一ヒューの淡ステップ)
PATH_BEACH = "#1a78c2"  # 伝搬バー: 岸格子(アクセント)
PATH_NULL = "#dde6ee"   # 欠測スロット


def path_svg(path_vals, beach_h, card_max):
    """沖→岸のうねり高ミニバー。左=最遠リング、右端の濃い棒=岸格子。
    途中でガクッと落ちる形=経路上の遮蔽・減衰がそのまま見える"""
    slots = list(reversed(path_vals)) + [("岸", beach_h)]  # 遠→近
    bw, gap, H, base = 8, 2, 22, 20
    W = len(slots) * bw + (len(slots) - 1) * gap
    parts = [f'<svg class="pathsvg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img">']
    for k, (dist, v) in enumerate(slots):
        x = k * (bw + gap)
        name = f"{dist}km沖" if dist != "岸" else "岸格子"
        if v is None:
            parts.append(f'<rect x="{x}" y="{base-2}" width="{bw}" height="2" '
                         f'fill="{PATH_NULL}"><title>{name}: 欠測</title></rect>')
            continue
        h = max(2, round(v / card_max * 18)) if card_max > 0 else 2
        color = PATH_BEACH if dist == "岸" else PATH_RING
        parts.append(f'<rect x="{x}" y="{base-h}" width="{bw}" height="{h}" '
                     f'rx="1.5" fill="{color}">'
                     f'<title>{name}: {v:.2f}m</title></rect>')
    parts.append(f'<line x1="0" y1="{base}" x2="{W}" y2="{base}" '
                 'stroke="#e3ebf1" stroke-width="1"/></svg>')
    return "".join(parts)


def write_html(path, pages, target):
    """構造化データからライトテーマのカード型ページを生成"""
    css = """
:root{--ink:#22313f;--sub:#6b7a88;--line:#e3ebf1;--accent:#1a78c2}
*{box-sizing:border-box}
body{background:#f4f8fb;color:var(--ink);margin:0;padding:1.2rem;
  font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:1.25rem;margin:0}
.date{color:var(--accent);font-weight:600}
.sub{color:var(--sub);font-size:.8rem;margin:.2rem 0 1.2rem}
h2{font-size:.95rem;color:var(--accent);border-bottom:2px solid var(--line);
  padding-bottom:.25rem;margin:1.6rem 0 .7rem}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:.9rem 1rem;margin:.7rem 0;box-shadow:0 1px 3px rgba(30,60,90,.06)}
.spot{font-size:1.02rem;font-weight:700;margin-bottom:.1rem}
.meta{color:var(--sub);font-size:.75rem;font-weight:400}
.tblwrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.82rem;white-space:nowrap;
  font-variant-numeric:tabular-nums}
th{color:var(--sub);font-weight:600;text-align:left;padding:.3rem .55rem;
  border-bottom:1px solid var(--line);font-size:.72rem}
td{padding:.3rem .55rem;border-bottom:1px solid #f0f5f9}
tr:last-child td{border-bottom:none}
.chip{display:inline-block;border-radius:999px;padding:.1rem .55rem;
  font-weight:700;font-size:.78rem}
.tag{display:inline-block;border-radius:4px;padding:.05rem .4rem;
  font-size:.72rem;font-weight:600;margin-left:.3rem}
.ratio{font-weight:600}
.pct{font-weight:600;font-size:.78rem;margin-left:.4rem;
  font-variant-numeric:tabular-nums}
.pathsvg{vertical-align:middle}
.err{color:#b0483f;font-size:.85rem}
details{margin-top:.5rem;font-size:.72rem;color:var(--sub)}
.legend{display:flex;flex-wrap:wrap;gap:.35rem;margin:.5rem 0}
.note{color:var(--sub);font-size:.72rem;line-height:1.7;margin-top:1.4rem}
"""
    body = [f'<div class="wrap"><h1>\U0001f30a プレーン波予測 '
            f'<span class="date">{target}</span></h1>'
            '<div class="sub">モデル値のみ・評価なし ('
            'Open-Meteo Marine + 気象庁MSM風)</div>']
    area_seen = None
    for p in pages:
        spot = p["spot"]
        if spot["area"] != area_seen:
            area_seen = spot["area"]
            body.append(f"<h2>{area_seen}</h2>")
        if p.get("error"):
            body.append(f'<div class="card"><div class="spot">{spot["name"]}'
                        f'</div><div class="err">{p["error"]}</div></div>')
            continue
        body.append(
            f'<div class="card"><div class="spot">{spot["name"]} '
            f'<span class="meta">うねり主方位 {p["bearing"]} ・ '
            f'岸格子 {p["grid"]}</span></div><div class="tblwrap"><table>'
            '<thead><tr><th>時刻</th><th>サイズ(有義波高)</th><th>風</th>'
            '<th>伝搬 沖→岸</th>'
            '<th>うねり(岸格子)</th><th>沖の生値</th>'
            '</tr></thead><tbody>')
        card_max = max([v for r in p["rows"] for _, v in r.get("path", [])
                        if v is not None]
                       + [r["sw_h"] for r in p["rows"] if r.get("sw_h") is not None]
                       + [0.01])
        for r in p["rows"]:
            label, bg, fg = r["size"]
            size_cell = (f'<span class="chip" style="background:{bg};'
                         f'color:{fg}">{label}'
                         + (f' {r["hs"]:.2f}m' if r["hs"] is not None else "")
                         + "</span>")
            pct = (f'<span class="pct">{r["ratio"]*100:.0f}%</span>'
                   if r["ratio"] is not None else '<span class="pct">--</span>')
            path_cell = (path_svg(r.get("path", []), r.get("sw_h"), card_max)
                         + pct)
            wfg, wbg = WIND_TAG.get(r["wtype"], WIND_TAG["--"])
            wind_cell = (r["wind"] + (f'<span class="tag" style="color:{wfg};'
                                      f'background:{wbg}">{r["wtype"]}</span>'
                                      if r["wind"] != "--" else ""))
            body.append(f'<tr><td>{r["time"]}</td><td>{size_cell}</td>'
                        f'<td>{wind_cell}</td><td>{path_cell}</td>'
                        f'<td>{r["swell"]}</td><td>{r["outer"]}</td></tr>')
        rings_txt = " / ".join(f"{d}km沖: {g}" for d, g in p["ring_grids"])
        body.append('</tbody></table></div>'
                    f'<details><summary>リング格子座標</summary>{rings_txt}'
                    '</details></div>')
    legend = "".join(
        f'<span class="chip" style="background:{bg};color:{fg}">{label}'
        + (f" 〜{th}m" if th else "+") + "</span>"
        for th, label, bg, fg in SIZE_BINS)
    body.append(
        f'<h2>\U0001f4cf 体感スケール(単位換算)</h2>'
        f'<div class="legend">{legend}</div>'
        '<div class="note">サイズは岸格子の有義波高をそのまま体感ラベルに換算した値。'
        '格子は約8kmで岸から離れた沖の値のため、実際のセットフェイスは地形・周期で'
        'これより上下する。<br>「伝搬 沖→岸」のバーは、うねりの来る方位に沿って'
        '150→90→40→15km沖と遡ったうねり高(淡色)と岸格子(濃色)。'
        '左から右へ段差がガクッと落ちる形=経路の途中で陸に遮蔽・減衰されて'
        '浜まで届いていない。%は透過率(岸格子うねり高÷最遠リングうねり高、'
        'モデルの陸地遮蔽・減衰込みの実効値)。バーにマウスを乗せると実値。'
        '風のオフ/オン/サイドはビーチ正面方位との幾何計算。評価・予想は含まない。</div>'
        "</div>")
    html = ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>\U0001f30a 波予測 {target}</title><style>{css}</style>'
            f'</head><body>{"".join(body)}</body></html>')
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(html)


def append_log(rows):
    if not rows:
        return
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "time", "spot", "swell_dir_deg",
                        "outer_swell_m", "beach_swell_m", "transmission"])
        w.writerows(rows)


def main():
    target = str(date.today() if "--today" in sys.argv else date.today() + timedelta(days=1))
    # --area 京丹後 / --area 生見 のようにエリア名・ポイント名で絞り込み(部分一致)
    area = None
    if "--area" in sys.argv:
        area = sys.argv[sys.argv.index("--area") + 1]
    spots = [s for s in SPOTS
             if area is None or area in s["area"] or area in s["name"]]

    reports, compacts, pages, failures = [], [], [], 0
    for spot in spots:
        try:
            report, compact, log_rows, data = build_report(spot, target)
            append_log(log_rows)
        except Exception as e:  # 1ポイントの想定外エラーで全体を落とさない
            report = compact = (f"◆ {spot['area']}/{spot['name']}  {target}"
                                f"  [エラー: {type(e).__name__}: {e}]")
            data = {"spot": spot, "error": f"{type(e).__name__}: {e}"}
            failures += 1
        print(report + "\n")
        reports.append(report)
        compacts.append(compact)
        pages.append(data)

    full = f"\U0001f30a プレーン波予測 {target}\n\n" + "\n\n".join(reports)
    try:
        deliver_slack(full)
    except Exception as e:
        print(f"[slack配信失敗: {e}]")
    try:
        deliver_line("\n\n".join(compacts))
    except Exception as e:
        print(f"[line配信失敗: {e}]")
    if "--html" in sys.argv:
        write_html(sys.argv[sys.argv.index("--html") + 1], pages, target)

    if failures == len(spots):  # 全滅のときだけ失敗扱い
        sys.exit(1)


if __name__ == "__main__":
    main()
