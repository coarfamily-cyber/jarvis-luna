# GLOSSARY

JARVIS LUNA 의 다이소 → Shopify 사업에서 쓰는 말. 에이전트는 이슈 제목, PR 본문,
설명(`/wait-what`, `/pr`)에서 이 말을 그대로 쓴다. 각 항목 끝의 경로가 정의의 근거다.
여기 없는 말이 필요하면 지어내지 말고 근거 파일을 먼저 찾는다.

## 상품

- **S등급**: 정본 채점표의 최상위 등급. Shopify 등록 대상은 S등급뿐이고 하위 등급 대체는 없다.
  `config/daiso_commerce_strategy.json` (`grade_policy`)
- **pdNo**: 다이소몰 상품 번호. Shopify 상품에는 `daiso-pd-<번호>` 태그로 붙는다. 중복 판정의 기준이다.
  `scripts/daiso_daily_beauty_to_shopify.py`
- **고시**: 다이소몰 상세페이지의 「상품정보 제공 고시」. 실제 내용은 상세 이미지의 `alt` 에 있다.
  HTTP 로 받은 HTML 에는 없고 렌더링해야 보인다. `CLAUDE.md`
- **랭킹 대체 / 바디 카테고리 대체**: 정규 S등급 후보가 없을 때 허용된 예외 경로. 언제나 비공개 초안으로만 만든다.
  `scripts/daiso_daily_beauty_to_shopify.py` (`ranking_fallback_draft_only`, `owner_category_fallback_draft_only`)

## 등록과 공개

- **초안 (DRAFT)**: 자동화가 만드는 비공개 상품. 자동화는 공개하지 않는다.
- **사업주 활성화**: 초안을 사업주가 검토한 뒤 공개하는 단계. 공개는 사람의 결정이다.
  `scripts/daiso_daily_beauty_to_shopify.py` ("prepare DRAFT, then owner activates")
- **공개 게이트**: 공개 판매 여부를 정하는 검사. 빠지거나 오래되거나 서로 어긋난 입력이면 막는다 (fail closed).
  `scripts/daiso_daily_beauty_to_shopify.py` (`canonical_public_gate`)

## 가격과 배송

- **착지원가 (landed cost)**: 원가 + 우체국 배송비 + 관세(ddu 일 때). 판매가 계산의 바탕이다.
  `scripts/pricing_model.py`
- **주문당 배송 하한 ₩9,000**: 가격 모델이 원가에 넣는 미국 1건 배송비 하한. 고객 청구액이 아니다.
  `scripts/pricing_model.py` (`US_ORDER_SHIPPING_FLOOR_KRW`)
- **1+1 (번들)**: 단품과 함께 파는 2개 구성. 판매 구성은 단품과 1+1 뿐이다. `scripts/pricing_model.py` (`SELL_QTYS`)
- **K-Packet 무료배송**: 우체국 K-Packet 이 가는 18개국은 결제 배송비 $0. 가격에 배송비가 이미 들어 있기 때문이다.
  `scripts/shopify_us_free_shipping.py` (`KPACKET_FREE_COUNTRIES`)

## 일하는 방식

- **11팀**: 상품 소싱·마케팅 조사·리스팅 제작·가격 정책·법률·규제·디자인·채널 운영·지식 수집·기관 수집·로보틱스 수집·옵시디언 그래프. `CLAUDE.md`
- **재귀적 자기개선 루프**: 잰다 → 가장 약한 고리 하나 → 고친다(전후 숫자) → 근거를 주석에 → 다시 잰다. `CLAUDE.md`
- **돌았다 / 됐다**: 실행이 끝난 것(돌았다)과 결과가 맞는 것(됐다)은 다르다. 보고는 "됐다" 를 확인한 뒤에 한다. `CLAUDE.md`

_피할 말_: "업로드 완료" 를 "공개" 의 뜻으로 쓰지 않는다. 초안 생성과 공개는 다른 단계다.
