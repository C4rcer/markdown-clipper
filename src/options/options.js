import { wireSupportLinks } from "../shared/support.js";

const Settings = globalThis.ExcerptSettings;
const $ = (id) => document.getElementById(id);
const RADIOS = ["headingStyle", "bullet", "linkStyle", "quickAction"];
const CHECKS = ["images", "titleHeading", "frontMatter"];
let saveTimer = 0;

async function load() {
  const settings = await Settings.load();
  for (const name of RADIOS) {
    for (const input of document.querySelectorAll(`input[name="${name}"]`)) input.checked = input.value === settings[name];
  }
  for (const id of CHECKS) $(id).checked = settings[id];
  // Leave the box alone while the user is typing in it.
  if (document.activeElement !== $("template")) $("template").value = settings.frontMatterTemplate;
  $("templateReset").disabled = settings.frontMatterTemplate === Settings.DEFAULT_TEMPLATE;
}

function saveTemplate() {
  clearTimeout(saveTimer);
  saveTimer = 0;
  $("templateState").textContent = "Saved";
  return Settings.save({ frontMatterTemplate: $("template").value });
}

wireSupportLinks();

for (const [name, what] of Settings.PLACEHOLDERS) {
  const dt = document.createElement("dt");
  dt.textContent = "{" + name + "}";
  const dd = document.createElement("dd");
  dd.textContent = what;
  $("placeholders").append(dt, dd);
}
$("template").maxLength = Settings.TEMPLATE_MAX;

document.addEventListener("change", (e) => {
  const input = e.target;
  if (input.type === "radio" && RADIOS.includes(input.name)) Settings.save({ [input.name]: input.value });
  else if (input.type === "checkbox" && CHECKS.includes(input.id)) Settings.save({ [input.id]: input.checked });
});

$("template").addEventListener("input", () => {
  $("templateState").textContent = "";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveTemplate, 400);
});
$("template").addEventListener("blur", () => {
  if (saveTimer) saveTemplate();
});
$("templateReset").addEventListener("click", async () => {
  clearTimeout(saveTimer);
  saveTimer = 0;
  $("template").value = Settings.DEFAULT_TEMPLATE;
  await Settings.save({ frontMatterTemplate: Settings.DEFAULT_TEMPLATE });
  $("templateState").textContent = "Back to the default";
});

browser.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.settings) load();
});

if (browser.commands) {
  browser.commands.getAll().then((all) => {
    const cmd = all.find((c) => c.name === "clip");
    if (cmd && cmd.shortcut) $("shortcut").textContent = cmd.shortcut;
  }, () => {});
}

load();
