# BUYMA 로컬 어댑터 — 첫 구현 검토 기록

2026-10-25. 실제 API 연결·상품 게시가 완료된 상태가 아니다. 이 단계는 자비스가
상품 준비, 검증, 요청 접수, 비동기 결과 확인을 수행할 경계를 로컬에서 검증한다.
HTTP 클라이언트, credential 로딩, OAuth 동의, Webhook 서버는 설치하지 않았다.
`execution_enabled`와 `publication_confirmed`는 항상 `false`다.

## 기준과 기존 구조

- 복제 기준 main: `21af427c89307ef4d4cda3ae1ef372589d0de537`.
- 작업 중 재확인한 원격 main: `b09e479f1e402199de754f782b02890dcb110333`.
  차이는 `owned-pages-once.yml`, `index.html`, `check_owned_workflow_policy.py`다.
  해당 변경을 체크아웃하거나 되돌리지 않았고 신규 BUYMA 파일과 경로가 겹치지 않는다.
- 저장소에 AGENTS.md, `.agents/skills`, 기존 BUYMA 전용 코드가 없었다.
  `CLAUDE.md`, `.claude/skills/tdd/SKILL.md`, `docs/agents/domain.md`, `GLOSSARY.md`를 확인했다.
  테스트 범위는 사용자가 지정한 성공·거절·중복·타임아웃·429·잘못된 서명에 맞췄다.
- `scripts/build_product_master.py`의 기존 `canonical_product_id`, `pd_no`,
  `image_url`, `source.collected_at`, `listing.blocked_by`를 사용한다.
  `pd_no`에는 `B2026...` 형태의 영숫자 식별자도 실제로 존재한다.
- Shopify 큐의 action/payload hash 구분과 동일한 용어를 사용한다.
  `jarvis_execution.canonical`, `digest`, `ExecutionStore`의 기존 경로 검증,
  배타 잠금, fsync, 원자적 파일 교체를 재사용한다. Core registry나 계약은 변경하지 않는다.
- 다른 로컬 작업 디렉터리의 미커밋 변경을 읽기 전용으로 확인했다. 수정하지 않았다.

## 파일과 사용 경계

- `scripts/buyma_adapter.py`: 공개등록 payload 검증, 로컬 action 준비, fixture 수명주기와 서명 검증.
- `scripts/test_buyma_adapter.py`: 네트워크 socket을 금지한 unittest 회귀검사.
- `tests/fixtures/buyma_offline.json`: 명시적으로 합성한 예제. 실제 상품 정보·재고·가격·계정 증빙이 아니다.
- 이 문서: 검토 결과와 실제 연결 전에 필요한 항목.

준비 CLI는 stdout으로 계획만 출력한다. `--master`, `--listings`,
`--environment`, `--seller-id`, `--now`를 명시해야 한다. listings는 CP를 키로 하는
BUYMA 필드 객체다. 실제 seller_id가 확인되지 않았으므로 운영 대상을 추정하지 않는다.
비밀값을 listings에 넣으면 안 된다. 미지원/읽기 전용 필드는 검증에서 거절한다.

로컬 검증 실행:

```powershell
python -m unittest discover -s scripts -p test_buyma_adapter.py -v
```

`prepare_action`은 한국어 상품명을 일본어 카피로 바꾸거나 KRW 원가를 JPY 판매가로
추정하지 않는다. 관측된 이미지 URL만 기본값으로 옮긴다. 일본어 카피, BUYMA master ID,
JPY 가격, 배송 방법, 옵션, 재고를 명시해야 한다. 이미지 공개 접근 여부와 master ID의
실재성, 카테고리별 세부 규칙은 로컬 구조 검증만으로 확인할 수 없다.
공급처 최신성은 기존 실행 경계의 24시간 기준을 참고한 로컬 경고이며 운영 정책 변경이 아니다.
HTML/과도한 UTF-8 설명 길이, 만료/90일 초과 구매기한(JST), 이미지 개수·순서,
배송 방법, 색상×사이즈 전체 조합, 재고 상태·수량을 검사한다.

## 식별자, 큐, 영수증

