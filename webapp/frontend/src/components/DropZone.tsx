import { createSignal, onCleanup, onMount, Show } from "solid-js";
import { formatBytes } from "../lib/api";
import { ACCEPTED_EXTENSIONS } from "../lib/studio-state";

const ACCEPT = ACCEPTED_EXTENSIONS.join(",");

/** Drag & drop, click, or paste a page. Every offered file is passed on;
 *  the studio decides what to do with more than one. */
export function DropZone(props: {
  file: File | null;
  onFiles: (files: File[]) => void;
  onClear: () => void;
  disabled?: boolean;
  /** Desktop app: accept several files (read one after another). */
  multiple?: boolean;
}) {
  const [dragging, setDragging] = createSignal(false);
  let root: HTMLDivElement | undefined;
  let input: HTMLInputElement | undefined;
  let thumbUrl: string | undefined;

  const accept = (files: FileList | File[] | null | undefined) => {
    const list = Array.from(files ?? []);
    if (!list.length || props.disabled) return;
    props.onFiles(list);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    accept(e.dataTransfer?.files);
  };

  onMount(() => {
    const onPaste = (e: ClipboardEvent) => {
      // The listener is document-wide; ignore pastes while this drop zone is
      // in a hidden panel (e.g. the Book video tab is showing).
      if (!root || root.closest("[hidden]")) return;
      const item = Array.from(e.clipboardData?.items ?? []).find((i) =>
        i.type.startsWith("image/"),
      );
      const file = item?.getAsFile();
      if (file) accept([file]);
    };
    document.addEventListener("paste", onPaste);
    onCleanup(() => {
      document.removeEventListener("paste", onPaste);
      if (thumbUrl) URL.revokeObjectURL(thumbUrl);
    });
  });

  return (
    <div ref={root}>
      {/* Operated through the drop zone button; kept out of the Tab order so
          there is one control, not two. */}
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple={props.multiple}
        class="visually-hidden"
        tabindex={-1}
        aria-label="Choose a page file"
        onChange={(e) => {
          accept(e.currentTarget.files);
          // allow choosing the same file again after clearing it
          e.currentTarget.value = "";
        }}
      />

      <Show
        when={props.file}
        fallback={
          <div
            class="dropzone"
            data-drag={dragging()}
            role="button"
            tabindex={props.disabled ? -1 : 0}
            aria-disabled={props.disabled ? "true" : undefined}
            aria-describedby="dropzone-hint"
            onClick={() => !props.disabled && input?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                if (!props.disabled) input?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span class="dropzone__title">Drop a page here, click to browse, or paste</span>
            <span class="dropzone__hint" id="dropzone-hint">
              PNG, JPG, WebP, TIFF or PDF
            </span>
          </div>
        }
      >
        {(file) => {
          if (thumbUrl) URL.revokeObjectURL(thumbUrl);
          thumbUrl = file().type.startsWith("image/") ? URL.createObjectURL(file()) : undefined;
          return (
            <div class="fileticket">
              <Show when={thumbUrl}>
                <img class="fileticket__thumb" src={thumbUrl} alt="" />
              </Show>
              <div class="fileticket__meta">
                <div class="fileticket__name">{file().name}</div>
                <div class="fileticket__size">{formatBytes(file().size)}</div>
              </div>
              <button
                class="fileticket__clear"
                type="button"
                aria-label={`Remove ${file().name}`}
                disabled={props.disabled}
                onClick={props.onClear}
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>
          );
        }}
      </Show>
    </div>
  );
}
