# Playwright + MCP 설정 (Windows 11)

## 1) 준비

- Node.js 18+ 설치
- VS Code 확장: `Playwright Test for VS Code` 설치

## 2) 프로젝트 설치

```powershell
npm install
npm run pw:install
```

## 3) 테스트 실행

```powershell
npm run test:e2e
```

## 4) VS Code에서 실행

- 테스트 탐색기(Testing)에서 `mcp-smoke.spec.ts` 실행
- 확장이 `playwright.config.ts`를 자동 인식

## 5) MCP 서버 확인

이 저장소의 `.mcp.json`에는 아래 설정이 포함되어 있습니다.

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

직접 실행 확인:

```powershell
npm run mcp:playwright -- --help
```

위 명령이 정상 출력되면 Playwright MCP 커맨드가 로컬에서 실행 가능한 상태입니다.
