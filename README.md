# plain-surf

座標だけから出すプレーンな波予測。人間の評価・スコアなし、モデル値のみ。

- データ: Open-Meteo Marine (ECMWF WAM/MFWAM系) + Open-Meteo JMA (気象庁MSM 5km風)
- うねりの来る方位に沿って 15/40/90/150km 沖を遡ってサンプリングし、遮蔽・減衰込みの「透過率」を表示
- 8エリア27ポイント (和歌山/志摩/那智勝浦/伊良湖/静岡/徳島北/室戸/京丹後)
- 毎朝5時(JST)に GitHub Actions が実行。手動実行は Actions タブの Run workflow から
- 配信: Slack (Secrets: SLACK_WEBHOOK_URL) / LINE broadcast (Secrets: LINE_CHANNEL_ACCESS_TOKEN) / GitHub Pages (docs/index.html)
- 実行ごとに plain_surf_log.csv へ透過率を追記 → 方向別伝達関数の実測データが蓄積される

ローカル実行: `python3 plain_surf.py --today` / エリア絞り込み `--area 京丹後`
