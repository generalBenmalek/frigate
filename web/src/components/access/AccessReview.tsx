import axios from "axios";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  LuCheck,
  LuChevronLeft,
  LuChevronRight,
  LuPlay,
  LuSave,
  LuSearch,
  LuX,
} from "react-icons/lu";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAccessReview } from "@/hooks/use-access-review";
import {
  emptyAccessReviewFilters,
  type AccessClassification,
  type AccessEvent,
  type AccessReviewFilters,
  type AccessReviewHistory,
} from "@/types/accessController";
import { accessReviewParams } from "@/utils/accessReview";
import { formatUnixTimestampToDateTime } from "@/utils/dateUtil";

const statuses: AccessClassification[] = ["warning", "valid", "unknown"];
const statusClasses: Record<string, string> = {
  valid: "text-emerald-500",
  warning: "text-amber-500",
  unknown: "text-muted-foreground",
  pending: "text-blue-500",
  unverified: "text-blue-500",
};

type Props = {
  controllers: { id: string; name: string }[];
  cameras: { value: string; label: string }[];
  timezone: string;
  onViewFootage: (event: AccessEvent) => void;
};

export default function AccessReview({
  controllers,
  cameras,
  timezone,
  onViewFootage,
}: Props) {
  const { t } = useTranslation("views/organization");
  const [draft, setDraft] = useState<AccessReviewFilters>({
    ...emptyAccessReviewFilters,
  });
  const [filters, setFilters] = useState<AccessReviewFilters>({
    ...emptyAccessReviewFilters,
  });
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [classification, setClassification] =
    useState<AccessClassification>("valid");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const {
    data,
    error: loadError,
    isLoading,
    mutate,
  } = useAccessReview(filters, timezone, page);
  const selected = data?.events.find((event) => event.id === selectedId);
  const {
    data: history,
    error: historyError,
    mutate: refreshHistory,
  } = useSWR<AccessReviewHistory[]>(
    selected
      ? `access-controllers/events/${encodeURIComponent(selected.id)}/reviews`
      : null,
    async (url: string) => (await axios.get<AccessReviewHistory[]>(url)).data,
  );
  const machine = selected?.machine_status ?? selected?.verification_status;
  const ready =
    machine !== undefined && statuses.includes(machine as AccessClassification);
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / 50));

  useEffect(() => {
    if (data && page > Math.max(1, Math.ceil(data.total / 50))) {
      setPage(Math.max(1, Math.ceil(data.total / 50)));
    }
  }, [data, page]);
  useEffect(() => {
    const status = selected?.effective_status;
    if (status && statuses.includes(status as AccessClassification)) {
      setClassification(status as AccessClassification);
    }
  }, [selected?.id, selected?.effective_status, selected?.review_revision]);

  const formatTime = (timestamp: number) =>
    formatUnixTimestampToDateTime(timestamp, {
      timezone: timezone.replace(/^UTC(?=[+-])/, ""),
      date_format: "yyyy-MM-dd HH:mm:ss",
    });
  const apply = () => {
    try {
      accessReviewParams(draft, timezone, 1);
      setError(null);
      setFilters({ ...draft });
      setPage(1);
      setSelectedId(null);
    } catch {
      setError("events.invalidRange");
    }
  };
  const submit = async (action: "confirm" | "correct") => {
    if (!selected || !ready || saving) return;
    setSaving(true);
    setError(null);
    try {
      await axios.post(
        `access-controllers/events/${encodeURIComponent(selected.id)}/review`,
        {
          action,
          expected_revision: selected.review_revision ?? 0,
          ...(action === "correct" ? { classification } : {}),
        },
      );
      await Promise.all([mutate(), refreshHistory()]);
    } catch (reviewError) {
      const reason = axios.isAxiosError(reviewError)
        ? reviewError.response?.data?.reason
        : undefined;
      setError(
        reason === "review_conflict"
          ? "review.conflict"
          : reason === "event_not_ready"
            ? "review.notReady"
            : "review.saveFailed",
      );
      if (reason === "review_conflict" || reason === "event_not_ready")
        await mutate();
    } finally {
      setSaving(false);
    }
  };
  const selectFilter = (
    key: "deviceId" | "camera" | "reviewed" | "source",
    label: string,
    options: { value: string; label: string }[],
  ) => (
    <div className="min-w-0 space-y-1">
      <label htmlFor={`review-${key}`} className="text-sm">
        {label}
      </label>
      <Select
        value={draft[key] || "all"}
        onValueChange={(value) =>
          setDraft({
            ...draft,
            [key]: value === "all" && key !== "reviewed" ? "" : value,
          })
        }
      >
        <SelectTrigger id={`review-${key}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <div className="space-y-4">
      <form
        className="grid grid-cols-1 items-end gap-3 border-b pb-4 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          apply();
        }}
      >
        {selectFilter("deviceId", t("events.table.device"), [
          { value: "all", label: t("events.all") },
          ...controllers.map((controller) => ({
            value: controller.id,
            label: controller.name || controller.id,
          })),
        ])}
        {selectFilter("reviewed", t("review.reviewState"), [
          { value: "unreviewed", label: t("review.unreviewed") },
          { value: "reviewed", label: t("review.reviewed") },
          { value: "all", label: t("events.filters.all") },
        ])}
        {selectFilter("camera", t("review.camera"), [
          { value: "all", label: t("events.filters.all") },
          ...cameras,
        ])}
        {selectFilter("source", t("review.source"), [
          { value: "all", label: t("events.filters.all") },
          { value: "controller", label: t("review.sources.controller") },
          {
            value: "employee_portal",
            label: t("review.sources.employee_portal"),
          },
        ])}
        {(
          [
            ["start", "events.filters.from", "datetime-local"],
            ["end", "events.filters.to", "datetime-local"],
            ["name", "events.filters.name", "text"],
            ["userId", "events.filters.userId", "text"],
            ["doorId", "review.doorId", "text"],
            ["cardNo", "events.filters.cardNo", "text"],
          ] as const
        ).map(([key, label, type]) => (
          <div key={key} className="min-w-0 space-y-1">
            <label htmlFor={`review-${key}`} className="text-sm">
              {t(label)}
            </label>
            <Input
              id={`review-${key}`}
              type={type}
              step={type === "datetime-local" ? 1 : undefined}
              value={draft[key]}
              onChange={(event) =>
                setDraft({ ...draft, [key]: event.target.value })
              }
            />
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={isLoading}>
            <LuSearch className="mr-2 size-4" />
            {t("events.search")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setDraft({ ...emptyAccessReviewFilters });
              setFilters({ ...emptyAccessReviewFilters });
              setPage(1);
              setSelectedId(null);
              setError(null);
            }}
          >
            <LuX className="mr-2 size-4" />
            {t("events.clear")}
          </Button>
        </div>
      </form>
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label={t("review.classification")}
      >
        {(["all", ...statuses, "pending"] as const).map((status) => (
          <Button
            key={status}
            variant={
              (filters.classification || "all") === status
                ? "default"
                : "outline"
            }
            aria-pressed={(filters.classification || "all") === status}
            onClick={() => {
              const value = status === "all" ? "" : status;
              setFilters({ ...filters, classification: value });
              setDraft({ ...draft, classification: value });
              setPage(1);
              setSelectedId(null);
              setError(null);
            }}
          >
            {status === "all"
              ? t("events.filters.all")
              : t(`verification.${status}`)}
            <span className="ml-2 tabular-nums">
              {data?.counts[status] ?? 0}
            </span>
          </Button>
        ))}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {t(error)}
        </p>
      )}
      {loadError && (
        <p role="alert" className="text-sm text-destructive">
          {t("review.loadFailed")}
          <Button variant="ghost" onClick={() => void mutate()}>
            {t("footage.retry")}
          </Button>
        </p>
      )}
      <div className="border">
        <Table containerClassName="scrollbar-container max-h-[55dvh] overflow-auto">
          <TableHeader className="sticky top-0 bg-background">
            <TableRow>
              {["name", "userId", "time", "device", "door", "verification"].map(
                (key) => (
                  <TableHead key={key} className="whitespace-nowrap">
                    {t(`events.table.${key}`)}
                  </TableHead>
                ),
              )}
              <TableHead>{t("review.reviewState")}</TableHead>
              <TableHead>{t("review.source")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading || !data?.events.length ? (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center">
                  {isLoading ? t("events.loading") : t("review.empty")}
                </TableCell>
              </TableRow>
            ) : (
              data.events.map((event) => (
                <TableRow
                  key={event.id}
                  tabIndex={0}
                  aria-selected={event.id === selectedId}
                  className={`cursor-pointer ${event.id === selectedId ? "bg-muted" : ""}`}
                  onClick={() => {
                    setSelectedId(event.id);
                    setError(null);
                  }}
                  onKeyDown={(key) => {
                    if (key.key === "Enter" || key.key === " ") {
                      key.preventDefault();
                      setSelectedId(event.id);
                      setError(null);
                    }
                  }}
                >
                  <TableCell>{event.user_name || "-"}</TableCell>
                  <TableCell>{event.user_id ?? "-"}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatTime(event.timestamp)}
                  </TableCell>
                  <TableCell>{event.device_name || event.device_id}</TableCell>
                  <TableCell>
                    {event.door_id != null &&
                    Number.isFinite(Number(event.door_id))
                      ? t("events.door", { number: Number(event.door_id) + 1 })
                      : (event.door_id ?? "-")}
                  </TableCell>
                  <TableCell
                    className={
                      statusClasses[event.effective_status ?? "pending"]
                    }
                  >
                    {t(`verification.${event.effective_status ?? "pending"}`)}
                  </TableCell>
                  <TableCell>
                    {t(
                      event.reviewed ? "review.reviewed" : "review.unreviewed",
                    )}
                  </TableCell>
                  <TableCell>
                    {t(`review.sources.${event.source ?? "controller"}`)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span aria-live="polite">
          {t("review.pagination", { page, pages, count: data?.total ?? 0 })}
        </span>
        <div className="flex gap-2">
          <Button
            size="icon"
            variant="outline"
            title={t("review.previous")}
            aria-label={t("review.previous")}
            disabled={page === 1 || isLoading}
            onClick={() => {
              setPage(page - 1);
              setSelectedId(null);
            }}
          >
            <LuChevronLeft className="size-4" />
          </Button>
          <Button
            size="icon"
            variant="outline"
            title={t("review.next")}
            aria-label={t("review.next")}
            disabled={page >= pages || isLoading}
            onClick={() => {
              setPage(page + 1);
              setSelectedId(null);
            }}
          >
            <LuChevronRight className="size-4" />
          </Button>
        </div>
      </div>
      {selected && (
        <section
          className="space-y-4 border-t pt-4"
          aria-label={t("review.decision")}
        >
          <h2 className="text-lg font-semibold">
            {selected.user_name || selected.user_id || "-"}
          </h2>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-sm text-muted-foreground">
                {t("review.machineStatus")}
              </dt>
              <dd className={statusClasses[machine ?? "pending"]}>
                {t(`verification.${machine ?? "pending"}`)}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">
                {t("review.finalStatus")}
              </dt>
              <dd
                className={
                  statusClasses[selected.effective_status ?? "pending"]
                }
              >
                {t(`verification.${selected.effective_status ?? "pending"}`)}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">
                {t("review.reviewedBy")}
              </dt>
              <dd>{selected.reviewed_by || "-"}</dd>
            </div>
            <div>
              <dt className="text-sm text-muted-foreground">
                {t("review.reviewedAt")}
              </dt>
              <dd>
                {selected.reviewed_at ? formatTime(selected.reviewed_at) : "-"}
              </dd>
            </div>
          </dl>
          {selected.verification_reason && (
            <p className="text-sm text-muted-foreground">
              {t(`verification.reasons.${selected.verification_reason}`)}
            </p>
          )}
          <Button variant="outline" onClick={() => onViewFootage(selected)}>
            <LuPlay className="mr-2 size-4" />
            {t("button.viewFootage")}
          </Button>
          <div className="flex flex-wrap items-end gap-3">
            <Button
              disabled={!ready || saving}
              onClick={() => void submit("confirm")}
            >
              <LuCheck className="mr-2 size-4" />
              {t("review.confirm")}
            </Button>
            <div className="space-y-1">
              <label htmlFor="review-classification" className="text-sm">
                {t("review.classification")}
              </label>
              <Select
                value={classification}
                disabled={!ready || saving}
                onValueChange={(value) =>
                  setClassification(value as AccessClassification)
                }
              >
                <SelectTrigger id="review-classification" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {statuses.map((status) => (
                    <SelectItem key={status} value={status}>
                      {t(`verification.${status}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              variant="outline"
              disabled={!ready || saving}
              onClick={() => void submit("correct")}
            >
              <LuSave className="mr-2 size-4" />
              {saving ? t("review.saving") : t("review.submit")}
            </Button>
          </div>
          {!ready && (
            <p role="status" className="text-sm text-muted-foreground">
              {t("review.processing")}
            </p>
          )}
          <details>
            <summary className="cursor-pointer text-sm">
              {t("review.history")}
            </summary>
            {historyError && (
              <p role="alert" className="text-sm text-destructive">
                {t("review.historyFailed")}
              </p>
            )}
            <ul className="mt-2 space-y-2 text-sm">
              {history?.map((item) => (
                <li
                  key={item.revision}
                  className="flex flex-wrap gap-x-3 gap-y-1 border-b py-2"
                >
                  <span>{formatTime(item.reviewed_at)}</span>
                  <span>{item.reviewer}</span>
                  <span>{t(`review.actions.${item.action}`)}</span>
                  <span>
                    {t("review.transition", {
                      previous: t(`verification.${item.previous_status}`),
                      status: t(`verification.${item.status}`),
                    })}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </div>
  );
}