`reference_number = jarvis-<canonical_product_id>`다. 제목·가격·배열 순서가 바뀌어도
같은 CP의 관리번호가 바뀌지 않는다. CLI는 기존 `pd_no_to_cp` registry와 중복을 검사한다.
대상은 environment와 seller_id로 묶고, `action_id`, payload hash, 원래 pd_no를 기록한다.

fixture 원장은 `data/operations/reports/.buyma-rehearsal.json`에만 저장되며
`mode: fixture_only`를 명시한다. 서버나 스케줄러에 연결하지 않는다.
같은 원장에는 한 환경/판매자만 들어갈 수 있다. 이 파일은 실제 게시 증거로 쓸 수 없다.

1. `SENDING` claim과 영수증을 먼저 원자적으로 저장한다.
2. 정상 `201`의 request_uid와 request_received_at를 확인하면 `ACCEPTED`다.
   BUYMA ID도 공개 완료도 아직 없다.
3. 서명·seller_id·reference_number·시각이 맞는 product/create 또는 product/update를
   확인한 뒤 BUYMA ID를 고유하게 매핑한다. 최초 `status: public` 확인으로 fixture의
   등록 수명주기가 `PUBLISHED`가 된다. 최초 공개 전 심사 중·초안 등은 `CREATED_NOT_PUBLIC`이다.
   최초 공개 후의 현재 상태는 별도 `remote_status`로 추적한다.
4. `PUBLISHED`라도 `simulated_publication_confirmed`만 true이며 실제
   `publication_confirmed`는 false로 유지한다. 모든 business hold도 그대로 남는다.
5. 422 또는 request_uid가 맞는 비동기 실패는 `REJECTED`다.
6. 타임아웃, 5xx, 불완전한 201, 409/중복 의심, 모순·역순 이벤트는
   `RECONCILIATION_REQUIRED`다. 재시작 후에도 재등록하지 않는다.
7. 429는 `RATE_LIMITED`와 공식 `X-Rate-Limit-Reset` 값을 보존한다.
   자동 재시도/대기 작업은 만들지 않는다. 검토 후 재시도 기능은 후속 범위다.

거절·429에서도 같은 reference를 자동 재전송하지 않는다. POST가 기존 상품을 수정할 수도
있기 때문이다. 변경 payload로 동일 관리번호를 덮어쓰는 것도 막는다. 중단 후 남은 잠금이나
`SENDING` 원장은 별도 확인 없이 초기화하지 않는다. 영수증은 이전 영수증 hash를 잇고
변조·행 상태 불일치를 검사한다. 로컬 hash는 계정 승인이나 인증된 운영 증거를 대체하지 않는다.

## Webhook

원본 body bytes에 application secret으로 HMAC-SHA256을 계산하고 Base64로 만든 뒤
`X-Buyma-Hmac-Sha256`와 constant-time 비교한다. JSON 파싱/상태 수정 전에 검사한다.
비밀값은 명시적 함수 인자로만 받으며 테스트에서는 합성 secret만 사용한다.
`X-Buyma-Event` 자체는 body 서명에 포함되지 않으므로 성공/실패 body 구조도 검사한다.
seller_id, API v1, 관리번호/요청 ID, BUYMA ID 충돌, 과거 시각을 검증한다.
검증된 본문 의미군(product snapshot 또는 create failure)+정규화 body hash를 영속 저장한다.
create/update 헤더 차이와 JSON 공백 차이는 동일 상품 스냅샷을 중복 처리하게 만들지 않는다.
실패 통지에 reference_number가 없으므로 request_uid로만 연결하며, 요청 ID를 잃은
타임아웃 이후의 실패를 상품에 임의 연결하지 않는다.

실제 수신 서버, 5초 내 HTTP 200 응답·큐 처리·시크릿 보관·환경별 Webhook 분리는
아직 구현/배포하지 않았다. 공식 문서에 없는 상품 조회 endpoint를 만들지 않았다.
결과가 불명확하면 승인된 조회/운영 확인 절차로 매핑을 해결해야 한다.

## 확인 결과와 남은 입력

실제 Product Master 356개에 BUYMA listing 입력을 비운 로컬 검사를 수행했다.
356개 모두 `BLOCKED`, BUYMA 필수 입력 누락, 공급처 관측 노후화가 유지됐다.
검증된 일본 시장가격, 수수료 개정 적용 여부, 실제 일본 배송비, 법률·공개 허가도
확인되지 않았다. 기존 미국 배송 계획 하한 9,000원을 일본 배송비로 옮기지 않았고
최소 마진 3,000원·STOP·예산·Core 계약을 바꾸지 않았다. Shopify도 변경하지 않았다.

