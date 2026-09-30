import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useWsConnectionState, useWsMessageSubscribe } from "@/api/ws";
import type { AccessEvent, AccessEventFilters } from "@/types/accessController";
import { accessFilterTimestamp, matchesAccessEvent, mergeAccessEvents } from "@/utils/accessController";

type HistoryResult = { device_id: string; success: boolean; incomplete?: boolean };

export function useAccessControllerEvents(
  deviceId: string, filters: AccessEventFilters, timezone: string,
  controllerKey: string, enabled: boolean,
) {
  const [events, setEvents] = useState<AccessEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>();
  const [historyWarning, setHistoryWarning] = useState(false);
  const [streamStates, setStreamStates] = useState<Record<string, string>>({});
  const socketState = useWsConnectionState();
  const controllerIds = useMemo(() => new Set(JSON.parse(controllerKey) as string[]), [controllerKey]);
  const request = useRef<AbortController | null>(null);
  const buffered = useRef(new Map<string, AccessEvent>());

  const refreshEvents = useCallback(async () => {
    request.current?.abort();
    const current = new AbortController();
    request.current = current;
    buffered.current.clear();
    setLoading(true);
    setError(undefined);
    setHistoryWarning(false);
    try {
      const start = accessFilterTimestamp(filters.start, timezone);
      const end = accessFilterTimestamp(filters.end, timezone);
      const bounds = {
        ...(start !== undefined ? { start: new Date(start * 1000).toISOString() } : {}),
        ...(end !== undefined ? { end: new Date(end * 1000).toISOString() } : {}),
        ...(deviceId !== "all" ? { device_id: deviceId } : {}),
      };
      const params = {
        ...bounds, name: filters.name || undefined, user_id: filters.userId || undefined,
        card_no: filters.cardNo || undefined, status: filters.status || undefined, count: 500,
      };
      const loadStored = async () => {
        const { data } = await axios.get<AccessEvent[]>("access-controllers/events", {
          signal: current.signal, params,
        });
        if (current.signal.aborted) return;
        setEvents(mergeAccessEvents(data, [...buffered.current.values()]).filter(
          (event) => matchesAccessEvent(event, deviceId, filters, timezone),
        ));
      };
      await loadStored();
      if (current.signal.aborted) return;
      if (controllerKey !== "[]") {
        try {
          const { data } = await axios.post<{ results: HistoryResult[] }>(
            "access-controllers/events/sync", { ...bounds, timezone, count: 500 }, { signal: current.signal },
          );
          if (current.signal.aborted) return;
          setHistoryWarning(data.results.some((result) => !result.success || result.incomplete));
        } catch {
          if (current.signal.aborted) return;
          setHistoryWarning(true);
        }
        await loadStored();
      }
    } catch (loadError) {
      if (!current.signal.aborted) setError(loadError);
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }, [controllerKey, deviceId, filters, timezone]);

  useEffect(() => {
    setEvents([]);
    if (enabled) void refreshEvents();
    return () => request.current?.abort();
  }, [enabled, refreshEvents]);

  const previousSocketState = useRef(socketState);
  useEffect(() => {
    if (socketState !== "live") setStreamStates({});
    if (enabled && socketState === "live" && previousSocketState.current !== "live") {
      void refreshEvents();
    }
    previousSocketState.current = socketState;
  }, [enabled, refreshEvents, socketState]);

  useWsMessageSubscribe((message) => {
    if (message.topic !== "access_controller_events" && message.topic !== "access_controller_status") return;
    let payload: unknown = message.payload;
    if (typeof payload === "string") {
      try { payload = JSON.parse(payload); } catch { return; }
    }
    if (!payload || typeof payload !== "object") return;
    if (message.topic === "access_controller_status") {
      const status = payload as { device_id?: string; state?: string };
      if (typeof status.device_id === "string" && typeof status.state === "string") {
        const id = status.device_id;
        const state = status.state;
        setStreamStates((current) => ({ ...current, [id]: state }));
      }
      return;
    }
    const event = payload as AccessEvent;
    if (typeof event.id !== "string" || typeof event.device_id !== "string" || !Number.isFinite(event.timestamp)) return;
    if (!controllerIds.has(event.device_id)) return;
    if (!matchesAccessEvent(event, deviceId, filters, timezone)) {
      buffered.current.delete(event.id);
      setEvents((current) => current.filter((item) => item.id !== event.id));
      return;
    }
    buffered.current.set(event.id, event);
    if (buffered.current.size > 500) {
      buffered.current = new Map(mergeAccessEvents([...buffered.current.values()]).map((item) => [item.id, item]));
    }
    setEvents((current) => mergeAccessEvents(current, [event]));
  });

  return { events, refreshEvents, loading, error, historyWarning, streamStates, socketState };
}
