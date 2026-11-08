@echo off
chcp 65001 > nul
title JARVIS LUNA - Craft Anything 웹 복제 엔진
echo ============================================================
echo   JARVIS LUNA - Craft Anything 고속 클린룸 웹 복제 자동화
echo ============================================================
echo.
echo [안내] 복제 및 분석할 대상 웹사이트 주소를 입력해 주세요.
echo 예시: https://apple.com, https://daiso.co.kr, 경쟁사 쇼피파이 주소
echo.
set /p TARGET_URL="타겟 웹사이트 URL 입력: "

if "%TARGET_URL%"=="" (
    echo [오류] URL이 입력되지 않았습니다. 종료합니다.
    pause
    exit /b
)

echo.
echo [안내] 복제 목적 또는 프롬프트를 입력하세요 (기본값: 쇼피파이 상세페이지 반응형 복제):
set /p USER_PROMPT="프롬프트 입력 [엔터시 기본값]: "
if "%USER_PROMPT%"=="" set USER_PROMPT=쇼피파이 상세페이지 반응형 복제

echo.
echo [실행] 자비스 크래프트 애니싱 파이프라인 가동 (Study - Build - Check - Refine)...
python automation\craft_anything.py rebuild "%TARGET_URL%" --prompt "%USER_PROMPT%"

echo.
echo ============================================================
echo   작업 완료! landing_pages 폴더의 결과물을 확인하세요.
echo ============================================================
pause
