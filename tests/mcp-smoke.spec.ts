import { expect, test } from '@playwright/test';

test('Playwright test runner smoke check', async ({ page }) => {
  await page.setContent(`
    <main>
      <h1 data-testid="title">Playwright MCP Ready</h1>
      <button id="btn">Click me</button>
      <p id="count">0</p>
      <script>
        let c = 0;
        document.getElementById('btn').addEventListener('click', () => {
          c += 1;
          document.getElementById('count').textContent = String(c);
        });
      </script>
    </main>
  `);

  await expect(page.getByTestId('title')).toHaveText('Playwright MCP Ready');
  await page.locator('#btn').click();
  await expect(page.locator('#count')).toHaveText('1');
});
