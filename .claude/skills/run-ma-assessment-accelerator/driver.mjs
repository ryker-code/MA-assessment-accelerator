#!/usr/bin/env node
/**
 * Driver for M&A Assessment Accelerator web UI.
 *
 * Usage:
 *   node driver.mjs screenshot                          # screenshot home page
 *   node driver.mjs screenshot <assessment_id>          # screenshot results for existing assessment
 *   node driver.mjs list                                # list all assessments via API
 *   node driver.mjs health                              # check server health
 *
 * Screenshots land at /tmp/ma-driver/<name>.png
 * Requires: uvicorn already running on port 8000
 *           playwright installed at /tmp/node_modules/
 */

import { chromium } from '/tmp/node_modules/playwright/index.mjs';
import { mkdir } from 'node:fs/promises';

const BASE = 'http://localhost:8000';
const OUT  = '/tmp/ma-driver';

await mkdir(OUT, { recursive: true });

const [,, cmd, arg] = process.argv;

// ── health ────────────────────────────────────────────────────────────────────
if (!cmd || cmd === 'health') {
  const r = await fetch(`${BASE}/health`);
  console.log(await r.json());
  process.exit(r.ok ? 0 : 1);
}

// ── list ──────────────────────────────────────────────────────────────────────
if (cmd === 'list') {
  const r = await fetch(`${BASE}/assessments`);
  const assessments = await r.json();
  console.log(`${assessments.length} assessments:`);
  for (const a of assessments) {
    console.log(`  ${a.assessment_id}  ${a.overall_status.padEnd(20)}  ${a.buyer_company} → ${a.target_company}`);
  }
  process.exit(0);
}

// ── screenshot ────────────────────────────────────────────────────────────────
if (cmd === 'screenshot') {
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  if (!arg) {
    // Home page — just the form
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
    const out = `${OUT}/home.png`;
    await page.screenshot({ path: out });
    console.log(`Screenshot: ${out}`);
  } else {
    // Results view for a known assessment_id
    const id = arg;

    // The SPA uses a module-level `let currentAssessmentId` that isn't exposed on window.
    // When updateUI() fetches agent files it reads that local var, which stays null
    // when we inject state via window.*. Fix: intercept the resulting /null/ requests
    // and rewrite them to the real assessment ID.
    await page.route(`${BASE}/assessments/null/**`, async (route) => {
      const url = route.request().url().replace('/assessments/null/', `/assessments/${id}/`);
      const response = await page.context().request.fetch(url);
      await route.fulfill({ response });
    });

    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });

    await page.evaluate(async (id) => {
      window.currentAssessmentId = id;
      window.show('pipeline-section');
      window.hide('input-section');
      window.renderGrid({}, 'PHASE_1');
      const resp = await fetch(`/assessments/${id}`);
      const m = await resp.json();
      window.manifest = m;
      await window.updateUI(m);
      window.hide('pipeline-section');
    }, id);

    // Wait for all agent file fetches to settle
    await page.waitForTimeout(6000);

    const out = `${OUT}/results-${id.slice(0,8)}.png`;
    await page.screenshot({ path: out, fullPage: true });
    console.log(`Screenshot: ${out}`);

    // Print tab summary
    const tabs = await page.evaluate(() =>
      Array.from(document.querySelectorAll('#tabs-bar .tab')).map(t => t.textContent.trim())
    );
    console.log('Tabs rendered:', tabs.join(', '));
  }

  await browser.close();
  process.exit(0);
}

console.error(`Unknown command: ${cmd}`);
process.exit(1);
