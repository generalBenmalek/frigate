import { useTranslation } from "react-i18next";
import { LuPlay } from "react-icons/lu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { AccessEvent, AccessEventFilters } from "@/types/accessController";
import { formatUnixTimestampToDateTime } from "@/utils/dateUtil";

type Props = {
  events: AccessEvent[];
  controllers: { id: string; name: string }[];
  deviceId: string;
  onDeviceChange: (id: string) => void;
  filters: AccessEventFilters;
  onFiltersChange: (filters: AccessEventFilters) => void;
  onSearch: () => void;
  onClear: () => void;
  loading: boolean;
  historyWarning: boolean;
  connectionState: string;
  timezone: string;
  selectedEventId: string | null;
  onSelectEvent: (id: string) => void;
  onViewFootage: (event: AccessEvent) => void;
};

export default function AccessEvents({
  events, controllers, deviceId, onDeviceChange, filters, onFiltersChange,
  onSearch, onClear, loading, historyWarning, connectionState, timezone,
  selectedEventId, onSelectEvent, onViewFootage,
}: Props) {
  const { t } = useTranslation("views/organization");
  const selected = events.find((event) => event.id === selectedEventId);
  const formatTime = (event: AccessEvent) => formatUnixTimestampToDateTime(event.timestamp, {
    timezone: timezone.replace(/^UTC(?=[+-])/, ""), date_format: "yyyy-MM-dd HH:mm:ss",
  });
  const fieldLabels = [
    { key: "start", label: t("events.filters.from"), type: "datetime-local" },
    { key: "end", label: t("events.filters.to"), type: "datetime-local" },
    { key: "name", label: t("events.filters.name"), type: "text" },
    { key: "userId", label: t("events.filters.userId"), type: "text" },
    { key: "cardNo", label: t("events.filters.cardNo"), type: "text" },
  ] as const;
  const headings = [
    t("events.table.name"), t("events.table.userId"), t("events.table.time"),
    t("events.table.status"), t("events.table.description"), t("events.table.door"),
    t("events.table.readerId"), t("events.table.cardNo"), t("events.table.type"),
    t("events.table.verifyMode"), t("events.table.method"), t("events.table.errorCode"),
  ];
  const verificationClasses: Record<string, string> = {
    valid: "text-emerald-500", warning: "text-amber-500", unknown: "text-slate-400",
    pending: "text-blue-400", unverified: "text-muted-foreground",
  };
  const verifyMode = (event: AccessEvent) => {
    if (event.verify_mode !== null && event.verify_mode !== undefined && event.verify_mode !== "") {
      return String(event.verify_mode);
    }
    const method = String(event.authentication_method ?? "");
    const modes: Record<string, string> = {
      "0": t("events.methods.password"), "1": t("events.methods.fingerprint"),
      "2": t("events.methods.card"), "3": t("events.methods.face"),
      "10": t("events.methods.card"), "11": t("events.methods.multiCard"),
    };
    return modes[method] ?? (method ? t("events.methods.unknown", { method }) : "-");
  };
  const description = (event: AccessEvent) => {
    if (event.status === "Failed") {
      return event.error_code !== null && event.error_code !== undefined && Number(event.error_code) !== 0
        ? t("events.descriptions.deniedError", { code: event.error_code })
        : t("events.descriptions.denied");
    }
    if (event.status !== "OK") return t("events.descriptions.event");
    if (event.type?.toLowerCase() === "entry") return t("events.descriptions.entry");
    if (event.type?.toLowerCase() === "exit") return t("events.descriptions.exit");
    return t("events.descriptions.granted");
  };

  return (
    <div className="space-y-4">
      <form className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4" onSubmit={(event) => { event.preventDefault(); onSearch(); }}>
        <div className="space-y-1">
          <label className="text-sm" htmlFor="access-controller-filter">{t("events.filter")}</label>
          <Select value={deviceId} onValueChange={onDeviceChange}>
            <SelectTrigger id="access-controller-filter" className="w-[200px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("events.all")}</SelectItem>
              {controllers.map((controller) => <SelectItem key={controller.id} value={controller.id}>{controller.name || controller.id}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        {fieldLabels.map(({ key, label, type }) => (
          <div className="space-y-1" key={key}>
            <label htmlFor={`access-${key}`} className="text-sm">{label}</label>
            <Input id={`access-${key}`} type={type} value={filters[key]} className={type === "text" ? "w-36" : "w-52"}
              onChange={(event) => onFiltersChange({ ...filters, [key]: event.target.value })} />
          </div>
        ))}
        <div className="space-y-1">
          <label className="text-sm" htmlFor="access-status">{t("events.filters.status")}</label>
          <Select value={filters.status || "all"} onValueChange={(value) => onFiltersChange({ ...filters, status: value === "all" ? "" : value as "OK" | "Failed" })}>
            <SelectTrigger id="access-status" className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("events.filters.all")}</SelectItem>
              <SelectItem value="OK">{t("events.results.OK")}</SelectItem>
              <SelectItem value="Failed">{t("events.results.Failed")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button type="submit" disabled={loading}>{t("events.search")}</Button>
        <Button type="button" variant="outline" onClick={onClear}>{t("events.clear")}</Button>
      </form>
      <div className="flex flex-wrap justify-between gap-2 text-sm text-muted-foreground" aria-live="polite">
        <span>{loading ? t("events.loading") : t("events.count", { count: events.length })}</span>
        <span>{t("events.newestFirst")}</span>
        <span className={connectionState === "live" ? "text-emerald-500" : "text-amber-500"}>
          {connectionState === "live" ? t("events.connection.live") : connectionState === "connecting" ? t("events.connection.connecting") : t("events.connection.reconnecting")}
        </span>
      </div>
      {historyWarning && <p role="status" className="text-sm text-amber-500">{t("events.historyWarning")}</p>}
      <div className="rounded-lg border bg-card">
        <Table className="min-w-[1200px]" containerClassName="scrollbar-container max-h-[60dvh] overflow-auto">
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow>{headings.map((heading, index) => <TableHead key={index} className="whitespace-nowrap">{heading}</TableHead>)}</TableRow>
          </TableHeader>
          <TableBody>
            {events.length === 0 ? <TableRow><TableCell colSpan={12} className="py-8 text-center text-muted-foreground">{t("events.empty")}</TableCell></TableRow> :
              events.map((event) => (
                <TableRow key={event.id} tabIndex={0} aria-selected={event.id === selectedEventId}
                  aria-label={t("events.selectEvent", { name: event.user_name || event.card_number || "-", time: formatTime(event) })}
                  className={`cursor-pointer whitespace-nowrap ${event.id === selectedEventId ? "bg-muted" : ""}`}
                  onClick={() => onSelectEvent(event.id)}
                  onKeyDown={(keyEvent) => { if (keyEvent.key === "Enter" || keyEvent.key === " ") { keyEvent.preventDefault(); onSelectEvent(event.id); } }}>
                  <TableCell>{event.user_name || "-"}</TableCell>
                  <TableCell>{event.user_id ?? "-"}</TableCell>
                  <TableCell>{formatTime(event)}</TableCell>
                  <TableCell><span className={`rounded-full px-2 py-1 text-xs ${event.status === "OK" ? "bg-emerald-500/10 text-emerald-500" : event.status === "Failed" ? "bg-red-500/10 text-red-500" : "text-muted-foreground"}`}>{event.status === "OK" ? t("events.results.OK") : event.status === "Failed" ? t("events.results.Failed") : event.status}</span></TableCell>
                  <TableCell>{description(event)}</TableCell>
                  <TableCell>{event.door_id !== null && event.door_id !== undefined && Number.isFinite(Number(event.door_id)) ? t("events.door", { number: Number(event.door_id) + 1 }) : "-"}</TableCell>
                  <TableCell>{event.reader_id ?? "-"}</TableCell>
                  <TableCell>{event.card_number || "-"}</TableCell>
                  <TableCell>{event.type || "-"}</TableCell>
                  <TableCell>{verifyMode(event)}</TableCell>
                  <TableCell>{event.authentication_method ?? "-"}</TableCell>
                  <TableCell>{event.error_code ?? "-"}</TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
      <section className="space-y-3 rounded-lg border bg-card p-4" aria-label={t("events.selected.title")}>
        <h2 className="font-semibold">{t("events.selected.title")}</h2>
        {selected ? <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-sm text-muted-foreground">{t("events.table.device")}</dt><dd>{selected.device_name || selected.device_id}</dd></div>
            <div><dt className="text-sm text-muted-foreground">{t("events.table.owners")}</dt><dd>{selected.owner_names?.join(", ") || "-"}</dd></div>
            <div><dt className="text-sm text-muted-foreground">{t("events.table.people")}</dt><dd>{selected.people?.map((person) => person.name).join(", ") || "-"}</dd></div>
            <div><dt className="text-sm text-muted-foreground">{t("events.table.verification")}</dt><dd className={verificationClasses[selected.verification_status ?? "unverified"]}>{t(`verification.${selected.verification_status ?? "unverified"}`)}</dd></div>
          </dl>
          <Button variant="outline" disabled={!selected.camera || selected.clip_start === undefined || selected.clip_end === undefined} onClick={() => onViewFootage(selected)}>
            <LuPlay className="mr-2 size-4" />{t("button.viewFootage")}
          </Button>
          <details><summary className="cursor-pointer text-sm">{t("events.table.details")}</summary>
            <pre className="scrollbar-container mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(selected.raw ?? selected, null, 2)}</pre>
          </details>
        </> : <p className="text-sm text-muted-foreground">{t("events.selected.empty")}</p>}
      </section>
    </div>
  );
}
