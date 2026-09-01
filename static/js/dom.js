// Minimal DOM construction helpers.
//
// The UI is plain DOM: `el()` builds nodes, tab modules keep their state in a
// closure and re-render only the subtree that changed. Text is always set via
// textContent, never innerHTML, so API strings can never inject markup.

/**
 * Build an element.
 *
 * `props` maps to DOM properties, with three special cases: `class` sets
 * className, `style` takes an object of CSS properties, and any `on*` key
 * takes an event listener. Children may be nodes, strings, numbers, or
 * arrays; null/undefined/false children are skipped so callers can write
 * `cond && el(...)`.
 *
 * @param {string} tag
 * @param {Record<string, unknown>} [props]
 * @param {...unknown} children
 * @returns {HTMLElement}
 */
export function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined) continue;
    if (key === "class") {
      node.className = String(value);
    } else if (key === "style" && typeof value === "object") {
      Object.assign(node.style, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in node) {
      node[key] = value;
    } else {
      node.setAttribute(key, String(value));
    }
  }
  append(node, children);
  return node;
}

/** Append children to `node`, flattening arrays and skipping empty slots. */
export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) {
      continue;
    }
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Replace every child of `node` with `children`. */
export function replace(node, ...children) {
  node.replaceChildren();
  return append(node, children);
}

/** A `<div class="field">` wrapping a labelled control. */
export function field(labelText, control, opts = {}) {
  const id = control.id || undefined;
  return el(
    "div",
    { class: opts.class ? `field ${opts.class}` : "field", style: opts.style },
    el("label", { htmlFor: id }, labelText),
    control,
    opts.hint,
  );
}

/** A `.banner` of the given kind ("ok" | "info" | "warn" | "error"). */
export function banner(kind, ...children) {
  return el("div", { class: `banner ${kind}` }, ...children);
}

/** Format a possibly-null number for display. */
export function fmtNum(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : Number(value).toFixed(digits);
}

/** Split a textarea value into trimmed, non-empty lines. */
export function splitLines(value) {
  return value
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Split a comma-separated string into finite numbers. */
export function splitNums(value) {
  return value
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
}

/** Split a comma-separated string into trimmed, non-empty strings. */
export function splitStrings(value) {
  return value
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}
