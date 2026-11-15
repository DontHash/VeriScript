/** Desktop library (docs/TECH_UPGRADE_PLAN.md B1): every kept document, with
 *  search over titles and recognised text, open, rename and delete. The
 *  server only offers it in the desktop app; the demo explains that. */
import { A } from "@solidjs/router";
import { createResource, createSignal, For, onCleanup, Show } from "solid-js";
import { deleteRun, fetchLibrary, renameRun } from "../lib/api";
import { announce } from "../lib/announce";
import { isLocal } from "../lib/health";
import type { LibraryDoc } from "../lib/types";

const when = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function Library() {
  const [query, setQuery] = createSignal("");
  const [error, setError] = createSignal<string | null>(null);
  const [editing, setEditing] = createSignal<string | null>(null);
  const [docs, { refetch, mutate }] = createResource(query, async (q) => {
    try {
      setError(null);
      return await fetchLibrary(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The library could not be read.");
      return [] as LibraryDoc[];
    }
  });

  let timer: number | undefined;
  const search = (value: string) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => setQuery(value.trim()), 250);
  };
  onCleanup(() => window.clearTimeout(timer));

  const rename = async (doc: LibraryDoc, title: string) => {
    setEditing(null);
    if (!title.trim() || title.trim() === doc.title) return;
    try {
      const saved = await renameRun(doc.run_id, title);
      mutate((list) => list?.map((d) => (d.run_id === doc.run_id ? { ...d, title: saved } : d)));
      announce(`Renamed to ${saved}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not rename it.");
    }
  };

  const remove = async (doc: LibraryDoc) => {
    if (!window.confirm(`Delete “${doc.title}” and all its files from this computer? This cannot be undone.`)) {
      return;
    }
    try {
      await deleteRun(doc.run_id);
      mutate((list) => list?.filter((d) => d.run_id !== doc.run_id));
      announce(`Deleted ${doc.title}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete it.");
    }
  };

  return (
    <div class="studio">
      <div class="container stack-16">
        <div class="studio__head">
          <h1 class="h2">Your documents</h1>
          <p class="lede">
            Everything you have read in the desktop app, kept on this computer until you
            delete it.
          </p>
        </div>

        <Show
          when={isLocal()}
          fallback={
            <p class="field__hint">
              The library is part of the desktop app. The online demo deletes results after a
              short time.
            </p>
          }
        >
          <div class="field">
            <label class="field__label" for="library-search">
              Search titles and text
            </label>
            <input
              id="library-search"
              class="input"
              type="search"
              placeholder="e.g. invoice 12345"
              onInput={(e) => search(e.currentTarget.value)}
            />
          </div>

          <Show when={error()}>
            <div class="alert" role="alert">
              {error()}{" "}
              <button class="btn btn--ghost btn--small" type="button" onClick={() => refetch()}>
                Try again
              </button>
            </div>
          </Show>

          <Show
            when={(docs() ?? []).length > 0}
            fallback={
              <Show when={!docs.loading}>
                <p class="field__hint">
                  {query()
                    ? `Nothing matches “${query()}”.`
                    : "No documents yet. Read a page in the studio and it appears here."}
                </p>
              </Show>
            }
          >
            <p class="field__hint" role="status">
              {docs()!.length} {docs()!.length === 1 ? "document" : "documents"}
              {query() ? ` matching “${query()}”` : ""}
            </p>
            <ul class="library" aria-label="Documents">
              <For each={docs()}>
                {(doc) => (
                  <li class="library__item">
                    <div class="library__main">
                      <Show
                        when={editing() === doc.run_id}
                        fallback={<h2 class="library__title">{doc.title}</h2>}
                      >
                        <label class="visually-hidden" for={`rename-${doc.run_id}`}>
                          New name for {doc.title}
                        </label>
                        <input
                          id={`rename-${doc.run_id}`}
                          class="input"
                          value={doc.title}
                          maxLength={120}
                          ref={(el) => queueMicrotask(() => el.select())}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void rename(doc, e.currentTarget.value);
                            if (e.key === "Escape") setEditing(null);
                          }}
                          onBlur={(e) => void rename(doc, e.currentTarget.value)}
                        />
                      </Show>
                      <p class="field__hint">
                        {when(doc.created)} · {doc.pages} {doc.pages === 1 ? "page" : "pages"} ·{" "}
                        {doc.input_kind === "pdf" ? "PDF" : "image"}
                        {doc.flagged ? ` · ${doc.flagged} to review` : " · nothing to review"}
                        {doc.corrected ? " · corrected" : ""}
                      </p>
                    </div>
                    <div class="library__actions">
                      <A class="btn btn--primary btn--small" href={`/studio?run=${doc.run_id}`}>
                        Open<span class="visually-hidden"> {doc.title}</span>
                      </A>
                      <button
                        class="btn btn--ghost btn--small"
                        type="button"
                        onClick={() => setEditing(doc.run_id)}
                      >
                        Rename<span class="visually-hidden"> {doc.title}</span>
                      </button>
                      <button
                        class="btn btn--ghost btn--small"
                        type="button"
                        onClick={() => void remove(doc)}
                      >
                        Delete<span class="visually-hidden"> {doc.title}</span>
                      </button>
                    </div>
                  </li>
                )}
              </For>
            </ul>
          </Show>
        </Show>
      </div>
    </div>
  );
}
