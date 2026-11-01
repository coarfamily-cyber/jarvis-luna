---
title: JARVIS Graph Guide
type: graph-guide
status: manual
updated: 2026-11-01
---

# JARVIS Graph Guide

수동 탐색 안내입니다. 자동 생성 허브와 Knowledge 원본은 수정하지 않습니다. 아래 연결은 저장소에 존재하는 노트를 기준으로 합니다. 노트의 상태·시각은 과거 기록일 수 있으며 현재 운영 상태를 보증하지 않습니다.

## 시작점

- [[JARVIS Graph Hub|전체 지식 진입점]]
- [[Brain/JARVIS Brain|프로젝트·팀 허브]]
- [[Brain/Shopify Store|Shopify 프로젝트 기록]]
- [[Brain/Teams/옵시디언 그래프|옵시디언 담당팀]]
- [[Knowledge/JARVIS Real Knowledge Index|수집 지식 인덱스]]

## 프로젝트·팀·주제별 탐색

- 상품 프로젝트: [[Brain/Desks/스킨케어 전담팀|스킨케어]], [[Brain/Desks/메이크업 전담팀|메이크업]], [[Brain/Desks/바디 전담팀|바디]]
- 운영팀: [[Brain/Teams/상품 소싱팀|상품 소싱]], [[Brain/Teams/AI 수집팀|AI 수집]], [[Brain/Teams/마케팅 조사팀|마케팅 조사]], [[Brain/Teams/디자인팀|디자인]]
- 수집팀 기록: [[Knowledge/Teams/팀 · 지식 수집팀|지식 수집]], [[Knowledge/Teams/팀 · 채널 운영팀|채널 운영]]
- 주제 허브: [[Knowledge/Topics/Shopify-Commerce|Shopify]], [[Knowledge/Topics/AI-Agents|AI Agents]], [[Knowledge/Topics/AI-Research|AI Research]], [[Knowledge/Topics/뷰티스킨케어|뷰티·스킨케어]]

원하는 허브를 연 다음 명령 팔레트에서 **Open local graph**를 실행합니다. 깊이 1부터 시작해 필요할 때 2로 넓히세요. 팀 허브에 연결된 자료를 보려면 경로 필터보다 로컬 그래프가 적합합니다. 로컬 그래프의 필터는 전역 그래프와 별도로 확인하세요.

## 기본 전역 보기

Graph view 오른쪽 위 설정의 Search files:

```text
-path:Knowledge/Records -path:Personal/templates -path:.trash -path:Personal/
```

개인 자료는 기본 보기에서만 숨깁니다. 개인 자료에만 연결된 개념 노트는 고립 노드 숨김 설정으로 함께 사라질 수 있습니다. 그런 개념을 찾을 때는 아래 확장 보기로 바꾸거나 Orphans를 켜세요. Records·템플릿·휴지통 제외는 유지합니다. 색상 8개는 허브(노랑), 팀·전담팀(보라), 상품(초록), 수집 지식 허브(파랑), 개념(청록), 단계(주황), 브리핑(분홍), 개인 자료(회청색)입니다. 개인 자료 색상은 확장 보기에서 나타납니다.

태그·첨부·미해결 링크·고립 노드는 기본적으로 숨깁니다. 연결 정리나 누락 노트 점검 때만 Orphans 또는 Existing files only를 조절하세요. 색상 변경 자체는 노드나 연결을 줄이지 않습니다.

## 확장 보기와 좁혀 보기

개인 자료까지 포함하는 확장 보기(기존 범위):

```text
-path:Knowledge/Records -path:Personal/templates -path:.trash
```

상품·팀 프로젝트만:

```text
path:Brain/
```

AI 수집팀의 운영 노트와 수집팀 허브만:

```text
path:"Brain/Teams/AI 수집팀.md" OR path:"Knowledge/Teams/팀 · AI 수집팀.md"
```

위 검색은 두 노트만 선택합니다. 주변 자료를 보려면 해당 노트를 열고 로컬 그래프를 사용하세요.

주제 허브만:

```text
path:Knowledge/Topics/
```

개념 자료만:

```text
path:Concepts/
```

86,702개 원본 노트 전부를 보려면 Search files를 비우고 Orphans를 켭니다. 이 경우 Records까지 포함되어 느리거나 매우 조밀할 수 있습니다. 보통은 해당 주제 허브의 로컬 그래프에서 Records 제외를 잠시 해제하는 편이 탐색하기 쉽습니다. 작업을 마치면 기본 검색식으로 돌아오세요.

## 적용·복원

이 안내와 설정은 저장소에서 준비한 후보입니다. 실제 Windows 보관함 또는 Obsidian 화면에서 배치·검색 실행을 확인한 결과가 아닙니다. 연결된 PC에서 Obsidian을 종료한 뒤 기존 로컬 설정도 별도로 백업하고, 검토한 파일만 적용하세요. 실행 중인 앱은 설정을 다시 저장할 수 있습니다.

저장소 원본 설정은 `.obsidian/backups/graph.json.before-20261101`에 바이트 그대로 보존했습니다. 복원할 때 Obsidian 종료 후 이 파일을 `.obsidian/graph.json`으로 복사합니다. 노트 원본이나 생성기 설정은 복원 대상에 포함되지 않습니다.

문법 근거: [Obsidian Search](https://obsidian.md/help/plugins/search), [Graph view](https://obsidian.md/help/plugins/graph). `path:`는 경로 부분 문자열, `OR`는 합집합, 공백은 AND입니다. 앱 버전별 실제 표시 결과는 Obsidian에서 확인해야 합니다.
