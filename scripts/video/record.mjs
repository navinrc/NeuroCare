// Record the live simulator for the demo video (docs/submission/video-script.md).
//
//   cd scripts/video && npm install && node record.mjs
//
// Env: SIM_URL, DEMO_EMAIL, DEMO_PASSWORD_FILE, AWS_PROFILE (for Polly). One real take: every turn
// is a live /sim/turn call to the deployed stack. Writes out/sim.webm, out/events.json, out/slides/*.png.
// assemble.py then cuts the waits and lays the audio.

import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "yaml";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "out");
const SIM = (process.env.SIM_URL || "https://yxsw3xdvj2op5aqmtd3flcc4la0ntjzf.lambda-url.us-east-1.on.aws").replace(/\/$/, "");
const W = 1920, H = 1080;
const THINK_KEEP = 600; // ms of "thinking" kept before the cut
const GAP = 450; // ms of quiet after Alexa finishes

const shots = yaml.parse(readFileSync(join(HERE, "shots.yaml"), "utf8"));
const durations = JSON.parse(readFileSync(join(OUT, "durations.json"), "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ms = (id) => Math.round((durations[id] || 0) * 1000);

function alexaAudio(id, text) {
  const out = execFileSync("uv", ["run", "python", join(HERE, "tts.py"), "alexa", id, text], { encoding: "utf8" });
  return Math.round(parseFloat(out.trim().split("\n").pop()) * 1000);
}

async function link(browser) {
  const context = await browser.newContext({ viewport: { width: W, height: H } });
  const page = await context.newPage();
  await page.goto(`${SIM}/sim/link`);
  await page.locator('input[name="username"]:visible').fill(process.env.DEMO_EMAIL);
  await page.locator('input[name="password"]:visible').fill(readFileSync(process.env.DEMO_PASSWORD_FILE, "utf8").trim());
  await page.locator('input[name="signInSubmitButton"]:visible').click();
  await page.waitForURL((url) => url.origin === SIM && url.pathname === "/", { waitUntil: "load" });
  const state = await context.storageState();
  await context.close();
  return state;
}

async function slides(browser) {
  mkdirSync(join(OUT, "slides"), { recursive: true });
  const page = await browser.newPage({ viewport: { width: W, height: H } });
  const style = `<style>
    body{margin:0;width:${W}px;height:${H}px;background:radial-gradient(circle at 20% 0%,#1b2a4a 0%,#0b1220 60%);color:#eef2f8;
      font-family:"Helvetica Neue",Arial,sans-serif;display:flex;flex-direction:column;justify-content:center;padding:0 160px;box-sizing:border-box}
    h1{font-size:120px;font-weight:300;margin:0}
    h2{font-size:48px;font-weight:300;color:#19c3f0;margin:16px 0 0}
    ul{font-size:44px;font-weight:300;line-height:1.7;padding-left:40px;margin:40px 0 0}
    .tag{position:absolute;bottom:60px;left:160px;font-size:26px;color:#8fa0bd}
    img{max-width:100%;max-height:900px;align-self:center;border-radius:16px;background:#fff;padding:24px}
  </style>`;
  const tag = `<div class="tag">Amazon Developer Hackathon 2026 · Alexa+ track</div>`;
  const html = {
    title: `${style}<h1>${shots.slides.title.heading}</h1><h2>${shots.slides.title.sub}</h2>${tag}`,
    closing: `${style}<h1 style="font-size:96px">${shots.slides.closing.heading}</h1><ul>${shots.slides.closing.bullets.map((b) => `<li>${b}</li>`).join("")}</ul>${tag}`,
    architecture: `${style}<img src="data:image/png;base64,${readFileSync(join(HERE, "..", "..", shots.slides.architecture.image)).toString("base64")}">`,
  };
  for (const [name, body] of Object.entries(html)) {
    await page.setContent(body);
    await page.screenshot({ path: join(OUT, "slides", `${name}.png`) });
  }
  await page.close();
}

async function main() {
  const browser = await chromium.launch({ headless: true, channel: process.env.PW_CHANNEL || "chrome" });
  await slides(browser);
  const storageState = await link(browser);
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    storageState,
    recordVideo: { dir: join(OUT, "raw"), size: { width: W, height: H } },
  });
  const page = await context.newPage();
  const t0 = Date.now();
  const events = [];
  const at = () => Date.now() - t0;
  const event = (e) => { events.push({ t: at(), ...e }); console.log(JSON.stringify(events.at(-1))); };

  await page.goto(`${SIM}/?demo=1`);
  await page.waitForFunction(() => window.demo && document.getElementById("dot").classList.contains("on"), null, { timeout: 30000 });
  await sleep(1500);
  event({ type: "start" });

  for (const turn of shots.turns) {
    if (turn.dev_panel) {
      await page.evaluate(() => window.demo.devPanel(true));
      event({ type: "devpanel" });
      await page.evaluate(() => { const p = document.getElementById("panel"); p.scrollTo({ top: 0 }); });
      await sleep(1500);
      await page.evaluate(() => { const p = document.getElementById("panel"); p.scrollTo({ top: p.scrollHeight, behavior: "smooth" }); });
      await sleep(3500);
      continue;
    }
    event({ type: "listen", id: turn.id });
    await page.evaluate(([text, d]) => window.demo.listen(text, d), [turn.show || turn.say, ms(turn.id)]);
    event({ type: "think", id: turn.id });
    const reply = await page.evaluate((text) => window.demo.ask(text), turn.say);
    const replyMs = alexaAudio(`a_${turn.id}`, reply.reply);
    await page.evaluate((t) => window.demo.show(t), reply);
    event({ type: "speak", id: turn.id, audio: `a_${turn.id}`, reply: reply.reply, tools: reply.tool_calls.map((c) => [c.name, c.ms]) });
    await sleep(replyMs);
    await page.evaluate(() => window.demo.idle());
    await sleep(GAP);

    if (turn.reminder) {
      event({ type: "wait_reminder" });
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        await page.evaluate(() => window.demo.refresh());
        if ((await page.evaluate(() => window.demo.fired.length)) > 0) break;
        await sleep(1000);
      }
      const fired = await page.evaluate(() => window.demo.fired[0]);
      const text = `Here's your reminder. ${fired ? fired.text : "drink water"}.`;
      const remMs = alexaAudio("a_reminder", text);
      event({ type: "reminder", audio: "a_reminder", chime: true });
      await sleep(900 + remMs + 800);
      await page.evaluate(() => window.demo.ack());
      await sleep(400);
    }
    if (turn.after) {
      event({ type: "narrate", audio: `n_${turn.id}` });
      await sleep(ms(`n_${turn.id}`) + 400);
    }
  }
  await sleep(800);
  event({ type: "end" });
  const video = page.video();
  await context.close(); // finishes writing the recording
  await video.saveAs(join(OUT, "sim.webm"));
  await browser.close();
  writeFileSync(join(OUT, "events.json"), JSON.stringify({ think_keep: THINK_KEEP, events }, null, 1));
  console.log("done:", join(OUT, "sim.webm"));
}

main().catch((e) => { console.error(e); process.exit(1); });
