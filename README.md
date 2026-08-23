# 구역판독

우편번호를 입력하면 건축물대장과 K-apt의 공식 건물정보를 우편구역 단위로 확인하는 공개 웹앱입니다.

## 제품 원칙

- 로그인과 고객정보 입력이 없습니다.
- 종합 난이도 점수를 만들지 않습니다.
- 값이 없는 경우 `0`으로 바꾸지 않고 `확인 불가`로 표시합니다.
- `승강기 0대·지상 4층 이상`, `세대당 주차 0.5대 미만`, `5개 동 이상`의 공개 조건만 별도로 표시합니다.
- 도로 폭, 막다른 길, 후진 출차 여부는 1차 데이터에 포함하지 않습니다.

## 로컬 실행

```bash
npm install
npm run dev
```

네이버 지도 없이도 공식 우편경계 미리보기가 표시됩니다. 네이버 지도를 사용하려면 `.env`의 `VITE_NAVER_MAP_CLIENT_ID`에 Maps 애플리케이션의 `ncpKeyId`를 설정하고 공개 도메인을 허용 도메인에 등록합니다.

## 검증

```bash
npm run lint
npm test
npm run build
python -m pip install -r scripts/requirements-data.txt
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/build_dataset.py validate
```

## 데이터 생성

서버 전용 `.env`에 다음 세 API와 인증키를 설정합니다.

- `AptListService3/getSidoAptList3`
- `AptBasisInfoServiceV4/getAphusBassInfoV4`, `getAphusDtlInfoV4`
- `BldRgstHubService/getBrTitleInfo`

공식 원본은 아래 위치에 둡니다.

```text
data/input/
├── TL_KODIS_BAS.shp     # 같은 이름의 dbf, shx, prj 포함
└── address/              # 우편번호와 도로명 건물키가 있는 공식 CSV/TXT
```

처음에는 다음 순서로 실행합니다.

```bash
python scripts/build_dataset.py prepare-address-index
python scripts/build_dataset.py collect-apt-list
python scripts/build_dataset.py collect-apt-details
python scripts/build_dataset.py collect-building-hub
python scripts/build_dataset.py build
python scripts/build_dataset.py validate
```

수집 결과와 API 응답 캐시는 `data/work/cycles/YYYY-MM`에 월별로 저장됩니다. 일일 한도에 도달하면 종료코드 `75`로 멈추며 다음 실행에서 이어집니다. 완성된 달은 다시 만들지 않고, 다음 달이 되면 새 작업공간에서 최신 API 응답을 수집합니다. 게시 파일은 다음 계약을 사용합니다.

```text
/data/manifest.json
/data/releases/{datasetVersion}/zones/{postcode 앞 2자리}/{postcode}.json
```

새 릴리스 전체를 검증한 뒤에만 `manifest.json`이 원자적으로 교체되므로 실패한 배치는 현재 공개 자료에 영향을 주지 않습니다.

## 오라클 배포

운영 스택은 `/opt/stacks/route-difficulty`를 사용하며 EventBot 컨테이너와 별도로 실행됩니다. 자세한 설치·검증 순서는 [deploy/oracle/README.md](deploy/oracle/README.md)에 있습니다.
