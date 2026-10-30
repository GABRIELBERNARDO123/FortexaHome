import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "./api";

export function useApiData<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const previousPath = useRef<string | null>(path);

  const reload = useCallback(() => setVersion((current) => current + 1), []);

  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      return;
    }
    let active = true;
    const controller = new AbortController();
    if (previousPath.current !== path) {
      setData(null);
      previousPath.current = path;
    }
    setLoading(true);
    setError(null);

    api<T>(path, { signal: controller.signal })
      .then((result) => {
        if (!active) return;
        setData(result);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [path, version]);

  return { data, loading, error, reload, setData };
}
