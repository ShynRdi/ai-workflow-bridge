import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_smoke_test_is_explicit_single_turn_and_no_retry_loop():
    script = (EXT / "provider-smoke.js").read_text(encoding="utf-8")
    assert "AWB_SMOKE_OK" in script
    assert 'type: "SEND_TO_LLM"' in script
    assert "No retries or fallback" in script
    assert "No retry was attempted" in script
    assert "setInterval" not in script


def test_smoke_test_is_wired_into_sidepanel():
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert 'id="providerSmokeTest"' in html
    assert 'id="providerSmokeStatus"' in html
    assert '<script src="provider-smoke.js"></script>' in html


def test_extension_version_04_and_permissions_remain_optional():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.4"
    assert manifest.get("host_permissions") == []
    assert "cookies" not in manifest.get("permissions", [])


def test_read_only_provider_safety_inspection_does_not_send_or_bind():
    import subprocess

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const nodes = new Map();
const get = id => {
  if (!nodes.has(id)) nodes.set(id, {
    addEventListener(type, fn) { this[type] = fn; },
  });
  return nodes.get(id);
};
let tab = {id: 7, url: "https://chat.z.ai/"};
let permitted = true;
let inspections = 0;
const document = {body: {innerText: ""}, querySelectorAll: () => []};
const state = {lifecycle: "paused"};
const context = vm.createContext({
  $: get, document, lastState: state, URL,
  effectiveProvider: async () => ({id:"glm", name:"Z.ai / GLM", origins:["https://chat.z.ai/*"]}),
  utils: {detectProvider: host => host === "chat.z.ai" ? {id:"glm"} : null},
  addLog: () => {},
  chrome: {
    permissions: {contains: async () => permitted},
    tabs: {query: async () => [tab]},
    scripting: {executeScript: async ({target, func, args}) => {
      assert.equal(target.tabId, 7);
      inspections++;
      return [{result: func(...args)}];
    }}
  }
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
(async () => {
  const check = get("checkProviderSafety").click;
  const output = get("providerSafetyResult");
  document.body.innerText = "Please complete security verification\nPlease drag the slider to complete the puzzle";
  await check();
  assert.match(output.textContent, /WARNING.*auth_challenge/);
  document.body.innerText = "";
  await check();
  assert.match(output.textContent, /INCONCLUSIVE.*not clearance/);
  tab = {id: 7, url: "https://example.com/"};
  await check();
  assert.match(output.textContent, /UNKNOWN/);
  tab = {id: 7, url: "https://chat.z.ai/"};
  permitted = false;
  await check();
  assert.match(output.textContent, /UNKNOWN/);
  permitted = true;
  state.lifecycle = "planning";
  await check();
  assert.match(output.textContent, /UNKNOWN/);
  assert.equal(inspections, 2);
  assert.equal(get("checkProviderSafety").disabled, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        ["node", "-e", script, str(EXT / "provider-safety-diagnostics.js")],
        check=True,
    )
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert 'id="checkProviderSafety"' in html
    assert 'src="provider-safety-diagnostics.js"' in html
