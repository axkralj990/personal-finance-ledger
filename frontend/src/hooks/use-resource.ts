import { useEffect, useEffectEvent, useState } from "react";

export interface ResourceState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

export function useResource<T>(loader: () => Promise<T>, key: string): ResourceState<T> {
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${key}:${attempt}`;
  const [state, setState] = useState<Omit<ResourceState<T>, "reload"> & { completedKey: string }>({
    data: null,
    error: null,
    loading: true,
    completedKey: "",
  });
  const load = useEffectEvent(loader);

  useEffect(() => {
    let active = true;
    void load().then(
      (data) => active && setState({ data, error: null, loading: false, completedKey: requestKey }),
      (error: unknown) => active && setState({ data: null, error: error instanceof Error ? error : new Error("Request failed"), loading: false, completedKey: requestKey }),
    );
    return () => {
      active = false;
    };
  }, [requestKey]);

  return {
    data: state.completedKey === requestKey ? state.data : null,
    error: state.completedKey === requestKey ? state.error : null,
    loading: state.completedKey !== requestKey || state.loading,
    reload: () => setAttempt((value) => value + 1),
  };
}
