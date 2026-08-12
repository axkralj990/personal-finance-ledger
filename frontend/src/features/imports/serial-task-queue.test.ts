import { SerialTaskQueue } from "./serial-task-queue";

describe("SerialTaskQueue", () => {
  it("runs writes one at a time in submission order", async () => {
    const queue = new SerialTaskQueue();
    const events: string[] = [];
    let releaseFirst: (() => void) | undefined;
    const firstBlocked = new Promise<void>((resolve) => { releaseFirst = resolve; });

    const first = queue.run(async () => {
      events.push("first:start");
      await firstBlocked;
      events.push("first:end");
      return 1;
    });
    const second = queue.run(async () => {
      events.push("second:start");
      return 2;
    });

    await vi.waitFor(() => expect(events).toEqual(["first:start"]));
    releaseFirst?.();
    await expect(Promise.all([first, second])).resolves.toEqual([1, 2]);
    expect(events).toEqual(["first:start", "first:end", "second:start"]);
  });

  it("continues after a failed write", async () => {
    const queue = new SerialTaskQueue();
    const failed = queue.run(() => Promise.reject(new Error("synthetic failure")));
    const recovered = queue.run(() => Promise.resolve("saved"));

    await expect(failed).rejects.toThrow("synthetic failure");
    await expect(recovered).resolves.toBe("saved");
  });
});
