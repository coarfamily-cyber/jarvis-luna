@echo off
chcp 65001 > nul
title JARVIS LUNA - 9대 깃허브 트렌딩 AI 툴킷
cls
echo ===============================================================================
echo       🤖 JARVIS LUNA - 깃허브 1위~15위 트렌딩 AI 통합 툴킷 (9선)
echo ===============================================================================
echo  [1위]  Agent Desktop    - 마우스/키보드 점유 없는 백그라운드 PC 앱 조작 (Vercel)
echo  [3위]  Scrapling        - 클라우드플레어 우회 적응형 차세대 웹 크롤러 (93k★)
echo  [4위]  Hyprland         - 리눅스 관제용 유려한 타일링 윈도우 매니저 (10k★)
echo  [6위]  FreeToken        - 게이밍 노트북 로컬 GPU 초고속 추론 가속기 (16k★)
echo  [8위]  Kronos           - 차트 및 이커머스 시계열 가격/수요 예측 엔진 (46k★)
echo  [10위] Colibri          - SSD 오프로딩으로 저사양 PC에서 70B 초대형 모델 실행 (47k★)
echo  [12위] WorkTrunk        - 멀티 코딩 AI 동시 작업 Git Worktree 분기/병합기 (10k★)
echo  [14위] NanoChat         - 안드레이 카파시의 초경량 커스텀 로컬 ChatGPT (60k★)
echo  [15위] Heretic          - 상투어 및 거절 제거 직설형 비서실장 프롬프트 엔진 (38k★)
echo ===============================================================================
echo  [A] 통합 파이프라인 원클릭 실행 (Scrapling -> Kronos -> Heretic -> Desktop)
echo  [S] 전체 도구 환경 자동 셋업 및 의존성 설치
echo  [W] 웹 스튜디오 (HTML 대시보드) 열기
echo  [Q] 종료
echo ===============================================================================

set /p choice="실행할 메뉴 번호를 입력하세요 (1~15 / A / S / W / Q): "

if /i "%choice%"=="1" (
    echo [Agent Desktop 실행 중...]
    python automation/agent_desktop.py --app notepad --action write --payload "JARVIS Agent Desktop Test"
    pause
    goto :eof
)
if /i "%choice%"=="3" (
    set /p url="스크래핑할 상품/웹사이트 URL 입력: "
    python automation/scrapling_crawler.py --url "%url%"
    pause
    goto :eof
)
if /i "%choice%"=="6" (
    echo [FreeToken GPU 가속 실행...]
    python automation/local_ai_engines.py --engine freetoken --prompt "JARVIS Fast Inference Test"
    pause
    goto :eof
)
if /i "%choice%"=="8" (
    echo [Kronos 시계열 가격 예측 실행...]
    python automation/kronos_forecaster.py --days 7
    pause
    goto :eof
)
if /i "%choice%"=="10" (
    echo [Colibri SSD 초대형 모델 오프로드 실행...]
    python automation/local_ai_engines.py --engine colibri --prompt "JARVIS 70B Deep Analysis"
    pause
    goto :eof
)
if /i "%choice%"=="12" (
    echo [WorkTrunk 멀티에이전트 워크트리 현황...]
    python automation/worktrunk_manager.py list
    pause
    goto :eof
)
if /i "%choice%"=="14" (
    echo [NanoChat 로컬 소형 AI 실행...]
    python automation/local_ai_engines.py --engine nanochat --prompt "안녕하세요 자비스 나노"
    pause
    goto :eof
)
if /i "%choice%"=="15" (
    set /p prompt_text="보정할 시스템 프롬프트 또는 답변 입력: "
    python automation/heretic_filter.py --text "%prompt_text%" --mode clean
    pause
    goto :eof
)
if /i "%choice%"=="A" (
    set /p pipe_url="타겟 상품 URL (기본값 엔터): "
    if "%pipe_url%"=="" set pipe_url=https://daisomall.co.kr/pd/pdr/SCR_PDR_0001?pdNo=1045234
    python automation/trending_ai_orchestrator.py pipeline --url "%pipe_url%"
    pause
    goto :eof
)
if /i "%choice%"=="S" (
    echo [환경 자동 설정 실행...]
    python scripts/setup_trending_tools.py
    pause
    goto :eof
)
if /i "%choice%"=="W" (
    start index.html#trending-suite
    goto :eof
)
if /i "%choice%"=="Q" goto :eof
