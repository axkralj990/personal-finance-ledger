import type { StagedRowPatch, StagedTransaction } from "../../api/types";
import type { SaveState } from "./row-state";

export type StagedChanges = Omit<Partial<StagedRowPatch>, "id" | "expectedRevision">;

interface QueueEntry {
  revision: number;
  queued: StagedChanges;
  unsaved: StagedChanges;
  running: boolean;
}

interface QueueOptions {
  save: (patch: StagedRowPatch) => Promise<StagedTransaction>;
  onSaved: (row: StagedTransaction) => void;
  onState: (id: string, state: SaveState, pending: StagedChanges) => void;
  onConflict: (id: string, pending: StagedChanges) => Promise<number | null>;
}

export function mergeStagedChanges(current: StagedChanges, next: StagedChanges): StagedChanges {
  const merged = { ...current, ...next };
  if (next.categoryId !== undefined && next.subcategoryId === undefined) merged.subcategoryId = null;
  return merged;
}

export class RowSaveQueue {
  private readonly entries = new Map<string, QueueEntry>();

  constructor(private readonly options: QueueOptions) {}

  enqueue(id: string, revision: number, changes: StagedChanges): void {
    const entry = this.entries.get(id) ?? { revision, queued: {}, unsaved: {}, running: false };
    if (!entry.running) entry.revision = revision;
    entry.queued = mergeStagedChanges(entry.queued, changes);
    entry.unsaved = mergeStagedChanges(entry.unsaved, changes);
    this.entries.set(id, entry);
    this.options.onState(id, "SAVING", entry.unsaved);
    if (!entry.running) void this.drain(id, entry);
  }

  retry(id: string, revision: number): void {
    const entry = this.entries.get(id);
    if (!entry || entry.running || !Object.keys(entry.unsaved).length) return;
    entry.revision = revision;
    entry.queued = entry.unsaved;
    this.options.onState(id, "SAVING", entry.unsaved);
    void this.drain(id, entry);
  }

  pending(id: string): StagedChanges {
    return this.entries.get(id)?.unsaved ?? {};
  }

  private async drain(id: string, entry: QueueEntry): Promise<void> {
    entry.running = true;
    while (Object.keys(entry.queued).length) {
      const operation = entry.queued;
      entry.queued = {};
      try {
        const saved = await this.options.save({ id, expectedRevision: entry.revision, ...operation });
        entry.revision = saved.revision;
        for (const key of Object.keys(operation) as (keyof StagedChanges)[]) {
          if (entry.unsaved[key] === operation[key]) delete entry.unsaved[key];
        }
        this.options.onSaved(saved);
      } catch (error) {
        entry.queued = mergeStagedChanges(operation, entry.queued);
        if (error instanceof Error && "status" in error && error.status === 409) {
          const revision = await this.options.onConflict(id, entry.unsaved);
          if (revision !== null) entry.revision = revision;
          this.options.onState(id, "CONFLICT", entry.unsaved);
        } else {
          this.options.onState(id, "ERROR", entry.unsaved);
        }
        entry.running = false;
        return;
      }
    }
    entry.running = false;
    this.options.onState(id, "SAVED", entry.unsaved);
  }
}
