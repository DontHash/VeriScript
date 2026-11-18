import { createSignal, onCleanup, onMount } from "solid-js";

/**
 * Before/after compare with a drag handle. Pointer-drag anywhere on the
 * surface, arrow keys on the handle. Mirrors the restore wipe from the film.
 */
export function CompareSlider(props: {
  before: string;
  after: string;
  alt: string;
  beforeLabel?: string;
  afterLabel?: string;
  /** initial handle position, 0–100 */
  initial?: number;
  onPositionChange?: (p: number) => void;
}) {
  const [pos, setPos] = createSignal(props.initial ?? 50);
  const [dragging, setDragging] = createSignal(false);
  let surface: HTMLDivElement | undefined;
  let handle: HTMLDivElement | undefined;

  const clamp = (v: number) => Math.min(100, Math.max(0, v));

  const update = (next: number) => {
    const value = clamp(next);
    setPos(value);
    props.onPositionChange?.(value);
  };

  const setFromClientX = (clientX: number) => {
    if (!surface) return;
    const rect = surface.getBoundingClientRect();
    update(((clientX - rect.left) / rect.width) * 100);
  };

  const onPointerDown = (e: PointerEvent) => {
    // Pointer users get the same keyboard-operable handle focused.
    handle?.focus({ preventScroll: true });
    setDragging(true);
    surface?.setPointerCapture(e.pointerId);
    setFromClientX(e.clientX);
  };
  const onPointerMove = (e: PointerEvent) => {
    if (dragging()) setFromClientX(e.clientX);
  };
  const onPointerUp = (e: PointerEvent) => {
    setDragging(false);
    surface?.releasePointerCapture(e.pointerId);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 5;
    const moves: Record<string, number> = {
      ArrowLeft: pos() - step,
      ArrowDown: pos() - step,
      ArrowRight: pos() + step,
      ArrowUp: pos() + step,
      PageDown: pos() - 25,
      PageUp: pos() + 25,
      Home: 0,
      End: 100,
    };
    if (!(e.key in moves)) return;
    e.preventDefault();
    update(moves[e.key]);
  };

  const valueText = () => {
    const shown = Math.round(pos());
    const before = props.beforeLabel ?? "before";
    const after = props.afterLabel ?? "after";
    return `${shown}% ${before}, ${100 - shown}% ${after}`;
  };

  onMount(() => {
    const stop = () => setDragging(false);
    window.addEventListener("pointerup", stop);
    onCleanup(() => window.removeEventListener("pointerup", stop));
  });

  const caption = () => {
    if (props.beforeLabel && props.afterLabel) {
      return `${props.beforeLabel} left, ${props.afterLabel} right. Drag to compare.`;
    }
    return props.beforeLabel ?? props.afterLabel ?? "";
  };

  return (
    <figure class="compare-figure">
      <div
        ref={surface}
        class="compare"
        data-dragging={dragging()}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <img class="compare__img" src={props.after} alt={`${props.alt} — restored`} draggable={false} />
        <div
          class="compare__before"
          style={{ "clip-path": `inset(0 ${100 - pos()}% 0 0)` }}
          aria-hidden="true"
        >
          <img class="compare__img" src={props.before} alt="" draggable={false} />
        </div>

        <div
          ref={handle}
          class="compare__handle"
          style={{ left: `${pos()}%` }}
          role="slider"
          tabindex={0}
          aria-label={`Compare ${props.alt}: before and after`}
          aria-orientation="horizontal"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pos())}
          aria-valuetext={valueText()}
          onKeyDown={onKeyDown}
        >
          <span class="compare__grip" aria-hidden="true" />
        </div>
      </div>

      {caption() && <figcaption class="compare__caption">{caption()}</figcaption>}
    </figure>
  );
}
