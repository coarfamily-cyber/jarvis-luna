# 🚀 JARVIS LUNA - 9대 깃허브 트렌딩 AI 툴킷 적용 가이드

본 문서는 유튜브 영상(민둥이 | 쉽게 배우는 AI, `HVe256dh9Ls`)에서 소개된 **깃허브 1위~15위 핵심 오픈소스 9종**을 자비스 루나(JARVIS LUNA) 자동화 파이프라인에 체계적으로 연동한 구조와 실전 활용법을 정리한 공식 가이드입니다.

---

## 📊 9대 트렌딩 AI 도구 요약 및 자비스 루나 적용 현황

| 순위 | 도구명 | 깃허브 원본 레포 | 별점 | 핵심 기능 | 자비스 루나 적용 및 역할 |
|:---:|:---|:---|:---:|:---|:---|
| **1위** | **Agent Desktop** | `vercel-labs/agent-desktop` | 11,000+ | 마우스/키보드 점유 없는 백그라운드 OS 앱 제어 | `automation/agent_desktop.py` - PC 사용 중 백그라운드 엑셀·메모·브라우저 상품 등록 자동화 |
| **3위** | **Scrapling** | `D4Vinci/Scrapling` | 93,000+ | 클라우드플레어 우회 & 레이아웃 변경 적응형 웹 스크래퍼 | `automation/scrapling_crawler.py` - 다이소·올리브영·네이버·아마존 봇 차단 없는 고속 상품 수집 |
| **4위** | **Hyprland** | `hyprwm/Hyprland` | 10,000+ | 리눅스 유려한 타일링 윈도우 매니저 (애니메이션/반투명) | `config/hyprland-jarvis.conf` - 리눅스 환경 관제실 멀티모니터 타일링 대시보드 프리셋 |
| **6위** | **FreeToken** | `FlashML-org/FreeToken` | 16,000+ | 8GB 게이밍 노트북 GPU 메모리 최적화 초고속 로컬 추론 | `automation/local_ai_engines.py` (freetoken) - 로컬 GPU 가속 및 Claude Code/자비스 고속 응답 |
| **8위** | **Kronos** | `shiyu-coder/Kronos` | 46,000+ | 금융 차트 및 시계열 패턴 예측 AI | `automation/kronos_forecaster.py` - 이커머스 상품 가격 추이, 마진, 수요 변동 7일~30일 예측 |
| **10위** | **Colibri** | `JustVugg/colibri` | 47,000+ | SSD 레이어 오프로딩으로 일반 PC에서 70B 초대형 LLM 구동 | `automation/local_ai_engines.py` (colibri) - 고가 GPU 서버 없이 SSD 기반 초대형 모델 오프라인 분석 |
| **12위** | **WorkTrunk** | `max-sixty/worktrunk` | 10,000+ | 멀티 코딩 AI 동시 작업 Git Worktree 분기/병합기 | `automation/worktrunk_manager.py` - 자비스 멀티에이전트(루나/비서실장/카피라이터) 파일 덮어쓰기 방지 |
| **14위** | **NanoChat** | `karpathy/nanochat` | 60,000+ | 안드레이 카파시의 초경량 커스텀 소형 LLM 학습/서빙 | `automation/local_ai_engines.py` (nanochat) - 외부 API 의존 없는 자비스 자체 경량 챗봇 모듈 |
| **15위** | **Heretic** | `p-e-w/heretic` | 38,000+ | AI 거절 제거 및 상투어/맞장구 말투 억제 가중치 튜너 | `automation/heretic_filter.py` - 상투적 군더더기 없는 직설적이고 명확한 비서실장 실행 모드 |

---

## 🛠️ 실전 실행 방법

### 1. 윈도우 원클릭 배치 파일
저장소 루트의 `JARVIS_TRENDING_AI_SUITE.bat` 파일을 더블클릭하면 9개 도구 개별 실행, 통합 파이프라인, 환경 점검을 손쉽게 수행할 수 있습니다.

### 2. 통합 파이프라인 (Composite Pipeline)
스크래핑(Scrapling) ➔ 가격 예측(Kronos) ➔ 카피 최적화(Heretic) ➔ 백그라운드 기록(Agent Desktop)을 한 번에 실행합니다:
```bash
python automation/trending_ai_orchestrator.py pipeline --url "https://daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1045234"
```

### 3. 개별 모듈 실행 예시
- **Scrapling 봇 차단 우회 수집**:
  ```bash
  python automation/scrapling_crawler.py --url "https://brand.naver.com/..."
  ```
- **Agent Desktop 백그라운드 작업**:
  ```bash
  python automation/agent_desktop.py --app notepad --action write --payload "다이소 신규 상품 등록 완료"
  ```
- **WorkTrunk 멀티에이전트 워크트리**:
  ```bash
  python automation/worktrunk_manager.py list
  python automation/worktrunk_manager.py create --agent agent-copywriter
  ```
- **Kronos 시계열 가격 예측**:
  ```bash
  python automation/kronos_forecaster.py --days 14 --prices 15000 15200 15100 15800 16000
  ```
- **Heretic 직설형 프롬프트 교정**:
  ```bash
  python automation/heretic_filter.py --text "안녕하세요! 질문해 주셔서 감사합니다..." --mode clean
  ```

---

## 🌐 자비스 웹사이트 대시보드 (`index.html`) 연동
자비스 공식 사이트(`index.html`) 상단 메뉴 및 대시보드에 **🔥 Trending AI Suite** 인터페이스가 통합되어 있어, 웹 브라우저나 모바일에서도 각 도구의 동작을 직관적으로 확인하고 시뮬레이션할 수 있습니다.
