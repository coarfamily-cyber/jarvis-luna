# JARVIS LUNA - Craft Anything 웹 복제 엔진 가이드

자비스 루나(JARVIS LUNA) 자동화 마케팅 공장에 ArtCraft 팀의 오픈소스 역공학·복제 엔진 **Craft Anything**을 연동한 종합 가이드입니다.

---

## 1. 개요: Craft Anything이란?

- **핵심 기능**: 타겟 웹사이트, 앱, 랜딩페이지를 분석(Study)하고, 코딩 에이전트가 새 프로젝트를 빌드(Build)한 뒤, 원본과 나란히 비교(Check)하여 유사도(Likeness %)를 측정하고 다듬는(Refine) 4단계 자동화 엔진.
- **클린룸(Clean Room) 원칙**: 원본 내부의 비공개 소스코드를 불법 탈취하지 않고, 방문자 눈에 보이는 레이아웃·색상·폰트·반응형 그리드·동작을 측정해 자체 코드로 재구현.
- **반응형 3단 폭 실측 검증**: 1440px(데스크톱), 768px(태블릿), 390px(모바일) 세 가지 화면 크기로 원본과 결과물을 비교해 90% 이상 일치할 때까지 자동 보정.

---

## 2. 자비스 루나에서의 활용 목적

1. **경쟁사 쇼피파이 / 이커머스 상세페이지 고속 복제**:
   - `Apple_Watch_Ultra3_페이지_정확복제.html`과 같은 고전환율 랜딩페이지를 몇 분 만에 반응형 코드로 생성.
2. **다이소 및 드랍쉬핑 상품 페이지 영문화 & 쇼피파이 테마화**:
   - 소싱 상품의 판매 페이지 구조를 분석해 미국/글로벌 타깃 쇼피파이 스토어에 최적화된 독립 페이지로 재탄생.
3. **자비스 멀티에이전트(디자인/리스팅 팀) 자동화**:
   - Claude Code 스킬(`.claude/skills/craft-anything`)과 파이썬 파이프라인으로 에이전트가 자율적으로 고품질 복제본 빌드.

---

## 3. 실행 방법

### 방법 A. 윈도우 원클릭 실행 (가장 추천)
루트 폴더의 **`JARVIS_CRAFT_ANYTHING.bat`** 파일을 더블클릭합니다.
1. 타겟 웹사이트 URL 입력 (예: `https://apple.com`, `https://daiso.co.kr` 등)
2. 프롬프트 입력 (기본값: 쇼피파이 상세페이지 반응형 복제)
3. Study → Build → Check → Refine 루프가 자동으로 실행되어 `landing_pages/`에 완성본 HTML 저장.

### 방법 B. 파이썬 CLI 명령어
```bash
# 기본 반응형 복제 실행
python automation/craft_anything.py rebuild https://example.com --prompt "쇼피파이 상세페이지 반응형 복제"

# 타겟 시각적 요소 사전 분석 (Study)
python automation/craft_anything.py study https://example.com

# 저장 위치 지정 복제
python automation/craft_anything.py rebuild https://example.com --output landing_pages/my_product.html
```

### 방법 C. Claude Code 에이전트 스킬 호출
자비스 개발 환경에서 Claude Code 실행 시:
```
/craft-anything https://target-url.com
```

### 방법 D. 공식 바이너리 설치 (선택 사항)
공식 Rust CLI 바이너리를 `tools/bin/`에 내려받아 네이티브 엔진을 연동할 때:
```bash
python scripts/setup_craft_anything.py
# 또는 scripts\setup_craft_anything.bat 실행
```
*(바이너리가 없어도 자비스 내장 클린룸 엔진이 100% 동일한 파이프라인으로 작동합니다.)*

---

## 4. 파일 구조

- `automation/craft_anything.py`: 핵심 파이프라인 (Study, Build, Check, Refine)
- `scripts/setup_craft_anything.py`: 공식 릴리스 다운로드 및 툴체인 셋업
- `scripts/setup_craft_anything.bat`: 윈도우용 셋업 배치
- `JARVIS_CRAFT_ANYTHING.bat`: 윈도우 사용자용 1클릭 실행 배치
- `.claude/skills/craft-anything/`: Claude Code 및 자비스 멀티에이전트 스킬
- `landing_pages/`: 생성된 복제 페이지 및 유사도 검증 리포트(.json) 보관소