연결 담당자가 확인할 사항:

- BUYMA API 신청 접수와 **이용 승인**을 구분한 승인 증빙 및 실제 seller_id/계정.
- 승인된 앱과 OAuth 연결 상태. 토큰 발급·비밀값 읽기/복사는 이 작업에서 수행하지 않았다.
- 운영/샌드박스 환경, 등록된 callback/Webhook URL, 안전한 secret/token 주입 방식.
- 공식 master CSV의 브랜드/카테고리/지역/색상·사이즈 ID와 계정별 배송 방법 ID.
- 검증된 일본어 상품 정보, 사용 권한이 있는 공개 이미지, 실제 옵션별 재고·구매 가능 수량.
- 신선한 공급처 관측, 일본 시장가격 근거, 실제 일본 배송 견적, 현재 적용 수수료와 손익 검증.
- 별도로 검토한 live transport 및 인증된 실행 허가 검증기. 편집 가능한 JSON flag는 허가가 아니다.
- Webhook 수신·저장·응답 경계와 운영 결과 대조 절차. sandbox 통합검증도 아직 수행하지 않았다.

## 테스트 기록

- 신규 BUYMA: P2 보강 후 68개 테스트 통과. payload 유효성, 실제 master 전체, CLI, 성공/거절,
  접수와 공개 분리, 재시작, 중복, 타임아웃/5xx/불완전 응답, 429, 잘못된 서명,
  판매자/ID 충돌, 오래된 이벤트, 저장 중단, 원장 손상 포함.
- 기존 `validate_commerce_architecture.py`: 통과.
  `master=356 S=6 gate_ready=0 legal_complete=0 exports=3`.
- fixture 개행 문제를 제외한 실행·Core·영속성 4개 모듈 별도 확인:
  67개 실행, 66개 통과, 1개 플랫폼 skip, 실패 없음.
- 기존 6개 모듈의 회귀검사: 76개 실행, 71개 통과, 1개 skip, 3개 failure + 1개 error.
  대상: test_jarvis_execution, test_execution_receipt_clock, test_owned_core_local,
  test_prepare_owned_core_policy, test_durable_local_runtime, test_actions_release_integration.
- 4건 실패 원인: Windows `core.autocrlf=true`로 hash-pinned fixture가 CRLF로 체크아웃됐다.
  실패한 준비 테스트의 historical import record/policy, 릴리스 테스트의 격리된 Core/Deep/Preflight
  YAML 모두 **현재 바이트 ≠ git blob, CRLF→LF 정규화 바이트 = git blob**을 읽기 전용으로 확인했다.
  git blob의 record/policy SHA256은 테스트의 고정 pin과 일치한다.
  완전 통과로 보고하지 않으며 fixture/워크플로/고정 pin을 변경하지 않았다.
- 자동 승인 검토가 복제본의 해당 fixture를 원본 바이트로 복원하는 쓰기를 거부했다.
  이유는 미커밋 변경 덮어쓰기 가능성이다. 거부된 복원을 재시도/우회하지 않았다.
  기존 실패를 해결하기 위한 원본 fixture 복원은 미수행 상태다.

## 후속 코드 검토와 보강

최초 테스트 결과를 그대로 신뢰하지 않고 악성 입력과 상태 전이를 두 번째로 검토했다.
발견한 문제를 fixture로 재현하고 신규 BUYMA 코드와 테스트만 보강했다.

