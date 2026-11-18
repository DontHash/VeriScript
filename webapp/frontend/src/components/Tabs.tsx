import { For, type JSX } from "solid-js";

/**
 * WAI-ARIA tabs (https://www.w3.org/WAI/ARIA/apg/patterns/tabs/).
 *
 * Roving tabindex: only the selected tab is in the Tab order; Arrow keys,
 * Home and End move between tabs and select them (automatic activation).
 * Pair every tab with a <TabPanel> that uses the same `idPrefix` and `id`.
 */
export interface TabItem<T extends string> {
  id: T;
  label: JSX.Element;
}

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

export function Tabs<T extends string>(props: {
  /** accessible name of the tab list */
  label: string;
  idPrefix: string;
  items: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
  /** disabled tabs stay focusable (aria-disabled) but cannot be selected */
  disabled?: boolean;
}) {
  let list: HTMLDivElement | undefined;

  const focusTab = (id: T) =>
    list?.querySelector<HTMLButtonElement>(`#${CSS.escape(tabId(props.idPrefix, id))}`)?.focus();

  const onKeyDown = (e: KeyboardEvent) => {
    const ids = props.items.map((i) => i.id);
    const current = ids.indexOf(props.selected);
    let next: number;
    switch (e.key) {
      case "ArrowRight":
        next = (current + 1) % ids.length;
        break;
      case "ArrowLeft":
        next = (current - 1 + ids.length) % ids.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = ids.length - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    if (props.disabled) return;
    props.onSelect(ids[next]);
    focusTab(ids[next]);
  };

  return (
    <div
      ref={list}
      class="tabs"
      role="tablist"
      aria-label={props.label}
      onKeyDown={onKeyDown}
    >
      <For each={props.items}>
        {(item) => (
          <button
            type="button"
            class="tab"
            role="tab"
            id={tabId(props.idPrefix, item.id)}
            aria-controls={panelId(props.idPrefix, item.id)}
            aria-selected={props.selected === item.id}
            aria-disabled={props.disabled ? "true" : undefined}
            tabindex={props.selected === item.id ? 0 : -1}
            onClick={() => {
              if (!props.disabled) props.onSelect(item.id);
            }}
          >
            {item.label}
          </button>
        )}
      </For>
    </div>
  );
}

/** The panel for one tab. `keepMounted` hides instead of unmounting, so
 *  state inside (an in-progress video review) survives switching tabs. */
export function TabPanel(props: {
  idPrefix: string;
  id: string;
  selected: boolean;
  keepMounted?: boolean;
  class?: string;
  children: JSX.Element;
}) {
  return (
    <div
      role="tabpanel"
      id={panelId(props.idPrefix, props.id)}
      aria-labelledby={tabId(props.idPrefix, props.id)}
      class={props.class}
      hidden={!props.selected}
    >
      {props.keepMounted || props.selected ? props.children : null}
    </div>
  );
}
