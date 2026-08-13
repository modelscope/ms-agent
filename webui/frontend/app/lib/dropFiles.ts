/**
 * Reading OS drag-and-drop payloads.
 *
 * `DataTransfer.files` is a trap for folder drops: a dropped directory shows up
 * as a single bogus `File` (its name, the inode's size — 96 B on macOS, empty
 * type) that cannot be read. Anything relying on it therefore renders a folder
 * as if it were a small file, and uploading it fails or stores garbage.
 *
 * The real payload is behind `DataTransfer.items` + `webkitGetAsEntry()`, which
 * exposes the FileSystem entry tree and lets us walk directories. This module is
 * the single place that walk lives — every drop zone in the app goes through it.
 */

/** One real file from a drop, with its path RELATIVE to the drop (a file dropped
 * on its own is just its name; a file inside a dropped folder is prefixed with
 * that folder, e.g. `my-skill/SKILL.md`). */
export interface DroppedFile {
  file: File
  path: string
}

/** One top-level dropped item, kept whole so callers can tell a folder drop from
 * a file drop (a skill bundle is a folder; the folder's name names the skill). */
export interface DroppedEntry {
  name: string
  isDirectory: boolean
  files: DroppedFile[]
}

async function readEntry(
  entry: FileSystemEntry,
  basePath: string,
  out: DroppedFile[]
): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject)
    ).catch(() => null)
    if (file) out.push({ file, path: basePath + file.name })
    return
  }
  if (!entry.isDirectory) return
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  let batch: FileSystemEntry[] = []
  // readEntries hands back at most ~100 entries per call — loop until it's dry.
  do {
    batch = await new Promise<FileSystemEntry[]>((resolve) =>
      reader.readEntries(resolve, () => resolve([]))
    )
    for (const child of batch)
      await readEntry(child, `${basePath}${entry.name}/`, out)
  } while (batch.length > 0)
}

/** Every top-level dropped item with its files, directories walked recursively.
 *
 * Falls back to `getAsFile()` for browsers/items without the entry API, where a
 * directory simply cannot be distinguished — it is then reported as a file, which
 * is the best that platform allows. */
export async function collectDroppedEntries(
  dataTransfer: DataTransfer
): Promise<DroppedEntry[]> {
  const entries: DroppedEntry[] = []
  // Snapshot first: the items list is neutered once we await.
  const handles = Array.from(dataTransfer.items)
    .filter((item) => item.kind === 'file')
    .map((item) => ({
      entry: item.webkitGetAsEntry?.() ?? null,
      file: item.getAsFile()
    }))
  for (const { entry, file } of handles) {
    if (entry) {
      const files: DroppedFile[] = []
      await readEntry(entry, '', files)
      entries.push({
        name: entry.name,
        isDirectory: !!entry.isDirectory,
        files
      })
    } else if (file) {
      entries.push({
        name: file.name,
        isDirectory: false,
        files: [{ file, path: file.name }]
      })
    }
  }
  return entries
}

/** Flat list of the real files in a drop — folders contribute their contents
 * with folder-prefixed paths. For drop zones that just want "the files". */
export async function collectDroppedFiles(
  dataTransfer: DataTransfer
): Promise<DroppedFile[]> {
  const entries = await collectDroppedEntries(dataTransfer)
  return entries.flatMap((entry) => entry.files)
}
