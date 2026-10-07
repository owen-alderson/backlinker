import {
  App, Editor, MarkdownFileInfo, MarkdownView, Modal, Notice, Plugin, PluginSettingTab, Setting, TFile,
  moment, normalizePath, parseFrontMatterAliases, parseFrontMatterTags,
} from "obsidian";
import { findDue } from "./dates";
import { insertLines } from "./insert";
import { Linker, Result, notesFrom, protectedRe } from "./linker";

interface Settings {
  heading: string;
  timePrefix: boolean;
  dueFormat: "tasks" | "dataview";
  peopleFolders: string;
  ignore: string;
}

const DEFAULTS: Settings = { heading: "", timePrefix: true, dueFormat: "tasks", peopleFolders: "People", ignore: "" };
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

interface DailyConfig { folder: string; format: string; template: string }

export default class BacklinkerPlugin extends Plugin {
  settings: Settings = DEFAULTS;

  async onload() {
    this.settings = { ...DEFAULTS, ...(await this.loadData()) };
    this.addCommand({ id: "capture", name: "Capture to daily note", callback: () => new CaptureModal(this.app, this).open() });
    this.addCommand({
      id: "link-mentions",
      name: "Link mentions in selection or note",
      editorCallback: (editor: Editor, ctx: MarkdownView | MarkdownFileInfo) => this.linkInEditor(editor, ctx.file),
    });
    this.addRibbonIcon("link", "Backlinker: capture", () => new CaptureModal(this.app, this).open());
    this.addSettingTab(new BacklinkerSettings(this.app, this));
    this.app.workspace.onLayoutReady(() => void this.dailyConfig());  // learns the templates folder
  }

  linker(): Linker {
    const skip = [this.templatesConfig.folder].filter(Boolean);
    const entries = this.app.vault.getMarkdownFiles()
      .filter((f) => !skip.some((s) => f.path.startsWith(s + "/")))
      .map((f) => {
        const fm = this.app.metadataCache.getFileCache(f)?.frontmatter;
        return { path: f.path, aliases: parseFrontMatterAliases(fm) ?? [], tags: parseFrontMatterTags(fm) ?? [] };
      });
    return new Linker(notesFrom(entries, list(this.settings.peopleFolders)), list(this.settings.ignore));
  }

  private templatesConfig = { folder: "", date: "YYYY-MM-DD", time: "HH:mm" };

  private async readConfig(rel: string): Promise<Record<string, unknown>> {
    try {
      return JSON.parse(await this.app.vault.adapter.read(normalizePath(`${this.app.vault.configDir}/${rel}`)));
    } catch {
      return {};
    }
  }

  /** Daily-note settings exactly as the CLI reads them (Periodic Notes wins when enabled). */
  async dailyConfig(): Promise<DailyConfig> {
    const t = await this.readConfig("templates.json");
    this.templatesConfig = {
      folder: String(t.folder ?? "").replace(/^\/+|\/+$/g, ""),
      date: String(t.dateFormat || "YYYY-MM-DD"), time: String(t.timeFormat || "HH:mm"),
    };
    const enabled = await this.readConfig("community-plugins.json");
    const periodic = ((await this.readConfig("plugins/periodic-notes/data.json")).daily ?? {}) as Record<string, unknown>;
    const usePeriodic = Array.isArray(enabled) && enabled.includes("periodic-notes") && periodic.enabled;
    const src = usePeriodic ? periodic : await this.readConfig("daily-notes.json");
    const clean = (v: unknown) => String(v ?? "").replace(/^\/+|\/+$/g, "");
    return { folder: clean(src.folder), format: String(src.format || "YYYY-MM-DD"), template: clean(src.template) };
  }

  async dailyFile(day: moment.Moment): Promise<TFile> {
    const cfg = await this.dailyConfig();
    const name = day.format(cfg.format);
    const path = normalizePath(cfg.folder ? `${cfg.folder}/${name}.md` : `${name}.md`);
    const existing = this.app.vault.getAbstractFileByPath(path);
    if (existing instanceof TFile) return existing;
    let content = "";
    const tpl = cfg.template && this.app.vault.getAbstractFileByPath(normalizePath(cfg.template.endsWith(".md") ? cfg.template : cfg.template + ".md"));
    if (tpl instanceof TFile) content = renderTemplate(await this.app.vault.read(tpl), day, cfg.format);
    const folder = path.split("/").slice(0, -1).join("/");
    if (folder && !this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder);
    return this.app.vault.create(path, content);
  }

