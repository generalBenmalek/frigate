import axios from "axios";
import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { useWsConnectionState, useWsMessageSubscribe } from "@/api/ws";
import type {
  AccessReviewFilters,
  AccessReviewResult,
} from "@/types/accessController";
import { accessReviewParams } from "@/utils/accessReview";

export function useAccessReview(
  filters: AccessReviewFilters,
  timezone: string,
  page: number,
) {
  const params = useMemo(
    () => accessReviewParams(filters, timezone, page),
    [filters, timezone, page],
  );
  const result = useSWR<AccessReviewResult>(
    ["access-controllers/events/review", params],
    async ([url, query]) =>
      (await axios.get<AccessReviewResult>(url, { params: query })).data,
    { revalidateOnFocus: true },
  );
  const { mutate } = result;
  const connection = useWsConnectionState();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (connection === "live") void mutate();
  }, [connection, mutate]);
  useEffect(() => () => clearTimeout(timer.current), []);

  useWsMessageSubscribe((message) => {
    if (message.topic !== "access_controller_events" || timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      void mutate();
    }, 300);
  });
  return result;
}
