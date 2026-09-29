import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { baseUrl } from "@/api/baseUrl";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { AccessEvent } from "@/types/accessController";

type Mode = "auto" | "preview" | "clip" | "snapshot";
type Media = { kind: Exclude<Mode, "auto">; url: string };

export default function AccessEventFootage({
  event, onClose,
}: { event: AccessEvent; onClose: () => void }) {
  const { t } = useTranslation("views/organization");
  const [mode, setMode] = useState<Mode>("auto");
  const [index, setIndex] = useState(0);
  const [loadedSource, setLoadedSource] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const media = useMemo(() => {
    const candidates: Media[] = [];
    if (event.camera && event.clip_start !== undefined && event.clip_end !== undefined) {
      const path = `${baseUrl}api/${encodeURIComponent(event.camera)}/start/${event.clip_start}/end/${event.clip_end}`;
      candidates.push({ kind: "preview", url: `${path}/preview.mp4` });
      candidates.push({ kind: "clip", url: `${path}/clip.mp4` });
    }
    const objectIds = [...new Set((event.people ?? [])
      .filter((person) => !person.event_id.startsWith("frame-") && !person.event_id.startsWith("recording-"))
      .map((person) => person.event_id))];
    for (const id of objectIds) {
      candidates.push({ kind: "clip", url: `${baseUrl}api/events/${encodeURIComponent(id)}/clip.mp4` });
    }
    for (const snapshot of event.snapshots ?? []) {
      candidates.push({ kind: "snapshot", url: `${baseUrl}api/${snapshot.url}` });
    }
    for (const id of objectIds) {
      candidates.push({ kind: "snapshot", url: `${baseUrl}api/events/${encodeURIComponent(id)}/snapshot.jpg` });
    }
    return mode === "auto" ? candidates : candidates.filter((candidate) => candidate.kind === mode);
  }, [event, mode]);
  const current = media[index];
  const url = current?.url;
  const mediaKey = `${url}-${attempt}`;
  const loaded = loadedSource === mediaKey;

  useEffect(() => {
    if (!url || loaded) return;
    // Media generation failures must advance rather than leave a spinner.
    const timer = setTimeout(() => setIndex((value) => value === index ? value + 1 : value), 30000);
    return () => clearTimeout(timer);
  }, [url, loaded, attempt, index]);

  const retry = () => {
    setIndex(0);
    setLoadedSource(null);
    setAttempt((value) => value + 1);
  };
  const fail = () => setIndex((value) => value === index ? value + 1 : value);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] max-w-4xl overflow-y-auto">
        <DialogHeader><DialogTitle>{t("footage.title")}</DialogTitle></DialogHeader>
        <div className="flex items-center gap-3">
          <label htmlFor="access-footage-mode">{t("footage.source")}</label>
          <Select value={mode} onValueChange={(value) => { setMode(value as Mode); retry(); }}>
            <SelectTrigger id="access-footage-mode" className="w-52"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">{t("footage.modes.auto")}</SelectItem>
              <SelectItem value="preview">{t("footage.modes.preview")}</SelectItem>
              <SelectItem value="clip">{t("footage.modes.clip")}</SelectItem>
              <SelectItem value="snapshot">{t("footage.modes.snapshot")}</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={retry}>{t("footage.retry")}</Button>
        </div>
        <p className="text-sm text-muted-foreground">{t("footage.fallbackOrder")}</p>
        {current ? <>
          {!loaded && <p role="status">{t("footage.loading")}</p>}
          <div className="flex aspect-video items-center justify-center bg-black">
            {current.kind === "snapshot" ? (
              <img key={mediaKey} src={current.url} alt={t("footage.snapshotAlt")}
                className="max-h-[60dvh] max-w-full object-contain" onLoad={() => setLoadedSource(mediaKey)} onError={fail} />
            ) : (
              <video key={mediaKey} src={current.url} controls autoPlay muted playsInline aria-label={t("footage.title")}
                className="max-h-[60dvh] w-full" onLoadedData={() => setLoadedSource(mediaKey)} onError={fail} />
            )}
          </div>
          <div className="flex items-center justify-between text-sm">
            <span>{t(`footage.modes.${current.kind}`)}</span>
            {current.kind === "snapshot" && index + 1 < media.length && (
              <Button variant="outline" onClick={fail}>{t("footage.nextSnapshot")}</Button>
            )}
          </div>
        </> : <p role="status">{t("footage.unavailable")}</p>}
      </DialogContent>
    </Dialog>
  );
}
