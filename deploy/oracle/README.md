# Oracle 배포 절차

## 1. 사전 확인

- `/opt` 아래 여유 디스크 10GB 이상
- 사용 가능 메모리 2GB 이상
- Docker Compose와 기존 외부 네트워크 `eventbot_proxy`
- `route.jamaifamily.duckdns.org` DNS가 Oracle 공인 IP를 가리킴
- GHCR 이미지를 읽을 수 있는 Docker 로그인

## 2. 이미지 게시

GitHub 저장소의 Actions secret에 `VITE_NAVER_MAP_CLIENT_ID`를 등록합니다. `main`에 push하면 다음 이미지가 `main` 및 커밋 SHA 태그로 게시됩니다.

- `ghcr.io/jamaica8612/route-difficulty-web`
- `ghcr.io/jamaica8612/route-difficulty-builder`

## 3. 스택 설치

저장소 루트에서 다음을 실행합니다.

```bash
sudo deploy/oracle/install-oracle.sh
sudoedit /opt/stacks/route-difficulty/builder.env
```

`builder.env`에는 교체한 공공데이터 인증키만 넣고 권한을 `0600`으로 유지합니다. `input/`에는 승인받아 내려받은 `TL_KODIS_BAS` 전체 파일과 공식 주소 DB를 배치합니다.

## 4. Caddy 연결

기존 Caddyfile에 `route-difficulty.caddy`의 사이트 블록을 추가한 뒤 설정을 검증하고 reload 합니다. 이 사이트에는 Basic 인증을 적용하지 않습니다.

```bash
sudo docker exec caddy caddy validate --config /etc/caddy/Caddyfile
sudo docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Caddy 컨테이너 이름과 설정 경로가 다르면 실제 운영 구성을 먼저 확인합니다.

## 5. 최초 기동과 자동 갱신

```bash
cd /opt/stacks/route-difficulty
sudo docker compose --env-file deploy.env pull web
sudo docker compose --env-file deploy.env up -d web
curl -fsS https://route.jamaifamily.duckdns.org/healthz
sudo systemctl enable --now route-difficulty-web.timer route-difficulty-data.timer
```

- 웹 타이머는 10분마다 새 이미지를 확인하고 라이브 health 검증에 실패하면 이전 이미지를 복구합니다.
- 데이터 타이머는 매일 03:30 이후 실행됩니다. 현재 월 자료가 완성될 때까지 일일 API 한도 안에서 이어받고, 검증된 릴리스만 활성화합니다.

## 6. 운영 검증

```bash
sudo docker compose --env-file deploy.env ps
systemctl list-timers 'route-difficulty-*'
curl -fsS https://route.jamaifamily.duckdns.org/healthz
curl -fsS https://route.jamaifamily.duckdns.org/data/manifest.json
curl -fsS https://eventbot.jamaifamily.duckdns.org/api/automation/health
```

마지막 확인은 새 앱 배포가 기존 EventBot 공개 서비스에 영향을 주지 않았는지 확인하기 위한 것입니다.
