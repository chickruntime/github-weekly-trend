# 설정 가이드

`README.md`는 매주 자동으로 다시 생성되므로, 사람이 읽는 설명은 이 파일에 둡니다.

## 동작 방식

매주 월요일 09:00 KST에 GitHub Actions(`.github/workflows/weekly.yml`)가 다음을 실행합니다.

1. `github.com/trending?since=weekly`를 스크래핑해 **종합 Top 10**을 뽑습니다. 실패하면 Search API로 대체합니다.
2. `config.yaml`의 카테고리마다 언어별 트렌딩 페이지와 토픽 검색으로 후보를 모읍니다.
3. Claude(Haiku)가 카테고리별로 최대 5개, 추가 추천을 최대 5개 고르고, 각 레포의 README를 한국어로 요약합니다.
4. `weekly/YYYY-Www.md`, `README.md`, `data/history.json`, `data/latest.json`을 커밋하고 push합니다.
5. Slack으로 요약 메시지를 보냅니다. 실패하면 실패 알림을 보냅니다.

한 레포는 리포트 안에서 한 번만 나옵니다. 지난주에 이미 소개한 레포는 카테고리와 추가 추천에서 빠지고, Top 10에서는 `🔁 N주 연속` 표시와 함께 짧게 소개됩니다.

## 1. Claude 인증 (A 또는 B 중 하나)

### A. Workload Identity Federation (권장, 저장되는 키 없음)

Claude Console → Workload identity → Connect workload → GitHub Actions 마법사로 생성합니다.
연동 규칙의 subject는 `repo:chickruntime/github-weekly-trend:ref:refs/heads/main`, audience는 `https://api.anthropic.com`입니다.
그다음 레포 **Settings → Secrets and variables → Actions → Variables** 탭에 아래 3개를 등록합니다. 식별자일 뿐 비밀 값은 아닙니다.

| Variable | 값 |
|---|---|
| `ANTHROPIC_ORGANIZATION_ID` | 조직 페이지의 UUID |
| `ANTHROPIC_SERVICE_ACCOUNT_ID` | `svac_...` |
| `ANTHROPIC_FEDERATION_RULE_ID` | `fdrl_...` |

실행 중에는 GitHub OIDC 토큰이 약 5분마다 만료되므로, `trend/wif.py`가 3분마다 새 토큰을 받아옵니다.
인증이 실패하면 Console의 Workload identity → 인증 기록 탭에서 거부 사유를 볼 수 있습니다.

### B. API 키

1. https://console.anthropic.com 에서 가입하고 **Billing**에서 크레딧을 충전합니다.
2. **Limits**에서 월 지출 한도를 낮게 설정합니다(예: $5). 예상 비용은 월 $1 미만입니다.
3. **API Keys**에서 이 프로젝트 전용 키를 새로 만듭니다.
4. GitHub 레포의 **Settings → Secrets and variables → Actions → New repository secret**에서
   이름은 `ANTHROPIC_API_KEY`, 값은 발급받은 키로 등록합니다.

키가 없으면 LLM 없이 실행되고, 리포트에 경고가 표시되며 요약 대신 레포 설명이 들어갑니다.

## 2. Slack Incoming Webhook

1. https://api.slack.com/apps 에서 **Create New App → From scratch**를 선택하고 워크스페이스를 고릅니다.
2. 왼쪽 메뉴 **Incoming Webhooks**에서 **Activate**를 켭니다.
3. **Add New Webhook to Workspace**를 누르고 메시지를 받을 채널을 선택합니다.
4. 생성된 `https://hooks.slack.com/services/...` URL을 GitHub Secret `SLACK_WEBHOOK_URL`로 등록합니다.

등록하지 않으면 Slack 단계는 건너뜁니다. URL이 유출되면 Slack 앱 설정에서 해당 웹훅을 삭제하고 새로 만드세요.

## 3. 수동 실행

**Actions → weekly-trend → Run workflow**를 누르면 바로 실행됩니다. 같은 주에 다시 실행하면 그 주 파일을 덮어씁니다.

## 로컬 실행

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
# 드라이런: LLM 없이, 레포 밖 임시 폴더에 출력
GITHUB_TOKEN=$(gh auth token) .venv/bin/python -m trend.main --no-llm --out /tmp/trend-dry
```

## 카테고리 수정

`config.yaml`의 `categories`에서 항목을 고치거나 추가합니다.

- `languages`: `github.com/trending/<언어>`에 쓰이는 슬러그입니다. C#은 `c%23`으로 씁니다.
- `topics`: GitHub 토픽입니다. 최근 `topic_created_within_days`일 안에 생성된 레포를 스타순으로 가져옵니다.
- `description`: Claude가 레포를 이 카테고리로 분류할 때 기준으로 쓰는 정의입니다.

## 보안 메모

- 워크플로 트리거는 `schedule`과 `workflow_dispatch`뿐입니다. 외부 PR로는 Secret이 노출되지 않습니다.
- 사용하는 Action은 커밋 SHA로 고정했고, 토큰 권한은 `contents: write` 하나뿐입니다.
- README는 신뢰할 수 없는 입력으로 취급합니다. Claude는 도구 없이 텍스트만 반환하고, 출력에서 링크와 HTML을 제거합니다.