| 발견 사항 | 수정 및 검증 |
| --- | --- |
| caller가 완료/허가 flag나 임의 credential 키를 action에 넣으면 복사될 수 있었음 | action 키 집합·고정 false flag·ID·토큰 헤더 이름 검증. unknown listing 키도 출력 전에 거절 |
| 거절 뒤 모순되는 성공 이벤트가 reconciliation을 거쳐 다시 성공할 가능성 | `confirmation_blocked`를 유지해 모순·역순 이후 자동 성공 전환 금지. timeout만 서명된 올바른 결과로 해소 가능 |
| 중복 JSON 키, NaN, 큰 body, 미래 시각의 명시적 방어 부족 | raw 2 MiB 상한, strict JSON, 수신 시각과 생성/실패 시각 검증 추가 |
| 이전에 존재하던 상품을 새 등록 결과로 연결할 수 있었음 | 최초 ID 매핑 시 created_at이 현재 시도보다 이전이면 거절 |
| 원장 `{}` 또는 위조된 완료 flag가 명확히 거절되지 않았음 | 기존 빈 원장 재초기화 금지, 원장의 false flag·모드·대상·모의 완료 일관성 검사 |
| 예외 문구가 잘못 넣은 날짜 문자열을 반사할 수 있었음 | timestamp/available_until 오류를 입력값 없는 고정 사유로 변경 |
| URL 형태만 맞는 localhost/사설 IP가 통과 가능 | 명백한 로컬 호스트·사설 IP·URL credential 거절. DNS/public 접근 검증은 후속 증빙 필요 |

공식 Webhook 서명 규칙을 다시 직접 확인했다. HMAC 알고리즘은 독립적으로 알려진
RFC 4231 case 1 벡터로도 검사한다. Base64는 허용하고 hex digest는 거절한다.
headers/application_secret/raw webhook body는 원장에 저장하지 않는다.
HTTP client·credential 로딩·OAuth·서버·live dispatcher는 여전히 없다.
동시 쓰기는 기존 ExecutionStore의 O_EXCL 잠금과 원자 저장을 사용한다.
동시 잠금 획득, 저장 중단, 재시작, receipt hash와 행 상태 손상을 검사한다.

## 매일 1개: 실행기에 연결하지 않은 후보 계획

`plan_daily_candidate`는 순수 로컬 후보 함수다. 스케줄·전송·슬롯 저장을 하지 않는다.
현재 운영 일일 한도가 설치되었다고 해석하면 안 된다. 실제 연결 단계에서는
후보 검증과 슬롯 claim을 동일한 배타 transaction 안에 넣어 동시 실행을 막아야 한다.
fixture의 `attempted_at`은 명시한 시험 시각이며 실제 API 시각 증거가 아니다.

- 날짜는 KST(UTC+9)의 자정으로 나눈다. 후보는 최대 1개다.
- `SENDING`/`ACCEPTED`/`RECONCILIATION_REQUIRED`/`CREATED_NOT_PUBLIC`은
  성공 0건을 유지하면서 슬롯을 예약한다. 전날 미확정 결과도 다음 날 새 후보를 막는다.
- 서명 검증 후 `public`일 때만 모의 성공으로 센다. 실제 성공 수는 항상 0이다.
  전날 요청이 오늘 공개되면 오늘 공개일에도 슬롯을 소비한다.
  집계일은 불변 `registration_publication.published_at`을 사용하며 후속 수정일로 이동하지 않는다.
- 명확한 거절/429는 다른 상품의 후보 검토를 허용하지만 동일 상품을 자동 재등록하지 않는다.
  모순 이벤트로 reconciliation이 된 상품은 계속 예약 상태다.
- 실제 순수 비용 검증기 `evaluate_japan_costs`를 일일 후보에 연결했다.
  `cost_inputs`를 CP별로 주면 모든 후보가 이 검증기를 거친다. 계산을 생략하는
  `eligible/net_profit` callback 경로는 제거했다.
  후보별 `candidate_checks`에는 비용·증빙·시장 검증의 구체적 차단 사유를 남긴다.
- 증빙의 진위를 확인하는 신뢰된 `evidence_verifier`는 별도 연결 지점이다.
  기본 미연결이므로 실제 자료가 없으면 차단한다. 편집 가능한 `approved: true`는 허가가 아니다.
- 최소 순이익 3,000원, 일본 배송·BUYMA 수수료·일본 시장가격·판매 전략·최신 공급처·
  법률/공개 허가·KRW/JPY 환율·포장비의 증빙과 계산이 모두 통과해야 로컬 후보가 된다.
  합성 fixture의 통과는 실제 비용/전략 검증 완료를 뜻하지 않는다.

### 일본 비용 입력 계약

배송비는 상품 순중량이나 상품 개수에 자동 곱하는 금액이 아니라 주문/택배 건 단위다.
증빙은 아래 입력을 서로 다른 필드로 묶는다. 계산 로직은 구현했으며 새 가격 정책·외부 수집·실행은 설치하지 않았다.

