# kr-beauty-sellers-data

데이터 전용 브랜치. 코드는 main 의 `scripts/collect_kr_beauty_sellers.py`.

- `latest.json` — 가장 최근 수집본
- `captures/<UTC 시각>.json` — 회차별 원본. 지우지 않는다.

main 의 `data/` 는 owned-core-local 이 바이트 단위로 고정하므로 여기에 따로 둔다.
수집 실패·차단은 items 0건과 사유(reason)로 남긴다.
