#!/usr/bin/env python3
"""
plain_surf.py v4.1 — 座標だけから出すプレーン波予測(人間の評価・スコアなし)

v2: うねりの来る方位に沿って沖を遡ってサンプリングし、
    モデルが計算済みの減衰(遮蔽込み)を「透過率」として表示する。
v3: 配信アダプタ (Slack Webhook / LINE broadcast / HTML)
v4: 8エリア27ポイント + リング15/40/90/150km + --areaフィルタ
v4.1: 実データ対応の堅牢化。欠測null・取得失敗をポイント単位で隔離し、
      1ポイントの失敗で全体が落ちない構造に変更。

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
        return line, line, []

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
    compact = [f"◆{spot['area']}/{spot['name']} {target[5:]} うねり主方位{compass(up_bearing)}"]
    for h in HOURS:
        i = hour_index(beach, target, h)
        if i is None:
            continue
        sw_h = hv(beach, "swell_wave_height", i)
        sw_t = hv(beach, "swell_wave_period", i)
        sw_d = hv(beach, "swell_wave_direction", i)

        ring_cells = []
        outer_h = None
        for ring in rings:
            j = hour_index(ring["data"], target, h)
            rh = hv(ring["data"], "swell_wave_height", j)
            rt = hv(ring["data"], "swell_wave_period", j)
            if rh is not None:
                outer_h = rh  # 値のある最遠リングを採用
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
            f"  {h:02d}:00  {fmt(hv(beach, 'wave_height', i), '.2f', 'm')}    "
            f"{fmt(hv(beach, 'wave_period', i), '.1f', 's')}   "
            f"{fmt(sw_h, '.2f', 'm')}/{fmt(sw_t, '.1f', 's')} "
            f"{compass(sw_d)}({fmt(sw_d, '.0f', '°')})  "
            + "".join(f"{c:<10}" for c in ring_cells)
            + (f"{ratio*100:3.0f}%" if ratio is not None else " --")
            + f"    {wind_s}"
        )
        compact.append(
            f"{h:02d}時 {fmt(sw_h, '.2f')}m/{fmt(sw_t, '.0f')}s{compass(sw_d)}"
            + (f" 沖{outer_h:.2f}m透過{ratio*100:.0f}%" if ratio is not None else "")
            + f" 風{wind_s.replace(' ', '').replace('m/s', '')}"
        )
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
    return "\n".join(lines), "\n".join(compact), log_rows


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


def write_html(path, text, target):
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>波予測 {target}</title>
<style>body{{background:#0b1520;color:#d8e6f0;font-family:monospace;
margin:1rem}}pre{{white-space:pre;overflow-x:auto;font-size:13px;
line-height:1.6}}h1{{font-size:1rem;color:#7fb8d8}}</style></head>
<body><h1>プレーン波予測 {target} (モデル値のみ・評価なし)</h1>
<pre>{text}</pre></body></html>"""
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

    reports, compacts, failures = [], [], 0
    for spot in spots:
        try:
            report, compact, log_rows = build_report(spot, target)
            append_log(log_rows)
        except Exception as e:  # 1ポイントの想定外エラーで全体を落とさない
            report = compact = (f"◆ {spot['area']}/{spot['name']}  {target}"
                                f"  [エラー: {type(e).__name__}: {e}]")
            failures += 1
        print(report + "\n")
        reports.append(report)
        compacts.append(compact)

    full = "\n\n".join(reports)
    try:
        deliver_slack(full)
    except Exception as e:
        print(f"[slack配信失敗: {e}]")
    try:
        deliver_line("\n\n".join(compacts))
    except Exception as e:
        print(f"[line配信失敗: {e}]")
    if "--html" in sys.argv:
        write_html(sys.argv[sys.argv.index("--html") + 1], full, target)

    if failures == len(spots):  # 全滅のときだけ失敗扱い
        sys.exit(1)


if __name__ == "__main__":
    main()