  /** Turn captured text into daily-note lines, with links and due dates. */
  plan(text: string, task: boolean, linker: Linker, now = moment()): { lines: string[]; result: Result[]; due: string[] } {
    const today = now.format("YYYY-MM-DD");
    const lines: string[] = [], result: Result[] = [], due: string[] = [];
    for (const raw of text.split("\n")) {
      let line = raw.trim();
      if (!line) continue;
      let isTask = task;
      const m = /^(?:[-*+]\s+)?(?:\[ ?\]\s*|todo:?\s+)/i.exec(line);
      if (m) { isTask = true; line = line.slice(m[0].length).trim(); }
      else line = line.replace(/^(?:[-*+]|\d+[.)])\s+/, "");
      let suffix = "";
      if (isTask) {
        const spans = [...line.matchAll(protectedRe())].map((p) => [p.index!, p.index! + p[0].length] as [number, number]);
        const [when, rest] = findDue(line, today, spans);
        line = rest;
        if (when) { due.push(when); suffix = this.settings.dueFormat === "tasks" ? ` 📅 ${when}` : ` [due:: ${when}]`; }
      }
      if (!line) continue;
      const r = linker.link(line);
      result.push(r);
      lines.push(isTask ? `- [ ] ${r.text}${suffix}` : `- ${this.settings.timePrefix ? now.format("HH:mm") + " " : ""}${r.text}`);
    }
    return { lines, result, due };
  }

  async capture(text: string, task: boolean): Promise<void> {
    const { lines, result } = this.plan(text, task, this.linker());
    if (!lines.length) return;
    const file = await this.dailyFile(moment());
    await this.app.vault.process(file, (data) => insertLines(data, lines, this.settings.heading, data.includes("\r\n") ? "\r\n" : "\n"));
    const links = [...new Set(result.flatMap((r) => r.links.map((l) => l.target)))];
    const ambiguous = result.flatMap((r) => r.ambiguous.map((a) => `${a.text}?`));
    new Notice(`Added to ${file.basename}` + (links.length ? `, linked ${links.join(", ")}` : "")
      + (ambiguous.length ? `. Ambiguous: ${ambiguous.join(", ")}` : ""));
  }

  linkInEditor(editor: Editor, file: TFile | null) {
    const linker = this.linker();
    const self = file ? this.app.metadataCache.fileToLinktext(file, "") : null;
    let r: Result;
    if (editor.somethingSelected()) {
      const whole = editor.getValue();
      const already = [...whole.matchAll(/!?\[\[([^\]|#^\n]*)/g)].map((m) => m[1]);
      r = linker.link(editor.getSelection(), self ? [...already, self] : already);
      if (r.links.length) editor.replaceSelection(r.text);
    } else {
      r = linker.linkDocument(editor.getValue(), self);
      if (r.links.length) {
        const last = editor.lastLine();
        editor.transaction({ changes: [{ from: { line: 0, ch: 0 }, to: { line: last, ch: editor.getLine(last).length }, text: r.text }] });
      }
    }
    const amb = r.ambiguous.map((a) => `${a.text} (${a.candidates.join(" / ")})`);
    new Notice((r.links.length ? `Linked ${r.links.map((l) => l.target).join(", ")}` : "Nothing new to link")
      + (amb.length ? `. Left ambiguous: ${amb.join(", ")}` : ""));
  }

  async saveSettings() { await this.saveData(this.settings); }
}

/** {{date}}, {{time}}, {{title}}, {{yesterday}}, {{tomorrow}}, {{date:FORMAT}}, {{date+1d}}, like the core plugin. */
export function renderTemplate(tpl: string, day: moment.Moment, format: string): string {
  const title = day.format(format);
  return tpl.replace(/{{\s*(date|time|title|yesterday|tomorrow)\s*(?:([+-]\d+)([dw]))?\s*(?::(.+?))?\s*}}/gi,
    (_m, v: string, amount?: string, unit?: string, custom?: string) => {
      const name = v.toLowerCase();
      if (name === "title") return title;
      const when = day.clone().set({ hour: moment().hour(), minute: moment().minute() });
      if (name === "yesterday") when.subtract(1, "day");
      if (name === "tomorrow") when.add(1, "day");
      if (amount) when.add(Number(amount) * (unit!.toLowerCase() === "w" ? 7 : 1), "days");
      if (name === "time" && !custom && !amount) return moment().format("HH:mm");
      return when.format(custom || format);
    });
}

class CaptureModal extends Modal {
  private task = false;
  private input!: HTMLTextAreaElement;
  private preview!: HTMLElement;
  private linker: Linker;

  constructor(app: App, private plugin: BacklinkerPlugin) {
    super(app);
    this.linker = plugin.linker();
  }

  onOpen() {
    const { contentEl } = this;
    this.setTitle("Capture to daily note");
    this.input = contentEl.createEl("textarea", { cls: "backlinker-input", attr: { rows: "3", placeholder: "Call with Maya about Lumen…" } });
    new Setting(contentEl).setName("Task").setDesc("A date like fri or tomorrow becomes the due date.")
      .addToggle((t) => t.setValue(this.task).onChange((v) => { this.task = v; this.render(); }));
    this.preview = contentEl.createDiv({ cls: "backlinker-preview" });
    new Setting(contentEl).addButton((b) => b.setButtonText("Add").setCta().onClick(() => this.submit()));
    this.input.addEventListener("input", () => this.render());
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.submit(); }
    });
    this.input.focus();
  }

  private render() {
    this.preview.empty();
    const { lines, result } = this.plugin.plan(this.input.value, this.task, this.linker);
    for (const line of lines) this.preview.createEl("code", { text: line, cls: "backlinker-line" });
    for (const a of result.flatMap((r) => r.ambiguous)) {
      this.preview.createDiv({ cls: "backlinker-ambiguous", text: `“${a.text}” could be ${a.candidates.join(" or ")}; left unlinked` });
    }
  }

  private async submit() {
    const text = this.input.value;
    if (!text.trim()) return;
    this.close();
    try {
      await this.plugin.capture(text, this.task);
    } catch (e) {
      new Notice(`Backlinker: ${(e as Error).message}`);
    }
  }

  onClose() { this.contentEl.empty(); }
}

class BacklinkerSettings extends PluginSettingTab {
  constructor(app: App, private plugin: BacklinkerPlugin) { super(app, plugin); }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    const s = this.plugin.settings;
    const save = () => this.plugin.saveSettings();
    new Setting(containerEl).setName("Heading").setDesc("Add captures under this heading in the daily note, e.g. ## Log. Empty: end of the note.")
      .addText((t) => t.setPlaceholder("## Log").setValue(s.heading).onChange(async (v) => { s.heading = v; await save(); }));
    new Setting(containerEl).setName("Time prefix").setDesc("Start each line with the time, like - 14:32 …")
      .addToggle((t) => t.setValue(s.timePrefix).onChange(async (v) => { s.timePrefix = v; await save(); }));
    new Setting(containerEl).setName("Due date format").setDesc("How a task's due date is written.")
      .addDropdown((d) => d.addOptions({ tasks: "Tasks plugin (📅 2026-10-09)", dataview: "Dataview ([due:: 2026-10-09])" })
        .setValue(s.dueFormat).onChange(async (v) => { s.dueFormat = v as Settings["dueFormat"]; await save(); }));
    new Setting(containerEl).setName("People folders").setDesc("Comma-separated. Notes here (or tagged #person) also link by unique first name.")
      .addText((t) => t.setValue(s.peopleFolders).onChange(async (v) => { s.peopleFolders = v; await save(); }));
    new Setting(containerEl).setName("Never link").setDesc("Comma-separated note names or aliases to leave alone.")
      .addText((t) => t.setValue(s.ignore).onChange(async (v) => { s.ignore = v; await save(); }));
  }
}
