import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { EmployeeAccessOption, EmployeeAccessResult, EmployeeSession } from "@/types/employee";

class PortalError extends Error {
  constructor(public reason: string, public status: number) {
    super(reason);
  }
}

async function portalRequest<T>(path: string, csrf?: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/employee/${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: body === undefined ? {} : {
      "Content-Type": "application/json",
      "X-CSRF-TOKEN": csrf ?? "",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new PortalError(data.reason ?? "verification_failed", response.status);
  return data as T;
}

export default function EmployeePortal() {
  const { t } = useTranslation("views/employeePortal");
  const [session, setSession] = useState<EmployeeSession>();
  const [options, setOptions] = useState<EmployeeAccessOption[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [camera, setCamera] = useState("");
  const [controller, setController] = useState("");
  const [door, setDoor] = useState("");
  const [selecting, setSelecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [countdown, setCountdown] = useState(10);
  const [result, setResult] = useState<EmployeeAccessResult>();
  const [error, setError] = useState("");
  const [optionsLoading, setOptionsLoading] = useState(false);

  useEffect(() => { document.title = t("title"); }, [t]);

  const refreshSession = useCallback(async () => {
    try {
      const current = await portalRequest<EmployeeSession>("session");
      setSession(current);
      if (!current.authenticated) {
        setOptions([]);
        setSelecting(false);
      }
    } catch {
      setError("service_unavailable");
    }
  }, []);

  useEffect(() => {
    void refreshSession();
    const timer = window.setInterval(() => { void refreshSession(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshSession]);

  useEffect(() => {
    if (!session?.authenticated) return;
    let canceled = false;
    setOptionsLoading(true);
    portalRequest<EmployeeAccessOption[]>("options")
      .then((values) => { if (!canceled) setOptions(values); })
      .catch((failure: unknown) => {
        if (!canceled) setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
      })
      .finally(() => { if (!canceled) setOptionsLoading(false); });
    return () => { canceled = true; };
  }, [session?.authenticated, selecting]);

  async function login(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      await portalRequest("login", session.csrf_token, { username, password });
      setPassword("");
      await refreshSession();
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
    } finally { setBusy(false); }
  }

  async function logout() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      await portalRequest("logout", session.csrf_token, {});
      setSelecting(false);
      setResult(undefined);
      setCamera(""); setController(""); setDoor("");
      await refreshSession();
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
    } finally { setBusy(false); }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (!session || busy || !camera || !controller || !door) return;
    setBusy(true);
    setVerifying(true);
    setError("");
    setResult(undefined);
    setCountdown(10);
    const started = Date.now();
    const timer = window.setInterval(() => setCountdown(Math.max(0, 10 - Math.floor((Date.now() - started) / 1000))), 250);
    try {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      const requestId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
      setResult(await portalRequest<EmployeeAccessResult>("forgot-card", session.csrf_token, {
        camera, controller_id: controller, door_id: door, request_id: requestId,
      }));
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "connection_lost");
      if (failure instanceof PortalError && failure.status === 401) await refreshSession();
    } finally {
      window.clearInterval(timer);
      setVerifying(false);
      setBusy(false);
    }
  }

  const cameras = Array.from(new Set(options.map((option) => option.camera)));
  const controllers = options.filter((option) => option.camera === camera);
  const doors = controllers.find((option) => option.controller_id === controller)?.doors ?? [];
  const available = session?.enabled && session?.has_face;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-4 text-primary">
      <section className="w-full max-w-lg space-y-6 rounded-2xl border border-secondary-highlight bg-background_alt p-6 shadow-lg">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        {!session && <p role="status">{t("loading")}</p>}
        {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.verification_failed") })}</p>}
        {session && !session.authenticated && (
          <form onSubmit={login} className="space-y-4">
            <div className="space-y-2"><Label htmlFor="username">{t("username")}</Label>
              <Input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required disabled={busy} maxLength={64} /></div>
            <div className="space-y-2"><Label htmlFor="password">{t("password")}</Label>
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={busy} maxLength={1024} /></div>
            <Button type="submit" className="w-full" disabled={busy}>{t(busy ? "signingIn" : "login")}</Button>
          </form>
        )}
        {session?.authenticated && (
          <>
            <div className="flex items-center justify-between gap-4"><p>{t("welcome", { name: session.name })}</p>
              <Button variant="outline" onClick={() => void logout()} disabled={busy}>{t("logout")}</Button></div>
            {!session.enabled && <p role="status">{t("errors.system_disabled")}</p>}
            {!session.has_face && <p role="status">{t("errors.no_registered_face")}</p>}
            <Button className="w-full" disabled={!available || busy} onClick={() => { setSelecting(true); setResult(undefined); setError(""); }}>{t("forgotCard")}</Button>
            {selecting && available && (
              <form onSubmit={verify} className="space-y-4">
                <p>{t("instructions")}</p>
                {optionsLoading && <p role="status">{t("loading")}</p>}
                {!optionsLoading && options.length === 0 && <p role="status">{t("noDoors")}</p>}
                <div className="space-y-2"><Label>{t("camera")}</Label>
                  <Select value={camera} onValueChange={(value) => { setCamera(value); setController(""); setDoor(""); setResult(undefined); }} disabled={busy}>
                    <SelectTrigger aria-label={t("camera")}><SelectValue placeholder={t("selectCamera")} /></SelectTrigger>
                    <SelectContent>{cameras.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
                  </Select></div>
                <div className="space-y-2"><Label>{t("controller")}</Label>
                  <Select value={controller} onValueChange={(value) => { setController(value); setDoor(""); setResult(undefined); }} disabled={busy || !camera}>
                    <SelectTrigger aria-label={t("controller")}><SelectValue placeholder={t("selectController")} /></SelectTrigger>
                    <SelectContent>{controllers.map((option) => <SelectItem key={option.controller_id} value={option.controller_id}>{option.controller_name}</SelectItem>)}</SelectContent>
                  </Select></div>
                <div className="space-y-2"><Label>{t("door")}</Label>
                  <Select value={door} onValueChange={(value) => { setDoor(value); setResult(undefined); }} disabled={busy || !controller}>
                    <SelectTrigger aria-label={t("door")}><SelectValue placeholder={t("selectDoor")} /></SelectTrigger>
                    <SelectContent>{doors.map((option) => <SelectItem key={option.id} value={option.id}>{option.name}</SelectItem>)}</SelectContent>
                  </Select></div>
                {camera && <p>{t("faceCamera", { camera })}</p>}
                <Button type="submit" className="w-full" disabled={busy || !doors.some((option) => option.id === door)}>{t("verify")}</Button>
              </form>
            )}
            {verifying && <p role="status" aria-live="polite">{countdown > 0 ? t("verifying", { seconds: countdown }) : t("finalizing")}</p>}
            {result && <div role={result.success ? "status" : "alert"} className="space-y-2 rounded-lg border border-secondary-highlight p-4">
              {result.success ? <><p className="font-semibold">{t("verified")}</p><p>{t("continue")}</p><p>{t("unlockRequested")}</p></> :
                <>{result.identity_verified && <p>{t("verified")}</p>}<p className="text-danger">{t(`errors.${result.reason}`, { defaultValue: t("errors.verification_failed") })}</p></>}
            </div>}
          </>
        )}
      </section>
    </main>
  );
}
