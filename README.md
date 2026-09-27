# 세판뷰어 (Sepan Viewer)

[DJMAX RESPECT V](https://store.steampowered.com/agecheck/app/960170/)의 세부판정 인디케이터 레이아웃을 OBS Studio용으로 출력하는 프로그램입니다.
범용적이고 정확한 툴보다, 복기를 통한 실력 증진을 돕는 레니저 역할을 지향합니다.

[예시 영상 보기](https://www.youtube.com/watch?v=be2ie5e_9og)

## 사용법

1. **Windows 11**에서 **Python 3.12 Windows x64**를 설치하세요. 설치 시 Python Launcher도 포함해 주세요.
2. 이 저장소의 **Code → Download ZIP**으로 내려받아 압축을 풀고, `install.bat`를 실행하세요. 최초 설치에는 인터넷 연결이 필요합니다.
3. 게임을 **1920×1080, 전체 창 모드**로 실행하고 아래 옵션을 사용해 주세요.
   - **센터기어 / 레인 불투명도 100% / 그코노트 / 트리거 및 사이드 기본색상**
   - 콤보, 판정폰트, 키빔 등 레인 내의 오브젝트가 너무 강하면 정확도가 떨어질 수 있습니다.
4. `config.ini`를 열고 `[4LANE]`, `[5LANE]`, `[6LANE]`에서 해당하는 키를 설정해 주세요.
   - **L/R은 트리거, A/B는 사이드**입니다. **8버튼은 `[6LANE]`의 설정값**을 사용합니다.
   - 5레인 중앙 키 두 개는 `3a`, `3b`로 지정합니다.
   - 기능키 이름은 [여기](https://www.autohotkey.com/docs/v1/KeyList.htm)를 참고하세요.
5. `[general]`에서 `triggerColor=default`, `sideColor=default`로 설정하세요. 커스텀 색상을 사용한다면 아래 색상 설정 표를 참고하세요.
6. `start.bat`를 실행하고 드롭다운에서 게임 창을 선택한 뒤 **시작**을 누르세요. 게임으로 돌아가 플레이합니다. 게임 화면 위에 다른 창이 겹치지 않도록 해 주세요.
7. OBS Studio에서 **브라우저 소스**를 추가하고 아래와 같이 설정하세요.
   - URL: `http://127.0.0.1:8765/` — 프로그램의 **주소 복사** 버튼으로도 복사할 수 있습니다.
   - 너비: **51px** / 높이: **301px** (`maxWindow=150` 기준)
   - 높이는 항상 **`maxWindow × 2 + 1`**입니다. 배경은 투명합니다.
8. 판정 표기가 위로 튈 경우 `[general]`의 `globalOffset`을 낮은 값으로 조절하세요. 아래로 튈 경우에는 높은 값으로 조절하세요.
9. 설정 파일을 저장한 뒤 **config.ini 적용**을 누르면 변경 사항이 반영됩니다.

## 노트 색상 설정

`config.ini`의 `[general]`에서 게임 내 색상에 맞게 선택하세요.

| 설정 | 대응하는 게임 내 색상 |
|---|---|
| `triggerColor=default` | 트리거 기본색 |
| `triggerColor=orange` | 트리거 custom RGB **(234,140,103)** |
| `sideColor=default` | 사이드 기본색 |
| `sideColor=teal` | 사이드 custom RGB **(124,222,239)** |

동봉 설정은 두 항목 모두 `default`입니다. 이전 설정 파일에서 항목을 생략하면 기존 동작을 유지하도록 트리거는 `orange`, 사이드는 `teal`로 처리합니다. 저장 후 **config.ini 적용**을 누르면 캡처가 자동으로 재시작됩니다.

## 주요 설정

- `[general]`의 `fps`: 캡처 빈도. 기본값은 `12`입니다.
- `[general]`의 `maxWindow`: 입력과 노트를 연결하는 최대 시간 차이(ms). 기본값은 `150`입니다.
- `[customization]`: 타이밍 임계값과 early/late 색상을 설정합니다.
- `[viewer]`의 `opacityStep`: 표시가 사라질 때까지의 후속 입력 횟수. 기본값 `20`에서는 입력마다 불투명도가 5%p씩 감소합니다. 대응 노트가 없는 입력도 기존 표시를 흐리게 합니다.

## 테스트

설치 후 프로젝트 폴더에서 실행하세요.

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

예시 이미지·영상과 테스트를 포함한 전체 배포본입니다. 기본 트리거·사이드 설정은 모두 `default`입니다. 자세한 설명은 [MANUAL.md](MANUAL.md)를 참고하세요.
