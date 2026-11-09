// A shared select-only combobox. Native selects retain form values and validation.
let sequence = 0,
  opened;
const controls = new Map();
const chevron =
  '<svg aria-hidden="true" viewBox="0 0 16 16"><path d="m4 6 4 4 4-4"/></svg>';
function enabled(option) {
  return !!option && !option.disabled && !option.closest("optgroup[disabled]");
}
class SelectControl {
  constructor(source) {
    this.source = source;
    const label = source.labels?.[0];
    const name =
      source.getAttribute("aria-label") ||
      (label
        ? [...label.childNodes]
            .filter((n) => n !== source && !n.contains(source))
            .map((n) => n.textContent)
            .join("")
            .trim()
        : "") ||
      "选择选项";
    this.wrapper = document.createElement("span");
    this.wrapper.className = "select-control";
    source.before(this.wrapper);
    this.wrapper.append(source);
    source.hidden = true;
    source.tabIndex = -1;
    this.trigger = document.createElement("button");
    this.trigger.type = "button";
    this.trigger.className = "select-trigger";
    this.trigger.setAttribute("role", "combobox");
    this.trigger.setAttribute("aria-label", name);
    this.trigger.setAttribute("aria-haspopup", "listbox");
    this.trigger.setAttribute("aria-expanded", "false");
    this.value = document.createElement("span");
    this.value.className = "select-value";
    this.trigger.append(this.value);
    this.trigger.insertAdjacentHTML("beforeend", chevron);
    this.wrapper.append(this.trigger);
    this.menu = document.createElement("div");
    this.menu.className = "select-menu";
    this.menu.hidden = true;
    this.menu.id = "workspace-select-" + ++sequence;
    this.menu.setAttribute("role", "listbox");
    this.menu.setAttribute("aria-label", name);
    this.trigger.setAttribute("aria-controls", this.menu.id);
    if ("showPopover" in this.menu) this.menu.setAttribute("popover", "manual");
    (source.closest("dialog") || document.body).append(this.menu);
    this.trigger.addEventListener("click", (event) => {
      event.preventDefault();
      opened === this ? this.close() : this.open();
    });
    this.trigger.addEventListener("keydown", (event) => this.keydown(event));
    this.trigger.addEventListener("blur", () => {
      if (opened === this) this.close(false);
    });
    this.menu.addEventListener("pointerdown", (event) => {
      const item = event.target.closest("[data-select-index]");
      if (!item) return;
      event.preventDefault();
      this.choose(Number(item.dataset.selectIndex));
    });
    this.menu.addEventListener("pointermove", (event) => {
      const item = event.target.closest("[data-select-index]");
      if (item && enabled(this.options[Number(item.dataset.selectIndex)]))
        this.highlight(Number(item.dataset.selectIndex), false);
    });
    this.change = () => this.sync();
    source.addEventListener("change", this.change);
    source.addEventListener("invalid", (event) => {
      event.preventDefault();
      this.trigger.setAttribute("aria-invalid", "true");
      this.trigger.focus();
    });
    label?.addEventListener("click", (event) => {
      if (event.target.closest("button,input,a,textarea,select")) return;
      event.preventDefault();
      this.trigger.focus();
    });
    this.sync();
  }
  sync() {
    this.options = [...this.source.options].filter((option) => !option.hidden);
    this.value.textContent =
      this.source.selectedOptions[0]?.textContent || "请选择";
    this.trigger.disabled = this.source.matches(":disabled");
    this.trigger.setAttribute("aria-required", String(this.source.required));
    if (this.source.value) this.trigger.removeAttribute("aria-invalid");
    if (this.trigger.disabled && opened === this) this.close(false);
    this.menu.replaceChildren(
      ...this.options.map((option, index) => {
        const item = document.createElement("div");
        item.className = "select-option";
        item.dataset.selectIndex = index;
        item.id = this.menu.id + "-" + index;
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(option.selected));
        item.setAttribute("aria-disabled", String(!enabled(option)));
        const text = document.createElement("span");
        text.textContent = option.textContent;
        const check = document.createElement("span");
        check.className = "select-check";
        check.textContent = option.selected ? "✓" : "";
        check.setAttribute("aria-hidden", "true");
        item.append(text, check);
        return item;
      }),
    );
    if (opened === this) {
      this.position();
      this.highlight(this.options.findIndex((o) => o.selected));
    }
  }
  open(index) {
    if (this.trigger.disabled || !this.options.some(enabled)) return;
    opened?.close(false);
    this.sync();
    opened = this;
    this.menu.hidden = false;
    this.menu.showPopover?.();
    this.trigger.setAttribute("aria-expanded", "true");
    this.position();
    const selected =
      index ??
      this.options.findIndex((option) => option.selected && enabled(option));
    this.highlight(selected >= 0 ? selected : this.options.findIndex(enabled));
  }
  position() {
    const rect = this.trigger.getBoundingClientRect(),
      gap = 6,
      edge = 8;
    const below = innerHeight - rect.bottom - edge,
      above = rect.top - edge,
      down = below >= 220 || below >= above;
    this.menu.style.width =
      Math.min(Math.max(rect.width, 216), innerWidth - edge * 2) + "px";
    this.menu.style.maxHeight =
      Math.max(44, Math.min(384, (down ? below : above) - gap)) + "px";
    const bounds = this.menu.getBoundingClientRect();
    this.menu.style.left =
      Math.max(edge, Math.min(rect.left, innerWidth - bounds.width - edge)) +
      "px";
    this.menu.style.top =
      Math.max(
        edge,
        Math.min(
          innerHeight - bounds.height - edge,
          down ? rect.bottom + gap : rect.top - bounds.height - gap,
        ),
      ) + "px";
  }
  highlight(index, scroll = true) {
    if (index < 0 || !enabled(this.options[index])) return;
    this.active = index;
    [...this.menu.children].forEach((node, i) =>
      node.classList.toggle("is-active", i === index),
    );
    const item = this.menu.children[index];
    this.trigger.setAttribute("aria-activedescendant", item.id);
    if (scroll) item.scrollIntoView({ block: "nearest" });
  }
  choose(index) {
    if (!enabled(this.options[index])) return;
    this.source.selectedIndex = [...this.source.options].indexOf(
      this.options[index],
    );
    this.source.dispatchEvent(new Event("input", { bubbles: true }));
    this.source.dispatchEvent(new Event("change", { bubbles: true }));
    this.close();
  }
  close(focus = true) {
    if (this.menu.hidePopover && this.menu.matches(":popover-open"))
      this.menu.hidePopover();
    this.menu.hidden = true;
    this.trigger.setAttribute("aria-expanded", "false");
    this.trigger.removeAttribute("aria-activedescendant");
    if (opened === this) opened = undefined;
    if (focus && this.trigger.isConnected) this.trigger.focus();
  }
  keydown(event) {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const choices = this.options
        .map((o, i) => (enabled(o) ? i : -1))
        .filter((i) => i >= 0);
      if (!choices.length) return;
      if (opened !== this) {
        this.open(
          event.key === "Home"
            ? choices[0]
            : event.key === "End"
              ? choices.at(-1)
              : undefined,
        );
        return;
      }
      const i = choices.indexOf(this.active),
        next =
          event.key === "Home"
            ? choices[0]
            : event.key === "End"
              ? choices.at(-1)
              : choices[
                  (i + (event.key === "ArrowDown" ? 1 : -1) + choices.length) %
                    choices.length
                ];
      this.highlight(next);
    } else if (event.key === "Escape" && opened === this) {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    } else if (["Enter", " "].includes(event.key)) {
      event.preventDefault();
      opened === this ? this.choose(this.active) : this.open();
    } else if (event.key === "Tab") this.close(false);
    else if (
      event.key.length === 1 &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !event.isComposing
    ) {
      event.preventDefault();
      const stamp = performance.now();
      this.typed =
        stamp - (this.typedAt || 0) < 700
          ? (this.typed || "") + event.key
          : event.key;
      this.typedAt = stamp;
      if (opened !== this) this.open();
      const index = this.options.findIndex(
        (o) =>
          enabled(o) &&
          o.textContent
            .trim()
            .toLocaleLowerCase()
            .startsWith(this.typed.toLocaleLowerCase()),
      );
      if (index >= 0) this.highlight(index);
    }
  }
  destroy() {
    this.close(false);
    this.menu.remove();
    this.source.removeEventListener("change", this.change);
  }
}
function enhance() {
  for (const [source, control] of controls)
    if (!source.isConnected) {
      control.destroy();
      controls.delete(source);
    }
  document.querySelectorAll("select:not([multiple])").forEach((source) => {
    if (!controls.has(source)) controls.set(source, new SelectControl(source));
  });
}
enhance();
new MutationObserver((records) => {
  enhance();
  const changed = new Set();
  for (const record of records) {
    const source = record.target.closest?.("select");
    if (source) changed.add(source);
    if (record.target.tagName === "FIELDSET")
      record.target.querySelectorAll("select").forEach((s) => changed.add(s));
  }
  changed.forEach((source) => controls.get(source)?.sync());
}).observe(document.body, {
  subtree: true,
  childList: true,
  attributes: true,
  attributeFilter: [
    "disabled",
    "selected",
    "value",
    "label",
    "hidden",
    "required",
  ],
});
document.addEventListener("pointerdown", (event) => {
  if (
    opened &&
    !opened.trigger.contains(event.target) &&
    !opened.menu.contains(event.target)
  )
    opened.close(false);
});
document.addEventListener(
  "scroll",
  (event) => {
    if (opened && !opened.menu.contains(event.target)) {
      const rect = opened.trigger.getBoundingClientRect();
      if (rect.bottom <= 8 || rect.top >= innerHeight - 8) opened.close(false);
      else opened.position();
    }
  },
  { capture: true, passive: true },
);
addEventListener("resize", () => opened?.close(false));
document.addEventListener(
  "close",
  (event) => {
    if (event.target.contains(opened?.source)) opened.close(false);
  },
  true,
);
document.addEventListener(
  "toggle",
  (event) => {
    if (
      event.target.tagName === "DETAILS" &&
      !event.target.open &&
      event.target.contains(opened?.source)
    )
      opened.close(false);
  },
  true,
);
document.addEventListener("reset", () =>
  queueMicrotask(() => controls.forEach((control) => control.sync())),
);
