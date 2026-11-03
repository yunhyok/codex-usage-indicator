# Codex Usage Indicator 0.2.1

Windows 알림 영역에서 Codex 사용량 제한의 남은 비율과 추가 크레딧 잔액을 확인하는 트레이 앱입니다.

- 바깥 링: 기본 Codex 제한의 `primary` 구간
- 안쪽 링: `secondary` 구간(있을 때만 표시)
- 밝은 부분: 남은 비율
- 어두운 부분: 사용한 비율
- 마우스 오버: 추가 크레딧 잔액, 남은 비율과 초기화 시각
- 왼쪽 클릭: 모든 Codex/모델별 제한 상세와 추가 크레딧 잔액

추가 크레딧 잔액은 Codex App Server가 `credits.balance`를 제공하는 계정에서 트레이 툴팁과 상세 정보 창에 표시됩니다. 이 값은 Codex가 제공하는 계정 또는 워크스페이스 크레딧 상태이며, 구매 크레딧, 자동 충전 크레딧 또는 공유 워크스페이스 크레딧일 수 있습니다. 프로토콜에는 구매 경로나 통화 단위 필드가 없으므로 앱은 현금, KRW 또는 USD 잔액으로 단정하지 않습니다. 응답 상태에 따라 잔액, 무제한, 크레딧 없음, 잔액 미상 또는 정보 없음으로 표시될 수 있습니다.

앱 이름과 버전은 툴팁, 상세 창, 정보 창에서 항상 확인할 수 있습니다.

## 개인정보와 인증

이 앱은 API 키나 ChatGPT 인증 토큰을 읽거나 저장하지 않습니다. 로컬에 설치된 Codex의 공식 App Server가 이미 사용 중인 로그인 상태를 재사용하며, `account/rateLimits/read` 응답과 `account/rateLimits/updated` 알림만 처리합니다. 앱은 이 데이터에 포함된 사용률, 초기화 시각 및 추가 크레딧 상태와 잔액을 표시합니다.

로컬 캐시에는 App Server 응답에서 선별한 제한 이름, 사용률, 초기화 시각, 플랜 유형, 추가 크레딧 상태와 잔액, 마지막 갱신 시각만 저장합니다. API 키, 인증 토큰, 이메일 주소는 캐시에 포함하지 않습니다.

Codex에 로그인되어 있지 않거나 호환되는 Codex CLI를 찾지 못하면 마지막 정상 값을 오래된 값으로 표시하고 트레이 아이콘에 경고 상태를 표시합니다.

## 설치

GitHub Release의 `CodexUsageIndicatorSetup-0.2.1.exe`를 실행합니다. 기본 위치는 Program Files이며 설치 화면에서 다른 폴더를 선택할 수 있습니다. Windows 로그인 시 자동 시작 옵션은 기본으로 선택됩니다.

현재 설치 파일은 코드 서명 인증서가 없어 미서명 상태이며 Windows SmartScreen 경고가 나타날 수 있습니다.

## 개발 실행

```powershell
python -m pip install -e ".[dev]"
python -m codex_usage_indicator
```

## 테스트와 빌드

```powershell
python -m pytest -q
powershell.exe -ExecutionPolicy Bypass -NoProfile -File .\scripts\build_installer.ps1
```

빌드에는 PyInstaller와 Inno Setup 6이 필요합니다. 설치 프로그램과 SHA-256 체크섬은 `dist` 폴더에 생성됩니다.

## 트레이 메뉴

- 새로 고침
- 상세 정보
- Windows 시작 시 실행
- 로그 폴더 열기
- 정보
- 종료