| 입력 | 단위/확인 사항 |
| --- | --- |
| 상품 순중량 | g, 상품 자체의 확인된 측정값 |
| 포장 후 실중량 | g, 실제 판매 구성과 포장 기준 |
| 박스 길이·너비·높이 | cm, `cm³/6000` kg 부피중량의 근거 |
| 청구 중량·요금 구간 | 포장 실중량과 부피중량 중 큰 값, 서비스의 다음 요금 구간 적용 |
| 서비스·계약 | EMS/K-Packet 구분, K-Packet 계약 확인 |
| 최종 일본 배송 견적 | KRW/택배 건, 조회 시각·출처·추가운송료 포함 여부, 방문/보험 포함 여부 |
| 포장비 | KRW/건, 배송료와 분리 |
| BUYMA 비율·정액 수수료 | 적용 기준/개정 시점과 통화까지 분리 |
| KRW/JPY 환율 | 기준 방향·관측 시각·출처, 손익 검증 시점과 묶음 |

[우정사업본부 EMS 요금표](https://www.koreapost.go.kr/kpost/subIndex/239.do)의
일본 비서류 0.5kg 26,000원/1kg 28,500원과
[2026-07-01 공고](https://ems.epost.go.kr/front.EmsNewsDetail.postal?db=notice&seq=1400)의
EMS 비서류 추가운송료 0원은 참고 근거다. 방문/보험과 실제 포장 중량은 별개다.
[K-Packet 기본료](https://ems.epost.go.kr/front.EmsDeliveryDelivery14.postal)의
100g 4,550원/300g 6,930원/500g 9,340원/1kg 14,090원도 계약과 추가운송료 포함
최종액을 대체하지 않는다. 이 숫자를 확정 판매가격 입력으로 하드코딩하지 않았다.
미확인 비용·수수료·환율·포장비를 0으로 바꾸지 않는다. 증빙 참조의 누락/0/unknown이나
기본요금 숫자만 전달하면 후보가 차단되는 회귀검사를 추가했다.

### 순수 비용/전략 검증기 입력과 재계산

`evaluate_japan_costs(action, inputs, now=..., evidence_verifier=...)`는 네트워크와
파일 쓰기를 하지 않는다. 전체 합성 입력 예제는 `buyma_offline.json`의 `costs`에 있다.
가격/중량/비율은 정수 또는 Decimal 문자열로 받고 float·NaN·Infinity·음수·null을 거절한다.
명시적이고 검증된 0원 추가료/포장비는 허용하지만 누락 값을 0으로 채우지 않는다.

| section | 필수 의미 |
| --- | --- |
| offer | JPY 단위 판매가, 주문의 listing 수량, 고객 배송 청구액, 관측/유효 시각 |
| purchase | KRW 단위 매입가, listing당 실물 수량, 주문 총 실물 수량(두 값 재검산), 관측/유효 시각 |
| shipping | JP, 한 주문/한 택배, EMS/K-Packet, 계약 확인, 실물 단위 순중량·포장 실중량·박스 cm, 검증된 중량 구간/청구 구간, 기본료·추가운송료·기타료·최종액, 모든 추가료 포함 여부, 견적/유효 시각 |
| packaging | KRW 주문당 포장비와 관측/유효 시각 |
| fee | JPY, 주문 매출 기준 비율, 주문당 정액, 명시적 반올림 방식, 적용 시작·관측·유효 시각 |
| fx | `KRW_PER_JPY` 방향의 환율과 관측/유효 시각 |
| supplier | action의 원본 공급처 hash와 일치하는 최신 관측/유효 시각 |
| legal / strategy | 검증된 공개 허가 및 주문 고객 총액 기준 전략, 관측/유효 시각 |
| market | JPY 고객 총액의 검증된 전략 상한과 관측/유효 시각. 없으면 경쟁력 미완료 |

모든 section 증빙은 대상 환경/판매자, CP, 등록 payload hash, **전체 비용 입력 hash**,
해당 section 사실을 묶는다. `evidence[key]`가 이 묶음의 hash와 일치해야 하고,
신뢰된 코드 `evidence_verifier(key, binding, ref)`가 진위를 별도로 확인해야 한다.
hash 재계산이나 JSON의 verified flag만으로 통과하지 않는다. 다른 주문 구성의 배송/매입
증빙을 섞는 것도 막는다. 현재 실제 증빙 인증원은 미연결이며 테스트는 합성 인증기를 사용한다.

재계산 순서:

1. 단위 JPY 판매가는 올림하고 실제 등록 payload의 정수 가격과 일치시킨다.
2. 주문 고객 총액 = 정수 단위가 × listing 수량 + 고객 배송 청구액.
3. 비율 수수료 = 주문 고객 총액 × 비율을 검증된 방식(CEILING/HALF_UP/FLOOR)으로
   정수 JPY 처리한다. 주문당 정액 JPY 수수료를 별도로 한 번 더한다.
   이 지원 계약과 다른 실제 수수료 기준은 임의 추정하지 말고 입력/검증기 확장 전까지 보류한다.
4. KRW 순이익 = (고객 총액 − 비율 수수료 − 정액 수수료) × KRW_PER_JPY
   − (단위 매입가 × 실물 총수량 + 최종 주문 배송비 + 주문 포장비).
   배송/포장/정액 수수료를 상품 수량만큼 중복 곱하지 않는다.
5. 최소 3,000원은 Decimal 원값으로 비교한다. 2,999.99원을 올려서 통과시키지 않는다.
   수수료 반올림까지 재계산하는 이분 탐색으로 최소 정수 JPY 판매가도 구한다.
6. 주문 실물 순중량 합계 ≤ 포장 실중량을 확인하고,
   `max(포장 g, 길이×너비×높이/6 g)` 이상의 첫 검증된 요금 구간을 선택한다.
   입력된 청구 중량이 이 구간과 다르면 차단한다. 지역/서비스별 구간표는 자동 추측하지 않는다.
7. K-Packet 계약 미확인, 추가료 미확인, 최종액 불일치, 적용 전/만료/미래 견적·환율·수수료는 차단한다.
   시장 증빙 누락/상한 초과는 마진 계산과 분리해 `market_status: incomplete`로 남긴다.

시험 예: 5,000JPY 판매가, 7% 비율 수수료(350JPY), 100JPY 정액, 9KRW/JPY,
매입 5,000원 × 실물 2개, 배송 26,000원, 포장 1,000원이면 순이익은 3,950원이다.
최소 판매가는 4,888JPY다. 4,887JPY는 2,996원, 4,888JPY는 3,005원이므로 경계를 확인할 수 있다.
이는 합성 회귀검사 값이며 실제 BUYMA 수수료·환율·배송 견적이 아니다.

한 listing이 실물 두 개짜리 번들이면 `listing_quantity=1`, `units_per_listing=2`로 표현한다.
여러 listing 구매 시나리오도 주문 배송비를 한 번만 계산하지만, 구매자가 한 listing만 살 수
있으므로 다량 주문 시나리오의 이익으로 등록 후보를 통과시키지 않는다.
일일 후보는 단일 listing 주문 시나리오에서의 검증을 요구한다.

이 추가 작업에서도 실제 자료/가격 확정, API 호출, credential 접근, 게시, 스케줄,
Core·워크플로 변경은 없으며 기존 거부 fixture를 변경하지 않았다.

## 기존 실패 4건의 읽기 전용 증명

### 독립 검토 P2 수정 기록

다음 4개 테스트를 먼저 추가해 이전 구현에서 모두 실패하는 것을 직접 재현했다.
수정 후 4개가 모두 통과하고, 과도한 중복제거·이력 변조·구버전 원장 검사 2개를 더해
전체 BUYMA 테스트는 68개가 통과했다.

| 회귀 테스트 | 수정 전 관측 | 수정 후 |
| --- | --- | --- |
| `test_p2_later_public_update_does_not_move_original_registration_to_new_day` | 다음 날 public 수정만으로 모의 성공 1건 | 최초 공개일 고정, 다음 날 신규 성공 0건 |
| `test_p2_soldout_after_publication_is_current_status_not_pending_registration` | soldout이 CREATED_NOT_PUBLIC로 내려감 | 등록 완료는 PUBLISHED 유지, 현재 remote_status만 soldout |
| `test_p2_same_signed_snapshot_with_only_event_header_changed_is_duplicate` | create→update 헤더 변경만으로 재처리·조정 필요 | 같은 본문/서명은 duplicate, 원장 불변 |
| `test_p2_id_conflict_immediately_persists_reconciliation_and_original_mapping` | 예외 후 저장 상태는 PUBLISHED 유지 | 충돌 즉시 조정 필요·blocked true·모의 확인 false를 영속 저장 |

최초 공개의 `registration_publication`에는 원래 BUYMA ID, 최초 확인 스냅샷의
`published_at`, 본문 event digest를 기록한다. 이는 최초로 확인한 공개 스냅샷의 서버
updated_at이며 그보다 앞선 실제 공개 시각을 추정하지 않는다. 이후 현재 상태·수정 시각은
`remote_status`, `remote_updated_at`만 갱신한다. 정상 후속 soldout/중지/삭제 상태가
등록 완료를 미확정 상태로 되돌리지 않는다. `simulated_publication_confirmed`는
등록 완료에 대한 모의 확인이며 현재 판매 중이라는 뜻이 아니다.

최초 공개 이력은 모든 후속 영수증에도 동일하게 포함하고, 이전 영수증과의 불변성 및
현재 행과 영수증의 일치를 확인한다. ID 충돌에서는 원래 매핑·최초 공개 이력을 보존하고
충돌 사유, 원래 ID, 수신 ID, 수신 updated_at, event digest만 최소 증거로 저장한다.
다시 읽어도 RECONCILIATION_REQUIRED이며 자동 재등록하지 않는다. 실제 공개 확인 flag는
계속 false다. 역사적 최초 공개 실적도 후속 충돌 때문에 다른 날짜로 이동시키지 않는다.

중복 키는 서명되지 않은 create/update 헤더가 아닌 `product_snapshot` 의미군과
검증된 전체 JSON 본문으로 만든다. 다른 본문/updated_at은 계속 처리하며,
`product_create_failure`는 별도 의미군과 구조 검사로 처리한다. 성공 본문의 헤더를
실패로 바꾸면 유효 실패 통지가 되지 않는다. 실제 실패 본문도 성공 스냅샷에 묻혀
중복 제거되지 않는 것을 검증했다.

새 모의 원장 형식은 schema 2다. 최초 공개 이력이 없는 schema 1 원장은 자동 변환하거나
현재 수정 시각을 과거 공개 시각으로 추정하지 않고 거절한다. 이전 모의 원장의 복원/초기화는
수행하지 않았다. 이 변경은 새 BUYMA 모의 저장 형식에만 적용하며 기존 Core 계약은 바꾸지 않는다.

실제 증빙 인증원·전송·스케줄러·실운영 동시 실행은 여전히 미구현/미검증이다.
로컬 O_EXCL 잠금 및 fixture 상태 검사를 운영 동시성 검증 완료로 보고하지 않는다.

### 기존 해시 고정 검사 실패

정확한 테스트명과 첫 실패 지점:

1. `test_prepare_owned_core_policy.PreparationTests.test_real_reviewed_record_fixture_policy`:
   historical import record와 historical policy의 SHA256 pin 비교 실패(error).
2. `test_actions_release_integration.ReleaseIntegrationTests.test_core_no_synthetic_generators`:
   격리된 `JARVIS-Core-Automation.yml` Git blob SHA1 비교 실패.
3. `test_actions_release_integration.ReleaseIntegrationTests.test_required_new_checks_exist_and_preflight_runs_them`:
   격리된 `preflight.yml` Git blob SHA1 비교 실패.
4. `test_actions_release_integration.ReleaseIntegrationTests.test_scheduled_model_evaluation_does_not_overwrite_prior_weights_first`:
   반복문의 첫 `JARVIS-Deep-Analysis.yml` Git blob SHA1 비교 실패.

아래 expected는 테스트/정책의 고정값이며 HEAD 원본에서 계산한 값과 일치한다.
actual은 작업 파일의 **바이트를 그대로** 해시한 값이다.

| 대상 | 알고리즘 | expected (= HEAD 원본) | actual (작업 파일) |
| --- | --- | --- | --- |
| historical-import-record-v1.json | SHA256 | `b609974aa560537a6183447eef29c9072e3dbc0ac8eabe03ce6986eb73c02f01` | `fbb00f7b2afb953e916e60c23fcd88e2f1090e5637fdd1c84871d7f1e25f7d41` |
| historical-import-policy-v1.json | SHA256 | `cfe83cdcf173efe10e4460472ae846e923262c868230398737ee3c993320161a` | `68fb91006d4efc6268ab1da2e030cdfd0cb84a15de4d86ddd72629ce8b117705` |
| JARVIS-Core-Automation.yml | Git blob SHA1 | `88281a6d915ae2defe085c21ca6a1d1a5b090655` | `c3c1d7c8ea590273fc4461f7ab539384db9ae0d9` |
| JARVIS-Deep-Analysis.yml | Git blob SHA1 | `55dbc1b99a4555329bac0ccc48264de3cfc616a5` | `e623e5cf33034336756cc8b5a5dd2eb0813f55c6` |
| preflight.yml | Git blob SHA1 | `a662091a17acbedc4ee244a02bc965f0fe5562c4` | `54c5e42f43935d9a43b96998ad7181780ed3c5a3` |

HEAD Git blob ID는 record=`5b3767e328b1b7073ff5f6bd64ef143e90a25e67`,
policy=`a98890f10e077551c85f49d5eaa8995fc321d80d`이며 YAML은 위 expected와 같다.

| 파일 | HEAD byte 수 | 작업 byte 수 | CRLF 개수/증가 byte 수 | 단독 CR |
| --- | ---: | ---: | ---: | ---: |
| record | 356995 | 356996 | 1 | 0 |
| policy | 2145 | 2146 | 1 | 0 |
| Core YAML | 16716 | 17036 | 320 | 0 |
| Deep YAML | 71613 | 73013 | 1400 | 0 |
| Preflight YAML | 11005 | 11218 | 213 | 0 |

5개 모두 `work.replace(b'\r\n', b'\n') == git show HEAD:<path>`가 true다.
문자열 해석이나 공백 제거가 아닌 전체 바이트 동등 비교로 개행 외 차이가 없음을 증명했다.
이 검사는 파일을 쓰지 않는다. 실제 원본 파일과 고정 pin, 워크플로, Git 설정은 변경하지 않았다.

독립 임시 입력 방법도 검토했다. 기존 실패 테스트는 실제 HEAD에 고정된 파일 바이트/위치를
검사하므로 합성 임시 입력으로 바꾸면 동일 검사 통과의 증거가 되지 않는다. 이를 우회해
통과시키거나 거부된 원본 복원을 다른 경로로 재현하지 않았다. 합성 임시 디렉터리 기반
BUYMA 및 기존 67개 실행/Core/영속성 검사는 별도로 실행하고, 원래 4건 실패는 보존한다.

커밋·push·배포·워크플로 활성화/재실행·실제 API 쓰기는 수행하지 않았다.
신규 파일의 diff만 검토 대상으로 남긴다.

## 직접 확인한 공식 근거

- [상품 API](https://specification.personal-shopper-api.buyma.com/api/products_json/):
  POST `/api/v1/products.json`, `{product: ...}`, 관리번호 고유성, 필수 필드,
  201 접수 영수증과 422 오류, 후속 Webhook.
- [REST API 비동기 처리](https://specification.personal-shopper-api.buyma.com/api/):
  접수와 실제 반영 사이 지연 및 request_uid.
- [OAuth](https://specification.personal-shopper-api.buyma.com/oauth/obtain_access_token/):
  공식 토큰 헤더는 `X-Buyma-Personal-Shopper-Api-Access-Token`이다.
  추측한 Bearer 인증을 사용하지 않는다.
- [Webhook](https://specification.personal-shopper-api.buyma.com/api/webhook/):
  body HMAC-SHA256/Base64, seller_id, 성공/실패 payload 차이, 중복 재전송.
- [레이트 제한](https://specification.personal-shopper-api.buyma.com/api/rate_limit/):
  429 및 `X-Rate-Limit-Reset`.
- [공식 이용약관](https://specification.personal-shopper-api.buyma.com/agreement/buyma_ps_api_user_agreement_for_providers_ver1.2.pdf):
  제4조 API 이용 대가는 무료, 제5조 연결 시작은 BUYMA 심사·승인 절차가 필요하다.
  API 무료와 판매 수수료/배송비는 별개다.
