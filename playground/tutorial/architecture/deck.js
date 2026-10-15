// Builds architecture.pptx: how dossier is built, what it does, and what could
// come next. Each slide's speaker notes are its narration, which narrate.py
// speaks over the slide to make architecture.mp4.
//
//     npm install          # once, in this folder
//     node deck.js         # -> architecture.pptx
//
// The figures on slide 3 are counted from the repository when the deck is
// built, so they cannot fall behind it. Nothing here is part of dossier.

const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT = path.join(__dirname, "architecture.pptx");

// --------------------------------------------------------------------------- theme

const THEME = {
  name: "dossier",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2430", // ink
    lt1: "FFFFFF",
    dk2: "12343B", // deep teal, the dark slides
    lt2: "EEF3F2", // the cards on light slides
    accent1: "1F6F78", // teal
    accent2: "D99A3D", // amber, the seal
    accent3: "B84A3A", // brick, for what is refused
    accent4: "5E8C64", // sage, for what holds
    accent5: "5B6B7A", // slate
    accent6: "A9C4C0",
    hlink: "1F6F78",
    folHlink: "5B6B7A",
  },
};
const HEX = THEME.colors;
const MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "dossier: architecture, features and what comes next";
pres.author = "dossier-audit";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333;
const M = 0.6; // side margin
const CW = W - 2 * M; // content width

// --------------------------------------------------------------------------- figures

function countRules() {
  const specs = fs.readdirSync(path.join(ROOT, "specs")).filter((f) => /^\d{3}-.*\.md$/.test(f));
  let rules = 0;
  for (const f of specs) {
    const text = fs.readFileSync(path.join(ROOT, "specs", f), "utf8");
    rules += (text.match(/^### R\d+\.\d+ /gm) || []).length;
  }
  return { specs: specs.length, rules };
}

function countFiles(dir, pattern) {
  let n = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "__pycache__") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) n += countFiles(full, pattern);
    else if (pattern.test(entry.name)) n += 1;
  }
  return n;
}

const { specs: SPECS, rules: RULES } = countRules();
const TESTS = countFiles(path.join(ROOT, "tests"), /^test_.*\.py$/);
const EXERCISES = fs.readdirSync(path.join(ROOT, "playground")).filter((f) => /^\d{2}-/.test(f)).length;

// --------------------------------------------------------------------------- icons

const iconCache = new Map();
async function icon(name, hex) {
  const key = `${name}:${hex}`;
  if (!iconCache.has(key)) {
    const svg = ReactDOMServer.renderToStaticMarkup(
      React.createElement(fa[name], { color: `#${hex}`, size: 256 })
    );
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    iconCache.set(key, "image/png;base64," + png.toString("base64"));
  }
  return iconCache.get(key);
}

// An icon in a filled circle: the deck's one motif.
async function badge(slide, name, x, y, d, { fill = C.accent1, glyph = HEX.lt1, id } = {}) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: `${id || name} badge` });
  const pad = d * 0.25;
  slide.addImage({ data: await icon(name, glyph), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, objectName: `${id || name} icon` });
}

// --------------------------------------------------------------------------- layouts

pres.defineSlideMaster({
  title: "Title",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: M, y: 1.7, w: CW, h: 0.5, fontSize: 18, color: C.accent2, bold: true, charSpacing: 2, margin: 0, valign: "bottom" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: M, y: 2.3, w: CW, h: 1.5, fontFace: THEME.headFontFace, fontSize: 60, bold: true, color: C.background1, margin: 0, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: M, y: 3.9, w: 10.5, h: 1.2, fontSize: 24, color: C.accent6, margin: 0, valign: "top" }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "Section",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "number", type: "body", x: M, y: 2.0, w: 2.0, h: 1.4, fontFace: THEME.headFontFace, fontSize: 96, bold: true, color: C.accent2, margin: 0, valign: "bottom" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: M, y: 3.5, w: CW, h: 1.0, fontFace: THEME.headFontFace, fontSize: 44, bold: true, color: C.background1, margin: 0, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "lede", type: "body", x: M, y: 4.6, w: 10.5, h: 1.0, fontSize: 22, color: C.accent6, margin: 0, valign: "top" }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "Content",
  background: { color: C.background1 },
  margin: [0.5, M, 0.6, M],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.4, w: CW, h: 0.85, fontFace: THEME.headFontFace, fontSize: 36, bold: true, color: C.text2, margin: 0, valign: "middle", align: "left" }, text: "" } },
    { text: { text: "dossier · architecture, features and what comes next", options: { x: M, y: 7.0, w: 8, h: 0.3, fontSize: 11, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: W - M - 0.6, y: 7.0, w: 0.6, h: 0.3, fontSize: 11, color: C.accent5, align: "right", margin: 0 },
});

// --------------------------------------------------------------------------- helpers

function content(section, title, notes) {
  const slide = pres.addSlide({ masterName: "Content", sectionTitle: section });
  slide.addText(title, { placeholder: "title" });
  slide.addNotes(notes);
  return slide;
}

function text(slide, value, opts) {
  slide.addText(value, { isTextBox: true, margin: 0, color: C.text1, fontSize: 16, valign: "top", ...opts });
}

function card(slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: opts.fill || C.background2 },
    line: opts.line ? { color: opts.line, width: 1.25 } : { type: "none" },
    objectName: opts.id,
  });
}

function arrow(slide, x1, y1, x2, y2, color = C.accent5) {
  slide.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color, width: 2, endArrowType: "triangle" },
  });
}

function chip(slide, label, x, y, w, h, { fill = C.accent1, color = C.background1, fontSize = 15, bold = true, fontFace } = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { type: "none" } });
  slide.addText(label, { isTextBox: true, x, y, w, h, margin: 0, align: "center", valign: "middle", fontSize, bold, color, fontFace });
}

