# Blippo+ 한글 패치

Steam판 [Blippo+](https://store.steampowered.com/app/3323850/Blippo/)(블리포+)를 한국어로 바꿔 주는 **비공식 팬 패치**입니다.
자막, 에피소드 제목·설명, 펨토팩스 게시판, 메뉴까지 게임 안의 텍스트 7,696개를 번역했습니다.

**다운로드: [Releases에서 최신 버전 받기](https://github.com/Moooooomin/blippo-plus-ko/releases/latest)** (`Blippo-plus-ko-v1.1.zip`)

- 대상: **Windows Steam판** (맥·스위치·플레이데이트판은 지원하지 않습니다)
- 언어: 게임의 "유럽 스페인어" 자리에 한국어를 넣습니다
- 글꼴: 게임에 이미 들어 있는 픽셀 글꼴(GNU Unifont)로 한글을 표시합니다
- 영상·음성은 건드리지 않고 텍스트만 바꿉니다

## 설치 방법

1. Steam에서 Blippo+를 설치합니다.
2. 받은 zip 파일을 원하는 곳에 풉니다. (압축을 푼 뒤 실행하세요)
3. 게임이 켜져 있으면 완전히 종료합니다.
4. `Blippo+ 한글패치.exe`를 실행합니다.
5. 창 위쪽에 게임 폴더가 자동으로 잡혔는지 확인하고 **[한글 패치 설치]**를 누릅니다.
6. 5~15분 정도 걸립니다. 진행 막대가 끝날 때까지 창을 닫지 마세요.
7. 게임을 실행하고 **Options → Language → 한국어**를 선택합니다.

게임 폴더를 못 찾으면 **[찾아보기…]**로 직접 고르세요.
Steam 라이브러리 → Blippo+ 우클릭 → 관리 → 로컬 파일 보기에서 열리는 폴더가 게임 폴더입니다.

### "Windows의 PC 보호" 경고가 뜨면

개인이 만든 프로그램이라 코드 서명이 없어서 처음 실행할 때 파란 경고 창이 뜰 수 있습니다.
**[추가 정보] → [실행]**을 누르면 됩니다. 무엇을 하는 프로그램인지는 이 저장소의 [`src/`](src/) 코드에서 확인할 수 있습니다.

## 제거 방법

설치 프로그램에서 **[원본으로 되돌리기]**를 누르면 됩니다. 설치할 때 원본 파일을 `backup` 폴더에 저장해 두므로 그대로 복구됩니다.

`backup` 폴더를 지웠다면 Steam에서 되돌릴 수 있습니다:
Steam 라이브러리 → Blippo+ 우클릭 → 속성 → 설치된 파일 → 게임 파일 무결성 확인

## 알아두실 점

- 게임이 업데이트되면 패치가 지워집니다. 다시 설치하면 됩니다.
- 게임에 언어 버튼이 4개뿐이라 한국어 버튼을 새로 만들 수 없어서, **유럽 스페인어 자리를 한국어로 바꿔 씁니다.** 패치 후에는 유럽 스페인어를 쓸 수 없습니다. (다른 언어는 그대로입니다)
- 편성표의 긴 프로그램 제목은 칸을 넘으면 말줄임(…)으로 잘립니다. 한글이 영문보다 폭을 많이 차지해서 생기는 일이며, 원래 영문 긴 제목도 똑같이 잘립니다.
- Unifont는 16픽셀에서 획이 가장 또렷해서 편성표의 한글 크기를 16픽셀로 맞춰 두었습니다.
- 등장인물 이름과 펨토팩스 사용자 아이디는 원문(로마자)을 유지했습니다.

## 문제가 생기면

| 증상 | 해결 |
|---|---|
| 설치 중 오류가 납니다 | 게임이나 Steam이 파일을 쓰고 있을 수 있습니다. 게임을 완전히 종료하고 다시 시도하세요. 창 아래 기록에 오류 내용이 나옵니다. |
| 일부만 한국어로 나옵니다 | **[설치 확인]**을 눌러 보세요. 빠진 곳이 있으면 **[다시 설치]**로 채워집니다. |
| 번역을 직접 고치고 싶습니다 | `blippo_ko.json`의 `"ko"` 값을 고친 뒤 **[다시 설치]**를 누르면 됩니다. |

오역이나 어색한 문장, 설치 문제는 [Issues](https://github.com/Moooooomin/blippo-plus-ko/issues)로 알려 주세요. 전문 번역가가 아니라 혼자 작업한 번역이라 다듬을 곳이 있을 수 있습니다.

## 파이썬으로 직접 실행하기

설치 프로그램(exe)에 든 코드와 [`src/`](src/)의 코드는 같습니다. 파이썬이 있으면 명령줄로도 쓸 수 있습니다.

```bash
pip install UnityPy
python src/blippo_ko.py apply  -i blippo_ko.json --slot 14   # 설치
python src/blippo_ko.py verify -i blippo_ko.json --slot 14   # 확인
python src/blippo_ko.py restore                              # 되돌리기
```

게임 폴더를 자동으로 못 찾으면 `--game "게임 경로"`를 붙입니다. 원본 백업은 기본으로 스크립트 옆 `backup` 폴더에 저장됩니다(`--backup-dir`로 바꿀 수 있음).

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `blippo_ko.json` | 번역문. 항목마다 `asset`·`path`(게임 안 위치)와 `ko`(한국어)만 들어 있습니다 |
| `src/blippo_ko.py` | 실제로 게임 파일을 고치는 부분 (UnityPy) |
| `src/blippo_ko_gui.py` | 설치 프로그램 창 |

패치가 건드리는 게임 파일 (설치할 때 `backup` 폴더에 원본이 저장됩니다):

```
Blippo+_Data\StreamingAssets\aa\StandaloneWindows64\
    metadata_assets_all.bundle       텍스트 원본
    programguide_assets_all.bundle   편성표 글꼴/글자 크기
Blippo+_Data\StreamingAssets\aa\catalog.json
Blippo+_Data\sharedassets0.assets    자막·에피소드·크레딧
Blippo+_Data\sharedassets1.assets    메뉴 UI·펨토팩스
```

## 바뀐 점

**v1.1**
- 설치 프로그램을 창(GUI)으로 바꿨습니다.
- 에피소드 제목·설명 808개가 일부 화면에서 스페인어로 나오던 문제를 고쳤습니다.
- 번역문 다듬기: 영어식 문장 부호(줄표 —, 쌍반점 ;)를 한국어식으로, 대화 속 직역 대명사(그녀·당신 등)를 자연스럽게, 연결어미 뒤 쉼표 정리.
- [설치 확인] 기능 추가.
- 배포용 `blippo_ko.json`에서 게임 원문(영어)과 다른 언어 참고 번역을 뺐습니다. 설치 결과는 같습니다.

**v1.0**
- 첫 배포.

## 저작권과 라이선스

- Blippo+와 게임 안의 모든 원본 콘텐츠의 저작권은 원저작자에게 있습니다 (개발: YACHT, Telefantasy Studios, Noble Robot / 배급: Panic). 이 패치는 개발사·배급사와 관계없는 비공식 팬 작업입니다.
- 이 저장소와 배포 파일에는 게임 파일이나 게임 원문 텍스트가 들어 있지 않습니다. 정식으로 구매해 설치한 게임에 번역문을 덮어쓰는 도구와 번역문만 배포합니다.
- 한글 표시에 쓰는 GNU Unifont는 게임에 이미 들어 있는 글꼴이며, 이 패치가 배포하지 않습니다.
- `src/`의 코드는 [MIT 라이선스](LICENSE)입니다. 번역문(`blippo_ko.json`)은 원작에 딸린 2차적 저작물이라 MIT 라이선스 대상이 아닙니다.
- 개발사에서 배포 중단을 요청하면 즉시 따릅니다.

---

### English

An unofficial Korean fan translation for the **Windows Steam version** of [Blippo+](https://store.steampowered.com/app/3323850/Blippo/).
It translates all 7,696 in-game text entries (subtitles, episode titles and descriptions, the Femtofax board and menus) and renders Hangul with the game's built-in GNU Unifont.
Korean replaces the European Spanish slot, because the game's language menu has only four buttons.

Download the installer from [Releases](https://github.com/Moooooomin/blippo-plus-ko/releases/latest), unzip it, close the game, run `Blippo+ 한글패치.exe` and press **[한글 패치 설치]** (Install). Then pick **Options → Language → 한국어** in the game.
**[원본으로 되돌리기]** (Restore) puts the original files back, or use Steam's "Verify integrity of game files".

This repository contains no game files and none of the game's original text. Blippo+ and all original content belong to their creators (YACHT, Telefantasy Studios, Noble Robot; published by Panic). The code in `src/` is MIT-licensed; the translation is not. I will take this down on request from the developers.
