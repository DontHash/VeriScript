import { createEffect, onCleanup } from "solid-js";

/** One image load per page image, shared by every row of the queue. */
const images = new Map<string, Promise<HTMLImageElement>>();

function loadImage(src: string): Promise<HTMLImageElement> {
  let pending = images.get(src);
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`could not load ${src}`));
      img.src = src;
    });
    images.set(src, pending);
  }
  return pending;
}

const PAD = 6;
const HEIGHT = 44;

/**
 * The page pixels under a review-queue token, so the reading can be checked
 * against the source without switching to the overlay. Decorative for
 * screen readers: the row already reads the token and its flags.
 */
export function TokenCrop(props: {
  src: string;
  bbox: [number, number, number, number];
}) {
  let canvas: HTMLCanvasElement | undefined;
  let alive = true;
  onCleanup(() => (alive = false));

  createEffect(() => {
    const [x0, y0, x1, y1] = props.bbox;
    void loadImage(props.src)
      .then((img) => {
        if (!alive || !canvas) return;
        const sx = Math.max(0, x0 - PAD);
        const sy = Math.max(0, y0 - PAD);
        const sw = Math.min(img.naturalWidth, x1 + PAD) - sx;
        const sh = Math.min(img.naturalHeight, y1 + PAD) - sy;
        if (sw <= 0 || sh <= 0) return;
        const scale = (HEIGHT * window.devicePixelRatio) / sh;
        canvas.width = Math.max(1, Math.round(sw * scale));
        canvas.height = Math.round(HEIGHT * window.devicePixelRatio);
        canvas.getContext("2d")?.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      })
      .catch(() => {
        if (canvas) canvas.hidden = true;
      });
  });

  return <canvas ref={canvas} class="review__crop" aria-hidden="true" />;
}