// pptxgenjs writes Office's own palette into the theme, so a scheme colour would
// resolve to Office blue. This writes the deck's colours over it, after the file
// is written, with the JSZip that pptxgenjs depends on.
async function applyTheme(file, theme) {
  const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const part = "ppt/theme/theme1.xml";
  let xml = await zip.file(part).async("string");
  for (const [slot, hex] of Object.entries(theme.colors)) {
    const pattern = new RegExp(`<a:${slot}>[\\s\\S]*?</a:${slot}>`);
    if (!pattern.test(xml)) throw new Error(`${part} has no <a:${slot}>`);
    xml = xml.replace(pattern, `<a:${slot}><a:srgbClr val="${hex}"/></a:${slot}>`);
  }
  xml = xml.replace(/<a:clrScheme name="[^"]*"/, `<a:clrScheme name="${theme.name}"`);
  zip.file(part, xml);
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

// --------------------------------------------------------------------------- slides

async function build() {
  // ===================================================================== Welcome
  pres.addSection({ title: "Welcome" });
  {
    const s = pres.addSlide({ masterName: "Title", sectionTitle: "Welcome" });
    s.addText("TUTORIAL 2", { placeholder: "kicker" });
    s.addText("dossier, from the inside", { placeholder: "title" });
    s.addText("How it is built, what it does today, and what could come next", { placeholder: "subtitle" });
    await badge(s, "FaMagnifyingGlass", W - M - 1.6, 5.2, 1.6, { fill: C.accent2, glyph: HEX.dk2 });
    s.addNotes(
      "Welcome to the second dossier tutorial. The quickstart showed you how to use it. " +
      "This one shows you how it is built, what it can do today, and what could come next. " +
      "You will see the two rules that shape the code, follow a document from the moment it is synced to the moment it is found by a search, " +
      "and finish with the pilot on real incidents."
    );
  }

  {
    const s = content("Welcome", "What dossier does",
      "dossier is a document collection and audit pipeline. " +
      "It syncs documents from the sources you configure, and fetches only what changed. " +
      "It freezes each one as a snapshot that is never changed again. " +
      "It converts them to text, and to a picture of every page. " +
      "It runs a sequence of prompt stages over them, which extract structured fields, each pointing at the evidence it came from. " +
      "It scores those answers against answers a person verified. " +
      "And it writes an index you can search by meaning and by words."
    );
    const steps = [
      ["FaArrowsRotate", "Sync", "Fetch only what changed, from folders, Jira, Confluence and websites"],
      ["FaSnowflake", "Freeze", "Keep every payload as an immutable, content-addressed snapshot"],
      ["FaFileLines", "Convert", "To text, and to one picture per page"],
      ["FaListCheck", "Ask", "Prompt stages extract fields, each pointing at its evidence"],
      ["FaScaleBalanced", "Score", "Against answers a person verified"],
      ["FaMagnifyingGlass", "Search", "By meaning and by words, filtered by what was extracted"],
    ];
    const gap = 0.2, w = (CW - gap * 5) / 6, y = 1.75, h = 4.1;
    for (let i = 0; i < steps.length; i++) {
      const [ic, head, body] = steps[i];
      const x = M + i * (w + gap);
      card(s, x, y, w, h, { id: `step ${head}` });
      await badge(s, ic, x + (w - 0.95) / 2, y + 0.35, 0.95, { fill: i === 1 ? C.accent2 : C.accent1, id: head });
      text(s, `${i + 1}`, { x, y: y + 1.45, w, h: 0.35, align: "center", fontSize: 14, color: C.accent5, bold: true });
      text(s, head, { x, y: y + 1.8, w, h: 0.5, align: "center", fontFace: THEME.headFontFace, fontSize: 22, bold: true, color: C.text2 });
      text(s, body, { x: x + 0.15, y: y + 2.4, w: w - 0.3, h: 1.6, align: "center", fontSize: 15 });
    }
    text(s, "Everything after Freeze is a function of what was frozen, so it can be repeated exactly.",
      { x: M, y: 6.15, w: CW, h: 0.45, fontSize: 18, italic: true, color: C.accent1 });
  }

  {
    const s = content("Welcome", "Written down first, then built",
      `Everything dossier does is written down before it is built. ` +
      `There are ${SPECS} specs, holding ${RULES} numbered rules. ` +
      `Behind them sit ${TESTS} test files, and the playground has ${EXERCISES} hands-on exercises. ` +
      "The numbers matter less than how they are linked: each rule names the test that proves it, " +
      "each test is claimed by a rule, and the build checks both."
    );
    const stats = [
      [String(SPECS), "specs", "in specs/, the source of truth"],
      [String(RULES), "rules", "each with examples and a counter-example"],
      [String(TESTS), "test files", "each named after the rule it proves"],
      [String(EXERCISES), "exercises", "in the playground, most of them offline"],
    ];
    const gap = 0.3, w = (CW - gap * 3) / 4;
    for (let i = 0; i < stats.length; i++) {
      const [n, label, sub] = stats[i];
      const x = M + i * (w + gap);
      card(s, x, 1.9, w, 3.3, { id: `stat ${label}` });
      text(s, n, { x, y: 2.15, w, h: 1.3, align: "center", valign: "middle", fontFace: THEME.headFontFace, fontSize: 66, bold: true, color: i === 1 ? C.accent2 : C.accent1 });
      text(s, label, { x, y: 3.5, w, h: 0.5, align: "center", fontSize: 22, bold: true, color: C.text2 });
      text(s, sub, { x: x + 0.25, y: 4.05, w: w - 0.5, h: 0.9, align: "center", fontSize: 15, color: C.accent5 });
    }
    text(s, "Each rule names the test that proves it. Each test is claimed by a rule. The build checks both.",
      { x: M, y: 5.65, w: CW, h: 0.45, fontSize: 18, italic: true, color: C.accent1 });
    const today = new Date().toISOString().slice(0, 10);
    text(s, `Counted from specs/, tests/ and playground/ on ${today}`, { x: M, y: 6.2, w: CW, h: 0.3, fontSize: 12, color: C.accent5 });
  }

  // ===================================================================== How it is built
  pres.addSection({ title: "How it is built" });
  {
    const s = pres.addSlide({ masterName: "Section", sectionTitle: "How it is built" });
    s.addText("1", { placeholder: "number" });
    s.addText("How it is built", { placeholder: "title" });
    s.addText("Two loops for writing it, and two boundaries for keeping it honest", { placeholder: "lede" });
    s.addNotes("Part one: how it is built. Two loops for writing it, and two boundaries for keeping it honest.");
  }

  {
    const s = content("How it is built", "The spec is the source of truth",
      "The specs folder is the source of truth, and the code is an implementation of it. " +
      "Every spec ends with a list of rules. Each rule is an invariant, with examples and at least one counter-example, " +
      "and it carries four fields: its kind, the layer it lives in, the test that proves it, and its status. " +
      "The test's file name carries the rule's id, and an architecture test checks the link in both directions. " +
      "Rule ids never move. A rule that stops being true is superseded and names its replacement, " +
      "so nothing that cites it is left claiming something nobody agreed to."
    );
    // rule card
    card(s, M, 1.7, 6.2, 3.75, { fill: C.text2, id: "rule card" });
    text(s, "specs/004-step-resolution.md", { x: M + 0.3, y: 1.9, w: 5.6, h: 0.3, fontSize: 12, color: C.accent6, fontFace: MONO });
    text(s, "R4.34 — a command looking for a past run passes over one whose failures.json it cannot read, and names it",
      { x: M + 0.3, y: 2.3, w: 5.6, h: 1.0, fontSize: 17, bold: true, color: C.background1 });
    const fields = [["Kind", "deterministic"], ["Layer", "application, domain, cli"], ["Proved by", "tests/acceptance/test_R004_34__…"], ["Status", "MET"]];
    fields.forEach(([k, v], i) => {
      text(s, [
        { text: `${k}  `, options: { bold: true, color: HEX.accent2 } },
        { text: v, options: { color: HEX.lt1 } },
      ], { x: M + 0.3, y: 3.45 + i * 0.45, w: 5.6, h: 0.4, fontSize: 15 });
    });
    arrow(s, M + 6.3, 3.55, M + 7.0, 3.55);
    // test and code
    card(s, M + 7.1, 1.7, 5.0, 1.7, { id: "test card" });
    await badge(s, "FaFlask", M + 7.35, 1.95, 0.7, { id: "test" });
    text(s, "The test", { x: M + 8.25, y: 1.95, w: 3.7, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    text(s, ["test_R004_34__an_unreadable_", "failures_file_is_passed_over_", "and_named.py"].map((t, i, all) =>
      ({ text: t, options: { breakLine: i < all.length - 1 } })),
      { x: M + 8.25, y: 2.4, w: 3.7, h: 0.9, fontSize: 13, fontFace: MONO, color: C.text1 });
    card(s, M + 7.1, 3.75, 5.0, 1.7, { id: "code card" });
    await badge(s, "FaCode", M + 7.35, 4.0, 0.7, { id: "code" });
    text(s, "The code", { x: M + 8.25, y: 4.0, w: 3.7, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    text(s, "Follows the spec. Behaviour no rule claims is not built.", { x: M + 8.25, y: 4.45, w: 3.7, h: 0.9, fontSize: 15 });
    arrow(s, M + 9.6, 3.4, M + 9.6, 3.75);
    // two promises
    const promises = [
      ["FaLock", "Rule ids never move", "A rule that stops being true is superseded, and names its replacement"],
      ["FaCircleExclamation", "Silence is not an option", "A rule not built yet says NOT MET, and needs no test until it is"],
    ];
    for (let i = 0; i < promises.length; i++) {
      const [ic, head, body] = promises[i];
      const x = M + i * 6.15;
      await badge(s, ic, x, 5.8, 0.6, { fill: C.accent2, glyph: HEX.dk2, id: head });
      text(s, head, { x: x + 0.8, y: 5.75, w: 5.1, h: 0.35, fontSize: 17, bold: true, color: C.text2 });
      text(s, body, { x: x + 0.8, y: 6.1, w: 5.1, h: 0.6, fontSize: 14, color: C.accent5 });
    }
  }

  {
    const s = content("How it is built", "Two loops, one slice at a time",
      "Work happens in two loops. Discover turns a request into rules, with the unknowns settled before anything is written. " +
      "Accept opens the outer loop: one acceptance test that describes what a user observes, and stays red for as long as the slice takes. " +
      "Inside it, each TDD cycle drives one failing unit test to green with the smallest change, and the default suite stays green after every cycle. " +
      "When the acceptance test passes, the rule is met and the slice is done. " +
      "Verify and quality then read the spec against the tests, and ask whether each rule is really proved."
    );
    const y = 2.0, h = 2.9;
    // discover
    card(s, M, y + 0.55, 2.3, 1.8, { id: "discover" });
    text(s, "/discover", { x: M, y: y + 0.75, w: 2.3, h: 0.45, align: "center", fontSize: 20, bold: true, fontFace: MONO, color: C.accent1 });
    text(s, "a request becomes rules", { x: M + 0.15, y: y + 1.3, w: 2.0, h: 0.8, align: "center", fontSize: 15 });
    arrow(s, M + 2.35, y + 1.45, M + 2.85, y + 1.45);
    // outer loop
    const ox = M + 2.9, ow = 6.8;
    card(s, ox, y, ow, h, { fill: C.background1, line: HEX.accent1, id: "outer loop" });
    text(s, [
      { text: "/accept", options: { fontFace: MONO, bold: true, color: HEX.accent1 } },
      { text: "   outer loop · one acceptance test, red until it is done", options: { color: HEX.dk1 } },
    ], { x: ox + 0.3, y: y + 0.25, w: ow - 0.6, h: 0.45, fontSize: 16 });
    for (let i = 0; i < 4; i++) {
      const cx = ox + 0.45 + i * 1.6;
      chip(s, "/tdd", cx, y + 1.05, 1.3, 0.75, { fontFace: MONO, fontSize: 18 });
      if (i < 3) arrow(s, cx + 1.33, y + 1.42, cx + 1.57, y + 1.42);
    }
    text(s, "inner loop · one unit test, red to green, the suite green after every cycle",
      { x: ox + 0.3, y: y + 2.1, w: ow - 0.6, h: 0.5, fontSize: 15, color: C.accent5 });
    arrow(s, ox + ow + 0.05, y + 1.45, ox + ow + 0.55, y + 1.45);
    // verify
    const vx = ox + ow + 0.6;
    card(s, vx, y + 0.55, W - M - vx, 1.8, { id: "verify" });
    text(s, "/verify", { x: vx, y: y + 0.75, w: W - M - vx, h: 0.45, align: "center", fontSize: 20, bold: true, fontFace: MONO, color: C.accent1 });
    text(s, "is each rule really proved?", { x: vx + 0.15, y: y + 1.3, w: W - M - vx - 0.3, h: 0.8, align: "center", fontSize: 15 });
    // footing
    const notes = [
      ["FaCircleDot", "Exactly one outer loop is open at a time"],
      ["FaBolt", "The default suite runs offline, in seconds, at zero cost"],
      ["FaRobot", "No live model call in it: a fake model counts every call"],
    ];
    for (let i = 0; i < notes.length; i++) {
      const x = M + i * 4.1;
      await badge(s, notes[i][0], x, 5.55, 0.6, { id: `loop note ${i}` });
      text(s, notes[i][1], { x: x + 0.8, y: 5.55, w: 3.1, h: 0.75, fontSize: 15, valign: "middle" });
    }
  }

  {
    const s = content("How it is built", "Boundary 1 · the hash boundary",
      "The first boundary is the hash boundary. Left of it, the world is mutable and remote: a Jira issue changes, a page is edited. " +
      "Sync crosses the line once, and freezes what it fetched. " +
      "Right of it, everything is a function of content hashes, so the same snapshots, prompts, schemas and model give byte-identical plans and cache keys, on any machine. " +
      "Only four packages may reach the network. Connectors fetch payloads. Models ask a model, for an answer or a vector. Tracking sends records to MLflow. And index writes and searches the embedding index. " +
      "An architecture test walks every module, and fails the build if anything else imports a network client, even lazily, inside a function."
    );
    const y = 1.65, h = 2.75;
    card(s, M, y, 5.55, h, { id: "left of the line" });
    text(s, "MUTABLE · REMOTE · NOT REPEATABLE", { x: M + 0.3, y: y + 0.25, w: 5.0, h: 0.35, fontSize: 13, bold: true, color: C.accent3, charSpacing: 1 });
    chip(s, "sync", M + 0.45, y + 1.0, 1.9, 0.8, { fill: C.accent5, fontSize: 20 });
    arrow(s, M + 2.4, y + 1.4, M + 3.0, y + 1.4);
    chip(s, "store", M + 3.05, y + 1.0, 1.9, 0.8, { fill: C.accent2, color: C.text2, fontSize: 20 });
    text(s, "a Jira issue changes, a page is edited", { x: M + 0.3, y: y + 2.05, w: 5.0, h: 0.4, fontSize: 15, color: C.accent5 });
    // the line
    s.addShape(pres.shapes.LINE, { x: M + 5.85, y: y - 0.1, w: 0, h: h + 0.2, line: { color: HEX.dk2, width: 4, dashType: "dash" }, objectName: "the hash boundary" });
    const rx = M + 6.15, rw = W - M - rx;
    card(s, rx, y, rw, h, { id: "right of the line" });
    text(s, "LOCAL · FROZEN · IDENTICAL ON EVERY RUN", { x: rx + 0.3, y: y + 0.25, w: rw - 0.6, h: 0.35, fontSize: 13, bold: true, color: C.accent4, charSpacing: 1 });
    const cw = 1.5;
    ["convert", "stages", "score"].forEach((label, i) => {
      const cx = rx + 0.35 + i * (cw + 0.35);
      chip(s, label, cx, y + 1.0, cw, 0.8, { fontSize: 20 });
      if (i < 2) arrow(s, cx + cw + 0.03, y + 1.4, cx + cw + 0.32, y + 1.4);
    });
    text(s, "a function of content hashes, byte for byte", { x: rx + 0.3, y: y + 2.05, w: rw - 0.6, h: 0.4, fontSize: 15, color: C.accent5 });
    // the four packages
    text(s, "Only four packages may reach the network", { x: M, y: 4.75, w: CW, h: 0.4, fontSize: 19, bold: true, color: C.text2 });
    const pkgs = [
      ["FaPlug", "connectors", "fetch source payloads"],
      ["FaRobot", "models", "ask for an answer or a vector"],
      ["FaChartLine", "tracking", "send records to MLflow"],
      ["FaDatabase", "index", "write and search the index"],
    ];
    const pw = (CW - 0.3 * 3) / 4;
    for (let i = 0; i < pkgs.length; i++) {
      const [ic, name, what] = pkgs[i];
      const x = M + i * (pw + 0.3);
      await badge(s, ic, x, 5.35, 0.7, { id: name });
      text(s, name, { x: x + 0.85, y: 5.33, w: pw - 0.85, h: 0.38, fontSize: 17, bold: true, fontFace: MONO, color: C.accent1 });
      text(s, what, { x: x + 0.85, y: 5.72, w: pw - 0.85, h: 0.6, fontSize: 14 });
    }
    text(s, "Checked by an ast walk over every module, a lazy import inside a function included (R0.19)",
      { x: M, y: 6.5, w: CW, h: 0.3, fontSize: 12, color: C.accent5 });
  }

  {
    const s = content("How it is built", "Boundary 2 · the purity boundary",
      "The second boundary is purity. The domain layer imports the standard library and pydantic, and nothing else: no files, no network, no clock, no environment variables. " +
      "The decisions live there: cache keys, resolution, grounding, scoring, model id checks. " +
      "That is why its tests need no fixtures and run in milliseconds, and why mutation testing is affordable on it. " +
      "Application holds the use cases, and is handed its connector, store and model client. Infrastructure is wiring. " +
      "Config is the only reader of the environment, and the CLI is the only place that exits. " +
      "The test for where something belongs is simple. If it could be asserted with a plain dictionary and no fixtures, it is a decision, and it goes in the domain."
    );
    const lx = M, lw = 6.6;
    chip(s, "cli · flags, output, exit codes", lx, 1.65, lw, 0.75, { fill: C.accent5, fontSize: 16 });
    const mids = [["config", "the only reader of the environment"], ["application", "use cases, handed their ports"], ["infrastructure", "wiring: connectors, stores, clients"]];
    const mw = (lw - 0.2 * 2) / 3;
    mids.forEach(([name, what], i) => {
      const x = lx + i * (mw + 0.2);
      card(s, x, 2.75, mw, 1.25, { id: name });
      text(s, name, { x, y: 2.85, w: mw, h: 0.4, align: "center", fontSize: 16, bold: true, fontFace: MONO, color: C.accent1 });
      text(s, what, { x: x + 0.1, y: 3.25, w: mw - 0.2, h: 0.7, align: "center", fontSize: 14 });
      arrow(s, x + mw / 2, 2.42, x + mw / 2, 2.73);
      arrow(s, x + mw / 2, 4.02, x + mw / 2, 4.33);
    });
    card(s, lx, 4.35, lw, 1.9, { fill: C.text2, id: "domain" });
    text(s, "domain", { x: lx + 0.35, y: 4.55, w: 3, h: 0.5, fontSize: 24, bold: true, fontFace: MONO, color: C.accent2 });
    text(s, "The standard library and pydantic, nothing else. No IO, no network, no clock, no environment.",
      { x: lx + 0.35, y: 5.1, w: lw - 0.7, h: 0.9, fontSize: 16, color: C.background1 });
    // the test
    const rx = M + 7.1, rw = W - M - rx;
    await badge(s, "FaCircleQuestion", rx, 1.65, 0.8, { fill: C.accent2, glyph: HEX.dk2, id: "where test" });
    text(s, "Could it be asserted with a plain dict and no fixtures?", { x: rx + 1.0, y: 1.6, w: rw - 1.0, h: 0.95, fontSize: 20, bold: true, italic: true, color: C.text2, valign: "middle" });
    text(s, "Then it is a decision, and it goes in domain.", { x: rx + 1.0, y: 2.55, w: rw - 1.0, h: 0.4, fontSize: 16, color: C.accent1 });
    const rows = [
      ["skip the fetch if the version matches", "domain"],
      ["reject a floating model alias", "domain"],
      ["issue the HTTP GET", "infrastructure"],
      ["read JIRA_TOKEN from the environment", "config"],
      ["print the plan table and exit 1", "cli"],
    ];
    rows.forEach(([looks, goes], i) => {
      const y = 3.3 + i * 0.6;
      card(s, rx, y, rw, 0.5, { fill: i < 2 ? C.background2 : C.background1, id: `row ${i}` });
      text(s, looks, { x: rx + 0.2, y, w: rw - 2.1, h: 0.5, fontSize: 14, valign: "middle" });
      text(s, goes, { x: rx + rw - 1.85, y, w: 1.7, h: 0.5, fontSize: 14, valign: "middle", align: "right", bold: true, fontFace: MONO, color: i < 2 ? C.accent1 : C.accent5 });
    });
  }

  {
    const s = content("How it is built", "Reproducible by construction",
      "Together, the two boundaries make a run reproducible by construction. " +
      "Snapshots are content addressed, and never overwritten. " +
      "Every stage's cache key holds everything that could change its answer: the snapshot, the prompt, the schema, the pinned model, and the keys of the stages before it. " +
      "Change one, and exactly what depends on it runs again. " +
      "A model is pinned exactly, so an Ollama tag is pinned by its digest. " +
      "A model is asked only on a cache miss, never during a plan or a replay, so a replay reproduces a run from months ago without a single model call."
    );
    const inputs = ["snapshot hash", "prompt hash", "schema hash", "model id, pinned", "keys of earlier stages"];
    inputs.forEach((label, i) => {
      chip(s, label, M, 1.7 + i * 0.72, 3.0, 0.55, { fill: C.background2, color: C.text1, fontSize: 15, bold: false });
      arrow(s, M + 3.05, 1.97 + i * 0.72, M + 3.75, 3.4);
    });
    card(s, M + 3.8, 2.75, 2.2, 1.3, { fill: C.accent2, id: "key" });
    await badge(s, "FaKey", M + 3.95, 2.97, 0.85, { fill: C.text2, glyph: HEX.accent2, id: "key" });
    text(s, "cache key", { x: M + 4.85, y: 2.75, w: 1.1, h: 1.3, fontSize: 16, bold: true, color: C.text2, valign: "middle" });
    arrow(s, M + 6.05, 3.4, M + 6.55, 3.4);
    card(s, M + 6.6, 2.75, 2.0, 1.3, { fill: C.text2, id: "answer" });
    text(s, "cached answer + provenance", { x: M + 6.7, y: 2.75, w: 1.8, h: 1.3, align: "center", valign: "middle", fontSize: 15, bold: true, color: C.background1 });
    const points = [
      ["FaRotateLeft", "Replay", "A past run, exactly, with no model call"],
      ["FaEquals", "Only what changed runs", "A cache hit means nothing relevant to that answer changed"],
      ["FaThumbtack", "Pinned models", "An Ollama tag is pinned by its digest"],
    ];
    const px = M + 9.0, pw = W - M - px;
    for (let i = 0; i < points.length; i++) {
      const y = 1.7 + i * 1.3;
      await badge(s, points[i][0], px, y, 0.65, { id: points[i][1] });
      text(s, points[i][1], { x: px + 0.8, y: y - 0.05, w: pw - 0.8, h: 0.4, fontSize: 16, bold: true, color: C.text2 });
      text(s, points[i][2], { x: px + 0.8, y: y + 0.35, w: pw - 0.8, h: 0.7, fontSize: 14 });
    }
    text(s, "A model is reached only on a cache miss: never during a plan, and never during a replay.",
      { x: M, y: 5.9, w: CW, h: 0.45, fontSize: 18, italic: true, color: C.accent1 });
  }

  // ===================================================================== What it does today
  pres.addSection({ title: "What it does today" });
  {
    const s = pres.addSlide({ masterName: "Section", sectionTitle: "What it does today" });
    s.addText("2", { placeholder: "number" });
    s.addText("What it does today", { placeholder: "title" });
    s.addText("A document's way through dossier, from the source to a search", { placeholder: "lede" });
    s.addNotes("Part two: what dossier does today, in the order a document meets it.");
  }

  {
    const s = content("What it does today", "Sources and sync",
      "Sources come first. There are four connectors: a folder, Jira, Confluence, and a website, read from its sitemap or crawled, " +
      "with an optional headless browser for pages drawn by script. " +
      "Every connector is read only, and returns each payload byte for byte, as it was received. " +
      "A ledger remembers what each source holds, so a sync asks only for what changed since the last one, with an overlap so that nothing at the edge is missed. " +
      "A document removed from its source is kept, and marked as gone. And a fetch that failed is owed, and asked for again next time."
    );
    const srcs = [
      ["FaFolderOpen", "Folder", "Files on disk, by path"],
      ["FaListUl", "Jira", "Issues, with comments and attachments"],
      ["FaBookOpen", "Confluence", "Pages, their files, and a PDF export"],
      ["FaGlobe", "Website", "From its sitemap or a crawl, drawn by a browser if asked"],
    ];
    const gap = 0.3, w = (CW - gap * 3) / 4;
    for (let i = 0; i < srcs.length; i++) {
      const [ic, head, body] = srcs[i];
      const x = M + i * (w + gap);
      card(s, x, 1.7, w, 2.15, { id: head });
      await badge(s, ic, x + 0.3, 1.95, 0.75, { id: head });
      text(s, head, { x: x + 1.2, y: 2.0, w: w - 1.3, h: 0.65, fontSize: 20, bold: true, color: C.text2, valign: "middle" });
      text(s, body, { x: x + 0.3, y: 2.9, w: w - 0.6, h: 0.85, fontSize: 15 });
    }
    const facts = [
      ["FaClockRotateLeft", "Incremental", "Asks only for what changed since the last sync, with an overlap at the edge"],
      ["FaEyeSlash", "Read only", "A connector never writes to the source, and keeps each payload byte for byte"],
      ["FaBoxArchive", "Gone, but kept", "A document removed from its source is kept, marked as a tombstone"],
      ["FaHourglassHalf", "Owed", "A fetch that failed is named, and asked for again at the next sync"],
    ];
    const fw = (CW - 0.4) / 2;
    for (let i = 0; i < facts.length; i++) {
      const x = M + (i % 2) * (fw + 0.4), y = 4.25 + Math.floor(i / 2) * 1.2;
      await badge(s, facts[i][0], x, y, 0.6, { fill: C.accent2, glyph: HEX.dk2, id: facts[i][1] });
      text(s, facts[i][1], { x: x + 0.8, y: y - 0.05, w: fw - 0.8, h: 0.38, fontSize: 17, bold: true, color: C.text2 });
      text(s, facts[i][2], { x: x + 0.8, y: y + 0.33, w: fw - 0.8, h: 0.65, fontSize: 14 });
    }
  }

  {
    const s = content("What it does today", "Conversion: text, and a picture of every page",
      "Conversion turns each snapshot into what a stage reads, and there are two kinds. " +
      "Markdown is text: what most stages read, and what every quoted span is checked against. " +
      "Page images are one picture per page, for a vision model to read charts and screenshots. " +
      "Converters exist for markdown, plain text, CSV, HTML, Jira issues, Confluence pages, PDFs from their text layer or as page images, images, and scans read by OCR with Docling. " +
      "A source declares which kinds it wants for each media type. And converters are registered by entry point, so you can write your own, as exercise three does."
    );
    const kinds = [
      ["FaFileLines", "markdown", "Text a stage reads, and every quoted span is checked against"],
      ["FaImages", "page_images", "One picture per page, for a vision model: charts, screenshots, scans"],
    ];
    for (let i = 0; i < kinds.length; i++) {
      const y = 1.7 + i * 2.15;
      card(s, M, y, 5.6, 1.9, { fill: i === 0 ? C.text2 : C.accent1, id: kinds[i][1] });
      await badge(s, kinds[i][0], M + 0.3, y + 0.3, 0.85, { fill: C.accent2, glyph: HEX.dk2, id: kinds[i][1] });
      text(s, kinds[i][1], { x: M + 1.4, y: y + 0.3, w: 4.0, h: 0.5, fontSize: 22, bold: true, fontFace: MONO, color: C.background1 });
      text(s, kinds[i][2], { x: M + 1.4, y: y + 0.85, w: 4.0, h: 0.9, fontSize: 15, color: C.background1 });
    }
    text(s, "A source asks for the kinds it wants per media type, in sources.yaml",
      { x: M, y: 6.1, w: 5.6, h: 0.6, fontSize: 13, color: C.accent5 });
    const rx = M + 6.1, rw = W - M - rx;
    text(s, "Converters, registered by entry point", { x: rx, y: 1.7, w: rw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    const convs = ["Markdown", "Plain text", "CSV", "HTML", "Jira issue", "Confluence page", "PDF, its text layer", "PDF, as page images", "Images, as pages", "Scans, by OCR (Docling)"];
    const cw = (rw - 0.25) / 2;
    convs.forEach((label, i) => {
      chip(s, label, rx + (i % 2) * (cw + 0.25), 2.25 + Math.floor(i / 2) * 0.72, cw, 0.56,
        { fill: C.background2, color: C.text1, fontSize: 15, bold: false });
    });
    text(s, "Write your own: exercise 03", { x: rx, y: 6.0, w: rw, h: 0.35, fontSize: 15, italic: true, color: C.accent1 });
  }

  {
    const s = content("What it does today", "A pipeline is data, end to end",
      "A pipeline is data, end to end. pipeline.yaml names its sources, a pinned model, and a sequence of steps. " +
      "Each step has a prompt, an input, a mode, per file or per group, and an output, declared as fields in YAML. " +
      "dossier never imports your code to find out what you are extracting. " +
      "Run with plan says what would run, and why, before anything is spent. " +
      "A try asks about one document at a time while you work on a prompt, and its answers are cached for the next full run. " +
      "And a replay reproduces a past run exactly."
    );
    card(s, M, 1.7, 6.1, 4.5, { fill: C.text1, id: "pipeline.yaml" });
    text(s, "pipelines/incident-audit/pipeline.yaml", { x: M + 0.3, y: 1.85, w: 5.5, h: 0.35, fontSize: 12, fontFace: MONO, color: C.accent6 });
    const yaml = [
      ["sources", ": [incidents-jira]"],
      ["model", ": openai:gpt-5.4-mini"],
      [" ", ""],
      ["steps", ":"],
      ["  - id", ": extract"],
      ["    prompt", ": prompts/01_extract.md"],
      ["    input", ": documents"],
      ["    mode", ": per_file"],
      ["    output", ": schemas/incident.yaml"],
    ];
    text(s, yaml.map(([k, v], i) => [
      { text: k, options: { color: HEX.accent2 } },
      { text: v, options: { color: HEX.lt1, breakLine: i < yaml.length - 1 } },
    // No paragraph option here (line spacing, say): pptxgenjs writes it before
    // every run, inside the paragraph, and PowerPoint refuses the file.
    ]).flat(), { x: M + 0.3, y: 2.35, w: 5.5, h: 3.6, fontSize: 18, fontFace: MONO });
    const modes = [
      ["FaRoute", "run --plan", "What would run, and why, before anything is spent"],
      ["FaVial", "run --doc KEY", "A try: one document while you work on a prompt; its answers serve the next run"],
      ["FaRotateLeft", "run --replay", "A past run, exactly, with no model call"],
    ];
    const rx = M + 6.5, rw = W - M - rx;
    for (let i = 0; i < modes.length; i++) {
      const y = 1.7 + i * 1.55;
      card(s, rx, y, rw, 1.35, { id: modes[i][1] });
      await badge(s, modes[i][0], rx + 0.25, y + 0.3, 0.75, { id: modes[i][1] });
      text(s, modes[i][1], { x: rx + 1.25, y: y + 0.18, w: rw - 1.45, h: 0.4, fontSize: 18, bold: true, fontFace: MONO, color: C.accent1 });
      text(s, modes[i][2], { x: rx + 1.25, y: y + 0.6, w: rw - 1.45, h: 0.7, fontSize: 15 });
    }
  }

  {
    const s = content("What it does today", "Every answer points at its evidence",
      "Each answer is checked before it is trusted. Output that does not match its schema is never written. " +
      "It is asked for again once, with the error, and a document that still fails does not stop the run. " +
      "Every value names the document it came from, and quotes a span of it. That span must be found in the document, " +
      "or the value is ungrounded, and scored incorrect whatever it says. " +
      "A value read from a picture of a page is described, because no string search can check it. " +
      "And not stated is a valid answer: null, with a reason."
    );
    card(s, M, 1.7, 5.4, 3.0, { fill: C.text1, id: "an answer" });
    text(s, "one field of an answer", { x: M + 0.3, y: 1.85, w: 4.8, h: 0.35, fontSize: 12, color: C.accent6 });
    const parts = [["value", "the answer"], ["source", "the document it came from"], ["span", "the words it quotes from it"]];
    parts.forEach(([k, v], i) => {
      text(s, [
        { text: k.padEnd(8), options: { fontFace: MONO, color: HEX.accent2, bold: true } },
        { text: v, options: { color: HEX.lt1 } },
      ], { x: M + 0.3, y: 2.4 + i * 0.7, w: 4.8, h: 0.5, fontSize: 18 });
    });
    text(s, "Not stated? value: null, with a reason. A valid answer, never a failure.",
      { x: M, y: 4.95, w: 5.4, h: 0.7, fontSize: 16, color: C.text2, bold: true });
    text(s, "Malformed output is asked for again once, with the error. A document that still fails does not stop the run.",
      { x: M, y: 5.7, w: 5.4, h: 0.9, fontSize: 15, color: C.accent5 });
    const states = [
      [C.accent4, "FaCircleCheck", "valid", "The span is found in the document. Scored on what it says."],
      [C.accent3, "FaCircleXmark", "ungrounded", "The span is not there. Scored incorrect, whatever it says."],
      [C.accent2, "FaImage", "described", "Read from a picture of a page, which no string search can check."],
    ];
    const rx = M + 5.9, rw = W - M - rx;
    text(s, "Three grounding states", { x: rx, y: 1.7, w: rw, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    for (let i = 0; i < states.length; i++) {
      const y = 2.3 + i * 1.4;
      card(s, rx, y, rw, 1.2, { id: states[i][2] });
      await badge(s, states[i][1], rx + 0.25, y + 0.25, 0.7, { fill: states[i][0], id: states[i][2] });
      text(s, states[i][2], { x: rx + 1.2, y: y + 0.15, w: rw - 1.4, h: 0.4, fontSize: 18, bold: true, fontFace: MONO, color: C.text2 });
      text(s, states[i][3], { x: rx + 1.2, y: y + 0.55, w: rw - 1.4, h: 0.6, fontSize: 15 });
    }
  }

  {
    const s = content("What it does today", "Scored against answers a person verified",
      "Scoring answers one question: is the output correct? Gold is a set of answers a person verified. " +
      "Each field is scored by its declared type. Amounts, dates, references, categories, booleans, durations and lists are scored exactly, with no model and no network. " +
      "Only free text needs a judge. A judge is a model too, so it is calibrated first, against a sample a person scored, and it must agree well enough before its scores count. " +
      "Eval with compare puts two runs side by side, field by field, which is how a prompt change that breaks something is caught before it ships."
    );
    text(s, "Scored exactly: no model, no network", { x: M, y: 1.7, w: 6.4, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    const types = ["amount", "date", "reference", "enum", "boolean", "duration", "list"];
    const tw = (6.4 - 0.2 * 3) / 4;
    types.forEach((t, i) => {
      chip(s, t, M + (i % 4) * (tw + 0.2), 2.25 + Math.floor(i / 4) * 0.75, tw, 0.58, { fill: C.accent1, fontSize: 16, fontFace: MONO });
    });
    text(s, "Asked of a judge", { x: M, y: 3.95, w: 6.4, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    chip(s, "free_text", M, 4.5, tw, 0.58, { fill: C.accent2, color: C.text2, fontSize: 16, fontFace: MONO });
    arrow(s, M + tw + 0.05, 4.79, M + tw + 0.5, 4.79);
    card(s, M + tw + 0.55, 4.3, 6.4 - tw - 0.55, 1.6, { id: "calibrate" });
    text(s, [
      { text: "dossier calibrate", options: { fontFace: MONO, bold: true, color: HEX.accent1, breakLine: true } },
      { text: "measures the judge against a sample a person scored. Below the agreed threshold, its scores are withheld.", options: {} },
    ], { x: M + tw + 0.75, y: 4.45, w: 6.4 - tw - 0.95, h: 1.35, fontSize: 15 });
    // compare
    const rx = M + 6.9, rw = W - M - rx;
    card(s, rx, 1.7, rw, 4.2, { fill: C.text2, id: "the change gate" });
    await badge(s, "FaCodeCompare", rx + 0.3, 1.95, 0.8, { fill: C.accent2, glyph: HEX.dk2, id: "compare" });
    text(s, "The change gate", { x: rx + 1.3, y: 2.0, w: rw - 1.5, h: 0.6, fontSize: 22, bold: true, color: C.background1, valign: "middle" });
    text(s, "dossier eval incident-audit --compare <run a> <run b>", { x: rx + 0.3, y: 2.95, w: rw - 0.6, h: 0.75, fontSize: 15, fontFace: MONO, color: C.accent2 });
    text(s, "Two runs, field by field, over the documents both answered. A field that got worse is named a regression, before the prompt change ships.",
      { x: rx + 0.3, y: 3.8, w: rw - 0.6, h: 1.6, fontSize: 16, color: C.background1 });
  }

  {
    const s = content("What it does today", "MLflow: the record, and the review",
      "With tracking on, every command records to MLflow. " +
      "A run is an MLflow run, with a trace for each document that shows what was read and what was answered, and an answer dossier doubts is tagged for review. " +
      "The gold set publishes as an evaluation dataset, a pipeline as a versioned logged model, and each prompt as a prompt version. " +
      "Reviewers who never run dossier mark answers in MLflow. Review pull brings their verdicts back, and review apply writes them into gold, with who verified them. " +
      "Tracking only sends. Nothing MLflow holds can enter a cache key, a manifest or a score."
    );
    // hub: what is recorded, around the server
    const cx = M + 3.35, cy = 3.95;
    const spokes = [
      ["FaTimeline", "Runs and traces", M, 1.7],
      ["FaTable", "Evaluation dataset", M + 3.9, 1.7],
      ["FaCodeBranch", "Pipeline versions", M, 5.25],
      ["FaPenToSquare", "Prompt versions", M + 3.9, 5.25],
    ];
    for (const [, , x, y] of spokes) {
      s.addShape(pres.shapes.LINE, {
        x: Math.min(x + 1.4, cx), y: Math.min(y + 0.35, cy), w: Math.abs(x + 1.4 - cx), h: Math.abs(y + 0.35 - cy),
        flipH: x + 1.4 > cx !== y + 0.35 > cy, line: { color: HEX.accent6, width: 2 },
      });
    }
    for (const [ic, label, x, y] of spokes) {
      chip(s, "", x, y, 2.8, 0.7, { fill: C.background2 });
      await badge(s, ic, x + 0.1, y + 0.08, 0.54, { id: label });
      text(s, label, { x: x + 0.75, y, w: 2.0, h: 0.7, fontSize: 15, bold: true, color: C.text2, valign: "middle" });
    }
    s.addShape(pres.shapes.OVAL, { x: cx - 1.0, y: cy - 1.0, w: 2.0, h: 2.0, fill: { color: C.text2 }, line: { type: "none" }, objectName: "MLflow hub" });
    text(s, "MLflow", { x: cx - 1.0, y: cy - 0.35, w: 2.0, h: 0.7, align: "center", valign: "middle", fontSize: 24, bold: true, color: C.background1 });
    // review loop
    const rx = M + 7.3, rw = W - M - rx;
    text(s, "Review, for people who never run dossier", { x: rx, y: 1.6, w: rw, h: 0.8, fontSize: 18, bold: true, color: C.text2, valign: "middle" });
    const steps = [
      ["A run tags each answer it doubts", C.accent5],
      ["A reviewer marks it in MLflow", C.accent1],
      ["dossier review pull brings the verdicts back", C.accent1],
      ["dossier review apply writes them into gold, with who verified them", C.accent2],
    ];
    steps.forEach(([label, fill], i) => {
      const y = 2.55 + i * 0.92;
      chip(s, label, rx, y, rw, 0.72, { fill, color: fill === C.accent2 ? C.text2 : C.background1, fontSize: 15 });
      if (i < steps.length - 1) arrow(s, rx + rw / 2, y + 0.73, rx + rw / 2, y + 0.91);
    });
    text(s, "Tracking only sends. Nothing MLflow holds enters a cache key, a manifest or a score.",
      { x: M, y: 6.3, w: CW, h: 0.45, fontSize: 17, italic: true, color: C.accent1 });
  }

  {
    const s = content("What it does today", "Search by meaning and by words",
      "Embed makes the workspace searchable. Each document is cut at its headings, each chunk carrying the headings above it, " +
      "and embedded with a pinned local model, through Ollama, into Postgres with pgvector. " +
      "The latest run's grounded answers come along: categories as values to filter on, and free text as one more chunk to search. " +
      "With nothing changed, no model is asked and nothing is written, because the index is derived data. " +
      "Search ranks by meaning and by words together, fuses the two lists with reciprocal rank fusion, filters by grounded values, " +
      "and shows a reader only the sources they may read. " +
      "And search with gold measures the ranking, against questions a person graded, as nDCG and recall at ten."
    );
    const rowY = [1.75, 3.85];
    text(s, "dossier embed", { x: M, y: rowY[0], w: 3, h: 0.4, fontSize: 18, bold: true, fontFace: MONO, color: C.accent1 });
    const embed = ["documents and the run's grounded record", "cut at headings, ≤ 2,000 characters", "embedded only on a cache miss, by a pinned model", "Postgres + pgvector"];
    const ew = (CW - 0.45 * 3) / 4;
    embed.forEach((label, i) => {
      const x = M + i * (ew + 0.45);
      chip(s, label, x, rowY[0] + 0.5, ew, 0.95, { fill: i === 3 ? C.text2 : C.background2, color: i === 3 ? C.background1 : C.text1, fontSize: 15, bold: i === 3 });
      if (i < 3) arrow(s, x + ew + 0.04, rowY[0] + 0.97, x + ew + 0.41, rowY[0] + 0.97);
    });
    text(s, "dossier search", { x: M, y: rowY[1], w: 3, h: 0.4, fontSize: 18, bold: true, fontFace: MONO, color: C.accent1 });
    const search = ["by meaning, and by words", "fused: reciprocal rank fusion", "filtered: --where on grounded values", "for a reader: --as, by source"];
    search.forEach((label, i) => {
      const x = M + i * (ew + 0.45);
      chip(s, label, x, rowY[1] + 0.5, ew, 0.95, { fill: i === 3 ? C.accent2 : C.background2, color: C.text1, fontSize: 15, bold: i === 3 });
      if (i < 3) arrow(s, x + ew + 0.04, rowY[1] + 0.97, x + ew + 0.41, rowY[1] + 0.97);
    });
    await badge(s, "FaRulerHorizontal", M, 5.95, 0.6, { fill: C.accent2, glyph: HEX.dk2, id: "measure" });
    text(s, [
      { text: "dossier search --gold  ", options: { fontFace: MONO, bold: true, color: HEX.accent1 } },
      { text: "measures the ranking against questions a person graded 0 to 2: nDCG@10 and recall@10", options: {} },
    ], { x: M + 0.8, y: 5.95, w: CW - 0.8, h: 0.6, fontSize: 16, valign: "middle" });
  }

  {
    const s = content("What it does today", "Running it, every day, safely",
      "Then there is running it every day. Status tells you what the workspace holds before anything is spent: " +
      "each source, each pipeline's latest run, and what eval would withhold. " +
      "gc reclaims space, and every run it keeps still replays. " +
      "A workspace lock lets one writing command run at a time, and refuses a second at once, naming the first, so a scheduled job never collides with yesterday's. " +
      "And CID masking. When a pipeline declares it, every text a model is shown is first masked on this machine, so a client's name becomes person one, " +
      "and the index and MLflow only ever see the masked text."
    );
    const items = [
      ["FaGaugeHigh", "dossier status", "What each source holds, each latest run, and what eval would withhold, before anything is spent"],
      ["FaBroom", "dossier gc", "Reclaims space from old runs, tries and cache entries. Every run it keeps still replays"],
      ["FaLock", "One writer at a time", "A second writing command is refused at once, naming the first. It never waits"],
      ["FaMask", "CID masking", "Client data masked on this machine before a model sees it: a name becomes [PERSON_1]"],
    ];
    const gw = (CW - 0.4) / 2, gh = 2.2;
    for (let i = 0; i < items.length; i++) {
      const x = M + (i % 2) * (gw + 0.4), y = 1.7 + Math.floor(i / 2) * (gh + 0.3);
      card(s, x, y, gw, gh, { id: items[i][1] });
      await badge(s, items[i][0], x + 0.35, y + 0.4, 1.0, { fill: i === 3 ? C.accent2 : C.accent1, glyph: i === 3 ? HEX.dk2 : HEX.lt1, id: items[i][1] });
      text(s, items[i][1], { x: x + 1.65, y: y + 0.35, w: gw - 1.9, h: 0.5, fontSize: 20, bold: true, color: C.text2, fontFace: i < 2 ? MONO : undefined });
      text(s, items[i][2], { x: x + 1.65, y: y + 0.9, w: gw - 1.9, h: 1.15, fontSize: 15 });
    }
  }

  {
    const s = content("What it does today", "Models, governed",
      "Models are reached through dossier's own model client, with no LangChain. " +
      "There are clients for any OpenAI-compatible endpoint, which covers OpenWebUI and vLLM, for Anthropic, and for Ollama, which also serves the embeddings. " +
      "The identifier in pipeline.yaml pins the model, and is part of every key. " +
      "Where it is served is the .env file's business, and in no key, which is how a local stub can stand in for a real model in the playground. " +
      "For real incidents the rule is simple: local models, or models behind OpenWebUI, and never a cloud API called directly."
    );
    const providers = [
      ["FaServer", "OpenAI-compatible", "OpenWebUI, vLLM, or any endpoint that speaks the API"],
      ["FaComments", "Anthropic", "Claude models, by their exact id"],
      ["FaHouseLaptop", "Ollama", "Local models, and the embedding model, pinned by digest"],
    ];
    const pw = (CW - 0.3 * 2) / 3;
    for (let i = 0; i < providers.length; i++) {
      const x = M + i * (pw + 0.3);
      card(s, x, 1.7, pw, 2.0, { id: providers[i][1] });
      await badge(s, providers[i][0], x + 0.3, 1.95, 0.75, { id: providers[i][1] });
      text(s, providers[i][1], { x: x + 1.2, y: 1.95, w: pw - 1.4, h: 0.75, fontSize: 19, bold: true, color: C.text2, valign: "middle" });
      text(s, providers[i][2], { x: x + 0.3, y: 2.85, w: pw - 0.6, h: 0.75, fontSize: 15 });
    }
    // what is in the key and what is not
    card(s, M, 4.05, 6.0, 2.45, { fill: C.text1, id: "key vs endpoint" });
    text(s, [
      { text: "pipeline.yaml", options: { color: HEX.accent6, breakLine: true, fontSize: 12 } },
      { text: "model: openai:gpt-5.4-mini", options: { color: HEX.accent2, bold: true, breakLine: true } },
      { text: "in every cache key", options: { color: HEX.lt1, breakLine: true, fontSize: 14, fontFace: THEME.bodyFontFace } },
      { text: " ", options: { breakLine: true, fontSize: 8 } },
      { text: ".env", options: { color: HEX.accent6, breakLine: true, fontSize: 12 } },
      { text: "DOSSIER_OPENAI_URL=…", options: { color: HEX.accent6, bold: true, breakLine: true } },
      { text: "where it is served: in no key", options: { color: HEX.lt1, fontSize: 14, fontFace: THEME.bodyFontFace } },
    ], { x: M + 0.3, y: 4.05, w: 5.4, h: 2.45, fontSize: 17, fontFace: MONO, valign: "middle" });
    const rx = M + 6.4, rw = W - M - rx;
    card(s, rx, 4.05, rw, 2.45, { fill: C.accent2, id: "real incidents" });
    await badge(s, "FaShieldHalved", rx + 0.3, 4.3, 0.85, { fill: C.text2, glyph: HEX.accent2, id: "governance" });
    text(s, "Real incidents", { x: rx + 1.4, y: 4.35, w: rw - 1.6, h: 0.7, fontSize: 21, bold: true, color: C.text2, valign: "middle" });
    text(s, "Only local models, or models behind OpenWebUI. Never a cloud API called directly.",
      { x: rx + 0.3, y: 5.3, w: rw - 0.6, h: 1.0, fontSize: 17, color: C.text2 });
  }

  {
    const s = content("What it does today", "Learn it by running it",
      `The best way to learn dossier is to run it. The playground has ${EXERCISES} exercises. ` +
      "The first ten are the core loop, and run offline, in seconds, at zero cost, against a stub model. " +
      "Then come MLflow and real servers: a Jira in Docker, a public Confluence, and reviews. " +
      "Then richer documents: several files as one, procedures as context, websites, answers that are not text, and OCR. " +
      "Then search. And finally operating it: two commands in one workspace, masking a client, and a workspace that runs every day. " +
      "Every walkthrough shows real output, and the quickstart video covers the core loop in ten minutes."
    );
    const groups = [
      ["01–10", "The core loop", "Sync, a pipeline, converters, gold and eval, grounding, a judge, MLflow, cache keys, page images", "offline"],
      ["11–15", "MLflow and real servers", "A Jira in Docker, a dataset and the change gate, prompt versions, review, a public Confluence", "servers"],
      ["16–19 · 23", "Richer documents", "Several files as one document, procedures as context, a website, answers that are not text, OCR", "mixed"],
      ["20–22", "Search", "An index, asking it a question, what a run costs and how fast it goes", "Postgres, Ollama"],
      ["24–27", "Operating it", "Two commands in one workspace, a client masked, a workspace that runs every day", "mixed"],
    ];
    groups.forEach(([range, head, body], i) => {
      const y = 1.6 + i * 0.9;
      card(s, M, y, CW, 0.78, { fill: i === 0 ? C.text2 : C.background2, id: head });
      text(s, range, { x: M + 0.3, y, w: 1.9, h: 0.78, valign: "middle", fontSize: 20, bold: true, fontFace: THEME.headFontFace, color: i === 0 ? C.accent2 : C.accent1 });
      text(s, head, { x: M + 2.3, y, w: 3.0, h: 0.78, valign: "middle", fontSize: 18, bold: true, color: i === 0 ? C.background1 : C.text2 });
      text(s, body, { x: M + 5.3, y, w: CW - 5.6, h: 0.78, valign: "middle", fontSize: 15, color: i === 0 ? C.background1 : C.text1 });
    });
    await badge(s, "FaCirclePlay", M, 6.2, 0.5, { fill: C.accent2, glyph: HEX.dk2, id: "quickstart" });
    text(s, "playground/README.md · and the quickstart video: the core loop in ten minutes",
      { x: M + 0.65, y: 6.25, w: CW - 0.65, h: 0.4, fontSize: 15, italic: true, color: C.accent1, valign: "middle" });
  }

  // ===================================================================== What could be next
  pres.addSection({ title: "What could be next" });
  {
    const s = pres.addSlide({ masterName: "Section", sectionTitle: "What could be next" });
    s.addText("3", { placeholder: "number" });
    s.addText("What could be next", { placeholder: "title" });
    s.addText("A pilot on real incidents, the numbers only it can settle, and what is already written down for later", { placeholder: "lede" });
    s.addNotes("Part three: what could come next.");
  }

  {
    const s = content("What could be next", "Next: a pilot on real incidents",
      "The next step is a pilot on real incidents, and it needs four things. " +
      "First, which Jira projects, Confluence spaces and folders to read. " +
      "Second, what Eureka is. Its post-mortems have no connector yet, so the pilot can start without them, or with an export to a folder. " +
      "Third, a labelled sample of real incidents, marked up on this machine, to set how much masking must catch. " +
      "And fourth, about thirty real questions, each with its top documents graded by a person, to give search its first measurement. " +
      "The stages run on gpt-5.4-mini, through OpenWebUI."
    );
    const needs = [
      ["FaSitemap", "The sources", "Which Jira projects, Confluence spaces and folders to read"],
      ["FaCircleQuestion", "Eureka", "What it is: a product, an API, an export. No connector yet: start without it, or from a folder export"],
      ["FaTags", "A labelled masking sample", "Real incidents marked up on this machine, never committed. Sets masking's recall bar (R21.14)"],
      ["FaClipboardQuestion", "Graded search questions", "About thirty real questions, their top ten documents graded by a person. Search's first nDCG@10"],
    ];
    const gw = (CW - 0.4) / 2, gh = 1.95;
    for (let i = 0; i < needs.length; i++) {
      const x = M + (i % 2) * (gw + 0.4), y = 1.65 + Math.floor(i / 2) * (gh + 0.25);
      card(s, x, y, gw, gh, { id: needs[i][1] });
      text(s, String(i + 1), { x: x + 0.3, y: y + 0.25, w: 0.8, h: 0.9, fontSize: 48, bold: true, fontFace: THEME.headFontFace, color: C.accent2 });
      await badge(s, needs[i][0], x + gw - 0.95, y + 0.25, 0.65, { id: needs[i][1] });
      text(s, needs[i][1], { x: x + 1.2, y: y + 0.3, w: gw - 2.3, h: 0.5, fontSize: 19, bold: true, color: C.text2 });
      text(s, needs[i][2], { x: x + 1.2, y: y + 1.0, w: gw - 1.5, h: 0.85, fontSize: 15 });
    }
    chip(s, "Stages: openai:gpt-5.4-mini, through OpenWebUI", M, 6.15, 5.6, 0.55, { fill: C.text2, fontSize: 15 });
  }

  {
    const s = content("What could be next", "Numbers only real data can settle",
      "Some decisions are left open on purpose, because only real data can settle them. " +
      "What recall makes masking good enough. What score search must clear. " +
      "Whether a hundred candidates per list is enough, and whether the words list should match any word of a query rather than all of them. " +
      "And whether a list of client names can be exported, as a deny list. " +
      "None of these numbers will be invented. Each waits on the pilot's measurements, and is the owner's to agree."
    );
    const open = [
      ["Masking recall", "What share of client data must masking catch?", "R21.14"],
      ["Search's bar", "What mean nDCG@10 must search clear?", "spec 022, Q1"],
      ["Candidate depth", "Are 100 candidates per list enough for the top 10?", "spec 019, Q1"],
      ["Any word, or all", "Should the words list match any word of a query?", "spec 019, Q2"],
      ["A deny-list", "Can client names be exported, to lift recall on names models miss?", "spec 021, Q3"],
    ];
    open.forEach(([head, q, ref], i) => {
      const y = 1.65 + i * 0.92;
      card(s, M, y, CW, 0.78, { fill: C.background2, id: head });
      chip(s, "OPEN", M + 0.2, y + 0.17, 1.0, 0.44, { fill: C.accent2, color: C.text2, fontSize: 13 });
      text(s, head, { x: M + 1.45, y, w: 2.6, h: 0.78, valign: "middle", fontSize: 17, bold: true, color: C.text2 });
      text(s, q, { x: M + 4.1, y, w: 6.3, h: 0.78, valign: "middle", fontSize: 15 });
      text(s, ref, { x: W - M - 1.8, y, w: 1.6, h: 0.78, valign: "middle", align: "right", fontSize: 13, color: C.accent5, fontFace: MONO });
    });
    text(s, "No threshold is invented: each waits on a measurement, and is the owner's to agree.",
      { x: M, y: 6.35, w: CW, h: 0.4, fontSize: 17, italic: true, color: C.accent1 });
  }

  {
    const s = content("What could be next", "Written down for later",
      "After the pilot, the candidates are already written down in the specs, under left out on purpose. " +
      "A Eureka connector, if an export is not enough. " +
      "Per item permissions, so the index honours Jira security levels and Confluence page restrictions, rather than one reader list per source. " +
      "Reranking, and a relevance judge for search, if the measurements ask for them. " +
      "More masking: a report of what was masked, redacted page images, and masked document keys. " +
      "A link and a container for every document. " +
      "And clustering and chat over the index, built by other tools that read its views. " +
      "Each one starts the same way: a spec, then a failing test."
    );
    const later = [
      ["FaPlug", "A Eureka connector", "If a folder export of its post-mortems is not enough"],
      ["FaUserLock", "Per-item permissions", "Jira security levels and Confluence restrictions in the index, not one reader list per source"],
      ["FaArrowUpWideShort", "Better ranking", "A reranker over the fused list, and a local relevance judge, if the measurements ask for them"],
      ["FaMask", "More masking", "What was masked, shown at convert; redacted page images; masked document keys"],
      ["FaLink", "Links and containers", "A URL, and the Jira project or Confluence space, for every document"],
      ["FaDiagramProject", "Clustering and chat", "Built by other tools, over the index's views. Not part of dossier"],
    ];
    const gw = (CW - 0.3 * 2) / 3, gh = 2.1;
    for (let i = 0; i < later.length; i++) {
      const x = M + (i % 3) * (gw + 0.3), y = 1.65 + Math.floor(i / 3) * (gh + 0.25);
      card(s, x, y, gw, gh, { id: later[i][1] });
      await badge(s, later[i][0], x + 0.25, y + 0.25, 0.65, { id: later[i][1] });
      text(s, later[i][1], { x: x + 1.05, y: y + 0.22, w: gw - 1.2, h: 0.7, fontSize: 17, bold: true, color: C.text2, valign: "middle" });
      text(s, later[i][2], { x: x + 0.25, y: y + 1.05, w: gw - 0.5, h: 0.95, fontSize: 14 });
    }
    text(s, "Each starts the same way: a spec, then a failing test.",
      { x: M, y: 6.35, w: CW, h: 0.4, fontSize: 17, italic: true, color: C.accent1 });
  }

  {
    const s = pres.addSlide({ masterName: "Title", sectionTitle: "What could be next" });
    s.addText("WHERE TO START", { placeholder: "kicker" });
    s.addText("Spec first, then code", { placeholder: "title" });
    s.addText("Read specs/000-overview.md and docs/architecture.md, then work through the playground", { placeholder: "subtitle" });
    await badge(s, "FaBookOpen", W - M - 1.6, 5.2, 1.6, { fill: C.accent2, glyph: HEX.dk2, id: "start" });
    s.addNotes(
      "That is dossier: two loops to build it, two boundaries to keep it honest, a path from a synced document to a search, and a pilot next. " +
      "To go further, start with the overview spec and the architecture document, then work through the playground. Thanks for watching."
    );
  }

  await pres.writeFile({ fileName: OUT });
  if (!process.env.NO_THEME) await applyTheme(OUT, THEME);
  console.log(`${path.basename(OUT)} · ${pres.slides.length} slides · ${SPECS} specs, ${RULES} rules, ${TESTS} test files, ${EXERCISES} exercises`);
}

build().catch((e) => {
  console.error(e);
  process.exit(1);
});
